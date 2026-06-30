"""Read-only analytics aggregates over Features 1–4 data (Feature 6, contract §1–§6).

Every function here is pure/total and **strictly read-only**: it issues only SELECTs and returns the
Pydantic DTO from :mod:`..api.schemas` directly — nothing is written back to any project, score,
snapshot, outcome, or personal record (constitution IV/VIII). All thresholds and the analytics
timezone come from ``settings`` rows (constitution III); each section carries an ``enough_data`` flag
so the UI stays honest under thin data. Unknown numerics (e.g. ``bids_count is None``) stay distinct
from 0 — never coerced. "Qualified" ≡ ``Project.eval_status == EvalStatus.qualified``; a project's
"when" is ``posting_time = posted_at or scraped_at`` (``scraped_at`` is NOT NULL, so always placeable).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..api.schemas import (
    BudgetBucket,
    BudgetDistribution,
    CompetitionDynamics,
    CompetitionPoint,
    Funnel,
    FunnelStage,
    HeatmapCell,
    MissedProject,
    OutcomeAnalytics,
    PostingHeatmap,
    TimeToClose,
    VolumePoint,
    VolumeTrends,
)
from ..config.settings_store import SettingsStore
from ..db.models import EvalStatus, Outcome, Project
from ..personal.statuses import APPLIED_KEY, list_statuses
from ..qualify.filters import budget_usd
from .timezone import (
    WEEKDAY_LABELS,
    analytics_tz,
    day_key,
    iso_week_key,
    local_parts,
)

#: Presentation USD bands for the budget histogram; ``hi=None`` marks the open-ended top band.
_BUDGET_BANDS: list[tuple[int, int | None]] = [
    (0, 100), (100, 250), (250, 500), (500, 1000), (1000, 2500), (2500, None),
]

#: Age (hours-since-posting) bands for the competition curve; the top band is JSON-finite (no inf).
_AGE_BANDS: list[tuple[float, float]] = [
    (0, 1), (1, 2), (2, 4), (4, 8), (8, 16), (16, 24), (24, 48), (48, 72), (72, 9999.0),
]


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _posting_time(project: Project) -> datetime:
    """A project's "when" — ``posted_at`` (approximate, nullable) falling back to ``scraped_at``."""
    return project.posted_at or project.scraped_at


def _seen_time(project: Project) -> datetime:
    """When a qualified project was surfaced — ``qualified_at`` falling back to ``scraped_at``."""
    return project.qualified_at or project.scraped_at


def _posting_in_window(utc_start: datetime, utc_end: datetime):
    """Half-open ``[utc_start, utc_end)`` membership by ``posting_time`` (SQL, index-friendly)."""
    return or_(
        and_(Project.posted_at.is_not(None), Project.posted_at >= utc_start, Project.posted_at < utc_end),
        and_(Project.posted_at.is_(None), Project.scraped_at >= utc_start, Project.scraped_at < utc_end),
    )


def _seen_in_window(utc_start: datetime, utc_end: datetime):
    """Half-open ``[utc_start, utc_end)`` membership by surfaced-time (``qualified_at`` ⇒ ``scraped_at``)."""
    return or_(
        and_(
            Project.qualified_at.is_not(None),
            Project.qualified_at >= utc_start,
            Project.qualified_at < utc_end,
        ),
        and_(Project.qualified_at.is_(None), Project.scraped_at >= utc_start, Project.scraped_at < utc_end),
    )


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    """Robust ``(p25, median, p75)``. Median via :func:`statistics.median`; quartiles via inclusive
    quantiles. A single value collapses to ``(v, v, v)``. Callers guard against an empty list."""
    if len(values) == 1:
        v = values[0]
        return (v, v, v)
    median = statistics.median(values)
    q = statistics.quantiles(values, n=4, method="inclusive")
    return (q[0], median, q[2])


# ---------------------------------------------------------------------------
# §1 — posting heatmap
# ---------------------------------------------------------------------------


