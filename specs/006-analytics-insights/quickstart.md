# Quickstart: Analytics and Insights (Feature 6)

The **reading** half of the system, on top of Features 1–4. It adds a dashboard **analytics section** — a
posting heatmap, volume trends, budget distribution, competition dynamics, outcome analytics, a personal
funnel, and a handful of rule-based plain-language tips — computed entirely from data the watcher, scorer,
re-check loop, and personal pipeline already collected. It is **strictly read-only**: it scrapes nothing,
takes no action on Mostaql, and writes nothing back to any project, score, snapshot, outcome, or personal
record. The **same four processes** as Feature 4 (worker, bot, API, frontend) — this feature adds **no new
process**, only API routes and a frontend page.

## Prerequisites

- Features 1–4 set up and ideally run for a while, so there is history to aggregate: collected projects with
  `posted_at`/`scraped_at`, `eval_status`, budgets/tiers; `project_scores` (score + outcome); a
  `project_snapshots` trajectory (the re-check loop appends these over time); and some `personal_records`
  (favourites/applied/won) — the richer the history, the more sections clear their support threshold.
- `.venv`, `.env` (the existing dashboard secrets + `DATABASE_URL`), DB migrated. Node 20+ and npm.

## 1. No migration, no new deps, no new process

Feature 6 adds **no Alembic migration, no new table, no new `.env` key, and no new runtime dependency**
(backend or frontend). The only new state is a handful of `settings` rows seeded on first run (the analytics
timezone + thresholds). There is nothing to migrate:

```bash
# Nothing to apply — the Alembic head is unchanged. The new settings seed on first API/worker start.
.venv/bin/alembic current        # unchanged from Feature 4
```

`seed_defaults` (run on startup, or by the API) inserts the new `analytics_*` keys idempotently. If you want
to seed without waiting:

```bash
.venv/bin/python -c "from mostaql_notifier.db.session import get_sessionmaker; \
from mostaql_notifier.config.settings_store import seed_defaults; \
s=get_sessionmaker()(); print('seeded', seed_defaults(s)); s.commit()"
```

## 2. Run the four processes (unchanged from Feature 4)

```bash
.venv/bin/mostaql-notifier          # worker (poll + re-check + outbound Telegram) — UNCHANGED by Feature 6
.venv/bin/mostaql-notifier-bot      # inbound bot (buttons + commands)            — UNCHANGED by Feature 6
.venv/bin/uvicorn mostaql_notifier.api.app:app --reload --port 8000   # API — now also serves /api/analytics/overview
cd frontend && npm install && echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local && npm run dev
```

`npm install` pulls **no new** frontend deps (every chart is bespoke inline SVG/CSS — see research R8).

> Frontend note: this stack is **not** stock Next.js — before editing frontend code, read
> `frontend/node_modules/next/dist/docs/` as `frontend/AGENTS.md` mandates (e.g. `proxy.ts` not
> `middleware.ts`; Tailwind v4 CSS config; Base UI primitives). The new `/analytics` route is auto-protected
> by `proxy.ts`.

## 3. Open the analytics section

Sign in to the dashboard and open the new **التحليلات (Analytics)** tab (added to the nav). It loads
`GET /api/analytics/overview` for the default window (the last `analytics_default_range_days`, default 90) and
renders, top to bottom:

1. **Posting heatmap** — a 7×24 (السبت→الجمعة × 0–23) grid of when qualified projects appear, in the analytics
   timezone; the densest cells are the windows worth watching.
2. **Volume trends** — qualified vs total counts over time, with **by-day / by-week** tabs.
3. **Budget distribution** — a budget histogram + the **Tier-1 vs Tier-2** split (partial/unknown budgets in a
   labelled band).
4. **Competition dynamics** — a median **bids-vs-age** curve with an IQR band and a "crowded" marker, a
   plain-language headline ("…يتجاوز {N} عرضًا خلال ~{X} ساعة…"), and a **bidding-by-hour** strip.
5. **Outcome analytics** — the **hired vs no-hire** share among concluded projects, mean **and** median
   time-to-close, and a list of **hired projects you never applied to**.
6. **My funnel** — seen → favourited → applied → discussion → won, with each step's conversion rate and (where
   the timestamps allow — the applied step) the typical lag.
7. **Tips** — a ranked, short list of plain sentences, each backed by the data above.

Each section shows a clear **"لا توجد بيانات كافية بعد" (not enough data yet)** state when its support is below
threshold — a fresh system is honest about it rather than misleading.

## 4. Filter by date range

The date-range control (presets آخر ٧/٣٠/٩٠ يومًا + custom dates) scopes **every** chart and tip consistently;
the range is held in the URL. The analytics reflect data up to the most recent collection — a **manual
refresh** picks up new data (real-time streaming is not required). Dates are interpreted as **calendar days in
the configured analytics timezone**.

