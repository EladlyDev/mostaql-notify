# Tasks: Analytics and Insights

**Input**: Design documents from `/specs/006-analytics-insights/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅ (openapi.yaml, analytics-aggregates.md)

**Tests**: INCLUDED. The spec (SC-006/SC-008 — "verified on a near-empty database", "verified by comparing those tables before and after"), the plan's Testing section, and the contract's "Invariants (test gates)" explicitly require tests — including the read-only assertion and the robust-stats / sparse-data gates. This is a test-heavy repo (existing suite ~1962 tests); test tasks are first-class here and are written before the implementation they cover within each story (TDD).

**Organization**: Tasks are grouped by user story (US1–US7 from spec.md). The single endpoint `GET /api/analytics/overview` returns every section + tips, so the section **shell** (router, service, DTOs, frontend page, date filter, settings) is shared infrastructure built in **Foundational**; each user story then adds exactly **one aggregate function + one chart** and is independently testable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US7 (user-story phases only; Setup/Foundational/Polish carry no story label)
- Every task names its exact file path.

## Path Conventions

Web application (existing): backend Python package at `src/mostaql_notifier/`, tests at `tests/`, frontend at
`frontend/`. This feature adds a new pure package `src/mostaql_notifier/analytics/`, one API router, and a new
frontend `app/analytics/` page + `components/analytics/` charts. **No new table, no migration, no new process,
no new dependency** (see plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton + the new config keys every aggregate and the tz helper read.

- [x] T001 Create the analytics package: `src/mostaql_notifier/analytics/__init__.py` (empty package marker).
- [x] T002 Add the 8 additive analytics settings to `src/mostaql_notifier/config/settings_store.py` `DEFAULTS` — `analytics_timezone` ("", "str"), `analytics_default_range_days` (90,"int"), `analytics_min_support` (30,"int"), `analytics_min_wins_support` (5,"int"), `analytics_crowded_bids` (15,"int"), `analytics_early_bids` (5,"int"), `analytics_max_tips` (6,"int"), `analytics_suggested_threshold_keep` (0.9,"float") (data-model.md "New settings keys").
- [x] T003 [P] Register the 7 numeric analytics settings in `src/mostaql_notifier/api/settings_spec.py` `EDITABLE_SETTINGS` as `SettingSpec(key, type, min, max, label_ar)` with the Arabic labels from data-model.md (the str `analytics_timezone` is DB-editable only, like `owner_timezone` — not registered).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The analytics-tz bucketer, the DTO scaffold, the pure-package skeleton, the single read-only
endpoint, and the frontend section shell + date filter. After this phase the endpoint returns a valid,
all-empty `AnalyticsOverview` and `/analytics` renders the shell with "not enough data yet" everywhere, behind
auth, with a working date filter.

**⚠️ CRITICAL**: No user-story aggregate/chart can be wired in until this phase is complete.

- [x] T004 Implement `src/mostaql_notifier/analytics/timezone.py`: `analytics_tz(session)` (read `analytics_timezone`; empty ⇒ `owner_timezone`; invalid ⇒ `Africa/Cairo`), `local_parts(dt_utc, tz) -> (weekday 0=Sat..6=Fri, hour, local_date)`, `day_key`, `iso_week_key`, and `window_bounds(date_from, date_to, tz) -> (utc_start, utc_end)` with default-range + half-open semantics (contracts/analytics-aggregates.md §0).
- [x] T005 [P] Unit test `tests/unit/test_analytics_timezone.py`: empty→owner / invalid→Cairo fallback, weekday Sat=0 mapping, a DST-boundary instant, a 23:30-local day-boundary case, and `window_bounds` half-open + default-range correctness.
- [x] T006 Add all analytics DTOs to `src/mostaql_notifier/api/schemas.py` (`AnalyticsRange`, `HeatmapCell`, `PostingHeatmap`, `VolumePoint`, `VolumeTrends`, `BudgetBucket`, `BudgetDistribution`, `CompetitionPoint`, `CompetitionDynamics`, `TimeToClose`, `MissedProject`, `OutcomeAnalytics`, `FunnelStage`, `Funnel`, `Tip`, `AnalyticsOverview`) — no `from_attributes`, `| None = None` for not-calculated numerics, `model_rebuild()` at module end (data-model.md "DTOs").
- [x] T007 Implement `src/mostaql_notifier/analytics/aggregates.py` with the result dataclasses and **stub** `posting_heatmap` / `volume_trends` / `budget_distribution` / `competition_dynamics` / `outcome_analytics` / `funnel` that each return an empty result with `enough_data=False` (real algorithms land per story).
- [x] T008 Implement `src/mostaql_notifier/analytics/tips.py` skeleton: `generate_tips(overview, settings, *, session) -> list[Tip]` returning `[]` (rules land in US6).
- [x] T009 Implement `src/mostaql_notifier/analytics/service.py` `compute_overview(session, settings, *, date_from, date_to, now)`: resolve the range via `timezone.window_bounds` (default `analytics_default_range_days`), call every aggregate + `generate_tips`, and assemble `AnalyticsOverview` (research R6).
- [x] T010 Create `src/mostaql_notifier/api/routers/analytics.py`: `router = APIRouter(tags=["analytics"])`; `@router.get("/api/analytics/overview", response_model=AnalyticsOverview)` with `date_from: Annotated[date | None, Query()] = None`, `date_to: … = None`, `db: Annotated[Session, Depends(get_db)]`; build `SettingsStore(db)`, call `compute_overview`, raise 422 when `date_from > date_to` (contracts/openapi.yaml).
- [x] T011 Mount the router in `src/mostaql_notifier/api/app.py`: add `analytics` to the local import tuple and `app.include_router(analytics.router, dependencies=[Depends(require_auth)])`.
- [x] T012 [P] API test scaffold `tests/api/test_analytics_api.py`: 401 unauthenticated, default-range overview shape on an empty DB (every section `enough_data=False`, `tips == []`), and 422 on `date_from > date_to` (uses `api_env` + factories).
- [x] T013 [P] Add `getAnalyticsOverview(params)` to `frontend/lib/api.ts` (via `apiFetch` + `buildQuery`) and the `AnalyticsOverview` + section interfaces to `frontend/lib/types.ts` (snake_case, `| null`).
- [x] T014 [P] Add `frontend/lib/useAnalytics.ts`: `useQuery(["analytics", params], …, { placeholderData: keepPrevious })`.
- [x] T015 [P] Add a tz-aware **date-only** formatter and a **percent** formatter to `frontend/lib/format.ts` (mirroring the existing `ar`/`ar-EG` `Intl` formatters).
- [x] T016 [P] Add the analytics nav item to `frontend/components/Nav.tsx` `NAV_ITEMS` — `{ href: "/analytics", label: "التحليلات", icon: BarChart3 }` (import `BarChart3` in the lucide block).
- [x] T017 Create `frontend/components/analytics/DateRangeFilter.tsx`: presets (آخر ٧/٣٠/٩٠ يومًا) via `ui/select`/`toggle-group` + custom `ui/input[type="date"]`, range held in the URL (the `useProjects` `useSearchParams` idiom).
- [x] T018 Create `frontend/app/analytics/page.tsx` shell: header, `DateRangeFilter`, the `useAnalytics` query, and the `Loading` / `ErrorState` / `EmptyState` ladder with one placeholder `Card` per section that renders "لا توجد بيانات كافية بعد" when `enough_data` is false (mirrors `app/projects/page.tsx`).
- [x] T019 [P] Add a "التحليلات" group to `frontend/components/SettingsForm.tsx` rendering the new numeric analytics settings.

**Checkpoint**: `GET /api/analytics/overview` returns a valid empty overview; `/analytics` renders the shell behind auth with a working date filter and tunable settings.

---

## Phase 3: User Story 1 - Posting heatmap (Priority: P1) 🎯 MVP

**Goal**: A 7×24 day-of-week × hour-of-day heatmap of when qualified projects are posted, in the configured
analytics timezone, scoped by the date filter, honest under thin data.

**Independent Test**: Seed qualified projects across weekdays/hours; the heatmap's densest cells mark the peak
windows; changing `analytics_timezone` re-buckets (a near-midnight project moves day/hour); narrowing the date
range narrows the counts; a near-empty DB shows "not enough data yet".

- [x] T020 [P] [US1] Unit tests for `posting_heatmap` in `tests/unit/test_analytics_aggregates.py`: per-cell counts, `peak`, Sat=0 weekday mapping, `posted_at`→`scraped_at` fallback, and the `enough_data = total ≥ analytics_min_support` gate.
- [x] T021 [US1] Implement `posting_heatmap` in `src/mostaql_notifier/analytics/aggregates.py` (replace the stub) per contracts/analytics-aggregates.md §1, including the Arabic `weekday_labels`.
- [x] T022 [P] [US1] Create `frontend/components/analytics/Heatmap.tsx`: a 7×24 CSS-grid heatmap (Arabic day rows / hour columns, RTL, intensity by count) with a `data-testid` "not enough data" state (mirror `lifecycle/BidChart.tsx` empty-state convention).
- [x] T023 [US1] Wire `Heatmap` into `frontend/app/analytics/page.tsx` (the heatmap section card).
- [x] T024 [US1] Extend `tests/api/test_analytics_api.py`: heatmap section populated above support, date-range scoping of the cells, and the `enough_data` flag.
- [x] T025 [P] [US1] Frontend vitest for `Heatmap` render + empty state in `frontend/components/analytics/__tests__/Heatmap.test.tsx`.

**Checkpoint**: MVP — the analytics section exists and shows a working posting heatmap end to end.

---

## Phase 4: User Story 2 - Volume trends + budget distribution (Priority: P2)

**Goal**: Qualified-vs-total counts over time (by day and by week, development category) and a budget
distribution with the Tier-1/Tier-2 split, handling missing/one-sided budgets gracefully.

**Independent Test**: Seed projects across weeks (mixed qualified/disqualified, mixed Tier-1/Tier-2, some
missing/one-sided budgets); the volume view shows day + week granularity scoped to the range; the budget view
shows the distribution + Tier split; partial-budget projects land in a labelled unknown band without distorting
totals.

- [x] T026 [P] [US2] Unit tests for `volume_trends` in `tests/unit/test_analytics_aggregates.py`: by-day + by-week buckets, total vs qualified, the category label, and `enough_data` (≥2 non-empty buckets).
- [x] T027 [P] [US2] Unit tests for `budget_distribution` in `tests/unit/test_analytics_aggregates.py`: USD bands, `tier1_count`/`tier2_count`, missing/one-sided budget → `unknown` band (counted, not dropped), and `enough_data`.
- [x] T028 [US2] Implement `volume_trends` in `src/mostaql_notifier/analytics/aggregates.py` (contracts §2; `posting_time` fallback; category from `category_slug`).
- [x] T029 [US2] Implement `budget_distribution` in `src/mostaql_notifier/analytics/aggregates.py` (contracts §3; reuse `qualify.filters.budget_usd` and `project.tier` — do not redefine the tier rule).
- [x] T030 [P] [US2] Create `frontend/components/analytics/VolumeChart.tsx` (inline-SVG qualified-vs-total over time, by-day/by-week tabs via `ui/tabs`).
- [x] T031 [P] [US2] Create `frontend/components/analytics/BudgetChart.tsx` (inline-SVG/CSS budget histogram + a Tier-1/Tier-2 split bar + the unknown band).
- [x] T032 [US2] Wire `VolumeChart` + `BudgetChart` into `frontend/app/analytics/page.tsx`.
- [x] T033 [P] [US2] Extend `tests/api/test_analytics_api.py` (volume + budget sections) and add `frontend/components/analytics/__tests__/VolumeChart.test.tsx` + `BudgetChart.test.tsx`.

**Checkpoint**: US1 + US2 both render independently; the date filter scopes both.

---

## Phase 5: User Story 3 - Competition dynamics (Priority: P3)

**Goal**: A median bids-vs-age curve from the real snapshot trajectories, a plain-language "how long before it
gets crowded" headline against a configurable threshold, and a bidding-by-hour view.

**Independent Test**: Seed projects with rising-bid snapshot sequences; the curve shows median bids by age band
with a spread; the headline states ~hours-to-`analytics_crowded_bids` and moves when the threshold changes; a
single-snapshot project doesn't break the aggregate.

- [x] T034 [P] [US3] Unit tests for `competition_dynamics` in `tests/unit/test_analytics_aggregates.py`: median/p25/p75 age curve, `crowded_after_hours` + headline, by-hour positive-delta attribution, single-snapshot degrade, and `enough_data`.
- [x] T035 [US3] Implement `competition_dynamics` in `src/mostaql_notifier/analytics/aggregates.py` (contracts §4; `statistics.quantiles`; deltas from consecutive snapshots; `analytics_crowded_bids`).
- [x] T036 [P] [US3] Create `frontend/components/analytics/CompetitionChart.tsx` (inline-SVG median curve + IQR band + "crowded" marker + a 24-hour bidding strip + the Arabic headline).
- [x] T037 [US3] Wire `CompetitionChart` into `frontend/app/analytics/page.tsx`.
- [x] T038 [P] [US3] Extend `tests/api/test_analytics_api.py` (competition section) and add `frontend/components/analytics/__tests__/CompetitionChart.test.tsx`.

**Checkpoint**: US1–US3 render independently; the headline answers the bidding-window question.

---

## Phase 6: User Story 4 - Outcome analytics & missed opportunities (Priority: P4)

**Goal**: Hired-vs-no-hire share among concluded projects, mean + median time-to-close, and a count + list of
hired projects the owner never applied to.

**Independent Test**: Seed concluded outcomes (hired / closed-no-hire / open / unknown) + personal records;
shares cover only concluded (open excluded, unknown not folded into hired); time-to-close shows mean + median;
the missed list = hired ∧ never-applied; an outlier doesn't move the median headline.

- [x] T039 [P] [US4] Unit tests for `outcome_analytics` in `tests/unit/test_analytics_aggregates.py`: shares over concluded only (open excluded, `unknown` separate), mean+median+IQR time-to-close, the missed-opportunity join (no record OR `applied_at IS NULL`), and `enough_data`.
- [x] T040 [US4] Implement `outcome_analytics` in `src/mostaql_notifier/analytics/aggregates.py` (contracts §5; reuse the `Outcome` enum; `closed_observed_at − posting_time`).
- [x] T041 [P] [US4] Create `frontend/components/analytics/OutcomesPanel.tsx` (hired/no-hire share + mean/median time-to-close + the missed-opportunities list with links).
- [x] T042 [US4] Wire `OutcomesPanel` into `frontend/app/analytics/page.tsx`.
- [x] T043 [P] [US4] Extend `tests/api/test_analytics_api.py` (outcomes section + missed list) and add `frontend/components/analytics/__tests__/OutcomesPanel.test.tsx`.

**Checkpoint**: US1–US4 render independently; missed opportunities are visible.

---

## Phase 7: User Story 5 - My funnel (Priority: P5)

**Goal**: The monotonic personal funnel seen → favourited → applied → in_discussion → won with step conversion
rates and the applied-step lag (others honestly "unavailable").

**Independent Test**: Seed personal records across stages; counts are monotonic; step rates are stage/prev with
a zero denominator shown unavailable; the applied lag (median) is shown, the favourited/discussion/won lags as
"غير متاح"; a mostly-empty funnel renders without divide-by-zero.

- [x] T044 [P] [US5] Unit tests for `funnel` in `tests/unit/test_analytics_aggregates.py`: monotonic stage counts, `conv_from_prev` incl. zero-denominator → `None`, the applied lag median, the unavailable lags, status ranking from the configured `personal_statuses`, and `enough_data`.
- [x] T045 [US5] Implement `funnel` in `src/mostaql_notifier/analytics/aggregates.py` (contracts §6; reuse `personal/statuses.py` ordering + `APPLIED_KEY`; monotonic `reached_*` model from research R4).
- [x] T046 [P] [US5] Create `frontend/components/analytics/FunnelChart.tsx` (CSS horizontal funnel bars per stage + conversion % + lag or "غير متاح").
- [x] T047 [US5] Wire `FunnelChart` into `frontend/app/analytics/page.tsx`.
- [x] T048 [P] [US5] Extend `tests/api/test_analytics_api.py` (funnel section) and add `frontend/components/analytics/__tests__/FunnelChart.test.tsx`.

**Checkpoint**: US1–US5 render independently; the funnel shows where the owner drops off.

---

## Phase 8: User Story 6 - Insights / tips engine (Priority: P6)

**Goal**: A short, ranked list of plain-language tips, each backed by its aggregate and shown only above its
configurable minimum support; rules over the owner's own data, no external AI.

**Independent Test**: With enough history, the expected tips appear (peak window, bid speed, win timing,
suggested score threshold, budget fallback), each citing its data; lower the data below a tip's support and the
tip disappears entirely; no tip is produced by any external service.

- [x] T049 [P] [US6] Unit tests `tests/unit/test_analytics_tips.py`: each rule fires above support and is withheld below it; the suggested-threshold replay (highest T keeping ≥ `analytics_suggested_threshold_keep` of wins); the budget-fallback rule from `qualify.budget_policy.load_policy` state; ranking + the `analytics_max_tips` cap; and "no external call" by construction.
- [x] T050 [US6] Implement the real rules in `src/mostaql_notifier/analytics/tips.py` (replace the skeleton) per contracts §7 — `peak_window`, `bid_speed`, `win_timing`, `score_threshold` (advisory replay), `budget_fallback`; rank + truncate to `analytics_max_tips`; each emits `Tip(key, text_ar, evidence)`.
- [x] T051 [P] [US6] Create `frontend/components/analytics/TipsPanel.tsx` (ranked plain-Arabic tips, each with its supporting figures; empty when none clear support).
- [x] T052 [US6] Wire `TipsPanel` into `frontend/app/analytics/page.tsx`.
- [x] T053 [P] [US6] Extend `tests/api/test_analytics_api.py` (tips present above support, absent below) and add `frontend/components/analytics/__tests__/TipsPanel.test.tsx`.

**Checkpoint**: US1–US6 render independently; tips synthesize the charts into actionable sentences.

---

## Phase 9: User Story 7 - Filter, refresh & trust (Priority: P7)

**Goal**: The cross-cutting guarantees — one date filter scoping everything, manual refresh, the strictly
read-only guarantee, RTL + responsive, behind auth.

**Independent Test**: Set a range and every chart/tip recomputes consistently; a manual refresh shows the latest
data; snapshotting the project/score/snapshot/personal tables before and after using the whole section shows
**zero** row changes; Arabic renders RTL and reads well on phone + laptop.

- [x] T054 [P] [US7] Read-only assertion test in `tests/api/test_analytics_api.py`: snapshot row counts + content of `projects`/`project_scores`/`project_snapshots`/`personal_records` before and after a series of `/api/analytics/overview` calls (varied ranges) and assert unchanged (SC-008, Constitution IV).
- [x] T055 [P] [US7] Date-scoping integration test in `tests/api/test_analytics_api.py`: the same `date_from`/`date_to` consistently scope every section; `range.default_applied` true when omitted; 422 on inverted range; 401 unauthenticated.
- [x] T056 [US7] Frontend `frontend/app/analytics/page.tsx`: confirm the single `DateRangeFilter` scopes all section cards, add a manual-refresh affordance, and distinguish "the selected range has no data" from "not enough data yet" across cards.
- [x] T057 [P] [US7] RTL + responsive pass across all `frontend/components/analytics/*` charts (phone + laptop viewports, Arabic labels, `Bidi` isolation, RTL axes like `BidChart`).
- [x] T058 [P] [US7] Frontend vitest `frontend/app/analytics/__tests__/page.test.tsx`: the date-filter wiring scopes the whole page and the empty/not-enough-data ladder renders.

**Checkpoint**: All seven stories work; the section is consistent, trustworthy, read-only, and RTL/responsive.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Docs, config-over-code audit, and the full-gate run.

- [x] T059 [P] Update `README.md`: add an "analytics" section to the dashboard feature list (the new التحليلات tab; read-only; no new process/migration).
- [x] T060 [P] Config-over-code audit of `src/mostaql_notifier/analytics/`: confirm no behaviour-affecting literal is hard-coded (every threshold/timezone read from `settings`); add module docstrings (Constitution III).
- [x] T061 Run `quickstart.md` validation: seed the new settings, exercise every section, and run the read-only count-before/after check.
- [x] T062 Run the full gate `bash scripts/ci.sh` (alembic no-op delta + ruff + pytest + frontend lint/test/build) and confirm green.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately. T002 (DEFAULTS) precedes T003 (settings_spec registration).
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS all user stories.** Internal order: T004 (tz) and T006 (DTOs) → T007 (aggregates stubs) + T008 (tips skeleton) → T009 (service) → T010 (router) → T011 (mount) → T012 (API scaffold test); frontend T013–T019 depend only on T006's DTO shapes (can proceed in parallel with the backend once T006 lands), and T018 (page shell) depends on T013/T014/T017 (api/hook/date-filter).
- **User Stories (Phases 3–8)**: Each depends only on Foundational. They can proceed in parallel (different aggregate functions + different chart files), but **note the shared files** below force light serialization.
- **US7 (Phase 9)**: Best done after the sections exist (it asserts cross-section consistency + read-only over the whole endpoint), though the read-only test (T054) can be written any time after Foundational.
- **Polish (Phase 10)**: After all desired stories.

### Shared-file serialization (important)

- `src/mostaql_notifier/analytics/aggregates.py` is edited by US1–US5 (one function each). Different functions, but the **same file** — land them in story order (or coordinate) to avoid edit collisions. The `[P]` markers within a story apply to its *tests + chart component* (different files), not to the aggregates.py edit.
- `frontend/app/analytics/page.tsx` is edited by Foundational (shell) + each story's "wire-in" task — sequential by nature (each adds a card).
- `tests/api/test_analytics_api.py` is extended by every story + US7 — append-only, sequential.

### User Story Dependencies

- **US1 (P1)** — after Foundational. No dependency on other stories. **MVP.**
- **US2–US6 (P2–P6)** — after Foundational; independent of each other (each adds one aggregate + one chart).
- **US7 (P7)** — after Foundational; most valuable once US1–US6 sections exist.

### Within Each User Story

- The unit test (TDD) is written first and fails, then the aggregate is implemented; the chart component (own file, `[P]`) and the wire-in (edits `page.tsx`, sequential) follow; the API/vitest coverage closes the story.

---

## Parallel Opportunities

- **Setup**: T003 `[P]` alongside T001/T002 once T002's keys exist.
- **Foundational**: after T006 (DTOs), the frontend shell tasks T013/T014/T015/T016/T019 are all `[P]` (different files); T005 `[P]` (tz test) runs alongside the DTO/service work.
- **Across stories**: once Foundational is done, US1–US6 can be staffed in parallel — each owns a distinct chart file and a distinct aggregates.py function (serialize only the aggregates.py writes and the page.tsx wire-ins).
- **Within a story**: the `[P]` unit test, the `[P]` chart component, and the `[P]` vitest run in parallel; only the aggregates.py impl and the page.tsx wire-in are sequential.

### Parallel Example: Foundational frontend shell (after T006 DTOs land)

```bash
Task: "T013 Add getAnalyticsOverview + types to frontend/lib/api.ts + frontend/lib/types.ts"
Task: "T014 Add frontend/lib/useAnalytics.ts"
Task: "T015 Add date-only + percent formatters to frontend/lib/format.ts"
Task: "T016 Add analytics nav item to frontend/components/Nav.tsx"
Task: "T019 Add التحليلات group to frontend/components/SettingsForm.tsx"
```

### Parallel Example: User Story 2 (after Foundational)

```bash
# Tests first (different files, parallel):
Task: "T026 Unit tests volume_trends in tests/unit/test_analytics_aggregates.py"
Task: "T027 Unit tests budget_distribution in tests/unit/test_analytics_aggregates.py"
# Chart components (different files, parallel):
Task: "T030 Create frontend/components/analytics/VolumeChart.tsx"
Task: "T031 Create frontend/components/analytics/BudgetChart.tsx"
# Then sequential: T028, T029 (aggregates.py), then T032 (wire-in)
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 (Setup) → Phase 2 (Foundational — the section shell + endpoint) → Phase 3 (US1 heatmap).
2. **STOP and VALIDATE**: the analytics section renders with a working posting heatmap, behind auth, scoped by
   the date filter, honest on a near-empty DB. Demo it.

### Incremental Delivery

1. Setup + Foundational → the empty section shell ships (every chart "not enough data yet").
2. US1 (heatmap) → **MVP** → demo.
3. US2 (volume + budget) → demo. 4. US3 (competition) → demo. 5. US4 (outcomes) → demo. 6. US5 (funnel) →
   demo. 7. US6 (tips) → demo.
8. US7 (filter/refresh/trust) → the trust + RTL/responsive + read-only guarantees.
9. Polish → docs + config audit + full CI gate.

Each story adds one chart to the same section without breaking the previous ones — the endpoint already returns
every section (stubs until implemented), so a half-built section degrades to honest "not enough data yet"
states rather than errors.

### Parallel Team Strategy

After Foundational, assign US1–US6 to different developers (each owns a chart file + an aggregates.py function);
coordinate the shared `aggregates.py` / `page.tsx` / `test_analytics_api.py` edits in story order. US7 + Polish
close out once the sections exist.

---

## Notes

- **No migration / no new table / no new process / no new dependency** — this feature is read-only aggregation
  over Features 1–4 data; the only new persisted state is the Setup-phase `settings` rows.
- **Honest under thin data** is a per-section contract: every aggregate returns `enough_data`, and tips are
  withheld below support — keep this true as each story lands (don't let a half-real section fake a conclusion).
- **Read-only is a test gate** (T054), not just a convention — the section must change zero rows.
- **Config over code**: every threshold/timezone is a `settings` row (T002/T003); the audit (T060) enforces it.