def posting_heatmap(
    session: Session,
    settings: SettingsStore,
    *,
    utc_start: datetime,
    utc_end: datetime,
) -> PostingHeatmap:
    """When qualified projects appear: a (weekday, hour) density grid in the analytics tz (§1)."""
    tz = analytics_tz(session)
    projects = session.scalars(
        select(Project).where(
            Project.eval_status == EvalStatus.qualified,
            _posting_in_window(utc_start, utc_end),
        )
    ).all()

    counts: dict[tuple[int, int], int] = defaultdict(int)
    for p in projects:
        weekday, hour, _ = local_parts(_posting_time(p), tz)
        counts[(weekday, hour)] += 1

    total = sum(counts.values())
    cells = [
        HeatmapCell(weekday=weekday, hour=hour, count=count)
        for (weekday, hour), count in sorted(counts.items())
    ]
    peak: HeatmapCell | None = None
    if total > 0:
        (pw, ph), pc = max(counts.items(), key=lambda kv: kv[1])
        peak = HeatmapCell(weekday=pw, hour=ph, count=pc)

    return PostingHeatmap(
        cells=cells,
        weekday_labels=list(WEEKDAY_LABELS),
        total=total,
        peak=peak,
        enough_data=total >= settings.get_int("analytics_min_support"),
    )


# ---------------------------------------------------------------------------
# §2 — volume trends
# ---------------------------------------------------------------------------


def volume_trends(
    session: Session,
    settings: SettingsStore,
    *,
    utc_start: datetime,
    utc_end: datetime,
) -> VolumeTrends:
    """Daily + weekly posting volume over **all** projects in window, with the qualified share (§2)."""
    tz = analytics_tz(session)
    projects = session.scalars(
        select(Project).where(_posting_in_window(utc_start, utc_end))
    ).all()

    day_total: dict[str, int] = defaultdict(int)
    day_qual: dict[str, int] = defaultdict(int)
    week_total: dict[str, int] = defaultdict(int)
    week_qual: dict[str, int] = defaultdict(int)
    for p in projects:
        pt = _posting_time(p)
        dk = day_key(pt, tz)
        wk = iso_week_key(pt, tz)
        day_total[dk] += 1
        week_total[wk] += 1
        if p.eval_status == EvalStatus.qualified:
            day_qual[dk] += 1
            week_qual[wk] += 1

    by_day = [
        VolumePoint(period=k, total=day_total[k], qualified=day_qual[k]) for k in sorted(day_total)
    ]
    by_week = [
        VolumePoint(period=k, total=week_total[k], qualified=week_qual[k]) for k in sorted(week_total)
    ]

    return VolumeTrends(
        by_day=by_day,
        by_week=by_week,
        category=settings.get_str("category_slug"),
        enough_data=len(day_total) >= 2,
    )


# ---------------------------------------------------------------------------
# §3 — budget distribution
# ---------------------------------------------------------------------------


def budget_distribution(
    session: Session,
    settings: SettingsStore,
    *,
    utc_start: datetime,
    utc_end: datetime,
) -> BudgetDistribution:
    """USD-budget histogram of qualified projects in window, with tier + unknown counts (§3)."""
    projects = session.scalars(
        select(Project).where(
            Project.eval_status == EvalStatus.qualified,
            _posting_in_window(utc_start, utc_end),
        )
    ).all()

    band_counts: dict[tuple[int, int | None], int] = {band: 0 for band in _BUDGET_BANDS}
    tier1_count = 0
    tier2_count = 0
    unknown_count = 0
    with_budget = 0
    for p in projects:
        if p.tier == 1:
            tier1_count += 1
        elif p.tier == 2:
            tier2_count += 1

        usd = budget_usd(p, settings)
        if usd is None:
            unknown_count += 1
            continue
        with_budget += 1
        for lo, hi in _BUDGET_BANDS:
            if usd >= lo and (hi is None or usd < hi):
                band_counts[(lo, hi)] += 1
                break

    buckets = [
        BudgetBucket(lo=float(lo), hi=(float(hi) if hi is not None else None), count=band_counts[(lo, hi)])
        for lo, hi in _BUDGET_BANDS
    ]
    # The unknown / partial-budget band (distinguished by lo=hi=None).
    buckets.append(BudgetBucket(lo=None, hi=None, count=unknown_count))

    return BudgetDistribution(
        buckets=buckets,
        tier1_count=tier1_count,
        tier2_count=tier2_count,
        unknown_count=unknown_count,
        total=len(projects),
        enough_data=with_budget >= settings.get_int("analytics_min_support"),
    )


# ---------------------------------------------------------------------------
# §4 — competition dynamics
# ---------------------------------------------------------------------------


