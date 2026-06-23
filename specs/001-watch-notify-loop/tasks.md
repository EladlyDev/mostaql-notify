---
description: "Task list for Watch-and-Notify MVP Loop"
---

# Tasks: Watch-and-Notify MVP Loop

**Input**: Design documents from `/specs/001-watch-notify-loop/`
**Prerequisites**: plan.md, spec.md, data-model.md, research.md, contracts/

**Tests**: Test tasks ARE included — the feature request explicitly asked for parser tests and
qualification/hysteresis tests, and the spec's success criteria (SC-002/003/004/005) are
constitution-critical, so a focused set of integration tests is included too. Tests are NOT blanket TDD;
they target the parser, the qualifier/hysteresis, and the fail-closed / dedup / block-detection behavior.

**Organization**: Tasks are grouped by user story (P1 → P2 → P3). Foundational infrastructure shared by
all stories is in Phase 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 (no label for Setup, Foundational, Polish)
- All paths are relative to the repository root.

## Path conventions

Single-project worker. Code under `src/mostaql_notifier/`, tests under `tests/`, migrations under
`alembic/`. Selectors live ONLY in `src/mostaql_notifier/scraper/mostaql.py`; the fetch layer sits
behind `src/mostaql_notifier/scraper/fetcher.py`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton, dependencies, secrets/ignore hygiene.

- [x] T001 Create the package skeleton per plan.md: `src/mostaql_notifier/` with subpackages `worker/`,
  `scraper/`, `parsing/`, `qualify/`, `notify/`, `db/`, `config/` (each with `__init__.py`), plus
  `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `data/`, and `alembic/`.
- [x] T002 [P] Define `pyproject.toml` with runtime deps (`httpx[http2]`, `selectolax`, `apscheduler`,
  `python-telegram-bot[rate-limiter]`, `sqlalchemy>=2`, `alembic`, `pydantic-settings`, `tzdata`) and dev
  deps (`pytest`, `pytest-asyncio`, `ruff`); `playwright` as an optional extra. Add console entry
  `mostaql-notifier = "mostaql_notifier.__main__:run"`.
- [x] T003 [P] Add `.gitignore` (`.env`, `data/`, `*.db`, `*.sqlite*`, captured HTML snapshots,
  `.venv/`, `__pycache__/`) and a committed `.env.example` documenting `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `DATABASE_URL=sqlite:///./data/mostaql.db` (constitution IX).
- [x] T004 [P] Add `ruff`/formatting config to `pyproject.toml` and a `pytest` config section
  (`pytest-asyncio` mode = auto).

**Checkpoint**: `pip install -e .` succeeds; repo has no secrets committed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: DB layer, models + migration + seeded settings, config loaders, the fetch layer + politeness,
and golden fixtures. **No user story can be implemented until this phase is complete.**

**⚠️ CRITICAL**: Everything here is shared by US1/US2/US3.

### Database layer

- [x] T005 [P] Implement portable types in `src/mostaql_notifier/db/types.py`: `UtcDateTime`
  (`TypeDecorator`, impl `DateTime(timezone=True)`, `cache_ok=True`; reject naive on write, return aware
  UTC on read), `JSONType = sa.JSON().with_variant(postgresql.JSONB, "postgresql")`, and a `make_enum()`
  helper using `Enum(PyEnum, native_enum=False, name=...)` (research §3).
- [x] T006 [P] Implement `src/mostaql_notifier/db/base.py`: `Base` with
  `MetaData(naming_convention={...ix/uq/ck/fk/pk...})` so Alembic batch mode can target constraints.
- [x] T007 Implement `src/mostaql_notifier/db/models.py` — all six entities per data-model.md: `clients`,
  `projects` (incl. `eval_status`, `eval_attempts`, `last_eval_at`, `qualified_at`, `tier`, `notified`,
  `site_status` enums; unique `mostaql_id`; indexes on `client_id`/`posted_at`/`scraped_at`/
  `qualified_at`/`eval_status`), `scrape_runs`, `notifications_log` (unique `dedup_key`), `settings`,
  `app_state`. Money columns use `Numeric`; timestamps use `UtcDateTime`; `raw`/`skills` use `JSONType`.
  (depends on T005, T006)
