---
description: "Task list for Feature 4 — Continuous Watching and Opportunity Scoring"
---

# Tasks: Continuous Watching and Opportunity Scoring

**Input**: Design documents from `/specs/004-continuous-watch-scoring/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓ (openapi.yaml, scoring-model.md, telegram-bot.md), quickstart.md ✓

**Tests**: INCLUDED. The spec defines per-part Independent Tests + edge cases and the plan's Testing section
lists unit/integration/API/frontend tests; the owner's standing directive is exhaustive coverage. Backend
pure-function and service tests are written before their implementation within each story.

**Organization**: Tasks are grouped by user story (US1–US5 from spec.md, in priority order) so each story is
an independently implementable, testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task in the same phase)
- **[Story]**: US1–US5 (user-story phases only)
- Every task gives an exact file path

## Path Conventions

Web application (existing): backend Python package at `src/mostaql_notifier/`, tests at `tests/`, Next.js app
at `frontend/`, Alembic at `alembic/versions/`. Paths below are repository-root-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffolding that every later phase builds on. No new dependencies (per plan.md).

- [X] T001 [P] Create the scoring package skeleton with typed function signatures + docstrings (no logic yet): `src/mostaql_notifier/scoring/__init__.py`, `src/mostaql_notifier/scoring/model.py`, `src/mostaql_notifier/scoring/freshness.py`, `src/mostaql_notifier/scoring/service.py`
- [X] T002 [P] Add all Feature-4 settings keys to `DEFAULTS` in `src/mostaql_notifier/config/settings_store.py` (6 weights, 9 tuning values, 4 re-check loop keys, 4 freshness thresholds, `top_default_count`, `auto_status_site_enabled`, `auto_status_personal_enabled`, `awarded_markers`) with exact defaults + type tags per `data-model.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The schema and shared test factories. **⚠️ No user story can begin until this phase is complete.**

- [X] T003 Extend ORM in `src/mostaql_notifier/db/models.py`: add `ProjectScore` (1:1, PK=`project_id`, with `score` indexed, `breakdown`, `computed_at`, `outcome`, `tracking_active`, `last_checked_at`, `closed_observed_at`, timestamps), `ProjectSnapshot` (many, with `(project_id, captured_at)` index), the `Outcome` `make_enum`, add `awarded` to the `ProjectStatus` enum, add `ScrapeRun.kind` (default `"poll"`), add `PersonalRecord.auto_status_from` + `auto_status_at` (nullable), and the new relationships/indexes per `data-model.md`
- [X] T004 Create the Alembic migration `alembic/versions/____continuous_watch_scoring.py` (`down_revision = "8e6070483eaf"`): create `project_scores` + `project_snapshots`; batch-alter `projects.site_status` CHECK to add `awarded`; add `scrape_runs.kind`; add `personal_records.auto_status_from`/`auto_status_at`; data-step idempotently append `{"key":"expired_missed","label":"منتهي/فائت"}` to the `personal_statuses` setting if absent; full downgrade. (depends on T003)
- [X] T005 [P] Add test factories `make_project_score` and `make_project_snapshot` (+ helper to build a trajectory) to `tests/api/conftest.py`. (depends on T003)
- [X] T006 [P] Migration round-trip test (`alembic upgrade head` → `downgrade -1` → `upgrade head` on a fresh DB; assert both new tables, the `awarded` value, the new columns, and the appended status) in `tests/integration/test_scoring_migration.py`. (depends on T004)

**Checkpoint**: Schema + factories ready — user stories can now proceed.

---

## Phase 3: User Story 1 - Rank every qualified project by a single opportunity score (Priority: P1) 🎯 MVP

**Goal**: Every qualified project (incl. backfilled) gets a 0–100 score with a stored per-component
breakdown; the feed gains a score column + sort + score-range filter; the detail view shows the breakdown as
bars beside the active weights; weights/tuning are editable in settings and a change re-scores immediately.

**Independent Test**: Seed varied qualified projects, run the backfill, confirm every one has a 0–100 score +
breakdown; sort and score-range-filter the feed; open a project and see the bars beside the active weights
summing to the total; change a weight in settings and confirm scores + bars change with no code change.

### Tests for User Story 1 ⚠️ (write first, expect FAIL)

