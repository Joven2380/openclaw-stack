"""Telegram Bot API client.

One TelegramClient instance per bot token — each agent has its own bot.
Uses raw httpx calls (no python-telegram-bot dependency).
"""

import asyncio
from typing import Any

import httpx

from api.core.logging import get_logger

log = get_logger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_MAX_MSG_LEN = 4096
_TIMEOUT = httpx.Timeout(30.0)


def _split_text(text: str) -> list[str]:
    """Split text into chunks that fit within Telegram's 4096-char limit.

    Splits on the last newline within the limit when possible, otherwise
    hard-cuts at the limit.
    """
    if len(text) <= _MAX_MSG_LEN:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= _MAX_MSG_LEN:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, _MAX_MSG_LEN)
        if split_at <= 0:
            split_at = _MAX_MSG_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


class TelegramClient:
    """Async client for the Telegram Bot API."""

    def __init__(self, bot_token: str) -> None:
        self._token = bot_token

    def _url(self, method: str) -> str:
        return _API_BASE.format(token=self._token, method=method)

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the Telegram API. Returns parsed JSON dict. Never raises on
        Telegram-level errors (ok=false) — callers inspect the result."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(self._url(method), json=payload)
            resp.raise_for_status()
            return resp.json()

    async def _send_chunk(
        self,
        chat_id: int,
        text: str,
        parse_mode: str,
    ) -> dict[str, Any]:
        """Send a single chunk. Retries once on network error (2s delay).
        Falls back to plain text if Markdown parse fails."""
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        for attempt in range(2):
            try:
                result = await self._post("sendMessage", payload)

                # Telegram returned ok=false — likely a Markdown parse error.
                if not result.get("ok") and "parse_mode" in payload:
                    log.warning(
                        "telegram_markdown_failed",
                        chat_id=chat_id,
                        description=result.get("description", ""),
                    )
                    payload.pop("parse_mode")
                    result = await self._post("sendMessage", payload)

                return result

            except httpx.NetworkError as exc:
                if attempt == 0:
                    log.warning("telegram_send_retry", chat_id=chat_id, error=str(exc))
                    await asyncio.sleep(2)
                    continue
                log.error("telegram_send_failed", chat_id=chat_id, error=str(exc))
                return {"ok": False, "error": str(exc)}

            except httpx.HTTPStatusError as exc:
                log.error(
                    "telegram_http_error",
                    chat_id=chat_id,
                    status=exc.response.status_code,
                    body=exc.response.text[:200],
                )
                return {"ok": False, "error": str(exc)}

        return {"ok": False, "error": "send failed after retry"}

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "Markdown",
    ) -> dict[str, Any]:
        """Send a message, splitting automatically if it exceeds 4096 chars.

        Args:
            chat_id: Telegram chat or user ID.
            text: Message text (Markdown by default).
            parse_mode: "Markdown", "HTML", or "" for plain text.

        Returns:
            API response dict for the last chunk sent.
        """
        chunks = _split_text(text)
        result: dict[str, Any] = {}

        for i, chunk in enumerate(chunks):
            result = await self._send_chunk(chat_id, chunk, parse_mode)
            if not result.get("ok"):
                log.error(
                    "telegram_chunk_failed",
                    chat_id=chat_id,
                    chunk=i + 1,
                    of=len(chunks),
                    description=result.get("description", result.get("error", "")),
                )

        log.info(
            "telegram_sent",
            chat_id=chat_id,
            chunks=len(chunks),
            chars=len(text),
        )
        return result

    async def send_typing_action(self, chat_id: int) -> None:
        """Send a typing indicator. Silently ignores failures."""
        try:
            await self._post(
                "sendChatAction",
                {"chat_id": chat_id, "action": "typing"},
            )
        except Exception as exc:
            log.debug("telegram_typing_failed", chat_id=chat_id, error=str(exc))

    async def set_webhook(self, url: str) -> dict[str, Any]:
        """Register a webhook URL with Telegram.

        Args:
            url: Full HTTPS URL Telegram will POST updates to.

        Returns:
            Telegram API response dict with ok, description fields.
        """
        result = await self._post("setWebhook", {"url": url})
        log.info(
            "telegram_webhook_set",
            url=url,
            ok=result.get("ok"),
            description=result.get("description", ""),
        )
        return result
