# Implementation Plan: Continuous Watching and Opportunity Scoring

**Branch**: `004-continuous-watch-scoring` | **Date**: 2026-06-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-continuous-watch-scoring/spec.md`

## Summary

Feature 4 turns the watcher's raw collection into judgement. It adds (A) a single **0–100 opportunity
score** for every qualified project — a pure function of stored project + client facts, combining six
configurable weighted components (confidence-shrunk hiring rate, hire volume, budget, competition,
freshness, rating adjustment) with a stored per-component **breakdown** — surfaced as a feed column +
sort + score-range filter and as per-component bars on the detail view; (B) a **second background loop**
(the "re-check" loop) that runs on its own slower interval, re-visits open and recently-closed projects in
polite bounded batches, refreshes each project's bid count + Mostaql status (now including **awarded**),
appends an **append-only snapshot** (bids, status, score), recomputes the score while the project is open,
captures a fail-closed **outcome** (open / closed-no-hire / hired / unknown), and stops tracking a project
once it has been closed past a configurable grace period; and (C) a derived green/yellow/red **freshness
signal**, **automatic status updates** (always-on Mostaql-status sync + an optional, off-by-default,
reversible "Interested→Expired/Missed" personal-status transition), and the **score + tier + a "Why?"
button + a `/top [n]` command** in Telegram.

**Technical approach** (extends Features 1–3 with no rewrites). The score is computed by a new **pure
scoring module** (`src/mostaql_notifier/scoring/model.py`) — injected `settings` + `now_utc`, no I/O, unit
tested like the existing qualifier — wrapped by a **surface-agnostic scoring service**
(`scoring/service.py`) that persists the latest score/breakdown, runs the backfill, answers "Why?"/`/top`,
and is called by the API, the worker, and the bot alike (mirroring `personal/service.py`). The re-check
loop (`worker/recheck.py`) **reuses** the watcher's `HttpxFetcher`, `polite_delay`, `CircuitBreaker`,
`classify_response`, `parse_project_page`, `qualify`, and `watcher_paused` handling, and is registered as a
**second `AsyncIOScheduler` job** beside the existing poll job in `worker/main.py`. Persistence adds **two
new SQLite tables** via **one Alembic migration** (`project_scores` 1:1 with `projects`; `project_snapshots`
many-per-project, append-only) plus three small additive changes (an `awarded` value on the `ProjectStatus`
CHECK enum, a defaulted `kind` column on `scrape_runs` so re-check runs are logged distinctly, and two
nullable `auto_status_*` columns on `personal_records` to make the optional auto-transition reversible).
Every new tunable — six weights, the model's tuning values, the re-check interval/batch/min-interval, the
grace period, the freshness thresholds, the `/top` default, and the two auto-status toggles — is an additive
`settings` row (config over code); the dashboard settings form gains a **scoring** group and bool-toggle
support. The **Next.js** frontend adds a score column + sort + range filter to the feed, and a
score-breakdown card, a dependency-free SVG **bid-over-time** chart, a **status timeline**, an **outcome**
badge, and a **freshness** badge to the detail view.

## Technical Context

**Language/Version**: Python 3.11+ (backend + worker + bot, one venv/package); TypeScript / Node 20+ (frontend)
**Primary Dependencies**: Backend — FastAPI + Uvicorn, SQLAlchemy 2 (existing models/session), Alembic (`render_as_batch=True`), pydantic-settings, APScheduler (`AsyncIOScheduler` — existing), python-telegram-bot v21 (existing, outbound `ExtBot` + inbound `Application`), httpx[http2] + selectolax (existing scraper). **No new backend dependency.** Frontend — Next.js 16, React 19, Tailwind v4, Base UI (`@base-ui/react`), TanStack Query, lucide. **No new frontend dependency** — the bid chart + timeline are bespoke inline SVG/flex (avoids a heavy React-19-compat charting lib; see research).
**Storage**: Existing SQLite (`sqlite:///./data/mostaql.db`, WAL). **Two new tables** (`project_scores`, `project_snapshots`) + additive column/enum changes via **one Alembic migration** (`down_revision = 8e6070483eaf`). All new state inside the backed-up `./data` volume.
**Testing**: Backend — pytest. Pure-function unit tests for the scoring model (each component + weight normalization + breakdown, with injected `now_utc`) and the freshness deriver; service tests for backfill/re-score/`top_open`/`get_breakdown`; integration tests for one full re-check cycle against golden fixtures (open→still-open snapshot, open→closed-no-hire, open→awarded/hired, ambiguous→unknown, grace-period stop, blocked-project skip, paused mid-cycle); migration round-trip (upgrade head → downgrade → upgrade). API — FastAPI `TestClient` (`api_env`) for the score column/sort/score-range filter, detail breakdown + lifecycle, score-triggered re-score on settings PUT, and the bool-toggle settings. Bot — codec + "Why?" callback + `/top [n]` handler. Frontend — Vitest + Testing Library (score column/sort/filter wiring, breakdown bars, bid-chart/timeline render, freshness badge, scoring settings group).
**Target Platform**: Localhost (laptop/phone on LAN); portable to a single always-on VPS via redeploy (Constitution X).
**Project Type**: Web application (FastAPI API + Next.js SPA) over the existing async worker package and the inbound Telegram bot — the same four cooperating processes (worker, bot, api, frontend) over one SQLite file (WAL). This feature adds **no new process** — the re-check loop is a second job inside the existing worker.
**Performance Goals**: Scoring is a pure in-memory computation (no I/O) — backfilling/​re-scoring the whole qualified set (personal scale: low-thousands) completes well under a second, so a settings-PUT weight change can re-score synchronously and the feed reflects it on the next refresh (SC-006). The re-check loop processes a bounded batch (default 20 projects) per cycle with the same randomized 2.5–7 s inter-request delays as the watcher, staying ≪1 req/s. Feed sort/filter by score is an indexed `LEFT JOIN` + `ORDER BY`.
**Constraints**: Re-check loop is as polite as the watcher (bounded batch, randomized delays, serial concurrency, backoff/block-detection, never re-check one project more often than the configured min-interval, paused honored) (II); outcome capture is fail-closed — ambiguous endings are `unknown`, never `hired` (VII); automation appends snapshots and refreshes the derived latest score but NEVER deletes/overwrites owner data and NEVER overwrites a deliberately-set personal status; the optional auto personal-status change is off by default, reversible, and timestamped (IV); all new tunables read from `settings` (III); re-parsed bids/percentages handle Arabic-Indic digits and "لم يحسب بعد", timestamps UTC / owner-tz displayed, surfaces RTL (V); all new surfaces behind the existing auth gate; reads only — no platform writes (VIII, IX).
**Scale/Scope**: One owner; low-thousands of projects; re-check batch ~20/cycle every ~30 min; ~6 new/changed HTTP responses (feed item, detail, lifecycle endpoint, settings group, score-triggered re-score), 1 new bot command + 1 new callback button, score/tier added to notifications, 2 new tables + 1 migration, ~20 new settings keys.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* **Verdict: PASS** (initial; re-checked after Phase 1 — still PASS). No violations; Complexity Tracking intentionally empty.

