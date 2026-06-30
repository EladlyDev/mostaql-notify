"""Comprehensive unit suite for the six read-only analytics aggregates (Feature 6, contract §1–§6).

Each function under test has the signature ``(session, settings, *, utc_start, utc_end)`` and returns a
Pydantic DTO from ``api.schemas``. The tests pin every behavioural invariant from
``contracts/analytics-aggregates.md`` ("Invariants (test gates)"): the posting-time fallback, the
qualified-only / all-projects split, fail-closed outcomes, robust medians, the monotonic funnel,
zero-denominator conversions, and "honest under thin data" (each section's ``enough_data`` gate).

Determinism: the analytics timezone defaults to Africa/Cairo (``analytics_timezone`` "" ⇒
``owner_timezone``). Every project "when" is built from a *Cairo-local* wall-clock time converted to
UTC via :func:`at_cairo`, so the local (weekday, hour, date) buckets are exact regardless of DST.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from mostaql_notifier.analytics.aggregates import (
    budget_distribution,
    competition_dynamics,
    funnel,
    outcome_analytics,
    posting_heatmap,
    volume_trends,
)
from mostaql_notifier.config.settings_store import SettingsStore
from mostaql_notifier.db.models import (
    EvalStatus,
    Outcome,
    PersonalRecord,
    Project,
    ProjectScore,
    ProjectSnapshot,
    ProjectStatus,
    Setting,
)
from tests.api.conftest import (
    make_personal_record,
    make_project,
    make_project_score,
    make_project_snapshot,
    make_trajectory,
)

# A window wide enough to contain every instant any test constructs.
WIDE: tuple[datetime, datetime] = (
    datetime(2000, 1, 1, tzinfo=timezone.utc),
    datetime(2100, 1, 1, tzinfo=timezone.utc),
)

CAIRO = ZoneInfo("Africa/Cairo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def at_cairo(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """A UTC instant whose Africa/Cairo wall-clock is exactly the given parts (DST-correct)."""
    return datetime(year, month, day, hour, minute, tzinfo=CAIRO).astimezone(timezone.utc)


def set_setting(session, key: str, value) -> SettingsStore:
    """Override a (seeded) ``Setting`` row in place, then return a FRESH ``SettingsStore``.

    ``SettingsStore`` caches on first read, so a write requires a new store for the change to be
    observed — this is the "config over code" gate (a setting change alters output on the next call
    with no code change).
    """
    row = session.get(Setting, key)
    if isinstance(value, bool):
        serialized, vtype = ("true" if value else "false"), "bool"
    elif isinstance(value, (list, dict)):
        serialized, vtype = json.dumps(value, ensure_ascii=False), "json"
    elif isinstance(value, int):
        serialized, vtype = str(value), "int"
    elif isinstance(value, float):
        serialized, vtype = str(value), "float"
    else:
        serialized, vtype = str(value), "str"
    if row is None:
        session.add(Setting(key=key, value=serialized, value_type=vtype))
    else:
        row.value = serialized  # keep the seeded value_type
    session.commit()
    return SettingsStore(session)


@pytest.fixture
def mk(db_session):
    """``make_project`` with an auto-incrementing ``_n`` so each call gets a unique ``mostaql_id``."""
    state = {"n": 0}

    def _mk(**over):
        state["n"] += 1
        over.setdefault("_n", state["n"])
        return make_project(db_session, **over)

    return _mk


def _cell(hm, weekday: int, hour: int) -> int:
    for c in hm.cells:
        if c.weekday == weekday and c.hour == hour:
            return c.count
    return 0


def _bucket(dist, lo, hi) -> int:
    for b in dist.buckets:
        if b.lo == lo and b.hi == hi:
            return b.count
    raise AssertionError(f"no budget bucket ({lo}, {hi})")


def _band(dyn, age_lo_h: float):
    for p in dyn.age_curve:
        if p.age_lo_h == age_lo_h:
            return p
    raise AssertionError(f"no age-curve band starting at {age_lo_h}")


def _stage(fn, key: str):
    for s in fn.stages:
        if s.key == key:
            return s
    raise AssertionError(f"no funnel stage {key}")


def _traj_project(mk, db_session, pt, points, **over) -> Project:
    """A qualified project posted at ``pt`` with a snapshot per ``(age_hours, bids)`` in ``points``."""
    p = mk(posted_at=pt, scraped_at=pt, **over)
    make_trajectory(
        db_session,
        p,
        [(pt + timedelta(hours=age), bids, ProjectStatus.open, 70.0) for age, bids in points],
    )
    return p


# ---------------------------------------------------------------------------
# §1 — posting_heatmap
# ---------------------------------------------------------------------------


def test_heatmap_cells_peak_fallback_and_qualified_only(db_session, settings, mk):
    # Monday 2025-01-06 → Arabic weekday (Mon=0 → (0+2)%7) = 2; three qualified projects at 14:00.
    for _ in range(3):
        mk(posted_at=at_cairo(2025, 1, 6, 14, 0))
    # Tuesday 2025-01-07 09:00 → weekday 3, hour 9 (one project).
    mk(posted_at=at_cairo(2025, 1, 7, 9, 0))
    # posted_at = None ⇒ the heatmap falls back to scraped_at (Wednesday 2025-01-08 20:00 → wd 4, h 20).
    mk(posted_at=None, scraped_at=at_cairo(2025, 1, 8, 20, 0))
    # A disqualified project on the peak cell must be ignored (qualified-only).
    mk(posted_at=at_cairo(2025, 1, 6, 14, 0), eval_status=EvalStatus.disqualified)

    hm = posting_heatmap(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    assert hm.total == 5  # 3 + 1 + 1 qualified; the disqualified one excluded
    assert _cell(hm, 2, 14) == 3  # peak cell — would be 4 if the disqualified one leaked in
    assert _cell(hm, 3, 9) == 1
    assert _cell(hm, 4, 20) == 1  # scraped_at fallback was placed and counted
    assert hm.peak is not None
    assert (hm.peak.weekday, hm.peak.hour, hm.peak.count) == (2, 14, 3)
    assert hm.weekday_labels[0] == "السبت"  # Arabic week order, Saturday first


def test_heatmap_enough_data_flips_on_min_support(db_session, settings, mk):
    for _ in range(5):
        mk(posted_at=at_cairo(2025, 1, 6, 14, 0))

    # Default analytics_min_support (30) ⇒ 5 records is not "enough".
    base = posting_heatmap(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert base.total == 5 and base.enough_data is False

    low = set_setting(db_session, "analytics_min_support", 2)
    assert posting_heatmap(db_session, low, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is True

    high = set_setting(db_session, "analytics_min_support", 6)  # above the count
    assert posting_heatmap(db_session, high, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is False


# ---------------------------------------------------------------------------
# §2 — volume_trends
# ---------------------------------------------------------------------------


def test_volume_counts_all_in_total_qualified_share_and_sorted_buckets(db_session, settings, mk):
    # Monday 2025-01-06: 2 qualified + 1 disqualified.
    mk(posted_at=at_cairo(2025, 1, 6, 10))
    mk(posted_at=at_cairo(2025, 1, 6, 11))
    mk(posted_at=at_cairo(2025, 1, 6, 12), eval_status=EvalStatus.disqualified)
    # Tuesday 2025-01-07: 1 qualified.
    mk(posted_at=at_cairo(2025, 1, 7, 10))
    # Monday 2025-01-13 (next ISO week): 1 qualified.
    mk(posted_at=at_cairo(2025, 1, 13, 10))

    vt = volume_trends(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    # by_day: ALL projects in total, only qualified in qualified; ascending by period.
    assert [p.period for p in vt.by_day] == ["2025-01-06", "2025-01-07", "2025-01-13"]
    assert [p.total for p in vt.by_day] == [3, 1, 1]
    assert [p.qualified for p in vt.by_day] == [2, 1, 1]

    # by_week: 06+07 share ISO week 2; 13 is week 3; ascending and consistent with totals.
    assert [p.period for p in vt.by_week] == ["2025-W02", "2025-W03"]
    assert [(p.total, p.qualified) for p in vt.by_week] == [(4, 3), (1, 1)]

    assert vt.category == "development"
    assert vt.enough_data is True  # 3 non-empty day buckets ≥ 2


def test_volume_enough_data_requires_two_nonempty_days(db_session, settings, mk):
    mk(posted_at=at_cairo(2025, 2, 3, 9))
    mk(posted_at=at_cairo(2025, 2, 3, 11))  # same single day
    one_day = volume_trends(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert len(one_day.by_day) == 1 and one_day.enough_data is False

    mk(posted_at=at_cairo(2025, 2, 4, 9))  # a second distinct day
    two_days = volume_trends(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert len(two_days.by_day) == 2 and two_days.enough_data is True


# ---------------------------------------------------------------------------
# §3 — budget_distribution
# ---------------------------------------------------------------------------


def test_budget_bands_unknown_band_tiers_and_enough_data(db_session, settings, mk):
    # USD currency, default rate 1.0, basis "max" ⇒ budget_max drives the band.
    mk(budget_min=0, budget_max=50, currency="USD", tier=1)         # [0, 100)
    mk(budget_min=None, budget_max=200, currency="USD", tier=1)     # [100, 250) — one-sided, resolved
    mk(budget_min=100, budget_max=300, currency="USD", tier=2)      # [250, 500)
    mk(budget_min=2000, budget_max=3000, currency="USD", tier=1)    # [2500, +inf)
    # Unknown band (lo=hi=None): no budget at all, and an unknown currency — both counted, never dropped.
    mk(budget_min=None, budget_max=None, currency="USD", tier=2)    # unknown (no budget)
    mk(budget_min=100, budget_max=400, currency="EUR", tier=None)   # unknown (currency not in rates)

    dist = budget_distribution(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    assert dist.total == 6
    assert _bucket(dist, 0.0, 100.0) == 1
    assert _bucket(dist, 100.0, 250.0) == 1
    assert _bucket(dist, 250.0, 500.0) == 1
    assert _bucket(dist, 2500.0, None) == 1
    assert _bucket(dist, 500.0, 1000.0) == 0
    # The unknown / partial-budget band carries both unknowns and is distinguished by lo=hi=None.
    assert _bucket(dist, None, None) == 2
    assert dist.unknown_count == 2

    # tier counts come straight off Project.tier.
    assert dist.tier1_count == 3
    assert dist.tier2_count == 2

    # enough_data gates on qualified-WITH-budget (4 here), not the total (6) or the unknowns.
    assert dist.enough_data is False  # default support 30
    assert budget_distribution(
        db_session, set_setting(db_session, "analytics_min_support", 4), utc_start=WIDE[0], utc_end=WIDE[1]
    ).enough_data is True
    assert budget_distribution(
        db_session, set_setting(db_session, "analytics_min_support", 5), utc_start=WIDE[0], utc_end=WIDE[1]
    ).enough_data is False  # 4 with-budget < 5


# ---------------------------------------------------------------------------
# §4 — competition_dynamics
# ---------------------------------------------------------------------------


def test_competition_age_curve_rises_and_crowded_headline(db_session, settings, mk):
    pt = at_cairo(2025, 1, 6, 0, 0)
    points = [(0.5, 2), (1.5, 5), (3, 10), (6, 20)]  # bids rise with age
    for _ in range(3):
        _traj_project(mk, db_session, pt, points)

    dyn = competition_dynamics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    # Each band carries median + IQR (p25/p75) + n; three identical series ⇒ a tight band.
    b0, b1, b2, b4 = _band(dyn, 0.0), _band(dyn, 1.0), _band(dyn, 2.0), _band(dyn, 4.0)
    assert (b0.median, b1.median, b2.median, b4.median) == (2.0, 5.0, 10.0, 20.0)
    assert b0.p25 == 2.0 and b0.p75 == 2.0 and b0.n == 3
    # Median rises monotonically with bids across the curve (ascending bands).
    medians = [p.median for p in dyn.age_curve]
    assert medians == sorted(medians) and medians[0] < medians[-1]

    # Crowded headline: first band whose median ≥ analytics_crowded_bids (15) is [4,8) ⇒ age_lo_h 4.0.
    assert dyn.crowded_bids == 15
    assert dyn.crowded_after_hours == 4.0
    assert "15" in dyn.headline and "4" in dyn.headline  # mentions the crowded number + hours
    assert "نشره" in dyn.headline


def test_competition_by_hour_accumulates_positive_deltas_only(db_session, settings, mk):
    pt = at_cairo(2025, 1, 6, 0, 0)
    rising = [(0.5, 2), (1.5, 5), (3, 10), (6, 20)]  # per-project Σ positive Δ = 3+5+10 = 18
    for _ in range(3):
        _traj_project(mk, db_session, pt, rising)
    # A decreasing series contributes max(0, Δ) = 0 — it must NOT reduce by_hour.
    _traj_project(mk, db_session, pt, [(0.5, 10), (1.5, 4)])

    dyn = competition_dynamics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    assert len(dyn.by_hour) == 24
    assert sum(dyn.by_hour) == 54  # 3 × 18; the negative delta clamped to 0


def test_competition_single_snapshot_feeds_curve_not_velocity(db_session, settings, mk):
    pt = at_cairo(2025, 1, 6, 0, 0)
    p = mk(posted_at=pt, scraped_at=pt)
    make_project_snapshot(db_session, project=p, captured_at=pt + timedelta(hours=0.5), bids_count=7)

    dyn = competition_dynamics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    # Contributes to the age curve (single value collapses to median=p25=p75).
    b0 = _band(dyn, 0.0)
    assert (b0.median, b0.p25, b0.p75, b0.n) == (7.0, 7.0, 7.0, 1)
    # But not to velocity / by-hour (no consecutive pair) — and it does not crash.
    assert sum(dyn.by_hour) == 0
    assert dyn.enough_data is False  # 0 multi-snapshot projects


def test_competition_outlier_moves_mean_not_reported_median(db_session, settings, mk):
    pt = at_cairo(2025, 1, 6, 0, 0)
    # Four projects with one snapshot each in band [4,8): three tight, one wild outlier.
    for bids in (16, 17, 18, 1000):
        p = mk(posted_at=pt, scraped_at=pt)
        make_project_snapshot(db_session, project=p, captured_at=pt + timedelta(hours=5), bids_count=bids)

    dyn = competition_dynamics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    band = _band(dyn, 4.0)
    assert band.median == 17.5  # robust: midpoint of 16..18, untouched by the 1000-bid outlier
    assert band.median < 100  # not dragged toward the outlier
    # The headline keys off the median, so it stays robust (17.5 ≥ 15 ⇒ crowded at 4h).
    assert dyn.crowded_after_hours == 4.0 and "15" in dyn.headline


def test_competition_enough_data_requires_three_multi_snapshot_projects(db_session, mk):
    pt = at_cairo(2025, 1, 6, 0, 0)
    pair = [(0.5, 2), (1.5, 5)]
    for _ in range(2):
        _traj_project(mk, db_session, pt, pair)

    low = set_setting(db_session, "analytics_min_support", 1)  # support trivially met
    assert competition_dynamics(db_session, low, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is False  # 2 < 3

    _traj_project(mk, db_session, pt, pair)  # third multi-snapshot project
    assert competition_dynamics(db_session, low, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is True


def test_competition_enough_data_requires_snapshot_support(db_session, mk):
    pt = at_cairo(2025, 1, 6, 0, 0)
    pair = [(0.5, 2), (1.5, 5)]
    for _ in range(3):
        _traj_project(mk, db_session, pt, pair)  # 3 multi-snapshot projects, 6 snapshots total

    met = set_setting(db_session, "analytics_min_support", 6)
    assert competition_dynamics(db_session, met, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is True

    unmet = set_setting(db_session, "analytics_min_support", 100)
    assert competition_dynamics(db_session, unmet, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is False


# ---------------------------------------------------------------------------
# §5 — outcome_analytics
# ---------------------------------------------------------------------------


def _outcome_dataset(db_session, mk):
    """7 scored qualified projects (3 hired / 2 no-hire / 1 unknown / 1 open) + 1 score-less project.

    Returns the hired project (``hC``) that WAS applied to, so the caller can assert it is not "missed".
    Closed-observed times yield TTC values ``[10, 12, 14, 1000]`` (one extreme outlier).
    """
    pt = datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc)

    hA = mk(posted_at=pt, scraped_at=pt)  # hired, no personal record ⇒ missed
    make_project_score(db_session, project=hA, outcome=Outcome.hired, closed_observed_at=pt + timedelta(hours=10))

    hB = mk(posted_at=pt, scraped_at=pt)  # hired, record with applied_at=None ⇒ missed
    make_project_score(db_session, project=hB, outcome=Outcome.hired, closed_observed_at=pt + timedelta(hours=12))
    make_personal_record(db_session, project=hB, applied_at=None)

    hC = mk(posted_at=pt, scraped_at=pt)  # hired, applied ⇒ NOT missed (outlier TTC)
    make_project_score(db_session, project=hC, outcome=Outcome.hired, closed_observed_at=pt + timedelta(hours=1000))
    make_personal_record(db_session, project=hC, applied_at=pt + timedelta(hours=1))

    nD = mk(posted_at=pt, scraped_at=pt)  # closed_no_hire, has a close time
    make_project_score(
        db_session, project=nD, outcome=Outcome.closed_no_hire, closed_observed_at=pt + timedelta(hours=14)
    )
    nE = mk(posted_at=pt, scraped_at=pt)  # closed_no_hire, no close time ⇒ no TTC contribution
    make_project_score(db_session, project=nE, outcome=Outcome.closed_no_hire, closed_observed_at=None)

    uF = mk(posted_at=pt, scraped_at=pt)  # unknown — fail-closed, never folded into hired
    make_project_score(db_session, project=uF, outcome=Outcome.unknown)
    oG = mk(posted_at=pt, scraped_at=pt)  # open — excluded from shares
    make_project_score(db_session, project=oG, outcome=Outcome.open)

    mk(posted_at=pt, scraped_at=pt)  # qualified but score-less ⇒ excluded by score_row.has()
    return hC


def test_outcome_counts_failclosed_and_missed(db_session, settings, mk):
    hC = _outcome_dataset(db_session, mk)

    oc = outcome_analytics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    # Counts (the score-less project is excluded; the four buckets sum to the 7 scored rows).
    assert (oc.hired_count, oc.no_hire_count, oc.unknown_count, oc.open_count) == (3, 2, 1, 1)
    assert oc.hired_count + oc.no_hire_count + oc.unknown_count + oc.open_count == 7
    # Fail-closed: unknown is NOT added to hired; open stays out of the shares.
    assert oc.unknown_count == 1 and oc.hired_count == 3

    # Missed wins render even though enough_data is False (5 concluded < default support 30).
    assert oc.enough_data is False
    assert oc.missed_count == 2 and len(oc.missed) == 2
    assert hC.id not in {m.id for m in oc.missed}  # the applied-to hire is not "missed"
    assert all(m.budget_usd == 500.0 for m in oc.missed)  # default budget_max=500 USD

    # Shares are gated below support (null), never fabricated.
    assert oc.hired_share is None and oc.no_hire_share is None

    # Time-to-close exposes BOTH mean and median; the median is robust to the 1000h outlier.
    ttc = oc.time_to_close_hours
    assert ttc.median == 13.0  # median of [10, 12, 14, 1000]
    assert ttc.mean == 259.0  # mean dragged up by the outlier
    assert ttc.mean != ttc.median and ttc.median < ttc.mean


def test_outcome_shares_emerge_at_support(db_session, mk):
    _outcome_dataset(db_session, mk)  # concluded = 5 (3 hired + 2 no-hire)

    gated = set_setting(db_session, "analytics_min_support", 5)
    oc = outcome_analytics(db_session, gated, utc_start=WIDE[0], utc_end=WIDE[1])
    assert oc.enough_data is True
    assert oc.hired_share == 3 / 5 and oc.no_hire_share == 2 / 5  # over CONCLUDED only

    above = set_setting(db_session, "analytics_min_support", 6)
    oc2 = outcome_analytics(db_session, above, utc_start=WIDE[0], utc_end=WIDE[1])
    assert oc2.enough_data is False and oc2.hired_share is None


# ---------------------------------------------------------------------------
# §6 — funnel (monotonic)
# ---------------------------------------------------------------------------


def test_funnel_monotonic_counts_conversions_and_applied_lag(db_session, settings, mk):
    base = datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc)

    def seen_project(status=None, fav=False, applied_after=None):
        p = mk(qualified_at=base)
        if status is not None or fav or applied_after is not None:
            make_personal_record(
                db_session,
                project=p,
                status=status if status is not None else "new",
                favorite=fav,
                applied_at=(base + timedelta(hours=applied_after)) if applied_after is not None else None,
            )
        return p

    seen_project()                                   # new, plain ⇒ seen only
    seen_project(status="new")                       # no record at all (default) ⇒ seen only
    seen_project(status="interested", fav=True)      # favourited only
    seen_project(status="applied", applied_after=2)  # applied (lag 2h)
    seen_project(status="in_discussion", applied_after=4)  # in_discussion (lag 4h)
    seen_project(status="won", applied_after=6)      # won (lag 6h)

    fn = funnel(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    counts = [(_stage(fn, k).count) for k in ("seen", "favourited", "applied", "in_discussion", "won")]
    assert counts == [6, 4, 3, 2, 1]
    # Monotonic non-increasing by construction.
    assert all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))
    assert fn.seen == 6

    # conv_from_prev: None for seen; ratio of consecutive stages otherwise.
    assert _stage(fn, "seen").conv_from_prev is None
    assert _stage(fn, "favourited").conv_from_prev == 4 / 6
    assert _stage(fn, "applied").conv_from_prev == 3 / 4
    assert _stage(fn, "in_discussion").conv_from_prev == 2 / 3
    assert _stage(fn, "won").conv_from_prev == 1 / 2

    # Only the applied stage carries a lag (median of applied_at − seen_time over 2h/4h/6h ⇒ 4h);
    # the other stages have no retained per-stage timestamp ⇒ None (never fabricated).
    assert _stage(fn, "applied").lag_median_hours == 4.0
    for k in ("seen", "favourited", "in_discussion", "won"):
        assert _stage(fn, k).lag_median_hours is None


def test_funnel_zero_denominator_conversion_is_null(db_session, settings, mk):
    mk(qualified_at=datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc))  # one seen, status "new"

    fn = funnel(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    assert _stage(fn, "seen").count == 1
    assert _stage(fn, "favourited").count == 0
    # favourited's denominator is seen (1) ⇒ a real 0.0, not null.
    assert _stage(fn, "favourited").conv_from_prev == 0.0
    # applied/in_discussion/won all divide by a 0 prev-stage ⇒ null, and it never raises.
    for k in ("applied", "in_discussion", "won"):
        assert _stage(fn, k).conv_from_prev is None


def test_funnel_status_rank_comes_from_config(db_session, mk):
    # A custom ordered status list: "z" sits above in_discussion, so reaching it implies the
    # earlier stages — proving the rank is read from personal_statuses, not hard-coded.
    custom = [
        {"key": "a", "label": "أ"},
        {"key": "applied", "label": "تقدّمت"},
        {"key": "in_discussion", "label": "قيد النقاش"},
        {"key": "won", "label": "ربح"},
        {"key": "z", "label": "زد"},
    ]
    cfg = set_setting(db_session, "personal_statuses", custom)
    p = mk(qualified_at=datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc))
    make_personal_record(db_session, project=p, status="z", favorite=False, applied_at=None)

    fn = funnel(db_session, cfg, utc_start=WIDE[0], utc_end=WIDE[1])

    # "z" outranks in_discussion ⇒ favourited/applied/in_discussion reached; "won" needs the exact key.
    assert _stage(fn, "seen").count == 1
    assert _stage(fn, "favourited").count == 1
    assert _stage(fn, "applied").count == 1
    assert _stage(fn, "in_discussion").count == 1
    assert _stage(fn, "won").count == 0


def test_funnel_enough_data_gates_on_seen(db_session, mk):
    for _ in range(3):
        mk(qualified_at=datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc))

    low = set_setting(db_session, "analytics_min_support", 3)
    assert funnel(db_session, low, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is True
    high = set_setting(db_session, "analytics_min_support", 4)
    assert funnel(db_session, high, utc_start=WIDE[0], utc_end=WIDE[1]).enough_data is False


# ---------------------------------------------------------------------------
# Cross-cutting invariants: honest-under-thin-data + strictly read-only
# ---------------------------------------------------------------------------


def test_all_aggregates_honest_on_empty_db(db_session, settings):
    hm = posting_heatmap(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert hm.total == 0 and hm.peak is None and hm.cells == [] and hm.enough_data is False

    vt = volume_trends(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert vt.by_day == [] and vt.by_week == [] and vt.enough_data is False

    bd = budget_distribution(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert bd.total == 0 and bd.unknown_count == 0 and bd.enough_data is False

    dyn = competition_dynamics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert dyn.age_curve == [] and dyn.crowded_after_hours is None
    assert sum(dyn.by_hour) == 0 and dyn.enough_data is False

    oc = outcome_analytics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert oc.hired_count == 0 and oc.missed == [] and oc.hired_share is None and oc.enough_data is False

    fn = funnel(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    assert fn.seen == 0 and _stage(fn, "seen").conv_from_prev is None and fn.enough_data is False


def test_aggregates_are_strictly_read_only(db_session, settings, mk):
    pt = at_cairo(2025, 1, 6, 12)
    won = mk(posted_at=pt, scraped_at=pt, qualified_at=pt)
    make_project_score(db_session, project=won, outcome=Outcome.hired)
    make_project_snapshot(db_session, project=won, captured_at=pt + timedelta(hours=1), bids_count=4)
    make_personal_record(db_session, project=won, status="won", applied_at=pt + timedelta(hours=2))
    mk(posted_at=pt, scraped_at=pt, eval_status=EvalStatus.disqualified)
    db_session.commit()

    def counts() -> tuple[int, int, int, int]:
        return (
            db_session.query(Project).count(),
            db_session.query(ProjectScore).count(),
            db_session.query(ProjectSnapshot).count(),
            db_session.query(PersonalRecord).count(),
        )

    before = counts()
    before_outcome = db_session.query(ProjectScore).filter_by(project_id=won.id).one().outcome
    before_eval = db_session.query(Project).filter_by(id=won.id).one().eval_status

    posting_heatmap(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    volume_trends(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    budget_distribution(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    competition_dynamics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    outcome_analytics(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])
    funnel(db_session, settings, utc_start=WIDE[0], utc_end=WIDE[1])

    assert counts() == before  # no INSERT/DELETE
    assert db_session.query(ProjectScore).filter_by(project_id=won.id).one().outcome == before_outcome
    assert db_session.query(Project).filter_by(id=won.id).one().eval_status == before_eval