- [x] T008 [P] Implement `src/mostaql_notifier/db/session.py`: engine + session factory built from
  `DATABASE_URL`; enable SQLite `PRAGMA foreign_keys=ON` at connect.
- [x] T009 [P] Implement the cross-dialect upsert helper in `src/mostaql_notifier/db/upsert.py`: select
  `sqlite_insert` vs `pg_insert` by `engine.dialect.name`, build
  `insert().on_conflict_do_update(index_elements=["mostaql_id"], set_={...excluded...})` (research §3).
- [x] T010 Initialize Alembic in `alembic/` with `env.py` set to `render_as_batch=True` and bound to
  `Base.metadata`; generate the initial migration creating all six tables. (depends on T007)

### Config & settings store

- [x] T011 [P] Implement `src/mostaql_notifier/config/secrets.py` using `pydantic-settings` to load
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL` from `.env` (typed, fail-loud if missing).
- [x] T012 Implement `src/mostaql_notifier/config/settings_store.py`: typed get/get-int/get-float/
  get-bool/get-json readers over the `settings` table, plus a `seed_defaults()` that inserts every key in
  data-model.md (`poll_interval_seconds=120`, floors, target/buffer/window, `min_hiring_rate=0`,
  delay/backoff/detection knobs, `currency_usd_rates`, `owner_timezone`, `listing_url`, etc.) only when
  absent. (depends on T007, T008)
- [x] T013 [P] Implement `app_state` accessors in `src/mostaql_notifier/config/settings_store.py` (or
  `db/app_state.py`): get/set for `active_budget_floor`, `last_successful_poll_at`, `last_heartbeat_at`,
  `run_header_set`, circuit-breaker state. (depends on T007)

### Fetch layer + politeness (the swap seam)

- [x] T014 [P] Define `src/mostaql_notifier/scraper/fetcher.py`: `FetchResult` dataclass (url, status,
  body, body_bytes, headers, elapsed_ms, error) and the `Fetcher` Protocol (`async get(url, referer=)`,
  `async aclose()`) per contracts/fetcher-interface.md.
- [x] T015 Implement `src/mostaql_notifier/scraper/httpx_fetcher.py`: one persistent
  `httpx.AsyncClient(http2=True, follow_redirects=True)`, cookie jar, per-request `Referer`, ~20 s
  timeout; never raises on HTTP status (returns it), returns `status=0` on transport error. (depends T014)
- [x] T016 [P] Implement `src/mostaql_notifier/scraper/playwright_fetcher.py` as a lazily-constructed
  fallback honoring the same Protocol; if Playwright isn't installed, log + raise a typed "fallback
  unavailable" signal (handled by the orchestrator as alert+skip). (depends on T014)
- [x] T017 Implement `src/mostaql_notifier/worker/politeness.py`: randomized inter-request delay
  (`delay_min/max`), stable per-run header-set selection from a small pool (UA + `sec-ch-ua` + Accept +
  `Accept-Language: ar,...`), and per-request exponential backoff honoring `Retry-After` (int **and**
  HTTP-date), all read from settings (config-over-code). (depends on T012, T014)

### Golden fixtures

- [x] T018 [P] Capture and commit golden HTML fixtures under `tests/fixtures/`: `listing.html`
  (`/projects/development`), `project_page.html`, `client_profile.html`, and `challenge.html`; plus a
  **synthetic** `client_not_calculated.html` containing `لم يحسب بعد` (never observed live — research R13).
  Include a short `tests/fixtures/README.md` noting capture date/source and the synthetic case.

**Checkpoint**: `alembic upgrade head` builds the schema; settings seed on first start; the fetch layer
and politeness are importable; fixtures exist. User-story work can begin.

---

## Phase 3: User Story 1 - Near-real-time alerts for qualifying projects (Priority: P1) 🎯 MVP

**Goal**: End-to-end loop — poll the listing, ingest new projects idempotently, fetch each project page
(+ client profile), qualify fail-closed against the **static primary floor (Tier 1)**, store raw+parsed,
and push qualifying projects to Telegram exactly once. Scheduler + bot run together.

**Independent Test**: Run a poll cycle against the golden fixtures with a qualifying project (hiring rate
> 0, budget ≥ $250) → exactly one Telegram message with title, budget+tier, hiring rate, bid count, time
since posting, category, link; a second cycle sends nothing for it; first-ever run sends nothing.

### Parsing (Arabic-first) — with tests

- [x] T019 [P] [US1] Implement `src/mostaql_notifier/parsing/arabic.py`: `normalize_text` (NFKC; both
  Arabic-Indic U+0660–0669 and Persian U+06F0–06F9 digits → ASCII; thousands/decimal/percent; strip bidi
  marks + tatweel), `parse_budget` (→ min,max,currency; `$`/`دولار`→USD else None+log), `parse_hiring_rate`
  (`يحسب` stem → None; else `(\d+(?:\.\d+)?)%`), `parse_relative_time(s, now_utc)` (strip `منذ`/`قبل`;
  Arabic stem units + dual forms; unit-seconds from settings) per contracts/parsing-and-qualification.md.
- [x] T020 [P] [US1] Write parser unit tests in `tests/unit/test_arabic_parsing.py` against the exact
  verbatim strings from research (`منذ 12 دقيقة`, `منذ ساعتين`, `$250.00 - $500.00`, `$10,000.00`,
  `50.00%`, `0.00%`, `لم يحسب`, `لم يحسب بعد`) plus synthetic Arabic-Indic/Persian digit variants; assert
  fail-closed (`None`) on unrecognized input. (can be written alongside T019)

### Mostaql selector module

- [x] T021 [US1] Implement `src/mostaql_notifier/scraper/mostaql.py`: `parse_listing(html)` →
  `[mostaql_id, url]` via `div.project-row` / `a[href*="/project/"]`; `parse_project_page(html)` →
  project fields + client-sidebar hiring rate/stats (single source of truth); `parse_profile_page(html)` →
  full client record. Uses `parsing/arabic.py`; emits the fail-loud sentinel on zero rows / missing
  hiring-rate row. (depends on T019; verify against T018 fixtures)
- [x] T022 [P] [US1] Write selector tests in `tests/unit/test_mostaql_parse.py` asserting 25 listing rows,
  correct id extraction, project-page budget/status/hiring-rate, and that `client_not_calculated.html`
  yields `hiring_rate=None`. (depends on T021)

### Ingestion (idempotent) + client fetch/cache

- [x] T023 [US1] Implement listing discovery + idempotent upsert in `src/mostaql_notifier/worker/poll.py`:
  diff listing ids vs seen (`projects.mostaql_id`), upsert via `db/upsert.py` (update
  `bids_count`/`site_status`/`scraped_at` on existing; insert new as `eval_status=pending`), and the
  **first-run baseline** (when seen-state empty and `baseline_on_first_run`, insert all visible ids as
  `eval_status=baseline`, notify nothing — research R7). (depends on T009, T012, T021)
- [x] T024 [US1] Implement project-page fetch + client-profile fetch with the 12 h cache in
  `src/mostaql_notifier/scraper/mostaql.py`/`worker/poll.py`: for each new/pending project fetch the
  project page; if it passes cheap filters, fetch the `/u/` profile only when
  `now − client.last_refreshed_at ≥ client_refresh_hours`; store raw+parsed; on fetch/parse failure bump
  `eval_attempts` and keep `pending` (terminal `eval_error` past `max_eval_attempts`/`pending_max_age_hours`)
  — research R3/R4. (depends on T015, T017, T023)

### Qualification (static floor) — with tests

- [x] T025 [P] [US1] Implement `src/mostaql_notifier/qualify/filters.py`: fail-closed `qualify()` (hiring
  rate not NULL and `> min_hiring_rate`; USD-normalized budget by `budget_comparison_basis` ≥ floor,
  one-sided→available bound, none/unmapped currency→disqualify; `site_status==open`; category; exclusion
  pass-through). For US1 the floor is the static `budget_primary_floor` (Tier 1). (depends on T012)
- [x] T026 [P] [US1] Write qualification unit tests in `tests/unit/test_qualify.py`: NULL hiring rate
  disqualifies (Scenario 1.3); `0.00%` disqualifies via a distinct path (Scenario 1.2); missing budget,
  one-sided budget, and unmapped currency each disqualify; a valid Tier-1 project qualifies. (depends T025)

### Notification (Telegram) + dedup

- [x] T027 [P] [US1] Implement `src/mostaql_notifier/notify/format.py`: HTML project-notification builder
  with the required fields (title, budget+tier, hiring rate, bid count, time-since-posting re-derived at
  render, category, link), HTML-escaped, owner-timezone aware, < 4096 chars (contracts/telegram-message.md).
- [x] T028 [US1] Implement `src/mostaql_notifier/notify/telegram.py`: `ExtBot(token,
  rate_limiter=AIORateLimiter(max_retries=3))` sender with a bounded retry for `TimedOut`/`NetworkError`;
  dedup-guarded send — insert `notifications_log` (unique `dedup_key="telegram:project:<mostaql_id>"`) +
  flip `projects.notified=true` in **one transaction**, committed right after a successful send (research
  R9). Skip if `dedup_key` exists. (depends on T011, T027)

### Orchestration + scheduler/entrypoint

- [x] T029 [US1] Complete the poll cycle in `src/mostaql_notifier/worker/poll.py`: discover → ingest →
  for each new/pending project evaluate (fetch, parse, qualify static) → notify qualifying → write a
  `scrape_runs` record (found/new/updated/errors); wrap each project in try/skip so one failure increments
  `error_count` without crashing the run. (depends on T023, T024, T025, T028)
- [x] T030 [US1] Implement the entrypoint in `src/mostaql_notifier/worker/main.py` + `__main__.py`:
  `asyncio.run(main())`; `async with ExtBot(...)`; build `AsyncIOScheduler()` inside the loop; add the
  poll job (`IntervalTrigger(seconds=poll_interval)`, `coalesce=True`, `max_instances=1`,
  `misfire_grace_time`); `SIGTERM/SIGINT` → graceful `scheduler.shutdown(wait=True)`; seed settings on
  start (research §2). (depends on T012, T029)
- [x] T031 [US1] Write an integration test in `tests/integration/test_poll_cycle.py` driving one poll
  against fixtures (fetcher stubbed to return fixture HTML): asserts exactly one notification for a
  qualifying project, no duplicate on a second cycle, and that a first-ever run with `baseline_on_first_run`
  notifies nothing. (depends on T029)

**Checkpoint**: US1 is a runnable MVP — given `.env` credentials it polls, qualifies (static floor),
stores, and notifies, with run logging. Independently demoable.

---

## Phase 4: User Story 2 - Stay alive: health alerts, block detection, run visibility (Priority: P2)

**Goal**: Make the loop safe to leave running — detect blocks/structure changes and alert+back off, never
die silently, and make downtime observable.

**Independent Test**: Inject a 403, a 429, a CAPTCHA marker, and a zero-rows-on-non-empty listing → each
yields a Telegram health alert + back-off and does NOT advance seen-state or `last_successful_poll_at`; a
single bad project is skipped (run `partial`) not fatal; stopping the loop is detectable via heartbeat
staleness.

- [x] T032 [US2] Implement block/structure-change classification in
  `src/mostaql_notifier/worker/circuit_breaker.py`: classify a listing `FetchResult` as
  `BLOCKED`/`TRANSIENT`/`CHALLENGE`/`STRUCTURE_CHANGE` using status, `challenge_markers`,
  `block_body_max_bytes`, and the "clearly non-empty" rule (`nonempty_body_min_bytes` + `listing_shell_markers`
  + not `empty_state_markers`); cross-check two selectors (research §5). (depends on T012, T021)
- [x] T033 [US2] Implement the circuit breaker (pause/cooldown with doubling to a ceiling) and the
  escalation-to-Playwright trigger in `src/mostaql_notifier/worker/circuit_breaker.py`; persist breaker
  state in `app_state`; on `BLOCKED`/`CHALLENGE`/`STRUCTURE_CHANGE` do not advance seen-state and do not
  update `last_successful_poll_at`. (depends on T013, T032)
- [x] T034 [P] [US2] Extend `src/mostaql_notifier/notify/format.py` with the health-alert and heartbeat
  builders (type, detail, action/resume time, run counts) per contracts/telegram-message.md.
- [x] T035 [US2] Wire health alerts into `src/mostaql_notifier/worker/poll.py` and
  `src/mostaql_notifier/worker/circuit_breaker.py`: send an alert on state transitions (de-duplicated,
  not every cycle) and on recovery; set `scrape_runs.status` to `blocked`/`failed`/`partial` accordingly.
  (depends on T032, T033, T034, T029)
- [x] T036 [US2] Add the APScheduler `add_listener(on_job_error, EVENT_JOB_ERROR | EVENT_JOB_MISSED)` in
  `src/mostaql_notifier/worker/main.py` → loud log + Telegram alert (APScheduler otherwise swallows job
  exceptions — research §2). (depends on T030)
- [x] T037 [US2] Implement heartbeat + downtime self-check: persist `last_successful_poll_at` on each
  successful poll; a scheduled job sends a heartbeat every `heartbeat_hours` and alerts when
  `now − last_successful_poll_at > 2 × poll_interval`; document the box-fully-dead limitation (research R11).
  (depends on T013, T030, T034)
- [x] T038 [P] [US2] Write integration tests in `tests/integration/test_block_detection.py`: 403/429/
  CAPTCHA/empty-on-non-empty each → health alert + no state advance + no `last_successful_poll_at` update;
  a project that raises is skipped (run `partial`), loop survives. (depends on T035)

**Checkpoint**: US1 + US2 — the loop is resilient and observable, safe to run unattended.

---

## Phase 5: User Story 3 - Dynamic two-tier budget with anti-flapping (Priority: P3)

**Goal**: Adapt the budget floor to recent Tier-1 volume with hysteresis, labeling Tier 2 clearly.

**Independent Test**: Drive Tier-1 volume below the target → floor lowers to $100, $100–$249 projects
qualify labeled Tier 2; drive above target+buffer → floor restores to $250; hold in the dead-band → no
switch.

- [x] T039 [US3] Implement `src/mostaql_notifier/qualify/budget_policy.py`: `recompute_floor()` keyed on
  the **rolling `fallback_window_hours` count of `tier==1` projects by authoritative `qualified_at`**
  (research R5); 250→100 when `< fallback_target`; 100→250 when `> fallback_target + fallback_buffer`;
  dead-band otherwise; persist `active_budget_floor` in `app_state`. (depends on T013)
- [x] T040 [US3] Wire the dynamic floor into the cycle and qualifier: call `recompute_floor()` once per
  poll **before** evaluating projects; pass `active_floor` into `qualify()`; set `tier` (≥250→1,
  [floor,250)→2) and `qualified_at` on qualification. (depends on T039, T025, T029)
- [x] T041 [P] [US3] Ensure Tier-2 labeling renders in `notify/format.py` (notification states the tier).
  (depends on T027)
- [x] T042 [P] [US3] Write hysteresis unit tests in `tests/unit/test_budget_policy.py`: below-target →
  lower; above target+buffer → restore; dead-band → no change; window counts only `qualified_at` within
  the window; persistence round-trips through `app_state`. (depends on T039)
- [x] T043 [P] [US3] Write an integration test in `tests/integration/test_dynamic_budget.py`: with a low
  Tier-1 window a $150 project qualifies as Tier 2 and is notified labeled Tier 2; after recovery the
  $250 floor is restored. (depends on T040)

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final hardening and validation.

- [x] T044 [P] Implement `python -m mostaql_notifier.notify.selfcheck` to send a test message to
  `TELEGRAM_CHAT_ID` (verifies wiring without scraping; referenced in quickstart.md).
- [x] T045 [P] Add a short `README.md` linking to `specs/001-watch-notify-loop/quickstart.md` and a
  sample `systemd` unit (`Restart=always`) per the single-box ops note (research R11).
- [x] T046 [P] Run `ruff` + ensure all modules import cleanly; add a minimal CI-style script that runs
  `alembic upgrade head` against a fresh SQLite file then `pytest` (catches batch-migration breakage).
- [x] T047 Validate `quickstart.md` end-to-end on a scratch DB (seed → first-run baseline sends nothing →
  stubbed poll notifies once); fix any drift between docs and code.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. **Blocks all user stories.**
- **US1 (Phase 3)**: depends on Foundational. The MVP.
- **US2 (Phase 4)**: depends on Foundational; builds on the US1 poll cycle (T029/T030).
- **US3 (Phase 5)**: depends on Foundational; builds on the US1 qualifier/cycle (T025/T029).
- **Polish (Phase 6)**: depends on the stories being delivered.

### Story independence

- US1 is fully independent once Foundational is done (delivers the MVP with the static floor).
- US2 and US3 each extend US1 but are independently testable (US2 via injected block signals; US3 via
  driven Tier-1 volume) and do not depend on each other — they may proceed in parallel after US1.

### Within US1

Parsers (T019) → selector module (T021) → ingestion (T023) → fetch/cache (T024) → orchestration (T029).
Qualifier (T025) and notification (T027/T028) can proceed in parallel with the scraping chain; T029 joins
them; T030 wires the scheduler; T031 tests the cycle.

---

## Parallel Execution Examples

**Phase 2 (Foundational)** — independent files can run together:

```text
T005 (db/types.py)   T006 (db/base.py)   T008 (db/session.py)   T009 (db/upsert.py)
T011 (config/secrets.py)   T014 (scraper/fetcher.py)   T016 (playwright_fetcher.py)   T018 (fixtures)
```

**US1** — parser, qualifier, and formatter are independent files:

```text
T019 (parsing/arabic.py) + T020 (parser tests)
T025 (qualify/filters.py) + T026 (qualify tests)
T027 (notify/format.py)
```

**US3** — tests parallel to wiring:

```text
T042 (test_budget_policy.py)   T043 (test_dynamic_budget.py)   T041 (Tier-2 label render)
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & validate** (T031): the loop polls,
qualifies on the static floor, stores, and notifies once. Deploy/demo with real `.env` credentials.

### Incremental delivery

- Add **US2** → loop is resilient and observable (safe to leave running). Demo block-alert behavior.
- Add **US3** → funnel adapts during dry spells with hysteresis. Demo Tier-2 widening + recovery.

### Notes

- `[P]` = different files, no incomplete dependency. Same-file tasks are sequential.
- Tests included per the explicit request: parser (T020, T022), qualifier (T026), hysteresis (T042),
  plus constitution-critical integration tests (T031 dedup/baseline, T038 block detection, T043 dynamic
  budget).
- Constitution gates honored throughout: config-over-code (all knobs from `settings`), fail-closed
  qualification (T025/T026), polite access (T017), fail-loud (T032–T038), idempotent + non-destructive
  (T023/T024), Arabic-first (T019/T020), no platform automation (read-only fetch layer).
- The repo has no commits yet, so spec-kit scripts need `SPECIFY_FEATURE=001-watch-notify-loop` until an
  initial commit exists.
