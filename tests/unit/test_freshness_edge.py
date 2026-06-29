"""Exhaustive edge-case / branch tests for the PURE freshness deriver (scoring/freshness.py).

Complements ``test_scoring_freshness.py`` by closing the remaining branches of §5: every RED trigger
in isolation (closed/awarded/unknown status, bids ≥ red_min, age ≥ red_min) and every exact boundary
(==), the GREEN conjunction and YELLOW middle band, latest-snapshot override of project status/bids,
the ``status`` normalization for None / enum / lower-case / upper-case strings, and the age-helper
degradations (both timestamps None ⇒ 0, naive-vs-aware subtraction TypeError ⇒ 0). Pure:
``SimpleNamespace`` stubs + a fixed injected ``now_utc`` + a tiny ``StubSettings``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from mostaql_notifier.db.models import ProjectStatus
from mostaql_notifier.scoring.freshness import freshness

NOW = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)


class StubSettings:
    """A minimal ``SettingsStore`` stand-in exposing ``get_int`` for the four freshness keys."""

    def __init__(self, **over):
        self._v = {
            "freshness_green_max_bids": 8,
            "freshness_green_max_age_hours": 12,
            "freshness_red_min_bids": 20,
            "freshness_red_min_age_hours": 48,
        }
        self._v.update(over)

    def get_int(self, key):
        return int(self._v[key])


def _proj(*, site_status="open", bids_count=0, age_hours=0.0, posted_at=None, scraped_at=None):
    if posted_at is None and age_hours is not None:
        posted_at = NOW - timedelta(hours=age_hours)
    if scraped_at is None:
        scraped_at = posted_at if posted_at is not None else NOW
    return SimpleNamespace(
        site_status=site_status, bids_count=bids_count, posted_at=posted_at, scraped_at=scraped_at,
    )


def _snap(*, site_status="open", bids_count=0):
    return SimpleNamespace(site_status=site_status, bids_count=bids_count)


def _fresh(proj, snap=None, settings=None):
    return freshness(proj, snap, settings=settings or StubSettings(), now_utc=NOW)


# --------------------------------------------------------------------------- RED triggers (isolated)


@pytest.mark.parametrize("status", ["closed", "awarded", "unknown"])
def test_red_status_regardless_of_bids_and_age(status):
    # A pristine, fresh project that would be green if open reads red on a terminal status.
    assert _fresh(_proj(site_status=status, bids_count=0, age_hours=0)) == "red"


def test_red_when_bids_at_threshold_only():
    # Open + fresh, but bids ≥ red_min_bids ⇒ red (the bid axis alone trips it).
    assert _fresh(_proj(site_status="open", bids_count=20, age_hours=1)) == "red"


def test_red_when_age_at_threshold_only():
    # Open + uncrowded, but age ≥ red_min_age_hours ⇒ red (the age axis alone trips it).
    assert _fresh(_proj(site_status="open", bids_count=0, age_hours=48)) == "red"


# --------------------------------------------------------------------------- GREEN / YELLOW


def test_green_requires_open_and_low_bids_and_fresh():
    assert _fresh(_proj(site_status="open", bids_count=4, age_hours=6)) == "green"


def test_yellow_when_aging_but_open():
    assert _fresh(_proj(site_status="open", bids_count=12, age_hours=30)) == "yellow"


def test_yellow_when_bids_climbing_but_open():
    # bids between green cap (8) and red floor (20), still fresh ⇒ yellow (not green, not red).
    assert _fresh(_proj(site_status="open", bids_count=15, age_hours=2)) == "yellow"


# --------------------------------------------------------------------------- exact boundaries (==)


@pytest.mark.parametrize("bids,expected", [(8, "green"), (9, "yellow")])
def test_green_max_bids_boundary(bids, expected):
    assert _fresh(_proj(site_status="open", bids_count=bids, age_hours=0)) == expected


@pytest.mark.parametrize("age,expected", [(12, "green"), (13, "yellow")])
def test_green_max_age_boundary(age, expected):
    assert _fresh(_proj(site_status="open", bids_count=0, age_hours=age)) == expected


@pytest.mark.parametrize("bids,expected", [(19, "yellow"), (20, "red")])
def test_red_min_bids_boundary(bids, expected):
    assert _fresh(_proj(site_status="open", bids_count=bids, age_hours=2)) == expected


@pytest.mark.parametrize("age,expected", [(47, "yellow"), (48, "red")])
def test_red_min_age_boundary(age, expected):
    assert _fresh(_proj(site_status="open", bids_count=2, age_hours=age)) == expected


# --------------------------------------------------------------------------- snapshot override


def test_snapshot_overrides_project_bids():
    proj = _proj(site_status="open", bids_count=1, age_hours=1)  # project looks green
    assert _fresh(proj, _snap(site_status="open", bids_count=25)) == "red"  # snapshot is crowded


def test_snapshot_overrides_project_status():
    proj = _proj(site_status="open", bids_count=2, age_hours=1)
    assert _fresh(proj, _snap(site_status="closed", bids_count=2)) == "red"


def test_snapshot_none_uses_project():
    proj = _proj(site_status="open", bids_count=4, age_hours=6)
    assert _fresh(proj, None) == "green"


# --------------------------------------------------------------------------- status normalization


def test_status_none_is_not_red_status():
    # None status normalizes to "" (not in RED set, not "open") ⇒ open conjunction fails ⇒ yellow.
    assert _fresh(_proj(site_status=None, bids_count=0, age_hours=0)) == "yellow"


def test_status_open_enum_is_handled():
    assert _fresh(_proj(site_status=ProjectStatus.open, bids_count=2, age_hours=1)) == "green"


@pytest.mark.parametrize("status", [ProjectStatus.closed, ProjectStatus.awarded, ProjectStatus.unknown])
def test_status_enum_terminal_is_red(status):
    assert _fresh(_proj(site_status=status, bids_count=0, age_hours=0)) == "red"


def test_status_uppercase_string_normalized():
    # A bare upper-case string is lower-cased before matching ("OPEN" ⇒ open).
    assert _fresh(_proj(site_status="OPEN", bids_count=2, age_hours=1)) == "green"
    assert _fresh(_proj(site_status="CLOSED", bids_count=0, age_hours=0)) == "red"


def test_status_padded_string_normalized():
    assert _fresh(_proj(site_status="  open  ", bids_count=2, age_hours=1)) == "green"


# --------------------------------------------------------------------------- bids None & age helpers


def test_none_bids_treated_as_zero():
    assert _fresh(_proj(site_status="open", bids_count=None, age_hours=1)) == "green"


def test_posted_at_none_uses_scraped_at():
    proj = _proj(site_status="open", bids_count=0, age_hours=None,
                 posted_at=None, scraped_at=NOW - timedelta(hours=50))
    assert _fresh(proj) == "red"  # scraped_at is 50 h old ⇒ aged out


def test_both_timestamps_none_age_zero_green():
    # No posted_at and no scraped_at ⇒ age basis is None ⇒ age 0.0 ⇒ open/fresh/uncrowded ⇒ green.
    # Build the stub directly (the _proj helper would otherwise default scraped_at to NOW).
    proj = SimpleNamespace(site_status="open", bids_count=0, posted_at=None, scraped_at=None)
    assert _fresh(proj) == "green"


def test_naive_posted_at_subtraction_typeerror_degrades_to_zero():
    # A naive posted_at minus an aware now_utc raises TypeError inside the helper; it degrades to
    # age 0.0 (never propagates) ⇒ open/fresh/uncrowded ⇒ green.
    naive = (NOW - timedelta(hours=100)).replace(tzinfo=None)
    proj = _proj(site_status="open", bids_count=0, age_hours=None, posted_at=naive, scraped_at=naive)
    assert _fresh(proj) == "green"


def test_future_posted_at_clamped_to_zero():
    proj = _proj(site_status="open", bids_count=1, posted_at=NOW + timedelta(hours=5))
    assert _fresh(proj) == "green"


# --------------------------------------------------------------------------- threshold moves boundary


def test_threshold_change_moves_boundary():
    proj = _proj(site_status="open", bids_count=6, age_hours=2)
    assert _fresh(proj, settings=StubSettings()) == "green"             # default cap 8
    assert _fresh(proj, settings=StubSettings(freshness_green_max_bids=4)) == "yellow"  # cap < 6
