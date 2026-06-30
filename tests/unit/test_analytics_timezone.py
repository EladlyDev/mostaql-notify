"""Unit tests for the analytics timezone + windowing helpers (Feature 6).

Covers the single source of the analytics tz (``analytics_tz``: empty ⇒ owner, valid wins, invalid
⇒ Africa/Cairo), the Arabic-week UTC↔local conversion (``local_parts``/``day_key``/``iso_week_key``
incl. day-boundary + DST correctness), the half-open UTC ``window_bounds``, and default filling in
``resolve_range``.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mostaql_notifier.analytics.timezone import (
    WEEKDAY_LABELS,
    analytics_tz,
    day_key,
    iso_week_key,
    local_parts,
    resolve_range,
    window_bounds,
)
from mostaql_notifier.db.models import Setting

UTC = timezone.utc
CAIRO = ZoneInfo("Africa/Cairo")


def _set(db_session, key: str, value: str) -> None:
    """Override a seeded ``settings`` row, then commit so a fresh ``SettingsStore`` reads it."""
    row = db_session.get(Setting, key)
    row.value = value
    db_session.commit()


# --- analytics_tz -----------------------------------------------------------------------------

def test_analytics_tz_empty_follows_owner(db_session, settings):
    # Default analytics_timezone is "" -> follow owner_timezone.
    _set(db_session, "owner_timezone", "Asia/Riyadh")
    assert analytics_tz(db_session).key == "Asia/Riyadh"


def test_analytics_tz_valid_wins_over_owner(db_session, settings):
    _set(db_session, "owner_timezone", "Asia/Riyadh")
    _set(db_session, "analytics_timezone", "America/New_York")
    assert analytics_tz(db_session).key == "America/New_York"


def test_analytics_tz_invalid_falls_back_to_cairo(db_session, settings):
    _set(db_session, "analytics_timezone", "Not/AZone")
    assert analytics_tz(db_session) == ZoneInfo("Africa/Cairo")


# --- local_parts ------------------------------------------------------------------------------

def test_local_parts_saturday_is_weekday_zero(db_session, settings):
    # 2026-01-03 is a Saturday; midday UTC keeps it unambiguously on that local day.
    saturday = datetime(2026, 1, 3, 12, 0, tzinfo=UTC)
    weekday, _hour, local_date = local_parts(saturday, CAIRO)
    assert weekday == 0
    assert local_date == date(2026, 1, 3)


def test_local_parts_friday_is_weekday_six(db_session, settings):
    # 2026-01-02 is a Friday -> the last day of the Arabic week (index 6).
    friday = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    weekday, _hour, local_date = local_parts(friday, CAIRO)
    assert weekday == 6
    assert local_date == date(2026, 1, 2)


def test_local_parts_keeps_local_day_near_boundary(db_session, settings):
    # An instant that is 23:30 local must stay on its own local day (not roll to the next).
    dt_utc = datetime(2026, 1, 3, 23, 30, tzinfo=CAIRO).astimezone(UTC)
    weekday, hour, local_date = local_parts(dt_utc, CAIRO)
    assert hour == 23
    assert local_date == date(2026, 1, 3)
    assert weekday == 0  # still Saturday


def test_local_parts_dst_correct_across_spring_forward(db_session, settings):
    # US spring-forward 2026 = 2026-03-08 02:00 local. Either side, the local hour must equal what
    # astimezone yields (the offset valid at that instant).
    ny = ZoneInfo("America/New_York")
    before = datetime(2026, 3, 8, 6, 0, tzinfo=UTC)  # 01:00 EST (UTC-5)
    after = datetime(2026, 3, 8, 8, 0, tzinfo=UTC)   # 04:00 EDT (UTC-4)
    for instant in (before, after):
        _weekday, hour, _local_date = local_parts(instant, ny)
        assert hour == instant.astimezone(ny).hour
    assert local_parts(before, ny)[1] == 1
    assert local_parts(after, ny)[1] == 4  # +3h local for +2h UTC -> DST jump applied


# --- window_bounds ----------------------------------------------------------------------------

def test_window_bounds_single_day_is_half_open(db_session, settings):
    start, end = window_bounds(date(2026, 6, 1), date(2026, 6, 1), CAIRO)
    assert end - start == timedelta(days=1)
    assert start == datetime(2026, 6, 1, tzinfo=CAIRO).astimezone(UTC)
    assert end == datetime(2026, 6, 2, tzinfo=CAIRO).astimezone(UTC)
    # Both bounds are tz-aware UTC.
    assert start.utcoffset() == timedelta(0)
    assert end.utcoffset() == timedelta(0)


def test_window_bounds_multi_day_span(db_session, settings):
    start, end = window_bounds(date(2026, 6, 1), date(2026, 6, 3), CAIRO)
    assert end - start == timedelta(days=3)
    assert start == datetime(2026, 6, 1, tzinfo=CAIRO).astimezone(UTC)
    assert end == datetime(2026, 6, 4, tzinfo=CAIRO).astimezone(UTC)


# --- resolve_range ----------------------------------------------------------------------------

def test_resolve_range_both_omitted_applies_default(db_session, settings):
    now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    date_from, date_to, default_applied = resolve_range(
        None, None, CAIRO, default_range_days=90, now=now
    )
    assert default_applied is True
    assert date_to == now.astimezone(CAIRO).date()
    assert date_from == date_to - timedelta(days=90)


def test_resolve_range_only_date_from_defaulted(db_session, settings):
    now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    given_to = date(2026, 6, 10)
    date_from, date_to, default_applied = resolve_range(
        None, given_to, CAIRO, default_range_days=30, now=now
    )
    assert default_applied is False
    assert date_to == given_to
    assert date_from == given_to - timedelta(days=30)


# --- key formatting + labels ------------------------------------------------------------------

def test_day_and_week_keys_format(db_session, settings):
    instant = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert day_key(instant, CAIRO) == "2026-06-01"
    week = iso_week_key(instant, CAIRO)
    assert re.fullmatch(r"\d{4}-W\d{2}", week)
    assert week == "2026-W23"


def test_weekday_labels(db_session, settings):
    assert WEEKDAY_LABELS[0] == "السبت"
    assert len(WEEKDAY_LABELS) == 7
