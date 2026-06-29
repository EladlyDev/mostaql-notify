"""Adversarial / edge tests for the Feature-4 scoring additions to the bot + notifications.

These complement (and deliberately do NOT duplicate) ``test_format_score.py``, ``test_why_callback.py``,
``test_top_command.py`` and ``test_telegram_keyboard.py``. They pin the corners those happy-path suites
leave open:

  * the score headline is omitted only on ``None`` — a genuine ``0`` score still renders (no falsy bug);
  * ``build_score_breakdown_message`` is total: a ``None`` breakdown, a missing ``components`` key, a
    component without a ``label`` and a ``None``/negative contribution all degrade gracefully, never
    raising and never leaking the literal string ``"None"``;
  * the "Why?" callback is strictly read-only — it answers the spinner *before* replying, never edits the
    original message, and never calls any ``personal/service`` mutation;
  * ``/top`` clamps ``0`` / negative ``n`` up to ``1``, honours a re-configured ``top_default_count``,
    renders ``Tier ?`` / no-link rows, and no-ops on a ``None`` message;
  * the app wires ``/top`` to ``top_command`` and routes the "Why?" tap through ``handle_callback``.

All offline: no real Telegram, no network. The DB is a per-test temp SQLite reached through the bot's own
``get_sessionmaker()`` and ``TELEGRAM_CHAT_ID`` is pinned so ``is_owner`` resolves deterministically.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from mostaql_notifier.config import secrets as secrets_mod
from mostaql_notifier.config.settings_store import _serialize, seed_defaults
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db import session as session_mod
from mostaql_notifier.db.models import (
    Client,
    EvalStatus,
    Outcome,
    PersonalRecord,
    Project,
    ProjectScore,
    ProjectStatus,
    Setting,
)
from mostaql_notifier.notify.format import (
    build_callback_data,
    build_project_message,
    build_score_breakdown_message,
)

OWNER_ID = 424242
_RANK_LINE = re.compile(r"^\d+\. ", re.MULTILINE)


@pytest.fixture
def bot_db(tmp_path, monkeypatch):
    """Point the shared session layer + secrets at a per-test temp DB and known owner chat."""
    db_path = tmp_path / "bot_edge.db"
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
        title=f"مشروع {n}",
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


def make_scored(session, n: int, score: float, **over) -> Project:
    p = make_project(session, n, **over)
    session.add(
        ProjectScore(
            project_id=p.id,
            score=score,
            breakdown={"score": score, "components": []},
            computed_at=_utc(),
            outcome=Outcome.open,
            tracking_active=True,
        )
    )
    session.commit()
    return p


def set_top_default(session, value: int) -> None:
    row = session.get(Setting, "top_default_count")
    row.value = _serialize(value, "int")
    row.value_type = "int"
    session.commit()


def make_why_update(project_id: int, *, chat_id: int = OWNER_ID, msg_text: str = "النص الأصلي"):
    message = SimpleNamespace(text=msg_text, reply_text=AsyncMock())
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


def make_message_update(text: str, *, chat_id: int = OWNER_ID):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=message,
        callback_query=None,
    )


def make_context(args=None):
    return SimpleNamespace(args=args, chat_data={})


def _sent(update) -> str:
    return update.message.reply_text.await_args.args[0]


# ==================================================================================================
# FORMAT — the 🎯 Score headline line
# ==================================================================================================

def _make_pair(now, *, score, tier=1):
    client = Client(
        mostaql_id="derived:edge",
        name="عميل",
        hiring_rate=80.0,
        last_refreshed_at=now,
        first_seen_at=now,
        raw={},
    )
    project = Project(
        mostaql_id="proj-edge",
        title="تطوير موقع",
        url="https://mostaql.com/project/proj-edge",
        category="تطوير",
        budget_min=Decimal("250"),
        budget_max=Decimal("500"),
        currency="USD",
        bids_count=7,
        posted_at=now - timedelta(hours=2),
        scraped_at=now,
        tier=tier,
        raw={},
    )
    if score is not None:
        project.score_row = ProjectScore(score=score, breakdown={"score": score, "components": []})
    return project, client


def test_score_line_renders_for_a_genuine_zero_score():
    """Omission is keyed on ``None``, not falsiness — a real ``0`` score must still print the line."""
    now = _utc()
    project, client = _make_pair(now, score=0.0, tier=3)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "🎯 Score: 0 · Tier 3" in msg
    assert "None" not in msg


def test_score_line_omitted_keeps_rest_and_never_prints_none():
    """An unscored project drops only the headline; no ``None`` leaks anywhere in the message."""
    now = _utc()
    project, client = _make_pair(now, score=None)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "🎯 Score:" not in msg
    assert "None" not in msg
    assert "💰" in msg  # the rest of the body survives intact


def test_score_headline_uses_bankers_rounding_for_a_half():
    """``round`` is banker's rounding: 82.5 → 82 (nearest even). Pin the actual behaviour."""
    now = _utc()
    project, client = _make_pair(now, score=82.5, tier=1)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "🎯 Score: 82 · Tier 1" in msg
    assert "82.5" not in msg


