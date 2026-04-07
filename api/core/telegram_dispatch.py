"""Telegram dispatch layer — per-agent bot routing.

Each agent has its own Telegram bot. Incoming updates are matched to an agent
by comparing the webhook path's bot_token against AGENT_BOT_MAP.

Environment variables (all optional — only configured bots are active):
    NORA_BOT_TOKEN, MAX_BOT_TOKEN, CLAY_BOT_TOKEN, LEAD_BOT_TOKEN, ANALYST_BOT_TOKEN
"""

from __future__ import annotations

import os
from typing import Any

from api.core.logging import get_logger
from api.core.telegram import TelegramClient

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Bot → agent mapping, built at module load from env vars.
# ---------------------------------------------------------------------------

_BOT_ENV_VARS: dict[str, str] = {
    "NORA_BOT_TOKEN": "nora",
    "MAX_BOT_TOKEN": "max",
    "CLAY_BOT_TOKEN": "clay",
    "LEAD_BOT_TOKEN": "lead",
    "ANALYST_BOT_TOKEN": "analyst",
}

AGENT_BOT_MAP: dict[str, str] = {}  # bot_token → agent_name

for _env_var, _agent_name in _BOT_ENV_VARS.items():
    _token = os.getenv(_env_var)
    if _token and _token.strip():
        AGENT_BOT_MAP[_token.strip()] = _agent_name

# Reverse map: agent_name → bot_token (for webhook registration)
_AGENT_TOKEN_MAP: dict[str, str] = {v: k for k, v in AGENT_BOT_MAP.items()}


def _extract_message(update: dict[str, Any]) -> tuple[int | None, str | None, int | None]:
    """Pull (chat_id, text, user_id) from a Telegram update dict.

    Returns (None, None, None) if the update has no usable text message.
    """
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None, None, None

    chat_id: int | None = message.get("chat", {}).get("id")
    text: str | None = message.get("text")
    from_ = message.get("from") or {}
    user_id: int | None = from_.get("id") or chat_id

    return chat_id, text, user_id


_NON_TEXT_REPLY = (
    "Sorry, I can only read text messages right now. "
    "Type your question and I'll help you."
)

_ERROR_REPLY = "Sorry, naay error. Try again or type /help."


async def dispatch_telegram_update(
    bot_token: str,
    update: dict[str, Any],
) -> dict[str, Any]:
    """Route a Telegram update to the correct agent and send the response.

    Args:
        bot_token: The bot token from the webhook URL path.
        update: Raw Telegram Update object as a dict.

    Returns:
        Dict with keys: agent, chat_id, tokens_used, ok.
    """
    # Resolve agent from bot token.
    agent_name = AGENT_BOT_MAP.get(bot_token)
    if not agent_name:
        log.warning("telegram_unknown_token", token_suffix=bot_token[-6:])
        return {"ok": True, "note": "unknown bot token — ignored"}

    client = TelegramClient(bot_token)

    chat_id, text, user_id = _extract_message(update)

    if chat_id is None:
        log.debug("telegram_no_chat_id", agent=agent_name, update_id=update.get("update_id"))
        return {"ok": True, "note": "no chat_id in update"}

    # Non-text message (photo, sticker, voice, etc.)
    if text is None:
        await client.send_message(chat_id, _NON_TEXT_REPLY, parse_mode="")
        return {"ok": True, "agent": agent_name, "chat_id": chat_id, "tokens_used": 0}

    client_id = f"telegram:{user_id}"

    log.info(
        "telegram_dispatch",
        agent=agent_name,
        chat_id=chat_id,
        user_id=user_id,
        chars=len(text),
        update_id=update.get("update_id"),
    )

    # Show typing indicator — fire and forget.
    await client.send_typing_action(chat_id)

    # Import here to keep module load fast and avoid circular imports at top level.
    from api.core.agent_runner import run_agent
    from api.db.database import get_pool

    tokens_used = 0
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await run_agent(
                agent_name=agent_name,
                user_message=text,
                client_id=client_id,
                context=None,
                conn=conn,
            )

        tokens_used = result.get("tokens_in", 0) + result.get("tokens_out", 0)
        response_text = result["response"]

        await client.send_message(chat_id, response_text)

        log.info(
            "telegram_dispatch_done",
            agent=agent_name,
            chat_id=chat_id,
            tokens_used=tokens_used,
            model=result.get("model"),
        )
        return {
            "ok": True,
            "agent": agent_name,
            "chat_id": chat_id,
            "tokens_used": tokens_used,
        }

    except RuntimeError as exc:
        # DB pool not ready or agent config missing — surface to user.
        log.error("telegram_dispatch_error", agent=agent_name, chat_id=chat_id, error=str(exc))
        await client.send_message(chat_id, _ERROR_REPLY, parse_mode="")
        return {"ok": False, "agent": agent_name, "chat_id": chat_id, "error": str(exc)}

    except Exception as exc:
        log.error("telegram_dispatch_error", agent=agent_name, chat_id=chat_id, error=str(exc))
        await client.send_message(chat_id, _ERROR_REPLY, parse_mode="")
        return {"ok": False, "agent": agent_name, "chat_id": chat_id, "error": str(exc)}


async def register_webhooks(base_url: str) -> list[dict[str, Any]]:
    """Register webhooks for all configured agent bots.

    Args:
        base_url: Public HTTPS base URL (e.g. "https://openclaw.example.com").
                  Do NOT include a trailing slash.

    Returns:
        List of dicts, one per bot: {agent, token_suffix, webhook_url, ok, description}.
    """
    base_url = base_url.rstrip("/")
    results: list[dict[str, Any]] = []

    if not AGENT_BOT_MAP:
        log.warning("register_webhooks_no_bots", hint="Set NORA_BOT_TOKEN etc. in .env")
        return results

    for token, agent_name in AGENT_BOT_MAP.items():
        webhook_url = f"{base_url}/webhooks/telegram/{token}"
        client = TelegramClient(token)
        try:
            resp = await client.set_webhook(webhook_url)
            results.append(
                {
                    "agent": agent_name,
                    "token_suffix": f"...{token[-6:]}",
                    "webhook_url": webhook_url,
                    "ok": resp.get("ok", False),
                    "description": resp.get("description", ""),
                }
            )
        except Exception as exc:
            log.error("register_webhook_failed", agent=agent_name, error=str(exc))
            results.append(
                {
                    "agent": agent_name,
                    "token_suffix": f"...{token[-6:]}",
                    "webhook_url": webhook_url,
                    "ok": False,
                    "error": str(exc),
                }
            )

    return results
