"""Tool registry for OpenClaw agents.

Tools are async callables that accept a params dict and return a result dict.
Agents list allowed tools by name in their YAML configs; execute_tool dispatches
to the registered implementation.

Phase A: Rewired query_fleet / query_trips / query_fuel to call OPS-AI API.
         Added get_kpi_summary, get_daily_report, get_pending_approvals.
         Added trigger_n8n_webhook wired to real n8n webhook URLs from config.

Adding a new tool:
  1. Define an async function: async def my_tool(params: dict) -> dict
  2. Register it in TOOL_REGISTRY: TOOL_REGISTRY["my_tool"] = my_tool
  3. Add the Anthropic schema in TOOL_SCHEMAS: TOOL_SCHEMAS["my_tool"] = { ... }
"""

from __future__ import annotations

import json
from typing import Any, Callable, Awaitable

import httpx

from api.core.logging import get_logger
from api.core.opsai_client import opsai_get

log = get_logger(__name__)

# Type alias for tool callables.
ToolFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def tool_escalate(params: dict[str, Any]) -> dict[str, Any]:
    """Log an escalation event and return routing metadata."""
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
    """Send a Telegram message via the agent's bot."""
    from api.core.telegram import TelegramClient

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


async def tool_query_fleet(params: dict[str, Any]) -> dict[str, Any]:
    """Query fleet/trucks from OPS-AI API."""
    query_params: dict[str, Any] = {}
    if params.get("status"):
        query_params["status"] = params["status"]
    result = await opsai_get("/api/v1/trucks/", params=query_params or None)
    if "error" in result:
        return result
    # Normalize: OPS-AI may return a list or a dict with items/data key
    rows = result if isinstance(result, list) else result.get("items", result.get("data", [result]))
    return {"count": len(rows), "trucks": rows}


async def tool_query_trips(params: dict[str, Any]) -> dict[str, Any]:
    """Query trips from OPS-AI API with optional date filters."""
    query_params: dict[str, Any] = {}
    if params.get("start_date"):
        query_params["start_date"] = params["start_date"]
    if params.get("end_date"):
        query_params["end_date"] = params["end_date"]
    if params.get("truck_id"):
        query_params["truck_id"] = params["truck_id"]
    if params.get("limit"):
        query_params["limit"] = params["limit"]
    result = await opsai_get("/api/v1/trips/", params=query_params or None)
    if "error" in result:
        return result
    rows = result if isinstance(result, list) else result.get("items", result.get("data", [result]))
    return {"count": len(rows), "trips": rows}


async def tool_query_fuel(params: dict[str, Any]) -> dict[str, Any]:
    """Query fuel efficiency data from OPS-AI API."""
    query_params: dict[str, Any] = {}
    if params.get("start_date"):
        query_params["start_date"] = params["start_date"]
    if params.get("end_date"):
        query_params["end_date"] = params["end_date"]
    if params.get("truck_id"):
        query_params["truck_id"] = params["truck_id"]
    result = await opsai_get("/api/v1/reports/fuel-efficiency/", params=query_params or None)
    if "error" in result:
        return result
    return result


async def tool_get_kpi_summary(_params: dict[str, Any]) -> dict[str, Any]:
    """Get weekly KPI dashboard data from OPS-AI."""
    return await opsai_get("/api/v1/kpis/summary/")


async def tool_get_daily_report(_params: dict[str, Any]) -> dict[str, Any]:
    """Get today's operations summary from OPS-AI."""
    return await opsai_get("/api/v1/reports/daily-summary/")


async def tool_get_pending_approvals(_params: dict[str, Any]) -> dict[str, Any]:
    """Get receipts/items pending approval from OPS-AI."""
    return await opsai_get("/api/v1/bot/pending-approvals/")


async def tool_trigger_n8n_webhook(params: dict[str, Any]) -> dict[str, Any]:
    """Trigger an n8n workflow by name via its webhook URL."""
    from api.core.config import get_settings

    settings = get_settings()

    workflow = params.get("workflow", "").lower().replace("-", "_").replace(" ", "_")
    payload = params.get("payload", {})

    webhook_map = {
        "daily_digest": settings.N8N_WEBHOOK_DAILY_DIGEST,
        "manager_alerts": settings.N8N_WEBHOOK_MANAGER_ALERTS,
    }

    webhook_path = webhook_map.get(workflow)
    if not webhook_path:
        available = [k for k, v in webhook_map.items() if v]
        return {
            "triggered": False,
            "error": f"Unknown or unconfigured workflow '{workflow}'",
            "available_workflows": available,
        }

    if not settings.N8N_BASE_URL:
        return {"triggered": False, "error": "N8N_BASE_URL is not configured"}

    url = f"{settings.N8N_BASE_URL.rstrip('/')}/{webhook_path.lstrip('/')}"
    log.info("tool_trigger_n8n_webhook", workflow=workflow, url=url)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return {"triggered": True, "workflow": workflow, "status": resp.status_code}
    except httpx.HTTPStatusError as exc:
        log.error("n8n_webhook_http_error", workflow=workflow, status=exc.response.status_code)
        return {"triggered": False, "error": f"n8n returned {exc.response.status_code}", "detail": exc.response.text[:300]}
    except httpx.TimeoutException:
        return {"triggered": False, "error": "n8n webhook timed out after 15s"}
    except Exception as exc:
        log.error("n8n_webhook_failed", workflow=workflow, error=str(exc))
        return {"triggered": False, "error": str(exc)}


