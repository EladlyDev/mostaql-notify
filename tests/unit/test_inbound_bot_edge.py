"""Exhaustive edge-case tests for the inbound Telegram bot handlers (Feature 3, US4).

Companion to ``test_inbound_bot.py``: this module drives the remaining *branches* of
``bot/callbacks.py``, ``bot/commands.py`` and ``bot/conversation.py`` — the silent guards
(``message is None`` / non-owner / ``query is None``), the ``_confirm`` footer rewrite + swallowed
``BadRequest``, the add-note force-reply edge states, and the ``_set_paused`` INSERT branch.

The temp-DB ``bot_db`` fixture and the fake-update helpers are reused verbatim from
``test_inbound_bot.py`` (same mocking approach: ``SimpleNamespace`` fakes with ``AsyncMock`` Telegram
methods, a per-test temp SQLite reached through the bot's own ``get_sessionmaker()``, and a pinned
owner chat id).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from mostaql_notifier.config import secrets as secrets_mod
from mostaql_notifier.config.settings_store import SettingsStore, seed_defaults
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db import session as session_mod
from mostaql_notifier.db.models import (
    EvalStatus,
    PersonalRecord,
    Project,
    ProjectStatus,
    RunStatus,
    ScrapeRun,
    Setting,
)
from mostaql_notifier.notify.format import build_callback_data

OWNER_ID = 424242
STRANGER_ID = 999999
_PAUSED_KEY = "watcher_paused"


# --- env / DB fixture + helpers (mirror tests/unit/test_inbound_bot.py exactly) -------------------

@pytest.fixture
def bot_db(tmp_path, monkeypatch):
    """Point the shared session layer + secrets at a per-test temp DB and known owner chat."""
    db_path = tmp_path / "bot_edge_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(OWNER_ID))
    session_mod._engine = None
    session_mod._Session = None
    secrets_mod.get_secrets.cache_clear()

    from mostaql_notifier.db.session import create_all, get_sessionmaker

    create_all()
    Session = get_sessionmaker()
    with Session() as s:
        seed_defaults(s)
    yield Session
    secrets_mod.get_secrets.cache_clear()


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def make_project(session, n: int = 1, **over) -> Project:
    defaults = dict(
        mostaql_id=f"proj{n}",
        title=f"مشروع تطوير {n}",
        description="وصف المشروع",
        url=f"https://mostaql.com/project/{n}",
        category="development",
        skills=["python", "برمجة"],
        budget_min=100,
        budget_max=500,
        currency="USD",
        bids_count=3,
        posted_at=_utc(),
        scraped_at=_utc(),
        site_status=ProjectStatus.open,
        eval_status=EvalStatus.qualified,
        tier=1,
        notified=False,
        raw={},
    )
    defaults.update(over)
    p = Project(**defaults)
    session.add(p)
    session.commit()
    return p


def make_message_update(text: str, *, chat_id: int = OWNER_ID):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=message,
        callback_query=None,
    )


def make_context(args=None, chat_data=None):
    return SimpleNamespace(args=args, chat_data=chat_data if chat_data is not None else {})


def personal(session, project_id: int) -> PersonalRecord | None:
    return session.get(PersonalRecord, project_id)


# --- local helper: a callback update with full control over query.message / edit side-effects -----

def make_cb(data: str, *, chat_id: int = OWNER_ID, message="عنوان المشروع", edit_side_effect=None):
    """Like ``make_callback_update`` but lets a test pass ``message=None`` (no attached message) or an
    ``edit_side_effect`` (e.g. a ``BadRequest``) so the ``_confirm`` branches can be exercised."""
    msg = None if message is None else SimpleNamespace(text=message, reply_text=AsyncMock())
    query = SimpleNamespace(
        data=data,
        message=msg,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(side_effect=edit_side_effect),
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        callback_query=query,
        message=None,
    )


def _no_message_update(*, chat_id: int = OWNER_ID):
    """An owner update whose ``.message`` is ``None`` (e.g. an edited_message/channel_post update)."""
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=None,
        callback_query=None,
    )


# ================================================================================================
# callbacks.py
# ================================================================================================

@pytest.mark.asyncio
async def test_callback_with_no_query_returns_silently(bot_db):
    """``handle_callback`` with ``update.callback_query is None`` (owner) returns without touching
    anything — covers the ``query is None`` guard."""
    from mostaql_notifier.bot import callbacks

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=OWNER_ID), callback_query=None, message=None
    )
    assert await callbacks.handle_callback(update, make_context()) is None


@pytest.mark.asyncio
async def test_non_owner_callback_makes_no_service_call(bot_db):
    """A stranger's tap is dropped before the query is even answered (owner gate, fail-closed)."""
    from mostaql_notifier.bot import callbacks

    update = make_cb(build_callback_data("fav", 1), chat_id=STRANGER_ID)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_not_awaited()
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_callback_data_only_answers(bot_db):
    """``callback_data`` that isn't our ``pf:*`` codec just clears the spinner (no edit, no mutate)."""
    from mostaql_notifier.bot import callbacks

    update = make_cb("totally:foreign:payload")
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_once_with()
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_project_answers_not_found(bot_db):
    """A tap on a vanished/expired project answers "المشروع غير موجود" and never edits."""
    from mostaql_notifier.bot import callbacks

    update = make_cb(build_callback_data("fav", 999123))
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_once_with("المشروع غير موجود")
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_favorite_writes_a_single_footer(bot_db):
    """A favorite tap appends exactly one ``— ★ مفضّل`` footer to the original body."""
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)

    update = make_cb(build_callback_data("fav", p.id), message="عنوان رائع")
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_with("★ مفضّل")
    update.callback_query.edit_message_text.assert_awaited_once_with("عنوان رائع\n\n— ★ مفضّل")
    with bot_db() as s:
        assert personal(s, p.id).favorite is True