def competition_dynamics(
    session: Session,
    settings: SettingsStore,
    *,
    utc_start: datetime,
    utc_end: datetime,
) -> CompetitionDynamics:
    """How competition builds: bids-by-age curve + crowding headline + bidding-by-hour (§4)."""
    tz = analytics_tz(session)
    projects = session.scalars(
        select(Project).where(
            Project.eval_status == EvalStatus.qualified,
            _posting_in_window(utc_start, utc_end),
        )
    ).all()

    band_bids: dict[tuple[float, float], list[float]] = {band: [] for band in _AGE_BANDS}
    by_hour = [0] * 24
    total_snapshots = 0
    multi_snapshot_projects = 0
    for p in projects:
        pt = _posting_time(p)
        snaps = p.snapshots  # relationship ordered by captured_at
        total_snapshots += len(snaps)
        if len(snaps) >= 2:
            multi_snapshot_projects += 1

        # Age curve: each snapshot with a known bid count, bucketed by hours-since-posting.
        for s in snaps:
            if s.bids_count is None:
                continue
            age_h = (s.captured_at - pt).total_seconds() / 3600
            if age_h < 0:  # clock skew — drop
                continue
            for lo, hi in _AGE_BANDS:
                if lo <= age_h < hi:
                    band_bids[(lo, hi)].append(float(s.bids_count))
                    break

        # Bidding-by-hour: positive bid deltas between consecutive snapshots, bucketed by tz hour.
        for i in range(1, len(snaps)):
            b_prev = snaps[i - 1].bids_count
            b_cur = snaps[i].bids_count
            if b_prev is None or b_cur is None:
                continue
            delta = max(0, b_cur - b_prev)
            _, hour, _ = local_parts(snaps[i].captured_at, tz)
            by_hour[hour] += delta

    age_curve: list[CompetitionPoint] = []
    for lo, hi in _AGE_BANDS:
        bids = band_bids[(lo, hi)]
        if not bids:
            continue
        p25, median, p75 = _quartiles(bids)
        age_curve.append(
            CompetitionPoint(
                age_lo_h=float(lo),
                age_hi_h=float(hi),
                median=median,
                p25=p25,
                p75=p75,
                n=len(bids),
            )
        )

    crowded_bids = settings.get_int("analytics_crowded_bids")
    crowded_after_hours: float | None = None
    for point in age_curve:  # ascending by band
        if point.median >= crowded_bids:
            crowded_after_hours = point.age_lo_h
            break
    if crowded_after_hours is not None:
        headline = (
            f"عادةً يتجاوز المشروع {crowded_bids} عرضًا خلال حوالي "
            f"{int(round(crowded_after_hours))} ساعة من نشره"
        )
    else:
        headline = "لا يصل المشروع عادةً إلى هذا الازدحام ضمن الفترة المرصودة"

    enough_data = (multi_snapshot_projects >= 3) and (
        total_snapshots >= settings.get_int("analytics_min_support")
    )

    return CompetitionDynamics(
        age_curve=age_curve,
        crowded_bids=crowded_bids,
        crowded_after_hours=crowded_after_hours,
        headline=headline,
        by_hour=by_hour,
        enough_data=enough_data,
    )


# ---------------------------------------------------------------------------
# §5 — outcome analytics
# ---------------------------------------------------------------------------


def outcome_analytics(
    session: Session,
    settings: SettingsStore,
    *,
    utc_start: datetime,
    utc_end: datetime,
) -> OutcomeAnalytics:
    """Outcomes of scored qualified projects: counts, hire/no-hire shares, TTC, missed wins (§5)."""
    projects = session.scalars(
        select(Project).where(
            Project.eval_status == EvalStatus.qualified,
            _posting_in_window(utc_start, utc_end),
            Project.score_row.has(),
        )
    ).all()

    hired_count = 0
    no_hire_count = 0
    unknown_count = 0
    open_count = 0
    ttc_values: list[float] = []
    missed: list[MissedProject] = []
    missed_count = 0
    for p in projects:
        outcome = p.score_row.outcome
        if outcome == Outcome.hired:
            hired_count += 1
        elif outcome == Outcome.closed_no_hire:
            no_hire_count += 1
        elif outcome == Outcome.unknown:
            unknown_count += 1
        elif outcome == Outcome.open:
            open_count += 1

        # Time-to-close over concluded projects that recorded a close time.
        if outcome in (Outcome.hired, Outcome.closed_no_hire) and p.score_row.closed_observed_at is not None:
            ttc_h = (p.score_row.closed_observed_at - _posting_time(p)).total_seconds() / 3600
            ttc_values.append(ttc_h)

        # Missed opportunities: a hire on a project the owner never applied to.
        if outcome == Outcome.hired:
            rec = p.personal
            if rec is None or rec.applied_at is None:
                missed_count += 1
                if len(missed) < 50:
                    usd = budget_usd(p, settings)
                    missed.append(
                        MissedProject(
                            id=p.id,
                            title=p.title,
                            url=p.url,
                            budget_usd=float(usd) if usd is not None else None,
                        )
                    )

    concluded = hired_count + no_hire_count
    min_support = settings.get_int("analytics_min_support")
    gated = concluded > 0 and concluded >= min_support
    hired_share = (hired_count / concluded) if gated else None
    no_hire_share = (no_hire_count / concluded) if gated else None

    if ttc_values:
        p25, median, p75 = _quartiles(ttc_values)
        ttc = TimeToClose(mean=statistics.mean(ttc_values), median=median, p25=p25, p75=p75)
    else:
        ttc = TimeToClose()

    return OutcomeAnalytics(
        hired_count=hired_count,
        no_hire_count=no_hire_count,
        unknown_count=unknown_count,
        open_count=open_count,
        hired_share=hired_share,
        no_hire_share=no_hire_share,
        time_to_close_hours=ttc,
        missed=missed,
        missed_count=missed_count,
        enough_data=concluded >= min_support,
    )


