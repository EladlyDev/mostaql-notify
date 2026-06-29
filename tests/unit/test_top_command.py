"""Unit tests for the Feature-4 ``/top [n]`` command (T047).

``/top`` lists the top open projects by opportunity score — read-only, never an error. Exercised
directly with fakes (mirroring ``test_inbound_bot.py``): a per-test temp SQLite reached through the
bot's own ``get_sessionmaker()`` and a pinned ``TELEGRAM_CHAT_ID``.
"""
from __future__ import annotations

import re
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
    Project,
    ProjectScore,
    ProjectStatus,
)

OWNER_ID = 424242
_RANK_LINE = re.compile(r"^\d+\. ", re.MULTILINE)


@pytest.fixture
def bot_db(tmp_path, monkeypatch):
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


def make_project(session, n: int, **over) -> Project:
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
    """A qualified + open project carrying a ``ProjectScore`` so it is eligible for ``/top``."""
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


# --- behavior -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_default_count_and_descending_order(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        for i in range(7):  # scores 10,20,...,70 across seven open scored projects
            make_scored(s, n=i + 1, score=(i + 1) * 10.0)

    update = make_message_update("/top")
    await commands.top_command(update, make_context(args=[]))

    sent = _sent(update)
    assert "🏆 أفضل 5 مشاريع مفتوحة" in sent  # default top_default_count == 5
    assert len(_RANK_LINE.findall(sent)) == 5
    # Highest score first; the two lowest (10, 20) are not in the top 5.
    assert sent.index("· 70 ·") < sent.index("· 60 ·") < sent.index("· 30 ·")
    assert "· 20 ·" not in sent and "· 10 ·" not in sent
    assert "https://mostaql.com/project/7" in sent  # links rendered on their own line


@pytest.mark.asyncio
async def test_top_clamps_huge_n_to_twenty(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        for i in range(25):
            make_scored(s, n=i + 1, score=float(i + 1))

    update = make_message_update("/top 9999")
    await commands.top_command(update, make_context(args=["9999"]))

    sent = _sent(update)
    assert len(_RANK_LINE.findall(sent)) == 20  # clamped 1..20
    assert "🏆 أفضل 20 مشاريع مفتوحة" in sent


@pytest.mark.asyncio
async def test_top_fewer_than_n_returns_short_list(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_scored(s, n=1, score=80.0)
        make_scored(s, n=2, score=60.0)
        make_scored(s, n=3, score=40.0)

    update = make_message_update("/top 5")
    await commands.top_command(update, make_context(args=["5"]))

    sent = _sent(update)
    assert "🏆 أفضل 3 مشاريع مفتوحة" in sent  # only three available, no padding
    assert len(_RANK_LINE.findall(sent)) == 3


@pytest.mark.asyncio
async def test_top_with_no_open_projects_is_friendly(bot_db):
    from mostaql_notifier.bot import commands

    update = make_message_update("/top")
    await commands.top_command(update, make_context(args=[]))

    update.message.reply_text.assert_awaited_with("🏆 لا مشاريع مفتوحة حاليًا")


@pytest.mark.asyncio
async def test_top_non_integer_arg_falls_back_to_default(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        for i in range(7):
            make_scored(s, n=i + 1, score=(i + 1) * 5.0)

    update = make_message_update("/top abc")
    await commands.top_command(update, make_context(args=["abc"]))

    sent = _sent(update)
    assert len(_RANK_LINE.findall(sent)) == 5  # non-integer → default 5, never an error
    assert "🏆 أفضل 5 مشاريع مفتوحة" in sent


@pytest.mark.asyncio
async def test_top_excludes_closed_and_untracked_projects(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_scored(s, n=1, score=90.0)  # eligible
        make_scored(s, n=2, score=95.0, site_status=ProjectStatus.closed)  # closed → excluded
        # qualified + open but tracking stopped → excluded.
        p = make_project(s, n=3, title="غير متتبَّع")
        s.add(
            ProjectScore(
                project_id=p.id,
                score=99.0,
                breakdown={"score": 99.0, "components": []},
                computed_at=_utc(),
                outcome=Outcome.open,
                tracking_active=False,
            )
        )
        s.commit()

    update = make_message_update("/top")
    await commands.top_command(update, make_context(args=[]))

    sent = _sent(update)
    assert len(_RANK_LINE.findall(sent)) == 1
    assert "· 90 ·" in sent
    assert "غير متتبَّع" not in sent  # untracked excluded despite the higher score


@pytest.mark.asyncio
async def test_top_from_non_owner_is_ignored(bot_db):
    from mostaql_notifier.bot import commands

    with bot_db() as s:
        make_scored(s, n=1, score=80.0)

    update = make_message_update("/top", chat_id=999999)
    await commands.top_command(update, make_context(args=[]))

    update.message.reply_text.assert_not_awaited()
