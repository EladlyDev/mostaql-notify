# Implementation Plan: Browse-and-Tune Dashboard

**Branch**: `002-browse-tune-dashboard` | **Date**: 2026-06-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-browse-tune-dashboard/spec.md`

## Summary

A private, single-owner web dashboard to browse/filter/sort/search the projects the Feature 1 watcher
has collected, inspect a project with its client and the client's other projects, view at-a-glance
home figures with a scraper-health light, and edit the watcher's tunable settings — all reading the
**same** SQLite database the worker writes, with the worker honoring settings changes on its next
cycle.

**Technical approach** (per owner's stack decision): a **FastAPI** backend in the existing Python
package/venv that *imports and reuses* Feature 1's SQLAlchemy models and session (the Python schema
stays the single source of truth — never redefined), exposing read endpoints (projects list, project
detail, home figures) and validated settings read/write endpoints, gated by a single shared-password
session. A separate **Next.js + React + Tailwind + shadcn/ui** frontend renders RTL-correct screens
against that JSON API. Worker and API run as **separate processes against the same SQLite file** with
**WAL mode** enabled so the worker's writes and the API's reads don't contend. Local orchestration via
a new docker-compose that runs worker + API + frontend against a mounted DB volume.

## Technical Context

**Language/Version**: Python 3.11+ (backend, same venv as worker); TypeScript / Node 20+ (frontend)  
**Primary Dependencies**: Backend — FastAPI, Uvicorn, existing SQLAlchemy 2 models/session, pydantic-settings, itsdangerous/passlib (signed session + password hash compare). Frontend — Next.js (App Router), React, Tailwind CSS, shadcn/ui, TanStack Query (data fetching/cache), a fetch client.  
**Storage**: Existing SQLite database (`sqlite:///./data/mostaql.db`) — **reused, not re-created**; WAL journal mode enabled for concurrent worker-write / API-read.  
**Testing**: Backend — pytest + httpx ASGI test client (contract + integration against a temp SQLite seeded via Feature 1 models). Frontend — component/RTL smoke tests (Vitest + Testing Library) + Playwright happy-path E2E (optional, lowest priority).  
**Target Platform**: Localhost (laptop/phone on LAN); portable to a single VPS via redeploy.  
**Project Type**: Web application (separate backend API + frontend SPA) layered over an existing worker package.  
**Performance Goals**: Feed filter/sort/search round-trip feels instant on the personal dataset (target < 300 ms server time for a page of ≤ 50 projects; SC-002: a refined slice in < 10 s of owner effort, no perceptible lag).  
**Constraints**: Read-only on projects/clients/scrape_runs (writes only to `settings`); never triggers scrape/notify; auth-by-default even on localhost; CORS restricted to the local frontend origin; UTF-8/RTL end to end; UTC stored, owner-timezone displayed.  
**Scale/Scope**: One user; low hundreds–low thousands of projects/clients; 5 screens (Login, Home, Feed, Detail, Settings); ~6 backend endpoints.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Personal & Single-Box**: One owner, one box. Auth is a single shared password — no accounts, roles, tenancy, or onboarding. **Pass.**
- [x] **II. Polite, Non-Aggressive Access**: The dashboard performs **no scraping at all** — it only reads the local DB. No outbound mostaql.com requests are added. **N/A (no scraping introduced).**
- [x] **III. Config Over Code**: Settings page edits the existing `settings` table (the watcher's config store); the worker reads new values next cycle. The dashboard adds **no new behavior-affecting constants in code** — per-key validation bounds are themselves table-driven where they gate behavior, and the auth toggle/password live in env/config, not literals. **Pass.**
- [x] **IV. Idempotent Ingestion & Non-Destructive History**: The dashboard **never deletes or overwrites** projects, clients, scrape_runs, notes, or raw payloads — it is read-only on all of these. The only writes are owner-initiated settings edits (additive config change, not history mutation). **Pass.**
- [x] **V. Arabic-First Correctness**: UTF-8 end to end; document RTL; logical CSS properties; bidi-safe rendering of mixed Arabic/Latin/digit strings; `NULL` hiring_rate ("لم يحسب بعد") shown as not-calculated (never 0); timestamps stored UTC, displayed in `owner_timezone`. **Pass.**
- [x] **VI. Fail Loud**: The dashboard surfaces the watcher's health (latest `scrape_runs` status + last-successful-scrape) as a red/green light and exposes scrape error/blocked states; its own API errors return structured error states, not silent blanks. It does not run the background loop, so the loop's own alerting is unchanged. **Pass.**
- [x] **VII. Conservative, Fail-Closed Qualification**: The dashboard does **not** qualify projects — it only *displays* the watcher's existing eval status, and settings validation **refuses values that would break the worker** (e.g. negative floors), never widening qualification by guessing. **Pass.**
- [x] **VIII. No Platform Automation**: No bidding, messaging, or any write to mostaql.com; only outbound Mostaql *links*. **Pass.**
- [x] **IX. Local Security Hygiene**: Auth gate on every data/settings route even on localhost; password from env (never committed), trivially disableable via a config flag; CORS limited to the local frontend origin; signed session cookie; no file uploads in this feature. **Pass.**
- [x] **X. Deployment-Portable**: API resolves the DB from the existing `DATABASE_URL`; frontend reads API base URL from config; no hostnames/absolute paths baked in; docker-compose + env make a VPS move a redeploy. **Pass.**

**Result**: All gates Pass / N/A. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/002-browse-tune-dashboard/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (read-views + settings write contract)
├── quickstart.md        # Phase 1 output (run worker + API + frontend locally)
├── contracts/
│   └── openapi.yaml     # Phase 1 output (API contract)
└── checklists/
    └── requirements.md  # From /speckit.specify
```

### Source Code (repository root)

```text
src/mostaql_notifier/
├── db/                  # EXISTING — models.py, session.py reused as-is (schema source of truth)
├── config/              # EXISTING — settings_store.py (DEFAULTS + typing) reused for validation bounds
└── api/                 # NEW — FastAPI app in the same package/venv
    ├── __init__.py
    ├── app.py           # FastAPI() factory, CORS, router wiring, WAL pragma on startup
    ├── deps.py          # request-scoped Session dependency (reuses get_sessionmaker)
    ├── security.py      # shared-password login, signed session cookie, auth dependency, disable toggle
    ├── schemas.py       # pydantic response/request models (read DTOs + settings update payloads)
    ├── settings_spec.py # editable-key registry: key→(type, range, label) — drives GET/PUT validation
    └── routers/
        ├── auth.py      # POST /api/auth/login, POST /api/auth/logout, GET /api/auth/status
        ├── projects.py  # GET /api/projects (filter/sort/search/paginate), GET /api/projects/{id}
        ├── home.py      # GET /api/home
        └── settings.py  # GET /api/settings, PUT /api/settings

frontend/                # NEW — Next.js app (App Router)
├── app/
│   ├── layout.tsx       # <html dir="rtl" lang="ar">; shell + persistent nav
│   ├── login/page.tsx
│   ├── page.tsx         # Home/overview
│   ├── projects/page.tsx        # Feed (table+card toggle, filters, sort, search, pagination)
│   ├── projects/[id]/page.tsx   # Detail (project + client panel + same-client projects)
│   └── settings/page.tsx
├── components/          # shadcn/ui-based; ProjectTable, ProjectCard, Filters, ClientPanel, StateViews
├── lib/                 # api client, query hooks, formatters (RTL date/budget/relative-age, bidi)
├── middleware.ts        # redirect unauthenticated to /login (reads session cookie)
└── (tailwind/next/ts config)

tests/
├── api/                 # NEW — contract + integration tests for the FastAPI endpoints
│   ├── test_projects_api.py
│   ├── test_project_detail_api.py
│   ├── test_home_api.py
│   ├── test_settings_api.py
│   └── test_auth_api.py
└── (existing worker tests untouched)

deploy/
├── mostaql-notifier.service   # EXISTING (worker)
├── docker-compose.yml         # NEW — worker + api + frontend + shared DB volume
├── Dockerfile.api             # NEW
└── Dockerfile.frontend        # NEW
```

**Structure Decision**: Web-application layout. The backend lives **inside the existing Python
package** as `src/mostaql_notifier/api/` so it imports Feature 1's `db.models` and `db.session`
directly (one schema, one language, zero drift) and shares the venv/pyproject. The frontend is a
**separate `frontend/` Next.js project** that talks to the API over JSON. The Drizzle/full-stack-Next
alternative is explicitly rejected (would force the schema into a second language and risk drift). API
tests join the existing `tests/` tree under `tests/api/`; frontend tests live under `frontend/`.

## Complexity Tracking

> No constitution violations — table intentionally empty.