- [X] T007 [P] [US1] Unit tests for the pure scoring model — each of the 6 components (incl. low-sample shrinkage, diminishing returns + cap, Tier-2 down-scale, competition crowdedness/velocity, freshness decay, rating nudge), weight normalization (sum≠1 and all-zero→equal), and breakdown completeness (contributions sum to the total) — with injected `now_utc`, in `tests/unit/test_scoring_model.py` (per `contracts/scoring-model.md`)
- [X] T008 [P] [US1] Unit tests for the scoring service (`score_project` persists a `ProjectScore`; `rescore_all` scores every qualified project and skips non-qualified; `get_breakdown` returns the stored breakdown) in `tests/unit/test_scoring_service.py`
- [X] T009 [P] [US1] API tests for the feed: `score` column present, `sort=score` (NULL/non-qualified last), `score_min`/`score_max` filter, combinable with existing filters, in `tests/api/test_projects_score.py`
- [X] T010 [P] [US1] API tests for project detail: `score`, `score_breakdown` (components + active weights), `outcome` fields in `tests/api/test_project_detail_score.py`
- [X] T011 [P] [US1] API tests for settings: numeric weight/tuning editing (min/max, per-field 422), and a weight change triggering a synchronous re-score, in `tests/api/test_settings_scoring.py`
- [X] T012 [P] [US1] Frontend tests: score column + sort-by-score + score-range wiring and `ScoreBars` render, in `frontend/__tests__/scoreFeed.test.tsx`

### Implementation for User Story 1

- [X] T013 [US1] Implement the pure scoring model (6 components + runtime weight normalization + breakdown dict) in `src/mostaql_notifier/scoring/model.py`, reusing `qualify.filters.budget_usd` for the budget basis, per `contracts/scoring-model.md`. (depends on T002, T003)
- [X] T014 [US1] Implement the scoring service in `src/mostaql_notifier/scoring/service.py`: `score_project` (compute + upsert `ProjectScore`), `rescore_all` (backfill all `qualified`), `get_breakdown` — surface-agnostic, caller owns the transaction (mirrors `personal/service.py`). (depends on T013)
- [X] T015 [US1] Wire the one-time startup backfill (call `rescore_all`, guarded by `app_state` flag `scoring_backfilled`) in `src/mostaql_notifier/worker/main.py`. (depends on T014)
- [X] T016 [US1] Extend `src/mostaql_notifier/api/schemas.py`: add `score` to `ProjectListItem`; `score`, `score_breakdown`, `outcome` to `ProjectDetail`; add `ScoreComponent` + `ScoreBreakdown` DTOs per `data-model.md`. (depends on T003)
- [X] T017 [US1] Extend `src/mostaql_notifier/api/routers/projects.py`: `LEFT JOIN project_scores`, add `score_min`/`score_max` query params, add `sort="score"` (NULLs last), and populate `score`/`score_breakdown`/`outcome` in the responses. (depends on T016, T014)
- [X] T018 [US1] Register the scoring weights + tuning values as editable numeric settings (min/max + Arabic labels; weights validated as non-negative floats, **not** required to sum to 1) in `src/mostaql_notifier/api/settings_spec.py`. (depends on T002)
- [X] T019 [US1] In `src/mostaql_notifier/api/routers/settings.py`, call `scoring.service.rescore_all` synchronously after a successful PUT that changes any scoring weight/tuning key. (depends on T018, T014)
- [X] T020 [P] [US1] Frontend feed: add `"score"` to `SortField` and `score_min`/`score_max` to `FILTER_KEYS` in `frontend/lib/useProjects.ts`; add the sort option + range fields in `frontend/components/Filters.tsx`; add the score column in `frontend/components/ProjectTable.tsx` and `frontend/components/ProjectCard.tsx`; add the types in `frontend/lib/types.ts`. (depends on —; backend contract from T017)
- [X] T021 [P] [US1] Frontend detail: create `frontend/components/score/ScoreBars.tsx` (per-component bars vs active weights, RTL) and integrate it into `frontend/app/projects/[id]/page.tsx`. (depends on —)
- [X] T022 [P] [US1] Frontend settings: add the **"التقييم" (Scoring)** group (weight + tuning numeric fields) and HINTS in `frontend/components/SettingsForm.tsx`. (depends on —)

