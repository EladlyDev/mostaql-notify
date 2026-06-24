"""Exhaustive coverage for ``GET /api/home``.

Covers today-window counts (found/qualified), full-table totals, the
never-false-green health matrix, last_successful_scrape vs latest_run_status,
multi-run ordering, and owner-timezone fallback behavior.

Timestamps use ``now`` vs ``now - 3 days`` to stay clear of the
local-midnight boundary so the today-window assertions are not tz-flaky.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mostaql_notifier.db.models import EvalStatus, RunStatus, Setting
from tests.api.conftest import make_client, make_project, make_scrape_run


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _three_days_ago() -> datetime:
    return _now() - timedelta(days=3)


def _set_owner_tz(api_env, value: str) -> None:
    with api_env.session() as s:
        s.get(Setting, "owner_timezone").value = value
        s.commit()


def _get_home(api_env, *, auth_enabled: bool = False) -> dict:
    client = api_env.client(auth_enabled=auth_enabled)
    resp = client.get("/api/home")
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# 1. Fresh / empty DB
# --------------------------------------------------------------------------- #
def test_empty_db_all_zero_and_health_unknown(api_env):
    body = _get_home(api_env)
    assert body["found_today"] == 0
    assert body["qualified_today"] == 0
    assert body["total_projects"] == 0
    assert body["total_clients"] == 0
    assert body["last_successful_scrape"] is None
    assert body["latest_run_status"] is None
    # Critical: an empty DB must NOT show green.
    assert body["health"] == "unknown"
    assert body["health"] != "green"


# --------------------------------------------------------------------------- #
# 2. Totals
# --------------------------------------------------------------------------- #
def test_totals_exact_counts(api_env):
    K, M = 4, 3
    with api_env.session() as s:
        for i in range(K):
            make_project(s, _n=i, mostaql_id=f"proj-tot-{i}")
        for j in range(M):
            make_client(s, _n=j, mostaql_id=f"derived:tot-client{j}")
        s.commit()

    body = _get_home(api_env)
    assert body["total_projects"] == K
    assert body["total_clients"] == M


def test_totals_zero_clients_with_projects(api_env):
    with api_env.session() as s:
        make_project(s, _n=1, mostaql_id="proj-only")
        s.commit()
    body = _get_home(api_env)
    assert body["total_projects"] == 1
    assert body["total_clients"] == 0


# --------------------------------------------------------------------------- #
# 3. found_today
# --------------------------------------------------------------------------- #
def test_found_today_counts_only_today(api_env):
    with api_env.session() as s:
        make_project(s, _n=1, mostaql_id="proj-today", scraped_at=_now())
        make_project(s, _n=2, mostaql_id="proj-old", scraped_at=_three_days_ago())
        s.commit()

    body = _get_home(api_env)
    assert body["total_projects"] == 2
    assert body["found_today"] == 1


def test_found_today_zero_when_all_old(api_env):
    with api_env.session() as s:
        make_project(s, _n=1, mostaql_id="proj-old1", scraped_at=_three_days_ago())
        make_project(s, _n=2, mostaql_id="proj-old2", scraped_at=_three_days_ago())
        s.commit()

    body = _get_home(api_env)
    assert body["total_projects"] == 2
    assert body["found_today"] == 0


# --------------------------------------------------------------------------- #
# 4. qualified_today
# --------------------------------------------------------------------------- #
def test_qualified_today_window_and_null_handling(api_env):
    with api_env.session() as s:
        # Counts: qualified_at = now AND eval_status qualified.
        make_project(
            s,
            _n=1,
            mostaql_id="proj-q-today",
            eval_status=EvalStatus.qualified,
            qualified_at=_now(),
        )
        # Does NOT count: never qualified (qualified_at None).
        make_project(
            s,
            _n=2,
            mostaql_id="proj-q-never",
            eval_status=EvalStatus.pending,
            qualified_at=None,
        )
        # Does NOT count: qualified 3 days ago (outside today window).
        make_project(
            s,
            _n=3,
            mostaql_id="proj-q-old",
            eval_status=EvalStatus.qualified,
            qualified_at=_three_days_ago(),
        )
        s.commit()

    body = _get_home(api_env)
    assert body["total_projects"] == 3
    assert body["qualified_today"] == 1


def test_qualified_today_zero_when_none_qualified(api_env):
    with api_env.session() as s:
        make_project(
            s,
            _n=1,
            mostaql_id="proj-noq",
            eval_status=EvalStatus.pending,
            qualified_at=None,
            scraped_at=_now(),
        )
        s.commit()

    body = _get_home(api_env)
    assert body["found_today"] == 1
    assert body["qualified_today"] == 0


# --------------------------------------------------------------------------- #
# 5. Health matrix — latest run (greatest started_at) wins.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("status", "expected_health"),
    [
        (RunStatus.success, "green"),
        (RunStatus.failed, "red"),
        (RunStatus.blocked, "red"),
        (RunStatus.running, "unknown"),
        (RunStatus.partial, "unknown"),
    ],
)
def test_health_single_latest_run(api_env, status, expected_health):
    finished = None if status == RunStatus.running else _now()
    with api_env.session() as s:
        make_scrape_run(
            s,
            status=status,
            started_at=_now() - timedelta(minutes=10),
            finished_at=finished,
        )
        s.commit()

    body = _get_home(api_env)
    assert body["latest_run_status"] == status.value
    assert body["health"] == expected_health
    # running / partial must never be reported as green.
    if status in (RunStatus.running, RunStatus.partial):
        assert body["health"] != "green"


def test_later_failed_after_earlier_success_is_red(api_env):
    base = _now()
    with api_env.session() as s:
        make_scrape_run(
            s,
            status=RunStatus.success,
            started_at=base - timedelta(hours=2),
            finished_at=base - timedelta(hours=2) + timedelta(minutes=5),
        )
        make_scrape_run(
            s,
            status=RunStatus.failed,
            started_at=base - timedelta(minutes=10),
            finished_at=base - timedelta(minutes=5),
        )
        s.commit()

    body = _get_home(api_env)
    # Latest by started_at wins, NOT the existence of an earlier success.
    assert body["latest_run_status"] == "failed"
    assert body["health"] == "red"


# --------------------------------------------------------------------------- #
# 6. last_successful_scrape
# --------------------------------------------------------------------------- #
def test_last_successful_scrape_with_later_failure(api_env):
    base = _now()
    success_finished = (base - timedelta(hours=1)).replace(microsecond=0)
    with api_env.session() as s:
        make_scrape_run(
            s,
            status=RunStatus.success,
            started_at=base - timedelta(hours=1, minutes=5),
            finished_at=success_finished,
        )
        make_scrape_run(
            s,
            status=RunStatus.failed,
            started_at=base - timedelta(minutes=10),
            finished_at=base - timedelta(minutes=5),
        )
        s.commit()

    body = _get_home(api_env)
    assert body["health"] == "red"
    assert body["latest_run_status"] == "failed"
    assert body["last_successful_scrape"] is not None
    returned = datetime.fromisoformat(body["last_successful_scrape"])
    if returned.tzinfo is None:
        returned = returned.replace(tzinfo=timezone.utc)
    assert returned.astimezone(timezone.utc) == success_finished.astimezone(timezone.utc)


def test_last_successful_scrape_null_when_only_failures(api_env):
    base = _now()
    with api_env.session() as s:
        make_scrape_run(
            s,
            status=RunStatus.failed,
            started_at=base - timedelta(minutes=30),
            finished_at=base - timedelta(minutes=25),
        )
        make_scrape_run(
            s,
            status=RunStatus.failed,
            started_at=base - timedelta(minutes=10),
            finished_at=base - timedelta(minutes=5),
        )
        s.commit()

    body = _get_home(api_env)
    assert body["last_successful_scrape"] is None
    assert body["latest_run_status"] == "failed"
    assert body["health"] == "red"


# --------------------------------------------------------------------------- #
# 7 & 9. latest_run_status reflects most-recent-by-started_at among many.
# --------------------------------------------------------------------------- #
def test_latest_run_status_among_many(api_env):
    base = _now()
    with api_env.session() as s:
        make_scrape_run(
            s,
            status=RunStatus.success,
            started_at=base - timedelta(hours=3),
            finished_at=base - timedelta(hours=3) + timedelta(minutes=5),
        )
        make_scrape_run(
            s,
            status=RunStatus.partial,
            started_at=base - timedelta(hours=2),
            finished_at=base - timedelta(hours=2) + timedelta(minutes=5),
        )
        # Newest by started_at:
        make_scrape_run(
            s,
            status=RunStatus.blocked,
            started_at=base - timedelta(minutes=1),
            finished_at=base,
        )
        s.commit()

    body = _get_home(api_env)
    assert body["latest_run_status"] == "blocked"
    assert body["health"] == "red"


def test_three_runs_increasing_started_at_latest_wins(api_env):
    base = _now()
    with api_env.session() as s:
        make_scrape_run(
            s,
            status=RunStatus.failed,
            started_at=base - timedelta(hours=3),
            finished_at=base - timedelta(hours=3) + timedelta(minutes=5),
        )
        make_scrape_run(
            s,
            status=RunStatus.blocked,
            started_at=base - timedelta(hours=2),
            finished_at=base - timedelta(hours=2) + timedelta(minutes=5),
        )
        # Newest run is a success -> green, regardless of earlier reds.
        make_scrape_run(
            s,
            status=RunStatus.success,
            started_at=base - timedelta(minutes=1),
            finished_at=base,
        )
        s.commit()

    body = _get_home(api_env)
    assert body["latest_run_status"] == "success"
    assert body["health"] == "green"


# --------------------------------------------------------------------------- #
# 8. Invalid / valid owner_timezone
# --------------------------------------------------------------------------- #
def test_invalid_owner_timezone_falls_back_no_500(api_env):
    _set_owner_tz(api_env, "Not/AZone")
    with api_env.session() as s:
        make_project(s, _n=1, mostaql_id="proj-tz-now", scraped_at=_now())
        make_project(s, _n=2, mostaql_id="proj-tz-old", scraped_at=_three_days_ago())
        s.commit()

    body = _get_home(api_env)  # 200 asserted inside helper
    assert body["total_projects"] == 2
    # Fallback to Africa/Cairo still yields a sensible today-window count.
    assert body["found_today"] == 1


def test_valid_non_default_owner_timezone(api_env):
    _set_owner_tz(api_env, "UTC")
    with api_env.session() as s:
        make_project(s, _n=1, mostaql_id="proj-utc-now", scraped_at=_now())
        make_project(s, _n=2, mostaql_id="proj-utc-old", scraped_at=_three_days_ago())
        s.commit()

    body = _get_home(api_env)
    assert body["total_projects"] == 2
    assert body["found_today"] == 1
