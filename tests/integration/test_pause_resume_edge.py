"""Edge cases for the watcher pause gate in ``run_poll_cycle`` (Feature 3, FR-028).

Complements ``test_pause_resume.py`` (which covers the happy skip/resume/idempotency on an empty
DB). These add the harder cases: a pause must be honoured even when real work (a pending project) is
queued, the gate must fire BEFORE any ``scrape_run`` row is created, and resuming must restore the
FULL evaluate pipeline — not just discovery.
"""
from __future__ import annotations

import pytest

from mostaql_notifier.db.models import EvalStatus, Project, RunStatus, ScrapeRun
from mostaql_notifier.worker.poll import run_poll_cycle
from tests.api.conftest import make_project
from tests.conftest import read_fixture

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio


def _routes():
    return [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 200, read_fixture("project_qualifying.html"), None),
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]


async def test_paused_skips_even_with_a_pending_project(db_session, settings):
    """A pause must hold even when there IS work to do: the pending project stays pending, no
    scrape_run is written, and the network is never touched."""
    set_setting(db_session, settings, "watcher_paused", True)
    make_project(db_session, _n=1, mostaql_id="9001", eval_status=EvalStatus.pending)
    fetcher, sender = FakeFetcher(_routes()), make_sender()

    assert db_session.query(ScrapeRun).count() == 0  # gate fires before any run row...
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run is None
    assert db_session.query(ScrapeRun).count() == 0  # ...so the count never moved off zero
    assert fetcher.calls == []                        # no fetch, even with a pending project queued
    assert sender.sent == []
    # The queued project was NOT evaluated — it is exactly as it was left.
    still = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert still.eval_status == EvalStatus.pending
    assert still.eval_attempts == 0


async def test_two_consecutive_paused_cycles_with_pending_stay_zero_runs(db_session, settings):
    """Idempotent under load: repeated paused cycles never accumulate scrape_run rows or progress
    the pending work."""
    set_setting(db_session, settings, "watcher_paused", True)
    make_project(db_session, _n=1, mostaql_id="9001", eval_status=EvalStatus.pending)
    fetcher, sender = FakeFetcher(_routes()), make_sender()

    for _ in range(2):
        assert await run_poll_cycle(db_session, fetcher, sender, settings) is None

    assert db_session.query(ScrapeRun).count() == 0
    assert fetcher.calls == []
    assert db_session.query(Project).filter_by(mostaql_id="9001").one().eval_status == EvalStatus.pending


async def test_resume_after_pause_runs_full_evaluate_pipeline(db_session, settings):
    """Resuming with a pre-existing pending project exercises the FULL pipeline (not the first-run
    baseline): a scrape_run is created, fetcher.get IS called, and the pending project is evaluated."""
    set_setting(db_session, settings, "watcher_paused", True)
    make_project(db_session, _n=1, mostaql_id="9001", url="https://mostaql.com/project/9001",
                 eval_status=EvalStatus.pending)

    # Paused first: confirm nothing happened.
    assert await run_poll_cycle(db_session, FakeFetcher(_routes()), make_sender(), settings) is None
    assert db_session.query(ScrapeRun).count() == 0

    # Resume + zero the politeness delay so the cycle is instant.
    set_setting(db_session, settings, "watcher_paused", False)
    set_setting(db_session, settings, "baseline_on_first_run", False)
    set_setting(db_session, settings, "delay_min_seconds", 0)
    set_setting(db_session, settings, "delay_max_seconds", 0)

    fetcher, sender = FakeFetcher(_routes()), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run is not None
    assert db_session.query(ScrapeRun).count() == 1               # exactly the resumed cycle's run
    assert fetcher.calls != []                                     # the network WAS touched on resume
    assert any("projects/development" in c for c in fetcher.calls)  # listing fetched
    assert run.status in (RunStatus.success, RunStatus.partial)
    # The previously-pending project was actually evaluated (no longer pending).
    p = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert p.eval_status != EvalStatus.pending
