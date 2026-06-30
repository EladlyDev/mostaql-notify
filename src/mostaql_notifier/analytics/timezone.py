"""Analytics timezone + windowing helpers (Feature 6, read-only).

The single source of the analytics timezone and the UTC↔local-calendar conversions every aggregate
uses. Mirrors the existing ``today_start_utc`` fallback (``personal/stats.py``): an empty
``analytics_timezone`` follows ``owner_timezone``; an unparseable value falls back to Africa/Cairo.
Weekdays use the Arabic week order (**0=Saturday … 6=Friday**). Windows are half-open
``[utc_start, utc_end)`` so a project on the boundary day is counted exactly once. DST is handled
correctly because ``astimezone`` applies the offset valid at the given instant (contract §0).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config.settings_store import SettingsStore

#: Last-resort timezone if both ``analytics_timezone`` and ``owner_timezone`` are unparseable.
_DEFAULT_TZ = "Africa/Cairo"

#: Arabic weekday labels, index-aligned to ``local_parts`` weekday 0..6 (Saturday → Friday).
WEEKDAY_LABELS: list[str] = [
    "السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة",
]


def analytics_tz(session: Session) -> ZoneInfo:
    """The configured analytics timezone.

    ``analytics_timezone`` empty ⇒ follow ``owner_timezone``; an unparseable value ⇒ Africa/Cairo
    (mirrors ``personal.stats.today_start_utc``). Single source of the analytics tz.
    """
    store = SettingsStore(session)
    tz_name = store.get_str("analytics_timezone").strip()
    if not tz_name:
        tz_name = store.get_str("owner_timezone").strip()
    try:
        return ZoneInfo(tz_name)
    except Exception:  # invalid/unknown tz string — fall back to the default
        return ZoneInfo(_DEFAULT_TZ)


def local_parts(dt_utc: datetime, tz: ZoneInfo) -> tuple[int, int, date]:
    """``(weekday 0=Sat..6=Fri, hour 0..23, local_date)`` for a UTC instant viewed in ``tz``.

    DST-correct: ``astimezone`` applies the offset valid at ``dt_utc`` (so a spring-forward instant
    buckets to the correct local hour).
    """
    local = dt_utc.astimezone(tz)
    weekday = (local.weekday() + 2) % 7  # Python Mon=0..Sun=6 → Arabic Sat=0..Fri=6
    return weekday, local.hour, local.date()


def day_key(dt_utc: datetime, tz: ZoneInfo) -> str:
    """``"YYYY-MM-DD"`` of the local calendar date for a UTC instant."""
    return dt_utc.astimezone(tz).strftime("%Y-%m-%d")


def iso_week_key(dt_utc: datetime, tz: ZoneInfo) -> str:
    """``"YYYY-Www"`` (ISO year + week) of the local calendar date for a UTC instant."""
    iso = dt_utc.astimezone(tz).isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def resolve_range(
    date_from: date | None,
    date_to: date | None,
    tz: ZoneInfo,
    *,
    default_range_days: int,
    now: datetime | None = None,
) -> tuple[date, date, bool]:
    """Resolve the requested calendar range, filling defaults.

    ``date_to`` omitted ⇒ today in ``tz``; ``date_from`` omitted ⇒ ``date_to − default_range_days``.
    Returns ``(date_from, date_to, default_applied)`` where ``default_applied`` is true when *no*
    range was supplied at all (both omitted) — surfaced so the UI can label the default window.
    ``now`` (aware) is injectable for deterministic tests; defaults to the wall clock.
    """
    default_applied = date_from is None and date_to is None
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=default_range_days)
    return date_from, date_to, default_applied


def window_bounds(date_from: date, date_to: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Resolve an analytics-tz calendar range to a half-open UTC window.

    ``utc_start = local_midnight(date_from)``; ``utc_end = local_midnight(date_to + 1 day)`` — the
    half-open ``[utc_start, utc_end)`` interval counts the boundary day once. Construct the next-day
    midnight from a ``date`` (not by adding a ``timedelta`` to an aware datetime) so DST transitions
    that fall at midnight resolve cleanly.
    """
    end_date = date_to + timedelta(days=1)
    start_local = datetime(date_from.year, date_from.month, date_from.day, tzinfo=tz)
    end_local = datetime(end_date.year, end_date.month, end_date.day, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