@pytest.mark.asyncio
async def test_applied_footer_new_then_already(bot_db):
    """First ✅ tap → "سُجّل التقديم"; a re-tap converges to "سبق التسجيل" (applied-once)."""
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)

    first = make_cb(build_callback_data("app", p.id), message="عنوان")
    await callbacks.handle_callback(first, make_context())
    first.callback_query.edit_message_text.assert_awaited_once_with("عنوان\n\n— ✅ سُجّل التقديم")

    again = make_cb(build_callback_data("app", p.id), message="عنوان")
    await callbacks.handle_callback(again, make_context())
    again.callback_query.answer.assert_awaited_with("سبق التسجيل")
    again.callback_query.edit_message_text.assert_awaited_once_with("عنوان\n\n— سبق التسجيل")


@pytest.mark.asyncio
async def test_confirm_with_no_message_edits_confirmation_only(bot_db):
    """When ``query.message`` is ``None`` the body collapses to ``""`` so the edited text is just the
    confirmation — yet ``edit_message_text`` is still called (covers the message-None ``_confirm``)."""
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)

    update = make_cb(build_callback_data("dis", p.id), message=None)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_with("🙈 تم الإخفاء")
    update.callback_query.edit_message_text.assert_awaited_once_with("🙈 تم الإخفاء")
    with bot_db() as s:
        assert personal(s, p.id).hidden is True


@pytest.mark.asyncio
async def test_confirm_rewrites_an_existing_footer(bot_db):
    """A re-tap on an already-footered message rewrites (not stacks) the footer — idempotent body."""
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)

    pre_footered = "النص الأصلي\n\n— حالة قديمة"
    update = make_cb(build_callback_data("dis", p.id), message=pre_footered)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.edit_message_text.assert_awaited_once_with("النص الأصلي\n\n— 🙈 تم الإخفاء")


@pytest.mark.asyncio
async def test_confirm_swallows_badrequest_not_modified(bot_db):
    """A "message is not modified" ``BadRequest`` from Telegram is swallowed (state already matches);
    the mutation still lands."""
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)

    update = make_cb(
        build_callback_data("dis", p.id),
        message="عنوان",
        edit_side_effect=BadRequest("Message is not modified"),
    )
    # Must not raise.
    await callbacks.handle_callback(update, make_context())

    update.callback_query.edit_message_text.assert_awaited_once()
    with bot_db() as s:
        assert personal(s, p.id).hidden is True


@pytest.mark.asyncio
async def test_note_tap_records_pending_and_prompts(bot_db):
    """Tapping 📝 opens the force-reply flow: pending id stored + a ForceReply prompt sent (covers the
    ``CB_NOTE`` dispatch and ``start_note``'s happy path)."""
    from mostaql_notifier.bot import callbacks, conversation

    with bot_db() as s:
        p = make_project(s)

    ctx = make_context()
    update = make_cb(build_callback_data("note", p.id), message="عنوان")
    await callbacks.handle_callback(update, ctx)

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.message.reply_text.assert_awaited_once()
    update.callback_query.edit_message_text.assert_not_awaited()  # note never edits the message
    assert ctx.chat_data[conversation.PENDING_KEY] == p.id


