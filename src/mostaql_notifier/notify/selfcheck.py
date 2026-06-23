"""`python -m mostaql_notifier.notify.selfcheck` — send a test message to verify Telegram wiring."""
from __future__ import annotations

import asyncio

from ..config.secrets import get_secrets, require_telegram
from .telegram import TelegramSender


async def _main() -> None:
    secrets = get_secrets()
    require_telegram(secrets)
    sender = TelegramSender(secrets.telegram_bot_token, secrets.telegram_chat_id)
    await sender.start()
    try:
        await sender.send_alert("✅ Mostaql Notifier self-check: Telegram wiring works.")
        print("Sent test message to chat", secrets.telegram_chat_id)
    finally:
        await sender.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