**Checkpoint**: US1 fully functional — scored feed (sort/filter), explained detail, tunable model. **MVP.**

---

## Phase 4: User Story 2 - Watch each project over time: trajectory, lifecycle, and outcome (Priority: P2)

**Goal**: A second, polite re-check loop re-visits open + recently-closed projects on its own interval,
appends snapshots, refreshes bids/status (incl. `awarded`), re-scores while open, captures a fail-closed
outcome, and stops past the grace period; the detail view shows a bid chart, status timeline, and outcome.

**Independent Test**: Run the re-check loop over open projects; confirm snapshots, recomputed scores, a bid
climb dropping the score, status→closed freezing the score, awarded→hired / closed-no-award→closed-no-hire /
ambiguous→unknown, grace-period stop, one blocked project skipped, paused-mid-cycle stop; see the lifecycle
render on detail.

### Tests for User Story 2 ⚠️

- [X] T023 [P] [US2] Unit test: `scraper/mostaql.py::_parse_status` detects `awarded` via config `awarded_markers` and stays fail-closed (`unknown` when ambiguous), in `tests/unit/test_parse_awarded.py`
- [X] T024 [P] [US2] Integration test for one full re-check cycle (snapshot append, re-score while open, outcome capture for open/closed-no-hire/awarded-hired/ambiguous-unknown, grace-period stop, blocked-project skip-not-stall, paused-mid-cycle) in `tests/integration/test_recheck_cycle.py`
- [X] T025 [P] [US2] API test for `GET /api/projects/{id}/lifecycle` (snapshots, derived status timeline, outcome) in `tests/api/test_project_lifecycle.py`
- [X] T026 [P] [US2] Frontend test: `BidChart` + `StatusTimeline` render from lifecycle data, in `frontend/__tests__/lifecycle.test.tsx`

### Implementation for User Story 2

- [X] T027 [US2] Extend `src/mostaql_notifier/scraper/mostaql.py::_parse_status` to recognize an awarded project via the config-driven `awarded_markers` (selectors confined to this file), defaulting fail-closed. (depends on T002)
- [X] T028 [US2] Implement `src/mostaql_notifier/worker/recheck.py::run_recheck_cycle`: select due projects (bounded `recheck_batch_size`, respect `recheck_min_interval_seconds`, open-or-within-grace, stalest-first); per project reuse `fetcher.get`+`parse_project_page`, refresh `bids_count`/`site_status`, refresh stale client, append a `project_snapshots` row, compute fail-closed `outcome`, re-score via `scoring.service` only while open, set `closed_observed_at`/stop tracking past grace, update `last_checked_at`; log a `kind="recheck"` `ScrapeRun`; honor `watcher_paused` + the `CircuitBreaker`/`classify_response`; wrap each project in try/except → log + skip. (depends on T014, T027, T003)
- [X] T029 [US2] Register a second `AsyncIOScheduler` job for the re-check loop (`IntervalTrigger(seconds=recheck_interval_seconds)`, `coalesce=True`, `max_instances=1`) beside the poll job, under the same job-error listener, in `src/mostaql_notifier/worker/main.py`. (depends on T028)
- [X] T030 [P] [US2] Add `Lifecycle`/`Snapshot`/`StatusEvent` DTOs in `src/mostaql_notifier/api/schemas.py` and `GET /api/projects/{id}/lifecycle` (status timeline = de-duplicated status changes from the snapshot series) in `src/mostaql_notifier/api/routers/projects.py`. (depends on T003)
- [X] T031 [P] [US2] Frontend lifecycle: create `frontend/components/lifecycle/BidChart.tsx` (dependency-free inline SVG) + `frontend/components/lifecycle/StatusTimeline.tsx` + `frontend/components/score/OutcomeBadge.tsx`; add `frontend/lib/useLifecycle.ts` + `getLifecycle` in `frontend/lib/api.ts` + types in `frontend/lib/types.ts`; integrate into `frontend/app/projects/[id]/page.tsx`. (depends on —)

**Checkpoint**: US1 + US2 work — live re-checked trajectory, outcome, and lifecycle view.

---

## Phase 5: User Story 3 - See at a glance whether a project is still worth bidding on (Priority: P3)

