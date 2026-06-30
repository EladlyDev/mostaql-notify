# Mostaql Notifier

Personal, single-box tool that politely watches the [mostaql.com](https://mostaql.com) development
listing and pushes **qualifying** new freelance projects to your private Telegram within minutes —
so you stop bidding late and stop wasting proposals on clients who never hire.

> Governed by [`.specify/memory/constitution.md`](.specify/memory/constitution.md): single-user,
> polite scraping, config-over-code, idempotent + non-destructive, Arabic-first, fail-loud,
> fail-closed qualification, no platform automation, local-security, deployment-portable.

## Feature 1 — the watch-and-notify loop

One long-lived worker process: an `AsyncIOScheduler` polls the listing every ~2 minutes, fetches each
**new** project page (the single source of truth for budget / status / hiring rate), qualifies it
fail-closed against hard filters + a dynamic two-tier budget rule with hysteresis, stores raw + parsed
data idempotently, and sends qualifying projects to Telegram (outbound-only `ExtBot`, no inbound
handlers). Blocks / CAPTCHAs / structure changes raise a health alert and back off; a heartbeat reports
liveness.

See [`specs/001-watch-notify-loop/`](specs/001-watch-notify-loop/) for the full spec, plan, data model,
and contracts, and [`quickstart.md`](specs/001-watch-notify-loop/quickstart.md) to set up and run.

## Dashboard (Features 2–6)

A local Next.js dashboard over the same SQLite DB (FastAPI backend, signed-cookie auth) lets you browse
and tune the watcher, manage a personal pipeline (favourites, statuses, a Kanban board, notes/files),
score every qualified project, and watch each one over time. Its tabs: **الرئيسية** (home), **المشاريع**
(projects), **اللوحة** (board), **التحليلات** (analytics), **الإعدادات** (settings).

**التحليلات — analytics & insights (Feature 6).** A **strictly read-only** analytics section that
aggregates the already-collected history into charts and rule-based plain-language tips: a posting
heatmap (day×hour, in a configurable analytics timezone), volume trends, budget distribution + Tier-1/2
split, competition dynamics (a median bids-vs-age curve answering "how long before it gets crowded"),
outcome analytics (hired vs no-hire, time-to-close, **hired projects you never applied to**), a personal
funnel (seen → favourited → applied → discussion → won), and a handful of honest, support-gated tips. It
**scrapes nothing and writes nothing back** — every chart and tip is computed at read time from existing
rows — so it adds **no new process, no Alembic migration, and no new dependency**; the only new state is a
few `analytics_*` `settings` rows. Each section is upfront about thin data ("لا توجد بيانات كافية بعد")
and a single date-range filter scopes every chart and tip. See
[`specs/006-analytics-insights/`](specs/006-analytics-insights/).

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'            # add ',fallback' for the Playwright fallback
cp .env.example .env               # fill TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
alembic upgrade head               # create the schema (settings seed on first start)
python -m mostaql_notifier         # 1) the worker: poll + re-check + OUTBOUND Telegram
python -m mostaql_notifier.bot     # 2) the inbound bot: inline-button taps + /commands
# verify Telegram wiring without scraping:
python -m mostaql_notifier.notify.selfcheck
```

> **Two processes, not one.** `python -m mostaql_notifier` is outbound-only — it sends
> notifications but does **not** consume `getUpdates`. The inline action buttons (★ favourite, ✅
> applied, 🙈 dismiss, 📝 note, Why?) and the owner commands (`/find /pause /resume /health /stats
> /top`) are handled by the **separate** `python -m mostaql_notifier.bot` process. If the buttons
> spin forever, this process isn't running. Run both (e.g. two `systemd` units).

All tunables live in the `settings` table (seeded on first run) — edit rows to retune without a redeploy
(see [`data-model.md`](specs/001-watch-notify-loop/data-model.md)). Secrets live only in `.env`.

## Tests

```bash
pytest -q       # 114 tests: parsers, qualifier, hysteresis, dedup, block detection, poll cycle
```

## Run it as a service (single box)

Use the sample unit in [`deploy/mostaql-notifier.service`](deploy/mostaql-notifier.service) with
`systemd` (`Restart=always` self-heals crashes; the heartbeat + `last_successful_poll_at` staleness
check surface a stuck loop). A fully dead box can't alert itself — notice prolonged downtime by the
**missing** heartbeat.

## Moving to a VPS / Postgres later

Set `DATABASE_URL=postgresql+psycopg://…`, run `alembic upgrade head`, restore the data — no code
changes (portable type layer: `UtcDateTime`, `JSONType`, non-native enums, dialect-switch upsert).
