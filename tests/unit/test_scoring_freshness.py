"""Unit tests for the PURE freshness "still good?" deriver (Feature 4, T032).

Covers the green/yellow/red rules and boundaries of contracts/scoring-model.md §5: red → green →
else yellow (red wins); the default thresholds (bids 8↔9, age 12↔13, bids 19↔20, age 47↔48);
closed/awarded/unknown ⇒ red regardless of bids/age; the single-snapshot low-data fallback; and a
settings threshold change moving a boundary. Project/snapshot are ``SimpleNamespace`` stubs; settings
come from the conftest ``settings`` fixture (real DEFAULTS) or a small stub.
"""
from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import pytest

from mostaql_notifier.config.settings_store import SettingsStore, seed_defaults
from mostaql_notifier.db.models import ProjectStatus, Setting
from mostaql_notifier.scoring.freshness import freshness

NOW = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)


def make_project(*, site_status="open", bids_count=0, age_hours=0.0,
                 posted_at=None, scraped_at=None):
    """A minimal project stub. ``age_hours`` sets ``posted_at`` relative to ``NOW`` unless an
    explicit ``posted_at`` is given; ``scraped_at`` defaults alongside ``posted_at``."""
    if posted_at is None and age_hours is not None:
        posted_at = NOW - timedelta(hours=age_hours)
    if scraped_at is None:
        scraped_at = posted_at if posted_at is not None else NOW
    return types.SimpleNamespace(
        site_status=site_status,
        bids_count=bids_count,
        posted_at=posted_at,
        scraped_at=scraped_at,
    )


def make_snapshot(*, site_status="open", bids_count=0):
    return types.SimpleNamespace(site_status=site_status, bids_count=bids_count)


class StubSettings:
    """A tiny stand-in for ``SettingsStore`` exposing only ``get_int`` for the freshness keys."""

    def __init__(self, **overrides):
        self._values = {
            "freshness_green_max_bids": 8,
            "freshness_green_max_age_hours": 12,
            "freshness_red_min_bids": 20,
            "freshness_red_min_age_hours": 48,
        }
        self._values.update(overrides)

    def get_int(self, key: str) -> int:
        return int(self._values[key])


# --- worked transitions from §5 ------------------------------------------------------------------

def test_worked_green(settings):
    proj = make_project(site_status="open", bids_count=4, age_hours=6)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "green"


def test_worked_yellow_cooling(settings):
    proj = make_project(site_status="open", bids_count=12, age_hours=30)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "yellow"


def test_worked_red_crowded(settings):
    proj = make_project(site_status="open", bids_count=25, age_hours=2)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "red"


def test_worked_red_aged_out(settings):
    proj = make_project(site_status="open", bids_count=4, age_hours=50)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "red"


# --- status always wins (closed / awarded / unknown ⇒ red regardless of bids/age) ----------------

@pytest.mark.parametrize("status", [
    ProjectStatus.closed, ProjectStatus.awarded, ProjectStatus.unknown,
    "closed", "awarded", "unknown",
])
def test_non_open_status_is_red_regardless(settings, status):
    # Even a pristine, fresh project (would be green if open) reads red when not open.
    proj = make_project(site_status=status, bids_count=0, age_hours=0)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "red"


def test_open_enum_status_is_handled(settings):
    proj = make_project(site_status=ProjectStatus.open, bids_count=2, age_hours=1)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "green"


# --- default boundaries (bids 8↔9, age 12↔13, bids 19↔20, age 47↔48) -----------------------------

@pytest.mark.parametrize("bids,expected", [(8, "green"), (9, "yellow")])
def test_green_bids_boundary(settings, bids, expected):
    proj = make_project(site_status="open", bids_count=bids, age_hours=0)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == expected


@pytest.mark.parametrize("age,expected", [(12, "green"), (13, "yellow")])
def test_green_age_boundary(settings, age, expected):
    proj = make_project(site_status="open", bids_count=0, age_hours=age)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == expected


@pytest.mark.parametrize("bids,expected", [(19, "yellow"), (20, "red")])
def test_red_bids_boundary(settings, bids, expected):
    proj = make_project(site_status="open", bids_count=bids, age_hours=2)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == expected


@pytest.mark.parametrize("age,expected", [(47, "yellow"), (48, "red")])
def test_red_age_boundary(settings, age, expected):
    proj = make_project(site_status="open", bids_count=2, age_hours=age)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == expected


# --- snapshot sourcing + low-data fallback (FR-025) ----------------------------------------------

def test_snapshot_overrides_project_bids(settings):
    # Project still looks fresh, but the latest snapshot shows a crowded board ⇒ red.
    proj = make_project(site_status="open", bids_count=1, age_hours=1)
    snap = make_snapshot(site_status="open", bids_count=25)
    assert freshness(proj, snap, settings=settings, now_utc=NOW) == "red"


def test_snapshot_overrides_project_status(settings):
    # Project recorded open, but the latest snapshot observed it closed ⇒ red.
    proj = make_project(site_status="open", bids_count=2, age_hours=1)
    snap = make_snapshot(site_status="closed", bids_count=2)
    assert freshness(proj, snap, settings=settings, now_utc=NOW) == "red"


def test_single_snapshot_low_data_returns_colour(settings):
    # One snapshot, bids unknown (None) — no velocity to compute; must degrade gracefully (no error).
    proj = make_project(site_status="open", bids_count=None, age_hours=3)
    snap = make_snapshot(site_status="open", bids_count=None)
    assert freshness(proj, snap, settings=settings, now_utc=NOW) == "green"


def test_none_bids_treated_as_zero(settings):
    proj = make_project(site_status="open", bids_count=None, age_hours=1)
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "green"


# --- age sourcing / clock-skew guards ------------------------------------------------------------

def test_posted_at_none_uses_scraped_at(settings):
    # No posted_at; scraped_at is 50 h old ⇒ aged out ⇒ red.
    proj = make_project(site_status="open", bids_count=0, age_hours=None,
                        posted_at=None, scraped_at=NOW - timedelta(hours=50))
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "red"


def test_future_posted_at_clamped_to_zero(settings):
    # A future posted_at (clock skew) clamps age to 0; open + few bids ⇒ green, never an error.
    proj = make_project(site_status="open", bids_count=1, posted_at=NOW + timedelta(hours=5))
    assert freshness(proj, None, settings=settings, now_utc=NOW) == "green"


# --- threshold change moves the boundary ---------------------------------------------------------

def test_threshold_change_via_stub_settings_moves_boundary():
    proj = make_project(site_status="open", bids_count=6, age_hours=2)
    # default green bids cap = 8 ⇒ 6 bids is green
    assert freshness(proj, None, settings=StubSettings(), now_utc=NOW) == "green"
    # tighten the cap below 6 ⇒ same project is now yellow
    tighter = StubSettings(freshness_green_max_bids=4)
    assert freshness(proj, None, settings=tighter, now_utc=NOW) == "yellow"


def test_threshold_change_via_settings_store_moves_boundary(db_session):
    seed_defaults(db_session)
    proj = make_project(site_status="open", bids_count=6, age_hours=2)
    assert freshness(proj, None, settings=SettingsStore(db_session), now_utc=NOW) == "green"

    row = db_session.get(Setting, "freshness_green_max_bids")
    row.value = "4"
    db_session.commit()

    # A fresh store re-reads the lowered threshold ⇒ the boundary moved, now yellow.
    assert freshness(proj, None, settings=SettingsStore(db_session), now_utc=NOW) == "yellow"
