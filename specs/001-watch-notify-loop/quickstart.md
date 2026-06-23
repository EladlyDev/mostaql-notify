# Quickstart: Watch-and-Notify MVP Loop

**Feature**: `001-watch-notify-loop` | Personal, single-box. Runs one worker process.

## Prerequisites

- Python 3.11+
- A Telegram bot token (from @BotFather) and your private chat id
- (Optional) Playwright + Chromium, only if the site ever switches to a JS-rendered/anti-bot path

## Setup

```bash
# 1. Create and activate a virtualenv
python3.11 -m venv .venv && source .venv/bin/activate

# 2. Install runtime deps
pip install -e .            # or: pip install -r requirements.txt
# core: httpx[http2], selectolax, apscheduler, "python-telegram-bot[rate-limiter]",
#       sqlalchemy>=2, alembic, pydantic-settings, tzdata
# optional fallback: playwright   (then: playwright install chromium)

# 3. Configure secrets (NEVER committed)
cp .env.example .env
# edit .env:
#   TELEGRAM_BOT_TOKEN=123456:ABC...
#   TELEGRAM_CHAT_ID=123456789
#   DATABASE_URL=sqlite:///./data/mostaql.db

# 4. Create the schema + seed settings
alembic upgrade head         # creates tables (batch mode for SQLite)
# settings + app_state rows are seeded on first worker start if absent
```

`.gitignore` MUST include `.env`, `data/`, `*.db`, and captured HTML snapshots (constitution IX).

## Run

```bash
python -m mostaql_notifier        # starts the single worker (scheduler + Telegram sender)
```

On start the worker: seeds settings/app_state if empty → (first run) establishes the seen-baseline and
sends nothing → then polls `https://mostaql.com/projects/development` every ~2 min, fetches each new
project page (and the client profile for projects passing cheap filters), qualifies fail-closed, stores
raw+parsed, and pushes qualifying projects to your Telegram. Health alerts fire on blocks/structure
changes; a heartbeat pings every 12 h.

## Tuning (no code changes — constitution III)

All thresholds live in the `settings` table; edit values directly (a Settings UI comes later):

```sql
-- example: widen the funnel target and lower the poll interval
UPDATE settings SET value='90'  WHERE key='poll_interval_seconds';
UPDATE settings SET value='15'  WHERE key='fallback_target';
```

Key knobs: `poll_interval_seconds`, `client_refresh_hours`, `budget_primary_floor`,
`budget_fallback_floor`, `fallback_target`, `fallback_buffer`, `fallback_window_hours`,
`min_hiring_rate`, `budget_comparison_basis`, `currency_usd_rates`, `owner_timezone`, the delay/backoff
and block-detection knobs (see `data-model.md`).

## Smoke test (no live scraping)

```bash
pytest tests/                # parsers, qualifier, hysteresis, dedup against golden HTML fixtures
# fixtures include the synthetic "لم يحسب بعد" not-yet-calculated client (never seen live)
```

To verify Telegram wiring without scraping, run the one-off sender check:

```bash
python -m mostaql_notifier.notify.selfcheck   # sends a test message to TELEGRAM_CHAT_ID
```

## Operating it (single box)

- Recommended: run under `systemd` with `Restart=always` so a crash self-heals; the in-process heartbeat
  + `last_successful_poll_at` staleness check covers "scheduler alive but polls failing".
- A fully dead box can't alert itself — rely on the **missing** heartbeat (and an optional off-box uptime
  check, deferred) to notice prolonged downtime.

## Moving to a VPS / Postgres later (constitution X)

Change `DATABASE_URL` to `postgresql+psycopg://...`, run `alembic upgrade head`, restore the data — no
code changes. The portable type layer (`UtcDateTime`, `JSONType`, non-native enums, dialect-switch
upsert) makes this a redeploy, not a rewrite.
