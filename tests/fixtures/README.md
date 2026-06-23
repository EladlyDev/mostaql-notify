# Test fixtures

Golden HTML captured from mostaql.com on **2026-06-23** (real) plus synthetic edge-cases.

| File | Source | Notes |
|---|---|---|
| `listing.html` | `GET /projects/development` | real; 25 `tr.project-row`; links `a[href*="/project/"]` → absolute `/project/{id}` |
| `project_page.html` | `GET /project/1252460` | **real**; budget `$25.00-$50.00`, status `مفتوح` (open), hiring rate **`لم يحسب بعد`** (a real not-yet-calculated case ⇒ disqualified) |
| `project_qualifying.html` | synthetic | structurally faithful; budget `$300-$500`, open, hiring rate `75.00%` ⇒ Tier-1 qualifying |
| `client_not_calculated.html` | synthetic | minimal `table.table-meta` with `لم يحسب بعد` for focused unit tests |
| `challenge.html` | synthetic | Cloudflare "Just a moment" interstitial for block-detection tests |

## Pinned selectors (verified against the real fixtures)

**Listing** (`listing.html`) — discovery only:
- rows: `tr.project-row` (25/page); project link: `a[href*="/project/"]` → absolute `https://mostaql.com/project/{id}` (extract numeric id); client name: `.project__meta bdi`.

**Project page** (`project_page.html`) — single source of truth for hard filters:
- title: `span[data-type="page-header-title"]`
- meta pairs: `div.meta-label` (Arabic label) + sibling `div.meta-value`:
  - `حالة المشروع` (status) → `bdi.label-prj-open` = open (`label-prj-closed`/absent → closed/unknown)
  - `تاريخ النشر` (posted) → `<time datetime="YYYY-MM-DD HH:MM:SS">` — **this attribute is UTC**; parse it (not the relative "منذ …" text)
  - `الميزانية` (budget) → `span[dir="rtl"]` text e.g. `$25.00 - $50.00`
  - `المهارات` (skills) → tag links
- client sidebar: `div[data-type="employer_widget"]` → name `h5.profile__name bdi`; `table.table-meta` rows `<tr><td>label</td><td>value</td></tr>`:
  - `تاريخ التسجيل` (member_since) → `<time>`
  - `معدل التوظيف` (hiring rate) → `label.label-rating-*` text (a `%` **or** `لم يحسب بعد`)
  - `المشاريع المفتوحة`, `مشاريع قيد التنفيذ`, `التواصلات الجارية` → integer cells

## Reality finding (drives the design)

The project page exposes the client's hiring rate + stats **inline** but has **no `/u/` profile link and no client id**. Therefore:
- qualification reads the hiring rate from the **project page** (one fetch ⇒ project + client; more polite);
- `Client.mostaql_id` is a derived surrogate (`derived:<sha1(name|member_since)>`, see `db/models.derive_client_key`);
- a separate `/u/` profile fetch / 12 h cache is **not reachable** in this feature and is reserved for later (the `client_refresh_hours` setting governs that future path).
