# Phase 0 Research — Analytics and Insights

All decisions below resolve the Technical Context and are grounded in the actual codebase (mapped via
exploration of `db/models.py`, `config/settings_store.py`, `qualify/`, `scoring/`, `personal/`, `api/`, and
`frontend/`). There are **no `NEEDS CLARIFICATION`** items: the five spec ambiguities were resolved in the
spec's Assumptions and are finalized here as concrete algorithms + `settings` defaults. The defining
constraint is that this feature is **read-only** — every decision below preserves "compute from existing
rows, write nothing back."

---

## R1. Read-only aggregation — no new table, no migration

**Decision**: Compute every chart and tip **at read time** from existing rows. Add **no table** and **no
Alembic migration**; the Alembic head is unchanged. The only new persisted state is additive `settings` rows
(R7). Aggregation runs in plain Python over rows pulled by indexed `SELECT`s; medians/percentiles use the
stdlib `statistics` module (no pandas/numpy).

**Rationale**: The spec is explicit (FR-006, FR-036, Constitution IV): the analytics section must not be a
new source of truth and must change nothing. Personal scale makes read-time computation trivially fast
(low-thousands of projects; tens-of-thousands of snapshots total → an O(rows) pass is sub-second), so there
is no need for a materialized summary table that would have to be kept in sync (and would itself be new state
to back up). Existing indexes already cover every query: `projects.posted_at/scraped_at/qualified_at/
eval_status`, `project_snapshots(project_id, captured_at)`, `project_scores.score`, and
`personal_records.status/favorite`.

**Alternatives considered**: (a) **Materialized `analytics_*` summary tables** refreshed by a job — rejected:
new state to migrate/back up and keep consistent, for a sub-second computation; contradicts "introduce no
history of its own." (b) **SQL `GROUP BY` with SQLite date functions** for the time buckets — rejected: SQLite
has no timezone-aware date extraction, so day/hour bucketing in the analytics tz cannot be done correctly in
SQL; Python `zoneinfo` bucketing is the project's established pattern (R2). (c) A **caching layer** — rejected
as premature; react-query already caches client-side and the endpoint is cheap.

---

## R2. Timezone bucketing — generalize the existing owner-tz helper

**Decision**: A new `analytics/timezone.py` centralizes tz handling. `analytics_tz(session) -> ZoneInfo`
reads the new `analytics_timezone` setting; **when it is empty (the default), it falls back to
`owner_timezone`**, and an invalid value falls back to `Africa/Cairo` — exactly the resolution logic already
in `personal/stats.py::today_start_utc` and `api/routers/home.py::_today_start_utc`. It exposes:
`local_parts(dt_utc) -> (weekday_idx, hour, local_date)` (convert a stored UTC `datetime` to the analytics tz,
then read weekday/hour/date — DST-correct because `zoneinfo` applies the offset for that instant);
`day_key`/`iso_week_key` for volume bucketing; and `window_bounds(date_from, date_to) -> (utc_start,
utc_end)` which turns an inclusive ISO **local-calendar** date range into a half-open `[utc_start, utc_end)`
UTC range (`local_midnight(date_from)` → `local_midnight(date_to + 1 day)`), so day-boundary and DST cases
are handled once, in one place.

**Weekday convention**: the heatmap weekday index is **0 = Saturday … 6 = Friday** (the Arabic calendar week
order), computed as `(python_weekday + 2) % 7`. The DTO also carries the Arabic day label so the frontend
renders without re-deriving the mapping.

**Rationale**: Reusing the proven resolution logic (UTC storage → `ZoneInfo` → bucket) keeps Feature 6
consistent with the rest of the app and gets DST correctness for free (`zoneinfo` knows the offset at each
instant, so a project posted at 23:30 local near a DST change lands in the right local day/hour). Centralizing
it removes the existing copy-paste and gives a single tested seam for every time-of-day view.

**Note on the existing duplication**: the two copy-pasted `today_start_utc` bodies are left untouched
(behaviour-preserving); de-duping them onto the new helper is an optional later cleanup, deliberately out of
scope to keep this feature read-only and low-risk.

**Alternatives considered**: bucketing in the browser from raw UTC timestamps — rejected: would ship every
raw row to the client and re-implement tz logic in TS, and the "configured analytics timezone" is a
server-side setting. Storing a per-row local hour — rejected: denormalized state that breaks the moment the tz
setting changes.

---

## R3. The seven aggregates (the heart of the feature)

