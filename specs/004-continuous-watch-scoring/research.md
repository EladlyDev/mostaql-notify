# Phase 0 Research — Continuous Watching and Opportunity Scoring

All decisions below resolve the Technical Context and are grounded in the actual codebase (mapped via
exploration of `db/`, `config/`, `worker/`, `scraper/`, `qualify/`, `notify/`, `bot/`, `api/`, and
`frontend/`). The current Alembic head is **`8e6070483eaf`** (Feature 3). There are **no `NEEDS
CLARIFICATION`** items: the spec's unstated tuning values were defaulted in the spec's Assumptions and are
finalized here as `settings` defaults.

---

## R1. Where the latest score + breakdown live

**Decision**: A new **1:1 table `project_scores`** (PK = `project_id`, FK → `projects.id`), holding the
latest `score` (Float, indexed), the `breakdown` (JSON), `computed_at`, plus the per-project lifecycle
singletons `outcome`, `tracking_active`, `last_checked_at`, and `closed_observed_at`. The append-only
trajectory goes in a separate table (R2).

**Rationale**: Mirrors the established Feature 3 pattern (`personal_records` is 1:1 with `projects` via a
shared PK). Keeping scoring out of the hot `projects` table avoids widening a row the watcher writes every
cycle, isolates Feature 4 state, and is backed up with the rest of `./data`. An indexed `score` column makes
the feed's `ORDER BY score` + score-range filter a simple, fast `LEFT JOIN` (the feed already uses
`contains_eager` joins for client/personal). Score/outcome/tracking are co-located because the re-check loop
updates them **together** for one project in one transaction.

**Alternatives considered**: (a) **Columns on `projects`** — simplest join, but widens the hot table and
mixes derived Feature-4 data into Feature-1's source-of-truth row; rejected. (b) **Score in `projects.raw`
JSON** — not indexable for sort/filter; rejected. (c) **Three separate tables** (score / outcome / tracking)
— needless joins for values always read and written together; rejected.

**Non-destructive note (Constitution IV)**: `project_scores.score`/`breakdown` are *derived* values the
automation recomputes; overwriting the latest is allowed because the full history is preserved append-only
in `project_snapshots`. No owner data lives in this table.

---

## R2. The trajectory (append-only snapshots)

**Decision**: A new table **`project_snapshots`** (many-per-project): `id` PK, `project_id` FK (indexed),
`captured_at` (UtcDateTime), `bids_count` (Int, nullable), `site_status` (the `ProjectStatus` string), and
`score` (Float, nullable). A composite index on `(project_id, captured_at)` serves the lifecycle query.
**Insert-only** — the re-check loop appends exactly one row per project per cycle; nothing updates or
deletes a snapshot.

**Rationale**: This is the time-series foundation the spec calls the bedrock for later analytics. Storing
`score` in each snapshot lets the bid chart and (future) analytics show score-over-time without recompute.
Append-only is the literal embodiment of Constitution IV. Personal scale (a project re-checked every ~30 min
for a few days ⇒ low-hundreds of snapshots max) makes table growth trivial.

**Alternatives considered**: One JSON array of snapshots on `project_scores` — unbounded row growth, no
per-snapshot indexing, awkward append under concurrency; rejected in favour of a normal child table.

---

## R3. The scoring model (the heart of Part A)

**Decision**: A **pure** module `scoring/model.py` exposing `score_project(project, client, *, settings,
now_utc) -> ScoreResult`, where `ScoreResult` carries the final `score: float` (0–100) and a `breakdown`
dict. Each of the six components returns a normalized sub-score in **[0, 1]**; the final score is
`100 × Σ(normalized_weightᵢ × sub_scoreᵢ)`. Weights are **normalized to sum to one at runtime** (if the
configured weights sum to `W ≠ 1`, each is divided by `W`; if all are zero, fall back to equal weights).
The `breakdown` stores, per component: `raw` input(s), `sub_score` (0–1), `weight` (normalized), and
`contribution` (`100 × weight × sub_score`, i.e. points out of 100), plus the `weights` block and a
`normalized: bool` flag — exactly what the detail bars and the "Why?" reply render.

Component definitions (all constants are `settings` keys, defaults in parentheses):

