# mostaql-notify Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-06-23

## Active Technologies
- Python 3.11+ (backend, same venv as worker); TypeScript / Node 20+ (frontend) + Backend — FastAPI, Uvicorn, existing SQLAlchemy 2 models/session, pydantic-settings, itsdangerous/passlib (signed session + password hash compare). Frontend — Next.js (App Router), React, Tailwind CSS, shadcn/ui, TanStack Query (data fetching/cache), a fetch client. (002-browse-tune-dashboard)
- Existing SQLite database (`sqlite:///./data/mostaql.db`) — **reused, not re-created**; WAL journal mode enabled for concurrent worker-write / API-read. (002-browse-tune-dashboard)

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
- 002-browse-tune-dashboard: Added Python 3.11+ (backend, same venv as worker); TypeScript / Node 20+ (frontend) + Backend — FastAPI, Uvicorn, existing SQLAlchemy 2 models/session, pydantic-settings, itsdangerous/passlib (signed session + password hash compare). Frontend — Next.js (App Router), React, Tailwind CSS, shadcn/ui, TanStack Query (data fetching/cache), a fetch client.

- 001-watch-notify-loop: Added Python 3.11+ + httpx[http2], selectolax (Playwright as gated fallback); APScheduler

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
