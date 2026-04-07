"""Agent execution engine.

Loads YAML-defined agent configs, builds system prompts from SOUL.md +
agent-specific instructions, retrieves pgvector memory context, dispatches
to the correct model provider, and persists interaction history.

Note: temperature control requires updating model_clients.py to accept the
parameter. Current clients use their internal defaults.
"""

import time
from pathlib import Path
from typing import Any

import asyncpg
import yaml

from api.core.cost_calc import compute_cost
from api.core.logging import get_logger
from api.core.memory import search_memory, store_memory
from api.core.model_clients import call_anthropic, call_ollama, call_openai, call_qwen
from api.db.queries import log_task

logger = get_logger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"

_PROVIDER_DISPATCH = {
    "anthropic": call_anthropic,
    "openai": call_openai,
    "qwen": call_qwen,
    "ollama": call_ollama,
}


def load_agent_config(agent_name: str) -> dict[str, Any]:
    """Load and parse an agent's YAML config file.

    Args:
        agent_name: Agent slug (e.g. "jake", "dame"). Must match agents/{agent_name}.yaml.

    Returns:
        Parsed YAML as a dict.

    Raises:
        FileNotFoundError: If agents/{agent_name}.yaml does not exist.
    """
    path = AGENTS_DIR / f"{agent_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No agent config found at {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_system_prompt(config: dict[str, Any]) -> str:
    """Concatenate SOUL.md with agent-specific system_prompt from YAML.

    Args:
        config: Parsed agent YAML config dict.

    Returns:
        Full system prompt string ready to pass to a model client.
    """
    soul_path = AGENTS_DIR / "SOUL.md"
    soul = soul_path.read_text(encoding="utf-8").strip() if soul_path.exists() else ""
    agent_instructions = config.get("system_prompt", "").strip()
    parts = [p for p in [soul, agent_instructions] if p]
    return "\n\n---\n\n".join(parts)


def list_agents() -> list[str]:
    """Return slugs of all agents with YAML configs in the agents/ directory.

    Returns:
        Sorted list of agent name strings (e.g. ["dame", "jake", "king", "kobe", "sam"]).
    """
    return sorted(p.stem for p in AGENTS_DIR.glob("*.yaml"))


def get_agent_info(agent_name: str) -> dict[str, Any]:
    """Return public metadata for a named agent.

    Args:
        agent_name: Agent slug.

    Returns:
        Dict with name, role, description, model, provider, tools, escalation_to.
    """
    config = load_agent_config(agent_name)
    return {
        "name": config.get("name", agent_name),
        "role": config.get("role", ""),
        "description": config.get("description", ""),
        "model": config.get("model", ""),
        "provider": config.get("provider", ""),
        "tools": config.get("tools", []),
        "escalation_to": config.get("escalation_to", ""),
    }


async def run_agent(
    agent_name: str,
    user_message: str,
    client_id: str = "internal",
    context: list[dict[str, str]] | None = None,
    conn: asyncpg.Connection | None = None,
) -> dict[str, Any]:
    """Execute a single agent turn end-to-end.

    Loads agent config, injects relevant memory into the system prompt,
    calls the model, stores the interaction in memory, and logs the task.

    Args:
        agent_name: Agent slug matching a YAML file in agents/.
        user_message: The user's input message.
        client_id: Identifier for namespace scoping and cost tracking.
        context: Optional prior conversation turns as {role, content} dicts.
        conn: asyncpg connection. Memory and logging are skipped if None.

    Returns:
        Dict with keys: agent, response, model, tokens_in, tokens_out,
        cost_usd, duration_ms.

    Raises:
        FileNotFoundError: If the agent YAML does not exist.
        ValueError: If the agent's provider is not in the dispatch table.
        RuntimeError: If the model call fails.
    """
    start = time.monotonic()
    log = logger.bind(agent=agent_name, client_id=client_id)

    config = load_agent_config(agent_name)
    model: str = config["model"]
    provider: str = config["provider"]
    max_tokens: int = config.get("max_tokens", 4000)
    agent_display_name: str = config.get("name", agent_name)

    system_prompt = build_system_prompt(config)

    # Inject top-k relevant memories as additional system context.
    if conn is not None:
        try:
            memories = await search_memory(
                agent_name=agent_name,
                query=user_message,
                conn=conn,
                client_id=client_id,
                limit=3,
            )
            if memories:
                memory_lines = "\n".join(
                    f"[{m['similarity']:.2f}] {m['content']}" for m in memories
                )
                system_prompt = system_prompt + f"\n\n## Relevant Memory\n{memory_lines}"
        except Exception as exc:
            log.warning("memory_search_skipped", error=str(exc))

    # Build message list: optional prior turns + current user message.
    messages: list[dict[str, str]] = list(context or []) + [
        {"role": "user", "content": user_message}
    ]

    caller = _PROVIDER_DISPATCH.get(provider)
    if caller is None:
        raise ValueError(f"Unknown provider '{provider}' for agent '{agent_name}'")

    log.info("agent_run_start", model=model, provider=provider, msg_chars=len(user_message))

    result = await caller(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        temperature=config.get("temperature"),
    )

    response_text: str = result["content"]
    tokens_in: int = result.get("tokens_in", 0)
    tokens_out: int = result.get("tokens_out", 0)
    cost_usd: float = compute_cost(model, tokens_in, tokens_out)
    duration_ms: int = int((time.monotonic() - start) * 1000)

    # Persist interaction as a single memory entry (user + response pair).
    if conn is not None:
        interaction = f"User: {user_message}\n{agent_display_name}: {response_text}"
        try:
            await store_memory(
                agent_name=agent_name,
                content=interaction,
                metadata={"client_id": client_id, "model": model},
                conn=conn,
                client_id=client_id,
            )
        except Exception as exc:
            log.warning("memory_store_skipped", error=str(exc))

        try:
            await log_task(
                conn=conn,
                client_id=client_id,
                agent_name=agent_name,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception as exc:
            log.warning("task_log_skipped", error=str(exc))

    log.info(
        "agent_run_complete",
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
    )

    return {
        "agent": agent_name,
        "response": response_text,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
    }