**Goal**: A derived green/yellow/red "still good?" signal (from the trajectory + configurable thresholds) in
the feed and on the detail view; closed/crowded reads red, fresh/uncrowded reads green.

**Independent Test**: Take projects at different life stages and confirm the right colour in feed + detail;
move a freshness threshold in settings and confirm the boundary shifts; a closed/crowded project reads red.

### Tests for User Story 3 ⚠️

- [X] T032 [P] [US3] Unit tests for the freshness deriver — green/yellow/red transitions, closed/awarded/unknown→red, threshold boundaries, single-snapshot low-data fallback — in `tests/unit/test_scoring_freshness.py`
- [X] T033 [P] [US3] API test: `freshness` present and correct in feed + detail responses in `tests/api/test_projects_freshness.py`
- [X] T034 [P] [US3] Frontend test: `FreshnessBadge` renders the right colour in feed + detail, in `frontend/__tests__/freshness.test.tsx`

### Implementation for User Story 3

- [X] T035 [US3] Implement the pure freshness deriver (green/yellow/red from latest snapshot + age + status against the configured thresholds; low-data fallback) in `src/mostaql_notifier/scoring/freshness.py`. (depends on T002, T003)
- [X] T036 [US3] Add the `freshness` field to `ProjectListItem`/`ProjectDetail` in `src/mostaql_notifier/api/schemas.py` and compute it on read (feed + detail) in `src/mostaql_notifier/api/routers/projects.py`. (depends on T035, T017)
- [X] T037 [P] [US3] Frontend: create `frontend/components/score/FreshnessBadge.tsx` and integrate into `frontend/components/ProjectTable.tsx` and the `frontend/app/projects/[id]/page.tsx` header; add the type in `frontend/lib/types.ts`. (depends on —)

**Checkpoint**: US1–US3 work — the feed/detail carry an at-a-glance freshness signal.

---

## Phase 6: User Story 4 - Keep status current automatically, and optionally flag missed projects (Priority: P4)