**Decision**: `analytics/aggregates.py` exposes one total function per view; each takes `(session, settings,
*, utc_start, utc_end, now)` and returns a small dataclass carrying its data **plus an `enough_data: bool`**
and the support counts behind it. All are **total** (handle `None`/empty/one-sided inputs without raising).
"Qualified" everywhere means `Project.eval_status == EvalStatus.qualified`.

1. **`posting_heatmap`** — qualified projects with `posted_at` (fallback `scraped_at`) in window; for each,
   `local_parts → (weekday, hour)`; count per `(weekday, hour)` into a 7×24 grid. `enough_data = total ≥
   analytics_min_support`. Also returns the peak cell(s) for the tip.
2. **`volume_trends`** — bucket projects by local day **and** by ISO week of `posted_at` (fallback
   `scraped_at`); per bucket emit `{period, total, qualified}` (total = all `eval_status`; qualified =
   `qualified`). Carries a `category` label (the configured `category_slug`, today only `development`) and is
   shaped as a list so more categories slot in later. `enough_data = ≥ 2 non-empty buckets`.
3. **`budget_distribution`** — for qualified projects, the USD basis from `qualify.filters.budget_usd`
   (already honours `budget_comparison_basis`, one-sided budgets, and the currency table); bucket into USD
   bands; projects with **no** usable budget go to a labelled `unknown` band (counted, never dropped). Tier
   split from `project.tier` (1/2). `enough_data = qualified-with-budget ≥ analytics_min_support`.
4. **`competition_dynamics`** — three outputs from the snapshot trajectory:
   - **bids-vs-age curve**: for each snapshot, `age_hours = captured_at − posted_at` (fallback
     `scraped_at`); bucket ages into bands; per band report `median`, `p25`, `p75`, `n` bids (robust to
     outliers via median/IQR, never mean alone).
   - **"crowded" headline**: the first age band whose median bids ≥ `analytics_crowded_bids` → "a typical
     project passes N bids in about X hours"; if it never crosses, say so.
   - **bidding-by-hour**: from consecutive snapshots **per project**, `delta = max(0, bids[i] − bids[i−1])`
     attributed to the analytics-tz hour of `captured_at[i]`; sum deltas per hour → 24-length array (an
     approximation bounded by the re-check cadence; documented as a relative pattern, not an exact bid log).
   - `enough_data = projects with ≥ 2 snapshots ≥ a small floor AND total snapshots ≥ analytics_min_support`;
     a single-snapshot project contributes to the curve where it can but not to velocity/by-hour.
5. **`outcome_analytics`** — over qualified projects whose `project_scores.outcome ∈ {hired,
   closed_no_hire}` (concluded), the hired/no-hire counts + shares (open excluded; `unknown` reported
   separately, never folded into hired). Time-to-close `= closed_observed_at − posted_at` (fallback
   `scraped_at`), reported as **mean and median** (+ p25/p75). Missed opportunities = `outcome == hired` AND
   the owner never applied (no `personal_records` row, **or** `personal.applied_at IS NULL`) → count + a small
   list (id, title, url, budget). `enough_data = concluded ≥ analytics_min_support` (the missed list renders
   even at 0).
6. **`funnel`** — see R4.

**Rationale**: Each view is a closed-form, dependency-free pass that **reuses** the module that owns the
underlying rule (`budget_usd`/`tier`, the `Outcome` enum, the personal status ordering) rather than
re-deriving it, so an aggregate can never disagree with the feed/detail. Returning `enough_data` + support on
every result is what makes the honest "not enough data yet" state (FR-005) and the tip min-support gate
(FR-025) mechanical rather than ad-hoc.

**Alternatives considered**: computing bidding-by-hour from absolute bid counts at a snapshot's hour (instead
of deltas) — rejected: that measures *cumulative* bids, not *activity*; deltas attribute new bids to when they
appeared. A mean-only "average bids by age" curve — rejected: outliers (a viral project) distort the mean, so
the spec requires a median + spread (FR-032).

---

## R4. The funnel — a monotonic, honest conversion model

**Decision**: `funnel` reads the **configured ordered** `personal_statuses` list (via `personal/statuses.py`)
to rank statuses, and reports five stages over the **seen** base: **seen → favourited → applied → in
discussion → won**. "Seen" = qualified projects surfaced to the owner in the window (`eval_status ==
qualified`, by `qualified_at` fallback `scraped_at`). The stages are made **monotonic by construction** —
`count(stageₖ) =` number of seen projects whose furthest progress reached at least stageₖ, where reaching a
later stage **implies** the earlier interest stage:

- **favourited** = `favorite == True` **OR** the record reached `applied`/`in_discussion`/`won` (a project the
  owner applied to was de-facto interested even if the star was never clicked);