1. **Hiring rate (confidence-shrunk)** — `weight score_weight_hiring_rate (0.35)`. Shrink the client's
   hiring rate `r` (0–100, `None`⇒baseline) toward a neutral baseline `b = score_hiring_baseline (50)` by
   sample size `n = client.projects_posted (None⇒0)` and pseudo-count `k = score_hiring_shrink_k (5)`:
   `r_adj = (r·n + b·k) / (n + k)`; sub-score `= r_adj / 100`. A high rate from few projects is pulled
   toward 0.5; a rate from many projects barely moves. (Edge: low-sample client.)
2. **Hire volume / reliability** — `weight score_weight_hire_volume (0.15)`. Diminishing returns on
   `h = client.hires_count (None⇒0)` via half-saturation `s = score_hire_volume_halfsat (10)`:
   `sub = h / (h + s)`.
3. **Budget** — `weight score_weight_budget (0.15)`. Take the project's USD budget basis (reuse
   `qualify.filters.budget_usd`, which already honours `budget_comparison_basis`, one-sided budgets, and the
   currency table; `None`⇒0). Diminishing returns to a cap `c = score_budget_cap_usd (1000)`:
   `sub = min(usd, c) / c`. Then if `project.tier == 2`, scale down: `sub ×= score_budget_tier2_scale (0.6)`.
   (Edges: one-sided budget handled by `budget_usd`; midpoint above cap clamps to 1 before scale.)
4. **Competition** — `weight score_weight_competition (0.20)`. Combine *crowdedness* and *velocity*. Let
   `bids = project.bids_count (None⇒0)`; crowdedness `= 1 − bids/(bids + score_competition_halfsat_bids
   (15))` (fewer bids ⇒ higher). Velocity `v` = bids per hour since posting, computed from the trajectory
   when ≥2 snapshots exist (`Δbids/Δhours` over the recent window) else `bids / max(age_hours, 1)` on first
   check; velocity sub `= 1 − min(v / score_competition_vel_cap (3.0), 1)`. Component sub-score = mean of
   crowdedness and velocity subs. (Edge: first re-check vs long history.)
5. **Freshness** — `weight score_weight_freshness (0.10)`. Exponential decay on age since posting with
   half-life `H = score_freshness_halflife_hours (12)`: `sub = 0.5 ** (age_hours / H)` (age from
   `posted_at`; if `posted_at` unknown, fall back to `scraped_at`). Newer ⇒ higher.
6. **Client-rating adjustment** — `weight score_weight_rating (0.05)`. A small signed nudge from
   `avg_rating` (0–5, `None`⇒neutral 3) scaled by review confidence
   `min(reviews_count / score_rating_min_reviews (3), 1)`: center at 3 → `sub = clamp(0.5 + ((rating−3)/2)
   × confidence × 0.5, 0, 1)`. Few reviews ⇒ stays near neutral 0.5.

**Rationale**: Every shape the spec demands (shrinkage for low sample, diminishing returns with a cap,
Tier-2 down-scaling, fewer-bids-and-lower-velocity-is-better, age decay, a *small* rating nudge, hiring rate
the largest weight) maps to a closed-form, monotonic, dependency-free function — trivially unit-testable with
injected `now_utc`, exactly like the existing `qualify`/`budget_policy` modules. Storing the full breakdown
makes the score explainable (FR-004, FR-007) and reproducible.

**Alternatives considered**: A learned/regression model — rejected (no labels yet; the outcome data this
feature *gathers* is the future training set, and the constitution forbids hard-coded opaque behavior).
Z-score/percentile normalization across the corpus — rejected (non-deterministic per-project, can't explain a
single score without the whole set, and shifts as the corpus changes). Closed-form bounded components are
deterministic, explainable, and config-tunable.

---

## R4. The `awarded` status and fail-closed outcome capture

**Decision**: Add **`awarded`** to the `ProjectStatus` enum (`open` / `closed` / `awarded` / `unknown`).
Because the enum is portable (`native_enum=False` ⇒ a CHECK constraint), the migration uses Alembic **batch
mode** (already configured `render_as_batch=True`) to rebuild the `site_status` CHECK on `projects` and on
the new `project_snapshots`. `scraper/mostaql.py::_parse_status` learns an **awarded marker** (config-driven
`awarded_markers`, default `["label-prj-awarded", "تم الترسية", "مسند"]`), kept — like all selectors — only
in `mostaql.py`; the exact DOM class is verified against a captured fixture during implementation, defaulting
**fail-closed** (anything not clearly open/closed/awarded ⇒ `unknown`).

The **outcome** (`project_scores.outcome`) is a fail-closed function of the latest observed status:
`open ⇒ open`; `awarded ⇒ hired`; `closed` **with** a visible award marker ⇒ `hired`; `closed` **without**
an award marker ⇒ `closed_no_hire`; anything ambiguous/unparseable ⇒ `unknown`. The system **never** infers
`hired` from absence of evidence (FR-016, Constitution VII).

**Rationale**: Adding the enum value is the minimal, additive, portable way to represent an awarded project;
batch mode is the SQLite-safe path the project already uses. Confining the new marker to `mostaql.py`
respects the "selectors live in one place" rule. The outcome state machine is small and total.

**Alternatives considered**: A boolean `awarded` flag instead of an enum value — rejected (loses the clean
status timeline and conflates two facts). Guessing `hired` when a closed project's client hire-count ticked
up — rejected as a forbidden inference (VII).

---

## R5. The re-check loop (Part B)

**Decision**: A new `worker/recheck.py::run_recheck_cycle(session, fetcher, sender, settings, now_utc)`,
registered as a **second `AsyncIOScheduler` job** in `worker/main.py` with
`IntervalTrigger(seconds=recheck_interval_seconds (1800))`, `coalesce=True`, `max_instances=1`, guarded by
the **same** job-error listener as the poll job. Cycle:

1. Return immediately if `settings.get_bool("watcher_paused")` (FR-021) or the `CircuitBreaker` is paused.
2. Open a `scrape_runs` row with **`kind="recheck"`** (new defaulted column; see R-schema), so `/health`
   keeps reporting the latest *poll* run while re-check runs are still logged loudly (Constitution VI).
3. **Select due projects** (bounded by `recheck_batch_size (20)`), ordered by stalest `last_checked_at`:
   `project_scores.tracking_active = True` AND (`last_checked_at IS NULL` OR `now − last_checked_at ≥
   recheck_min_interval_seconds (1500)`) AND (status is `open`, OR status is `closed/awarded` AND
   `closed_observed_at` is within `tracking_grace_hours (72)`).
4. For each (with `await polite_delay(settings)` between): reuse `fetcher.get(project.url, referer=…)` +
   `parse_project_page`; on a block classification, alert + back off + stop the cycle (reusing
   `classify_response`/`CircuitBreaker`); refresh `bids_count` + `site_status`; refresh the client's stats
   when `now − client.last_refreshed_at > client_refresh_hours`; **append a `project_snapshots` row**;
   compute `outcome`; **re-score** via `scoring.service.score_project` only while `open` (freeze otherwise);
   set `tracking_active=False` once closed past grace; update `last_checked_at`; apply auto-status (R8).
   Wrap each project in `try/except` → log + `error_count++` + skip (FR-020).
5. Finish the run (`status` = success / partial / blocked), commit.

**Rationale**: Re-using the watcher's primitives makes politeness, backoff, and block-detection true by
construction (II) and keeps the loop ~40 lines of orchestration over already-tested helpers. A second
scheduler job (not a new process) is the smallest change that gives an independent cadence; `coalesce` +
`max_instances=1` prevent pile-ups; the existing error listener gives fail-loud for free.

**Alternatives considered**: A separate OS process/console script — rejected (more deployment surface for no
benefit; the worker already owns the scheduler, session, fetcher, and sender). Folding re-checks into the
fast poll cycle — rejected (couples the cadences the spec wants independent, and risks the polite budget).

---

## R6. The freshness "still good?" signal (Part C-1)

**Decision**: A pure `scoring/freshness.py::freshness(project, latest_snapshot, *, settings, now_utc) ->
"green"|"yellow"|"red"`, derived (not stored) and computed on read for the feed and detail. Rules
(thresholds all in `settings`):

- **red** if status is `closed`/`awarded`/`unknown`, OR `bids ≥ freshness_red_min_bids (20)`, OR
  `age_hours ≥ freshness_red_min_age_hours (48)`.
- **green** if status `open` AND `bids ≤ freshness_green_max_bids (8)` AND `age_hours ≤
  freshness_green_max_age_hours (12)`.
- **yellow** otherwise (cooling).
- **Low-data fallback**: with only one snapshot (no velocity), the rule already needs only current bids +
  age + status, so it degrades gracefully and never errors (FR-025).

**Rationale**: The signal is the everyday "should I still bid?" glance and must be instant and obvious;
deriving it on read keeps it always consistent with the latest snapshot and the live thresholds, with no
extra write path. It is intentionally distinct from the *freshness component* of the score (which is a
smooth decay) — the signal is a coarse, action-oriented traffic light.

**Alternatives considered**: Storing the colour on `project_scores` — rejected (would need rewriting whenever
a threshold changes; deriving on read is simpler and always current).

---

## R7. Backfill and settings-triggered re-score (Part A rollout + SC-006)

**Decision**: `scoring/service.py::rescore_all(session, settings, now_utc)` scores **every
`eval_status==qualified` project** from stored data (pure, no I/O). It runs in three situations: (a) **once on
worker startup**, guarded by an `app_state` flag `scoring_backfilled` (so already-collected projects get a
score — FR-005); (b) **synchronously from the settings PUT handler** whenever a scoring weight or tuning
value changes, so the feed reflects the change on the next refresh (SC-006); (c) continuously per open
project inside the re-check loop (R5). A console entry is unnecessary — startup + settings-trigger + loop
cover every case.

**Rationale**: Scoring touches no network and is O(projects) in memory; at personal scale (low-thousands) a
full re-score is sub-second, so doing it synchronously on a weight change is simplest and gives immediate,
predictable behavior. The startup guard makes the backfill idempotent and cheap on every subsequent boot.

