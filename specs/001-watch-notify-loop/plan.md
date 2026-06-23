# Implementation Plan: Watch-and-Notify MVP Loop

**Branch**: `001-watch-notify-loop` | **Date**: 2026-06-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-watch-notify-loop/spec.md`

## Summary

Build one long-lived Python worker that politely polls the mostaql.com development listing every ~2
minutes, identifies genuinely-new projects by Mostaql id, fetches each new project page (single source
of truth for budget/status/hiring-rate) plus the client profile for the full client record, qualifies
fail-closed against hard filters and a dynamic two-tier budget rule with hysteresis, stores raw + parsed
data idempotently, and pushes qualifying projects to the owner's private Telegram — with run logging,
block/structure-change health alerts, and a heartbeat. Research verified mostaql.com is server-rendered
plain nginx (no Cloudflare), so **httpx + selectolax** is the default fetcher behind a swappable
interface (Playwright is a gated fallback). Persistence is **SQLAlchemy 2 + Alembic on SQLite**, typed
for a zero-rewrite move to Postgres. Telegram uses **python-telegram-bot `ExtBot`** (outbound only, no
Application/Updater) driven by an **`AsyncIOScheduler`** in a single asyncio process.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: httpx[http2], selectolax (Playwright as gated fallback); APScheduler
(`AsyncIOScheduler`); python-telegram-bot[rate-limiter] (`ExtBot` + `AIORateLimiter`); SQLAlchemy 2 +
Alembic; pydantic-settings (typed `.env`); tzdata/`zoneinfo`
**Storage**: SQLite (local file) via SQLAlchemy; portable type layer (`UtcDateTime`, `JSONType`,
non-native enums, dialect-switch upsert) for a later Postgres redeploy
**Testing**: pytest against committed golden HTML fixtures (incl. a synthetic `لم يحسب بعد` client);
pure-function parser/qualifier/hysteresis unit tests with injected `now_utc`
**Target Platform**: single Linux box now (home network), VPS later (redeploy, not rewrite)
**Project Type**: single-project background worker (no web server in this feature)
**Performance Goals**: qualifying project → Telegram within ~5 min of posting (SLA measured from
authoritative `scraped_at`, not the fuzzy parsed `posted_at`); ≪1 req/s average (polite)
**Constraints**: concurrency = 1; randomized 2.5–7 s inter-request delays; exponential backoff +
circuit breaker on 403/429/challenge; fail-closed qualification; UTC storage; all tunables in the
`settings` table; secrets only in `.env`
**Scale/Scope**: one user; ~25 projects/listing page; 0–3 new projects per cycle (worst realistic ~6)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* **Verdict: PASS** (initial and
post-design). No violations; no Complexity Tracking entries required.

- [x] **I. Personal & Single-Box** — PASS. One worker, one chat, one user. No accounts/roles/tenancy; no
  inbound Telegram handlers; the worker is outbound-only and binds no public socket.
- [x] **II. Polite, Non-Aggressive Access** — PASS. concurrency=1; randomized delays; one stable
  realistic header set per run; per-request exponential backoff honoring `Retry-After`; circuit breaker
  pauses + alerts on blocks; 12 h client-profile cache; robots-compliant (`/projects` allowed, `/ajax/`
  & `/search*` avoided); listing fetched once, each project fetched at most once.
- [x] **III. Config Over Code** — PASS. All ~35 tunables (intervals, delays, floors, target/buffer/window,
  min hiring rate, detection thresholds, currency table, timezone) live in the `settings` table, seeded
  on first run and read at runtime. No behavior-affecting literal in code.
- [x] **IV. Idempotent Ingestion & Non-Destructive History** — PASS. Upsert keyed on unique `mostaql_id`;
  raw payload stored beside parsed fields for projects and clients; automation only advances state and
  annotates — never deletes; pending projects retained and retried (FR-005).
- [x] **V. Arabic-First Correctness** — PASS. UTF-8 end to end; dependency-free Arabic parser (both
  Arabic-Indic and Persian digits, `يحسب`-stem detection of `لم يحسب بعد`, relative Arabic time);
  HTML-mode Telegram render preserving RTL; UTC storage, owner-timezone display.
- [x] **VI. Fail Loud** — PASS. Every run logged (found/new/updated/errors + status); APScheduler
  `EVENT_JOB_ERROR|EVENT_JOB_MISSED` listener + per-project try/skip; Telegram health alerts on
  blocks/structure-change; at-least-once + dedup notifications; heartbeat + `last_successful_poll_at`
  staleness for downtime (single-box limit documented).
- [x] **VII. Conservative, Fail-Closed Qualification** — PASS. NULL/`0.0`/unparseable hiring rate,
  missing/unmapped-currency/absent budget, `unknown` status, and any parser sentinel all disqualify;
  nothing is admitted on a guessed signal.
- [x] **VIII. No Platform Automation** — PASS. Read-only scraping; no bid/submit/message/write action on
  mostaql.com (FR-037).
- [~] **IX. Local Security Hygiene** — PASS (applicable parts); dashboard-auth and upload-validation are
  **N/A this feature** (no dashboard/uploads yet — deferred). Applicable: secrets (`TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `DATABASE_URL`) only in gitignored `.env`, never committed; worker exposes no
  inbound network surface.
- [x] **X. Deployment-Portable** — PASS. No hostname/abspath assumptions; `DATABASE_URL`-driven engine;
  portable SQLAlchemy type layer + Alembic batch migrations; SQLite→Postgres is config + restore.

