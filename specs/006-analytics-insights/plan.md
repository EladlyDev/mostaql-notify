# Implementation Plan: Analytics and Insights

**Branch**: `006-analytics-insights` | **Date**: 2026-06-30 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-analytics-insights/spec.md`

## Summary

Feature 6 is the **reading** half of the system: it aggregates the history Features 1–4 already gathered
(projects, scores, the append-only per-project snapshot trajectory, recorded outcomes, and the personal
pipeline) into a dashboard **analytics section** — seven views and a handful of rule-based, plain-language
tips — answering *when qualified projects appear, how fast competition builds, what became of the projects
the owner saw (and which good ones were missed), and how the owner's own funnel converts*. It is **strictly
read-only**: it scrapes nothing, takes no action on mostaql.com, and **writes nothing back** to any project,
client, score, snapshot, outcome, or personal record. The only new persisted state is its **configuration**
(an analytics timezone plus a few tip thresholds), so — unlike Feature 4 — it ships **no database migration
and no new table**.

**Technical approach** (extends Features 1–4 with no rewrites and no new dependency). A new **surface-agnostic
analytics package** (`src/mostaql_notifier/analytics/`, mirroring `scoring/` and `personal/`) holds total,
side-effect-free aggregation functions — `posting_heatmap`, `volume_trends`, `budget_distribution`,
`competition_dynamics`, `outcome_analytics`, `funnel` — plus a rule-based `tips` engine and a thin `service`
that composes them. Every time-of-day analysis is bucketed **in Python** in a **configured analytics
timezone** (`zoneinfo`, DST-correct), reusing the established UTC-store → owner-tz-bucket pattern already in
`personal/stats.py::today_start_utc` (generalized here into `analytics/timezone.py`, defaulting the analytics
tz to `owner_timezone`). The aggregates **reuse** existing helpers — `qualify.filters.budget_usd`/`tier`
(budget distribution), `qualify.budget_policy.load_policy` (the "Tier-1 supply low" tip), the configured
ordered `personal_statuses` and the `personal/stats.py` engaged-stage logic (funnel), and the `Outcome` enum
on `project_scores` (outcome analytics) — so no aggregation re-derives a rule another module owns. A single
read-only endpoint **`GET /api/analytics/overview`** (new `api/routers/analytics.py`, auth-gated like every
other router) accepts an ISO `date_from`/`date_to` window and returns every section + the tips in one
response, each section carrying its own **`enough_data`** flag so the UI degrades to an honest "not enough
data yet" state under thin history. The **Next.js** frontend adds an `/analytics` page and a set of
**dependency-free inline-SVG/CSS** charts (a 7×24 heatmap, volume/budget/competition charts, a funnel, an
outcomes panel, a tips list) built in the exact style of the existing `lifecycle/BidChart.tsx`, plus a
date-range control (no charting or date-picker library is added). All new tunables — the analytics timezone,
the default range, the tip minimum-support thresholds, and the "crowded"/"early" bid levels — are additive
`settings` rows (config over code); the numeric ones are registered in `settings_spec.py` and gain an Arabic
**"التحليلات"** group on the settings form. Because analytics values are read at query time, **no
settings change triggers any recompute** (the `score_*` re-score branch in `settings.py` is untouched).

## Technical Context

**Language/Version**: Python 3.11+ (backend, same venv/package as worker + bot); TypeScript / Node 20+ (frontend)
**Primary Dependencies**: Backend — FastAPI + Uvicorn, SQLAlchemy 2 (existing models/session), `zoneinfo` (stdlib, for analytics-tz bucketing), pydantic-settings, the existing `SettingsStore`. **No new backend dependency** (no pandas/numpy — aggregation is plain Python over personal-scale data; medians/percentiles use `statistics`). Frontend — Next.js 16, React 19, Tailwind v4, Base UI (`@base-ui/react`), TanStack Query, lucide. **No new frontend dependency** — every chart is bespoke inline SVG/CSS (heatmap = CSS grid; volume/competition = inline SVG like `BidChart`), and the date-range control is built from the existing `ui/input` + `ui/select`/`toggle-group` (no charting lib, no date-picker lib; see research R8).
**Storage**: Existing SQLite (`sqlite:///./data/mostaql.db`, WAL) — **read-only**. **No new table and no Alembic migration**; the Alembic head is unchanged. The only new persisted state is additive `settings` rows (analytics timezone + thresholds) seeded by `seed_defaults`. Existing indexes (`projects.posted_at/scraped_at/qualified_at/eval_status`, `project_snapshots(project_id, captured_at)`, `project_scores.score`, `personal_records.status/favorite`) already cover every aggregation query.
**Testing**: Backend — pytest. Pure-function unit tests for each aggregate (`analytics/aggregates.py`) with injected `now`/settings and golden in-memory rows (heatmap bucketing incl. day-boundary + DST, volume by-day/by-week, budget incl. missing/one-sided + Tier-1/2 split, competition median curve + "crowded" headline + by-hour deltas + single-snapshot degrade, outcome shares excluding open + mean/median time-to-close + missed-opportunity join, funnel monotonic counts + zero-denominator + lag-unavailable), the timezone bucketer (`analytics/timezone.py`), and the tips engine (`analytics/tips.py`: each rule fires above support, is withheld below it, the suggested-threshold replay, the budget-fallback rule from policy state, the max-cap/ranking, and "no external service" by construction). API — FastAPI `TestClient` (`api_env` + the `make_project`/`make_project_score`/`make_project_snapshot`/`make_trajectory`/`make_personal_record` factories) for `GET /api/analytics/overview`: auth gating, date-range scoping, the per-section `enough_data` flag, and a **read-only assertion** (snapshot the project/score/snapshot/personal tables before and after the call and assert byte-for-byte unchanged). Frontend — Vitest + Testing Library (heatmap/volume/competition/funnel render, the "not enough data yet" states, the date-range filter wiring, RTL labels).
**Target Platform**: Localhost (laptop/phone on LAN); portable to a single always-on VPS via redeploy (Constitution X). Same four cooperating processes (worker, bot, API, frontend) over one SQLite file — this feature adds **no new process** (it is API routes + a frontend page).
**Project Type**: Web application (FastAPI API + Next.js SPA) over the existing async worker package and inbound bot. This feature lives entirely in the API + frontend tiers and a new pure analytics package; the worker and bot are untouched.
**Performance Goals**: Every aggregate is an O(rows) in-memory pass at personal scale (low-thousands of projects; tens-of-thousands of snapshots total) and completes well under a second, so the overview endpoint answers a date-range change on the next refresh with no caching layer needed. Time-of-day bucketing is per-row `zoneinfo` conversion (DST-correct) in Python — the codebase already buckets owner-tz day boundaries this way. No new index is required.
**Constraints**: Strictly read-only — no write to any project/client/score/snapshot/outcome/personal row, no scraping, no mostaql action (IV, VIII); honest under thin data — every section returns an `enough_data` flag and every tip is withheld below its configurable minimum support, never a misleading conclusion (VI, VII); unknown outcomes are never counted as hires (VII); all tunables read from `settings` (III); every time bucket is in the configured analytics timezone with correct day-boundary/DST handling, all surfaces render RTL, and Arabic-Indic/unknown-vs-zero conventions of the already-parsed data are preserved (V); the analytics section sits behind the existing single-owner auth with no new public surface (IX); tips are rules over the owner's own data only — no external AI service (FR-029, VIII).
**Scale/Scope**: One owner; one new read-only HTTP endpoint (`GET /api/analytics/overview`); one new pure backend package (5 modules); ~8 new `settings` keys (1 tz string + 7 numeric thresholds); one new frontend page + ~8 dependency-free chart/control components + one new hook; **zero** new tables, migrations, processes, bot commands, or runtime dependencies.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* **Verdict: PASS** (initial; re-checked after Phase 1 — still PASS). No violations; Complexity Tracking intentionally empty. Several scraping-/write-oriented gates are satisfied **by construction** because this feature performs no network access and no writes to existing data.

