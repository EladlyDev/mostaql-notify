"""Entrypoint for the ``mostaql-notifier-bot`` console script.

A separate long-polling process (``getUpdates``, no webhook, no inbound port — Constitution IX/X)
that reacts to the inline buttons on project notifications and to the owner's commands, mutating the
same personal record as the dashboard. Supervised like the worker (``restart: unless-stopped`` /
``Restart=always``); failures are logged and the process is restarted.

Importing this module does **not** start polling — only :func:`run` does.
"""
from __future__ import annotations

import logging

from telegram import Update

from ..config.secrets import get_secrets, require_telegram
from .app import build_application

log = logging.getLogger("mostaql.bot")


def run() -> None:
    """Console entrypoint: build the Application and block on long-poll ``getUpdates``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    secrets = get_secrets()
    require_telegram(secrets)  # fail loud if TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are missing
    application = build_application(secrets.telegram_bot_token)
    log.info("inbound bot starting (long-poll getUpdates)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run()
