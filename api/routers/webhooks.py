import asyncpg
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from api.core.alerts import alert_error
from api.core.cost_calc import format_cost
from api.core.logging import get_logger
from api.core.model_clients import call_model
from api.core.model_router import TaskType
from api.core.telegram_dispatch import AGENT_BOT_MAP, dispatch_telegram_update, register_webhooks
from api.db.database import get_db
from api.db.queries import get_cost_summary
from api.models.schemas import TelegramUpdate

router = APIRouter()
logger = get_logger(__name__)


class RegisterWebhooksRequest(BaseModel):
    base_url: str

_TELEGRAM_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"

COMMANDS = {"/nora", "/max", "/clay", "/ask", "/cost", "/status"}

_AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "nora": (
        "You are Nora, an AI fleet operations assistant for RPQ Truckwide Corp. "
        "Help with trip logging, fuel tracking, driver payroll, and billing queries. "
        "Be concise — replies go to Telegram."
    ),
    "max": (
        "You are Max, a software development assistant. "
        "Help with code, debugging, architecture, and technical questions. "
        "Be concise — replies go to Telegram."
    ),
    "clay": (
        "You are Clay, a professional client-facing AI assistant. "
        "Be friendly, helpful, and concise."
    ),
    "orchestrator": (
        "You are a helpful AI assistant. Be concise — replies go to Telegram."
    ),
}


async def send_telegram_message(chat_id: int, text: str) -> None:
    """Send a message to a Telegram chat. Never raises."""
    from api.core.config import get_settings
    settings = get_settings()
    url = _TELEGRAM_SEND_URL.format(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.error("telegram_send_failed", chat_id=chat_id, error=str(e))


def _extract_command(text: str) -> str | None:
    token = text.strip().split()[0].lower()
    return token if token in COMMANDS else None


def _message_body(text: str, command: str | None) -> str:
    """Strip the command prefix from the message. Returns remaining text."""
    if not command:
        return text.strip()
    body = text[len(command):].strip()
    return body if body else "Hello"


@router.post("/telegram")
async def telegram_webhook(
    update: TelegramUpdate,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: asyncpg.Connection = Depends(get_db),
) -> dict:
    from api.core.config import get_settings
    settings = get_settings()

    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="invalid webhook secret")

    if not update.message or not update.message.text:
        return {"ok": True}

    message_text = update.message.text
    chat_id = update.message.chat.id
    user_id = update.message.from_.id if update.message.from_ else chat_id
    client_id = f"telegram:{user_id}"

    command = _extract_command(message_text)
    body = _message_body(message_text, command)

    logger.info(
        "telegram_update",
        update_id=update.update_id,
        chat_id=chat_id,
        command=command,
        body=body[:80],
    )

    # ── /cost — query DB, no model call ──────────────────────────────────────
    if command == "/cost":
        try:
            rows = await get_cost_summary(db, client_id=None, days=7)
            if not rows:
                reply = "No cost data yet."
            else:
                lines = ["📊 Cost summary (last 7 days):"]
                for row in rows[:10]:
                    lines.append(
                        f"  {row['date']} | {row['model']} | "
                        f"{format_cost(float(row['total_cost_usd']))} | "
                        f"{row['request_count']} calls"
                    )
                reply = "\n".join(lines)
        except Exception as e:
            reply = f"⚠️ Could not fetch cost data: {e}"
        await send_telegram_message(chat_id, reply)
        return {"ok": True}

    # ── /status — health check, no model call ────────────────────────────────
    if command == "/status":
        try:
            await db.execute("SELECT 1")
            reply = "✅ System online\n• DB: OK\n• API: OK"
        except Exception as e:
            reply = f"⚠️ System degraded\n• DB: ERROR ({e})"
        await send_telegram_message(chat_id, reply)
        return {"ok": True}

    # ── Agent commands — real model call ─────────────────────────────────────
    agent_name_map = {
        "/nora": "nora",
        "/max": "max",
        "/clay": "clay",
        "/ask": "orchestrator",
    }
    agent_name = agent_name_map.get(command, "orchestrator")
    system_prompt = _AGENT_SYSTEM_PROMPTS[agent_name]

    try:
        messages = [{"role": "user", "content": body}]
        result = await call_model(messages, TaskType.ORCHESTRATE, system=system_prompt)
        reply = result["content"]
    except Exception as e:
        logger.error("telegram_agent_failed", agent=agent_name, error=str(e))
        await alert_error(context=f"Telegram {command or 'message'} agent={agent_name}", error=e)
        reply = f"⚠️ Sorry, something went wrong. Please try again."

    # Telegram has a 4096-char message limit
    if len(reply) > 4000:
        reply = reply[:3997] + "..."

    await send_telegram_message(chat_id, reply)
    return {"ok": True}


@router.post("/n8n")
async def n8n_webhook(request: Request) -> dict:
    payload = await request.json()
    logger.info("n8n_webhook_received", payload=payload)
    return {"received": True}


# ── Per-agent Telegram bots ───────────────────────────────────────────────────
# IMPORTANT: /telegram/register must be defined before /telegram/{bot_token}
# so FastAPI doesn't swallow "register" as a bot_token path param.

@router.post("/telegram/register")
async def telegram_register_webhooks(body: RegisterWebhooksRequest) -> dict:
    """Register Telegram webhooks for all configured agent bots.

    Body: {"base_url": "https://openclaw.yourdomain.com"}
    Each configured bot gets a webhook at {base_url}/webhooks/telegram/{bot_token}.
    """
    results = await register_webhooks(body.base_url)
    return {
        "registered": len([r for r in results if r.get("ok")]),
        "total": len(results),
        "bots": results,
    }


@router.post("/telegram/{bot_token}")
async def telegram_agent_webhook(
    bot_token: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Per-agent Telegram webhook. Returns 200 immediately; processes in background.

    Telegram requires a response within 5 seconds — agent processing happens
    asynchronously via FastAPI BackgroundTasks so the connection is released fast.

    URL pattern: POST /webhooks/telegram/{bot_token}
    """
    if bot_token not in AGENT_BOT_MAP:
        # Return 200 to Telegram regardless — don't leak which tokens are valid.
        logger.warning("telegram_unknown_bot_token", suffix=bot_token[-6:] if len(bot_token) >= 6 else bot_token)
        return {"ok": True}

    try:
        update = await request.json()
    except Exception as exc:
        logger.error("telegram_bad_payload", error=str(exc))
        return {"ok": True}

    logger.info(
        "telegram_webhook_received",
        agent=AGENT_BOT_MAP[bot_token],
        update_id=update.get("update_id"),
    )

    background_tasks.add_task(dispatch_telegram_update, bot_token, update)
    return {"ok": True}
