"""Exhaustive integration coverage for the poll spine (worker/poll.py).

Every branch of ``run_poll_cycle`` / ``_evaluate_project`` / ``_handle_block`` /
``_finish_blocked`` / ``_finish_success`` / ``_safe_alert`` is exercised here, including the
adversarial / constitution-relevant paths:

  * circuit breaker already paused -> blocked, no fetch (poll.py 47-52);
  * terminal pending (attempts cap, age cap) -> eval_error + alert (127-134);
  * per-cycle fetch cap (136);
  * mid-cycle hard block -> blocked + breaker trips (143-144, 162-166);
  * transient project fetch -> attempt++, stays pending, cycle continues (167-172);
  * transient listing -> FAILED not blocked (handle_block 220-228);
  * dynamic floor recompute persistence;
  * updated_count on re-observation;
  * RECOVERED alert + last_successful_poll_at on recovery (237-244).

Determinism: every test that runs a cycle zeroes the politeness delay and (unless under test)
disables the first-run baseline. ``now`` is injected wherever the cycle's clock matters.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
import telegram.error

from mostaql_notifier.config.settings_store import (
    app_state_get,
    app_state_set,
)
from mostaql_notifier.db.models import (
    EvalStatus,
    NotificationLog,
    Project,
    ProjectStatus,
    RunStatus,
    ScrapeRun,
)
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.worker.circuit_breaker import CircuitBreaker
from mostaql_notifier.worker.poll import run_poll_cycle
from tests.conftest import read_fixture

from ._helpers import FakeFetcher, make_sender, set_setting

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- helpers


def _zero_delays(db_session, settings) -> None:
    set_setting(db_session, settings, "delay_min_seconds", 0)
    set_setting(db_session, settings, "delay_max_seconds", 0)


def _no_baseline(db_session, settings) -> None:
    set_setting(db_session, settings, "baseline_on_first_run", False)


def _prep(db_session, settings) -> None:
    """Fast + deterministic default for any cycle test."""
    _zero_delays(db_session, settings)
    _no_baseline(db_session, settings)


def _routes(qualifying="project_qualifying.html"):
    """Standard listing_small (ids 9001, 9002) with a routable project page each."""
    return [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 200, read_fixture(qualifying), None),
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]


def _listing_only_routes(listing_response):
    return [("projects/development", *listing_response)]


# --------------------------------------------------------------------------- (a) breaker paused


async def test_breaker_already_paused_blocks_without_fetching(db_session, settings):
    """cb_resume_at in the FUTURE -> run blocked, returns BEFORE any fetch (poll.py 47-52)."""
    _prep(db_session, settings)
    future = (utcnow() + timedelta(minutes=30)).isoformat()
    app_state_set(db_session, "cb_resume_at", future)

    fetcher, sender = FakeFetcher(_routes()), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.blocked
    assert run.finished_at is not None
    assert "circuit breaker paused until" in (run.notes or "")
    # No HTTP at all: the listing was never fetched.
    assert fetcher.calls == []
    # No notification, no health alert, no project ingested.
    assert sender.sent == []
    assert db_session.query(Project).count() == 0
    # A successful-poll marker is NOT written for a blocked run.
    assert app_state_get(db_session, "last_successful_poll_at") is None


async def test_breaker_resume_exactly_now_is_not_paused(db_session, settings):
    """Boundary: is_paused() uses strict ``utcnow() < resume`` so resume==now is NOT paused.

    We inject now slightly past the resume instant so the cycle proceeds normally.
    """
    _prep(db_session, settings)
    resume = utcnow()
    app_state_set(db_session, "cb_resume_at", resume.isoformat())

    fetcher, sender = FakeFetcher(_routes()), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings, now=resume + timedelta(seconds=1))

    # Not blocked-on-entry: we actually fetched the listing.
    assert any("projects/development" in c for c in fetcher.calls)
    assert run.status != RunStatus.blocked


# --------------------------------------------------------------------------- (b) attempts cap terminal


async def test_pending_at_attempt_cap_becomes_eval_error_and_alerts(db_session, settings):
    """eval_attempts >= max_eval_attempts at selection -> eval_error, error_count++, alert (127-134)."""
    _prep(db_session, settings)
    set_setting(db_session, settings, "max_eval_attempts", 3)

    now = utcnow()
    # Pre-insert a pending project already at the attempt cap; not in the listing fixture.
    db_session.add(Project(
        mostaql_id="7001", url="https://mostaql.com/project/7001-x",
        title="capped", category="development",
        site_status=ProjectStatus.unknown, eval_status=EvalStatus.pending,
        eval_attempts=3, scraped_at=now, raw={},
    ))
    db_session.commit()

    # The standard small listing also ingests 9001/9002 fresh; we assert only on 7001's terminal
    # transition (it is not in the listing, so it is selected purely as an over-cap pending).
    fetcher = FakeFetcher(_routes())
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings, now=now)

    capped = db_session.query(Project).filter_by(mostaql_id="7001").one()
    assert capped.eval_status == EvalStatus.eval_error
    assert capped.last_eval_at is not None
    assert run.error_count >= 1
    # A health alert was emitted for the eval error.
    assert any("EVAL_ERROR" in m for m in sender.sent)
    # Terminal projects are NOT fetched (never routed to 7001).
    assert not any("/project/7001" in c for c in fetcher.calls)


# --------------------------------------------------------------------------- (c) age cap terminal


async def test_pending_older_than_max_age_becomes_eval_error(db_session, settings):
    """(now - scraped_at) > pending_max_age_hours -> terminal eval_error (127-134, age branch)."""
    _prep(db_session, settings)
    set_setting(db_session, settings, "pending_max_age_hours", 1)

    now = utcnow()
    old = now - timedelta(hours=5)
    db_session.add(Project(
        mostaql_id="7002", url="https://mostaql.com/project/7002-old",
        title="stale", category="development",
        site_status=ProjectStatus.unknown, eval_status=EvalStatus.pending,
        eval_attempts=0, scraped_at=old, raw={},
    ))
    db_session.commit()

    fetcher = FakeFetcher(_routes())
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings, now=now)

    stale = db_session.query(Project).filter_by(mostaql_id="7002").one()
    assert stale.eval_status == EvalStatus.eval_error
    assert run.error_count >= 1
    assert any("EVAL_ERROR" in m for m in sender.sent)
    # Never fetched the stale project page.
    assert not any("/project/7002" in c for c in fetcher.calls)


async def test_age_cap_boundary_not_terminal_when_equal(db_session, settings):
    """Boundary: age == max_age is NOT > max_age, so the project is evaluated, not terminated.

    The 9999 project page is broken so the eval ends in a skip (error), but crucially it is
    *fetched* and not short-circuited as a terminal age error.
    """
    _prep(db_session, settings)
    set_setting(db_session, settings, "pending_max_age_hours", 2)

    now = utcnow()
    exactly = now - timedelta(hours=2)  # equal, not greater
    db_session.add(Project(
        mostaql_id="9999", url="https://mostaql.com/project/9999-edge",
        title="edge", category="development",
        site_status=ProjectStatus.unknown, eval_status=EvalStatus.pending,
        eval_attempts=0, scraped_at=exactly, raw={},
    ))
    db_session.commit()

    routes = [
        ("projects/development", 200, "<html><body>" + ("x" * 60000) + "</body></html>", 200_000),
        ("/project/9999", 200, read_fixture("project_qualifying.html"), None),
    ]
    fetcher = FakeFetcher(routes)
    sender = make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings, now=now)

    edge = db_session.query(Project).filter_by(mostaql_id="9999").one()
    # It was actually evaluated (fetched), not marked eval_error by the age short-circuit.
    assert any("/project/9999" in c for c in fetcher.calls)
    assert edge.eval_status != EvalStatus.eval_error


# --------------------------------------------------------------------------- (d) transient project 503


async def test_transient_project_503_increments_attempt_stays_pending_continues(db_session, settings):
    """Project route 503 -> attempt++, error_count++, NOT terminal, stays pending, run continues (167-172)."""
    _prep(db_session, settings)
    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 503, "service unavailable", 100),  # transient
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert p1.eval_status == EvalStatus.pending  # not terminal
    assert p1.eval_attempts == 1
    assert p1.last_eval_at is not None
    assert run.error_count >= 1
    # The cycle did NOT stop on the transient: 9002 was still evaluated.
    assert any("/project/9002" in c for c in fetcher.calls)
    # Not a block: run finishes (partial because of the error), breaker not paused.
    assert run.status == RunStatus.partial
    assert CircuitBreaker(db_session).is_paused() is False


async def test_transient_project_status_zero_is_transient(db_session, settings):
    """status==0 (transport error) classifies transient just like 5xx (167-172)."""
    _prep(db_session, settings)
    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 0, "", 0),
        ("/project/9002", 0, "", 0),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    p2 = db_session.query(Project).filter_by(mostaql_id="9002").one()
    assert p1.eval_status == EvalStatus.pending and p1.eval_attempts == 1
    assert p2.eval_status == EvalStatus.pending and p2.eval_attempts == 1
    assert run.error_count == 2
    assert run.status == RunStatus.partial


# --------------------------------------------------------------------------- (e) mid-cycle hard block


async def test_mid_cycle_403_blocks_and_trips_breaker(db_session, settings):
    """Project route 403 -> _evaluate_project returns stop -> run blocked, breaker trips, alert (143-144, 162-166)."""
    _prep(db_session, settings)
    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 403, "forbidden", 100),  # hard block on first project
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.blocked
    assert run.finished_at is not None
    # Breaker tripped into a paused state on the hard block.
    breaker = CircuitBreaker(db_session)
    assert breaker.is_paused() is True
    # A BLOCKED health alert went out (transition).
    assert any("BLOCKED" in m for m in sender.sent)
    # Cycle stopped: the second project was never fetched (stop short-circuits the loop).
    assert not any("/project/9002" in c for c in fetcher.calls)
    # Not a successful poll.
    assert app_state_get(db_session, "last_successful_poll_at") is None


async def test_mid_cycle_challenge_body_blocks(db_session, settings):
    """Project route returns a Cloudflare challenge body (200, tiny) -> challenge -> block (161-166)."""
    _prep(db_session, settings)
    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 200, read_fixture("challenge.html"), None),  # small + cf marker
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.blocked
    assert CircuitBreaker(db_session).is_paused() is True
    assert any("CHALLENGE" in m for m in sender.sent)


async def test_mid_cycle_block_emits_exactly_one_alert_per_transition(db_session, settings):
    """A mid-cycle hard block emits the BLOCKED alert exactly once (single transition per cycle).

    Even with both project routes blocking, the cycle stops at the first project (``stop`` is
    returned), so ``record_failure`` transitions the breaker once and ``_safe_alert`` fires once —
    never a double alert.
    """
    _prep(db_session, settings)
    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 403, "forbidden", 100),
        ("/project/9002", 403, "forbidden", 100),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)
    # Only the first (transition) block alerts; the cycle stops at the first project anyway.
    assert sum("BLOCKED" in m for m in sender.sent) == 1
    # The second project was never fetched (cycle stopped on the first block).
    assert not any("/project/9002" in c for c in fetcher.calls)


# --------------------------------------------------------------------------- (f) floor recompute persists


async def test_floor_recomputes_to_fallback_and_persists(db_session, settings):
    """Scarce tier-1 supply with start floor 250 -> after cycle app_state floor == fallback 100."""
    _prep(db_session, settings)
    # Defaults: fallback_target=10, so count(0) < 10 -> primary(250) flips to fallback(100).
    app_state_set(db_session, "active_budget_floor", "250")

    fetcher, sender = FakeFetcher(_routes()), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)

    assert app_state_get(db_session, "active_budget_floor") == "100"


async def test_floor_held_when_no_threshold_crossed(db_session, settings):
    """fallback_target=0 pins the floor: 250 stays 250 (count<0 impossible, count>0+buffer at 0 false)."""
    _prep(db_session, settings)
    set_setting(db_session, settings, "fallback_target", 0)
    app_state_set(db_session, "active_budget_floor", "250")

    fetcher, sender = FakeFetcher(_routes()), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)

    assert app_state_get(db_session, "active_budget_floor") == "250"


# --------------------------------------------------------------------------- (g) listing transient


async def test_listing_503_is_failed_not_blocked(db_session, settings):
    """Listing route 503 (transient) -> _handle_block(hard=False) -> run FAILED, not blocked."""
    _prep(db_session, settings)
    fetcher = FakeFetcher(_listing_only_routes((503, "boom", 100)))
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.failed
    assert "transient" in (run.notes or "")
    assert run.finished_at is not None
    # First transient does NOT trip the breaker (needs 3 consecutive soft failures).
    assert CircuitBreaker(db_session).is_paused() is False
    # No project was ingested; no successful-poll marker.
    assert db_session.query(Project).count() == 0
    assert app_state_get(db_session, "last_successful_poll_at") is None


async def test_listing_status_zero_is_failed(db_session, settings):
    """Transport error on the listing (status 0) also classifies transient -> FAILED."""
    _prep(db_session, settings)
    fetcher = FakeFetcher(_listing_only_routes((0, "", 0)))
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.failed
    assert CircuitBreaker(db_session).is_paused() is False


async def test_listing_403_blocks_and_trips(db_session, settings):
    """Listing 403 -> hard block -> run blocked + breaker trips + alert (handle_block hard path)."""
    _prep(db_session, settings)
    fetcher = FakeFetcher(_listing_only_routes((403, "forbidden", 100)))
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.blocked
    assert CircuitBreaker(db_session).is_paused() is True
    assert any("BLOCKED" in m for m in sender.sent)


async def test_junk_listing_without_shell_markers_is_a_clean_empty_success(db_session, settings):
    """A big 200 listing with no project rows AND no shell markers -> 0 rows, not a structure change.

    Note: poll.py lines 72-75 (the ``except ParseError`` around ``parse_listing``) are unreachable
    with the current scraper — ``parse_listing`` never raises ParseError; it silently skips
    unidentifiable rows and returns an empty list. So a body that parses to 0 rows but lacks any
    ``listing_shell_markers`` is treated as a genuine empty page (is_clearly_nonempty False) and the
    cycle finishes cleanly. This asserts that empty-but-plausible path does NOT false-alarm.
    """
    _prep(db_session, settings)
    # Large body (passes the challenge/size gate as ok) with no project-row <tr> and no shell marker.
    body = "<html><body>" + ("plain text no rows " * 4000) + "</body></html>"
    fetcher = FakeFetcher(_listing_only_routes((200, body, len(body.encode("utf-8")))))
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.success
    assert run.found_count == 0
    assert sender.sent == []  # no spurious structure-change alert
    assert app_state_get(db_session, "last_successful_poll_at") is not None


async def test_zero_rows_on_clearly_nonempty_listing_blocks(db_session, settings):
    """0 parsed rows on a big page with shell markers -> structure_change block (76-79)."""
    _prep(db_session, settings)
    # Big body, contains a shell marker ("مشروع") and listing-ish text but no real project-row <tr>.
    body = "<html><body>" + ("مشروع filler " * 5000) + "</body></html>"
    fetcher = FakeFetcher(_listing_only_routes((200, body, len(body.encode("utf-8")))))
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.blocked
    assert "0 rows" in (run.notes or "")
    assert CircuitBreaker(db_session).is_paused() is True


# --------------------------------------------------------------------------- (h) updated_count


async def test_updated_count_increments_on_reobservation(db_session, settings):
    """Ingest once, then run again with the same ids -> updated_count > 0 (re-observation branch 100-101)."""
    _prep(db_session, settings)
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    run1 = await run_poll_cycle(db_session, fetcher, sender, settings)
    assert run1.new_count == 2
    assert run1.updated_count == 0

    run2 = await run_poll_cycle(db_session, FakeFetcher(_routes()), make_sender(), settings)
    assert run2.new_count == 0
    assert run2.updated_count == 2
    assert run2.found_count == 2


# --------------------------------------------------------------------------- (i) per-cycle fetch cap


async def test_max_fetches_per_cycle_cap_one_evaluates_exactly_one(db_session, settings):
    """cap=1 with 2 new pendings -> exactly 1 evaluated, the other stays pending (135-136 break)."""
    _prep(db_session, settings)
    set_setting(db_session, settings, "max_fetches_per_cycle", 1)

    fetcher, sender = FakeFetcher(_routes()), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)

    projects = {p.mostaql_id: p for p in db_session.query(Project).all()}
    evaluated = [p for p in projects.values() if p.eval_status != EvalStatus.pending]
    still_pending = [p for p in projects.values() if p.eval_status == EvalStatus.pending]
    assert len(evaluated) == 1
    assert len(still_pending) == 1
    # Exactly one project page was fetched (plus the listing).
    project_fetches = [c for c in fetcher.calls if "/project/" in c]
    assert len(project_fetches) == 1


async def test_fetch_cap_processes_oldest_first(db_session, settings):
    """The cap selects pending ordered by scraped_at asc — the OLDER pending is evaluated first."""
    _prep(db_session, settings)
    set_setting(db_session, settings, "max_fetches_per_cycle", 1)

    now = utcnow()
    # Pre-seed two pendings; 8001 older than 8002. Neither is in the listing fixture, so the
    # listing's own 9001/9002 will be appended NEWER (scraped_at == now).
    db_session.add(Project(
        mostaql_id="8001", url="https://mostaql.com/project/8001-old",
        title="older", category="development", site_status=ProjectStatus.unknown,
        eval_status=EvalStatus.pending, scraped_at=now - timedelta(hours=2), raw={},
    ))
    db_session.add(Project(
        mostaql_id="8002", url="https://mostaql.com/project/8002-new",
        title="newer", category="development", site_status=ProjectStatus.unknown,
        eval_status=EvalStatus.pending, scraped_at=now - timedelta(hours=1), raw={},
    ))
    db_session.commit()

    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/8001", 200, read_fixture("project_page.html"), None),
        ("/project/8002", 200, read_fixture("project_page.html"), None),
        ("/project/9001", 200, read_fixture("project_qualifying.html"), None),
        ("/project/9002", 200, read_fixture("project_page.html"), None),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings, now=now)

    # Oldest (8001) is the single one fetched/evaluated.
    assert any("/project/8001" in c for c in fetcher.calls)
    p8001 = db_session.query(Project).filter_by(mostaql_id="8001").one()
    assert p8001.eval_status != EvalStatus.pending


# --------------------------------------------------------------------------- (j) recovered alert


async def test_recovered_alert_after_breaker_trip_then_clean_cycle(db_session, settings):
    """Trip the breaker, force resume into the past, then a clean cycle -> RECOVERED alert."""
    _prep(db_session, settings)

    # Cycle 1: listing 403 trips the breaker.
    fetcher1 = FakeFetcher(_listing_only_routes((403, "forbidden", 100)))
    sender1 = make_sender()
    run1 = await run_poll_cycle(db_session, fetcher1, sender1, settings)
    assert run1.status == RunStatus.blocked
    assert CircuitBreaker(db_session).is_paused() is True

    # Force the pause to have already elapsed (resume in the past) so the entry guard passes.
    app_state_set(db_session, "cb_resume_at", (utcnow() - timedelta(minutes=1)).isoformat())

    # Cycle 2: fully successful — listing + projects all 200.
    fetcher2, sender2 = FakeFetcher(_routes()), make_sender()
    run2 = await run_poll_cycle(db_session, fetcher2, sender2, settings)

    assert run2.status in (RunStatus.success, RunStatus.partial)
    # A RECOVERED alert was emitted on the success transition.
    assert any("RECOVERED" in m for m in sender2.sent)
    # last_successful_poll_at is now set and parseable as an ISO timestamp.
    marker = app_state_get(db_session, "last_successful_poll_at")
    assert marker is not None
    from datetime import datetime
    datetime.fromisoformat(marker)
    # The pause was cleared on recovery.
    assert CircuitBreaker(db_session).is_paused() is False
    assert app_state_get(db_session, "cb_resume_at") in ("", None)


async def test_clean_run_with_no_prior_failure_does_not_send_recovered(db_session, settings):
    """record_success returns False when nothing was failing -> NO recovered alert (243 false branch)."""
    _prep(db_session, settings)
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.status == RunStatus.success
    assert not any("RECOVERED" in m for m in sender.sent)
    # Successful poll marker IS set even without a prior failure.
    assert app_state_get(db_session, "last_successful_poll_at") is not None


# --------------------------------------------------------------------------- first-run baseline branch


async def test_first_run_baseline_seeds_and_marks_success(db_session, settings):
    """baseline_on_first_run True + empty DB -> all rows seeded baseline, nothing notified, success."""
    _zero_delays(db_session, settings)  # baseline ON (default)
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    assert run.new_count == 0
    assert "first-run baseline" in (run.notes or "")
    assert sender.sent == []
    assert db_session.query(NotificationLog).count() == 0
    statuses = {p.mostaql_id: p.eval_status for p in db_session.query(Project).all()}
    assert statuses == {"9001": EvalStatus.baseline, "9002": EvalStatus.baseline}
    # Baseline goes through _finish_success -> marks the poll successful.
    assert run.status == RunStatus.success
    assert app_state_get(db_session, "last_successful_poll_at") is not None


async def test_baseline_disabled_evaluates_immediately(db_session, settings):
    """baseline_on_first_run False -> even on an empty DB the projects are evaluated, not seeded baseline."""
    _prep(db_session, settings)
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)

    statuses = {p.mostaql_id: p.eval_status for p in db_session.query(Project).all()}
    assert EvalStatus.baseline not in statuses.values()
    # 9001 qualifies and is notified.
    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert p1.eval_status == EvalStatus.qualified
    assert p1.notified is True


# --------------------------------------------------------------------------- per-project exception safety


async def test_one_unparseable_project_is_skipped_not_fatal(db_session, settings):
    """A project page that fails parse_project_page is caught per-project: attempt++, error_count++."""
    _prep(db_session, settings)
    routes = [
        ("projects/development", 200, read_fixture("listing_small.html"), None),
        ("/project/9001", 200, "<html><body>" + ("garbage " * 5000) + "</body></html>", 200_000),
        ("/project/9002", 200, read_fixture("project_qualifying.html"), None),
    ]
    fetcher, sender = FakeFetcher(routes), make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    # Stayed pending (not terminal) with one consumed attempt; recorded as an error.
    assert p1.eval_status == EvalStatus.pending
    assert p1.eval_attempts == 1
    assert run.error_count >= 1
    assert run.status == RunStatus.partial
    # The note captured the failing project id.
    assert "9001" in (run.notes or "")
    # The second project still got evaluated despite the first one's failure.
    p2 = db_session.query(Project).filter_by(mostaql_id="9002").one()
    assert p2.eval_status in (EvalStatus.qualified, EvalStatus.disqualified)


# --------------------------------------------------------------------------- disqualified path + dedup


async def test_disqualified_project_not_notified(db_session, settings):
    """The real 'لم يحسب بعد' fixture (9002) disqualifies: status disqualified, no notification."""
    _prep(db_session, settings)
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)

    p2 = db_session.query(Project).filter_by(mostaql_id="9002").one()
    assert p2.eval_status == EvalStatus.disqualified
    assert p2.notified is False
    # Only the qualifying 9001 produced a log row.
    assert db_session.query(NotificationLog).count() == 1


async def test_qualified_notified_once_then_deduped_across_cycles(db_session, settings):
    """Qualifying project notified exactly once; a second cycle re-observes without re-notifying."""
    _prep(db_session, settings)
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)
    assert db_session.query(NotificationLog).count() == 1
    assert len(sender.sent) == 1

    # Re-run with the same sender: the qualified project is no longer pending, so not re-evaluated,
    # and dedup would block a re-send anyway.
    run2 = await run_poll_cycle(db_session, FakeFetcher(_routes()), sender, settings)
    assert run2.updated_count == 2
    assert db_session.query(NotificationLog).count() == 1
    assert len(sender.sent) == 1


# --------------------------------------------------------------------------- alert-send failure is swallowed


async def test_eval_error_alert_send_failure_is_swallowed(db_session, settings):
    """_safe_alert swallows a sender failure (254-255): the eval_error still commits, run does not crash."""
    _prep(db_session, settings)
    set_setting(db_session, settings, "max_eval_attempts", 1)

    now = utcnow()
    db_session.add(Project(
        mostaql_id="7003", url="https://mostaql.com/project/7003-x",
        title="capped", category="development", site_status=ProjectStatus.unknown,
        eval_status=EvalStatus.pending, eval_attempts=1, scraped_at=now, raw={},
    ))
    db_session.commit()

    fetcher = FakeFetcher(_routes())
    sender = make_sender()

    async def _boom(text):  # send_alert path raises
        raise RuntimeError("telegram down")

    sender.send_alert = _boom  # type: ignore[assignment]

    # Must not raise despite the alert failing.
    run = await run_poll_cycle(db_session, fetcher, sender, settings, now=now)

    capped = db_session.query(Project).filter_by(mostaql_id="7003").one()
    assert capped.eval_status == EvalStatus.eval_error  # transition still committed
    assert run.error_count >= 1


# --------------------------------------------------------------------------- transient does not trip on first hit


async def test_three_consecutive_transient_listings_eventually_trip(db_session, settings):
    """Soft failures accumulate: the 3rd consecutive transient listing trips the breaker (record_failure fails>=3)."""
    _prep(db_session, settings)

    async def one():
        fetcher = FakeFetcher(_listing_only_routes((503, "boom", 100)))
        sender = make_sender()
        run = await run_poll_cycle(db_session, fetcher, sender, settings)
        return run, sender

    run1, _ = await one()
    assert run1.status == RunStatus.failed
    assert CircuitBreaker(db_session).is_paused() is False

    run2, _ = await one()
    assert run2.status == RunStatus.failed
    assert CircuitBreaker(db_session).is_paused() is False

    run3, sender3 = await one()
    # Third consecutive soft failure trips the pause.
    assert CircuitBreaker(db_session).is_paused() is True
    # The transition emits a TRANSIENT health alert.
    assert any("TRANSIENT" in m for m in sender3.sent)


# --------------------------------------------------------------------------- ScrapeRun bookkeeping


async def test_scrape_run_row_is_persisted_with_counts(db_session, settings):
    """A ScrapeRun row is created and finished with sane counts/timestamps on a normal cycle."""
    _prep(db_session, settings)
    fetcher, sender = FakeFetcher(_routes()), make_sender()
    await run_poll_cycle(db_session, fetcher, sender, settings)

    persisted = db_session.query(ScrapeRun).all()
    assert len(persisted) == 1
    r = persisted[0]
    assert r.started_at is not None and r.finished_at is not None
    assert r.finished_at >= r.started_at
    assert r.found_count == 2
    assert r.new_count == 2


# --------------------------------------------------------------------------- KNOWN BUG: at-least-once


async def test_qualified_but_send_failed_is_retried_next_cycle(db_session, settings):
    """At-least-once: a qualifying project whose send fails (TimedOut) MUST be retried & delivered.

    Cycle 1: 9001 qualifies but the sender raises telegram.error.TimedOut inside _send, so the
    real TelegramSender catches it and returns False — leaving the project qualified, notified=False,
    and NO NotificationLog row. Cycle 2 runs with a working sender.

    Behaviour (regression guard for the fixed at-least-once bug): after cycle 2 the project is
    delivered EXACTLY once — project.notified is True AND exactly one NotificationLog row AND one
    message actually sent. The per-cycle _drain_unnotified pass re-drives the deferred delivery.
    """
    _prep(db_session, settings)

    # --- Cycle 1: working everywhere except the actual Telegram send, which times out.
    fetcher1 = FakeFetcher(_routes())
    sender1 = make_sender()

    async def _timeout_send(text, reply_markup=None):
        raise telegram.error.TimedOut()

    sender1._send = _timeout_send  # type: ignore[method-assign]

    await run_poll_cycle(db_session, fetcher1, sender1, settings)

    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    # Pre-condition for the bug: qualified, committed, but the send silently failed.
    assert p1.eval_status == EvalStatus.qualified
    assert p1.notified is False
    assert db_session.query(NotificationLog).count() == 0

    # --- Cycle 2: a fully working sender. The project MUST be retried and delivered.
    fetcher2 = FakeFetcher(_routes())
    sender2 = make_sender()
    await run_poll_cycle(db_session, fetcher2, sender2, settings)

    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert p1.notified is True
    assert db_session.query(NotificationLog).count() == 1
    assert len(sender2.sent) == 1


async def test_qualified_permanent_send_failure_is_terminal_and_alerts(db_session, settings):
    """A qualifying project whose delivery fails PERMANENTLY (BadRequest) must NOT be retried
    forever: _drain_unnotified moves it to eval_error, counts the error, and emits a NOTIFY_ERROR
    health alert (fail-loud) — while at-most-once still holds (no log row, notified stays False)."""
    _prep(db_session, settings)
    fetcher, sender = FakeFetcher(_routes()), make_sender()

    async def _permanent(session, project, client, *, now_utc, owner_tz):
        raise telegram.error.BadRequest("Message is too long")

    # Only the project notification fails permanently; health alerts still go out via _send.
    sender.send_project_notification = _permanent  # type: ignore[method-assign]

    run = await run_poll_cycle(db_session, fetcher, sender, settings)

    p1 = db_session.query(Project).filter_by(mostaql_id="9001").one()
    assert p1.eval_status == EvalStatus.eval_error      # terminal, not retried forever
    assert p1.notified is False
    assert db_session.query(NotificationLog).count() == 0
    assert run.error_count >= 1
    assert run.status == RunStatus.partial
    assert any("Health alert: NOTIFY_ERROR" in m for m in sender.sent)


# ------------------------------------------- re-listed projects refresh bids from the listing (free)


async def test_relisted_project_bids_refreshed_from_listing(db_session, settings):
    """A still-listed known project's stale bid count is refreshed from the (uncapped) listing every
    cycle — no detail fetch — and the refresh never downgrades a larger stored count.

    Regression: a project first seen minutes after posting (≈0 bids) used to stay frozen at that
    count until a paced detail re-check happened to reach it, so the feed showed 0 bids for projects
    that already had many. ``listing.html`` carries a real offer count for every row.
    """
    _prep(db_session, settings)
    # Detail fetches off: assert purely on the listing-driven refresh of already-known projects.
    set_setting(db_session, settings, "max_fetches_per_cycle", 0)

    now = utcnow()
    # Two ids that appear in listing.html: 1252460 (8 offers) and 1252806 (4 offers).
    db_session.add(Project(  # scraped ≈at posting with 0 bids -> must climb to the listing's 8
        mostaql_id="1252460", url="https://mostaql.com/project/1252460-x", title="fresh-when-seen",
        category="development", bids_count=0,
        site_status=ProjectStatus.unknown, eval_status=EvalStatus.disqualified,
        scraped_at=now, raw={},
    ))
    db_session.add(Project(  # already holds a higher (uncapped) total -> listing 4 must NOT downgrade
        mostaql_id="1252806", url="https://mostaql.com/project/1252806-x", title="already-high",
        category="development", bids_count=10,
        site_status=ProjectStatus.unknown, eval_status=EvalStatus.disqualified,
        scraped_at=now, raw={},
    ))
    db_session.commit()

    fetcher = FakeFetcher([("projects/development", 200, read_fixture("listing.html"), None)])
    sender = make_sender()
    run = await run_poll_cycle(db_session, fetcher, sender, settings, now=now)

    climbed = db_session.query(Project).filter_by(mostaql_id="1252460").one()
    kept = db_session.query(Project).filter_by(mostaql_id="1252806").one()
    assert climbed.bids_count == 8      # 0 -> 8, refreshed from the listing for free
    assert kept.bids_count == 10        # 10 vs listing's 4 -> never downgrades
    assert run.updated_count == 2       # both were re-observations, not new
    # The refresh costs no extra fetch: only the listing was hit, no /project/ detail pages.
    assert not any("/project/" in c for c in fetcher.calls)