- [x] **I. Personal & Single-Box** — PASS. No accounts/roles/tenancy. Every new surface reuses Feature 2's single-password gate; the new `/top` command and "Why?" callback are owner-chat-gated like all bot handlers. No new user class, no new public surface, no new process.
- [x] **II. Polite, Non-Aggressive Access** — PASS. The re-check loop **reuses** `HttpxFetcher`, `polite_delay` (randomized 2.5–7 s), serial concurrency, `backoff_seconds`, and the `CircuitBreaker`/`classify_response` block & structure-change detection; it works in bounded batches (`recheck_batch_size`), never re-checks a single project more often than `recheck_min_interval_seconds`, fetches each project's existing detail URL at most once per cycle, and skips its whole cycle when `watcher_paused`. It adds request volume but stays personal and low (FR-018, FR-019, FR-021).
- [x] **III. Config Over Code** — PASS. All six weights, every tuning value (baseline, shrink-k, half-saturations, budget cap, Tier-2 scale, freshness half-life, rating bounds), the re-check interval/batch/min-interval, the grace period, the freshness thresholds, the `/top` default, and both auto-status toggles are additive `settings` rows read at runtime; weights are **normalized**, not rejected, when they do not sum to one. No behavior-affecting literal in code (FR-008, FR-009, FR-033).
- [x] **IV. Idempotent Ingestion & Non-Destructive History** — PASS. Snapshots are **append-only** (a new row per re-check, never overwritten); the latest score/breakdown in `project_scores` is a derived value the automation maintains (full history preserved in `project_snapshots`), not owner data. Automation never deletes or overwrites notes/tags/files/outcomes/statuses; the optional personal-status auto-transition only ever fires on an Interested-but-not-applied project that closes, stores the prior status for one-click revert, is timestamped, and never touches Applied/Won/Lost or any deliberately-set status (FR-014, FR-028, FR-029, FR-035). The reused parser keeps storing raw payloads (Feature 1). New tables + columns are inside the backed-up `./data` volume.
- [x] **V. Arabic-First Correctness** — PASS. Re-parsing reuses `normalize_text` / `parse_hiring_rate` (Arabic-Indic + Persian digits, "لم يحسب بعد" as a first-class state); all new timestamps (`captured_at`, `last_checked_at`, `closed_observed_at`, `auto_status_at`) are `UtcDateTime` (strict UTC), displayed in `owner_timezone`; the score column, breakdown bars, freshness badge, outcome, "Why?" reply, and `/top` list render RTL with `<bdi>` isolation (FR-034, FR-037).
- [x] **VI. Fail Loud** — PASS. The re-check loop logs every cycle as a `scrape_runs` row with `kind="recheck"` (found/checked/updated/errors + status), alerts the owner via the existing `sender.send_alert` on block/structure-change, retries under the same backoff, and never dies silently; one project's failure is logged and skipped without stalling the batch (FR-020, FR-023). The loop honors and exposes the paused state.
- [x] **VII. Conservative, Fail-Closed Qualification** — PASS. Outcome capture is fail-closed — an explicit award ⇒ `hired`; a plain close with no visible award ⇒ `closed_no_hire`; anything ambiguous ⇒ `unknown` (never assumed hired). The hiring-rate component shrinks low-sample rates toward the neutral baseline rather than trusting them; only `eval_status == qualified` projects are scored, ranked, and listed by `/top` (FR-002, FR-011, FR-016).
- [x] **VIII. No Platform Automation** — PASS. The re-check loop only **reads** project pages (the same GET the watcher already performs); scoring, freshness, auto-status, notifications, "Why?", and `/top` write only to local data — no bid/message/submit/write on mostaql.com (FR-036).
- [x] **IX. Local Security Hygiene** — PASS. The score column/sort/filter, the detail breakdown + lifecycle endpoint, and the scoring settings all sit behind `require_auth`; no new public surface, no uploads, no new secret. The bot handlers stay owner-chat-gated. Secrets remain in `.env`.
- [x] **X. Deployment-Portable** — PASS. The two new tables, the additive columns, and all new settings live in the portable, restorable `./data` volume via the existing `DATABASE_URL` engine and Alembic batch migrations; no hostname/abspath assumptions; SQLite→Postgres stays config + restore.