- **applied** = `applied_at IS NOT NULL` **OR** status rank ≥ rank(`applied`);
- **in discussion** = status rank ≥ rank(`in_discussion`);
- **won** = status == `won`.

This guarantees `seen ≥ favourited ≥ applied ≥ discussion ≥ won`, so step conversion rates
(`stageₖ / stageₖ₋₁`) are always in `[0, 1]` and a zero denominator yields **`null` (unavailable)**, never a
divide-by-zero (FR-023).

**Lags** are best-effort from the timestamps that actually exist: the **applied lag** (`applied_at − seen
time`, median) is reported; the **favourited / discussion / won** step lags are reported as **unavailable** —
`favorite` has no timestamp and only the single `status_changed_at` (latest change) is retained, so isolating
those transition times would be fabrication (FR-022). `enough_data = seen ≥ analytics_min_support`.

**Rationale**: A naïve "independent milestone counts" funnel can show >100% step conversions (more applied
than favourited, since favouriting is optional), which reads as a bug; the monotonic model is the honest,
conventional funnel and matches "conversion rate from the previous step." Reusing the configured status order
(not a hard-coded list) keeps it correct if the owner customizes `personal_statuses` (Config Over Code).

**Alternatives considered**: independent per-stage counts with rates vs `seen` — rejected (confusing >100%
step rates, and the user explicitly asked for step-over-step). Fabricating per-stage transition timestamps
from `status_changed_at` — rejected (false precision; the constitution's fail-loud honesty forbids inventing
data).

---

## R5. The tips engine — rules over the owner's own data, min-support gated

**Decision**: `analytics/tips.py::generate_tips(aggregates, settings, *, session)` is a **pure rule set** —
no external service, no model call (FR-029). Each rule inspects an already-computed aggregate and emits at
most one `Tip(key, text_ar, evidence)` **only** when its support clears the relevant threshold; tips are
ranked and truncated to `analytics_max_tips`. The rules:

| Key | Fires when (support gate) | Statement (plain Arabic) |
|---|---|---|
| `peak_window` | heatmap `enough_data` (qualified ≥ `analytics_min_support`) | the peak weekday(s)/hour(s) qualified projects appear → when to be ready |
| `bid_speed` | competition `enough_data` | median age at which bids pass `analytics_early_bids` → "bid within ~X hours" |
| `win_timing` | wins ≥ `analytics_min_wins_support` | the applied-lag of wins is shorter than overall → wins skew toward early application |
| `score_threshold` | wins ≥ `analytics_min_wins_support` and wins are scored | a **suggested** score cut-off T retaining ≥ `analytics_suggested_threshold_keep` of past wins while excluding the most non-win qualified projects (advisory; sets/sends nothing) |
| `budget_fallback` | `load_policy().active_floor == budget_fallback_floor` AND Tier-1 qualified count over `fallback_window_hours` < `fallback_target` | Tier-1 supply has been low, so the floor is relaxed to the fallback level |

The **suggested-threshold** rule replays past wins against candidate cut-offs (each distinct win score,
descending) and picks the highest T such that `wins_with_score≥T / total_wins ≥ keep_fraction`, reporting T,
the wins retained, and the share of other qualified projects it would have excluded. The **budget-fallback**
rule reads the live policy state (`qualify.budget_policy.load_policy`) plus the recent Tier-1 count — it does
**not** claim a precise duration the system never recorded (no floor-change history exists), so it states the
honest condition (low Tier-1 supply → relaxed floor) rather than "for N days."

**Rationale**: Rules over the owner's own aggregates are deterministic, explainable, and constitution-clean
(no opaque/external behaviour, no AI service). Gating each tip on a configurable support count is the
mechanical embodiment of "honest under thin data" (FR-025): below support, the tip simply isn't in the list.
Reusing the budget-policy module for the fallback tip avoids re-deriving the hysteresis rule.

**Alternatives considered**: an LLM/external summarizer over the data — **explicitly forbidden** by the spec
(FR-029) and the constitution. A fixed precise "floor relaxed for N days" claim — rejected: unsupported by
stored data; the honest condition-based phrasing is used instead.

---

## R6. One read-only endpoint vs many

**Decision**: A single **`GET /api/analytics/overview`** in a new `api/routers/analytics.py`, mounted
auth-gated (`dependencies=[Depends(require_auth)]`) like every other router. It accepts `date_from: date |
None` and `date_to: date | None` (ISO `YYYY-MM-DD`, interpreted as analytics-tz calendar days; default = the
last `analytics_default_range_days`) and returns **every section + the tips in one response**, each section
carrying its own `enough_data` flag and the resolved `range` + `timezone`. It calls
`analytics/service.py::compute_overview`, which computes the aggregates once and feeds them to the tips engine
(so a tip and its chart always agree). The seven aggregate functions remain **independently unit-testable**
without HTTP — the endpoint only composes them.