**Goal**: The loop keeps the Mostaql status current (delivered by US2's loop); an **optional, off-by-default,
reversible** "Interested→Expired/Missed" personal-status transition fires only on Interested-but-not-applied
projects that close; the two toggles are editable in settings (bool support added).

**Independent Test**: Toggle off → an Interested project that closes is unchanged; toggle on → it becomes
Expired/Missed (timestamped, automated, reversible); Applied/Won/Lost and deliberately-set statuses are never
touched; no personal data is deleted.

### Tests for User Story 4 ⚠️

- [X] T038 [P] [US4] Integration test for the optional auto personal-status: off=no change; on=Interested+not-applied+closed→`expired_missed`; Applied/Won/Lost untouched; deliberately-set status not overwritten; reversible (prior status restored); no notes/tags/files deleted; Mostaql status auto-synced by the loop — in `tests/integration/test_recheck_autostatus.py`
- [X] T039 [P] [US4] API test for editing the bool toggles (`auto_status_site_enabled`, `auto_status_personal_enabled`) via the settings endpoint, in `tests/api/test_settings_toggles.py`
- [X] T040 [P] [US4] Frontend test: bool settings render as a `Switch` and save, in `frontend/__tests__/settingsToggles.test.tsx`

### Implementation for User Story 4

- [X] T041 [US4] Add the optional auto personal-status transition to `src/mostaql_notifier/worker/recheck.py`: gated on `auto_status_personal_enabled`; only when the latest status is `closed`/`awarded` AND `personal.status == "interested"` AND `applied_at IS NULL`; set `status="expired_missed"`, store `auto_status_from`, stamp `auto_status_at` + `status_changed_at`; never touch other statuses or delete data. (depends on T028)
- [X] T042 [US4] Add a revert helper (restore `auto_status_from`, clear the auto fields) in `src/mostaql_notifier/personal/service.py` and expose it (PATCH personal or a small control route). (depends on T003)
- [X] T043 [US4] Add `"bool"` `SettingItem` support in `src/mostaql_notifier/api/schemas.py`, register the two toggles (type `"bool"`) in `src/mostaql_notifier/api/settings_spec.py`, and accept bool values in `src/mostaql_notifier/api/routers/settings.py`. (depends on T018)
- [X] T044 [P] [US4] Frontend: render a `Switch` for `"bool"` settings + a toggles group in `frontend/components/SettingsForm.tsx`, and add an "undo auto-change" affordance on the personal panel when `auto_status_at` is set in `frontend/app/projects/[id]/page.tsx`. (depends on —)

**Checkpoint**: US1–US4 work — auto status sync + the safe, reversible missed-project flag.

---

## Phase 7: User Story 5 - See the score, ask why, and pull the top projects in Telegram (Priority: P5)

**Goal**: Notifications carry the score + tier; a "Why?" button replies with the breakdown; `/top [n]` lists
the current top open projects by score with links.

**Independent Test**: Trigger a notification → it shows score+tier; tap "Why?" → per-component breakdown;
send `/top` and `/top 5` → top open projects by score with links; `/top` with none → friendly message; "Why?"
on a since-closed project → last known breakdown, no error.

### Tests for User Story 5 ⚠️

- [X] T045 [P] [US5] Unit test: `build_project_message` includes the score+tier line (and omits it gracefully when unscored), in `tests/unit/test_format_score.py`
- [X] T046 [P] [US5] Unit test: the "Why?" callback returns a per-component breakdown and is idempotent on a closed/old project, in `tests/unit/test_why_callback.py`
- [X] T047 [P] [US5] Unit test: `/top [n]` returns top open projects by score (default count, clamp to max, fewer-than-n short list, none→friendly message), in `tests/unit/test_top_command.py`

### Implementation for User Story 5

- [X] T048 [US5] Extend `src/mostaql_notifier/notify/format.py`: add the score+tier line to `build_project_message`; add `CB_WHY="why"` + a "لماذا؟" button to `build_project_keyboard`; add `build_score_breakdown_message`. (depends on T014)
- [X] T049 [US5] Implement `scoring.service.top_open(session, n)` (qualified + open + tracking, ordered by `score` desc) in `src/mostaql_notifier/scoring/service.py`. (depends on T014)
- [X] T050 [US5] Route `CB_WHY` → `scoring.service.get_breakdown` reply (owner-gated, answers the callback, idempotent, keeps the Feature-3 action buttons) in `src/mostaql_notifier/bot/callbacks.py`. (depends on T048, T014)
- [X] T051 [US5] Add `top_command` (parse optional `n`, default `top_default_count`, clamp) in `src/mostaql_notifier/bot/commands.py` and register `CommandHandler("top", …)` in `src/mostaql_notifier/bot/app.py`. (depends on T049)

**Checkpoint**: All five user stories independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T052 [P] Edge-case hardening unit tests (weights sum≠1 + all-zero normalization, non-finite/NaN guards, unknown-budget & None-bids → component floor, first-recheck velocity fallback vs long history) in `tests/unit/test_scoring_edge.py`
- [X] T053 [P] Walk `specs/004-continuous-watch-scoring/quickstart.md` end-to-end (migrate → backfill → re-check → tune → exercise each surface) and fix any drift
- [X] T054 Run `ruff check .` + full `pytest` (with branch coverage on `scoring/`, `worker/recheck.py`, `api/routers/projects.py`) and resolve any lint/test failures
- [X] T055 [P] Run the frontend `vitest` suite + lint in `frontend/` and resolve failures
- [X] T056 [P] Confirm the backup set covers `project_scores`/`project_snapshots` (they live in `./data`) and that `CLAUDE.md` reflects the new tech (note in `specs/004-continuous-watch-scoring/quickstart.md` ops section)
- [X] T057 Verify each Success Criterion SC-001…SC-010 from `spec.md` is demonstrably met (scored backfilled feed, explained detail, scheduled re-checks + lifecycle, grace-period outcome, freshness signal, live config change, Telegram score/why/top, low-sample shrink, polite + paused loop, safe reversible auto-status)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately (T001, T002 in parallel).
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories**. T003→T004; T005 after T003; T006 after T004.
- **User Stories (Phases 3–7)**: all depend on Foundational. US1 is the MVP and the score source US2/US5 consume; US2 produces the trajectory US3 reads and the loop US4 hooks. Recommended order P1→P2→P3→P4→P5; US3/US4/US5 can be parallelized by different developers once their dependency is met (see below).
- **Polish (Phase 8)**: after the desired stories are complete.

### User Story Dependencies

- **US1 (P1)**: only Foundational. Delivers the scoring model + service (`score_project`, `rescore_all`, `get_breakdown`) that later stories call.
- **US2 (P2)**: Foundational + US1's `scoring.service` (the loop re-scores via it). Delivers `project_snapshots` (the trajectory) + the `awarded` parse + the lifecycle.
- **US3 (P3)**: Foundational; reads the latest snapshot/status US2 produces (degrades gracefully with a single snapshot, so it is testable on US1 data alone).
- **US4 (P4)**: builds on US2's loop (adds the auto-status hook) + US1's settings plumbing (adds bool toggles).
- **US5 (P5)**: US1's `scoring.service` + the existing Telegram channel; independent of US2–US4.

### Within Each User Story

- Tests (the `[P]` test tasks) are written first and expected to fail.
- Pure model/deriver → service → worker/API wiring → frontend.
- Same-file tasks are sequential; different-file tasks are `[P]`.

### Parallel Opportunities

- **Setup**: T001 ∥ T002.
- **Foundational**: T005 ∥ T006 (after their deps).
- **US1**: all tests T007–T012 ∥; then T013→T014→(T015, T017, T019) backend chain; frontend T020 ∥ T021 ∥ T022 ∥ the backend chain.
- **US2**: tests T023–T026 ∥; T027→T028→T029 chain; T030 ∥ T031 ∥ that chain.
- **US3**: tests T032–T034 ∥; T035→T036; T037 ∥.
- **US4**: tests T038–T040 ∥; T041 / T042 / T043 (different files) largely ∥; T044 ∥.
- **US5**: tests T045–T047 ∥; T048 / T049 ∥; T050 (after T048) / T051 (after T049).
- **Cross-story**: once Foundational is done, a team can run US1, then split US3/US4/US5 across developers after their single dependency lands.

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together (expect FAIL):
Task: "Unit tests for the scoring model in tests/unit/test_scoring_model.py"
Task: "Unit tests for the scoring service in tests/unit/test_scoring_service.py"
Task: "API tests for feed score column/sort/filter in tests/api/test_projects_score.py"
Task: "API tests for project detail breakdown in tests/api/test_project_detail_score.py"
Task: "API tests for scoring settings + re-score in tests/api/test_settings_scoring.py"
Task: "Frontend tests for score feed + ScoreBars in frontend/__tests__/scoreFeed.test.tsx"

# Then the three frontend surfaces in parallel with the backend chain:
Task: "Frontend feed score column/sort/filter (useProjects/Filters/ProjectTable/ProjectCard/types)"
Task: "Frontend ScoreBars in components/score/ + detail page"
Task: "Frontend Scoring settings group in components/SettingsForm.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational (schema + factories).
2. Phase 3 US1 (scoring model + service + backfill + feed/detail/settings + frontend).
3. **STOP & VALIDATE**: every qualified project scored, feed sort/filter works, detail explains the score, a
   weight change re-scores. Demo the MVP.

### Incremental Delivery

US1 (MVP: ranked, explained, tunable feed) → US2 (live re-checked trajectory + outcome + lifecycle) → US3
(freshness signal) → US4 (auto status + safe reversible missed-flag) → US5 (Telegram score/why/top). Each
phase ends at an independently testable checkpoint.

### Parallel Team Strategy

After Foundational: Developer A builds US1; once `scoring.service` lands, B takes US2 and C takes US5 (both
need only US1); after US2's loop lands, D takes US3 and E takes US4. Pure modules (`scoring/model.py`,
`scoring/freshness.py`) and the frontend components are the cleanest parallel hand-offs.

---

## Notes

- `[P]` = different files, no incomplete same-phase dependency.
- `[USx]` ties each task to its spec user story for traceability.
- Every story ends at a checkpoint where it is independently demonstrable.
- TDD: confirm the `[P]` test tasks fail before implementing.
- Constitution guards baked into tasks: polite re-use (T028), config-over-code (T002, T018, T043), fail-closed
  outcome (T024, T028), non-destructive/reversible auto-status (T038, T041, T042), append-only snapshots
  (T014, T028), Arabic/RTL + UTC (T013, T035, T048), fail-loud re-check runs (T028, T029).
- Commit after each task or logical group; never weaken a story's independent testability.
