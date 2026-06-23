"""US2 integration: blocks/structure-change alert + back off; a bad project is skipped, not fatal."""
from __future__ import annotations

import pytest

from mostaql_notifier.config.settings_store import app_state_get
from mostaql_notifier.db.models import RunStatus
from mostaql_notifier.worker.circuit_breaker import CircuitBreaker
from mostaql_notifier.worker.poll import run_poll_cycle
from tests.conftest import read_fixture

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio


async def _assert_block(db_session, settings, listing_response):
    set_setting(db_session, settings, "baseline_on_first_run", False)
    fetcher = FakeFetcher([("projects/development", *listing_response)])
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.blocked
    assert len(sender.sent) >= 1  # a health alert went out
    assert app_state_get(db_session, "last_successful_poll_at") is None  # not a successful poll
    assert CircuitBreaker(db_session).is_paused() is True


async def test_http_403_blocks_and_alerts(db_session, settings):
    await _assert_block(db_session, settings, (403, "forbidden", 100))


async def test_http_429_blocks_and_alerts(db_session, settings):
    await _assert_block(db_session, settings, (429, "slow down", 100))


async def test_captcha_marker_blocks_and_alerts(db_session, settings):
    await _assert_block(db_session, settings, (200, read_fixture("challenge.html"), None))


async def test_zero_rows_on_nonempty_listing_is_structure_change(db_session, settings):
    # Big body with shell markers but no real project rows => structure change (not "no new projects").
    body = "<html><body>" + ("مشروع project-row " * 4000) + "</body></html>"
    await _assert_block(db_session, settings, (200, body, len(body.encode("utf-8"))))


async def test_one_bad_project_is_skipped_not_fatal(db_session, settings):
    set_setting(db_session, settings, "baseline_on_first_run", False)
    set_setting(db_session, settings, "delay_min_seconds", 0)  # instant, deterministic
    set_setting(db_session, settings, "delay_max_seconds", 0)
    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 200, "<html><body>broken, no project structure</body></html>", None),
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.error_count >= 1
    assert run.status == RunStatus.partial  # survived; some projects errored