- [x] **I. Personal & Single-Box** — PASS. No accounts/roles/tenancy. The analytics section is one more area of the single-owner dashboard behind the existing password gate; it adds no new user class, no new public surface, and no new process.
- [x] **II. Polite, Non-Aggressive Access** — PASS (N/A by construction). This feature makes **no request to mostaql.com at all** — it reads only the local database. There is nothing to rate-limit, back off, or be blocked by (FR-006).
- [x] **III. Config Over Code** — PASS. The analytics timezone, the default date range, the tip minimum-support thresholds, the "crowded" and "early" bid levels, the max-tips cap, and the suggested-threshold keep-fraction are all additive `settings` rows read at runtime; no behaviour-affecting literal is hard-coded (FR-002, FR-014, FR-025, FR-030).
- [x] **IV. Idempotent Ingestion & Non-Destructive History** — PASS. The section is **strictly read-only**: every aggregate is a `SELECT`-and-compute with no `INSERT`/`UPDATE`/`DELETE` to any project, client, score, snapshot, outcome, or personal row. It introduces no new history of its own (aggregates are derived at read time); the only writes anywhere are the one-time `seed_defaults` insert of the new `settings` rows. A read-only assertion (tables unchanged before/after the endpoint call) is a test gate (FR-006, FR-036).
- [x] **V. Arabic-First Correctness** — PASS. RTL is global (`<html dir="rtl" lang="ar">`); all labels/numbers use the existing `ar-EG`/`ar` `Intl` formatters; every time bucket converts UTC → the configured analytics tz via `zoneinfo` with correct day-boundary/DST handling; the already-parsed source data preserves Arabic-Indic digits and the unknown-vs-zero distinction (an unknown bid count / hiring rate is never treated as 0 in an aggregate) (FR-031, FR-033, FR-034).
- [x] **VI. Fail Loud / Honest Under Thin Data** — PASS. Every section returns an explicit `enough_data` flag and renders a clear "not enough data yet" state below it, and every tip is withheld until its supporting aggregate clears the configured minimum support — so the section never shows a confident-looking but unsupported number (FR-005, FR-025, FR-032). (Background-loop alerting is N/A — this feature runs no loop.)
- [x] **VII. Conservative, Fail-Closed Qualification** — PASS. Outcome analytics count **hired** only from a recorded `Outcome.hired`; **unknown** endings are shown honestly and never folded into hires; still-open projects are excluded from outcome shares; tips never overreach beyond their support (FR-017, FR-020, FR-025).
- [x] **VIII. No Platform Automation** — PASS. No bid/message/submit/write on mostaql.com and no scrape. The strongest output, the **suggested score threshold**, is advisory only — it sets nothing, gates nothing, and sends nothing (FR-006, FR-027).
- [x] **IX. Local Security Hygiene** — PASS. `GET /api/analytics/overview` is mounted with `dependencies=[Depends(require_auth)]` exactly like every other dashboard router; the `/analytics` page is behind the same session gate. No new public surface, no uploads, no new secret (FR-035).
- [x] **X. Deployment-Portable** — PASS. The only new state is additive `settings` rows in the portable, restorable `./data` volume; no hostname/abspath/OS assumption; no new table to migrate; SQLite→Postgres stays config + restore (FR-030, FR-036).

