"""Unit tests for worker.circuit_breaker.

Covers classify_response, is_clearly_nonempty, and the persisted CircuitBreaker
(soft/hard trips, escalating-and-capped cooldown, pause window, success recovery).

Constitution bars exercised here:
  * Fail-closed: a small/suspicious body or a marker DISQUALIFIES (challenge), never "ok".
  * UTC everywhere: resume_at / cb_resume_at are timezone-aware UTC.
  * At-least-once alerting: a trip transition returns True exactly ONCE so the caller alerts once.

Determinism: ``utcnow`` is patched per-test where a stable clock matters; otherwise we
force ``cb_resume_at`` into the past via app_state_set (the persisted seam) so no sleeps run.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import mostaql_notifier.worker.circuit_breaker as cb_mod
from mostaql_notifier.config.settings_store import app_state_get, app_state_set
from mostaql_notifier.scraper.fetcher import FetchResult
from mostaql_notifier.worker.circuit_breaker import (
    CircuitBreaker,
    Classification,
    classify_response,
    is_clearly_nonempty,
)

FIXED_NOW = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen_now(monkeypatch):
    """Freeze circuit_breaker.utcnow at FIXED_NOW (module-level import is patched in place)."""
    monkeypatch.setattr(cb_mod, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


def _result(status: int, body: str = "", body_bytes: int | None = None, error=None) -> FetchResult:
    if body_bytes is None:
        body_bytes = len(body.encode("utf-8"))
    return FetchResult(url="https://mostaql.com/x", status=status, body=body, body_bytes=body_bytes, error=error)


# --------------------------------------------------------------------------- #
# classify_response                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("status", [403, 429])
def test_classify_blocked_statuses(status, settings):
    assert classify_response(_result(status, "x", 100), settings) is Classification.blocked


@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_classify_5xx_is_transient(status, settings):
    assert classify_response(_result(status, "x", 100), settings) is Classification.transient


def test_classify_status_zero_transport_error_is_transient(settings):
    # line 28: status == 0 (transport error) -> transient (per-request backoff, not a block)
    r = _result(0, "", 0, error="connection reset")
    assert classify_response(r, settings) is Classification.transient


def test_classify_status_600_is_not_5xx(settings):
    # 600 is outside [500,600); not 200 either -> falls through to final return (transient).
    assert classify_response(_result(600, "x", 100), settings) is Classification.transient


def test_classify_499_is_not_5xx_falls_through(settings):
    # 499 < 500, not 200/403/429/0 -> final return transient.
    assert classify_response(_result(499, "x", 100), settings) is Classification.transient


def test_classify_200_challenge_marker_just_a_moment(settings):
    body = "<html><title>Just a Moment...</title></html>"  # mixed case -> markers are lowercased
    r = _result(200, body, body_bytes=200_000)  # big body so only the marker triggers
    assert classify_response(r, settings) is Classification.challenge


@pytest.mark.parametrize(
    "marker",
    ["cf-chl", "__cf_chl", "challenges.cloudflare.com", "checking your browser", "g-recaptcha", "hcaptcha.com"],
)
def test_classify_200_each_challenge_marker(marker, settings):
    body = "<html>" + marker.upper() + " padding</html>"
    r = _result(200, body, body_bytes=200_000)
    assert classify_response(r, settings) is Classification.challenge


def test_classify_200_small_body_is_challenge(settings):
    # line 35: clean body but below block_body_max_bytes -> suspiciously small -> challenge.
    floor = settings.get_int("block_body_max_bytes")
    r = _result(200, "<html>clean tiny page</html>", body_bytes=floor - 1)
    assert classify_response(r, settings) is Classification.challenge


def test_classify_200_body_exactly_at_floor_is_ok(settings):
    # Boundary: body_bytes == floor is NOT < floor -> ok (strict less-than at line 34).
    floor = settings.get_int("block_body_max_bytes")
    r = _result(200, "<html>clean</html>", body_bytes=floor)
    assert classify_response(r, settings) is Classification.ok


def test_classify_200_large_clean_body_is_ok(settings):
    # line 37: big clean body, no markers -> ok.
    r = _result(200, "<html><body>a real listing page</body></html>", body_bytes=200_000)
    assert classify_response(r, settings) is Classification.ok


def test_classify_marker_beats_size_when_both_trigger(settings):
    # A small body that ALSO has a marker: both paths yield challenge; marker checked first.
    r = _result(200, "just a moment", body_bytes=5)
    assert classify_response(r, settings) is Classification.challenge


def test_classify_301_redirect_is_transient(settings):
    # 3xx is not 200/403/429/0/5xx -> final return transient.
    assert classify_response(_result(301, "moved", 100), settings) is Classification.transient


def test_classify_marker_match_is_case_insensitive_both_sides(settings):
    # Body uppercased AND markers lowercased in code -> match regardless of input case.
    r = _result(200, "ATTENTION REQUIRED! Cloudflare", body_bytes=200_000)
    assert classify_response(r, settings) is Classification.challenge


# --------------------------------------------------------------------------- #
# is_clearly_nonempty                                                         #
# --------------------------------------------------------------------------- #

def test_nonempty_below_min_bytes_is_false(settings):
    # line 42-43: body too small to be a full listing -> not "clearly nonempty".
    floor = settings.get_int("nonempty_body_min_bytes")
    body = "project-row مشروع"
    r = _result(200, body, body_bytes=floor - 1)
    assert is_clearly_nonempty(r, settings) is False


def test_nonempty_at_min_bytes_with_shell_marker_is_true(settings):
    floor = settings.get_int("nonempty_body_min_bytes")
    body = "<html>project-row real rows</html>"
    r = _result(200, body, body_bytes=floor)  # exactly floor: not < floor
    assert is_clearly_nonempty(r, settings) is True


def test_nonempty_arabic_shell_marker_is_true(settings):
    # The second shell marker is the Arabic word مشروع (project).
    body = "<html>مشروع listing</html>"
    r = _result(200, body, body_bytes=200_000)
    assert is_clearly_nonempty(r, settings) is True


def test_nonempty_empty_state_marker_arabic_is_false(settings):
    # line 47-48: empty-state marker "لا توجد" -> page legitimately empty, NOT a structure change.
    body = "<html>project-row لا توجد نتائج</html>"  # shell present but empty marker wins
    r = _result(200, body, body_bytes=200_000)
    assert is_clearly_nonempty(r, settings) is False


def test_nonempty_empty_state_marker_english_is_false(settings):
    body = "<html>project-row no results found</html>"
    r = _result(200, body, body_bytes=200_000)
    assert is_clearly_nonempty(r, settings) is False


def test_nonempty_big_body_no_shell_marker_is_false(settings):
    # Big enough, no empty marker, but also no shell marker -> False (can't assert it should have rows).
    body = "<html><body>" + ("padding " * 10000) + "</body></html>"
    r = _result(200, body, body_bytes=200_000)
    assert is_clearly_nonempty(r, settings) is False


def test_nonempty_big_body_with_shell_marker_is_true(settings):
    floor = settings.get_int("nonempty_body_min_bytes")
    body = "<html>" + ("project-row " * 6000) + "</html>"
    assert len(body.encode("utf-8")) >= floor  # comfortably above the size gate
    r = _result(200, body, body_bytes=len(body.encode("utf-8")))
    assert is_clearly_nonempty(r, settings) is True


def test_nonempty_empty_marker_below_min_bytes_still_false(settings):
    # Size gate is checked first; below min bytes -> False before markers even matter.
    floor = settings.get_int("nonempty_body_min_bytes")
    r = _result(200, "project-row", body_bytes=floor - 1)
    assert is_clearly_nonempty(r, settings) is False


# --------------------------------------------------------------------------- #
# CircuitBreaker: properties / initial state                                 #
# --------------------------------------------------------------------------- #

def test_initial_state_is_clean(db_session):
    cb = CircuitBreaker(db_session)
    assert cb.consecutive_failures == 0
    assert cb.trip_count == 0
    assert cb.is_paused() is False
    assert cb.resume_at() is None


def test_resume_at_returns_aware_utc(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    cb.record_failure(hard=True, settings=settings)
    ra = cb.resume_at()
    assert ra is not None
    assert ra.tzinfo is not None  # aware
    # Equal to UTC offset zero (constitution: UTC everywhere).
    assert ra.utcoffset() == timedelta(0)
    base = settings.get_int("cb_cooldown_minutes")
    assert ra == FIXED_NOW + timedelta(minutes=base)


def test_resume_at_parses_naive_stored_value_as_utc(db_session):
    # _parse_iso back-fills tzinfo for legacy naive stored values.
    app_state_set(db_session, "cb_resume_at", "2026-06-23T13:00:00")  # naive
    cb = CircuitBreaker(db_session)
    ra = cb.resume_at()
    assert ra.tzinfo is not None
    assert ra == datetime(2026, 6, 23, 13, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# CircuitBreaker: soft failures                                              #
# --------------------------------------------------------------------------- #

def test_soft_failure_trips_only_on_third(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    assert cb.record_failure(hard=False, settings=settings) is False  # 1
    assert cb.is_paused() is False
    assert cb.record_failure(hard=False, settings=settings) is False  # 2
    assert cb.is_paused() is False
    # 3rd consecutive: trips, returns True ONLY on this transition.
    assert cb.record_failure(hard=False, settings=settings) is True
    assert cb.is_paused() is True
    assert cb.trip_count == 1


def test_soft_failure_within_pause_returns_false(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    cb.record_failure(hard=False, settings=settings)
    cb.record_failure(hard=False, settings=settings)
    assert cb.record_failure(hard=False, settings=settings) is True  # trip transition
    # Already paused -> subsequent failures do NOT re-alert (return False), no new trip.
    assert cb.record_failure(hard=False, settings=settings) is False
    assert cb.record_failure(hard=False, settings=settings) is False
    assert cb.trip_count == 1  # not incremented while paused


def test_consecutive_failures_counter_increments(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    cb.record_failure(hard=False, settings=settings)
    assert cb.consecutive_failures == 1
    cb.record_failure(hard=False, settings=settings)
    assert cb.consecutive_failures == 2


# --------------------------------------------------------------------------- #
# CircuitBreaker: hard failures                                              #
# --------------------------------------------------------------------------- #

def test_hard_failure_trips_immediately(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    # First failure, hard=True -> trips on the spot.
    assert cb.record_failure(hard=True, settings=settings) is True
    assert cb.is_paused() is True
    assert cb.trip_count == 1


def test_hard_failure_within_pause_returns_false(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    assert cb.record_failure(hard=True, settings=settings) is True
    assert cb.record_failure(hard=True, settings=settings) is False  # already paused -> no re-alert
    assert cb.trip_count == 1


# --------------------------------------------------------------------------- #
# CircuitBreaker: escalating + capped cooldown                              #
# --------------------------------------------------------------------------- #

def test_escalating_cooldown_strictly_longer(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    base = settings.get_int("cb_cooldown_minutes")
    factor = settings.get_int("cb_cooldown_factor")

    # Trip 1.
    assert cb.record_failure(hard=True, settings=settings) is True
    first = cb.resume_at()
    assert first == FIXED_NOW + timedelta(minutes=base)

    # Force the pause into the past via the persisted seam (no real sleep).
    app_state_set(db_session, "cb_resume_at", (FIXED_NOW - timedelta(minutes=1)).isoformat())
    assert cb.is_paused() is False

    # Trip 2: strictly longer cooldown.
    assert cb.record_failure(hard=True, settings=settings) is True
    second = cb.resume_at()
    assert second == FIXED_NOW + timedelta(minutes=base * factor)
    assert (second - FIXED_NOW) > (first - FIXED_NOW)
    assert cb.trip_count == 2


def test_cooldown_capped_at_max(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    base = settings.get_int("cb_cooldown_minutes")
    factor = settings.get_int("cb_cooldown_factor")
    cap = settings.get_int("cb_cooldown_max_minutes")

    last_minutes = None
    for _ in range(8):  # enough trips for base*factor**(n-1) to exceed the cap
        if cb.is_paused():
            app_state_set(db_session, "cb_resume_at", (FIXED_NOW - timedelta(minutes=1)).isoformat())
        assert cb.record_failure(hard=True, settings=settings) is True
        trips = cb.trip_count
        expected = min(base * (factor ** (trips - 1)), cap)
        ra = cb.resume_at()
        last_minutes = (ra - FIXED_NOW).total_seconds() / 60
        assert last_minutes == expected
        assert last_minutes <= cap

    assert last_minutes == cap  # eventually pinned at the cap


def test_cooldown_factor_one_stays_at_base(db_session, settings, frozen_now):
    # Config-over-code: with factor 1 the cooldown never escalates.
    from tests.integration._helpers import set_setting

    set_setting(db_session, settings, "cb_cooldown_factor", 1)
    cb = CircuitBreaker(db_session)
    base = settings.get_int("cb_cooldown_minutes")

    cb.record_failure(hard=True, settings=settings)
    assert cb.resume_at() == FIXED_NOW + timedelta(minutes=base)
    app_state_set(db_session, "cb_resume_at", (FIXED_NOW - timedelta(minutes=1)).isoformat())
    cb.record_failure(hard=True, settings=settings)
    assert cb.resume_at() == FIXED_NOW + timedelta(minutes=base)  # unchanged


# --------------------------------------------------------------------------- #
# CircuitBreaker: is_paused window semantics                                 #
# --------------------------------------------------------------------------- #

def test_is_paused_true_while_resume_in_future(db_session, monkeypatch):
    monkeypatch.setattr(cb_mod, "utcnow", lambda: FIXED_NOW)
    app_state_set(db_session, "cb_resume_at", (FIXED_NOW + timedelta(minutes=5)).isoformat())
    assert CircuitBreaker(db_session).is_paused() is True


def test_is_paused_false_when_resume_in_past(db_session, monkeypatch):
    monkeypatch.setattr(cb_mod, "utcnow", lambda: FIXED_NOW)
    app_state_set(db_session, "cb_resume_at", (FIXED_NOW - timedelta(minutes=5)).isoformat())
    assert CircuitBreaker(db_session).is_paused() is False


def test_is_paused_false_at_exact_resume_instant(db_session, monkeypatch):
    # Boundary: now == resume -> not < resume -> not paused (the pause has elapsed).
    monkeypatch.setattr(cb_mod, "utcnow", lambda: FIXED_NOW)
    app_state_set(db_session, "cb_resume_at", FIXED_NOW.isoformat())
    assert CircuitBreaker(db_session).is_paused() is False


def test_is_paused_false_when_unset(db_session):
    assert CircuitBreaker(db_session).is_paused() is False


def test_is_paused_false_when_empty_string(db_session):
    # After a recovery clear cb_resume_at is "" -> falsy -> not paused.
    app_state_set(db_session, "cb_resume_at", "")
    assert CircuitBreaker(db_session).is_paused() is False


# --------------------------------------------------------------------------- #
# CircuitBreaker: record_success recovery                                    #
# --------------------------------------------------------------------------- #

def test_record_success_clean_returns_false(db_session):
    cb = CircuitBreaker(db_session)
    assert cb.record_success() is False  # already clean -> not a recovery transition


def test_record_success_after_soft_failures_returns_true(db_session, settings, frozen_now):
    cb = CircuitBreaker(db_session)
    cb.record_failure(hard=False, settings=settings)  # failing but not yet tripped
    assert cb.consecutive_failures == 1
    assert cb.record_success() is True  # recovery transition (was failing)
    assert cb.consecutive_failures == 0


def test_record_success_after_trip_clears_resume_and_counter(db_session, settings, frozen_now):
    # line 87: clears cb_resume_at on recovery.
    cb = CircuitBreaker(db_session)
    cb.record_failure(hard=True, settings=settings)
    assert cb.is_paused() is True
    assert cb.record_success() is True
    assert cb.consecutive_failures == 0
    assert cb.is_paused() is False
    assert cb.resume_at() is None  # "" -> falsy -> resume_at returns None
    assert app_state_get(db_session, "cb_resume_at") == ""


def test_record_success_does_not_reset_trip_count(db_session, settings, frozen_now):
    # Trip count is the escalation memory; a single recovery must NOT zero it (next trip escalates).
    cb = CircuitBreaker(db_session)
    cb.record_failure(hard=True, settings=settings)
    cb.record_success()
    assert cb.trip_count == 1


def test_recovery_then_clean_second_success_returns_false(db_session, settings, frozen_now):
    """After a recovery, cb_resume_at is "" (not None). A second success on an already-clean
    breaker MUST report False (no transition). Constitution: alert ONLY on transitions."""
    cb = CircuitBreaker(db_session)
    cb.record_failure(hard=True, settings=settings)
    assert cb.record_success() is True  # the real recovery
    # Now fully clean: failures==0, resume_at()==None. A second success is a no-op transition.
    second = cb.record_success()
    assert second is False


def test_record_success_persists_across_new_breaker_instance(db_session, settings, frozen_now):
    # State lives in app_state, so a fresh CircuitBreaker reads the cleared state.
    CircuitBreaker(db_session).record_failure(hard=True, settings=settings)
    CircuitBreaker(db_session).record_success()
    fresh = CircuitBreaker(db_session)
    assert fresh.is_paused() is False
    assert fresh.consecutive_failures == 0


# --------------------------------------------------------------------------- #
# CircuitBreaker: full lifecycle                                             #
# --------------------------------------------------------------------------- #

def test_full_soft_trip_recover_retrip_cycle(db_session, settings, monkeypatch):
    clock = {"t": FIXED_NOW}
    monkeypatch.setattr(cb_mod, "utcnow", lambda: clock["t"])
    cb = CircuitBreaker(db_session)
    base = settings.get_int("cb_cooldown_minutes")
    factor = settings.get_int("cb_cooldown_factor")

    # 3 soft fails -> trip.
    cb.record_failure(hard=False, settings=settings)
    cb.record_failure(hard=False, settings=settings)
    assert cb.record_failure(hard=False, settings=settings) is True
    assert cb.resume_at() == clock["t"] + timedelta(minutes=base)

    # Recover.
    assert cb.record_success() is True
    assert cb.is_paused() is False
    assert cb.consecutive_failures == 0

    # Advance time past any residual; new hard trip escalates (trip_count survived).
    clock["t"] = FIXED_NOW + timedelta(hours=1)
    assert cb.record_failure(hard=True, settings=settings) is True
    assert cb.trip_count == 2
    assert cb.resume_at() == clock["t"] + timedelta(minutes=base * factor)
