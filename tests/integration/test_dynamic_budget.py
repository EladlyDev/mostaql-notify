"""US3 integration: a $150 project qualifies as Tier 2 only when the dynamic floor is lowered."""
from __future__ import annotations

import pytest

from mostaql_notifier.config.settings_store import app_state_set
from mostaql_notifier.db.models import EvalStatus, NotificationLog, Project
from mostaql_notifier.worker.poll import run_poll_cycle
from tests.conftest import read_fixture

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio


def _routes_150():
    # Reuse the qualifying fixture but drop the budget into the Tier-2 band ($100–$249).
    proj = read_fixture("project_qualifying.html").replace("$300.00 - $500.00", "$150.00 - $150.00")
    listing = read_fixture("listing_small.html")
    return [
        ("projects/development", 200, listing, None),
        ("/project/9001", 200, proj, None),
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]


async def test_tier2_qualifies_only_when_floor_lowered(db_session, settings):
    set_setting(db_session, settings, "baseline_on_first_run", False)
    set_setting(db_session, settings, "delay_min_seconds", 0)  # instant, deterministic
    set_setting(db_session, settings, "delay_max_seconds", 0)
    # Pin the hysteresis so recompute_floor does not auto-adjust the floor under test:
    # target=0 means "never lower" (count<0 is impossible) and "never raise" (count>0+buffer is false at 0).
    set_setting(db_session, settings, "fallback_target", 0)

    # Floor at the primary $250 → a $150 project is disqualified.
    app_state_set(db_session, "active_budget_floor", "250")
    await run_poll_cycle(db_session, FakeFetcher(_routes_150()), make_sender(), settings)
    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert p1.eval_status == EvalStatus.disqualified
    assert db_session.query(NotificationLog).count() == 0

    # Lower the floor to the fallback $100 → the same $150 project now qualifies as Tier 2.
    for p in db_session.query(Project).all():
        db_session.delete(p)
    db_session.commit()
    app_state_set(db_session, "active_budget_floor", "100")
    sender = make_sender()
    await run_poll_cycle(db_session, FakeFetcher(_routes_150()), sender, settings)

    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert p1.eval_status == EvalStatus.qualified
    assert p1.tier == 2
    assert p1.notified is True
    assert any("Tier 2" in m for m in sender.sent)