**Result**: All gates Pass. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/006-analytics-insights/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output — design decisions (read-only aggregation, tz bucketing, each aggregate, tips, no-migration)
├── data-model.md        # Phase 1 output — NO new tables; new settings; derived aggregate + DTO shapes; query/index reuse
├── quickstart.md        # Phase 1 output — open the analytics section, tune thresholds, verify read-only locally
├── contracts/
│   ├── openapi.yaml             # Phase 1 — GET /api/analytics/overview request + full response schema (auth, date range, enough_data)
│   └── analytics-aggregates.md  # Phase 1 — the aggregation contract: each view's inputs, bucketing, robust stats, and every tip rule + its min-support gate
└── checklists/
    └── requirements.md          # From /speckit.specify
```

### Source Code (repository root)

```text
src/mostaql_notifier/
├── analytics/                # NEW — surface-agnostic, read-only aggregation (mirrors scoring/ and personal/)
│   ├── __init__.py
│   ├── timezone.py           # resolve analytics tz (analytics_timezone → owner_timezone → Africa/Cairo, zoneinfo);
│   │                         #   UTC→local helpers: local_parts(dt)->(weekday,hour,date), day/iso-week keys,
│   │                         #   and date-range (ISO local dates) → [utc_start, utc_end) bounds (DST-correct)
│   ├── aggregates.py         # PURE/total functions over (session, settings, window): posting_heatmap,
│   │                         #   volume_trends (day+week, category dim), budget_distribution (+Tier1/2, missing/one-sided),
│   │                         #   competition_dynamics (bids-vs-age median curve + "crowded" headline + bidding-by-hour),
│   │                         #   outcome_analytics (hired/no-hire shares, mean+median time-to-close, missed list),
│   │                         #   funnel (monotonic seen→fav→applied→discussion→won + rates + best-effort lags);
│   │                         #   each returns a dataclass carrying enough_data + support counts
│   ├── tips.py               # PURE — rule set over the aggregates; each Tip(key, text_ar, evidence) emitted ONLY
│   │                         #   above its configurable min-support; suggested-threshold replay; budget-fallback
│   │                         #   from budget_policy state; ranked + capped at analytics_max_tips (no external service)
│   └── service.py            # compute_overview(session, settings, *, date_from, date_to, now) — composes all
│                             #   aggregates once and feeds tips; the single entry the API router calls
├── api/
│   ├── schemas.py            # EXTEND — AnalyticsOverview + per-section DTOs (HeatmapCell, VolumePoint, BudgetBucket,
│   │                         #   CompetitionPoint, OutcomeShare, FunnelStage, Tip, AnalyticsRange) — "| None = None" for
│   │                         #   not-calculated stats; no from_attributes (all are computed, not ORM projections)
│   ├── settings_spec.py      # EXTEND — register the numeric analytics settings (min/max + Arabic labels)
│   └── routers/
│       └── analytics.py      # NEW — router = APIRouter(tags=["analytics"]);
│                             #   GET /api/analytics/overview(date_from: date|None, date_to: date|None) -> AnalyticsOverview
├── api/app.py                # EXTEND — add `analytics` to the local import tuple +
│                             #   app.include_router(analytics.router, dependencies=[Depends(require_auth)])
└── config/
    └── settings_store.py     # EXTEND DEFAULTS — ~8 new keys (analytics_timezone + thresholds); app_state untouched

