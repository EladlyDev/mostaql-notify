"""Exhaustive db-layer audit: types.py, models.derive_client_key, upsert.py, session.py.

Covers the constitution bars relevant to persistence:
  * UTC everywhere / tz-aware only — naive writes are fail-loud (ValueError), non-datetime
    writes are fail-loud (TypeError), and reads always re-attach UTC.
  * Config over code — the Setting table upserts idempotently (no dupes, value updated).
  * Portable engine bootstrap — nested sqlite dir is created and FK enforcement is on.

Run ONLY this file:
  .venv/bin/python -m pytest tests/unit/test_db_layer.py -q -p no:cacheprovider
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from mostaql_notifier.db.models import (
    Client,
    Project,
    Setting,
    derive_client_key,
)
from mostaql_notifier.db.types import JSONType, UtcDateTime, make_enum, utcnow
from mostaql_notifier.db.upsert import exists_by, pk_columns, upsert

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

UTC = timezone.utc
PLUS3 = timezone(timedelta(hours=3))
MINUS5 = timezone(timedelta(hours=-5))


def _client(**over):
    base = dict(
        mostaql_id="derived:abc",
        name="عميل",
        last_refreshed_at=utcnow(),
        first_seen_at=utcnow(),
        raw={},
    )
    base.update(over)
    return Client(**base)


def _project(**over):
    base = dict(
        mostaql_id="p1",
        scraped_at=utcnow(),
        raw={},
    )
    base.update(over)
    return Project(**base)


# ======================================================================================
# types.py :: UtcDateTime.process_bind_param  (lines 30, 32)
# ======================================================================================

def test_bind_none_passthrough():
    assert UtcDateTime().process_bind_param(None, None) is None


def test_bind_naive_datetime_raises_valueerror():
    """Constitution: tz-aware only. A naive datetime on write must fail loud (line 32)."""
    with pytest.raises(ValueError):
        UtcDateTime().process_bind_param(datetime(2020, 1, 1, 12, 0, 0), None)


@pytest.mark.parametrize(
    "bad",
    [
        "2020-01-01T00:00:00Z",          # str
        1577836800,                       # int epoch
        1577836800.0,                     # float epoch
        datetime(2020, 1, 1).date(),      # date (not datetime)
        object(),                         # arbitrary object
        [datetime(2020, 1, 1, tzinfo=UTC)],
    ],
)
def test_bind_non_datetime_raises_typeerror(bad):
    """Non-datetime input on write must raise TypeError (line 30), not be coerced."""
    with pytest.raises(TypeError):
        UtcDateTime().process_bind_param(bad, None)


def test_bind_date_is_not_datetime_subclass_check():
    # Guard against datetime.date sneaking through isinstance(datetime). date is NOT a datetime.
    import datetime as _dt

    assert not isinstance(_dt.date(2020, 1, 1), datetime)


def test_bind_aware_utc_normalised_to_utc():
    aware = datetime(2020, 6, 1, 9, 30, tzinfo=UTC)
    out = UtcDateTime().process_bind_param(aware, None)
    assert out.tzinfo == UTC
    assert out == aware


def test_bind_aware_plus3_converted_to_utc():
    aware = datetime(2020, 1, 1, 3, 0, 0, tzinfo=PLUS3)
    out = UtcDateTime().process_bind_param(aware, None)
    assert out.tzinfo == UTC
    assert out == datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_bind_aware_minus5_converted_to_utc():
    aware = datetime(2020, 1, 1, 0, 0, 0, tzinfo=MINUS5)
    out = UtcDateTime().process_bind_param(aware, None)
    assert out.tzinfo == UTC
    assert out == datetime(2020, 1, 1, 5, 0, 0, tzinfo=UTC)


# ======================================================================================
# types.py :: UtcDateTime.process_result_value  (lines 38-40)
# ======================================================================================

def test_result_none_passthrough():
    assert UtcDateTime().process_result_value(None, None) is None


def test_result_naive_gets_utc_attached():
    """Naive value from the DB (line 40 branch) is interpreted AS UTC, not converted."""
    naive = datetime(2020, 1, 1, 12, 0, 0)
    out = UtcDateTime().process_result_value(naive, None)
    assert out.tzinfo == UTC
    assert out == datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_result_aware_utc_passthrough():
    aware = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    out = UtcDateTime().process_result_value(aware, None)
    assert out.tzinfo == UTC
    assert out == aware


def test_result_aware_plus3_converted_to_utc():
    aware = datetime(2020, 1, 1, 3, 0, 0, tzinfo=PLUS3)
    out = UtcDateTime().process_result_value(aware, None)
    assert out.tzinfo == UTC
    assert out == datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)


# ======================================================================================
# types.py :: UtcDateTime full round-trip through a real Client row
# ======================================================================================

def test_client_roundtrip_plus3_reads_back_as_aware_utc(db_session):
    aware = datetime(2020, 1, 1, 3, 0, 0, tzinfo=PLUS3)
    c = _client(mostaql_id="derived:rt1", last_refreshed_at=aware, first_seen_at=utcnow())
    db_session.add(c)
    db_session.commit()
    db_session.expire_all()
    got = db_session.get(Client, c.id)
    assert got.last_refreshed_at.tzinfo is not None
    # tz-aware UTC and equal to the original instant
    assert got.last_refreshed_at.utcoffset() == timedelta(0)
    assert got.last_refreshed_at == datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert got.last_refreshed_at == aware  # same instant


def test_client_roundtrip_utcnow_preserves_instant(db_session):
    now = utcnow()
    c = _client(mostaql_id="derived:rt2", last_refreshed_at=now, first_seen_at=now)
    db_session.add(c)
    db_session.commit()
    db_session.expire_all()
    got = db_session.get(Client, c.id)
    # SQLite truncates sub-second differently across builds; compare to second precision.
    delta = abs((got.last_refreshed_at - now).total_seconds())
    assert delta < 1.0
    assert got.last_refreshed_at.tzinfo is not None


def test_client_insert_naive_datetime_fails_loud(db_session):
    """Writing a naive datetime through the ORM must surface a ValueError (fail-closed).

    SQLAlchemy wraps the type-level ValueError in a StatementError; the original error
    must still be the ValueError raised by UtcDateTime (never a silent coercion).
    """
    c = _client(mostaql_id="derived:naive", last_refreshed_at=datetime(2020, 1, 1, 0, 0, 0))
    db_session.add(c)
    with pytest.raises(sa.exc.StatementError) as ei:
        db_session.flush()
    assert isinstance(ei.value.orig, ValueError)
    db_session.rollback()


def test_project_nullable_utc_columns_roundtrip_none(db_session):
    p = _project(mostaql_id="p_none", posted_at=None, last_eval_at=None, qualified_at=None)
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()
    got = db_session.get(Project, p.id)
    assert got.posted_at is None
    assert got.last_eval_at is None
    assert got.qualified_at is None


# ======================================================================================
# types.py :: JSONType round-trips nested dict and list
# ======================================================================================

def test_jsontype_roundtrip_nested_dict_on_raw(db_session):
    payload = {"a": 1, "b": {"c": [1, 2, {"d": "نص عربي"}], "e": None}, "f": True}
    p = _project(mostaql_id="p_json1", raw=payload)
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()
    got = db_session.get(Project, p.id)
    assert got.raw == payload
    assert isinstance(got.raw, dict)
    assert got.raw["b"]["c"][2]["d"] == "نص عربي"


def test_jsontype_roundtrip_list_on_skills(db_session):
    skills = ["python", "sql", "عربي", 3, {"x": 1}]
    p = _project(mostaql_id="p_json2", skills=skills)
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()
    got = db_session.get(Project, p.id)
    assert got.skills == skills
    assert isinstance(got.skills, list)


def test_jsontype_skills_none_roundtrip(db_session):
    p = _project(mostaql_id="p_json3", skills=None)
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()
    got = db_session.get(Project, p.id)
    assert got.skills is None


def test_jsontype_empty_collections_roundtrip(db_session):
    p = _project(mostaql_id="p_json4", raw={}, skills=[])
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()
    got = db_session.get(Project, p.id)
    assert got.raw == {}
    assert got.skills == []


def test_jsontype_module_attribute_is_json_variant():
    # JSONType is the portable column type used by the models.
    assert isinstance(JSONType, sa.JSON)


# ======================================================================================
# types.py :: make_enum / utcnow
# ======================================================================================

def test_make_enum_is_non_native_named():
    import enum as _enum

    class E(str, _enum.Enum):
        a = "a"
        b = "b"

    col = make_enum(E, "my_enum")
    assert isinstance(col, sa.Enum)
    assert col.name == "my_enum"
    assert col.native_enum is False


def test_utcnow_is_aware_utc():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


# ======================================================================================
# models.py :: derive_client_key
# ======================================================================================

def test_derive_client_key_deterministic_same_inputs():
    a = derive_client_key("Acme Co", "2019")
    b = derive_client_key("Acme Co", "2019")
    assert a == b


def test_derive_client_key_format_prefix_and_length():
    key = derive_client_key("Acme Co", "2019")
    assert key.startswith("derived:")
    assert len(key) == len("derived:") + 16  # 16-hex truncated sha1
    assert all(ch in "0123456789abcdef" for ch in key[len("derived:"):])


def test_derive_client_key_distinct_names_distinct_keys():
    assert derive_client_key("Acme", "2019") != derive_client_key("Beta", "2019")


def test_derive_client_key_distinct_member_since_distinct_keys():
    assert derive_client_key("Acme", "2019") != derive_client_key("Acme", "2020")


def test_derive_client_key_none_none_does_not_crash():
    key = derive_client_key(None, None)
    assert key.startswith("derived:")
    # None/None must equal empty/empty (both fold to "" via `or ''`)
    assert key == derive_client_key("", "")


def test_derive_client_key_name_none_vs_membersince_none_differ():
    # Different which-field-is-present should give different basis "|..." vs "...|"
    assert derive_client_key("Acme", None) != derive_client_key(None, "Acme")


def test_derive_client_key_strips_whitespace_both_fields():
    assert derive_client_key("  Acme  ", "  2019  ") == derive_client_key("Acme", "2019")
    assert derive_client_key("\tAcme\n", "\n2019\t") == derive_client_key("Acme", "2019")


def test_derive_client_key_internal_whitespace_significant():
    # Only leading/trailing folds; internal spaces are NOT collapsed.
    assert derive_client_key("Acme Co", "2019") != derive_client_key("AcmeCo", "2019")


def test_derive_client_key_separator_not_ambiguous():
    """The '|' separator must not let ("a|b", "") collide with ("a", "b")."""
    assert derive_client_key("a|b", "") != derive_client_key("a", "b")


def test_derive_client_key_unicode_arabic_stable():
    a = derive_client_key("شركة الأمل", "٢٠١٩")
    b = derive_client_key("شركة الأمل", "٢٠١٩")
    assert a == b
    assert a != derive_client_key("شركة الأمل", "2019")


def test_derive_client_key_matches_manual_sha1():
    import hashlib

    basis = "Acme Co|2019"
    expected = "derived:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    assert derive_client_key("Acme Co", "2019") == expected


# ======================================================================================
# upsert.py :: pk_columns
# ======================================================================================

def test_pk_columns_setting_is_key():
    assert pk_columns(Setting) == ["key"]


def test_pk_columns_project_is_id():
    assert pk_columns(Project) == ["id"]


def test_pk_columns_client_is_id():
    assert pk_columns(Client) == ["id"]


# ======================================================================================
# upsert.py :: exists_by
# ======================================================================================

def test_exists_by_false_on_empty(db_session):
    assert exists_by(db_session, Setting, key="absent") is False


def test_exists_by_true_after_insert(db_session):
    db_session.add(Setting(key="k_exists", value="v", value_type="str"))
    db_session.commit()
    assert exists_by(db_session, Setting, key="k_exists") is True


def test_exists_by_multi_filter(db_session):
    db_session.add(Setting(key="k_multi", value="v", value_type="int"))
    db_session.commit()
    assert exists_by(db_session, Setting, key="k_multi", value_type="int") is True
    assert exists_by(db_session, Setting, key="k_multi", value_type="str") is False


# ======================================================================================
# upsert.py :: upsert  (insert path + conflict-update path on sqlite)
# ======================================================================================

def test_upsert_inserts_new_row(db_session):
    upsert(
        db_session,
        Setting,
        {"key": "u1", "value": "first", "value_type": "str"},
        index_elements=["key"],
        update_cols=["value"],
    )
    db_session.commit()
    row = db_session.get(Setting, "u1")
    assert row is not None
    assert row.value == "first"


def test_upsert_conflict_updates_in_place_no_duplicate(db_session):
    upsert(
        db_session,
        Setting,
        {"key": "u2", "value": "v1", "value_type": "str"},
        index_elements=["key"],
        update_cols=["value"],
    )
    db_session.commit()
    upsert(
        db_session,
        Setting,
        {"key": "u2", "value": "v2", "value_type": "str"},
        index_elements=["key"],
        update_cols=["value"],
    )
    db_session.commit()
    db_session.expire_all()
    rows = db_session.query(Setting).filter_by(key="u2").all()
    assert len(rows) == 1  # no duplicate
    assert rows[0].value == "v2"  # value updated


def test_upsert_update_cols_restricts_what_changes(db_session):
    upsert(
        db_session,
        Setting,
        {"key": "u3", "value": "v1", "value_type": "str"},
        index_elements=["key"],
        update_cols=["value"],
    )
    db_session.commit()
    # conflict with a different value_type but update_cols only lists 'value'
    upsert(
        db_session,
        Setting,
        {"key": "u3", "value": "v2", "value_type": "int"},
        index_elements=["key"],
        update_cols=["value"],
    )
    db_session.commit()
    db_session.expire_all()
    row = db_session.get(Setting, "u3")
    assert row.value == "v2"
    assert row.value_type == "str"  # NOT updated (not in update_cols)


def test_upsert_returns_none(db_session):
    out = upsert(
        db_session,
        Setting,
        {"key": "u4", "value": "v", "value_type": "str"},
        index_elements=["key"],
        update_cols=["value"],
    )
    assert out is None
    db_session.commit()


def test_upsert_accepts_any_mapping_values(db_session):
    from collections import OrderedDict

    vals = OrderedDict([("key", "u5"), ("value", "ov"), ("value_type", "str")])
    upsert(db_session, Setting, vals, index_elements=["key"], update_cols=["value"])
    db_session.commit()
    assert db_session.get(Setting, "u5").value == "ov"


def test_upsert_then_exists_by(db_session):
    upsert(
        db_session,
        Setting,
        {"key": "u6", "value": "v", "value_type": "str"},
        index_elements=["key"],
        update_cols=["value"],
    )
    db_session.commit()
    assert exists_by(db_session, Setting, key="u6") is True


# ======================================================================================
# session.py :: get_engine / get_sessionmaker / create_all
# ======================================================================================

def _patch_session_secrets(monkeypatch, db_url):
    """Patch every binding of get_secrets and reset module globals; reset in finally by caller.

    session.py did ``from ..config.secrets import get_secrets`` so it holds its OWN reference;
    patching only config.secrets.get_secrets would NOT take effect. We patch both, clear the
    lru_cache, and null the cached engine/session globals so a fresh engine is built.
    """
    import mostaql_notifier.config.secrets as secrets_mod
    import mostaql_notifier.db.session as sess

    class _FakeSecrets:
        database_url = db_url

    def _fake_get_secrets():
        return _FakeSecrets()

    # clear the real lru_cache so the original can't be served from cache
    secrets_mod.get_secrets.cache_clear()
    monkeypatch.setattr(secrets_mod, "get_secrets", _fake_get_secrets, raising=True)
    monkeypatch.setattr(sess, "get_secrets", _fake_get_secrets, raising=True)
    sess._engine = None
    sess._Session = None
    return sess


def test_get_engine_creates_nested_dir_and_enables_fk(monkeypatch, tmp_path):
    import mostaql_notifier.db.session as sess

    db_path = str(tmp_path / "nested" / "dir" / "x.db")
    assert not os.path.exists(os.path.dirname(db_path))
    try:
        sess = _patch_session_secrets(monkeypatch, "sqlite:///" + db_path)
        engine = sess.get_engine()
        # nested directory was created
        assert os.path.isdir(os.path.dirname(db_path))
        # FK pragma is ON via the connect listener
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("PRAGMA foreign_keys")
            assert cur.fetchone()[0] == 1
            cur.close()
        finally:
            raw.close()
    finally:
        sess._engine = None
        sess._Session = None
        # monkeypatch teardown restores the original lru_cache-wrapped get_secrets.


def test_get_engine_is_cached_singleton(monkeypatch, tmp_path):
    import mostaql_notifier.db.session as sess

    db_path = str(tmp_path / "n2" / "x.db")
    try:
        sess = _patch_session_secrets(monkeypatch, "sqlite:///" + db_path)
        e1 = sess.get_engine()
        e2 = sess.get_engine()
        assert e1 is e2
    finally:
        sess._engine = None
        sess._Session = None
        # monkeypatch teardown restores the original lru_cache-wrapped get_secrets.


def test_get_sessionmaker_usable(monkeypatch, tmp_path):
    import mostaql_notifier.db.session as sess

    db_path = str(tmp_path / "n3" / "x.db")
    try:
        sess = _patch_session_secrets(monkeypatch, "sqlite:///" + db_path)
        sess.create_all()
        sm = sess.get_sessionmaker()
        assert isinstance(sm, sessionmaker)
        with sm() as s:
            s.add(Setting(key="smk", value="smv", value_type="str"))
            s.commit()
            assert s.get(Setting, "smk").value == "smv"
    finally:
        sess._engine = None
        sess._Session = None
        # monkeypatch teardown restores the original lru_cache-wrapped get_secrets.


def test_create_all_builds_tables(monkeypatch, tmp_path):
    import mostaql_notifier.db.session as sess

    db_path = str(tmp_path / "n4" / "x.db")
    try:
        sess = _patch_session_secrets(monkeypatch, "sqlite:///" + db_path)
        sess.create_all()
        engine = sess.get_engine()
        tables = set(sa.inspect(engine).get_table_names())
        assert {"settings", "clients", "projects", "scrape_runs",
                "notifications_log", "app_state"} <= tables
    finally:
        sess._engine = None
        sess._Session = None
        # monkeypatch teardown restores the original lru_cache-wrapped get_secrets.


def test_get_sessionmaker_calls_get_engine_first(monkeypatch, tmp_path):
    # get_sessionmaker must bootstrap the engine even if not called yet.
    import mostaql_notifier.db.session as sess

    db_path = str(tmp_path / "n5" / "x.db")
    try:
        sess = _patch_session_secrets(monkeypatch, "sqlite:///" + db_path)
        assert sess._engine is None
        sm = sess.get_sessionmaker()
        assert sm is not None
        assert sess._engine is not None  # engine was created as a side effect
    finally:
        sess._engine = None
        sess._Session = None
        # monkeypatch teardown restores the original lru_cache-wrapped get_secrets.