**Rationale**: The dashboard analytics section is one page under one shared date filter (US7), so one request
that returns everything is the simplest correct mapping — it computes each aggregate once (the tips reuse
them, no double work), keeps the date-range/timezone resolution in one place, and avoids seven near-identical
handlers. FastAPI auto-parses a `date`-typed query param from ISO-8601, so no custom parsing is needed (the
codebase has no prior `from`/`to` precedent — only the int `posted_within_hours` — so introducing typed-`date`
params is clean and idiomatic). Aggregates are total functions, so a sparse section returns its
`enough_data=false` state rather than failing the response.

**Alternatives considered**: seven per-section endpoints — rejected: more surface and seven date-range
parsers for a single-page section; the per-aggregate unit tests already give independent testability. A
POST/body API — rejected: this is a pure read; GET with query params is correct and cacheable by react-query.

---

## R7. Settings — the only new state

**Decision**: Add the following additive keys to `config/settings_store.py::DEFAULTS` (format `key: (default,
"type")`), seeded idempotently by `seed_defaults`. The numeric ones are registered in
`api/settings_spec.py::EDITABLE_SETTINGS` as `SettingSpec(key, type, min, max, label_ar)` so they appear in a
new **"التحليلات"** group on the settings form; the timezone string follows the `owner_timezone` precedent
(DB-editable, not a numeric form field).

| Key | Default | Type | Editable | Notes |
|---|---|---|---|---|
| `analytics_timezone` | `""` | str | DB (like `owner_timezone`) | Empty ⇒ follow `owner_timezone`; invalid ⇒ Africa/Cairo |
| `analytics_default_range_days` | `90` | int | yes (≥1) | Default date window when none supplied |
| `analytics_min_support` | `30` | int | yes (≥1) | Generic minimum record count before a section/tip is "enough" |
| `analytics_min_wins_support` | `5` | int | yes (≥1) | Minimum wins before win-timing / suggested-threshold tips appear |
| `analytics_crowded_bids` | `15` | int | yes (≥1) | Bid level the "gets crowded" headline refers to |
| `analytics_early_bids` | `5` | int | yes (≥1) | Small/early bid level the "how fast to bid" tip refers to |
| `analytics_max_tips` | `6` | int | yes (1–20) | Cap on tips shown |
| `analytics_suggested_threshold_keep` | `0.9` | float | yes (0–1) | Fraction of past wins the suggested score threshold must retain |

**No re-score trigger**: the `settings.py` PUT handler re-scores only when a `score_*` key changes; analytics
values are read fresh on every query, so **changing an analytics setting needs no recompute** — it simply
takes effect on the next refresh (FR-030). The `score_*` branch is left untouched. App-state (`app_state`) is
not used by this feature.

**Rationale**: Reuses the existing validated settings pipeline (typed getters, `seed_defaults`, per-field
422s) with zero new machinery. Defaulting `analytics_timezone` to empty-means-follow-`owner_timezone`
delivers "the analytics tz defaults to the owner timezone" (spec Assumptions) without coupling the two
settings.

**Alternatives considered**: per-tip min-support keys for every rule — rejected as over-configuration; one
generic `analytics_min_support` plus a wins-specific one covers the real unit differences (counts vs the rare
win events). Adding a `"str"`/select spec type so the tz is form-editable — deferred (optional polish);
`owner_timezone` itself isn't form-editable today, so matching that precedent keeps scope tight.

---

## R8. Frontend — no new dependency

**Decision**: Build the analytics page and all charts with **no new library**, mirroring the existing
dependency-free `lifecycle/BidChart.tsx` (inline SVG, `viewBox`, Tailwind-token colours via `currentColor`,
`Math.max(1, …)`/`|| 1` divide-by-zero guards, `data-testid` empty states):

- **Heatmap** = a 7×24 **CSS grid** of cells whose background opacity scales with the count (RTL-aware; Arabic
  day rows, hour columns).
- **Volume / competition** = inline **SVG** (bars + a median line with an IQR band + a "crowded" marker),
  exactly like `BidChart` (which already flips its x-axis for RTL).