# ================================================================================================
# commands.py
# ================================================================================================

@pytest.mark.asyncio
async def test_set_paused_inserts_missing_settings_row(bot_db):
    """``_set_paused`` INSERTs the ``watcher_paused`` row when it is absent (the else branch) — verify
    by deleting the seeded row first, then ``/pause``."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        s.delete(s.get(Setting, _PAUSED_KEY))
        s.commit()
        assert s.get(Setting, _PAUSED_KEY) is None

    pause = make_message_update("/pause")
    await commands.pause_command(pause, make_context())

    with bot_db() as s:
        row = s.get(Setting, _PAUSED_KEY)
        assert row is not None  # INSERT branch ran
        assert SettingsStore(s).get_bool(_PAUSED_KEY) is True
    pause.message.reply_text.assert_awaited_with("⏸️ تم الإيقاف المؤقت")


@pytest.mark.asyncio
async def test_all_commands_with_no_message_return_silently(bot_db):
    """find/pause/resume/health/stats with ``update.message is None`` return without crash or reply,
    and pause/resume leave the flag untouched."""
    from mostaql_notifier.bot import commands

    for fn in (
        commands.find_command,
        commands.pause_command,
        commands.resume_command,
        commands.health_command,
        commands.stats_command,
    ):
        update = _no_message_update()
        assert await fn(update, make_context(args=["كلمة"])) is None

    with bot_db() as s:
        assert SettingsStore(s).get_bool(_PAUSED_KEY) is False  # never mutated


@pytest.mark.asyncio
async def test_all_commands_ignore_non_owner(bot_db):
    """A stranger's command never replies and never flips the watcher flag (owner gate on each)."""
    from mostaql_notifier.bot import commands

    for fn in (
        commands.find_command,
        commands.pause_command,
        commands.resume_command,
        commands.health_command,
        commands.stats_command,
    ):
        update = make_message_update("/x", chat_id=STRANGER_ID)
        await fn(update, make_context(args=["كلمة"]))
        update.message.reply_text.assert_not_awaited()

    with bot_db() as s:
        assert SettingsStore(s).get_bool(_PAUSED_KEY) is False


@pytest.mark.asyncio
async def test_find_with_none_args_shows_usage(bot_db):
    """``/find`` with ``context.args is None`` → the usage string (no crash on ``" ".join(None)``)."""
    from mostaql_notifier.bot import commands

    update = make_message_update("/find")
    await commands.find_command(update, make_context(args=None))

    update.message.reply_text.assert_awaited_once_with("الاستخدام: /find <كلمة>")


@pytest.mark.asyncio
async def test_find_with_whitespace_only_args_shows_usage(bot_db):
    """Whitespace-only args strip to empty → usage string, never a search."""
    from mostaql_notifier.bot import commands

    update = make_message_update("/find    ")
    await commands.find_command(update, make_context(args=["   ", "  "]))

    update.message.reply_text.assert_awaited_once_with("الاستخدام: /find <كلمة>")


@pytest.mark.asyncio
async def test_find_renders_with_and_without_url(bot_db):
    """A matching project with a URL renders the link; one without a URL still renders its title line
    (covers both arms of the per-result ternary)."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_project(s, n=1, title="بحث فريد ألفا", url="https://mostaql.com/project/1")
        make_project(s, n=2, title="بحث فريد بيتا", url=None)

    update = make_message_update("/find فريد")
    await commands.find_command(update, make_context(args=["فريد"]))

    sent = update.message.reply_text.await_args.args[0]
    assert "بحث فريد ألفا" in sent
    assert "https://mostaql.com/project/1" in sent
    assert "بحث فريد بيتا" in sent  # url-less result line still present


@pytest.mark.asyncio
async def test_find_no_matches_reports_none(bot_db):
    """No matches → "لا نتائج"."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_project(s, n=1, title="شيء مختلف")

    update = make_message_update("/find سلسلة_لن_تطابق_شيئا")
    await commands.find_command(update, make_context(args=["سلسلة_لن_تطابق_شيئا"]))

    update.message.reply_text.assert_awaited_with("لا نتائج")


