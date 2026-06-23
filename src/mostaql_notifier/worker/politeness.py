"""Politeness primitives: header rotation, inter-request delay, and retry backoff.

All durations are read from :class:`SettingsStore` at call time (constitution III —
config over code); nothing here hard-codes a timing knob. The duration math is split into
pure functions (``next_delay``, ``backoff_seconds``, ``parse_retry_after``) so it is testable
without sleeping or patching the clock.
"""
from __future__ import annotations

import email.utils
import random as _random_module
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.settings_store import SettingsStore

# Complete, self-consistent desktop header sets. Each dict pairs a User-Agent with a matching
# sec-ch-ua trio (Chromium sets only) and an Arabic-first Accept-Language (constitution —
# Arabic-first). polite rotation between these reduces fingerprint uniqueness.
HEADER_SETS: list[dict[str, str]] = [
    {
        # Chrome 124 on Windows 10/11
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        # Chrome 123 on macOS
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        # Firefox 125 on Windows (no sec-ch-ua: Firefox does not send Client Hints)
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        # Firefox 124 on Linux
        "User-Agent": (
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    },
]


def choose_header_set(seed: int) -> dict[str, str]:
    """Deterministically pick one header set for a given ``seed`` (stable within a run).

    Returns a fresh copy so callers may mutate it without affecting the canonical list.
    """
    chosen = HEADER_SETS[seed % len(HEADER_SETS)]
    return dict(chosen)


def next_delay(settings: SettingsStore, rng: _random_module.Random = _random_module) -> float:
    """Pure: the next inter-request delay in seconds, uniform in [min, max]. No sleeping."""
    lo = settings.get_float("delay_min_seconds")
    hi = settings.get_float("delay_max_seconds")
    if hi < lo:
        lo, hi = hi, lo
    return rng.uniform(lo, hi)


async def polite_delay(
    settings: SettingsStore, rng: _random_module.Random = _random_module
) -> float:
    """Sleep for :func:`next_delay` seconds, then return the slept duration."""
    import asyncio

    seconds = next_delay(settings, rng)
    await asyncio.sleep(seconds)
    return seconds


def backoff_seconds(
    attempt: int, settings: SettingsStore, rng: _random_module.Random = _random_module
) -> float:
    """Full-jitter exponential backoff: uniform(0, min(cap, base * 2**attempt)).

    ``attempt`` is 0-based. Result is always within ``[0, retry_cap_seconds]``.
    """
    base = settings.get_float("retry_base_seconds")
    cap = settings.get_float("retry_cap_seconds")
    exp = base * (2 ** max(attempt, 0))
    ceiling = min(cap, exp)
    if ceiling < 0:
        ceiling = 0.0
    return rng.uniform(0, ceiling)


def parse_retry_after(value: str | None, now_utc: datetime) -> float | None:
    """Interpret a ``Retry-After`` header value as seconds-to-wait.

    Handles both integer-seconds form ("120") and HTTP-date form. A date in the past (or any
    unparseable value) yields ``None``; fail-closed callers should treat ``None`` as "no hint".
    Returns ``0.0`` only when an integer ``0`` is given.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    # Integer seconds form.
    try:
        seconds = int(text)
    except ValueError:
        pass
    else:
        return float(max(seconds, 0))
    # HTTP-date form.
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (ValueError, TypeError):
        return None
    if parsed is None:  # pragma: no cover - py3.10+ parsedate_to_datetime raises instead of None
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = (parsed - now_utc).total_seconds()
    if delta <= 0:
        return 0.0
    return delta
