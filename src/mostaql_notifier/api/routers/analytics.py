"""Analytics API — the single read-only overview endpoint (Feature 6).

``GET /api/analytics/overview`` returns every analytics section + the rule-based tips for an
analytics-tz calendar date range, computed at read time from existing rows. It triggers no scrape,
sends no notification, and writes NOTHING to any project / score / snapshot / outcome / personal
row (constitution IV/VIII). Auth is applied at include time in ``api/app.py``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...analytics.service import compute_overview
from ...config.settings_store import SettingsStore
from ..deps import get_db
from ..schemas import AnalyticsOverview

router = APIRouter(tags=["analytics"])


@router.get("/api/analytics/overview", response_model=AnalyticsOverview)
def analytics_overview(
    db: Annotated[Session, Depends(get_db)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> AnalyticsOverview:
    """Read-only analytics overview (all sections + tips) for a date range.

    ``date_from``/``date_to`` are calendar dates (YYYY-MM-DD) in the configured analytics timezone;
    either may be omitted (→ the configured default window). An inverted range is a 422.
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    settings = SettingsStore(db)
    return compute_overview(
        db, settings, date_from=date_from, date_to=date_to, now=datetime.now(timezone.utc)
    )
