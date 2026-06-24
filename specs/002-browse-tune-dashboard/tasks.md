---
description: "Task list for Feature 2 — Browse-and-Tune Dashboard"
---

# Tasks: Browse-and-Tune Dashboard

**Input**: Design documents from `/specs/002-browse-tune-dashboard/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml

**Tests**: Test tasks are included where the spec/owner asked for them — the projects-list
filtering/search logic (US1), the settings validation (US3), and the auth gate (foundational). Other
screens are validated via the quickstart smoke checks in the Polish phase.

**Organization**: Tasks are grouped by user story. Each story is a vertical slice (its backend
endpoint + its screen) that is independently testable. Backend-before-UI is preserved *within* each
story (endpoint task precedes the screen task that consumes it).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4 (Setup, Foundational, Polish carry no story label)

## Path Conventions

- **Backend** (existing Python package/venv): `src/mostaql_notifier/api/`, tests in `tests/api/`
- **Frontend** (new Next.js app): `frontend/`
- **Deploy**: `deploy/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project dependencies and skeletons for both backend and frontend.

- [X] T001 Add an `api` optional-dependency group to `pyproject.toml` (`fastapi`, `uvicorn[standard]`, `itsdangerous`, `passlib`) and create the package dir `src/mostaql_notifier/api/__init__.py`.
- [X] T002 [P] Add dashboard secrets to `src/mostaql_notifier/config/secrets.py` (`dashboard_auth_enabled: bool = True`, `dashboard_password: str = ""`, `dashboard_session_secret: str = ""`, `frontend_origin: str = "http://localhost:3000"`) and document them as blanks in `.env.example`.
- [X] T003 [P] Scaffold the Next.js app in `frontend/` (App Router, TypeScript, Tailwind CSS) and install the shadcn/ui component kit and TanStack Query; add `frontend/.env.local.example` with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The FastAPI app, shared DB access with WAL, the auth gate (gates *every* route), and the
RTL frontend shell. **No user story can be completed until this phase is done.**

**⚠️ CRITICAL**: Auth, app factory, WAL, and the shell are cross-cutting — every story depends on them.

### Backend foundation

