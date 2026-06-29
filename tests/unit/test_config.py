"""Exhaustive unit tests for config.settings_store + config.secrets.

Targets the typed settings accessors, DEFAULTS fallback, seed idempotency, the
serialize/coerce round-trip for every default, app_state get/set, cache/reload
semantics, and the Secrets defaults + require_telegram fail-loud behaviour.

Constitution focus:
  * Config over code (III): every behaviour knob comes from the settings table; reads are typed.
  * Fail-closed: unparseable / unknown signals raise rather than silently admit a guess.
  * Arabic-first numerics are *not* this module's job, but 0 vs None distinctions
    (min_hiring_rate default 0 -> 0.0) are exercised here.
  * Secrets live in .env only; require_telegram must fail loud naming the missing key(s).
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from mostaql_notifier.config.secrets import (
    Secrets,
    get_secrets,
    require_telegram,
)
from mostaql_notifier.config.settings_store import (
    DEFAULTS,
    SettingsStore,
    _coerce,
    _serialize,
    app_state_get,
    app_state_set,
    seed_defaults,
)
from mostaql_notifier.db.base import Base
from mostaql_notifier.db.models import AppState, Setting

# ---------------------------------------------------------------------------
# local fixtures: a *bare* (non-seeded) session distinct from conftest.settings.
# We build our own engine/session so we can exercise the DEFAULTS-fallback path
# (settings table empty) which the seeded `settings` fixture cannot reach.
# ---------------------------------------------------------------------------


@pytest.fixture
def bare_session(tmp_path):
    """A temp-file SQLite session with schema created but NO settings seeded."""
    eng = sa.create_engine(f"sqlite:///{tmp_path}/bare.db", future=True)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    with Session() as s:
        yield s


def _put_setting(session, key: str, value: str, value_type: str) -> None:
    """Insert-or-update a raw settings row (bypassing _serialize) for adversarial inputs."""
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value, value_type=value_type))
    else:
        row.value = value
        row.value_type = value_type
    session.commit()


# ===========================================================================
# DEFAULTS table sanity
# ===========================================================================


def test_defaults_count_is_66():
    # 39 (Features 1–3) + 27 Feature 4 keys (6 weights, 9 tuning, 4 re-check loop, 4 freshness,
    # top_default_count, 2 auto-status toggles, awarded_markers).
    assert len(DEFAULTS) == 66


def test_defaults_every_entry_is_value_type_pair():
    valid_types = {"int", "float", "bool", "json", "str"}
    for key, pair in DEFAULTS.items():
        assert isinstance(pair, tuple) and len(pair) == 2, key
        _value, vtype = pair
        assert vtype in valid_types, (key, vtype)


def test_min_hiring_rate_default_is_zero_not_none():
    # 0% is a REAL distinct value; the default must be 0 (falsy but present), never None.
    value, vtype = DEFAULTS["min_hiring_rate"]
    assert value == 0
    assert value is not None
    assert vtype == "float"


def test_baseline_on_first_run_default_true_bool():
    value, vtype = DEFAULTS["baseline_on_first_run"]
    assert value is True
    assert vtype == "bool"


# ===========================================================================
# _serialize / _coerce round-trip for EVERY default (incl. json list/dict & bool)
# ===========================================================================


@pytest.mark.parametrize("key", sorted(DEFAULTS.keys()))
def test_serialize_coerce_round_trip_every_default(key):
    value, vtype = DEFAULTS[key]
    serialized = _serialize(value, vtype)
    assert isinstance(serialized, str)
    coerced = _coerce(serialized, vtype)
    assert coerced == value
    # json containers must come back as the same *kind* of container.
    if vtype == "json":
        assert type(coerced) is type(value)
    if vtype == "bool":
        assert isinstance(coerced, bool)


def test_serialize_json_preserves_arabic_unicode():
    # ensure_ascii=False keeps Arabic markers human-readable & round-trippable.
    value = ["لا توجد", "مشروع", "no results"]
    s = _serialize(value, "json")
    assert "لا توجد" in s  # not \u-escaped
    assert _coerce(s, "json") == value


def test_serialize_bool_true_false_lowercase_words():
    assert _serialize(True, "bool") == "true"
    assert _serialize(False, "bool") == "false"


def test_serialize_str_uses_str():
    assert _serialize(123, "str") == "123"
    assert _serialize("max", "str") == "max"


def test_serialize_unknown_type_falls_through_to_str():
    # Defensive: an unrecognised value_type serialises via str().
    assert _serialize(42, "weird") == "42"


def test_coerce_int_and_float():
    assert _coerce("250", "int") == 250
    assert isinstance(_coerce("250", "int"), int)
    assert _coerce("2.5", "float") == 2.5
    assert isinstance(_coerce("2.5", "float"), float)


def test_coerce_bool_truthy_and_falsy_tokens():
    for tok in ("1", "true", "TRUE", "  Yes ", "on", "ON"):
        assert _coerce(tok, "bool") is True, tok
    for tok in ("0", "false", "FALSE", "no", "off", "", "maybe", "2"):
        assert _coerce(tok, "bool") is False, tok


def test_coerce_unknown_type_returns_raw_string():
    assert _coerce("anything", "weird") == "anything"


def test_coerce_bad_int_raises_value_error_fail_loud():
    # Fail-closed: an unparseable int is NOT silently swallowed.
    with pytest.raises(ValueError):
        _coerce("not-an-int", "int")


def test_coerce_bad_json_raises_fail_loud():
    import json

    with pytest.raises(json.JSONDecodeError):
        _coerce("{not json}", "json")


# ===========================================================================
# DEFAULTS fallback path (non-seeded session) — covers settings_store 102-103
# ===========================================================================


def test_get_falls_back_to_default_on_empty_table(bare_session):
    store = SettingsStore(bare_session)
    assert store.get_int("poll_interval_seconds") == 120


def test_fallback_returns_raw_default_python_object(bare_session):
    store = SettingsStore(bare_session)
    # min_hiring_rate's raw default is int 0 (NOT coerced to float on the fallback path).
    raw = store.get("min_hiring_rate")
    assert raw == 0
    # but the typed accessor still normalises to float 0.0 (and not None).
    assert store.get_float("min_hiring_rate") == 0.0
    assert isinstance(store.get_float("min_hiring_rate"), float)


def test_fallback_bool_default(bare_session):
    store = SettingsStore(bare_session)
    assert store.get_bool("baseline_on_first_run") is True


def test_fallback_json_default_list(bare_session):
    store = SettingsStore(bare_session)
    markers = store.get_json("listing_shell_markers")
    assert markers == ["project-row", "مشروع"]


def test_fallback_json_default_dict(bare_session):
    store = SettingsStore(bare_session)
    assert store.get_json("currency_usd_rates") == {"USD": 1.0}


def test_fallback_str_default(bare_session):
    store = SettingsStore(bare_session)
    assert store.get_str("owner_timezone") == "Africa/Cairo"
    assert store.get_str("budget_comparison_basis") == "max"


@pytest.mark.parametrize("key", sorted(DEFAULTS.keys()))
def test_every_default_readable_via_fallback(bare_session, key):
    # No KeyError for any seeded-default key even on a totally empty table.
    store = SettingsStore(bare_session)
    assert store.get(key) == DEFAULTS[key][0]


# ===========================================================================
# Unknown key -> KeyError (covers line 104)
# ===========================================================================


def test_unknown_key_raises_key_error_on_empty_table(bare_session):
    store = SettingsStore(bare_session)
    with pytest.raises(KeyError) as ei:
        store.get("totally_unknown_key")
    assert "totally_unknown_key" in str(ei.value)


def test_unknown_key_raises_key_error_on_seeded_store(settings):
    with pytest.raises(KeyError):
        settings.get("nope_not_a_setting")


def test_typed_accessors_propagate_key_error(settings):
    for getter in (
        settings.get_int,
        settings.get_float,
        settings.get_decimal,
        settings.get_bool,
        settings.get_json,
        settings.get_str,
    ):
        with pytest.raises(KeyError):
            getter("definitely_missing")


# ===========================================================================
# Typed accessors against the SEEDED store (correct types & values)
# ===========================================================================


def test_get_int_seeded(settings):
    assert settings.get_int("poll_interval_seconds") == 120
    assert isinstance(settings.get_int("poll_interval_seconds"), int)
    assert settings.get_int("max_fetches_per_cycle") == 12


def test_get_float_seeded(settings):
    assert settings.get_float("delay_min_seconds") == 2.5
    assert isinstance(settings.get_float("delay_min_seconds"), float)
    assert settings.get_float("delay_max_seconds") == 7.0


def test_get_decimal_seeded(settings):
    from decimal import Decimal

    d = settings.get_decimal("budget_primary_floor")
    assert d == Decimal(250)
    assert isinstance(d, Decimal)
    # Decimal goes through str() so a float-typed value is exact, not binary-fuzzy.
    assert settings.get_decimal("delay_min_seconds") == Decimal("2.5")


def test_get_decimal_via_str_avoids_float_artifacts(settings):
    from decimal import Decimal

    # _serialize stored 2.5 as "2.5"; Decimal(str(2.5)) == Decimal("2.5") exactly.
    assert settings.get_decimal("delay_max_seconds") == Decimal("7.0")


def test_get_bool_native_and_strings(settings, db_session):
    # seeded bool round-trips to a native python bool, returned as-is.
    assert settings.get_bool("baseline_on_first_run") is True
    # now overwrite the raw row with each accepted token & confirm parsing.
    truthy = ["1", "true", "yes", "on", "TRUE", " Yes ", "ON"]
    falsy = ["0", "false", "no", "off", "", "garbage", "FALSE"]
    for tok in truthy:
        _put_setting(db_session, "baseline_on_first_run", tok, "bool")
        settings.reload()
        assert settings.get_bool("baseline_on_first_run") is True, tok
    for tok in falsy:
        _put_setting(db_session, "baseline_on_first_run", tok, "bool")
        settings.reload()
        assert settings.get_bool("baseline_on_first_run") is False, tok


def test_get_bool_on_non_bool_value_is_falsey(settings):
    # min_hiring_rate coerces to float 0.0; get_bool stringifies -> "0.0" -> not truthy.
    assert settings.get_bool("min_hiring_rate") is False


def test_get_bool_returns_actual_bool_type(settings):
    v = settings.get_bool("baseline_on_first_run")
    assert isinstance(v, bool)


def test_get_json_returns_parsed_containers(settings):
    challenge = settings.get_json("challenge_markers")
    assert isinstance(challenge, list)
    assert "just a moment" in challenge
    rates = settings.get_json("currency_usd_rates")
    assert isinstance(rates, dict)
    assert rates["USD"] == 1.0


def test_get_str_seeded(settings):
    assert settings.get_str("listing_url") == "https://mostaql.com/projects/development"
    assert settings.get_str("category_slug") == "development"


def test_get_str_coerces_non_string_to_str(settings):
    # poll_interval is an int in cache; get_str stringifies it.
    assert settings.get_str("poll_interval_seconds") == "120"


def test_get_int_coerces_float_value(settings):
    # get_int(float) truncates via int(); confirm a float setting becomes an int.
    assert settings.get_int("delay_min_seconds") == 2


def test_seeded_min_hiring_rate_is_float_zero(settings):
    # Seeded path coerces "0" -> 0.0 (float), distinct from None.
    v = settings.get("min_hiring_rate")
    assert v == 0.0
    assert isinstance(v, float)
    assert v is not None


# ===========================================================================
# seed_defaults: idempotency, count, leaves existing rows untouched
# ===========================================================================


def test_seed_defaults_first_call_inserts_all(bare_session):
    n = seed_defaults(bare_session)
    assert n == len(DEFAULTS)
    # every default key now present in the table.
    keys = {k for (k,) in bare_session.query(Setting.key).all()}
    assert keys == set(DEFAULTS.keys())


def test_seed_defaults_second_call_is_idempotent(bare_session):
    assert seed_defaults(bare_session) == len(DEFAULTS)
    assert seed_defaults(bare_session) == 0
    # row count unchanged.
    assert bare_session.query(Setting).count() == len(DEFAULTS)


def test_seed_defaults_leaves_existing_rows_untouched(bare_session):
    # Pre-seed a custom value for a key that is also a default.
    _put_setting(bare_session, "poll_interval_seconds", "999", "int")
    inserted = seed_defaults(bare_session)
    assert inserted == len(DEFAULTS) - 1  # all but the pre-existing one
    assert bare_session.get(Setting, "poll_interval_seconds").value == "999"


def test_seed_then_store_reads_seeded_value_not_default(bare_session):
    _put_setting(bare_session, "poll_interval_seconds", "999", "int")
    seed_defaults(bare_session)
    store = SettingsStore(bare_session)
    assert store.get_int("poll_interval_seconds") == 999


def test_every_seeded_default_round_trips_to_right_python_type(bare_session):
    seed_defaults(bare_session)
    store = SettingsStore(bare_session)
    store.reload()
    for key, (value, vtype) in DEFAULTS.items():
        got = store.get(key)
        assert got == value, key
        if vtype == "int":
            assert isinstance(got, int) and not isinstance(got, bool), key
        elif vtype == "float":
            assert isinstance(got, float), key
        elif vtype == "bool":
            assert isinstance(got, bool), key
        elif vtype == "json":
            assert isinstance(got, (list, dict)), key
        elif vtype == "str":
            assert isinstance(got, str), key


# ===========================================================================
# Cache / reload semantics
# ===========================================================================


def test_reload_picks_up_external_row_edit(settings, db_session):
    assert settings.get_int("poll_interval_seconds") == 120  # primes the cache
    _put_setting(db_session, "poll_interval_seconds", "300", "int")
    # without reload the cache is still stale (documents the per-cycle cache contract)...
    assert settings.get_int("poll_interval_seconds") == 120
    # ...reload picks up the external edit.
    settings.reload()
    assert settings.get_int("poll_interval_seconds") == 300


def test_reload_picks_up_externally_inserted_new_key(settings, db_session):
    settings.reload()
    _put_setting(db_session, "category_slug", "design", "str")
    settings.reload()
    assert settings.get_str("category_slug") == "design"


def test_lazy_reload_on_first_get(bare_session):
    # A brand-new store has an empty cache; get() triggers reload() lazily.
    seed_defaults(bare_session)
    store = SettingsStore(bare_session)
    assert store._cache == {}
    assert store.get_int("poll_interval_seconds") == 120
    assert store._cache  # now populated


def test_reload_replaces_cache_wholesale(settings, db_session):
    settings.get_int("poll_interval_seconds")
    # Delete a row then reload; the cache must no longer carry the old key value
    # from before (it falls back to DEFAULTS instead of a stale cached row).
    row = db_session.get(Setting, "poll_interval_seconds")
    db_session.delete(row)
    db_session.commit()
    settings.reload()
    # row gone -> served from DEFAULTS now.
    assert settings.get_int("poll_interval_seconds") == 120


def test_get_json_returns_live_cache_reference(settings):
    # Documents that get_json hands back the cached object (no defensive copy).
    a = settings.get_json("challenge_markers")
    b = settings.get_json("challenge_markers")
    assert a is b


# ===========================================================================
# app_state get/set
# ===========================================================================


def test_app_state_get_missing_returns_default(db_session):
    assert app_state_get(db_session, "last_cursor", "FALLBACK") == "FALLBACK"


def test_app_state_get_missing_returns_none_default(db_session):
    assert app_state_get(db_session, "last_cursor") is None


def test_app_state_set_inserts_then_get(db_session):
    app_state_set(db_session, "last_cursor", "abc")
    assert app_state_get(db_session, "last_cursor") == "abc"
    # confirm exactly one row exists.
    assert db_session.query(AppState).filter_by(key="last_cursor").count() == 1


def test_app_state_set_updates_existing(db_session):
    app_state_set(db_session, "last_cursor", "first")
    app_state_set(db_session, "last_cursor", "second")
    assert app_state_get(db_session, "last_cursor") == "second"
    # still a single row (update, not duplicate insert).
    assert db_session.query(AppState).filter_by(key="last_cursor").count() == 1


def test_app_state_set_persists_across_new_session(engine):
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    with Session() as s1:
        app_state_set(s1, "heartbeat_at", "2026-06-23T00:00:00Z")
    with Session() as s2:
        assert app_state_get(s2, "heartbeat_at") == "2026-06-23T00:00:00Z"


def test_app_state_independent_keys(db_session):
    app_state_set(db_session, "k1", "v1")
    app_state_set(db_session, "k2", "v2")
    assert app_state_get(db_session, "k1") == "v1"
    assert app_state_get(db_session, "k2") == "v2"


# ===========================================================================
# Secrets: defaults, explicit construction, require_telegram fail-loud
# ===========================================================================


def test_secrets_defaults_empty_token_and_chat():
    # Construct ignoring any .env so defaults are deterministic.
    s = Secrets(_env_file=None)
    assert s.telegram_bot_token == ""
    assert s.telegram_chat_id == ""


def test_secrets_database_url_sqlite_default():
    s = Secrets(_env_file=None)
    assert s.database_url == "sqlite:///./data/mostaql.db"


def test_secrets_explicit_construction_bypasses_env():
    s = Secrets(telegram_bot_token="x", telegram_chat_id="y", _env_file=None)
    assert s.telegram_bot_token == "x"
    assert s.telegram_chat_id == "y"
    # database_url still defaults when not provided.
    assert s.database_url == "sqlite:///./data/mostaql.db"


def test_get_secrets_is_lru_cached():
    assert get_secrets() is get_secrets()


def test_require_telegram_raises_naming_both_when_empty():
    s = Secrets(telegram_bot_token="", telegram_chat_id="", _env_file=None)
    with pytest.raises(RuntimeError) as ei:
        require_telegram(s)
    msg = str(ei.value)
    assert "telegram_bot_token" in msg
    assert "telegram_chat_id" in msg
    assert ".env" in msg  # points the operator at the right file


def test_require_telegram_names_only_missing_chat():
    s = Secrets(telegram_bot_token="x", telegram_chat_id="", _env_file=None)
    with pytest.raises(RuntimeError) as ei:
        require_telegram(s)
    msg = str(ei.value)
    assert "telegram_chat_id" in msg
    assert "telegram_bot_token" not in msg


def test_require_telegram_names_only_missing_token():
    s = Secrets(telegram_bot_token="", telegram_chat_id="y", _env_file=None)
    with pytest.raises(RuntimeError) as ei:
        require_telegram(s)
    msg = str(ei.value)
    assert "telegram_bot_token" in msg
    assert "telegram_chat_id" not in msg


def test_require_telegram_passes_when_both_set():
    s = Secrets(telegram_bot_token="x", telegram_chat_id="y", _env_file=None)
    assert require_telegram(s) is None  # no raise, returns None


def test_require_telegram_whitespace_only_token_is_considered_present():
    # Documents current behaviour: require_telegram checks falsiness, so a
    # whitespace-only token (truthy non-empty string) is treated as present.
    s = Secrets(telegram_bot_token="   ", telegram_chat_id="y", _env_file=None)
    assert require_telegram(s) is None
