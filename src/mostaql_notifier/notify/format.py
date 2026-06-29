"""Pure Telegram message builders (HTML parse_mode).

No I/O, no network, no clock reads here: callers pass ``now_utc`` and ``owner_tz`` so these stay
deterministic and unit-testable. Each notification field lives on its own line so an RTL Arabic
title and an LTR budget/number do not visually scramble when rendered together.
"""
from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..db.models import Client, Project

_MAX_LEN = 4096

# --- Inline action-button codec (Feature 3, research §4) -------------------------------------
# Compact callback_data ``pf:{action}:{project_id}`` — well within Telegram's 64-byte limit (the DB
# id is far shorter than the mostaql id). The bot (bot/callbacks.py) parses these; "Open" is a URL
# button (no callback), so it carries no action.
CALLBACK_PREFIX = "pf"
CB_FAVORITE = "fav"
CB_APPLIED = "app"
CB_DISMISS = "dis"
CB_NOTE = "note"
# Feature 4 — a read-only "Why?" tap that replies with the score breakdown (no mutation, no edit).
CB_WHY = "why"
_CALLBACK_ACTIONS = frozenset({CB_FAVORITE, CB_APPLIED, CB_DISMISS, CB_NOTE, CB_WHY})


def build_callback_data(action: str, project_id: int) -> str:
    """Encode a callback action + project id as ``pf:{action}:{project_id}`` (≤ 64 bytes)."""
    return f"{CALLBACK_PREFIX}:{action}:{project_id}"


def parse_callback_data(data: str) -> tuple[str, int] | None:
    """Decode ``pf:{action}:{project_id}`` → ``(action, project_id)``; None if it isn't ours."""
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX or parts[1] not in _CALLBACK_ACTIONS:
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


def build_project_keyboard(project: Project) -> InlineKeyboardMarkup:
    """The inline keyboard attached to each project notification (FR-024).

    Layout (Arabic-first):
        [⭐ مفضّل] [✅ تقدّمت] / [🙈 إخفاء] [📝 ملاحظة] / [🎯 لماذا؟] [🔗 فتح على مستقل].
    The first four are Feature-3 callback buttons (unchanged); "Why?" is a Feature-4 callback button
    sharing the final row with "Open" (a URL button to the project on Mostaql). When the project has
    no URL, Open is dropped (existing behavior) and "Why?" stands alone on that row — never omitted.
    """
    pid = project.id
    rows = [
        [
            InlineKeyboardButton("⭐ مفضّل", callback_data=build_callback_data(CB_FAVORITE, pid)),
            InlineKeyboardButton("✅ تقدّمت", callback_data=build_callback_data(CB_APPLIED, pid)),
        ],
        [
            InlineKeyboardButton("🙈 إخفاء", callback_data=build_callback_data(CB_DISMISS, pid)),
            InlineKeyboardButton("📝 ملاحظة", callback_data=build_callback_data(CB_NOTE, pid)),
        ],
    ]
    last_row = [InlineKeyboardButton("🎯 لماذا؟", callback_data=build_callback_data(CB_WHY, pid))]
    if project.url:
        last_row.append(InlineKeyboardButton("🔗 فتح على مستقل", url=project.url))
    rows.append(last_row)
    return InlineKeyboardMarkup(rows)


def html_escape(text: object) -> str:
    """HTML-escape any value for safe inclusion in a parse_mode=HTML message."""
    return html.escape("" if text is None else str(text))


def _safe_truncate(text: str, limit: int) -> str:
    """Truncate to <= ``limit`` chars without splitting a trailing HTML entity.

    A char-count slice over already-escaped text can land mid-entity ("&amp;" -> "&am"), which
    Telegram's HTML parser rejects (400) — dropping the message exactly when it matters. We back
    the cut up to before any half-written ``&…`` entity before appending the ellipsis.
    """
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]
    return cut + "…"


def relative_since(dt: datetime | None, now_utc: datetime) -> str:
    """Human "Nm/h/d ago" relative to ``now_utc``; "unknown" when ``dt`` is None."""
    if dt is None:
        return "unknown"
    seconds = (now_utc - dt).total_seconds()
    if seconds < 0:
        seconds = 0.0
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _fmt_decimal(value: Decimal | None) -> str | None:
    """Render a Decimal without a trailing ``.00`` (250 not 250.00); None passes through."""
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    d = d.normalize()
    # normalize() can yield exponent form (e.g. 2.5E+2); expand it back.
    if d == d.to_integral_value():
        d = d.quantize(Decimal(1))
    return format(d, "f")


def _budget_text(project: Project) -> str:
    lo = _fmt_decimal(project.budget_min)
    hi = _fmt_decimal(project.budget_max)
    cur = (project.currency or "").strip()
    if lo is None and hi is None:
        body = "unknown"
    elif lo is not None and hi is not None:
        body = f"{lo}–{hi}" if lo != hi else lo
    else:
        body = lo if lo is not None else hi  # one bound known
    return f"{body} {cur}".strip()