async def tool_classify_intent(params: dict[str, Any]) -> dict[str, Any]:
    """Classify the intent of a message by routing to Clay."""
    from api.core.agent_runner import run_agent

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
            conn=None,
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
    "get_kpi_summary": tool_get_kpi_summary,
    "get_daily_report": tool_get_daily_report,
    "get_pending_approvals": tool_get_pending_approvals,
    "trigger_n8n_webhook": tool_trigger_n8n_webhook,
    "classify_intent": tool_classify_intent,
}


async def execute_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Look up and execute a named tool.

    Returns a dict — errors are returned as {"error": "..."} rather than
    raised, so agent_runner can decide whether to surface them.
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


# ---------------------------------------------------------------------------
# TOOL_SCHEMAS — Anthropic-format tool definitions for native tool use
# ---------------------------------------------------------------------------
# These are passed to the Anthropic API in the `tools` parameter.
# agent_runner._get_tool_schemas_for_agent() filters these to only the tools
# listed in each agent's YAML config.
#
# Format: https://docs.anthropic.com/en/docs/tool-use
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: dict[str, dict] = {
    "escalate": {
        "name": "escalate",
        "description": (
            "Escalate a task to another agent when it's outside your scope. "
            "Use this when you can't handle a request and need to hand off."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "escalated_to": {
                    "type": "string",
                    "description": "Target agent slug to escalate to (e.g. 'clay', 'jake').",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this is being escalated.",
                },
                "original_message": {
                    "type": "string",
                    "description": "The original user message that triggered the escalation.",
                },
            },
            "required": ["escalated_to", "reason"],
        },
    },
    "query_fleet": {
        "name": "query_fleet",
        "description": (
            "Get the list of trucks/fleet from OPS-AI. Returns plate numbers, "
            "status, and assignments. Use for fleet status and availability questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by truck status (e.g. 'available', 'on_trip', 'maintenance'). Leave empty for all.",
                },
            },
            "required": [],
        },
    },
    "query_trips": {
        "name": "query_trips",
        "description": (
            "Get trip records from OPS-AI. Returns trip dates, routes, trucks, drivers, "
            "and tonnage. Use for trip history, hauling questions, or weekly trip counts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Filter trips from this date (YYYY-MM-DD). Use for 'this week', 'last 7 days' etc.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter trips up to this date (YYYY-MM-DD).",
                },
                "truck_id": {
                    "type": "string",
                    "description": "Filter by specific truck ID or plate number.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of trips to return. Default: 20.",
                },
            },
            "required": [],
        },
    },
    "query_fuel": {
        "name": "query_fuel",
        "description": (
            "Get fuel efficiency report from OPS-AI. Returns consumption, costs, "
            "and efficiency metrics per truck. Use for fuel cost and consumption questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Filter from this date (YYYY-MM-DD).",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter up to this date (YYYY-MM-DD).",
                },
                "truck_id": {
                    "type": "string",
                    "description": "Filter by specific truck ID.",
                },
            },
            "required": [],
        },
    },
    "get_kpi_summary": {
        "name": "get_kpi_summary",
        "description": (
            "Get the weekly KPI dashboard from OPS-AI. Returns total trips, tonnage, "
            "active trucks, revenue, and other key performance indicators. "
            "Use when asked for a business overview, KPIs, or weekly summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_daily_report": {
        "name": "get_daily_report",
        "description": (
            "Get today's operations summary from OPS-AI. Returns active trips, "
            "trucks deployed, drivers on duty, and today's highlights. "
            "Use when asked 'what's happening today' or 'daily status'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_pending_approvals": {
        "name": "get_pending_approvals",
        "description": (
            "Get receipts and items waiting for Job's approval from OPS-AI. "
            "Returns pending fuel receipts, expense claims, and procurement requests. "
            "Use when asked about pending items, approvals, or what needs review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "trigger_n8n_webhook": {
        "name": "trigger_n8n_webhook",
        "description": (
            "Trigger an n8n automation workflow by name. Available workflows: "
            "'daily_digest' (sends morning summary), 'manager_alerts' (checks and sends pending alerts). "
            "Always confirm with Job before triggering workflows that send messages to others."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow": {
                    "type": "string",
                    "description": "Workflow name to trigger: 'daily_digest' or 'manager_alerts'.",
                },
                "payload": {
                    "type": "object",
                    "description": "Optional JSON payload to pass to the webhook.",
                },
            },
            "required": ["workflow"],
        },
    },
    "classify_intent": {
        "name": "classify_intent",
        "description": (
            "Classify the intent of a user message by routing it to the Clay agent. "
            "Returns structured intent classification. Use when you need to understand "
            "what a user is asking before deciding how to respond."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to classify.",
                },
                "client_id": {
                    "type": "string",
                    "description": "Client scope identifier. Default: 'internal'.",
                },
            },
            "required": ["message"],
        },
    },
    "send_telegram": {
        "name": "send_telegram",
        "description": (
            "Send a Telegram message to a specific chat. Requires bot_token "
            "and chat_id. Use for proactive notifications or cross-agent messaging."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Telegram chat or user ID.",
                },
                "text": {
                    "type": "string",
                    "description": "Message body (Markdown supported).",
                },
                "bot_token": {
                    "type": "string",
                    "description": "Bot token for the sending agent.",
                },
                "parse_mode": {
                    "type": "string",
                    "description": "Parse mode: 'Markdown', 'HTML', or empty. Default: 'Markdown'.",
                },
            },
            "required": ["chat_id", "text", "bot_token"],
        },
    },
}
