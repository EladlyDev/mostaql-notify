"""Edge-branch coverage for worker.politeness not hit by test_politeness.py."""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from mostaql_notifier.db.models import Setting
from mostaql_notifier.worker.politeness import next_delay, parse_retry_after


def _set(session, settings, key, value):
    row = session.get(Setting, key)
    row.value = str(value)
    session.commit()
    settings.reload()


def test_next_delay_swaps_when_min_greater_than_max(db_session, settings):
    # Misconfigured bounds (min > max) must not crash or produce an empty interval: the function
    # swaps them so the draw stays within [max, min] (politeness.next_delay line 111).
    _set(db_session, settings, "delay_min_seconds", 10)
    _set(db_session, settings, "delay_max_seconds", 2)
    rng = random.Random(0)
    for _ in range(200):
        d = next_delay(settings, rng)
        assert 2.0 <= d <= 10.0


def test_next_delay_equal_bounds_is_exact(db_session, settings):
    _set(db_session, settings, "delay_min_seconds", 0)
    _set(db_session, settings, "delay_max_seconds", 0)
    assert next_delay(settings, random.Random(1)) == 0.0


def test_parse_retry_after_naive_http_date_treated_as_utc():
    # An HTTP-date with no timezone token parses to a NAIVE datetime; parse_retry_after must treat
    # it as UTC rather than crash on the aware/naive subtraction (politeness line 168-169).
    now = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    wait = parse_retry_after("Tue, 23 Jun 2026 12:01:00", now)  # +60s, no GMT/tz
    assert wait is not None
    assert wait == pytest.approx(60, abs=1.5)


def test_parse_retry_after_naive_past_http_date_is_zero():
    now = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    wait = parse_retry_after("Tue, 23 Jun 2026 11:59:00", now)  # -60s, no tz -> clamped to 0
    assert wait == 0.0