@pytest.mark.asyncio
async def test_pause_resume_full_cycle_with_idempotent_replies(bot_db):
    """pause→(already)→resume→(already): both the set branch and the idempotent already-in-state reply
    of pause and resume, plus the ``_set_paused`` row-exists UPDATE branch."""
    from mostaql_notifier.bot import commands

    p1 = make_message_update("/pause")
    await commands.pause_command(p1, make_context())
    p1.message.reply_text.assert_awaited_with("⏸️ تم الإيقاف المؤقت")
    with bot_db() as s:
        assert SettingsStore(s).get_bool(_PAUSED_KEY) is True

    p2 = make_message_update("/pause")
    await commands.pause_command(p2, make_context())
    p2.message.reply_text.assert_awaited_with("متوقّف مؤقتًا بالفعل")

    r1 = make_message_update("/resume")
    await commands.resume_command(r1, make_context())
    r1.message.reply_text.assert_awaited_with("▶️ تم الاستئناف")
    with bot_db() as s:
        assert SettingsStore(s).get_bool(_PAUSED_KEY) is False

    r2 = make_message_update("/resume")
    await commands.resume_command(r2, make_context())
    r2.message.reply_text.assert_awaited_with("يعمل بالفعل")


@pytest.mark.asyncio
async def test_health_with_successful_run_reports_counts_and_time(bot_db):
    """``/health`` with a successful run reports its status + counts, "آخر نجاح" time, and "يعمل"."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        s.add(
            ScrapeRun(
                started_at=_utc(),
                finished_at=_utc(),
                found_count=5,
                new_count=1,
                updated_count=2,
                error_count=0,
                status=RunStatus.success,
            )
        )
        s.commit()

    update = make_message_update("/health")
    await commands.health_command(update, make_context())

    sent = update.message.reply_text.await_args.args[0]
    assert "success" in sent
    assert "عُثر 5" in sent
    assert "يعمل" in sent
    # last-successful line carries an ISO timestamp (a 'T'), not the em dash.
    last_line = [ln for ln in sent.splitlines() if ln.startswith("آخر نجاح:")][0]
    assert "T" in last_line and "—" not in last_line


@pytest.mark.asyncio
async def test_health_with_no_run_renders_em_dashes(bot_db):
    """With no scrape run at all, the latest-run counts and last-successful time render as em dashes
    (covers the ``_or_dash(None)`` and ``last is None`` arms)."""
    from mostaql_notifier.bot import commands

    update = make_message_update("/health")
    await commands.health_command(update, make_context())

    sent = update.message.reply_text.await_args.args[0]
    assert "آخر تشغيل: —" in sent
    assert "عُثر — · جديد —" in sent
    assert "آخر نجاح: —" in sent


@pytest.mark.asyncio
async def test_stats_reports_totals_paused_and_stage_lines(bot_db):
    """``/stats`` renders totals, the paused/running line, and a per-stage breakdown."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        p = make_project(s, n=1)
        make_project(s, n=2)
        s.add(PersonalRecord(project_id=p.id, status="interested", favorite=False, tags=[]))
        s.commit()

    update = make_message_update("/stats")
    await commands.stats_command(update, make_context())

    sent = update.message.reply_text.await_args.args[0]
    assert "📊 الإحصائيات" in sent
    assert "مشاريع 2" in sent
    assert "مهتم: 1" in sent
    assert "جديد: 0" in sent
    assert "يعمل" in sent


# ================================================================================================
# conversation.py  (add-note force-reply flow)
# ================================================================================================

@pytest.mark.asyncio
async def test_start_note_with_chat_data_none_still_answers_and_prompts():
    """``start_note`` tolerates ``context.chat_data is None`` (can't record pending) but still answers
    the callback and sends the ForceReply prompt."""
    from mostaql_notifier.bot import conversation

    answer, reply = AsyncMock(), AsyncMock()
    query = SimpleNamespace(answer=answer, message=SimpleNamespace(reply_text=reply))
    update = SimpleNamespace(callback_query=query)
    ctx = SimpleNamespace(args=None, chat_data=None)

    await conversation.start_note(update, ctx, 7)

    answer.assert_awaited_once()
    reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_note_with_query_none_only_records_pending():
    """No callback query (defensive) → still records the pending id, never tries to answer/prompt."""
    from mostaql_notifier.bot import conversation

    ctx = SimpleNamespace(args=None, chat_data={})
    update = SimpleNamespace(callback_query=None)

    await conversation.start_note(update, ctx, 9)

    assert ctx.chat_data[conversation.PENDING_KEY] == 9