# ==================================================================================================
# FORMAT — build_score_breakdown_message totality
# ==================================================================================================

def test_breakdown_none_degrades_to_header_only():
    """A ``None`` breakdown (nullable column) must not raise — it degrades to a 0/100 header."""
    project = SimpleNamespace(title="بلا تقييم")

    msg = build_score_breakdown_message(project, None)

    assert "🎯 تقييم الفرصة: 0 / 100" in msg
    assert "<b>بلا تقييم</b>" in msg
    assert "نقطة" not in msg
    assert "None" not in msg


def test_breakdown_missing_components_key_renders_no_component_lines():
    project = SimpleNamespace(title="عنوان")

    msg = build_score_breakdown_message(project, {"score": 55})

    assert "🎯 تقييم الفرصة: 55 / 100" in msg
    assert "نقطة" not in msg
    assert "None" not in msg


def test_breakdown_component_missing_label_and_none_contribution_is_zeroed():
    project = SimpleNamespace(title="عنوان")

    msg = build_score_breakdown_message(
        project,
        {"score": 40, "components": [{"contribution": None}, {"label": "الميزانية"}]},
    )

    # Missing label → empty label; missing/None contribution → 0.0 نقطة; never raises, no "None".
    assert "• : 0.0 نقطة" in msg
    assert "• الميزانية: 0.0 نقطة" in msg
    assert "None" not in msg


def test_breakdown_negative_contribution_keeps_its_sign():
    project = SimpleNamespace(title="عنوان")

    msg = build_score_breakdown_message(
        project,
        {"score": 12, "components": [{"label": "المنافسة", "contribution": -3.2}]},
    )

    assert "• المنافسة: -3.2 نقطة" in msg


def test_breakdown_html_escapes_a_malicious_label():
    project = SimpleNamespace(title="عنوان")

    msg = build_score_breakdown_message(
        project,
        {"score": 50, "components": [{"label": "<b>x</b>", "contribution": 5.0}]},
    )

    assert "&lt;b&gt;x&lt;/b&gt;" in msg
    assert "<b>x</b>" not in msg.replace("<b>عنوان</b>", "")  # the only real <b> is the title


# ==================================================================================================
# CALLBACK — the "Why?" tap is strictly read-only
# ==================================================================================================

@pytest.mark.asyncio
async def test_why_answers_spinner_before_replying(bot_db):
    """Read-only contract: the spinner is cleared (``answer``) *before* the breakdown reply is sent."""
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_scored(s, n=1, score=77.0)

    update = make_why_update(p.id)
    manager = Mock()
    manager.attach_mock(update.callback_query.answer, "answer")
    manager.attach_mock(update.callback_query.message.reply_text, "reply")

    await callbacks.handle_callback(update, make_context())

    ordered = [name for name, _, _ in manager.mock_calls]
    assert ordered.index("answer") < ordered.index("reply")
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_why_never_calls_a_personal_service_mutation(bot_db, monkeypatch):
    """A "Why?" tap must reach no mutation path — guard every ``personal/service`` writer."""
    from mostaql_notifier.bot import callbacks

    def _boom(*a, **k):  # pragma: no cover - asserts it is never reached
        raise AssertionError("Why? must not mutate")

    for name in ("toggle_favorite", "get_or_create", "set_applied", "hide"):
        monkeypatch.setattr(callbacks.service, name, _boom)

    with bot_db() as s:
        p = make_scored(s, n=1, score=77.0)

    update = make_why_update(p.id)
    await callbacks.handle_callback(update, make_context())

    update.callback_query.message.reply_text.assert_awaited_once()
    with bot_db() as s:  # no personal record was ever created
        assert s.get(PersonalRecord, p.id) is None


