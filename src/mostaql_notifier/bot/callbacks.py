"""The ``pf:*`` inline-button callback handler (Feature 3, US4).

Each project notification carries callback buttons encoded ``pf:{action}:{project_id}`` (built in
``notify/format.py``; codec reused here, never redefined). A tap is resolved by id, applied through
``personal/service.py``, the callback query is **answered** (clears the Telegram spinner), and the
message is edited to confirm the new state. Everything is idempotent: a double-tap or a tap on an
old/expired notification converges to the same state and answers harmlessly; a vanished project
answers "المشروع غير موجود" without error (FR-026, SC-008).
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..db.models import Project
from ..notify.format import (
    CB_APPLIED,
    CB_DISMISS,
    CB_FAVORITE,
    CB_NOTE,
    parse_callback_data,
)
from ..personal import service, statuses
from . import conversation
from .app import is_owner, session_scope

log = logging.getLogger("mostaql.bot")

# Confirmation toasts / message footers (Arabic-first).
_FAV_ON = "★ مفضّل"
_FAV_OFF = "☆ أُزيل من المفضّلة"
_APPLIED_NEW = "✅ سُجّل التقديم"
_APPLIED_AGAIN = "سبق التسجيل"
_DISMISSED = "🙈 تم الإخفاء"
_NOT_FOUND = "المشروع غير موجود"

#: Separator between the original notification body and the appended state footer (kept stable so a
#: repeat tap rewrites — rather than stacks — the footer, staying idempotent).
_FOOTER_SEP = "\n\n— "


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch a ``pf:*`` inline-button tap to the right service mutation (owner-gated)."""
    if not is_owner(update):
        return  # silently ignore non-owner taps (Constitution I & IX)
    query = update.callback_query
    if query is None:
        return

    parsed = parse_callback_data(query.data or "")
    if parsed is None:
        # Foreign / garbage callback_data (not ours) — clear the spinner harmlessly, do nothing.
        await query.answer()
        return
    action, project_id = parsed

    # Add-note opens a conversation (ForceReply) rather than mutating immediately.
    if action == CB_NOTE:
        await conversation.start_note(update, context, project_id)
        return

    with session_scope() as session:
        if session.get(Project, project_id) is None:
            await query.answer(_NOT_FOUND)  # old/expired notification or deleted project
            return

        if action == CB_FAVORITE:
            rec = service.toggle_favorite(session, project_id)
            session.commit()
            confirmation = _FAV_ON if rec.favorite else _FAV_OFF
        elif action == CB_APPLIED:
            rec = service.get_or_create(session, project_id)
            already_applied = rec.status == statuses.APPLIED_KEY
            service.set_applied(session, project_id)
            session.commit()
            confirmation = _APPLIED_AGAIN if already_applied else _APPLIED_NEW
        elif action == CB_DISMISS:
            service.hide(session, project_id)
            session.commit()
            confirmation = _DISMISSED
        else:  # pragma: no cover - parse_callback_data already constrains the action set
            await query.answer()
            return

    await query.answer(confirmation)  # clears the spinner + shows a toast
    await _confirm(query, confirmation)


async def _confirm(query, confirmation: str) -> None:
    """Edit the message to reflect the new state by (re)writing a single state footer.

    A converging repeat tap (e.g. dismiss twice) yields identical text → Telegram answers "message
    is not modified"; we swallow that since the state already matches."""
    original = query.message.text if query.message is not None else None
    body = original if isinstance(original, str) else ""
    if _FOOTER_SEP in body:
        body = body.split(_FOOTER_SEP, 1)[0].rstrip()
    new_text = f"{body}{_FOOTER_SEP}{confirmation}" if body else confirmation
    try:
        await query.edit_message_text(new_text)
    except BadRequest:
        pass  # idempotent: the message already shows this state
