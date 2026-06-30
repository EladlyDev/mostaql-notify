"""Unit tests for the rule-based analytics tips (Feature 6, contract §7).

The realistic path is exercised: seed Features 1–4 rows, run :func:`compute_overview` with a fixed
aware ``now`` to get a real :class:`AnalyticsOverview`, and inspect ``overview.tips`` (which already
delegates to :func:`generate_tips`). For finer control a couple of cases call ``generate_tips``
directly with an explicit window. Each rule's support gate is checked from both sides (present /
absent), the suggested score threshold is confirmed advisory, ranking + the ``analytics_max_tips``
cap are asserted, and the whole computation is shown to be read-only (FR-025/FR-027, §7 + Invariants).

All seeded timestamps sit a few days before ``NOW`` so they fall inside the default 90-day window.
The analytics timezone is pinned to UTC so weekday/hour buckets are deterministic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mostaql_notifier.analytics.service import compute_overview
from mostaql_notifier.analytics.timezone import analytics_tz, window_bounds
from mostaql_notifier.analytics.tips import generate_tips
from mostaql_notifier.config.settings_store import (
    SettingsStore,
    app_state_get,
    app_state_set,
)
from mostaql_notifier.db.models import (
    PersonalRecord,
    Project,
    ProjectScore,
    ProjectSnapshot,
    Setting,
)
from tests.api.conftest import (
    make_personal_record,
    make_project,
    make_project_score,
    make_project_snapshot,
)

#: Fixed, injectable "now" — every seeded row is placed inside the resulting default window.
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
#: Common posting anchor: 5 days before NOW (well within the 90-day default range).
WIN = NOW - timedelta(days=5)


# --------------------------------------------------------------------------- helpers


def _set(session, key: str, value, vtype: str) -> None:
    """Update (or insert) a ``settings`` row, then commit so a *fresh* store sees it."""
    from mostaql_notifier.config.settings_store import _serialize

    row = session.get(Setting, key)
    serialized = _serialize(value, vtype)
    if row is None:
        session.add(Setting(key=key, value=serialized, value_type=vtype))
    else:
        row.value = serialized
        row.value_type = vtype
    session.commit()


def _overview(session):
    """Compute the real overview with a fresh (un-cached) store and the fixed ``now``."""
    return compute_overview(session, SettingsStore(session), now=NOW)


def _tip(tips, key: str):
    """The single tip with ``key`` (or ``None`` when the rule was gated out)."""
    return next((t for t in tips if t.key == key), None)


def _mkq(session, n: int, **over) -> Project:
    """A qualified project anchored at ``WIN`` (overridable)."""
    over.setdefault("posted_at", WIN)
    over.setdefault("scraped_at", WIN)
    return make_project(session, _n=n, **over)


@pytest.fixture
def s(db_session, settings):
    """Seeded session (``settings`` seeds the defaults) with the analytics tz pinned to UTC."""
    _set(db_session, "analytics_timezone", "UTC", "str")
    return db_session


# --------------------------------------------------------------------------- empty DB


def test_empty_db_yields_no_tips(s):
    """Honesty under thin data: an empty DB produces zero tips (§7 Invariants)."""
    ov = _overview(s)
    assert ov.tips == []

    # Same result through the direct entry point.
    tz = analytics_tz(s)
    utc_start, utc_end = window_bounds(ov.range.date_from, ov.range.date_to, tz)
    assert (
        generate_tips(ov, SettingsStore(s), session=s, utc_start=utc_start, utc_end=utc_end) == []
    )


# --------------------------------------------------------------------------- peak_window


def test_peak_window_present_and_gated(s):
    """Clustered qualified postings surface the peak-window tip; below support it is omitted."""
    _set(s, "analytics_min_support", 3, "int")
    for i in range(5):  # five projects on the exact same (weekday, hour) cell
        _mkq(s, i)

    ov = _overview(s)
    tip = _tip(ov.tips, "peak_window")
    assert tip is not None
    peak = ov.heatmap.peak
    assert peak is not None and peak.count == 5
    assert tip.evidence["weekday"] == peak.weekday
    assert tip.evidence["hour"] == peak.hour == 12  # 12:00 UTC
    assert tip.evidence["count"] == 5

    # Raise the support gate above the available data ⇒ the tip disappears entirely (FR-025).
    _set(s, "analytics_min_support", 30, "int")
    assert _tip(_overview(s).tips, "peak_window") is None


# --------------------------------------------------------------------------- bid_speed


def test_bid_speed_present_and_gated(s):
    """A median that crosses ``analytics_early_bids`` early yields the bid-speed tip; no support ⇒ none."""
    _set(s, "analytics_min_support", 6, "int")  # competition needs >= this many snapshots
    for i in range(3):  # three multi-snapshot projects → six snapshots, all in the [2,4)h band
        p = _mkq(s, i)
        make_project_snapshot(
            s, project=p, captured_at=WIN + timedelta(hours=2.0), bids_count=10, score=70.0
        )
        make_project_snapshot(
            s, project=p, captured_at=WIN + timedelta(hours=2.5), bids_count=10, score=70.0
        )

    ov = _overview(s)
    assert ov.competition.enough_data
    tip = _tip(ov.tips, "bid_speed")
    assert tip is not None
    assert tip.evidence["early_bids"] == 5  # analytics_early_bids default
    assert tip.evidence["hours"] == 2.0     # age_lo_h of the first crossing band
    # Only bid_speed fired (heatmap below support keeps peak_window out).
    assert _tip(ov.tips, "peak_window") is None

    # Drop the competition section below support ⇒ the tip is omitted.
    _set(s, "analytics_min_support", 7, "int")
    assert _tip(_overview(s).tips, "bid_speed") is None


# --------------------------------------------------------------------------- win_timing


def test_win_timing_present_and_gated(s):
    """Wins applied earlier than the applied population surface the tip; too few wins ⇒ none."""
    _set(s, "analytics_min_wins_support", 2, "int")
    for i in range(2):  # two wins, applied 1h after surfacing (early)
        p = _mkq(s, i)
        make_personal_record(s, project=p, status="won", applied_at=WIN + timedelta(hours=1))
    for i in range(2, 5):  # three non-win applications, applied 10h after surfacing (late)
        p = _mkq(s, i)
        make_personal_record(s, project=p, status="applied", applied_at=WIN + timedelta(hours=10))

    ov = _overview(s)
    tip = _tip(ov.tips, "win_timing")
    assert tip is not None
    assert tip.evidence["n_wins"] == 2
    assert tip.evidence["won_applied_lag"] < tip.evidence["overall_applied_lag"]

    # Same answer through a direct generate_tips call with an explicit window (finer control).
    tz = analytics_tz(s)
    utc_start, utc_end = window_bounds(ov.range.date_from, ov.range.date_to, tz)
    direct = generate_tips(
        ov, SettingsStore(s), session=s, utc_start=utc_start, utc_end=utc_end
    )
    assert _tip(direct, "win_timing") is not None

    # Fewer wins than the support floor ⇒ the tip vanishes (so does score_threshold, same gate).
    _set(s, "analytics_min_wins_support", 5, "int")
    assert _tip(_overview(s).tips, "win_timing") is None


# --------------------------------------------------------------------------- score_threshold


def test_score_threshold_present_advisory_and_gated(s):
    """The suggested cut-off keeps most past wins, is advisory, and is gated by win support."""
    _set(s, "analytics_min_wins_support", 2, "int")
    # Two scored wins (80, 90) and three scored non-win qualified projects (40, 50, 60).
    for i, score in enumerate((80.0, 90.0)):
        p = _mkq(s, i)
        make_personal_record(s, project=p, status="won")  # no applied_at ⇒ win_timing stays silent
        make_project_score(s, project=p, score=score)
    for i, score in zip(range(2, 5), (40.0, 50.0, 60.0), strict=True):
        p = _mkq(s, i)
        make_project_score(s, project=p, score=score)

    keep = SettingsStore(s).get_float("analytics_suggested_threshold_keep")  # 0.9 default

    # Snapshot of mutable state to prove the advisory rule writes nothing (FR-027).
    settings_before = s.query(Setting).count()
    scores_before = sorted(v for (v,) in s.query(ProjectScore.score).all())

    ov = _overview(s)
    tip = _tip(ov.tips, "score_threshold")
    assert tip is not None
    ev = tip.evidence
    assert ev["T"] == 80.0
    assert ev["total_wins"] == 2
    assert ev["kept_wins"] == 2
    assert ev["kept_wins"] / ev["total_wins"] >= keep  # keeps >= the configured share of wins
    assert ev["cut_share"] == 1.0  # all three non-win scores sit below T=80

    # Advisory only: no settings changed, no scores rewritten, no budget floor gated.
    assert s.query(Setting).count() == settings_before
    assert sorted(v for (v,) in s.query(ProjectScore.score).all()) == scores_before
    assert app_state_get(s, "active_budget_floor") is None

    # Below the win-support floor ⇒ omitted entirely.
    _set(s, "analytics_min_wins_support", 5, "int")
    assert _tip(_overview(s).tips, "score_threshold") is None


# --------------------------------------------------------------------------- budget_fallback


def test_budget_fallback_present_and_gated(s):
    """When the live floor is the fallback and recent Tier-1 supply is scarce, the tip explains it."""
    store = SettingsStore(s)
    fallback = store.get_decimal("budget_fallback_floor")  # 100
    primary = store.get_decimal("budget_primary_floor")    # 250

    # Force the active floor to the fallback value; no recent Tier-1 supply exists.
    app_state_set(s, "active_budget_floor", str(fallback))
    ov = _overview(s)
    tip = _tip(ov.tips, "budget_fallback")
    assert tip is not None
    assert tip.evidence["active_floor"] == float(fallback)
    assert tip.evidence["tier1_recent"] == 0
    assert tip.evidence["fallback_target"] == store.get_int("fallback_target")

    # When the active floor is the primary, the live condition is false ⇒ omitted.
    app_state_set(s, "active_budget_floor", str(primary))
    assert _tip(_overview(s).tips, "budget_fallback") is None


# --------------------------------------------------------------------------- ranking + cap


def test_ranking_order_and_max_tips_cap(s):
    """Multiple firing rules keep the fixed order and are truncated to ``analytics_max_tips``."""
    _set(s, "analytics_min_support", 5, "int")
    _set(s, "analytics_min_wins_support", 2, "int")

    # peak + competition base: three multi-snapshot projects (six snapshots in [2,4)h).
    for i in range(3):
        p = _mkq(s, i)
        make_project_snapshot(
            s, project=p, captured_at=WIN + timedelta(hours=2.0), bids_count=10, score=70.0
        )
        make_project_snapshot(
            s, project=p, captured_at=WIN + timedelta(hours=2.5), bids_count=10, score=70.0
        )
    # win_timing: two early wins + two late applications.
    for i in range(3, 5):
        p = _mkq(s, i)
        make_personal_record(s, project=p, status="won", applied_at=WIN + timedelta(hours=1))
    for i in range(5, 7):
        p = _mkq(s, i)
        make_personal_record(s, project=p, status="applied", applied_at=WIN + timedelta(hours=10))

    # With a generous cap, the three firing rules appear in the fixed contract order.
    _set(s, "analytics_max_tips", 6, "int")
    keys = [t.key for t in _overview(s).tips]
    assert keys == ["peak_window", "bid_speed", "win_timing"]

    # A small cap truncates to the top-ranked rules.
    _set(s, "analytics_max_tips", 2, "int")
    capped = _overview(s).tips
    assert len(capped) == 2
    assert [t.key for t in capped] == ["peak_window", "bid_speed"]


# --------------------------------------------------------------------------- read-only


def test_generation_is_read_only(s):
    """Computing the overview / tips issues no writes to the four data tables (§7 Invariants)."""
    _set(s, "analytics_min_support", 2, "int")
    _set(s, "analytics_min_wins_support", 1, "int")

    # A representative mix across every table the rules touch.
    won = _mkq(s, 1)
    make_personal_record(s, project=won, status="won", applied_at=WIN + timedelta(hours=1))
    make_project_score(s, project=won, score=85.0)

    other = _mkq(s, 2)
    make_project_score(s, project=other, score=45.0)

    snap = _mkq(s, 3)
    make_project_snapshot(
        s, project=snap, captured_at=WIN + timedelta(hours=2.0), bids_count=12, score=70.0
    )

    def _counts():
        return (
            s.query(Project).count(),
            s.query(ProjectScore).count(),
            s.query(ProjectSnapshot).count(),
            s.query(PersonalRecord).count(),
        )

    before = _counts()

    ov = _overview(s)
    tz = analytics_tz(s)
    utc_start, utc_end = window_bounds(ov.range.date_from, ov.range.date_to, tz)
    generate_tips(ov, SettingsStore(s), session=s, utc_start=utc_start, utc_end=utc_end)

    assert _counts() == before
    # No budget-floor state was created as a side effect of the budget_fallback probe.
    assert app_state_get(s, "active_budget_floor") is None
