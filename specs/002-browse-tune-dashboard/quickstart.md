# Quickstart: Browse-and-Tune Dashboard (Feature 2)

Runs the dashboard locally against the **same** SQLite database the Feature 1 worker writes. Three
processes — worker, API, frontend — share `./data/mostaql.db` (WAL mode).

## Prerequisites

- Feature 1 set up: venv at `.venv`, `.env` present with `TELEGRAM_*` and `DATABASE_URL`, DB migrated
  and (ideally) seeded with some collected projects.
- Node 20+ and npm (for the Next.js frontend).

## 1. Add the dashboard secrets to `.env`

Append to the gitignored `.env` (and mirror as blanks in `.env.example`):

```dotenv
# Dashboard (Feature 2)
DASHBOARD_AUTH_ENABLED=true          # set false to run with no login (local only)
DASHBOARD_PASSWORD=choose-a-strong-password
DASHBOARD_SESSION_SECRET=any-long-random-string
FRONTEND_ORIGIN=http://localhost:3000
```

If `DASHBOARD_AUTH_ENABLED=true` and `DASHBOARD_PASSWORD` is empty, the API fails loud at startup
(mirrors `require_telegram`).

## 2. Backend (FastAPI) — same venv as the worker

```bash
# add api deps to the project (fastapi, uvicorn, itsdangerous, passlib)
.venv/bin/pip install -e ".[api]"          # api extra added to pyproject
.venv/bin/uvicorn mostaql_notifier.api.app:app --reload --port 8000
```

- On startup the API ensures **WAL mode** on the SQLite engine (shared with the worker) and serves at
  `http://localhost:8000`. OpenAPI docs at `/docs`.
- It reuses `mostaql_notifier.db.session` and `mostaql_notifier.db.models` — no separate schema.

## 3. Frontend (Next.js)

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev          # http://localhost:3000
```

## 4. Use it

1. Open `http://localhost:3000` → redirected to **/login** (unless auth disabled).
2. Log in with `DASHBOARD_PASSWORD`.
3. **Home**: found-today / qualified-today / totals + last-successful-scrape with a red/green health light.
4. **Projects**: toggle table/card; filter (tier, budget, min hiring rate, bids, age, status,
   qualified-only); sort (posted/budget/bids/hiring rate); search Arabic or Latin; paginate.
5. **Project detail**: full RTL description + client panel + the client's other projects.
6. **Settings**: edit the 8 watcher tunables; invalid values are rejected inline; valid ones are honored
   by the worker on its next cycle.

## 5. One-command bring-up (docker-compose)

```bash
cd deploy
docker compose up --build
# worker + api (:8000) + frontend (:3000) sharing ../data/mostaql.db
```

## Verifying the contract (tests)

```bash
.venv/bin/pytest tests/api -q          # API contract + integration (temp seeded SQLite)
cd frontend && npm test                # component/RTL smoke tests
```

## Smoke checks mapping to success criteria

- **SC-001/002**: feed lists every project; refine to "open Tier-1, hiring ≥ 80, few bids, newest" fast.
- **SC-003**: open a project → full Arabic description RTL + client panel + same-client projects.
- **SC-004**: change `budget_primary_floor` in Settings → confirm `settings` row updated → worker uses it
  next cycle.
- **SC-005**: submit an out-of-range setting → rejected, stored value unchanged.
- **SC-007**: stop the API → frontend shows the error state (not a blank/empty); empty DB → empty states.
- **SC-008**: with a failed/blocked latest run → health light red; after a fresh success → green.
- **SC-009**: exercise every screen → `projects`/`clients`/`scrape_runs` rows unchanged; no scrape/notify
  fired.
