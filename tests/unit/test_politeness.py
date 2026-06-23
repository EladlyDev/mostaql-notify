"""Unit tests for worker.politeness: delays, backoff, Retry-After parsing, header rotation."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from mostaql_notifier.worker.politeness import (
    HEADER_SETS,
    backoff_seconds,
    choose_header_set,
    next_delay,
    parse_retry_after,
)


def test_next_delay_within_bounds(settings):
    lo = settings.get_float("delay_min_seconds")
    hi = settings.get_float("delay_max_seconds")
    rng = random.Random(0)
    for _ in range(200):
        d = next_delay(settings, rng)
        assert lo <= d <= hi


def test_backoff_within_cap(settings):
    cap = settings.get_float("retry_cap_seconds")
    rng = random.Random(1)
    for attempt in range(0, 12):
        for _ in range(50):
            b = backoff_seconds(attempt, settings, rng)
            assert 0.0 <= b <= cap


def test_backoff_ceiling_grows_with_attempt(settings):
    """The full-jitter ceiling (base * 2**attempt, capped) is non-decreasing in attempt."""
    base = settings.get_float("retry_base_seconds")
    cap = settings.get_float("retry_cap_seconds")
    prev = -1.0
    for attempt in range(0, 12):
        ceiling = min(cap, base * (2 ** attempt))
        assert ceiling >= prev
        prev = ceiling
    # And the early ceilings are strictly increasing until they hit the cap.
    assert min(cap, base * 2 ** 0) < min(cap, base * 2 ** 4)


def test_backoff_max_observed_increases(settings):
    """Sampling many draws, the achievable upper end should rise across early attempts."""
    rng = random.Random(7)
    max0 = max(backoff_seconds(0, settings, rng) for _ in range(500))
    max3 = max(backoff_seconds(3, settings, rng) for _ in range(500))
    assert max3 > max0


def test_parse_retry_after_integer():
    now = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after("5", now) == 5.0
    assert parse_retry_after("0", now) == 0.0
    assert parse_retry_after("  120 ", now) == 120.0


def test_parse_retry_after_future_http_date():
    now = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    future = now + timedelta(seconds=90)
    header = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    wait = parse_retry_after(header, now)
    assert wait is not None
    assert wait > 0
    assert wait == pytest.approx(90, abs=1.5)


def test_parse_retry_after_past_http_date_is_zero():
    now = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    past = now - timedelta(seconds=120)
    header = past.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(header, now) == 0.0


def test_parse_retry_after_none_and_garbage():
    now = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after(None, now) is None
    assert parse_retry_after("", now) is None
    assert parse_retry_after("not-a-date", now) is None


def test_choose_header_set_deterministic():
    a = choose_header_set(3)
    b = choose_header_set(3)
    assert a == b
    # Equal modulo the list length too.
    assert choose_header_set(3) == choose_header_set(3 + len(HEADER_SETS))


def test_choose_header_set_shape():
    hs = choose_header_set(0)
    assert isinstance(hs, dict)
    assert "User-Agent" in hs
    assert "Accept-Language" in hs
    assert hs["Accept-Language"].startswith("ar")


def test_choose_header_set_returns_copy():
    hs = choose_header_set(1)
    hs["User-Agent"] = "tampered"
    assert HEADER_SETS[1 % len(HEADER_SETS)]["User-Agent"] != "tampered"


@pytest.mark.asyncio
async def test_polite_delay_sleeps_and_returns(settings, monkeypatch):
    import mostaql_notifier.worker.politeness as politeness

    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    rng = random.Random(0)
    returned = await politeness.polite_delay(settings, rng)
    lo = settings.get_float("delay_min_seconds")
    hi = settings.get_float("delay_max_seconds")
    assert lo <= returned <= hi
    assert slept == [returned]
