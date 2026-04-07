import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from api.core.config import get_settings
from api.core.logging import get_logger
from api.models.schemas import TelegramUpdate

router = APIRouter()
logger = get_logger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

COMMANDS = {"/nora", "/max", "/clay", "/ask", "/cost", "/status"}


async def _send_telegram_message(chat_id: int, text: str) -> None:
    settings = get_settings()
    url = _TELEGRAM_API.format(token=settings.TELEGRAM_BOT_TOKEN)
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})


def _extract_command(text: str) -> str | None:
    token = text.strip().split()[0].lower()
    return token if token in COMMANDS else None


@router.post("/telegram")
async def telegram_webhook(
    update: TelegramUpdate,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    settings = get_settings()

    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="invalid webhook secret")

    if not update.message or not update.message.text:
        return {"ok": True}

    message_text = update.message.text
    chat_id = update.message.chat.id

    command = _extract_command(message_text)

    logger.info(
        "telegram_update",
        update_id=update.update_id,
        chat_id=chat_id,
        command=command,
        text=message_text[:100],
    )

    # Route by command — stub responses for now
    if command == "/nora":
        reply = "Nora here. Fleet ops assistant ready."
    elif command == "/max":
        reply = "Max here. Dev assistant ready."
    elif command == "/clay":
        reply = "Clay here. Client agent ready."
    elif command == "/ask":
        reply = "Ask anything. Routing to best model..."
    elif command == "/cost":
        reply = "Cost tracking not yet wired. Coming in Phase 2."
    elif command == "/status":
        reply = "System online. DB and Redis checks coming in Phase 2."
    else:
        reply = f"Received: {message_text}"

    await _send_telegram_message(chat_id, reply)
    return {"ok": True}


@router.post("/n8n")
async def n8n_webhook(request: Request) -> dict:
    payload = await request.json()
    logger.info("n8n_webhook_received", payload=payload)
    return {"received": True}
