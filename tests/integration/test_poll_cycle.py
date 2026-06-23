"""US1 integration: end-to-end poll → qualify → notify, with dedup and first-run baseline."""
from __future__ import annotations

import pytest

from mostaql_notifier.db.models import EvalStatus, NotificationLog, Project
from mostaql_notifier.worker.poll import run_poll_cycle
from tests.conftest import read_fixture

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio


def _routes():
    return [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 200, read_fixture("project_qualifying.html"), None),
        ("/project/9002", 200, read_fixture("project_page.html"), None),  # real "لم يحسب بعد" => disqualified
    ]


async def test_qualifying_project_is_notified_once(db_session, settings):
    set_setting(db_session, settings, "baseline_on_first_run", False)
    # Zero the inter-request politeness delay so the cycle is instant + deterministic (the delay is
    # config-driven; real timing is covered by worker.politeness unit tests, not here).
    set_setting(db_session, settings, "delay_min_seconds", 0)
    set_setting(db_session, settings, "delay_max_seconds", 0)
    fetcher, sender = FakeFetcher(_routes()), make_sender()

    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.found_count == 2
    assert run.new_count == 2
    # 9001 qualifies (75% hiring, $300-$500), 9002 disqualified ("لم يحسب بعد").
    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    p2 = db_session.query(Project).filter_by(mostaql_id="9002").one()
    assert p1.eval_status == EvalStatus.qualified and p1.tier == 1 and p1.notified is True
    assert p2.eval_status == EvalStatus.disqualified and p2.notified is False
    assert db_session.query(NotificationLog).count() == 1
    assert len(sender.sent) == 1
    assert "Tier 1" in sender.sent[0]

    # Second cycle: no new notification (dedup), nothing new.
    run2 = await run_poll_cycle(db_session, FakeFetcher(_routes()), sender, settings)
    assert run2.new_count == 0
    assert db_session.query(NotificationLog).count() == 1
    assert len(sender.sent) == 1


async def test_first_run_baseline_sends_nothing(db_session, settings):
    # default baseline_on_first_run = True
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.new_count == 0
    assert len(sender.sent) == 0
    assert db_session.query(NotificationLog).count() == 0
    statuses = {p.mostaql_id: p.eval_status for p in db_session.query(Project).all()}
    assert statuses == {"9001": EvalStatus.baseline, "9002": EvalStatus.baseline}