### Notable design decisions / deltas from the inputs (all improvements, no constitution conflict)

1. **`ExtBot`, not `Application`/`Updater`** — outbound-only means PTB's polling layer is dead weight;
   `ExtBot` still gives `AIORateLimiter`. (research §2)
2. **Hiring rate read from the PROJECT page, not the `/u/` profile** — verified on the listing the
   hiring-rate label is absent and the project page carries it; this reinterprets FR-008's wording and
   *reduces* request volume. The profile is still fetched (12 h cache) to complete FR-007's full client
   record for projects that pass the cheap filters. (research R2/R3)
3. **Project schema extended** beyond the user's draft with `eval_status` (baseline/pending/qualified/
   disqualified/eval_error), `eval_attempts`, `qualified_at`, `notified` — required to honor FR-005
   (pending/retry) and to key the hysteresis window on an authoritative timestamp. (research R4/R5)
4. **First-run baseline** seeds seen-state and sends nothing (SC-002). (research R7)
5. **No reachable `/u/` profile link** (verified during implementation, 2026-06-23): a project page
   exposes the client's hiring rate + several stats inline (`table.table-meta`) but **no profile link
   and no client id**. So the **separate profile fetch / 12 h cache (FR-008/009) is a no-op in this
   feature** — qualification reads the hiring rate from the project page (one fetch ⇒ project + client,
   strictly more polite), and `Client.mostaql_id` is a derived surrogate
   (`derived:<sha1(name|member_since)>`). The full FR-007 profile fields (rating, reviews, total spent,
   country, verification) are not reachable and stay NULL; `client_refresh_hours` is reserved for when a
   profile URL becomes discoverable. Documented in `db/models.py` and `tests/fixtures/README.md`.
6. **`posted_at` from the `<time datetime>` attribute** (UTC) on the project page rather than the fuzzy
   relative "منذ …" text — more authoritative; the Arabic relative-time parser remains the fallback.

**Build status (2026-06-23): COMPLETE.** All 47 tasks implemented; `bash scripts/ci.sh` green —
Alembic migration applies on a fresh DB, `ruff` passes, **114 tests pass** (parsers, qualifier,
hysteresis, dedup/at-least-once, block detection, full poll cycle).

## Project Structure

### Documentation (this feature)

```text
specs/001-watch-notify-loop/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 decisions (verified against live mostaql.com)
├── data-model.md        # Entities, schema, state machine, seeded settings
├── quickstart.md        # Setup / run / tune / migrate
├── contracts/           # fetcher-interface, parsing-and-qualification, telegram-message
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/mostaql_notifier/
├── __main__.py            # entrypoint: asyncio.run(main()) — builds ExtBot + AsyncIOScheduler
├── worker/
│   ├── main.py            # loop lifecycle, signal handlers, scheduler + job-error listener
│   ├── poll.py            # one poll cycle: discover → ingest → evaluate → notify → log run
│   ├── politeness.py      # delays, header-set selection, per-request backoff
│   └── circuit_breaker.py # block/structure-change classification, pause/cooldown, heartbeat
├── scraper/
│   ├── fetcher.py         # Fetcher Protocol + FetchResult
│   ├── httpx_fetcher.py   # default
│   ├── playwright_fetcher.py  # gated fallback
│   └── mostaql.py         # ONLY place selectors live: listing/project/profile parse → dicts
├── parsing/
│   └── arabic.py          # normalize_text, parse_budget, parse_hiring_rate, parse_relative_time
├── qualify/
│   ├── filters.py         # fail-closed qualify(); exclusion-check pass-through
│   └── budget_policy.py   # dynamic two-tier floor + hysteresis (recompute_floor)
├── notify/
│   ├── telegram.py        # ExtBot sender + bounded retry + dedup-guarded send
│   └── format.py          # HTML message builders (notification / alert / heartbeat)
├── db/
│   ├── base.py            # Base + MetaData(naming_convention)
│   ├── types.py           # UtcDateTime, JSONType, make_enum
│   ├── models.py          # clients, projects, scrape_runs, notifications_log, settings, app_state
│   ├── session.py         # engine/session from DATABASE_URL
│   └── upsert.py          # dialect-switch on_conflict_do_update helper
├── config/
│   ├── secrets.py         # pydantic-settings: token, chat id, DATABASE_URL from .env
│   └── settings_store.py  # typed read/seed of the settings table
alembic/                   # migrations (env.py: render_as_batch=True)
tests/
├── unit/                  # parsers, qualifier, hysteresis (injected now_utc)
├── integration/           # poll cycle against golden fixtures; dedup; first-run baseline
└── fixtures/              # captured listing/project/profile/challenge HTML + synthetic لم يحسب بعد
data/                      # sqlite db (gitignored)
.env.example               # documents required secrets (committed); .env is gitignored
pyproject.toml
```

**Structure Decision**: Single-project background worker matching the user's suggested layout
(`worker/ scraper/ qualify/ notify/ db/ config/`) plus a `parsing/` module (constitution-critical Arabic
seam) and `tests/fixtures/`. Selectors are confined to `scraper/mostaql.py`; the fetch layer sits behind
`scraper/fetcher.py` so httpx→Playwright is a swap. No web/API tier exists in this feature.

## Complexity Tracking

> No Constitution Check violations — this table is intentionally empty. The design adds no extra
> projects, services, or patterns beyond what the FRs and constitution require; the schema extensions in
> "deltas" item 3 are the minimum needed to satisfy FR-005 and the hysteresis window, not added
> complexity for its own sake.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |
