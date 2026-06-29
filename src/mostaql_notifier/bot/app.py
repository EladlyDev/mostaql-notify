"""Builds the inbound PTB v21 ``Application`` (long-poll ``getUpdates``, no webhook).

This is the single ``getUpdates`` consumer for the bot token (the worker only *sends*). Every
handler first passes through :func:`is_owner` so the bot serves exactly the one configured owner
chat (Constitution I & IX); anything else is silently dropped. DB sessions are obtained per handler
invocation from the shared :func:`get_sessionmaker`, and all personal mutations go through
``personal/service.py`` so a Telegram action and a dashboard action converge on the same record.

The handler modules import :func:`is_owner` / :func:`session_scope` from here; to avoid an import
cycle the concrete handlers are imported lazily inside :func:`build_application`.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from ..config.secrets import get_secrets
from ..db.session import get_sessionmaker

log = logging.getLogger("mostaql.bot")


def is_owner(update: Update) -> bool:
    """True iff the update originates from the single configured owner chat (Constitution I & IX).

    Every callback/command/message handler gates on this; a non-owner update is silently ignored —
    no reply, no action, no service call. A missing chat or an unparsable ``TELEGRAM_CHAT_ID`` is
    treated as *not* the owner (fail closed)."""
    chat = update.effective_chat
    if chat is None:
        return False
    try:
        owner_id = int(get_secrets().telegram_chat_id)
    except (TypeError, ValueError):
        return False
    return chat.id == owner_id


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a fresh DB session for one handler invocation; the handler owns its ``commit``.

    Mirrors the worker (``with Session() as s``) and the API's per-request session — a short-lived
    session over the shared WAL SQLite, closed when the handler returns."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def build_application(token: str) -> Application:
    """Build the long-poll :class:`telegram.ext.Application` with every handler registered.

    Handlers (imported lazily to avoid an ``app`` ↔ handler import cycle):
      * ``CallbackQueryHandler`` — the inline ``pf:*`` action buttons (incl. Feature 4's "Why?").
      * ``CommandHandler`` × 6 — ``/find /pause /resume /health /stats /top``.
      * ``MessageHandler`` (plain text, non-command) — the owner's reply that completes an
        *add-note* force-reply flow.
    """
    from . import callbacks, commands, conversation

    application = ApplicationBuilder().token(token).build()

    # Inline action buttons on project notifications: callback_data ``pf:{action}:{project_id}``.
    application.add_handler(CallbackQueryHandler(callbacks.handle_callback))

    # Owner commands.
    application.add_handler(CommandHandler("find", commands.find_command))
    application.add_handler(CommandHandler("pause", commands.pause_command))
    application.add_handler(CommandHandler("resume", commands.resume_command))
    application.add_handler(CommandHandler("health", commands.health_command))
    application.add_handler(CommandHandler("stats", commands.stats_command))
    application.add_handler(CommandHandler("top", commands.top_command))

    # Add-note completion: the owner's next plain-text message after tapping 📝 (a ForceReply was
    # sent). Commands are excluded so e.g. ``/stats`` mid-flow is still handled as a command.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, conversation.handle_note_reply)
    )

    return application
