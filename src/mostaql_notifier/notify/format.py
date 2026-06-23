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

from ..db.models import Client, Project

_MAX_LEN = 4096


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

    rest_lines = [
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
