"""Exhaustive unit tests for the shared stats module (Feature 3).

``personal.stats`` is the single source of the figures rendered by BOTH the Telegram ``/stats`` +
``/health`` reports and the dashboard Home overview. These tests pin its arithmetic, its engaged
predicate, its timezone day-boundary (including the bad-tz fallback), and the bot<->dashboard
parity guarantee (the same DB must yield the same numbers through ``api/routers/home.py``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mostaql_notifier.api.routers.home import get_home
from mostaql_notifier.db.models import (
    EvalStatus,
    ProjectStatus,
    RunStatus,
    Setting,
)
from mostaql_notifier.personal import stats, statuses
from tests.api.conftest import (
    make_client,
    make_personal_record,
    make_project,
    make_scrape_run,
)

# --- helpers ---------------------------------------------------------------

def _set(session, key: str, value) -> None:
    """Update a seeded ``settings`` row in place (the stats functions read it back fresh)."""
    row = session.get(Setting, key)
    if isinstance(value, bool):
        row.value = "true" if value else "false"
    else:
        row.value = str(value)
    session.commit()


def _aware(dt: datetime | None) -> datetime | None:
    """Normalise a possibly-naive DB datetime to aware UTC for instant comparison."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# --- today_start_utc -------------------------------------------------------

def test_today_start_utc_valid_timezone_returns_local_midnight_in_utc(db_session, settings):
    _set(db_session, "owner_timezone", "America/New_York")

    result = stats.today_start_utc(db_session)

    # Always returned as an aware UTC instant...
    assert result.tzinfo == timezone.utc
    # ...that is exactly local midnight of the configured zone (proves the configured tz is used,
    # not the Cairo fallback — Cairo midnight is NOT midnight in New York).
    local = result.astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)


def test_today_start_utc_bad_timezone_falls_back_to_cairo_without_raising(db_session, settings):
    # Garbage owner_timezone must NOT raise; it falls back to Africa/Cairo (covers stats.py L25-26).
    _set(db_session, "owner_timezone", "Not/AZone")
    fallback = stats.today_start_utc(db_session)  # must not raise

    _set(db_session, "owner_timezone", "Africa/Cairo")
    cairo = stats.today_start_utc(db_session)

    assert fallback.tzinfo == timezone.utc
    # The fallback produced the SAME instant as an explicit Africa/Cairo configuration.
    assert fallback == cairo
    # And it is local midnight in Cairo.
    local = fallback.astimezone(ZoneInfo("Africa/Cairo"))
    assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)


# --- is_paused -------------------------------------------------------------

def test_is_paused_reflects_flag(db_session, settings):
    assert stats.is_paused(db_session) is False  # seeded default
    _set(db_session, "watcher_paused", True)
    assert stats.is_paused(db_session) is True


# --- per_stage_counts ------------------------------------------------------

def test_per_stage_counts_empty_db_has_every_slug_at_zero(db_session, settings):
    result = stats.per_stage_counts(db_session)
    configured = {s["key"] for s in statuses.list_statuses(db_session)}

    assert set(result.keys()) == configured
    assert all(v == 0 for v in result.values())


def test_per_stage_counts_engaged_predicate(db_session, settings):
    # Anchor: the seeded default is "new".
    assert statuses.default_status(db_session) == "new"

    # (a) default status, not favorite, not hidden -> NOT engaged.
    make_personal_record(db_session, project=make_project(db_session, _n=1),
                         status="new", favorite=False, hidden=False)
    # (b) favorite + default status -> engaged, counted under the default slug.
    make_personal_record(db_session, project=make_project(db_session, _n=2),
                         status="new", favorite=True, hidden=False)
    # (c) status != default ("applied") -> engaged, counted under that slug.
    make_personal_record(db_session, project=make_project(db_session, _n=3),
                         status="applied", favorite=False, hidden=False)
    # (d) favorite BUT hidden -> NOT counted (hidden always excluded).
    make_personal_record(db_session, project=make_project(db_session, _n=4),
                         status="won", favorite=True, hidden=True)
    # (e) status removed from config ("ghost"): engaged, but omitted (no configured column).
    make_personal_record(db_session, project=make_project(db_session, _n=5),
                         status="ghost", favorite=True, hidden=False)

    result = stats.per_stage_counts(db_session)

    # Keys are EXACTLY the configured slugs (a stale/removed status is never a key).
    configured = {s["key"] for s in statuses.list_statuses(db_session)}
    assert set(result.keys()) == configured
    assert "ghost" not in result

    assert result["new"] == 1       # only (b) — (a) is the un-engaged default
    assert result["applied"] == 1   # (c)
    # Everything else has no engaged record.
    for slug in configured - {"new", "applied"}:
        assert result[slug] == 0


