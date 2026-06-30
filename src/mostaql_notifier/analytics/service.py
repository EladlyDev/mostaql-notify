"""Assemble the read-only analytics overview (Feature 6, research R6).

The single surface-agnostic entry point the API router calls: resolve the requested analytics-tz
calendar range to a half-open UTC window, run every aggregate over that window, derive the
rule-based tips, and assemble the :class:`AnalyticsOverview`. Strictly read-only — it issues only
SELECTs and writes nothing back (constitution IV).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from ..api.schemas import AnalyticsOverview, AnalyticsRange
from ..config.settings_store import SettingsStore
from . import aggregates, tips
from .timezone import analytics_tz, resolve_range, window_bounds


def compute_overview(
    session: Session,
    settings: SettingsStore,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    now: datetime | None = None,
) -> AnalyticsOverview:
    """Compute the full analytics overview for a calendar date range.

    ``date_from``/``date_to`` are analytics-tz calendar dates (either may be omitted → the
    configured default window). ``now`` (aware) is injectable for deterministic tests. Every section
    carries its own ``enough_data`` flag and tips below their support are omitted, so the result is
    honest under thin data.
    """
    tz = analytics_tz(session)
    default_days = settings.get_int("analytics_default_range_days")
    resolved_from, resolved_to, default_applied = resolve_range(
        date_from, date_to, tz, default_range_days=default_days, now=now
    )
    utc_start, utc_end = window_bounds(resolved_from, resolved_to, tz)

    window = {"utc_start": utc_start, "utc_end": utc_end}
    overview = AnalyticsOverview(
        range=AnalyticsRange(
            date_from=resolved_from,
            date_to=resolved_to,
            timezone=str(tz),
            default_applied=default_applied,
        ),
        heatmap=aggregates.posting_heatmap(session, settings, **window),
        volume=aggregates.volume_trends(session, settings, **window),
        budget=aggregates.budget_distribution(session, settings, **window),
        competition=aggregates.competition_dynamics(session, settings, **window),
        outcomes=aggregates.outcome_analytics(session, settings, **window),
        funnel=aggregates.funnel(session, settings, **window),
        tips=[],
    )
    # Tips read the already-computed sections (+ windowed win queries); scoped to the same range so
    # the date filter consistently scopes every chart *and* tip (SC-011).
    overview.tips = tips.generate_tips(
        overview, settings, session=session, utc_start=utc_start, utc_end=utc_end
    )
    return overview


__all__ = ["compute_overview"]
