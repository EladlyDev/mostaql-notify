"""Cover the deliberately-defensive seams the happy paths don't reach (but which ARE reachable)."""
from __future__ import annotations

import random
from decimal import Decimal

import mostaql_notifier.qualify.filters as filters_mod
from mostaql_notifier.db.models import (
    Client,
    EvalStatus,
    Project,
    ProjectStatus,
    Setting,
)
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.qualify.budget_policy import BudgetPolicy
from mostaql_notifier.qualify.filters import qualify
from mostaql_notifier.worker.politeness import backoff_seconds


def _client():
    return Client(
        mostaql_id="derived:x", hiring_rate=75.0,
        last_refreshed_at=utcnow(), first_seen_at=utcnow(), raw={},
    )


def _project(settings):
    return Project(
        mostaql_id="p", budget_max=Decimal(300), currency="USD", scraped_at=utcnow(),
        site_status=ProjectStatus.open, eval_status=EvalStatus.pending,
        category=settings.get_str("category_slug"), raw={},
    )


def test_exclusion_gate_disqualifies_when_a_rule_rejects(db_session, settings, monkeypatch):
    # exclusion_passes is a pass-through today; when a future rule rejects a project, the gate must
    # disqualify it with reason 'excluded' (filters.py line 83). All earlier gates pass here.
    monkeypatch.setattr(filters_mod, "exclusion_passes", lambda project, s: False)
    q = qualify(_project(settings), _client(), BudgetPolicy(active_floor=Decimal(250)), settings)
    assert q.qualified is False
    assert q.reason == "excluded"
    assert q.tier is None


def _set(session, settings, key, value):
    row = session.get(Setting, key)
    row.value = str(value)
    session.commit()
    settings.reload()


def test_backoff_clamps_negative_ceiling_to_zero(db_session, settings):
    # A misconfigured negative retry cap must never yield a negative backoff (politeness line 138):
    # the ceiling is clamped to 0 so uniform(0, 0) == 0.
    _set(db_session, settings, "retry_cap_seconds", -5)
    for _ in range(50):
        assert backoff_seconds(0, settings, random.Random(0)) == 0.0