**Result**: All gates Pass. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/004-continuous-watch-scoring/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output — key design decisions
├── data-model.md        # Phase 1 output — new tables, enum/column deltas, settings, transitions
├── quickstart.md        # Phase 1 output — run the re-check loop + backfill + tune locally
├── contracts/
│   ├── openapi.yaml      # Phase 1 — new/changed HTTP endpoints (feed score, detail breakdown, lifecycle, settings)
│   ├── scoring-model.md  # Phase 1 — the scoring contract: components, formulas, normalization, breakdown shape
│   └── telegram-bot.md   # Phase 1 — score+tier in notifications, "Why?" callback, /top [n]
└── checklists/
    └── requirements.md  # From /speckit.specify
```

### Source Code (repository root)

```text
src/mostaql_notifier/
├── db/
│   └── models.py            # EXTEND — ProjectScore (1:1, PK=project_id) + ProjectSnapshot (many);
│                            #   add ProjectStatus.awarded; add ScrapeRun.kind (default "poll");
│                            #   add PersonalRecord.auto_status_from + auto_status_at; relationships
├── scoring/                 # NEW — surface-agnostic scoring (used by API, worker, AND bot)
│   ├── __init__.py
│   ├── model.py             # PURE — component sub-scores (hiring-rate shrinkage, hire-volume & budget
│   │                        #   diminishing returns + Tier-2 scale + cap, competition from bids+velocity,
│   │                        #   freshness decay, rating adjustment), weight normalization, combine → 0–100 + breakdown
│   ├── freshness.py         # PURE — derive green/yellow/red from trajectory + configured thresholds
│   └── service.py           # score_project / rescore_all (backfill + settings-triggered) / get_breakdown / top_open
├── worker/
│   ├── main.py              # EXTEND — register a 2nd AsyncIOScheduler job (recheck) on recheck_interval;
│   │                        #   run startup backfill once (guarded by app_state "scoring_backfilled")
│   └── recheck.py           # NEW — run_recheck_cycle: select due projects (bounded batch); per project
│                            #   reuse fetch+parse, refresh bids/status (+stale client), append snapshot,
│                            #   detect outcome (fail-closed), re-score if open, auto-status, stop past grace;
│                            #   log a kind="recheck" ScrapeRun; honor pause + circuit breaker
├── scraper/
│   └── mostaql.py           # EXTEND — _parse_status learns the "awarded" marker (config-driven markers)
├── qualify/
│   └── filters.py           # (reused unchanged for re-qualify; tier feeds the budget component)
├── notify/
│   └── format.py            # EXTEND — build_project_message adds score+tier line; add CB_WHY="why" +
│                            #   "لماذا؟" button in build_project_keyboard; build_score_breakdown_message
├── bot/
│   ├── app.py               # EXTEND — register CommandHandler("top", commands.top_command)
│   ├── callbacks.py         # EXTEND — route CB_WHY → reply with scoring.service.get_breakdown
│   └── commands.py          # EXTEND — top_command([n]) → scoring.service.top_open
├── api/
│   ├── schemas.py           # EXTEND — score/freshness on ProjectListItem; score_breakdown/outcome/freshness
│   │                        #   on ProjectDetail; ScoreBreakdown, Lifecycle, Snapshot, StatusEvent DTOs;
│   │                        #   bool SettingItem support
│   ├── settings_spec.py     # EXTEND — register scoring weights/tuning, loop, freshness, /top, toggles
│   │                        #   (with min/max + Arabic labels + "bool" type); weights-sum note (normalized at runtime)
│   └── routers/
│       ├── projects.py      # EXTEND — score_min/score_max filters, sort="score"; load ProjectScore (join);
│       │                    #   GET /api/projects/{id}/lifecycle (snapshots + status timeline + outcome)
│       └── settings.py      # EXTEND — on a scoring-weight/tuning change, call scoring.service.rescore_all
└── config/
    └── settings_store.py    # EXTEND DEFAULTS — ~20 new keys (weights, tuning, loop, freshness, /top, toggles)

