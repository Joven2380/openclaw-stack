"""Agent execution engine.

Loads YAML-defined agent configs, builds system prompts from SOUL.md +
agent-specific instructions, retrieves pgvector memory context, dispatches
to the correct model provider, and persists interaction history.

Phase 2 Step 4: Tool execution loop — when an Anthropic model returns
tool_use blocks, we execute them via api.tools.registry and loop back
until the model produces a final text response (or hits MAX_TOOL_ROUNDS).
"""

import json
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
from api.tools.registry import TOOL_SCHEMAS, execute_tool

logger = get_logger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"

MAX_TOOL_ROUNDS = 5  # Safety cap per request

_PROVIDER_DISPATCH = {
    "anthropic": call_anthropic,
    "openai": call_openai,
    "qwen": call_qwen,
    "ollama": call_ollama,
}

# Providers that support native tool_use in responses
_TOOL_USE_PROVIDERS = {"anthropic"}


def load_agent_config(agent_name: str) -> dict[str, Any]:
    """Load and parse an agent's YAML config file."""
    path = AGENTS_DIR / f"{agent_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No agent config found at {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_system_prompt(config: dict[str, Any]) -> str:
    """Concatenate SOUL.md with agent-specific system_prompt from YAML."""
    soul_path = AGENTS_DIR / "SOUL.md"
    soul = soul_path.read_text(encoding="utf-8").strip() if soul_path.exists() else ""
    agent_instructions = config.get("system_prompt", "").strip()
    parts = [p for p in [soul, agent_instructions] if p]
    return "\n\n---\n\n".join(parts)


def list_agents() -> list[str]:
    """Return slugs of all agents with YAML configs in the agents/ directory."""
    return sorted(p.stem for p in AGENTS_DIR.glob("*.yaml"))


def get_agent_info(agent_name: str) -> dict[str, Any]:
    """Return public metadata for a named agent."""
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


def _get_tool_schemas_for_agent(config: dict[str, Any]) -> list[dict]:
    """Build Anthropic-format tool schemas for tools listed in agent YAML.

    Only includes tools that are both listed in the agent config AND
    have a schema defined in TOOL_SCHEMAS.
    """
    agent_tools = config.get("tools", [])
    if not agent_tools:
        return []

    schemas = []
    for tool_name in agent_tools:
        if tool_name in TOOL_SCHEMAS:
            schemas.append(TOOL_SCHEMAS[tool_name])
        else:
            logger.warning("tool_schema_missing", tool=tool_name,
                           hint="Add to TOOL_SCHEMAS in registry.py")
    return schemas


async def run_agent(
    agent_name: str,
    user_message: str,
    client_id: str = "internal",
    context: list[dict[str, str]] | None = None,
    conn: asyncpg.Connection | None = None,
) -> dict[str, Any]:
    """Execute a single agent turn end-to-end, with tool execution loop.

    For Anthropic providers with tools configured: if the model returns
    tool_use blocks, we execute them via the tool registry and loop back
    until a final text response or MAX_TOOL_ROUNDS is hit.

    For non-Anthropic providers (or agents with no tools): single call.

    Returns:
        Dict with keys: agent, response, model, tokens_in, tokens_out,
        cost_usd, duration_ms, tool_calls_made.
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
    messages: list[dict[str, Any]] = list(context or []) + [
        {"role": "user", "content": user_message}
    ]

    caller = _PROVIDER_DISPATCH.get(provider)
    if caller is None:
        raise ValueError(f"Unknown provider '{provider}' for agent '{agent_name}'")

    log.info("agent_run_start", model=model, provider=provider, msg_chars=len(user_message))

    # ── Decide: tool loop or single call ────────────────────────────────────
    tool_schemas = _get_tool_schemas_for_agent(config)
    use_tool_loop = provider in _TOOL_USE_PROVIDERS and len(tool_schemas) > 0

    if use_tool_loop:
        result = await _run_with_tools(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            tool_schemas=tool_schemas,
            temperature=config.get("temperature"),
            log=log,
        )
    else:
        # Single call — no tool loop
        raw = await caller(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            temperature=config.get("temperature"),
        )
        result = {
            "response_text": raw["content"],
            "tokens_in": raw.get("tokens_in", 0),
            "tokens_out": raw.get("tokens_out", 0),
            "tool_calls_made": [],
            "rounds": 1,
        }

    response_text: str = result["response_text"]
    tokens_in: int = result["tokens_in"]
    tokens_out: int = result["tokens_out"]
    tool_calls_made: list = result["tool_calls_made"]
    cost_usd: float = compute_cost(model, tokens_in, tokens_out)
    duration_ms: int = int((time.monotonic() - start) * 1000)

    # Persist interaction as a single memory entry.
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
        tool_calls=len(tool_calls_made),
        rounds=result["rounds"],
    )

    return {
        "agent": agent_name,
        "response": response_text,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
        "tool_calls_made": tool_calls_made,
    }


# ── Anthropic tool execution loop ────────────────────────────────────────────

async def _run_with_tools(
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    system_prompt: str,
    tool_schemas: list[dict],
    temperature: float | None,
    log: Any,
) -> dict[str, Any]:
    """Anthropic tool execution loop.

    Calls the model, checks for tool_use blocks, executes tools via
    registry, feeds results back, and repeats until final text or
    MAX_TOOL_ROUNDS.

    Returns dict with: response_text, tokens_in, tokens_out,
    tool_calls_made, rounds.
    """
    import anthropic
    from api.core.config import get_settings

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    total_tokens_in = 0
    total_tokens_out = 0
    tool_calls_log: list[dict] = []
    text_parts: list[str] = []  # track across rounds for max-rounds fallback

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        log.info("tool_loop_round", round=round_num, model=model)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if temperature is not None:
            kwargs["temperature"] = temperature
        if tool_schemas:
            kwargs["tools"] = tool_schemas

        response = await client.messages.create(**kwargs)

        total_tokens_in += response.usage.input_tokens
        total_tokens_out += response.usage.output_tokens

        # Parse content blocks
        text_parts = []
        tool_use_blocks: list = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        # No tool calls or model says it's done — return final text
        if not tool_use_blocks or response.stop_reason == "end_turn":
            return {
                "response_text": "\n".join(text_parts) if text_parts else "(No response)",
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
                "tool_calls_made": tool_calls_log,
                "rounds": round_num,
            }

        # Append the full assistant response to message history
        # (content blocks include both text and tool_use — Anthropic needs this)
        messages.append({
            "role": "assistant",
            "content": [_block_to_dict(b) for b in response.content],
        })

        # Execute each tool call
        tool_results: list[dict] = []

        for tool_block in tool_use_blocks:
            tool_name = tool_block.name
            tool_input = tool_block.input
            tool_use_id = tool_block.id

            log.info("tool_execute", round=round_num, tool=tool_name,
                     input_preview=json.dumps(tool_input, default=str)[:200])

            t0 = time.monotonic()
            try:
                tool_result = await execute_tool(tool_name, tool_input)
                is_error = "error" in tool_result
            except Exception as exc:
                log.error("tool_execute_failed", tool=tool_name, error=str(exc))
                tool_result = {"error": str(exc)}
                is_error = True
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            tool_calls_log.append({
                "round": round_num,
                "tool": tool_name,
                "input": tool_input,
                "result": tool_result,
                "is_error": is_error,
                "elapsed_ms": elapsed_ms,
            })

            log.info("tool_result", round=round_num, tool=tool_name,
                     elapsed_ms=elapsed_ms, is_error=is_error)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(tool_result, default=str),
                "is_error": is_error,
            })

        # Feed tool results back as a user message (Anthropic format)
        messages.append({"role": "user", "content": tool_results})

    # Hit max rounds
    log.warning("tool_loop_max_rounds", max=MAX_TOOL_ROUNDS)
    final_text = "\n".join(text_parts) if text_parts else ""
    final_text += f"\n\n(Reached tool call limit of {MAX_TOOL_ROUNDS} rounds)"
    return {
        "response_text": final_text,
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
        "tool_calls_made": tool_calls_log,
        "rounds": MAX_TOOL_ROUNDS,
    }


def _block_to_dict(block: Any) -> dict:
    """Convert an Anthropic SDK content block to a plain dict for message history."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    elif block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    # Fallback for any other block types
    return {"type": block.type}