## 5. Tune the thresholds without code (Config Over Code)

Every behaviour is a `settings` row — change it on the **Settings** page (the new **"التحليلات"** group) or in
the `settings` table. Changing an analytics setting **takes effect on the next refresh with no recompute**
(analytics are read fresh each call — there is no backfill/re-score step like scoring has):

- `analytics_timezone` (`""` ⇒ follows `owner_timezone`) — the single timezone for the heatmap + bidding-by-hour.
- `analytics_default_range_days` (90) — default window when none is chosen.
- `analytics_min_support` (30) — minimum records before a section/tip is "enough".
- `analytics_min_wins_support` (5) — minimum wins before the win-timing / suggested-threshold tips appear.
- `analytics_crowded_bids` (15) — the bid level the "gets crowded" headline refers to (move it and the headline
  + curve marker move).
- `analytics_early_bids` (5) — the early bid level the "how fast to bid" tip refers to.
- `analytics_max_tips` (6) — cap on tips shown.
- `analytics_suggested_threshold_keep` (0.9) — fraction of past wins the suggested score threshold must retain.

## 6. Verify the read-only guarantee (Constitution IV)

The analytics section must change **nothing**. Confirm:

```bash
# counts before
.venv/bin/python -c "from mostaql_notifier.db.session import get_sessionmaker; from sqlalchemy import text; \
s=get_sessionmaker()(); \
print({t: s.execute(text(f'select count(*) from {t}')).scalar() for t in \
['projects','project_scores','project_snapshots','personal_records']})"

# hit the endpoint a few times with different ranges
curl -s 'http://localhost:8000/api/analytics/overview' -b cookies.txt >/dev/null
curl -s 'http://localhost:8000/api/analytics/overview?date_from=2026-01-01&date_to=2026-06-30' -b cookies.txt >/dev/null

# counts after — identical
```

The counts (and the rows themselves) are unchanged. The automated `tests/api/test_analytics_api.py`
asserts this byte-for-byte across a call.

## 7. Exercise the honest-under-thin-data behaviour

- On a **near-empty** DB (or a date range with no data), every section shows "not enough data yet" and `tips`
  is empty — never a percentage drawn from two projects.
- Seed enough qualified projects to clear `analytics_min_support` and the heatmap + its `peak_window` tip
  appear; seed `analytics_min_wins_support` wins and the win-timing + suggested-threshold tips appear.
- Lower a single project's score far below the rest, or add one extreme time-to-close — confirm the **median**
  headline barely moves (robust to outliers; the mean may move).

## 8. Run the tests

```bash
.venv/bin/pytest tests -q              # analytics: timezone bucketing/DST, each aggregate (incl. sparse,
                                       #   missing/one-sided budget, robust median, funnel monotonic +
                                       #   zero-denominator + lag-unavailable, missed-opportunity join),
                                       #   tips (each rule above/below support, suggested-threshold replay,
                                       #   budget-fallback, cap/rank), and the API read-only assertion
cd frontend && npm test                # vitest: heatmap/volume/competition/funnel render, "not enough data"
                                       #   states, date-range filter wiring, RTL labels
bash scripts/ci.sh                     # full gate: alembic upgrade (no-op delta) + ruff + pytest + frontend
```

## Backups (unchanged from Feature 4 — Constitution X)

Nothing new to back up beyond the `settings` rows (already inside `./data/mostaql.db`). This feature stores no
new history — every chart and tip is derived at read time from existing rows, so a restore of the existing
`./data` volume restores the analytics exactly. No code change is needed to migrate to a VPS.

## Smoke checks mapping to success criteria

- **SC-001 (when to watch)**: the heatmap's densest cells mark the peak weekday/hour windows, in the configured
  analytics timezone; changing `analytics_timezone` re-buckets them.
- **SC-002 (how long before crowded)**: the competition headline states a concrete hours-to-crowded answer
  from real trajectories, and it moves when `analytics_crowded_bids` changes.
- **SC-003 (outcomes + missed)**: the hired/no-hire share over concluded projects + a clear count and list of
  hired projects you never applied to.
- **SC-004 (funnel)**: seen → favourited → applied → discussion → won with step conversion rates and the
  applied-step lag (others shown "غير متاح", never fabricated).
- **SC-005 / SC-006 (honest tips)**: a handful of ranked tips, each citing its data; none appear below
  `analytics_min_support` / `analytics_min_wins_support`; on a fresh DB the section is honest, not misleading.
- **SC-008 (read-only)**: project/score/snapshot/personal row counts are unchanged before and after using the
  whole section.
- **SC-009 (robust)**: time-to-close and bid figures show a median alongside the mean; one outlier doesn't move
  the headline.
- **SC-011 / SC-012 (filter + RTL)**: the date filter scopes every chart and tip; everything renders Arabic
  RTL and reads well on phone and laptop.