alembic/versions/
└── ____continuous_watch_scoring.py  # NEW — create project_scores + project_snapshots; batch-alter
                                     #   projects.site_status CHECK (+awarded); add scrape_runs.kind;
                                     #   add personal_records.auto_status_from/at; data-migrate: append
                                     #   "expired_missed" to personal_statuses if absent (idempotent)

frontend/
├── app/projects/page.tsx            # (table host) — score column shows via ProjectTable
├── app/projects/[id]/page.tsx       # EXTEND — freshness badge (header), score-breakdown card, lifecycle card
├── components/
│   ├── Filters.tsx                  # EXTEND — sort "score" option + score_min/score_max range fields
│   ├── ProjectTable.tsx             # EXTEND — score column (+ freshness dot) between bids and posted
│   ├── ProjectCard.tsx              # EXTEND — score + freshness on the card layout
│   ├── SettingsForm.tsx             # EXTEND — "scoring" group; render Switch for bool settings
│   ├── score/                       # NEW — ScoreBars (per-component bars vs active weights), FreshnessBadge, OutcomeBadge
│   └── lifecycle/                   # NEW — BidChart (inline SVG sparkline), StatusTimeline
└── lib/
    ├── api.ts                       # EXTEND — getLifecycle(id); score fields flow through existing calls
    ├── types.ts                     # EXTEND — score, freshness, ScoreBreakdown, Lifecycle, Snapshot, StatusEvent
    ├── useProjects.ts               # EXTEND — SortField += "score"; FILTER_KEYS += score_min/score_max
    └── useLifecycle.ts              # NEW — query ["lifecycle", id] for the detail charts

tests/
├── unit/        # NEW — test_scoring_model (components + normalization + breakdown), test_scoring_freshness,
│                #   test_scoring_service (backfill/rescore/top_open/get_breakdown)
├── api/         # NEW — test_projects_score (column/sort/score-range), test_project_lifecycle,
│                #   test_settings_scoring (re-score on weight change + bool toggles); EXTEND test_settings_*
├── integration/ # NEW — test_recheck_cycle (snapshot/outcome/grace/skip/paused), test_recheck_autostatus,
│                #   test_scoring_backfill, test_scoring_migration (round-trip)
└── (bot)        # NEW — test_top_command, test_why_callback; EXTEND notification-format test (score+tier)
```

**Structure Decision**: Web-application layout, continuing Features 2–3. The **pure scoring model** is
isolated in `scoring/model.py` (the constitution-critical "config-over-code, fully testable" seam, mirroring
`qualify/`), and the **scoring service** is the single surface-agnostic entry the API, worker, and bot all
call (mirroring `personal/service.py`) so "one score, one breakdown, consistent everywhere" lives in one
place. The re-check loop is a **second scheduler job inside the existing worker** (not a new process): it
reuses every politeness/parse/qualify primitive, so politeness is guaranteed by construction and a re-check
fault is isolated by the same job-error listener that guards the poll job. Schema evolves by **one Alembic
migration** adding two tables plus three additive, non-destructive deltas; new tunables are additive
`settings` rows seeded by `seed_defaults`.

## Complexity Tracking

> No constitution violations — table intentionally empty. The design adds no new process, no new runtime
> dependency, and no new abstraction beyond the two patterns already established in this codebase (a pure
> rules module like `qualify/`, and a surface-agnostic service like `personal/`). The two new tables and the
> three additive schema deltas are the minimum needed to store the score, the append-only trajectory, the
> `awarded` status, distinct re-check run logging, and a reversible auto-status — each required by an FR.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |
