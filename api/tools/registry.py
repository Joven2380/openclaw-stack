"""Tool registry for OpenClaw agents.

Tools are async callables that accept a params dict and return a result dict.
Agents list allowed tools by name in their YAML configs; execute_tool dispatches
to the registered implementation.

Adding a new tool:
  1. Define an async function: async def my_tool(params: dict) -> dict
  2. Register it: TOOL_REGISTRY["my_tool"] = my_tool
"""

from __future__ import annotations

import json
from typing import Any, Callable, Awaitable

import structlog

from api.core.logging import get_logger
from api.db.database import get_pool

log = get_logger(__name__)

# Type alias for tool callables.
ToolFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def tool_escalate(params: dict[str, Any]) -> dict[str, Any]:
    """Log an escalation event and return routing metadata.

    Expected params:
        escalated_to (str): Target agent slug.
        reason (str): Why this is being escalated.
        original_message (str, optional): The message that triggered escalation.
    """
    escalated_to = params.get("escalated_to", "clay")
    reason = params.get("reason", "Task outside agent scope")
    original_message = params.get("original_message", "")

    log.info(
        "tool_escalate",
        escalated_to=escalated_to,
        reason=reason,
        original_chars=len(original_message),
    )
    return {
        "status": "escalated",
        "escalated_to": escalated_to,
        "reason": reason,
    }


async def tool_send_telegram(params: dict[str, Any]) -> dict[str, Any]:
    """Send a Telegram message via the agent's bot.

    Expected params:
        chat_id (str | int): Target chat or user ID.
        text (str): Message body (Markdown supported).
        bot_token (str): Bot token for the sending agent.
        parse_mode (str, optional): "Markdown" (default) or "HTML" or "".

    Returns:
        {"sent": True, "chat_id": chat_id} on success,
        {"sent": False, "error": "..."} on failure.
    """
    from api.core.telegram import TelegramClient  # lazy to avoid circular at load time

    chat_id = params.get("chat_id")
    text = params.get("text", "")
    bot_token = params.get("bot_token")
    parse_mode = params.get("parse_mode", "Markdown")

    if not chat_id:
        return {"sent": False, "error": "chat_id is required"}
    if not bot_token:
        return {"sent": False, "error": "bot_token is required — pass via agent context"}
    if not text:
        return {"sent": False, "error": "text is required"}

    try:
        client = TelegramClient(str(bot_token))
        result = await client.send_message(int(chat_id), text, parse_mode=parse_mode)
        ok = result.get("ok", False)
        log.info("tool_send_telegram", chat_id=chat_id, ok=ok, chars=len(text))
        if ok:
            return {"sent": True, "chat_id": chat_id}
        return {"sent": False, "error": result.get("description", "Telegram returned ok=false")}
    except Exception as exc:
        log.error("tool_send_telegram_failed", chat_id=chat_id, error=str(exc))
        return {"sent": False, "error": str(exc)}


async def _query_table(
    table: str,
    params: dict[str, Any],
    select_cols: str = "*",
    limit: int = 20,
) -> dict[str, Any]:
    """Generic safe SELECT against a named table using the asyncpg pool.

    Returns a friendly error dict if the table doesn't exist yet.
    """
    try:
        pool = get_pool()
    except RuntimeError:
        return {"error": "Database pool not initialized", "rows": []}

    where_clause = params.get("where", "")
    order_clause = params.get("order_by", "created_at DESC")
    row_limit = int(params.get("limit", limit))

    sql = f"SELECT {select_cols} FROM {table}"  # noqa: S608 — table name is hard-coded, not user input
    if where_clause:
        sql += f" WHERE {where_clause}"
    if order_clause:
        sql += f" ORDER BY {order_clause}"
    sql += f" LIMIT {row_limit}"

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return {
            "table": table,
            "count": len(rows),
            "rows": [dict(r) for r in rows],
        }
    except Exception as exc:
        err_msg = str(exc)
        # Friendly message for tables that haven't been migrated yet.
        if "does not exist" in err_msg or "relation" in err_msg:
            return {
                "table": table,
                "count": 0,
                "rows": [],
                "note": f"Table '{table}' not yet populated — run the relevant migration first.",
            }
        log.error("tool_query_failed", table=table, error=err_msg)
        return {"error": err_msg, "table": table, "rows": []}


async def tool_query_fleet(params: dict[str, Any]) -> dict[str, Any]:
    """Query the trucks/fleet table.

    Expected params (all optional):
        where (str): SQL WHERE clause fragment (e.g. "status = 'available'").
        order_by (str): ORDER BY clause (default: "plate_number ASC").
        limit (int): Row limit (default: 20).
    """
    params.setdefault("order_by", "plate_number ASC")
    return await _query_table("trucks", params)


async def tool_query_trips(params: dict[str, Any]) -> dict[str, Any]:
    """Query the trips table.

    Expected params (all optional):
        where (str): SQL WHERE clause fragment (e.g. "status = 'active'").
        order_by (str): ORDER BY clause (default: "trip_date DESC").
        limit (int): Row limit (default: 20).
    """
    params.setdefault("order_by", "trip_date DESC")
    return await _query_table("trips", params)


async def tool_query_fuel(params: dict[str, Any]) -> dict[str, Any]:
    """Query the fuel_logs table.

    Expected params (all optional):
        where (str): SQL WHERE clause fragment (e.g. "truck_id = '...'").
        order_by (str): ORDER BY clause (default: "log_date DESC").
        limit (int): Row limit (default: 20).
    """
    params.setdefault("order_by", "log_date DESC")
    return await _query_table("fuel_logs", params)


async def tool_classify_intent(params: dict[str, Any]) -> dict[str, Any]:
    """Classify the intent of a message by routing to Clay.

    Expected params:
        message (str): The message to classify.
        client_id (str, optional): Client scope (default: "internal").

    Returns:
        Clay's classification response dict.
    """
    # Lazy import to avoid circular dependency at module load time.
    from api.core.agent_runner import run_agent  # noqa: PLC0415

    message = params.get("message", "")
    client_id = params.get("client_id", "internal")

    if not message:
        return {"error": "No message provided for classification"}

    classification_prompt = (
        f"Classify the following message. Return JSON only.\n\nMessage: {message}"
    )

    try:
        result = await run_agent(
            agent_name="clay",
            user_message=classification_prompt,
            client_id=client_id,
            conn=None,  # no memory for classification calls
        )
        return {
            "intent_raw": result["response"],
            "model": result["model"],
            "tokens_used": result["tokens_in"] + result["tokens_out"],
        }
    except Exception as exc:
        log.error("tool_classify_intent_failed", error=str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Registry + dispatch
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolFn] = {
    "escalate": tool_escalate,
    "send_telegram": tool_send_telegram,
    "query_fleet": tool_query_fleet,
    "query_trips": tool_query_trips,
    "query_fuel": tool_query_fuel,
    "classify_intent": tool_classify_intent,
}


async def execute_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Look up and execute a named tool.

    Args:
        tool_name: Key in TOOL_REGISTRY (e.g. "query_trips").
        params: Arbitrary params dict passed to the tool function.

    Returns:
        Tool result dict. Always returns a dict — errors are returned as
        {"error": "..."} rather than raised, so agent_runner can decide
        whether to surface them to the model or escalate.
    """
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        log.warning("tool_not_found", tool=tool_name, available=list(TOOL_REGISTRY))
        return {
            "error": f"Tool '{tool_name}' not registered",
            "available_tools": list(TOOL_REGISTRY),
        }

    log.info("tool_execute", tool=tool_name, params=json.dumps(params, default=str)[:200])
    try:
        result = await fn(params)
        log.debug("tool_result", tool=tool_name, keys=list(result))
        return result
    except Exception as exc:
        log.error("tool_execute_failed", tool=tool_name, error=str(exc))
        return {"error": str(exc), "tool": tool_name}
