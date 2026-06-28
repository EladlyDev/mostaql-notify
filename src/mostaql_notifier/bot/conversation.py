"""The add-note force-reply flow (Feature 3, US4).

Tapping the 📝 button (``pf:note:{id}``) sends a :class:`telegram.ForceReply` prompt and records the
pending project id for this chat; the owner's *next* plain-text message is **appended** to that
project's notes via ``service.set_notes(..., append=True)`` — append, never overwrite
(non-destructive, Constitution IV) — and confirmed.

The pending target lives in ``context.chat_data`` (per-chat, in-memory for PTB v21). That is enough
for a single supervised process; to also survive a bot restart mid-flow it could be persisted in the
``app_state`` table (keyed by chat id) instead — left as an in-memory dict here for simplicity.
"""
from __future__ import annotations

import logging

from telegram import ForceReply, Update
from telegram.ext import ContextTypes

from ..db.models import Project
from ..personal import service
from .app import is_owner, session_scope

log = logging.getLogger("mostaql.bot")

#: ``context.chat_data`` key holding the project id awaiting a note from this chat.
PENDING_KEY = "pending_note_project_id"

_PROMPT = "✏️ اكتب ملاحظتك للمشروع"
_SAVED = "📝 حُفظت الملاحظة"
_CANCELLED = "تم الإلغاء"
_NOT_FOUND = "المشروع غير موجود"


async def start_note(update: Update, context: ContextTypes.DEFAULT_TYPE, project_id: int) -> None:
    """Begin the add-note flow for ``project_id``: answer the callback, remember the pending target,
    and send a ForceReply prompt so the owner's next message is captured as the note."""
    query = update.callback_query
    if context.chat_data is not None:
        context.chat_data[PENDING_KEY] = project_id
    if query is not None:
        await query.answer()
        if query.message is not None:
            await query.message.reply_text(_PROMPT, reply_markup=ForceReply(selective=True))


async def handle_note_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Append the owner's text to the pending project's notes, if a note is in progress.

    No pending target → the plain text isn't ours; ignore it. The pending state is cleared as soon
    as a reply arrives, so an empty/whitespace reply cancels gracefully rather than re-prompting."""
    if not is_owner(update):
        return
    pending = context.chat_data.get(PENDING_KEY) if context.chat_data is not None else None
    if pending is None:
        return  # not awaiting a note — leave plain text alone

    if context.chat_data is not None:  # pragma: no branch - a non-None pending implies chat_data
        context.chat_data.pop(PENDING_KEY, None)  # consume the pending target

    message = update.message
    text = (message.text or "").strip() if message is not None else ""
    if not text:
        if message is not None:
            await message.reply_text(_CANCELLED)
        return

    with session_scope() as session:
        if session.get(Project, pending) is None:
            if message is not None:  # pragma: no branch - non-empty text implies a message
                await message.reply_text(_NOT_FOUND)
            return
        service.set_notes(session, pending, text, append=True)
        session.commit()
    if message is not None:  # pragma: no branch - non-empty text implies a message
        await message.reply_text(_SAVED)
