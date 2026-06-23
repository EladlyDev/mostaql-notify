"""Unit tests for qualification filters and the USD budget basis."""
from __future__ import annotations

from decimal import Decimal

from mostaql_notifier.db.models import Client, EvalStatus, Project, ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.qualify.budget_policy import BudgetPolicy
from mostaql_notifier.qualify.filters import budget_usd, qualify


def _client(hiring_rate):
    return Client(
        mostaql_id="derived:abc",
        name="عميل",
        hiring_rate=hiring_rate,
        last_refreshed_at=utcnow(),
        first_seen_at=utcnow(),
        raw={},
    )


def _project(settings, *, budget_min=None, budget_max=Decimal(300), currency="USD",
             status=ProjectStatus.open, category=None):
    return Project(
        mostaql_id="p1",
        title="مشروع تطوير",
        budget_min=budget_min,
        budget_max=budget_max,
        currency=currency,
        scraped_at=utcnow(),
        site_status=status,
        eval_status=EvalStatus.pending,
        category=settings.get_str("category_slug") if category is None else category,
        raw={},
    )


def _policy():
    return BudgetPolicy(active_floor=Decimal(250))


def test_hiring_rate_none_disqualified(db_session, settings):
    proj = _project(settings)
    result = qualify(proj, _client(None), _policy(), settings)
    assert result.qualified is False
    assert result.tier is None


def test_hiring_rate_zero_disqualified(db_session, settings):
    # 0.0 is a real value but must FAIL (not strictly > 0).
    proj = _project(settings)
    result = qualify(proj, _client(0.0), _policy(), settings)
    assert result.qualified is False


def test_valid_project_qualifies_tier1(db_session, settings):
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is True
    assert result.tier == 1


def test_missing_budget_disqualified(db_session, settings):
    proj = _project(settings, budget_min=None, budget_max=None)
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False
    assert result.tier is None


def test_one_sided_budget_uses_present_bound(db_session, settings):
    # Basis default is "max"; only budget_max present -> uses it.
    proj = _project(settings, budget_min=None, budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(300)
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is True


def test_currency_none_disqualified(db_session, settings):
    proj = _project(settings, currency=None)
    assert budget_usd(proj, settings) is None
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False


def test_currency_not_in_rates_disqualified(db_session, settings):
    proj = _project(settings, currency="EUR")
    assert budget_usd(proj, settings) is None
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False


def test_closed_project_disqualified(db_session, settings):
    proj = _project(settings, status=ProjectStatus.closed)
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False


def test_wrong_category_disqualified(db_session, settings):
    proj = _project(settings, category="design")
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False
