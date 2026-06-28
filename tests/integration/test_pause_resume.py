"""US4 integration: the watcher pause flag makes a poll cycle skip QUIETLY (Feature 3, T043).

A pause is an intentional idle, not a fault — so a paused cycle must write NO ``scrape_run`` row
(otherwise Feature 2's health light would read red). Resuming restores the normal poll.
"""
from __future__ import annotations

import pytest

from mostaql_notifier.db.models import Project, ScrapeRun
from mostaql_notifier.worker.poll import run_poll_cycle
from tests.conftest import read_fixture

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio


def _routes():
    return [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 200, read_fixture("project_qualifying.html"), None),
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]


async def test_paused_skips_cycle_quietly_no_run_row(db_session, settings):
    set_setting(db_session, settings, "watcher_paused", True)
    fetcher, sender = FakeFetcher(_routes()), make_sender()

    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    # Skipped quietly: no run object, no scrape_run row, and the network was never touched.
    assert run is None
    assert db_session.query(ScrapeRun).count() == 0
    assert fetcher.calls == []
    assert sender.sent == []


async def test_resume_restores_polling(db_session, settings):
    # Pause, confirm the skip, then resume and confirm the cycle runs and records a run.
    set_setting(db_session, settings, "watcher_paused", True)
    assert await run_poll_cycle(db_session, FakeFetcher(_routes()), make_sender(), settings) is None
    assert db_session.query(ScrapeRun).count() == 0

    set_setting(db_session, settings, "watcher_paused", False)
    set_setting(db_session, settings, "delay_min_seconds", 0)
    set_setting(db_session, settings, "delay_max_seconds", 0)

    run = await run_poll_cycle(db_session, FakeFetcher(_routes()), make_sender(), settings)

    assert run is not None
    assert db_session.query(ScrapeRun).count() == 1
    assert run.found_count == 2
    assert db_session.query(Project).count() >= 2


async def test_pause_is_idempotent_across_cycles(db_session, settings):
    set_setting(db_session, settings, "watcher_paused", True)
    for _ in range(3):
        assert await run_poll_cycle(db_session, FakeFetcher(_routes()), make_sender(), settings) is None
    assert db_session.query(ScrapeRun).count() == 0
