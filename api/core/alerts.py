from datetime import datetime

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger

logger = get_logger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def _send_telegram(text: str) -> None:
    settings = get_settings()
    if not settings.TELEGRAM_ALERT_CHAT_ID:
        logger.warning("telegram_alert_skipped", reason="TELEGRAM_ALERT_CHAT_ID not set", text=text)
        return

    url = _TELEGRAM_API.format(token=settings.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": settings.TELEGRAM_ALERT_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json=payload)


async def alert_error(context: str, error: Exception) -> None:
    text = (
        f"🚨 openclaw error\n"
        f"Context: {context}\n"
        f"Error: {type(error).__name__}\n"
        f"Detail: {str(error)[:200]}\n"
        f"Time: {datetime.utcnow().isoformat()}"
    )
    try:
        await _send_telegram(text)
    except Exception as e:
        logger.error("alert_send_failed", original_context=context, alert_error=str(e))


async def alert_info(message: str) -> None:
    try:
        await _send_telegram(message)
    except Exception as e:
        logger.error("alert_send_failed", message=message, alert_error=str(e))