- [X] T004 Enable SQLite **WAL + busy_timeout** in `src/mostaql_notifier/db/session.py` by extending the existing sqlite `connect` event listener (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` alongside the existing `foreign_keys=ON`) so worker and API share it.
- [X] T005 Create the FastAPI app factory in `src/mostaql_notifier/api/app.py`: instantiate `FastAPI()`, add `CORSMiddleware` restricted to `frontend_origin` with `allow_credentials=True` and methods `GET/POST/PUT/OPTIONS`, wire routers, and on startup call `get_engine()` so the WAL pragma is applied; add a fail-loud check (if `dashboard_auth_enabled` and `dashboard_password` empty → raise at startup).
- [X] T006 [P] Create a request-scoped read session dependency in `src/mostaql_notifier/api/deps.py` reusing `get_sessionmaker()`, yielding a session and closing it per request; map DB errors to HTTP 503.
- [X] T007 [P] Create shared response DTOs in `src/mostaql_notifier/api/schemas.py` (`ProjectListItem`, `ProjectListResponse`, `ClientPanel`, `ProjectDetail`, `HomeOverview`, `SettingItem`, `SettingsResponse`, `AuthStatus`, error bodies) matching `contracts/openapi.yaml`; ensure null numerics serialize as `null` (never coerced to 0).
- [X] T008 Implement the auth gate in `src/mostaql_notifier/api/security.py`: constant-time password compare against `dashboard_password`, issue/verify an `itsdangerous`-signed HttpOnly `mn_session` cookie (SameSite=Lax, configurable TTL), an `require_auth` dependency that is a no-op when `dashboard_auth_enabled=false`; and `src/mostaql_notifier/api/routers/auth.py` with `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/status`.
- [X] T009 [P] Auth contract test in `tests/api/test_auth_api.py`: unauthenticated request to a protected route → 401; login with correct password sets cookie and grants access; wrong password → 401; with `dashboard_auth_enabled=false` the gate is bypassed.

### Frontend foundation

- [X] T010 [P] Configure RTL + bidi in `frontend/`: set `<html dir="rtl" lang="ar">` in `frontend/app/layout.tsx`, enable Tailwind logical properties / RTL and shadcn RTL config, and add shared formatters in `frontend/lib/format.ts` (owner-timezone absolute time, relative age, budget/number rendering wrapped in bidi isolation).
- [X] T011 Build the app shell in `frontend/app/layout.tsx` + `frontend/components/Nav.tsx`: persistent responsive navigation (Home / Projects / Settings + sign-out), the API client in `frontend/lib/api.ts` (sends credentials), TanStack Query provider, and reusable `frontend/components/states/` (Loading skeleton, EmptyNoData, Error) used by every screen.
- [X] T012 Create the login screen `frontend/app/login/page.tsx` wired to `POST /api/auth/login`, and `frontend/middleware.ts` redirecting unauthenticated requests to `/login` (reads the session cookie; honors the auth-disabled config via `GET /api/auth/status`).

**Checkpoint**: API runs with WAL + CORS + auth; frontend shell renders RTL and can log in. Story work can begin.

---

## Phase 3: User Story 1 — Secure access & browse the projects feed (Priority: P1) 🎯 MVP

**Goal**: A logged-in owner browses every collected project in table or card view, filters/sorts/searches it fast, with correct RTL and empty/loading/error states.

**Independent Test**: Seed a temp DB via Feature 1 models, log in, and confirm the feed lists all projects with every required field; each filter (and combinations), each sort, Arabic & Latin search, table/card toggle, and pagination work; unauthenticated access is redirected.

### Tests for User Story 1 ⚠️ (write first, ensure they fail)

- [X] T013 [P] [US1] Contract/integration test for `GET /api/projects` in `tests/api/test_projects_api.py`: each filter (tier, budget range, min hiring rate incl. NULL-rate exclusion, bids range, age window, site_status, qualified-only), each sort (posted_at desc default, budget, bids_count, hiring_rate; NULLs last), logical-AND combos, and pagination (`total`/`page`/`page_size`).
- [X] T014 [P] [US1] Keyword-search test in `tests/api/test_projects_search.py`: `q` matches Arabic and Latin substrings across title, description, and skills, and excludes non-matches.

### Implementation for User Story 1

- [X] T015 [US1] Implement the projects-list query builder in `src/mostaql_notifier/api/routers/projects.py` (`GET /api/projects`): outer-join Project→Client, apply all filters as logical AND, sort with NULLs-last, `LIKE` search over title/description/skills, offset/limit pagination → `ProjectListResponse`.
- [X] T016 [P] [US1] Feed data hooks + query-string state in `frontend/lib/useProjects.ts` (TanStack Query bound to `GET /api/projects`; filters/sort/search/page encoded in the URL, persisted across paging).
- [X] T017 [P] [US1] `frontend/components/ProjectTable.tsx` and `frontend/components/ProjectCard.tsx` rendering all required per-project fields (title, client name + hiring rate, budget range + Tier label, bids, relative+absolute age, site status, qualified indicator, Mostaql link), RTL/bidi-safe.
- [X] T018 [P] [US1] `frontend/components/Filters.tsx` + sort + search controls (tier, budget range, min hiring rate, bids range, age window, site_status, qualified-only toggle).
- [X] T019 [US1] Assemble the feed screen `frontend/app/projects/page.tsx`: table/card toggle, filters/sort/search/pagination wired to T016, and the four states (loading skeleton, empty-no-data, empty-no-match with clear-filters, error). Depends on T015–T018.

**Checkpoint**: MVP — login + a fully functional, RTL-correct, filterable projects feed.

---

## Phase 4: User Story 2 — Inspect a project and its client in depth (Priority: P2)

**Goal**: Open any project to see its full RTL description, a client reputation panel, and the client's other collected projects, with graceful handling of unknown/not-calculated fields.

**Independent Test**: Open a project's detail; confirm full description renders RTL, the client panel shows every reputation field (NULL hiring rate shown as not-calculated, missing fields graceful), same-client projects are listed and link to their own detail, and the Mostaql link works.

### Implementation for User Story 2

- [X] T020 [US2] Implement `GET /api/projects/{id}` in `src/mostaql_notifier/api/routers/projects.py`: load the project + its client, query other projects sharing `client_id` (excluding self) → `ProjectDetail`; 404 when absent.
- [X] T021 [P] [US2] `frontend/components/ClientPanel.tsx` rendering hiring rate, projects posted/open/hired, avg rating + reviews, total spent, member-since, verification, country — null fields shown as "not calculated"/unknown, never 0.
- [X] T022 [US2] Build the detail screen `frontend/app/projects/[id]/page.tsx`: full RTL description, the ClientPanel, the same-client project list (each linking to its detail), Mostaql link, plus loading/error/not-found states. Depends on T020, T021.

**Checkpoint**: Feed + drill-down into project and client both work independently.

---

## Phase 5: User Story 3 — Tune the watcher's thresholds (Priority: P3)

**Goal**: View and edit the 8 watcher tunables with per-key validation; valid saves are honored by the worker next cycle; invalid input is rejected with a clear message and never persisted.

**Independent Test**: Open Settings, confirm current values display; save a valid `budget_primary_floor` and confirm the `settings` row updated; submit an out-of-range/wrong-type value and confirm 422 + unchanged stored value.

### Tests for User Story 3 ⚠️ (write first, ensure they fail)

- [X] T023 [P] [US3] Settings validation test in `tests/api/test_settings_api.py`: GET returns the 8 keys with value+type+range; valid PUT writes through to the `settings` table; unknown key, wrong type, out-of-range, and `budget_fallback_floor > budget_primary_floor` each → 422 with per-field message and **no** partial write.

### Implementation for User Story 3

- [X] T024 [P] [US3] Create the editable-settings registry in `src/mostaql_notifier/api/settings_spec.py`: the 8 keys with type + inclusive range + label (per data-model.md), and the cross-field rule `budget_fallback_floor ≤ budget_primary_floor`; min poll interval ≥ 30 s.
- [X] T025 [US3] Implement `src/mostaql_notifier/api/routers/settings.py`: `GET /api/settings` (current values + spec from the registry via `SettingsStore`) and `PUT /api/settings` (validate every key all-or-nothing against the registry, then write via the existing typed serialize path; 422 on any failure).
- [X] T026 [US3] Build the settings screen `frontend/app/settings/page.tsx`: a form bound to `GET/PUT /api/settings` with inline per-field validation feedback, success confirmation, and error state. Depends on T025.

**Checkpoint**: Owner can retune the watcher from the UI without touching the database.

---

## Phase 6: User Story 4 — Home overview & scraper-health light (Priority: P3)

**Goal**: An at-a-glance Home with today's found/qualified counts, totals, last-successful-scrape, and a red/green/unknown health light derived from existing tables.

**Independent Test**: Seed scrape_runs with a recent success vs. a failed/blocked latest run and confirm each figure is correct and the light is green/red accordingly; a fresh DB shows zeros and an "unknown" (not false-green) light.

### Implementation for User Story 4

- [X] T027 [US4] Implement `GET /api/home` in `src/mostaql_notifier/api/routers/home.py`: found-today + qualified-today (owner-timezone day boundary → UTC), total projects/clients, last successful `scrape_runs.finished_at`, latest run status, and `health` (green/red/unknown) → `HomeOverview`.
- [X] T028 [US4] Build the home screen `frontend/app/page.tsx`: the figure cards + health indicator, with loading/empty/error states. Depends on T027.

**Checkpoint**: All four screens independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final quality pass, local orchestration, and verification.

- [X] T029 Final RTL + bidi sweep across all screens (long Arabic titles/descriptions, mixed Arabic/Latin/digit strings, mirrored icons/spacing) — fixes in `frontend/` components/layout.
- [X] T030 Empty / loading / error state audit across Home, Feed, Detail, Settings in `frontend/app/` and `frontend/components/states/` (including backend-unreachable → 503 surfaced as the error view, and no-filter-match vs. no-data distinction).
- [X] T031 [P] Add `deploy/Dockerfile.api`, `deploy/Dockerfile.frontend`, and `deploy/docker-compose.yml` (worker + api:8000 + frontend:3000 sharing the `./data` DB volume; secrets via env-file).
- [X] T032 [P] Update `scripts/ci.sh` to include `tests/api` in the pytest run and `ruff check` the new `src/mostaql_notifier/api` package.
- [X] T033 Run the `quickstart.md` smoke checks end-to-end (SC-001…SC-009): browse/filter/sort/search, detail, settings round-trip honored by the worker, health light, read-only/no-side-effect verification.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; **blocks all user stories** (auth, app factory, WAL, shell).
- **User Stories (Phase 3–6)**: each depends only on Foundational; independent of one another after that.
- **Polish (Phase 7)**: depends on the desired stories being complete.

### User-story independence

- **US1 (P1)**: after Foundational — the MVP; no dependency on US2–US4.
- **US2 (P2)**: after Foundational — independent (detail links exist in the feed but detail is testable alone).
- **US3 (P3)**: after Foundational — independent (backend + settings form).
- **US4 (P3)**: after Foundational — independent (read-only overview).

### Within each story

- Tests (where present) before implementation; backend endpoint before the screen that consumes it; component pieces (`[P]`) before screen assembly.

### Parallel opportunities

- Setup: T002, T003 in parallel.
- Foundational: T006, T007, T009, T010 in parallel; T008 before T009 logically (cookie) but test can be drafted in parallel.
- Once Foundational is done, **US1, US2, US3, US4 can be built in parallel** by different developers.
- Within US1: T013, T014 (tests) parallel; T016, T017, T018 (frontend pieces) parallel before T019.

---

## Parallel Example: User Story 1

```bash
# Tests first (parallel):
Task: "Contract/integration test for GET /api/projects in tests/api/test_projects_api.py"
Task: "Keyword-search test in tests/api/test_projects_search.py"

# Frontend pieces (parallel, after the endpoint T015):
Task: "ProjectTable + ProjectCard in frontend/components/"
Task: "Filters + sort + search controls in frontend/components/Filters.tsx"
Task: "Feed data hooks in frontend/lib/useProjects.ts"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (auth + WAL + shell) → 3. Phase 3 US1 → **STOP & validate**: login + browse/filter/sort/search the feed. Demo.

### Incremental delivery

Foundation → US1 (MVP) → US2 (detail) → US3 (settings) → US4 (home), each tested and demoable independently, then Polish (docker-compose, CI, RTL/state sweep, quickstart validation).

### Parallel team strategy

After Foundational: Dev A → US1, Dev B → US2, Dev C → US3, Dev D → US4. Backend endpoint and its screen can be split within a story (endpoint first).

---

## Notes

- `[P]` = different files, no dependency on an incomplete task.
- The Python schema (Feature 1 `db/models.py`) is the single source of truth — never redefined here.
- Read-only guarantee: only `PUT /api/settings` writes (to the `settings` table); no endpoint triggers a scrape or notification.
- Constitution: auth-by-default (IX), config-over-code via the settings registry (III), Arabic-first RTL (V), fail-closed display of unknown signals (VII), fail-loud health surfacing (VI).
