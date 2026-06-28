"""Unit tests for the inbound Telegram bot handlers (Feature 3, US4).

The handler functions are exercised **directly** with fakes — no real ``Application``, no network.
Awaited Telegram methods (``answer``, ``edit_message_text``, ``reply_text``) are ``AsyncMock``s; the
DB is a per-test temp SQLite reached through the bot's own ``get_sessionmaker()`` (the
``api/conftest.py`` ``_reset_engine_to`` pattern), and ``TELEGRAM_CHAT_ID`` is pinned to a known
owner so :func:`is_owner` resolves deterministically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
)
from mostaql_notifier.notify.format import build_callback_data

OWNER_ID = 424242
STRANGER_ID = 999999


# --- env / DB fixture (mirrors tests/api/conftest.py) ---------------------------------------------

@pytest.fixture
def bot_db(tmp_path, monkeypatch):
    """Point the shared session layer + secrets at a per-test temp DB and known owner chat."""
    db_path = tmp_path / "bot_test.db"
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


# --- fake Telegram update/context ---------------------------------------------------------------

def make_callback_update(callback_data: str, *, chat_id: int = OWNER_ID):
    """A fake callback-query update with AsyncMock answer/edit/reply methods."""
    message = SimpleNamespace(
        text="مشروع تطوير 1",
        reply_text=AsyncMock(),
    )
    query = SimpleNamespace(
        data=callback_data,
        message=message,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        callback_query=query,
        message=None,
    )
    return update


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


# --- callbacks ----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_owner_callback_is_ignored(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)
    update = make_callback_update(build_callback_data("fav", p.id), chat_id=STRANGER_ID)

    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_not_awaited()
    update.callback_query.edit_message_text.assert_not_awaited()
    with bot_db() as s:
        assert personal(s, p.id) is None  # no record created → no service call


@pytest.mark.asyncio
async def test_favorite_toggles_and_answers_and_edits(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)

    update = make_callback_update(build_callback_data("fav", p.id))
    await callbacks.handle_callback(update, make_context())
    with bot_db() as s:
        assert personal(s, p.id).favorite is True
    update.callback_query.answer.assert_awaited()
    update.callback_query.edit_message_text.assert_awaited()

    # Second tap toggles back off (idempotent convergence, opposite state).
    update2 = make_callback_update(build_callback_data("fav", p.id))
    await callbacks.handle_callback(update2, make_context())
    with bot_db() as s:
        assert personal(s, p.id).favorite is False


@pytest.mark.asyncio
async def test_applied_sets_status_and_date_then_idempotent(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)

    update = make_callback_update(build_callback_data("app", p.id))
    await callbacks.handle_callback(update, make_context())
    with bot_db() as s:
        rec = personal(s, p.id)
        assert rec.status == "applied"
        first_applied = rec.applied_at
        assert first_applied is not None
    update.callback_query.answer.assert_awaited_with("✅ سُجّل التقديم")

    # Re-tap: status stays applied, date is NOT moved, and the toast says "already".
    update2 = make_callback_update(build_callback_data("app", p.id))
    await callbacks.handle_callback(update2, make_context())
    with bot_db() as s:
        assert personal(s, p.id).applied_at == first_applied
    update2.callback_query.answer.assert_awaited_with("سبق التسجيل")


@pytest.mark.asyncio
async def test_dismiss_hides(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)
    update = make_callback_update(build_callback_data("dis", p.id))

    await callbacks.handle_callback(update, make_context())

    with bot_db() as s:
        assert personal(s, p.id).hidden is True
    update.callback_query.answer.assert_awaited_with("🙈 تم الإخفاء")


@pytest.mark.asyncio
async def test_callback_on_missing_project_is_harmless(bot_db):
    from mostaql_notifier.bot import callbacks

    update = make_callback_update(build_callback_data("fav", 9999))
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_with("المشروع غير موجود")
    update.callback_query.edit_message_text.assert_not_awaited()
    with bot_db() as s:
        assert personal(s, 9999) is None


@pytest.mark.asyncio
async def test_foreign_callback_data_answers_without_acting(bot_db):
    from mostaql_notifier.bot import callbacks

    update = make_callback_update("totally:foreign:data")
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited()  # clears the spinner
    update.callback_query.edit_message_text.assert_not_awaited()


# --- add-note conversation ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_note_appends_via_conversation(bot_db):
    from mostaql_notifier.bot import callbacks, conversation

    with bot_db() as s:
        p = make_project(s)

    # 1) Tap the 📝 button → prompt + pending target recorded.
    ctx = make_context()
    tap = make_callback_update(build_callback_data("note", p.id))
    await callbacks.handle_callback(tap, ctx)
    tap.callback_query.answer.assert_awaited()
    tap.callback_query.message.reply_text.assert_awaited()
    assert ctx.chat_data[conversation.PENDING_KEY] == p.id

    # 2) The owner's next text is appended to notes.
    reply = make_message_update("أول ملاحظة")
    await conversation.handle_note_reply(reply, ctx)
    with bot_db() as s:
        assert personal(s, p.id).notes == "أول ملاحظة"
    reply.message.reply_text.assert_awaited_with("📝 حُفظت الملاحظة")
    assert conversation.PENDING_KEY not in ctx.chat_data  # pending consumed

    # 3) A second note appends (never overwrites).
    tap2 = make_callback_update(build_callback_data("note", p.id))
    await callbacks.handle_callback(tap2, ctx)
    reply2 = make_message_update("ملاحظة ثانية")
    await conversation.handle_note_reply(reply2, ctx)
    with bot_db() as s:
        notes = personal(s, p.id).notes
    assert "أول ملاحظة" in notes and "ملاحظة ثانية" in notes


@pytest.mark.asyncio
async def test_note_reply_without_pending_is_ignored(bot_db):
    from mostaql_notifier.bot import conversation

    with bot_db() as s:
        p = make_project(s)
    reply = make_message_update("نص عابر بلا سياق")

    await conversation.handle_note_reply(reply, make_context())

    reply.message.reply_text.assert_not_awaited()
    with bot_db() as s:
        assert personal(s, p.id) is None  # no record touched


# --- commands -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_then_resume_flip_flag(bot_db):
    from mostaql_notifier.bot import commands

    pause = make_message_update("/pause")
    await commands.pause_command(pause, make_context())
    with bot_db() as s:
        assert SettingsStore(s).get_bool("watcher_paused") is True

    # Idempotent: pausing again reports "already paused".
    pause2 = make_message_update("/pause")
    await commands.pause_command(pause2, make_context())
    pause2.message.reply_text.assert_awaited_with("متوقّف مؤقتًا بالفعل")

    resume = make_message_update("/resume")
    await commands.resume_command(resume, make_context())
    with bot_db() as s:
        assert SettingsStore(s).get_bool("watcher_paused") is False

    resume2 = make_message_update("/resume")
    await commands.resume_command(resume2, make_context())
    resume2.message.reply_text.assert_awaited_with("يعمل بالفعل")


@pytest.mark.asyncio
async def test_find_returns_matches_and_links(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_project(s, n=1, title="موقع أخبار بايثون")
        make_project(s, n=2, title="تطبيق جوال", description="شيء آخر تمامًا")

    update = make_message_update("/find أخبار")
    await commands.find_command(update, make_context(args=["أخبار"]))

    update.message.reply_text.assert_awaited_once()
    sent = update.message.reply_text.await_args.args[0]
    assert "موقع أخبار بايثون" in sent
    assert "https://mostaql.com/project/1" in sent
    assert "تطبيق جوال" not in sent


@pytest.mark.asyncio
async def test_find_no_results(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_project(s, n=1, title="موقع أخبار")
    update = make_message_update("/find لا_يوجد_مطلقا")

    await commands.find_command(update, make_context(args=["لا_يوجد_مطلقا"]))

    update.message.reply_text.assert_awaited_with("لا نتائج")


@pytest.mark.asyncio
async def test_find_without_keyword_shows_usage(bot_db):
    from mostaql_notifier.bot import commands

    update = make_message_update("/find")
    await commands.find_command(update, make_context(args=[]))
    sent = update.message.reply_text.await_args.args[0]
    assert "/find" in sent


@pytest.mark.asyncio
async def test_health_reports_run_and_paused_state(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        s.add(
            ScrapeRun(
                started_at=_utc(),
                finished_at=_utc(),
                found_count=7,
                new_count=2,
                updated_count=1,
                error_count=0,
                status=RunStatus.success,
            )
        )
        s.commit()

    update = make_message_update("/health")
    await commands.health_command(update, make_context())

    sent = update.message.reply_text.await_args.args[0]
    assert "success" in sent
    assert "7" in sent  # found count
    assert "يعمل" in sent  # not paused


@pytest.mark.asyncio
async def test_stats_reports_totals_and_per_stage(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        p = make_project(s, n=1)
        make_project(s, n=2)
        # Engage one record in a non-default stage so per-stage shows a count.
        s.add(PersonalRecord(project_id=p.id, status="interested", favorite=False, tags=[]))
        s.commit()

    update = make_message_update("/stats")
    await commands.stats_command(update, make_context())

    sent = update.message.reply_text.await_args.args[0]
    assert "مشاريع 2" in sent  # total projects
    assert "مهتم: 1" in sent  # Arabic label for 'interested', engaged count
    assert "جديد: 0" in sent  # default stage label appears with zero


@pytest.mark.asyncio
async def test_non_owner_command_is_ignored(bot_db):
    from mostaql_notifier.bot import commands

    update = make_message_update("/pause", chat_id=STRANGER_ID)
    await commands.pause_command(update, make_context())

    update.message.reply_text.assert_not_awaited()
    with bot_db() as s:
        assert SettingsStore(s).get_bool("watcher_paused") is False
