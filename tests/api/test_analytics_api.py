"""T054/T055 — GET /api/analytics/overview (Feature 6, the read-only analytics overview).

Covers the auth gate (401), the empty-DB honest default shape (every section ``enough_data=False``,
``tips == []``, default range applied), the inverted-range 422, and each populated section
(heatmap / volume / budget / competition / outcomes / funnel) behaving per the aggregates contract.
Also pins the two cross-cutting invariants from ``contracts/analytics-aggregates.md`` "Invariants":
the SAME ``date_from``/``date_to`` scopes EVERY section (T055), and the endpoint is strictly
READ-ONLY — a series of calls leaves projects / scores / snapshots / personal records byte-for-byte
unchanged (T054, SC-008, constitution IV).

All data is seeded via the conftest factories; the analytics timezone is the default ``Africa/Cairo``
so the test pins posting times to Cairo-noon (boundary-proof) when an exact local day matters.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from mostaql_notifier.db.models import Outcome, ProjectStatus, Setting
from tests.api.conftest import (
    make_personal_record,
    make_project,
    make_project_score,
    make_trajectory,
)

CAIRO = ZoneInfo("Africa/Cairo")
OVERVIEW = "/api/analytics/overview"
SECTIONS = ("heatmap", "volume", "budget", "competition", "outcomes", "funnel")


# --- helpers ---------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cairo_noon_utc(d: date) -> datetime:
    """A UTC instant that is unambiguously local noon on calendar date ``d`` in the analytics tz."""
    return datetime.combine(d, time(12, 0), tzinfo=CAIRO).astimezone(timezone.utc)


def _today_cairo() -> date:
    return datetime.now(CAIRO).date()


def _set_setting(session, key: str, value, value_type: str = "int") -> None:
    """Override a (already-seeded) ``settings`` row in place, then the caller commits."""
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=str(value), value_type=value_type))
    else:
        row.value = str(value)
        row.value_type = value_type


def _overview(client, **params) -> dict:
    resp = client.get(OVERVIEW, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _dump_owner_tables(session) -> dict[str, list[tuple]]:
    """Full ordered content of every table the analytics endpoint must never touch."""
    tables = {
        "projects": "id",
        "project_scores": "project_id",
        "project_snapshots": "id",
        "personal_records": "project_id",
    }
    snapshot: dict[str, list[tuple]] = {}
    for tbl, order in tables.items():
        rows = session.execute(text(f"SELECT * FROM {tbl} ORDER BY {order}")).fetchall()
        snapshot[tbl] = [tuple(r) for r in rows]
    return snapshot


# --- 401 -------------------------------------------------------------------


def test_overview_requires_auth(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    assert client.get(OVERVIEW).status_code == 401


# --- empty-DB default shape ------------------------------------------------


def test_overview_empty_db_default_shape(api_env):
    body = _overview(api_env.client())

    # Exactly the documented top-level sections.
    assert set(body) == {
        "range",
        "heatmap",
        "volume",
        "budget",
        "competition",
        "outcomes",
        "funnel",
        "tips",
    }

    # Honest under thin data: no section claims enough support, and no tips are emitted.
    for name in SECTIONS:
        assert body[name]["enough_data"] is False, name
    assert body["tips"] == []

    # No range was supplied → the configured default window is applied, in a real tz.
    rng = body["range"]
    assert rng["default_applied"] is True
    assert isinstance(rng["timezone"], str) and rng["timezone"]


# --- 422 inverted range ----------------------------------------------------


def test_overview_inverted_range_422(api_env):
    resp = api_env.client().get(OVERVIEW, params={"date_from": "2026-06-30", "date_to": "2026-01-01"})
    assert resp.status_code == 422


# --- heatmap ---------------------------------------------------------------


def test_overview_heatmap_above_support_and_date_scoped(api_env):
    today = _today_cairo()
    old = today - timedelta(days=10)
    with api_env.session() as s:
        _set_setting(s, "analytics_min_support", 3)  # lower the gate so a small seed counts
        for n in range(4):  # posted "today" (local)
            make_project(s, _n=100 + n, posted_at=_cairo_noon_utc(today))
        for n in range(3):  # posted 10 local days ago
            make_project(s, _n=200 + n, posted_at=_cairo_noon_utc(old))
        s.commit()

    client = api_env.client()  # built AFTER seeding so the lowered support takes effect

    full = _overview(client)["heatmap"]
    assert full["enough_data"] is True
    assert full["peak"] is not None
    assert full["total"] == 7

    # Narrowing to just "today" (local) excludes the 10-day-old postings → the count shrinks.
    narrow = _overview(client, date_from=today.isoformat(), date_to=today.isoformat())["heatmap"]
    assert narrow["total"] == 4
    assert narrow["total"] < full["total"]


# --- volume + budget -------------------------------------------------------


def test_overview_volume_and_budget_sections(api_env):
    today = _today_cairo()
    yesterday = today - timedelta(days=1)
    with api_env.session() as s:
        # Day A: two Tier-1 USD-budgeted qualified projects.
        make_project(s, _n=1, tier=1, budget_min=100, budget_max=500, posted_at=_cairo_noon_utc(today))
        make_project(s, _n=2, tier=1, budget_min=200, budget_max=600, posted_at=_cairo_noon_utc(today))
        # Day B: one Tier-2 USD-budgeted + one unknown-budget (no tier, no budget) project.
        make_project(s, _n=3, tier=2, budget_min=50, budget_max=300, posted_at=_cairo_noon_utc(yesterday))
        make_project(
            s,
            _n=4,
            tier=None,
            budget_min=None,
            budget_max=None,
            posted_at=_cairo_noon_utc(yesterday),
        )
        s.commit()

    body = _overview(api_env.client())

    volume = body["volume"]
    assert len(volume["by_day"]) >= 2  # two distinct local days seeded
    assert volume["by_week"]  # weekly rollup present and non-empty
    assert volume["enough_data"] is True

    budget = body["budget"]
    # Tier + unknown counts partition the total (the one-sided/unknown-budget project is unknown).
    assert budget["unknown_count"] >= 1
    assert budget["tier1_count"] + budget["tier2_count"] + budget["unknown_count"] == budget["total"]
    assert budget["total"] == 4


# --- competition -----------------------------------------------------------


def test_overview_competition_section(api_env):
    base = _cairo_noon_utc(_today_cairo())
    with api_env.session() as s:
        for n in range(2):
            p = make_project(s, _n=300 + n, posted_at=base)
            make_trajectory(
                s,
                p,
                [
                    (base + timedelta(hours=1), 2, ProjectStatus.open, 70.0),
                    (base + timedelta(hours=2), 6, ProjectStatus.open, 68.0),
                    (base + timedelta(hours=3), 11, ProjectStatus.open, 65.0),
                ],
            )
        s.commit()

    competition = _overview(api_env.client())["competition"]
    assert len(competition["by_hour"]) == 24
    assert isinstance(competition["headline"], str) and competition["headline"]


# --- outcomes --------------------------------------------------------------


def test_overview_outcomes_section(api_env):
    now = _now()
    with api_env.session() as s:
        # A hire the owner DID apply to (not missed).
        hired_applied = make_project(s, _n=1)
        make_project_score(s, project=hired_applied, outcome=Outcome.hired)
        make_personal_record(s, project=hired_applied, status="applied", applied_at=now)
        # A hire the owner NEVER applied to → a missed opportunity.
        hired_missed = make_project(s, _n=2)
        make_project_score(s, project=hired_missed, outcome=Outcome.hired)
        # Concluded with no hire.
        no_hire = make_project(s, _n=3)
        make_project_score(s, project=no_hire, outcome=Outcome.closed_no_hire)
        # Still open.
        still_open = make_project(s, _n=4)
        make_project_score(s, project=still_open, outcome=Outcome.open)
        # Ambiguous ending.
        ambiguous = make_project(s, _n=5)
        make_project_score(s, project=ambiguous, outcome=Outcome.unknown)
        s.commit()

    outcomes = _overview(api_env.client())["outcomes"]

    # Exactly the two real hires — unknown/open are NEVER folded into hired (fail-closed, VII).
    assert outcomes["hired_count"] == 2
    assert outcomes["unknown_count"] == 1
    assert outcomes["open_count"] == 1
    assert outcomes["no_hire_count"] == 1
    # The hire with no application is surfaced as a missed opportunity.
    assert outcomes["missed_count"] >= 1


# --- funnel ----------------------------------------------------------------


def test_overview_funnel_section(api_env):
    now = _now()
    with api_env.session() as s:
        won = make_project(s, _n=1)
        make_personal_record(s, project=won, status="won", applied_at=now)
        disc = make_project(s, _n=2)
        make_personal_record(s, project=disc, status="in_discussion", applied_at=now)
        applied = make_project(s, _n=3)
        make_personal_record(s, project=applied, status="applied", applied_at=now)
        fav = make_project(s, _n=4)
        make_personal_record(s, project=fav, status="interested", favorite=True)
        make_project(s, _n=5)  # "seen" only (default record-less status)
        s.commit()

    funnel = _overview(api_env.client())["funnel"]
    stages = funnel["stages"]

    # Base stage is "seen" with no conversion-from-previous.
    assert stages[0]["key"] == "seen"
    assert stages[0]["conv_from_prev"] is None

    # Monotonic by construction: seen ≥ favourited ≥ applied ≥ in_discussion ≥ won.
    counts = [st["count"] for st in stages]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 5  # all five projects are "seen"
    assert counts[-1] == 1  # exactly one "won"


# --- date scoping consistency (T055) ---------------------------------------


def test_overview_date_scoping_scopes_every_section(api_env):
    base = _cairo_noon_utc(_today_cairo())
    with api_env.session() as s:
        p1 = make_project(s, _n=1, posted_at=base)
        make_project_score(s, project=p1, outcome=Outcome.hired)
        make_personal_record(s, project=p1, status="applied", applied_at=base)
        p2 = make_project(s, _n=2, posted_at=base)
        make_trajectory(
            s,
            p2,
            [
                (base + timedelta(hours=1), 3, ProjectStatus.open, 70.0),
                (base + timedelta(hours=2), 7, ProjectStatus.open, 66.0),
            ],
        )
        s.commit()

    client = api_env.client()

    # Default (covering) window: the seeded data shows up across sections.
    covered = _overview(client)
    assert covered["heatmap"]["total"] > 0
    assert covered["volume"]["by_day"]
    assert covered["funnel"]["seen"] > 0
    assert covered["outcomes"]["hired_count"] > 0

    # A range that excludes ALL the data empties EVERY section (one date filter, every chart).
    empty = _overview(client, date_from="2000-01-01", date_to="2000-01-02")
    assert empty["heatmap"]["total"] == 0
    assert empty["heatmap"]["cells"] == []
    assert empty["volume"]["by_day"] == []
    assert empty["volume"]["by_week"] == []
    assert empty["budget"]["total"] == 0
    assert empty["competition"]["age_curve"] == []
    assert sum(empty["competition"]["by_hour"]) == 0
    assert empty["outcomes"]["hired_count"] == 0
    assert empty["outcomes"]["missed_count"] == 0
    assert empty["funnel"]["seen"] == 0
    assert all(st["count"] == 0 for st in empty["funnel"]["stages"])
    assert empty["tips"] == []


# --- READ-ONLY invariant (T054, SC-008, constitution IV) -------------------


def test_overview_is_strictly_read_only(api_env):
    base = _cairo_noon_utc(_today_cairo())
    with api_env.session() as s:
        hired = make_project(s, _n=1, posted_at=base)
        make_project_score(s, project=hired, outcome=Outcome.hired)  # missed (no personal record)
        no_hire = make_project(s, _n=2, posted_at=base)
        make_project_score(s, project=no_hire, outcome=Outcome.closed_no_hire)
        make_personal_record(s, project=no_hire, status="applied", applied_at=base)
        tracked = make_project(s, _n=3, posted_at=base)
        make_trajectory(
            s,
            tracked,
            [
                (base + timedelta(hours=1), 4, ProjectStatus.open, 72.0),
                (base + timedelta(hours=2), 9, ProjectStatus.open, 64.0),
            ],
        )
        s.commit()

    with api_env.session() as s:
        before = _dump_owner_tables(s)

    client = api_env.client()
    # A series of calls with varied ranges (default, all-time, narrow, and a 422 inverted range).
    client.get(OVERVIEW)
    client.get(OVERVIEW, params={"date_from": "2000-01-01", "date_to": "2100-01-01"})
    client.get(
        OVERVIEW,
        params={"date_from": _today_cairo().isoformat(), "date_to": _today_cairo().isoformat()},
    )
    client.get(OVERVIEW, params={"date_from": "2030-01-01", "date_to": "2020-01-01"})  # 422, no write

    with api_env.session() as s:
        after = _dump_owner_tables(s)

    # Row COUNT unchanged per table …
    assert {t: len(r) for t, r in after.items()} == {t: len(r) for t, r in before.items()}
    # … and full CONTENT byte-for-byte unchanged.
    assert after == before