# --- compute_stats ---------------------------------------------------------

def test_compute_stats_counts_today_totals_and_per_stage(db_session, settings):
    now = datetime.now(timezone.utc)
    two_days = now - timedelta(days=2)

    # found today + qualified today
    p_today = make_project(db_session, _n=1, scraped_at=now, qualified_at=now,
                           site_status=ProjectStatus.open, eval_status=EvalStatus.qualified)
    # neither (scraped + qualified two days ago)
    make_project(db_session, _n=2, scraped_at=two_days, qualified_at=two_days)
    # found today but not qualified (qualified_at NULL excluded by the is_not(None) clause)
    make_project(db_session, _n=3, scraped_at=now, qualified_at=None)
    make_client(db_session, _n=1)

    # Engage one record so per_stage is non-trivial.
    make_personal_record(db_session, project=p_today, status="applied")

    result = stats.compute_stats(db_session)

    assert result["found_today"] == 2          # p1 + p3
    assert result["qualified_today"] == 1       # p1 only
    assert result["total_projects"] == 3
    assert result["total_clients"] == 1
    assert result["per_stage"] == stats.per_stage_counts(db_session)
    assert result["per_stage"]["applied"] == 1
    assert result["paused"] is False

    _set(db_session, "watcher_paused", True)
    assert stats.compute_stats(db_session)["paused"] is True


def test_compute_stats_empty_db_is_all_zero(db_session, settings):
    result = stats.compute_stats(db_session)
    assert result["found_today"] == 0
    assert result["qualified_today"] == 0
    assert result["total_projects"] == 0
    assert result["total_clients"] == 0
    assert all(v == 0 for v in result["per_stage"].values())
    assert result["paused"] is False


# --- compute_health --------------------------------------------------------

def test_compute_health_no_runs_is_all_none_but_paused_tracks_flag(db_session, settings):
    health = stats.compute_health(db_session)

    assert health["last_successful_scrape"] is None
    assert health["latest_run_status"] is None
    assert health["found_count"] is None
    assert health["new_count"] is None
    assert health["updated_count"] is None
    assert health["error_count"] is None
    assert health["paused"] is False

    _set(db_session, "watcher_paused", True)
    # An intentional idle (no runs) is still distinguishable from a fault via the flag.
    assert stats.compute_health(db_session)["paused"] is True


def test_compute_health_latest_run_drives_status_but_last_success_persists(db_session, settings):
    base = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)

    success = make_scrape_run(
        db_session,
        started_at=base - timedelta(minutes=10),
        finished_at=base - timedelta(minutes=5),
        status=RunStatus.success,
        found_count=10, new_count=2, updated_count=1, error_count=0,
    )

    health = stats.compute_health(db_session)
    assert _aware(health["last_successful_scrape"]) == success.finished_at
    assert health["latest_run_status"] == "success"
    assert health["found_count"] == 10
    assert health["new_count"] == 2
    assert health["updated_count"] == 1
    assert health["error_count"] == 0
    assert health["paused"] is False

    # A LATER failed run becomes the latest (by started_at) — health status flips to failed, and its
    # counts surface, but the last SUCCESSFUL scrape time still points at the earlier green run.
    failed = make_scrape_run(
        db_session,
        started_at=base - timedelta(minutes=1),
        finished_at=base,
        status=RunStatus.failed,
        found_count=5, new_count=0, updated_count=0, error_count=3,
    )

    health2 = stats.compute_health(db_session)
    assert health2["latest_run_status"] == "failed"
    assert _aware(health2["last_successful_scrape"]) == success.finished_at  # unchanged
    assert health2["found_count"] == failed.found_count == 5
    assert health2["error_count"] == 3

    _set(db_session, "watcher_paused", True)
    assert stats.compute_health(db_session)["paused"] is True


# --- bot <-> dashboard parity ---------------------------------------------

def test_stats_match_home_router_for_same_db(db_session, settings):
    """The shared figures must be byte-for-byte the SAME through the dashboard Home route."""
    now = datetime.now(timezone.utc)
    make_project(db_session, _n=1, scraped_at=now, qualified_at=now)
    make_project(db_session, _n=2, scraped_at=now - timedelta(days=2),
                 qualified_at=now - timedelta(days=2))
    make_client(db_session, _n=1)

    shared = stats.compute_stats(db_session)
    home = get_home(db_session)  # the real Home endpoint logic, called directly with the session

    assert shared["found_today"] == home.found_today
    assert shared["qualified_today"] == home.qualified_today
    assert shared["total_projects"] == home.total_projects
    assert shared["total_clients"] == home.total_clients
