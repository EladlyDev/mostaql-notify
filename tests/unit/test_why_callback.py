"""Unit tests for the Feature-4 "Why?" callback handler (T046).

The ``pf:why:{id}`` tap is a **read**: it replies with the stored score breakdown and must never
mutate the record nor edit the original notification (so the Feature-3 buttons survive). Exercised
directly with fakes — no real ``Application``, no network — mirroring ``test_inbound_bot.py``: the DB
is a per-test temp SQLite reached through the bot's own ``get_sessionmaker()`` and
``TELEGRAM_CHAT_ID`` is pinned so :func:`is_owner` resolves deterministically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mostaql_notifier.config import secrets as secrets_mod
from mostaql_notifier.config.settings_store import seed_defaults
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db import session as session_mod
from mostaql_notifier.db.models import (
    EvalStatus,
    Outcome,
    PersonalRecord,
    Project,
    ProjectScore,
    ProjectStatus,
)
from mostaql_notifier.notify.format import build_callback_data

OWNER_ID = 424242

_BREAKDOWN = {
    "score": 82.0,
    "components": [
        {"key": "hiring_rate", "label": "معدل التوظيف", "contribution": 28.5},
        {"key": "hire_volume", "label": "حجم التوظيف", "contribution": 9.2},
        {"key": "budget", "label": "الميزانية", "contribution": 11.0},
        {"key": "competition", "label": "المنافسة", "contribution": 14.8},
        {"key": "freshness", "label": "الحداثة", "contribution": 6.5},
        {"key": "rating", "label": "تقييم العميل", "contribution": 12.0},
    ],
}


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
        description="وصف",
        url=f"https://mostaql.com/project/{n}",
        category="development",
        skills=[],
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


def make_score(session, project_id, *, score=82.0, breakdown=None, tracking_active=True):
    row = ProjectScore(
        project_id=project_id,
        score=score,
        breakdown=breakdown if breakdown is not None else dict(_BREAKDOWN),
        computed_at=_utc(),
        outcome=Outcome.open,
        tracking_active=tracking_active,
    )
    session.add(row)
    session.commit()
    return row


def make_why_update(project_id: int, *, chat_id: int = OWNER_ID):
    message = SimpleNamespace(text="مشروع تطوير 1", reply_text=AsyncMock())
    query = SimpleNamespace(
        data=build_callback_data("why", project_id),
        message=message,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        callback_query=query,
        message=None,
    )


def make_context(args=None):
    return SimpleNamespace(args=args, chat_data={})


def personal(session, project_id: int) -> PersonalRecord | None:
    return session.get(PersonalRecord, project_id)


# --- the handler --------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_why_replies_with_per_component_breakdown_without_editing(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)
        make_score(s, p.id)

    update = make_why_update(p.id)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited()  # spinner cleared
    update.callback_query.message.reply_text.assert_awaited_once()
    call = update.callback_query.message.reply_text.await_args
    sent = call.args[0]
    assert "🎯 تقييم الفرصة: 82 / 100" in sent
    for comp in _BREAKDOWN["components"]:
        assert comp["label"] in sent
    assert call.kwargs.get("parse_mode") == "HTML"

    # Read-only + non-destructive: no record created, original message never edited.
    update.callback_query.edit_message_text.assert_not_awaited()
    with bot_db() as s:
        assert personal(s, p.id) is None


@pytest.mark.asyncio
async def test_why_is_idempotent_on_a_closed_frozen_project(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        # Closed project whose breakdown is frozen at the last open re-check (tracking stopped).
        p = make_project(s, site_status=ProjectStatus.closed)
        make_score(s, p.id, tracking_active=False)

    # Re-tapping yields the same stored breakdown each time; never an error, never an edit.
    for _ in range(2):
        update = make_why_update(p.id)
        await callbacks.handle_callback(update, make_context())
        update.callback_query.answer.assert_awaited()
        sent = update.callback_query.message.reply_text.await_args.args[0]
        assert "🎯 تقييم الفرصة: 82 / 100" in sent
        update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_why_on_unscored_project_answers_no_score(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)  # exists but never scored (no ProjectScore row)

    update = make_why_update(p.id)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_with()  # bare answer to clear the spinner
    update.callback_query.message.reply_text.assert_awaited_with("لا يوجد تقييم لهذا المشروع بعد")
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_why_on_missing_project_answers_not_found(bot_db):
    from mostaql_notifier.bot import callbacks

    update = make_why_update(9999)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_with("المشروع غير موجود")
    update.callback_query.message.reply_text.assert_not_awaited()
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_why_from_non_owner_is_ignored(bot_db):
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s)
        make_score(s, p.id)

    update = make_why_update(p.id, chat_id=999999)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_not_awaited()
    update.callback_query.message.reply_text.assert_not_awaited()
