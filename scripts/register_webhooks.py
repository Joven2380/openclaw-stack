"""Register Telegram webhooks for all configured OpenClaw agent bots.

Usage:
    cd openclaw-stack
    python scripts/register_webhooks.py --base-url https://openclaw.yourdomain.com

Each configured agent bot (JAKE_BOT_TOKEN, DAME_BOT_TOKEN, etc.) gets a webhook
registered at: {base_url}/webhooks/telegram/{bot_token}

Required: at least one of JAKE_BOT_TOKEN, DAME_BOT_TOKEN, KOBE_BOT_TOKEN,
          SAM_BOT_TOKEN, KING_BOT_TOKEN must be set in your .env.
"""

import argparse
import asyncio
import os
import sys

# Ensure project root is importable when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env before importing app code.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment


async def main(base_url: str) -> None:
    from api.core.telegram_dispatch import AGENT_BOT_MAP, register_webhooks

    base_url = base_url.rstrip("/")

    if not AGENT_BOT_MAP:
        print(
            "\n[ERROR] No bot tokens configured.\n"
            "  Set at least one of these in your .env:\n"
            "    JAKE_BOT_TOKEN, DAME_BOT_TOKEN, KOBE_BOT_TOKEN, "
            "SAM_BOT_TOKEN, KING_BOT_TOKEN\n"
        )
        sys.exit(1)

    print(
        f"\n[openclaw] Registering webhooks for {len(AGENT_BOT_MAP)} bot(s)"
        f" -> {base_url}/webhooks/telegram/{{bot_token}}\n"
    )

    results = await register_webhooks(base_url)

    ok_count = 0
    for r in results:
        status = "OK  " if r.get("ok") else "FAIL"
        detail = r.get("description") or r.get("error", "no detail")
        token_hint = r.get("token_suffix", "")
        print(f"  [{status}] {r['agent']:<10} token={token_hint}  {detail}")
        if r.get("ok"):
            ok_count += 1

    print(f"\n  {ok_count}/{len(results)} bots registered successfully.\n")
    if ok_count < len(results):
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Register Telegram webhooks for all OpenClaw agent bots."
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Public HTTPS base URL of your API (e.g. https://openclaw.example.com)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
