"""Pure tests for the Feature-4 scoring additions to ``notify.format`` (T045).

Covered:
  * the ``🎯 Score: NN · Tier T`` headline line — present with a score row, placed directly under
    the title and above the budget line, and **omitted gracefully** when the project is unscored;
  * ``build_score_breakdown_message`` — one Arabic line per component whose point contributions sum
    (within rounding) to the headline total;
  * the new ``🎯 لماذا؟`` Why button + its ``pf:why:{id}`` codec round-trip.

All pure — no Telegram network, no DB session.
"""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from mostaql_notifier.db.models import Client, Project, ProjectScore
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.notify.format import (
    CB_WHY,
    build_callback_data,
    build_project_keyboard,
    build_project_message,
    build_score_breakdown_message,
    parse_callback_data,
)

_BREAKDOWN = {
    "score": 82.0,
    "normalized": False,
    "components": [
        {"key": "hiring_rate", "label": "معدل التوظيف", "contribution": 28.5},
        {"key": "hire_volume", "label": "حجم التوظيف", "contribution": 9.2},
        {"key": "budget", "label": "الميزانية", "contribution": 11.0},
        {"key": "competition", "label": "المنافسة", "contribution": 14.8},
        {"key": "freshness", "label": "الحداثة", "contribution": 6.5},
        {"key": "rating", "label": "تقييم العميل", "contribution": 12.0},
    ],
}


def _make_pair(now, *, score: float | None = 82.0, tier: int | None = 1):
    client = Client(
        mostaql_id="derived:abc123",
        name="عميل تجريبي",
        hiring_rate=87.0,
        last_refreshed_at=now,
        first_seen_at=now,
        raw={},
    )
    project = Project(
        mostaql_id="proj-42",
        title="تطوير موقع <ووردبريس>",
        url="https://mostaql.com/project/proj-42",
        category="تطوير",
        budget_min=Decimal("250"),
        budget_max=Decimal("500"),
        currency="USD",
        bids_count=7,
        posted_at=now - timedelta(hours=2),
        scraped_at=now,
        tier=tier,
        raw={},
    )
    if score is not None:
        project.score_row = ProjectScore(score=score, breakdown=dict(_BREAKDOWN))
    return project, client


# --- the score + tier headline line --------------------------------------------------------------

def test_score_line_present_under_title_above_budget():
    now = utcnow()
    project, client = _make_pair(now, score=82.0, tier=1)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "🎯 Score: 82 · Tier 1" in msg
    # Placement: between the bold title and the 💰 budget line.
    assert msg.index("</b>") < msg.index("🎯 Score:") < msg.index("💰")


def test_score_is_rounded_to_an_integer():
    now = utcnow()
    project, client = _make_pair(now, score=81.6, tier=2)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "🎯 Score: 82 · Tier 2" in msg  # 81.6 → 82
    assert "81.6" not in msg


def test_score_line_omitted_when_no_score_row():
    now = utcnow()
    project, client = _make_pair(now, score=None)

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "🎯 Score:" not in msg
    # The rest of the notification is unaffected (budget/tier still rendered).
    assert "💰" in msg and "Tier 1" in msg


def test_score_line_omitted_when_score_is_none():
    now = utcnow()
    project, client = _make_pair(now, score=None)
    project.score_row = ProjectScore(score=None, breakdown={})  # row exists but never computed

    msg = build_project_message(project, client, now_utc=now, owner_tz="Africa/Cairo")

    assert "🎯 Score:" not in msg


# --- the "Why?" breakdown message ----------------------------------------------------------------

def test_breakdown_message_header_title_and_components():
    project = SimpleNamespace(title="تصميم <متجر>")

    msg = build_score_breakdown_message(project, _BREAKDOWN)

    assert "🎯 تقييم الفرصة: 82 / 100" in msg
    assert "<b>تصميم &lt;متجر&gt;</b>" in msg  # title is bold + html-escaped
    for comp in _BREAKDOWN["components"]:
        assert f"• {comp['label']}: {comp['contribution']:.1f} نقطة" in msg


def test_breakdown_contributions_sum_to_the_total():
    project = SimpleNamespace(title="مشروع")

    msg = build_score_breakdown_message(project, _BREAKDOWN)

    rendered = [float(x) for x in re.findall(r"([0-9]+\.[0-9]) نقطة", msg)]
    assert len(rendered) == len(_BREAKDOWN["components"])
    assert round(sum(rendered)) == round(_BREAKDOWN["score"])  # accounting adds up to the headline


def test_breakdown_message_handles_missing_score_and_empty_components():
    project = SimpleNamespace(title="بلا مكوّنات")

    msg = build_score_breakdown_message(project, {"score": None, "components": []})

    assert "🎯 تقييم الفرصة: 0 / 100" in msg  # None total degrades to 0, never raises
    assert "نقطة" not in msg  # no component lines


# --- the Why button + pf:why codec ---------------------------------------------------------------

def test_why_button_present_and_codec_round_trips():
    kb = build_project_keyboard(SimpleNamespace(id=123, url="https://mostaql.com/project/123"))
    buttons = [b for row in kb.inline_keyboard for b in row]

    why = next(b for b in buttons if b.callback_data == build_callback_data(CB_WHY, 123))
    assert why.text == "🎯 لماذا؟"
    assert why.url is None  # it is a callback button, not a URL button
    assert parse_callback_data(why.callback_data) == (CB_WHY, 123)
    assert build_callback_data(CB_WHY, 123) == "pf:why:123"


def test_why_shares_final_row_with_open_and_stands_alone_without_url():
    with_url = build_project_keyboard(SimpleNamespace(id=7, url="https://mostaql.com/project/7"))
    last_row = with_url.inline_keyboard[-1]
    assert last_row[0].callback_data == build_callback_data(CB_WHY, 7)
    assert last_row[1].url == "https://mostaql.com/project/7"  # Open pairs with Why on the last row

    no_url = build_project_keyboard(SimpleNamespace(id=7, url=None))
    last_row = no_url.inline_keyboard[-1]
    assert len(last_row) == 1  # Why stands alone, never dropped
    assert last_row[0].callback_data == build_callback_data(CB_WHY, 7)