@pytest.mark.asyncio
async def test_start_note_with_message_none_answers_without_prompt():
    """A query with no attached message → answer the callback but skip the (impossible) prompt."""
    from mostaql_notifier.bot import conversation

    answer = AsyncMock()
    query = SimpleNamespace(answer=answer, message=None)
    update = SimpleNamespace(callback_query=query)
    ctx = SimpleNamespace(args=None, chat_data={})

    await conversation.start_note(update, ctx, 3)

    answer.assert_awaited_once()
    assert ctx.chat_data[conversation.PENDING_KEY] == 3


@pytest.mark.asyncio
async def test_note_reply_from_non_owner_is_dropped(bot_db):
    """A stranger's reply is dropped before pending is read or consumed."""
    from mostaql_notifier.bot import conversation

    update = make_message_update("ملاحظة", chat_id=STRANGER_ID)
    ctx = make_context(chat_data={conversation.PENDING_KEY: 1})

    await conversation.handle_note_reply(update, ctx)

    update.message.reply_text.assert_not_awaited()
    assert ctx.chat_data[conversation.PENDING_KEY] == 1  # not consumed


@pytest.mark.asyncio
async def test_note_reply_with_chat_data_none_is_ignored(bot_db):
    """Owner reply but ``chat_data is None`` → no pending → plain text left alone."""
    from mostaql_notifier.bot import conversation

    update = make_message_update("نص عابر")
    ctx = SimpleNamespace(args=None, chat_data=None)

    await conversation.handle_note_reply(update, ctx)

    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_note_reply_without_pending_key_is_ignored(bot_db):
    """Owner reply with an empty ``chat_data`` (no pending key) → ignored."""
    from mostaql_notifier.bot import conversation

    update = make_message_update("نص عابر آخر")
    await conversation.handle_note_reply(update, make_context())  # chat_data={}

    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_note_reply_whitespace_text_cancels_and_clears_pending(bot_db):
    """A whitespace-only reply cancels gracefully ("تم الإلغاء"), consumes the pending target, and
    writes nothing."""
    from mostaql_notifier.bot import conversation

    with bot_db() as s:
        p = make_project(s)

    ctx = make_context(chat_data={conversation.PENDING_KEY: p.id})
    update = make_message_update("   \n\t ")
    await conversation.handle_note_reply(update, ctx)

    update.message.reply_text.assert_awaited_once_with("تم الإلغاء")
    assert conversation.PENDING_KEY not in ctx.chat_data
    with bot_db() as s:
        assert personal(s, p.id) is None  # no record created


@pytest.mark.asyncio
async def test_note_reply_with_message_none_clears_pending_silently(bot_db):
    """A pending note but ``update.message is None`` (defensive): pending is consumed, no reply, no
    write (covers the message-None arms of the text extraction + cancel guard)."""
    from mostaql_notifier.bot import conversation

    ctx = make_context(chat_data={conversation.PENDING_KEY: 555})
    update = _no_message_update()

    await conversation.handle_note_reply(update, ctx)

    assert conversation.PENDING_KEY not in ctx.chat_data  # consumed even with no message


@pytest.mark.asyncio
async def test_note_reply_for_deleted_project_reports_not_found(bot_db):
    """A pending note whose project was deleted → "المشروع غير موجود" and pending cleared."""
    from mostaql_notifier.bot import conversation

    with bot_db() as s:
        p = make_project(s)
        pid = p.id
        s.delete(s.get(Project, pid))
        s.commit()

    ctx = make_context(chat_data={conversation.PENDING_KEY: pid})
    update = make_message_update("ملاحظة لمشروع محذوف")
    await conversation.handle_note_reply(update, ctx)

    update.message.reply_text.assert_awaited_once_with("المشروع غير موجود")
    assert conversation.PENDING_KEY not in ctx.chat_data
    with bot_db() as s:
        assert personal(s, pid) is None


@pytest.mark.asyncio
async def test_note_reply_happy_path_appends_and_confirms(bot_db):
    """The owner's text is appended to the project's notes and confirmed with "حُفظت الملاحظة"."""
    from mostaql_notifier.bot import conversation

    with bot_db() as s:
        p = make_project(s)

    ctx = make_context(chat_data={conversation.PENDING_KEY: p.id})
    update = make_message_update("ملاحظة محفوظة")
    await conversation.handle_note_reply(update, ctx)

    update.message.reply_text.assert_awaited_once_with("📝 حُفظت الملاحظة")
    assert conversation.PENDING_KEY not in ctx.chat_data
    with bot_db() as s:
        assert personal(s, p.id).notes == "ملاحظة محفوظة"