#  (reused READ-ONLY, unchanged): qualify/filters.py (budget_usd, tier), qualify/budget_policy.py (load_policy),
#   personal/statuses.py (ordered status list + APPLIED_KEY), personal/stats.py (engaged-stage logic),
#   scoring Outcome enum, db/models.py — NO model, worker, bot, or scraper change. NO alembic migration.

frontend/
├── app/
│   └── analytics/
│       └── page.tsx          # NEW — date-range control + one useAnalytics query; renders the section cards with the
│                             #   Loading / ErrorState / "not enough data yet" ladder (mirrors app/projects/page.tsx)
├── components/
│   ├── Nav.tsx               # EXTEND — add { href: "/analytics", label: "التحليلات", icon: BarChart3 } to NAV_ITEMS
│   ├── SettingsForm.tsx      # EXTEND — new "التحليلات" (Analytics) group for the numeric analytics settings
│   └── analytics/            # NEW — all dependency-free, RTL-aware (mirror lifecycle/BidChart.tsx)
│       ├── DateRangeFilter.tsx   # presets (آخر ٧/٣٠/٩٠ يومًا) via ui/select + custom ui/input[type=date]; URL-as-state
│       ├── Heatmap.tsx           # 7×24 CSS-grid heatmap, Arabic day/hour labels, RTL
│       ├── VolumeChart.tsx       # inline-SVG qualified-vs-total over time; day/week tabs (ui/tabs)
│       ├── BudgetChart.tsx       # inline-SVG/CSS budget histogram + Tier-1/Tier-2 split
│       ├── CompetitionChart.tsx  # inline-SVG bids-vs-age median curve + spread + crowded marker + by-hour bars + headline
│       ├── FunnelChart.tsx       # CSS horizontal funnel bars + per-step conversion + lag (or "غير متاح")
│       ├── OutcomesPanel.tsx     # hired/no-hire share + mean/median time-to-close + missed-opportunities list
│       └── TipsPanel.tsx         # ranked plain-language tips, each with its supporting figures
└── lib/
    ├── api.ts                # EXTEND — getAnalyticsOverview(params) via apiFetch + buildQuery
    ├── types.ts              # EXTEND — AnalyticsOverview + section DTO interfaces (snake_case, `| null`)
    ├── useAnalytics.ts       # NEW — useQuery(["analytics", params]) with placeholderData: keepPrevious
    └── format.ts             # EXTEND — a tz-aware date-only formatter + a percent formatter for analytics labels

tests/
├── unit/        # NEW — test_analytics_timezone (bucketing/DST/day-boundary/fallback),
│                #   test_analytics_aggregates (each view incl. sparse, missing/one-sided budget, robust median,
│                #   funnel zero-denominator + lag-unavailable, missed-opportunity join),
│                #   test_analytics_tips (each rule above/below support, suggested-threshold replay, fallback tip, cap/rank)
├── api/         # NEW — test_analytics_api (auth-gated, date-range scoping, per-section enough_data, READ-ONLY assertion)
└── (frontend)   # NEW — vitest: heatmap/volume/competition/funnel render, "not enough data" states, date-filter wiring
```

**Structure Decision**: Web-application layout, continuing Features 2–4. The aggregation logic is isolated in a
**pure, surface-agnostic `analytics/` package** (mirroring `qualify/` and `scoring/model.py`: total functions
of injected `session`/`settings`/`now`, fully unit-testable without HTTP), and a thin `analytics/service.py`
is the single entry the API calls (mirroring `personal/service.py` / `scoring/service.py`) so the seven
aggregates are computed once and fed to the tips engine consistently. The new `analytics/timezone.py`
**generalizes** the existing copy-pasted `today_start_utc` tz-resolution into a reusable analytics-tz
bucketer (read-only; the two existing copies are left working as-is — de-duping them is an optional later
cleanup, out of scope here). The feature is delivered as **one read-only endpoint** (`GET
/api/analytics/overview`) plus a frontend page; it adds **no table, no migration, no process, no dependency**,
making it by far the lightest backend feature — the heavy lifting (the score, the snapshot trajectory, the
outcomes, the personal pipeline) was all done by Features 1–4, and this feature only reads it.

## Complexity Tracking

> No constitution violations — table intentionally empty. The design adds no new process, no new runtime
> dependency, no new table, no migration, and no new abstraction beyond the two patterns already established
> in this codebase (a pure rules module like `qualify/`/`scoring/model.py`, and a surface-agnostic service
> like `personal/`). All new state is additive `settings` rows.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |
