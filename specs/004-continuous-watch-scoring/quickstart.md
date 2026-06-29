# Quickstart: Continuous Watching and Opportunity Scoring (Feature 4)

Turns the watcher's raw collection into judgement, on top of Features 1–3. It adds a single **0–100
opportunity score** (six configurable weighted components + a stored per-component breakdown) for every
qualified project, a **second background re-check loop** that re-visits open and recently-closed projects in
polite bounded batches (appending append-only snapshots, refreshing bids/status, capturing a fail-closed
**outcome**), and a derived green/yellow/red **freshness** signal plus **auto status updates** and the
**score + tier + "Why?" + `/top [n]`** in Telegram. Still the **same four processes** sharing
`./data/mostaql.db` (WAL) — the re-check loop is **not** a new process, it is a second scheduler job inside
the existing worker.

## Prerequisites

- Features 1 + 2 + 3 set up: `.venv`, `.env` with `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`,
  the dashboard secrets, and `ATTACHMENTS_DIR`; DB migrated and ideally seeded with collected projects.
- Node 20+ and npm.

## 1. No new config files, no new deps

Feature 4 adds **no new `.env` keys** and **no new runtime dependency** (backend or frontend). Every new
tunable is a `settings` row seeded on first run (six weights, model tuning, the re-check interval/batch/
min-interval, the grace period, the freshness thresholds, the `/top` default, the two auto-status toggles,
and the `awarded_markers`). Edit them in the DB or from the dashboard to retune, no redeploy (Constitution
III). `watcher_paused` is the same existing `settings` row.

## 2. Apply the migration

```bash
.venv/bin/alembic upgrade head      # the one Feature 4 migration (down_revision = 8e6070483eaf)
```

The migration:

- **creates `project_scores`** (1:1 with `projects` — latest score/breakdown + outcome/tracking singletons)
  and **`project_snapshots`** (append-only trajectory, one row per re-check);
- **widens `ProjectStatus`** with `awarded` (batch-rebuilds the portable `site_status` CHECK on `projects`
  and defines it on `project_snapshots`);
- **adds `scrape_runs.kind`** (String, default `"poll"`) so re-check runs log distinctly;
- **adds `personal_records.auto_status_from` + `auto_status_at`** (both nullable) for the reversible
  auto-transition;
- **data step**: idempotently appends the `expired_missed` personal status to an existing `personal_statuses`
  setting if absent (fresh DBs already include it).

`seed_defaults` (run on worker startup, or seeded by the API) inserts the ~20 new scoring/loop/freshness/top/
toggle settings keys. The migration **round-trips**: `upgrade head → downgrade → upgrade` restores the same
schema (the round-trip is covered by `tests/integration/test_scoring_migration.py`). The worker also
self-migrates on startup (`upgrade_head()` + `seed_defaults`), so running it once applies everything too.

## 3. Run the four processes (each in its own shell)

Same four processes as Feature 3 — the re-check loop is a **second scheduler job in the SAME worker
process** (no new process, no new console script):

```bash
# worker — now runs BOTH the fast poll job AND the new re-check job in one process
.venv/bin/mostaql-notifier          # (== python -m mostaql_notifier)

# inbound bot (button taps + commands, now incl. /top) 
.venv/bin/mostaql-notifier-bot

# API
.venv/bin/uvicorn mostaql_notifier.api.app:app --reload --port 8000

# frontend
cd frontend && npm install && echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local && npm run dev
```

The worker's `AsyncIOScheduler` registers the re-check job beside the existing poll + heartbeat jobs, on its
own `recheck_interval_seconds` (default 1800s / 30 min) cadence, with `coalesce=True`, `max_instances=1`, and
the same job-error listener that guards the poll job. `npm install` pulls **no new** frontend deps (the bid
chart + status timeline are bespoke inline SVG/flex — see research R9).

> Frontend note: this stack is **not** stock Next.js — before editing frontend code, read
> `frontend/node_modules/next/dist/docs/` as `frontend/AGENTS.md` mandates (e.g. `proxy.ts`, not
> `middleware.ts`; Tailwind v4 CSS config; Base UI primitives). New surfaces are auto-protected by `proxy.ts`.

## 4. The one-time backfill

On the **first worker start after upgrade**, `scoring.service.rescore_all` scores **every currently
`eval_status==qualified` project** from stored data (pure, no network). It is guarded by the `app_state` flag
`scoring_backfilled` (`"true"` after the first run), so it runs once and is cheap on every later boot.

Confirm scores appeared:

- **Feed** (`/projects`): the new **score column** (with a freshness dot) shows a number on qualified rows;
  sort by score (descending) and the top rows carry the highest scores.
- Or query the DB: `SELECT COUNT(*) FROM project_scores WHERE score IS NOT NULL;` is non-zero, and
  `SELECT value FROM app_state WHERE key='scoring_backfilled';` is `true`.

## 5. Tune the model without code (Config Over Code)

Every behaviour is a `settings` row — change it on the dashboard **Settings** page (the new **"التقييم"
(Scoring)** group + the two toggles) or directly in the `settings` table. Key groups:

- **Six weights** (0–1 each): `score_weight_hiring_rate` (0.35), `score_weight_hire_volume` (0.15),
  `score_weight_budget` (0.15), `score_weight_competition` (0.20), `score_weight_freshness` (0.10),
  `score_weight_rating` (0.05). **They need not sum to 1** — they are **normalized at runtime** (the
  validator only rejects negatives/NaN, never a sum ≠ 1).
- **Tuning values**: `score_hiring_baseline`, `score_hiring_shrink_k`, `score_hire_volume_halfsat`,
  `score_budget_cap_usd`, `score_budget_tier2_scale`, `score_competition_halfsat_bids`,
  `score_competition_vel_cap`, `score_freshness_halflife_hours`, `score_rating_min_reviews`.
- **Re-check loop**: `recheck_interval_seconds` (1800), `recheck_batch_size` (20),
  `recheck_min_interval_seconds` (1500), `tracking_grace_hours` (72).
- **Freshness thresholds**: `freshness_green_max_bids` (8), `freshness_green_max_age_hours` (12),
  `freshness_red_min_bids` (20), `freshness_red_min_age_hours` (48).
- **`/top` default**: `top_default_count` (5).
- **Auto-status toggles** (rendered as switches): `auto_status_site_enabled` (true — always-on Mostaql sync),
  `auto_status_personal_enabled` (false — optional Interested→Expired/Missed).

Changing a **weight or tuning value** triggers a **synchronous re-score of the whole qualified set** in the
settings PUT handler (sub-second at personal scale), so the feed reflects the new model on the next refresh
(SC-006) — no restart, no separate job.

## 6. Exercise each surface

1. **Feed** (`/projects`): score column (+ freshness dot) between bids and posted; sort by **score**; filter
   by a **score range** (`score_min` / `score_max`). Unscored / non-qualified projects sort last.
2. **Detail** (`/projects/{id}`): a **score-breakdown card** (per-component bars showing each component's
   contribution against its active normalized weight), a dependency-free SVG **bid-over-time** chart, a
   **status timeline** (deduped status changes), and an **outcome badge** + **freshness badge** in the header.
3. **Telegram**: each notification now carries a **score + tier** line and a **"لماذا؟ (Why?)"** button —
   tap it to get the per-component breakdown reply (idempotent; returns the last known breakdown even if the
   project since closed). Send **`/top [n]`** to list the top open qualified projects by score (defaults to
   `top_default_count`).
4. **Optional auto personal-status**: turn `auto_status_personal_enabled` **on**, then on a project whose
   personal status is **Interested** (and never applied) that closes/awards on Mostaql, the re-check loop
   transitions it to **Expired/Missed** — **reversible** (a one-click undo restores the prior status from
   `auto_status_from`) and it **never** touches Applied / Won / Lost or any status you set after the close.

## 7. Verify politeness and fail-loud

The re-check loop **reuses** the watcher's `HttpxFetcher`, `polite_delay` (randomized 2.5–7 s), serial
concurrency, backoff, and `CircuitBreaker`/`classify_response` — so politeness is true by construction:

- **Pause it**: set `watcher_paused` true (dashboard toggle, `/pause`, or the DB). The next re-check cycle
  returns immediately and logs nothing; `/resume` (or false) lets it pick up the next cycle.
- **Bounded batches**: each cycle re-checks at most `recheck_batch_size` projects (stalest first), never
  re-checks one project more often than `recheck_min_interval_seconds`, and stops tracking a project once it
  has been closed past `tracking_grace_hours`.
- **Logged loudly**: every cycle writes a `scrape_runs` row with **`kind="recheck"`** (found / checked /
  updated / errors + status), so `/health` keeps reporting the latest **poll** run while re-check runs are
  still visible. Block/structure-change alerts go through the existing `sender.send_alert`.
- **Isolated failures**: one failing project is logged, counted (`error_count++`), and skipped — the batch
  does not crash. Confirm by pointing one project at a bad URL and watching the cycle finish `partial`.

## 8. Run the tests

```bash
.venv/bin/pytest tests -q              # scoring model (components + normalization + breakdown), freshness,
                                       #   scoring service (backfill/rescore/top_open/get_breakdown),
                                       #   re-check cycle (snapshot/outcome/grace/skip/paused/auto-status),
                                       #   migration round-trip, API score/lifecycle/settings, bot why/top
cd frontend && npm test                # vitest: score column/sort/filter, breakdown bars, bid-chart/timeline,
                                       #   freshness + outcome badges, scoring settings group
bash scripts/ci.sh                     # full gate: alembic upgrade + ruff + pytest + frontend lint/test/build
```

## Backups (unchanged from Feature 3 — Constitution X)

A backup still captures **both** `./data/mostaql.db` (+ `-wal`/`-shm` sidecars — now also holding
`project_scores` + `project_snapshots`) **and** `./data/attachments/`. All new state lives inside the single
backed-up `./data` volume; restoring it on a new box is a redeploy with no code changes. Automation only ever
**appends** snapshots and refreshes the derived latest score — it **never** deletes or overwrites owner data,
and the optional auto personal-status change is reversible and timestamped (Constitution IV).

## Smoke checks mapping to success criteria

- **SC-001 (score everywhere)**: a qualified project shows the **same** score on the feed, its detail
  breakdown, and the Telegram notification / "Why?" reply — one score, one breakdown, consistent across
  surfaces.
- **SC-006 (live tuning)**: change a weight on Settings → the whole feed re-scores synchronously and reflects
  it on the next refresh; weights that don't sum to 1 still work (normalized).
- **Re-check cycle**: leave the worker running ~30 min (or lower `recheck_interval_seconds`) → a
  `kind="recheck"` run appears, due projects gain a fresh `project_snapshots` row, open projects re-score,
  and a closed-past-grace project flips `tracking_active=False`.
- **Outcome (fail-closed)**: an awarded project ⇒ `hired`; a plain close with no award marker ⇒
  `closed_no_hire`; anything ambiguous ⇒ `unknown` (never assumed hired).
- **Freshness**: a brand-new low-bid open project glows **green**; a busy/old or closed one shows **red**;
  in-between shows **yellow** — changing the threshold settings shifts the colours on the next read.
- **Telegram**: `/top` returns the top open qualified projects by score; `/top 3` clamps to three;
  tapping **"Why?"** on an old notification still replies with the last known breakdown (idempotent).
- **Politeness**: with `watcher_paused` true the re-check cycle skips entirely; a single bad project is
  logged and skipped without stalling the batch.