def build_project_message(
    project: Project,
    client: Client,
    *,
    now_utc: datetime,
    owner_tz: str,
) -> str:
    """HTML notification: title, budget+tier, hiring rate, bids, age, category, link.

    Fields appear in that exact order, each on its own line, escaped where free-text. ``owner_tz``
    is accepted for symmetry with the heartbeat/owner-clock convention but the body uses a relative
    age (timezone-independent) so RTL/LTR mixing stays stable.
    """
    ZoneInfo(owner_tz)  # validate the configured zone fail-loud rather than silently mis-display

    tier_text = f"Tier {project.tier}" if project.tier is not None else "Tier ?"
    budget = html_escape(_budget_text(project))

    if client is not None and client.hiring_rate is not None:
        hiring = f"{client.hiring_rate:.0f}%"
    else:
        hiring = "unknown"

    bids = project.bids_count if project.bids_count is not None else "unknown"
    age = relative_since(project.posted_at, now_utc)
    category = html_escape(project.category) if project.category else "unknown"
    url = html_escape(project.url) if project.url else ""

    # Feature 4 (FR-030) — the opportunity score is the new headline field, on its own line directly
    # under the title and above the budget. An as-yet-unscored project (no score row / score is None)
    # omits the line entirely rather than printing a placeholder; scoring never gates the notification.
    score_row = getattr(project, "score_row", None)
    score_value = score_row.score if score_row is not None else None

    rest_lines = []
    if score_value is not None:
        rest_lines.append(f"🎯 Score: {html_escape(round(score_value))} · {html_escape(tier_text)}")
    rest_lines += [
        f"💰 {budget} · {html_escape(tier_text)}",
        f"📈 Hiring rate: {html_escape(hiring)}",
        f"🧮 Bids: {html_escape(bids)}",
        f"🕒 Posted: {html_escape(age)}",
        f"🏷️ {category}",
        f"🔗 {url}" if url else "🔗 unknown",
    ]

    def _render(title_text: str) -> str:
        return "\n".join([f"<b>{html_escape(title_text)}</b>", *rest_lines])

    text = _render(project.title or "")
    if len(text) > _MAX_LEN:
        # Truncate the RAW title (pre-escape) so the <b> tag stays balanced and no HTML entity is
        # ever split — Telegram rejects malformed HTML with a 400, which would silently drop a
        # qualifying notification (constitution: at-least-once). Escaping only grows length, so trim
        # raw characters until the rendered message fits.
        raw = project.title or ""
        cut = min(len(raw), (len(text) - _MAX_LEN) + 1)
        raw = raw[: len(raw) - cut]
        while raw and len(_render(raw + "…")) > _MAX_LEN:  # pragma: no cover
            raw = raw[:-1]  # belt-and-suspenders: the cut above already guarantees a fit
        text = _render(raw + "…")
    return text


def build_score_breakdown_message(project: Project, breakdown: dict) -> str:
    """HTML "Why?" reply: the total score, the project title, and one line per scored component.

    Pure (no I/O, no clock): the numbers come straight from the stored ``project_scores.breakdown``
    dict the scoring service returns, so the bot, the dashboard and ``/top`` always agree (FR-031).
    Arabic-first; every interpolated value is ``html_escape``d and each component sits on its own line
    so an RTL label and its LTR points value stay stable. ``parse_mode=HTML`` at the call site.

    ``breakdown`` is the nullable ``project_scores.breakdown`` column; a ``None`` (or a dict missing
    keys) degrades to a header-only "0 / 100" reply rather than raising.
    """
    breakdown = breakdown or {}
    score_value = breakdown.get("score")
    score = round(score_value) if score_value is not None else 0
    lines = [
        f"🎯 تقييم الفرصة: {html_escape(score)} / 100",
        f"<b>{html_escape(project.title or '')}</b>",
        "",
    ]
    for component in breakdown.get("components", []):
        label = component.get("label", "")
        contribution = component.get("contribution")
        contribution = float(contribution) if contribution is not None else 0.0
        lines.append(f"• {html_escape(label)}: {html_escape(f'{contribution:.1f}')} نقطة")
    return "\n".join(lines)


def build_health_alert(
    *,
    kind: str,
    detail: str,
    action: str,
    found,
    new,
    updated,
    errors,
) -> str:
    """Operator alert (HTML) for a degraded/blocked run."""
    lines = [
        f"<b>⚠️ Health alert: {html_escape(kind)}</b>",
        html_escape(detail),
        f"Action: {html_escape(action)}",
        (
            f"Counts — found {html_escape(found)}, new {html_escape(new)}, "
            f"updated {html_escape(updated)}, errors {html_escape(errors)}"
        ),
    ]
    return _safe_truncate("\n".join(lines), _MAX_LEN)


def build_heartbeat(*, last_poll_iso: str, active_floor) -> str:
    """Periodic "still alive" message (HTML)."""
    lines = [
        "<b>💚 Heartbeat</b>",
        f"Last poll: {html_escape(last_poll_iso)}",
        f"Active budget floor: {html_escape(active_floor)}",
    ]
    return "\n".join(lines)