# ---------------------------------------------------------------------------
# §6 — funnel (monotonic)
# ---------------------------------------------------------------------------


def funnel(
    session: Session,
    settings: SettingsStore,
    *,
    utc_start: datetime,
    utc_end: datetime,
) -> Funnel:
    """Seen → favourited → applied → in_discussion → won, monotonic, with applied-lag median (§6)."""
    projects = session.scalars(
        select(Project).where(
            Project.eval_status == EvalStatus.qualified,
            _seen_in_window(utc_start, utc_end),
        )
    ).all()

    statuses = list_statuses(session)
    rank = {s["key"]: i for i, s in enumerate(statuses)}
    default_key = statuses[0]["key"] if statuses else ""
    applied_rank = rank.get(APPLIED_KEY)
    disc_rank = rank.get("in_discussion")

    seen = len(projects)
    fav_count = 0
    applied_count = 0
    disc_count = 0
    won_count = 0
    applied_lags: list[float] = []
    for p in projects:
        rec = p.personal
        status = rec.status if rec else default_key
        fav = rec.favorite if rec else False
        applied_at = rec.applied_at if rec else None
        srank = rank.get(status, -1)

        # Chain the reached flags so the funnel is monotonic by construction
        # (seen ≥ favourited ≥ applied ≥ in_discussion ≥ won) regardless of how the configured
        # statuses are ordered — reaching a later stage implies every earlier one.
        reached_won = status == "won"
        reached_discussion = reached_won or (disc_rank is not None and srank >= disc_rank)
        reached_applied = (
            applied_at is not None
            or reached_discussion
            or (applied_rank is not None and srank >= applied_rank)
        )
        reached_favourited = fav or reached_applied

        if reached_favourited:
            fav_count += 1
        if reached_applied:
            applied_count += 1
        if reached_discussion:
            disc_count += 1
        if reached_won:
            won_count += 1
        if applied_at is not None:
            applied_lags.append((applied_at - _seen_time(p)).total_seconds() / 3600)

    applied_lag_median = statistics.median(applied_lags) if applied_lags else None

    def _conv(stage: int, prev: int) -> float | None:
        return (stage / prev) if prev else None

    stages = [
        FunnelStage(key="seen", label="ظهرت", count=seen, conv_from_prev=None, lag_median_hours=None),
        FunnelStage(
            key="favourited",
            label="مفضّلة",
            count=fav_count,
            conv_from_prev=_conv(fav_count, seen),
            lag_median_hours=None,
        ),
        FunnelStage(
            key="applied",
            label="تقدّمت",
            count=applied_count,
            conv_from_prev=_conv(applied_count, fav_count),
            lag_median_hours=applied_lag_median,
        ),
        FunnelStage(
            key="in_discussion",
            label="قيد النقاش",
            count=disc_count,
            conv_from_prev=_conv(disc_count, applied_count),
            lag_median_hours=None,
        ),
        FunnelStage(
            key="won",
            label="ربح",
            count=won_count,
            conv_from_prev=_conv(won_count, disc_count),
            lag_median_hours=None,
        ),
    ]

    return Funnel(
        stages=stages,
        seen=seen,
        enough_data=seen >= settings.get_int("analytics_min_support"),
    )