**Alternatives considered**: A background "re-score" job triggered by a dirty flag — rejected as
over-engineering for a sub-second synchronous operation. Lazy per-request scoring on feed read — rejected
(re-computes repeatedly, can't index for sort/filter).

---

## R8. The optional auto personal-status transition (Part C-2)

**Decision**: Two **nullable** additive columns on `personal_records`: `auto_status_from` (String — the
status the record held immediately before an automated change) and `auto_status_at` (UtcDateTime). The
re-check loop, **only when `settings.get_bool("auto_status_personal_enabled")` is true (default false)**, and
**only** when a project's latest status becomes `closed`/`awarded`, and the personal record's current status
is exactly `"interested"` with `applied_at IS NULL`, transitions it to `"expired_missed"` — storing the prior
status in `auto_status_from`, stamping `auto_status_at`, and stamping `status_changed_at`. Reverting (a new
`scoring`/`personal` service helper, surfaced as a small "undo" affordance) restores `auto_status_from` and
clears the auto fields. The always-on Mostaql-status sync (FR-026) is just the loop writing
`project.site_status`. The default `personal_statuses` gains an `expired_missed` entry; the migration's data
step **appends** it to an existing `personal_statuses` setting if absent (idempotent), so existing DBs gain
the stage without losing owner customizations.

**Guards (FR-028)**: never fires on Applied/Won/Lost or any status other than `interested`; never overwrites
a status the owner set after the close; never deletes notes/tags/files/outcomes; off by default.

**Rationale**: Storing the prior status is the minimal way to make the change *reversible and recorded*
(FR-029) while keeping `status` a single column the rest of the app already reads. Gating hard on
`interested` + `applied_at IS NULL` makes the "never touch what I acted on" guarantee mechanical.

**Alternatives considered**: A separate `status_history` table — richer but heavier than the spec needs
(only the single most-recent auto-change must be reversible); rejected for now (the snapshot trajectory plus
these two columns already capture what's required). An "audit JSON" on the record — less queryable; rejected.

---

## R9. Frontend charts — no new dependency

**Decision**: Build the **bid-over-time chart** as a bespoke inline **SVG sparkline/line chart** and the
**status timeline** as a fl/flex list of stamped events, both small RTL-aware components under
`frontend/components/lifecycle/`. The score-component bars reuse a new lightweight `score/ScoreBars`
(div widths in %, like a progress bar) and freshness/outcome use the existing `Badge` variants. **No
charting library is added.**

**Rationale**: The data is tiny (low-hundreds of points), the visuals are simple (one line + a few dated
dots + horizontal bars), and the app is Next 16 / React 19 / Tailwind v4 with Base UI — where heavy chart
libs (recharts/visx) add bundle weight and React-19 peer-dependency friction for no real benefit. A ~60-line
SVG component is fully controllable, RTL-correct, and dependency-free (Constitution X portability ethos).

**Alternatives considered**: `recharts` — most popular, but a large dependency with React-19 compatibility
caveats; rejected. `visx`/`d3` — powerful but overkill and a big surface; rejected.

---

## R10. Settings: bool toggles + many numeric tunables

**Decision**: Extend `api/settings_spec.py` to register Feature-4 keys with `min`/`max` + Arabic labels and
to support a **`"bool"`** spec type (for `auto_status_site_enabled`, `auto_status_personal_enabled`); extend
`SettingsForm.tsx` to render a `Switch` for bool specs and group the numeric weight/tuning fields under a new
Arabic **"التقييم" (Scoring)** group. Weights are exposed as individual 0–1 floats and **normalized at
runtime**, so the validator accepts any non-negative weights (it does **not** force a sum of 1 — that would
contradict FR-009); it only rejects negatives/NaN.

**Rationale**: Reuses the existing validated, all-or-nothing settings pipeline (per-field 422s, cross-field
checks) instead of inventing a new control surface; the only gap is bool rendering, which the existing
`switch.tsx` component fills. Per-weight floats are the most legible way to tune in a form, and runtime
normalization keeps them safe.

**Alternatives considered**: A bespoke "scoring model editor" page — explicitly out of scope per the spec.
Putting toggles on the `control.py` endpoint like pause — viable but scatters configuration; keeping all
tunables in the one settings surface is cleaner.

---

## R11. Telegram: score in notifications, "Why?", and `/top [n]`

**Decision**: `notify/format.py::build_project_message` gains a score line (`🎯 Score: NN · Tier T`); a new
**`CB_WHY="why"`** action + a "لماذا؟ (Why?)" inline button in `build_project_keyboard`; a new
`build_score_breakdown_message(project, breakdown)` that lists each component's contribution. `bot/callbacks.py`
routes `CB_WHY` → `scoring.service.get_breakdown(session, project_id)` and replies (answering the callback,
no destructive edit; idempotent, returns the last known breakdown even if the project since closed —
FR-031). `bot/commands.py::top_command` parses an optional `n` (default `settings.top_default_count (5)`,
clamped to a sane max), calls `scoring.service.top_open(session, n)` (qualified + open + tracking, ordered by
score desc), and replies with title · score · tier · link per line; fewer-than-n returns the short list, none
returns a friendly message (FR-032). Registered as `CommandHandler("top", …)` in `bot/app.py`.

**Rationale**: Each addition slots into an existing, idempotent pattern (the `pf:` callback codec ≤64 bytes,
the owner-gated command handlers, the surface-agnostic service). The "Why?" reply and `/top` both read the
same `scoring.service` the dashboard uses, so the numbers always agree across surfaces.

**Alternatives considered**: Sending the breakdown as a new message vs editing the notification — chose a
reply (the original notification stays intact; matches "returns the breakdown" wording and avoids clobbering
the Feature-3 action buttons).

---

## Schema delta summary (one migration, `down_revision = 8e6070483eaf`)

1. **Create `project_scores`** (1:1, PK `project_id`) — `score`, `breakdown` (JSON), `computed_at`,
   `outcome` (default `open`), `tracking_active` (default `True`), `last_checked_at`, `closed_observed_at`,
   `created_at`, `updated_at`; index on `score`, index on `(tracking_active, last_checked_at)`.
2. **Create `project_snapshots`** (many) — `id`, `project_id` FK, `captured_at`, `bids_count`,
   `site_status`, `score`; index `(project_id, captured_at)`.
3. **Batch-alter `projects.site_status` CHECK** to add `awarded` (portable enum widening).
4. **Add `scrape_runs.kind`** (String, default `"poll"`) — re-check runs log as `"recheck"`.
5. **Add `personal_records.auto_status_from` (String, null) + `auto_status_at` (UtcDateTime, null)**.
6. **Data step**: append `{"key":"expired_missed","label":"منتهي/فائت"}` to the `personal_statuses`
   setting if absent (idempotent); `seed_defaults` adds all new scoring/loop/freshness/top/toggle keys.

All changes are additive and non-destructive; the migration is reversible (downgrade drops the two tables and
the added columns and narrows the CHECK), verified by an upgrade→downgrade→upgrade round-trip test.
