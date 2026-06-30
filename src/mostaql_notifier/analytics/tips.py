"""Rule-based, read-only insight tips over the computed analytics overview (Feature 6, §7).

Pure heuristics — **no external service / model / network** (FR-029). Each rule emits at most one
:class:`~mostaql_notifier.api.schemas.Tip` and **only** when its support gate holds; a tip below its
gate is omitted *entirely*, never weakened (FR-025 honesty rule). Rules are ranked in the fixed order
below, then the list is truncated to ``analytics_max_tips``.

The chart rules read only the already-computed ``overview`` sections; the win-based rules issue
**read-only** SELECTs scoped to the analytics window ``[utc_start, utc_end)`` (a project is placed by
its posting time ``posted_at or scraped_at``). Nothing here writes, commits, sets, gates, or sends —
the ``score_threshold`` suggestion in particular is advisory only (FR-027). Every division and every
nullable value is guarded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..api.schemas import AnalyticsOverview, Tip
from ..config.settings_store import SettingsStore
from ..db.models import EvalStatus, PersonalRecord, Project, ProjectScore
from ..db.types import UtcDateTime, utcnow
from ..qualify.budget_policy import load_policy

#: The reserved personal-status slug for a closed-won deal (config key; default label "ربح").
_WON_KEY = "won"


@dataclass
class _WinData:
    """Per-window win/applied aggregates pulled in a single read-only pass."""

    n_wins: int = 0
    won_lags: list[float] = field(default_factory=list)      # applied-lag (h) of won projects
    overall_lags: list[float] = field(default_factory=list)  # applied-lag (h) of all applied projects
    win_scores: list[float] = field(default_factory=list)    # scores of scored won projects
    non_win_scores: list[float] = field(default_factory=list)  # scores of scored non-win projects


def _median_or_none(values: list[float]) -> float | None:
    """Median of ``values`` (a robust central tendency), or ``None`` when empty."""
    return float(median(values)) if values else None


def _collect_win_data(
    session: Session, *, utc_start: datetime, utc_end: datetime
) -> _WinData:
    """Single read-only pass over qualified projects whose posting time is in the window.

    Gathers each project's personal status / applied timestamp, its posting anchor
    (``qualified_at or scraped_at``) and its latest score — enough for the win-timing and
    score-threshold rules without a second query.
    """
    posting_time = sa.func.coalesce(
        Project.posted_at, Project.scraped_at, type_=UtcDateTime()
    )
    rows = (
        session.query(
            PersonalRecord.status,
            PersonalRecord.applied_at,
            Project.qualified_at,
            Project.scraped_at,
            ProjectScore.score,
        )
        .select_from(Project)
        .outerjoin(PersonalRecord, PersonalRecord.project_id == Project.id)
        .outerjoin(ProjectScore, ProjectScore.project_id == Project.id)
        .filter(Project.eval_status == EvalStatus.qualified)
        .filter(posting_time >= utc_start)
        .filter(posting_time < utc_end)
        .all()
    )

    data = _WinData()
    for status, applied_at, qualified_at, scraped_at, score in rows:
        is_won = status == _WON_KEY
        if is_won:
            data.n_wins += 1
        if applied_at is not None:
            anchor = qualified_at if qualified_at is not None else scraped_at
            if anchor is not None:
                lag = (applied_at - anchor).total_seconds() / 3600.0
                data.overall_lags.append(lag)
                if is_won:
                    data.won_lags.append(lag)
        if score is not None:
            if is_won:
                data.win_scores.append(float(score))
            else:
                data.non_win_scores.append(float(score))
    return data


def _tip_peak_window(overview: AnalyticsOverview) -> Tip | None:
    """When the most qualified projects appear (peak heatmap cell)."""
    heatmap = overview.heatmap
    if not heatmap.enough_data or heatmap.peak is None:
        return None
    peak = heatmap.peak
    labels = heatmap.weekday_labels
    day = labels[peak.weekday] if 0 <= peak.weekday < len(labels) else str(peak.weekday)
    text = (
        f"أكثر المشاريع المؤهلة تظهر يوم {day} حوالي الساعة {peak.hour} — كن جاهزًا حينها"
    )
    return Tip(
        key="peak_window",
        text=text,
        evidence={"weekday": peak.weekday, "hour": peak.hour, "count": peak.count},
    )


def _tip_bid_speed(overview: AnalyticsOverview, settings: SettingsStore) -> Tip | None:
    """How fast competition arrives — earliest age band where the median reaches ``early``."""
    competition = overview.competition
    if not competition.enough_data:
        return None
    early = settings.get_int("analytics_early_bids")
    candidates = [p for p in competition.age_curve if p.median >= early]
    if not candidates:
        return None
    band = min(candidates, key=lambda p: p.age_lo_h)
    hours = int(round(band.age_lo_h))
    text = (
        f"تتجاوز نصف المشاريع {early} عروض خلال نحو {hours} ساعة — قدّم خلال {hours} ساعة"
    )
    return Tip(
        key="bid_speed",
        text=text,
        evidence={"early_bids": early, "hours": band.age_lo_h},
    )


def _tip_win_timing(data: _WinData, settings: SettingsStore) -> Tip | None:
    """Whether winning deals came from projects the owner applied to earlier than usual."""
    if data.n_wins < settings.get_int("analytics_min_wins_support"):
        return None
    won_lag = _median_or_none(data.won_lags)
    overall_lag = _median_or_none(data.overall_lags)
    if won_lag is None or overall_lag is None or won_lag >= overall_lag:
        return None
    text = (
        "صفقاتك الرابحة غالبًا من مشاريع تقدّمت لها مبكرًا "
        f"(خلال نحو {int(round(won_lag))} ساعة)"
    )
    return Tip(
        key="win_timing",
        text=text,
        evidence={
            "won_applied_lag": won_lag,
            "overall_applied_lag": overall_lag,
            "n_wins": data.n_wins,
        },
    )


def _tip_score_threshold(data: _WinData, settings: SettingsStore) -> Tip | None:
    """Advisory-only replay: the highest score cut-off that still keeps most past wins (FR-027)."""
    if data.n_wins < settings.get_int("analytics_min_wins_support"):
        return None
    wins = data.win_scores
    if not wins:  # gate also requires the wins to be scored
        return None
    keep = settings.get_float("analytics_suggested_threshold_keep")
    total_wins = len(wins)
    distinct = sorted(set(wins), reverse=True)
    eligible = [t for t in distinct if sum(1 for w in wins if w >= t) / total_wins >= keep]
    if not eligible:  # the minimum win score keeps 100% ⇒ always eligible, but guard regardless
        return None
    threshold = max(eligible)
    kept_wins = sum(1 for w in wins if w >= threshold)
    non_win = data.non_win_scores
    cut_share = (sum(1 for s in non_win if s < threshold) / len(non_win)) if non_win else 0.0
    text = (
        f"حدّ تقييم حوالي {int(round(threshold))} كان سيحتفظ بـ{kept_wins}/{total_wins} "
        "من صفقاتك الرابحة مع استبعاد جزء من الباقي — مجرد اقتراح"
    )
    return Tip(
        key="score_threshold",
        text=text,
        evidence={
            "T": float(threshold),
            "kept_wins": kept_wins,
            "total_wins": total_wins,
            "cut_share": cut_share,
        },
    )


def _tip_budget_fallback(session: Session, settings: SettingsStore) -> Tip | None:
    """Explain the live relaxed budget floor when Tier-1 supply is currently scarce."""
    active_floor = load_policy(session, settings).active_floor
    fallback_floor = Decimal(settings.get_decimal("budget_fallback_floor"))
    if active_floor != fallback_floor:
        return None
    target = settings.get_int("fallback_target")
    since = utcnow() - timedelta(hours=settings.get_int("fallback_window_hours"))
    tier1_recent = (
        session.query(Project)
        .filter(Project.eval_status == EvalStatus.qualified)
        .filter(Project.tier == 1)
        .filter(Project.qualified_at >= since)
        .count()
    )
    if tier1_recent >= target:
        return None
    text = "عرض مشاريع الفئة الأولى منخفض حاليًا، لذا انخفض حدّ الميزانية إلى المستوى الاحتياطي"
    return Tip(
        key="budget_fallback",
        text=text,
        evidence={
            "active_floor": float(active_floor),
            "tier1_recent": tier1_recent,
            "fallback_target": target,
        },
    )


def generate_tips(
    overview: AnalyticsOverview,
    settings: SettingsStore,
    *,
    session: Session,
    utc_start: datetime,
    utc_end: datetime,
) -> list[Tip]:
    """Rank the gated rule outputs and truncate to ``analytics_max_tips`` (contract §7).

    Read-only: the chart rules read ``overview``; the win-based rules issue read-only SELECTs scoped
    to ``[utc_start, utc_end)``. No write/commit, no network/model. Below-gate tips are omitted.
    """
    win_data = _collect_win_data(session, utc_start=utc_start, utc_end=utc_end)

    ranked: list[Tip | None] = [
        _tip_peak_window(overview),
        _tip_bid_speed(overview, settings),
        _tip_win_timing(win_data, settings),
        _tip_score_threshold(win_data, settings),
        _tip_budget_fallback(session, settings),
    ]

    tips = [tip for tip in ranked if tip is not None]
    max_tips = settings.get_int("analytics_max_tips")
    return tips[:max_tips]