- **Budget** = CSS/SVG horizontal bars + a Tier-1/Tier-2 split bar.
- **Funnel** = CSS horizontal bars per stage with the conversion % and lag (or "غير متاح").
- **Tips / outcomes / missed list** = plain RTL lists/cards (`ui/card`, `Bidi`, `StatCard`).
- **Date-range control** = presets via `ui/select`/`toggle-group` (آخر ٧/٣٠/٩٠ يومًا) + custom
  `ui/input[type="date"]`, with the range held in the URL (the `useProjects` `useSearchParams` idiom). **No
  date-picker library** is added.

Data flows through one `useAnalytics` hook (`useQuery(["analytics", params], …, { placeholderData:
keepPrevious })`) and one `getAnalyticsOverview` wrapper (`apiFetch` + `buildQuery`). New formatters in
`lib/format.ts`: a tz-aware **date-only** formatter and a **percent** formatter (today `format.ts` has number,
budget, relative, and a tz-aware date-time formatter, but no date-only/percent). The page uses the existing
**Loading / ErrorState / EmptyState** ladder from `app/projects/page.tsx`, distinguishing "filtered range has
no data" from "not enough data yet."

**Rationale**: The data is tiny and the visuals are simple (a grid, a few bars, one line) on a Next 16 / React
19 / Tailwind v4 / Base UI stack where heavy chart libs (recharts/visx) add bundle weight and React-19
peer-dependency friction for no benefit — exactly the reasoning Feature 4 used for `BidChart`. RTL and Arabic
are already global (`<html dir="rtl" lang="ar">`, Cairo font, `ar-EG` `Intl`), so the charts inherit
correctness.

**Frontend caveat (AGENTS.md)**: this is **not** stock Next.js — before writing the page/route, read
`frontend/node_modules/next/dist/docs/` (e.g. `proxy.ts` not `middleware.ts`, Tailwind v4 CSS config, Base UI
primitives) as `frontend/AGENTS.md` mandates; new routes are auto-protected by `proxy.ts`.

**Alternatives considered**: `recharts`/`visx`/`d3` for the heatmap and curves — rejected (large dependency,
React-19 caveats, overkill for personal-scale data). `react-day-picker` for the date filter — rejected
(native `input[type=date]` + presets suffice and add nothing to the bundle).

---

## R9. Testing strategy

**Decision**: Unit-test each aggregate and the tips engine as **pure functions** over in-memory golden rows
(the `tests/unit` pattern of `qualify`/`scoring`), with `now`/settings injected: heatmap bucketing incl. a
day-boundary and a DST instant; volume by-day/by-week; budget with missing/one-sided budgets and the Tier
split; the competition median curve + the "crowded" headline + by-hour deltas + a single-snapshot project; the
outcome shares excluding open and the mean/median time-to-close and the missed-opportunity join; the funnel's
monotonic counts, a zero-denominator step, and lag-unavailable; and each tip rule above vs below support, the
suggested-threshold replay, and the budget-fallback rule. API-test `GET /api/analytics/overview` with the
`api_env` fixture + the `make_project`/`make_project_score`/`make_project_snapshot`/`make_trajectory`/
`make_personal_record` factories: auth gating, date-range scoping, per-section `enough_data`, and a
**read-only assertion** — snapshot the project/score/snapshot/personal tables before and after the call and
assert they are unchanged. Frontend Vitest covers the charts' render + empty states + date-filter wiring.

**Rationale**: Keeping the aggregates pure makes the bulk of the feature testable without a database or HTTP,
mirroring the project's existing seam for `qualify`/`scoring`. The read-only assertion turns Constitution IV
into an executable gate rather than a promise.

**Alternatives considered**: only end-to-end API tests — rejected (slower, and wouldn't isolate the bucketing
/ robust-stat logic that is the actual risk surface).

---

## Summary of decisions (no NEEDS CLARIFICATION remain)

1. Read-only, compute-at-read-time; **no table, no migration** (R1).
2. Analytics-tz bucketing centralized in `analytics/timezone.py`, DST-correct, defaulting to `owner_timezone`
   (R2).
3. Seven total aggregate functions, each returning `enough_data` + support (R3); the funnel is monotonic and
   honest about unavailable lags (R4).
4. A pure, min-support-gated, no-external-AI tips engine; the suggested threshold is advisory; the
   budget-fallback tip reads live policy state without claiming a false duration (R5).
5. One auth-gated read-only endpoint `GET /api/analytics/overview` composing the aggregates once (R6).
6. ~8 additive `settings` keys; no recompute on change (R7).
7. No new frontend dependency — bespoke inline-SVG/CSS charts + native date inputs (R8).
8. Pure-function unit tests + an API read-only assertion (R9).