@pytest.mark.asyncio
async def test_why_renders_zero_total_when_stored_score_is_missing(bot_db):
    """A stored breakdown without a ``score`` key replies "0 / 100" rather than crashing."""
    from mostaql_notifier.bot import callbacks

    with bot_db() as s:
        p = make_project(s, n=1)
        s.add(
            ProjectScore(
                project_id=p.id,
                score=64.0,  # row qualifies as "scored" so get_breakdown returns the dict
                breakdown={"components": [{"label": "الميزانية", "contribution": 9.0}]},
                computed_at=_utc(),
                outcome=Outcome.open,
                tracking_active=True,
            )
        )
        s.commit()

    update = make_why_update(p.id)
    await callbacks.handle_callback(update, make_context())

    sent = update.callback_query.message.reply_text.await_args.args[0]
    assert "🎯 تقييم الفرصة: 0 / 100" in sent
    assert "• الميزانية: 9.0 نقطة" in sent
    assert "None" not in sent


# ==================================================================================================
# COMMANDS — /top clamping, configurability, and rendering corners
# ==================================================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("arg", ["0", "-5"])
async def test_top_clamps_zero_or_negative_to_one(bot_db, arg):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        for i in range(3):
            make_scored(s, n=i + 1, score=(i + 1) * 10.0)

    update = make_message_update(f"/top {arg}")
    await commands.top_command(update, make_context(args=[arg]))

    sent = _sent(update)
    assert len(_RANK_LINE.findall(sent)) == 1  # clamped up to 1, never an error
    assert "🏆 أفضل 1 مشاريع مفتوحة" in sent
    assert "· 30 ·" in sent  # the single highest-scored project


@pytest.mark.asyncio
async def test_top_honours_reconfigured_default_count(bot_db):
    """``/top`` with no arg uses the *current* ``top_default_count`` setting, not a hard-coded 5."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        set_top_default(s, 3)
        for i in range(6):
            make_scored(s, n=i + 1, score=(i + 1) * 10.0)

    update = make_message_update("/top")
    await commands.top_command(update, make_context(args=[]))

    sent = _sent(update)
    assert len(_RANK_LINE.findall(sent)) == 3
    assert "🏆 أفضل 3 مشاريع مفتوحة" in sent


@pytest.mark.asyncio
async def test_top_renders_tier_question_mark_and_no_link_row(bot_db):
    """A scored project with no tier and no URL renders ``Tier ?`` and omits the link line."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_scored(s, n=1, score=88.0, tier=None, url=None)

    update = make_message_update("/top")
    await commands.top_command(update, make_context(args=[]))

    sent = _sent(update)
    assert len(_RANK_LINE.findall(sent)) == 1
    assert "· 88 · Tier ?" in sent
    assert "https://" not in sent  # no URL → no link line appended
    assert "None" not in sent


@pytest.mark.asyncio
async def test_top_uses_only_first_arg_token(bot_db):
    """Extra tokens after the count are ignored (``context.args[0]`` only)."""
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        for i in range(4):
            make_scored(s, n=i + 1, score=(i + 1) * 10.0)

    update = make_message_update("/top 2 garbage extra")
    await commands.top_command(update, make_context(args=["2", "garbage", "extra"]))

    assert len(_RANK_LINE.findall(_sent(update))) == 2


@pytest.mark.asyncio
async def test_top_with_no_message_is_a_silent_noop(bot_db):
    """An owner update that somehow carries no ``message`` returns without raising or replying."""
    from mostaql_notifier.bot import commands

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=OWNER_ID), message=None, callback_query=None
    )
    await commands.top_command(update, make_context(args=[]))  # must not raise


# ==================================================================================================
# APP WIRING — /top and the Why? route
# ==================================================================================================

def test_top_command_is_wired_to_top_command_callable():
    from telegram.ext import CallbackQueryHandler, CommandHandler

    from mostaql_notifier.bot import callbacks, commands
    from mostaql_notifier.bot.app import build_application

    application = build_application("123456:TESTTOKEN")
    flat = [h for group in application.handlers.values() for h in group]

    top_handlers = [
        h for h in flat if isinstance(h, CommandHandler) and "top" in h.commands
    ]
    assert len(top_handlers) == 1
    assert top_handlers[0].callback is commands.top_command

    # The single CallbackQueryHandler routes every pf:* tap (incl. the Feature-4 "Why?") through one
    # dispatcher; there is no per-action pattern — handle_callback parses the codec itself.
    cb_handlers = [h for h in flat if isinstance(h, CallbackQueryHandler)]
    assert len(cb_handlers) == 1
    assert cb_handlers[0].callback is callbacks.handle_callback
