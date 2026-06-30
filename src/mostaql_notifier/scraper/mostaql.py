"""HTML parsers for mostaql.com listing, project, and profile pages.

Pure functions: given page HTML, return plain dicts (the orchestrator builds ORM rows). Per
constitution these fail closed — an unrecognised value yields ``None`` / ``ProjectStatus.unknown``
rather than a guess — but a *structural* surprise (missing meta rows or hiring-rate row, i.e. the
site changed shape) raises :class:`ParseError` so the caller fails loud instead of silently
mis-parsing.

Selectors verified against tests/fixtures/* on 2026-06-23; the bids-count and description selectors
were corrected against the live site on 2026-06-30 (the originals were synthetic-fixture-only and
silently yielded ``None`` on every real page — see ``_parse_bids_count`` / ``_parse_description``).
The real project page renders two copies of the meta block (a desktop ``#project-meta-panel`` and a
``#mobile-project-meta-panel``); we scope to the first occurrence of each label to avoid
double-counting.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from selectolax.parser import HTMLParser, Node

from ..db.models import ProjectStatus
from ..db.types import utcnow
from ..parsing.arabic import (
    normalize_text,
    parse_budget,
    parse_hiring_rate,
    parse_relative_time,
)

_PROJECT_ID_RE = re.compile(r"/project/(\d+)")
_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

# Default DOM/text markers that flag an *awarded* project. Mirrors
# ``settings_store.DEFAULTS["awarded_markers"]``; the live values are config-driven — a caller
# passes ``settings.get_json("awarded_markers")`` and we fall back to these when none is supplied.
# Kept here (with every other selector) so marker knowledge stays confined to this module.
_DEFAULT_AWARDED_MARKERS: tuple[str, ...] = ("label-prj-awarded", "تم الترسية", "مسند")


class ParseError(Exception):
    """Raised when a page lacks its expected structure (the site changed shape)."""


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------


def parse_listing(html: str) -> list[dict]:
    """Discover projects from a listing page.

    Each dict: ``{"mostaql_id", "url", "title", "client_name", "bids_count"}``. Rows whose link has
    no numeric ``/project/<id>`` are skipped (fail-closed: an unidentifiable row is no project at
    all). ``bids_count`` is the listing's offer count — the **authoritative, uncapped total**: the
    project detail page only renders the first 50 offer cards, so for heavily-bid projects the
    listing is the only place the true count appears (see ``_parse_bids_count``).
    """
    tree = HTMLParser(html)
    out: list[dict] = []
    for row in tree.css("tr.project-row"):
        link = row.css_first('h2 a[href*="/project/"]')
        if link is None:
            continue
        href = link.attributes.get("href") or ""
        m = _PROJECT_ID_RE.search(href)
        if m is None:
            continue
        title = normalize_text(link.text()) or None
        out.append(
            {
                "mostaql_id": m.group(1),
                "url": href,
                "title": title,
                "client_name": _listing_client_name(row),
                "bids_count": _listing_bids_count(row),
            }
        )
    return out


# Listing offer count: "<n> عرض/عروض" (digit forms) plus the Arabic singular/dual word forms that
# carry no digit at all ("عرض واحد" = 1, "عرضان"/"عرضين" = 2).
_BIDS_DIGIT_RE = re.compile(r"(\d+)\s*عر")


def _parse_listing_bids(text: str) -> int | None:
    t = normalize_text(text)
    m = _BIDS_DIGIT_RE.search(t)
    if m is not None:
        return int(m.group(1))
    if "عرضان" in t or "عرضين" in t:
        return 2
    if "عرض واحد" in t:
        return 1
    return None


def _listing_bids_count(row: Node) -> int | None:
    """The offer-count ``li`` under ``ul.project__meta`` -> its integer count (``None`` if absent)."""
    for ul in row.css("ul.project__meta"):
        for li in ul.css("li"):
            text = normalize_text(li.text())
            if "عرض" in text or "عرو" in text:
                n = _parse_listing_bids(text)
                if n is not None:
                    return n
    return None


def merge_bids_count(observed: int | None, existing: int | None) -> int | None:
    """Combine a freshly-observed bid count with the stored one, never downgrading.

    The detail page caps its offer cards at 50, so a re-check of a >50-bid project would otherwise
    overwrite an authoritative (uncapped) listing total with ``50``. Bids on an open project only
    grow in practice, so we keep the larger of the two (None-safe: a missing side never wins).
    """
    if observed is None:
        return existing
    if existing is None:
        return observed
    return max(observed, existing)


def _listing_client_name(row: Node) -> str | None:
    """First ``li`` bearing a fa-user icon under ``ul.project__meta`` -> its bdi text."""
    for ul in row.css("ul.project__meta"):
        for li in ul.css("li"):
            if li.css_first("i.fa-user") is None:
                continue
            bdi = li.css_first("bdi")
            text = bdi.text() if bdi is not None else li.text()
            name = normalize_text(text) or None
            if name:
                return name
    return None


# ---------------------------------------------------------------------------
# project page
# ---------------------------------------------------------------------------


def parse_project_page(html: str, awarded_markers: Sequence[str] | None = None) -> dict:
    """Parse a single project page into a flat dict (+ nested ``client``).

    ``awarded_markers`` are the config-driven DOM-class / Arabic-text markers that flag an
    *awarded* project; when ``None`` the data-model defaults (:data:`_DEFAULT_AWARDED_MARKERS`)
    are used. A settings-aware caller passes ``settings.get_json("awarded_markers")`` to honour
    runtime tuning; omitting the argument keeps every existing caller working unchanged.

    Raises :class:`ParseError` if the meta block or the client hiring-rate row is absent.
    """
    tree = HTMLParser(html)
    if awarded_markers is None:
        awarded_markers = _DEFAULT_AWARDED_MARKERS

    title_node = tree.css_first('span[data-type="page-header-title"]')
    title = normalize_text(title_node.text()) if title_node is not None else None

    meta = _collect_meta_values(tree)
    if not meta:
        raise ParseError("project page has no meta-label/value rows")

    site_status = _parse_status(meta.get("حالة المشروع"), awarded_markers)
    posted_at = _parse_posted(meta.get("تاريخ النشر"))
    budget_min, budget_max, currency = _parse_budget_node(meta.get("الميزانية"))
    skills = _parse_skills(tree, meta.get("المهارات"))

    client = _parse_client(tree)

    return {
        "title": title,
        "description": _parse_description(tree),
        "url": None,
        "category": "development",
        "skills": skills,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "currency": currency,
        "bids_count": _parse_bids_count(tree),
        "posted_at": posted_at,
        "site_status": site_status,
        "client": client,
    }


def _collect_meta_values(tree: HTMLParser) -> dict[str, Node]:
    """Map each meta label (first occurrence wins) to its sibling ``div.meta-value`` node."""
    out: dict[str, Node] = {}
    for label in tree.css("div.meta-label"):
        key = normalize_text(label.text())
        if not key or key in out:
            continue  # keep the first (desktop) copy; ignore the mobile duplicate
        value = _next_meta_value(label)
        if value is not None:
            out[key] = value
    return out


def _next_meta_value(label: Node) -> Node | None:
    node = label.next
    while node is not None:
        if getattr(node, "tag", None) == "div" and "meta-value" in (
            node.attributes.get("class") or ""
        ):
            return node
        node = node.next
    return None


def _parse_status(
    value: Node | None,
    awarded_markers: Sequence[str] = _DEFAULT_AWARDED_MARKERS,
) -> ProjectStatus:
    """Open / closed / awarded / unknown, fail-closed (constitution VII).

    Awarded is checked *first* and requires a positive marker match: an awarded project is also
    flagged closed on the site, so the award signal must win over a co-present closed marker.
    Anything that is not clearly open / closed / awarded yields ``unknown`` — never a guess.
    """
    if value is None:
        return ProjectStatus.unknown
    if _has_awarded_marker(value, awarded_markers):
        return ProjectStatus.awarded
    for bdi in value.css("bdi"):
        cls = bdi.attributes.get("class") or ""
        if "label-prj-open" in cls:
            return ProjectStatus.open
        if "label-prj-closed" in cls:
            return ProjectStatus.closed
    return ProjectStatus.unknown


def _has_awarded_marker(value: Node, awarded_markers: Sequence[str]) -> bool:
    """True iff a configured marker shows up in the status value as a class token (matched
    case-insensitively) or as Arabic text (matched via ``normalize_text`` for digit/whitespace/
    diacritic robustness). Scoped to the status value node only, so an unrelated word elsewhere
    can never spuriously flag awarded (fail-closed: no positive match => not awarded)."""
    class_blob = " ".join(
        [value.attributes.get("class") or ""]
        + [n.attributes.get("class") or "" for n in value.css("[class]")]
    ).lower()
    text_blob = normalize_text(value.text())
    for marker in awarded_markers:
        marker = (marker or "").strip()
        if not marker:
            continue
        if marker.lower() in class_blob:
            return True
        norm_marker = normalize_text(marker)
        if norm_marker and norm_marker in text_blob:
            return True
    return False


def _parse_posted(value: Node | None) -> datetime | None:
    if value is None:
        return None
    time_node = value.css_first("time")
    if time_node is not None:
        dt_attr = time_node.attributes.get("datetime")
        if dt_attr:
            try:
                return datetime.strptime(dt_attr.strip(), _DATETIME_FMT).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass
    return parse_relative_time(value.text(), utcnow())


def _parse_budget_node(value: Node | None) -> tuple[Decimal | None, Decimal | None, str | None]:
    if value is None:
        return (None, None, None)
    span = value.css_first('span[dir="rtl"]')
    text = span.text() if span is not None else value.text()
    return parse_budget(text)


def _parse_skills(tree: HTMLParser, value: Node | None) -> list[str]:
    """Skill tag texts, deduped.

    The synthetic fixture nests ``ul.skills__list`` inside the budget/skills meta-value; the real
    page renders skills in a *separate* meta-row and duplicates the whole block into a mobile panel.
    So we collect from the label's own meta-value first, then fall back to the first meta panel —
    never the whole document, which would double-count the mobile copy.
    """
    scope = value
    if scope is None or not scope.css("a.tag"):
        scope = tree.css_first("#project-meta-panel") or tree.css_first("div.meta-container")
    if scope is None:
        return []
    skills: list[str] = []
    seen: set[str] = set()
    for tag in scope.css("a.tag"):
        bdi = tag.css_first("bdi")
        text = normalize_text(bdi.text() if bdi is not None else tag.text())
        if text and text not in seen:
            seen.add(text)
            skills.append(text)
    return skills


def _parse_description(tree: HTMLParser) -> str | None:
    """The project brief.

    On the live page the brief renders inside the ``تفاصيل المشروع`` card as
    ``#project-brief > #projectDetailsTab > div.text-wrapper-div`` (verified against the live
    site 2026-06-30). The older ``div[data-type="project-details"]`` / ``div.project-brief`` /
    ``div.text-wrapper-h`` selectors were synthetic-fixture-only and never matched a real page;
    they are kept *after* the real ones as a fail-soft fallback for those fixtures.
    """
    node = (
        tree.css_first("#projectDetailsTab div.text-wrapper-div")
        or tree.css_first("#project-brief div.text-wrapper-div")
        or tree.css_first('div[data-type="project-details"]')
        or tree.css_first("div.project-brief, div.text-wrapper-h")
    )
    if node is None:
        return None
    text = normalize_text(node.text())
    return text or None


def _parse_bids_count(tree: HTMLParser) -> int | None:
    """Number of public bids/offers on the project.

    On the live page every submitted offer is a ``[data-bid-item]`` card inside
    ``#bidsCollection-panel`` — there is no count badge or "showing N of M" text. The card count
    is therefore a **lower bound**: it is exact up to 50 but the page renders at most 50 cards
    (verified against the live site 2026-06-30 — a 79-bid project shows exactly 50 cards and the
    true total appears nowhere on the page). The uncapped total only lives on the listing, so
    callers merge this with ``parse_listing``'s count via :func:`merge_bids_count`. When the panel
    is present we return the card count; ``0`` is a real value (a project with no offers yet),
    distinct from ``None`` (panel absent ⇒ unknown). The legacy ``span.count`` digit is kept as a
    fail-soft fallback for the synthetic qualifying fixture.
    """
    panel = tree.css_first("#bidsCollection-panel") or tree.css_first("#project-bids")
    if panel is not None:
        return len(panel.css("[data-bid-item]"))
    count = tree.css_first("span.count")
    if count is not None:
        digits = re.search(r"\d+", normalize_text(count.text()))
        if digits is not None:
            return int(digits.group())
    return None


def _parse_client(tree: HTMLParser) -> dict:
    widget = tree.css_first('div[data-type="employer_widget"]')
    if widget is None:
        raise ParseError("project page has no employer widget")

    name_node = widget.css_first("h5.profile__name bdi") or widget.css_first(
        "h5.profile__name"
    )
    name = normalize_text(name_node.text()) if name_node is not None else None

    member_since: str | None = None
    hiring_rate: float | None = None
    projects_open: int | None = None
    in_progress: int | None = None
    seen_hiring_row = False

    for tr in widget.css("table.table-meta tr"):
        tds = tr.css("td")
        if len(tds) < 2:
            continue
        label = normalize_text(tds[0].text())
        value_text = tds[1].text()
        if label == "تاريخ التسجيل":
            member_since = normalize_text(value_text) or None
        elif label == "معدل التوظيف":
            seen_hiring_row = True
            hiring_rate = parse_hiring_rate(value_text)
        elif label == "المشاريع المفتوحة":
            projects_open = _to_int(value_text)
        elif label == "مشاريع قيد التنفيذ":
            in_progress = _to_int(value_text)

    if not seen_hiring_row:
        raise ParseError("client widget has no hiring-rate row")

    return {
        "name": name,
        "member_since": member_since,
        "hiring_rate": hiring_rate,
        "projects_open": projects_open,
        "raw": {"in_progress": in_progress},
    }


def _to_int(text: str) -> int | None:
    m = re.search(r"\d+", normalize_text(text))
    return int(m.group()) if m is not None else None


# ---------------------------------------------------------------------------
# profile page (best-effort; may be unused this feature)
# ---------------------------------------------------------------------------


def parse_profile_page(html: str) -> dict:
    """Tolerant profile parse: ``{rating, reviews, total_spent, country, verified}``.

    Every field is optional; missing data yields ``None`` / ``False`` rather than an error.
    """
    tree = HTMLParser(html)

    rating: float | None = None
    rating_node = tree.css_first('[data-type="rating"], span.rating, .profile-rating')
    if rating_node is not None:
        m = re.search(r"\d+(?:\.\d+)?", normalize_text(rating_node.text()))
        if m is not None:
            rating = float(m.group())

    reviews: int | None = None
    reviews_node = tree.css_first('[data-type="reviews"], span.reviews-count')
    if reviews_node is not None:
        reviews = _to_int(reviews_node.text())

    total_spent: Decimal | None = None
    spent_node = tree.css_first('[data-type="total-spent"], .total-spent')
    if spent_node is not None:
        lo, hi, _ = parse_budget(spent_node.text())
        total_spent = hi or lo

    country: str | None = None
    country_node = tree.css_first('[data-type="country"], .profile-country')
    if country_node is not None:
        country = normalize_text(country_node.text()) or None

    verified = tree.css_first(
        '[data-type="verified"], .verified-badge, .fa-check-circle'
    ) is not None

    return {
        "rating": rating,
        "reviews": reviews,
        "total_spent": total_spent,
        "country": country,
        "verified": verified,
    }
