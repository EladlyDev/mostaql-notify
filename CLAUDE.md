# mostaql-notify Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-06-25

## Active Technologies
- Python 3.11+ (backend, same venv as worker); TypeScript / Node 20+ (frontend) + Backend — FastAPI, Uvicorn, existing SQLAlchemy 2 models/session, pydantic-settings, itsdangerous/passlib (signed session + password hash compare). Frontend — Next.js (App Router), React, Tailwind CSS, shadcn/ui, TanStack Query (data fetching/cache), a fetch client. (002-browse-tune-dashboard)
- Existing SQLite database (`sqlite:///./data/mostaql.db`) — **reused, not re-created**; WAL journal mode enabled for concurrent worker-write / API-read. (002-browse-tune-dashboard)
- Python 3.11+ (backend + worker + bot, one venv/package); TypeScript / Node 20+ (frontend) + Backend — FastAPI + Uvicorn, SQLAlchemy 2 (existing models/session), Alembic, pydantic-settings, **python-telegram-bot[rate-limiter] v21 (already present; now also used inbound)**, **python-multipart (NEW — uploads)**, itsdangerous/passlib (existing auth). Frontend — Next.js 16, React 19, Tailwind v4, Base UI (`@base-ui/react`), TanStack Query, lucide; **NEW: `@dnd-kit/core`+`/sortable`+`/utilities` (Kanban), `react-markdown`+`remark-gfm`+`rehype-sanitize` (notes render/sanitize)**. (003-personal-pipeline-workspace)
- Existing SQLite (`sqlite:///./data/mostaql.db`, WAL) — **two new tables added via Alembic**, existing tables read-only to this feature except the new ones + additive `settings` rows. Uploaded files on the filesystem under a configurable **`attachments_dir`** (default `./data/attachments`), inside the backed-up `./data` volume, outside any public web path. (003-personal-pipeline-workspace)

- Python 3.11+ + httpx[http2], selectolax (Playwright as gated fallback); APScheduler (001-watch-notify-loop)

## Project Structure

```text
backend/
frontend/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes
- 003-personal-pipeline-workspace: Added Python 3.11+ (backend + worker + bot, one venv/package); TypeScript / Node 20+ (frontend) + Backend — FastAPI + Uvicorn, SQLAlchemy 2 (existing models/session), Alembic, pydantic-settings, **python-telegram-bot[rate-limiter] v21 (already present; now also used inbound)**, **python-multipart (NEW — uploads)**, itsdangerous/passlib (existing auth). Frontend — Next.js 16, React 19, Tailwind v4, Base UI (`@base-ui/react`), TanStack Query, lucide; **NEW: `@dnd-kit/core`+`/sortable`+`/utilities` (Kanban), `react-markdown`+`remark-gfm`+`rehype-sanitize` (notes render/sanitize)**.
- 002-browse-tune-dashboard: Added Python 3.11+ (backend, same venv as worker); TypeScript / Node 20+ (frontend) + Backend — FastAPI, Uvicorn, existing SQLAlchemy 2 models/session, pydantic-settings, itsdangerous/passlib (signed session + password hash compare). Frontend — Next.js (App Router), React, Tailwind CSS, shadcn/ui, TanStack Query (data fetching/cache), a fetch client.

- 001-watch-notify-loop: Added Python 3.11+ + httpx[http2], selectolax (Playwright as gated fallback); APScheduler

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
