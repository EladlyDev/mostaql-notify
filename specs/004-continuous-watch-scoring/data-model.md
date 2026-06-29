# Phase 1 Data Model — Continuous Watching and Opportunity Scoring

Extends the existing schema (Alembic head `8e6070483eaf`). **One migration** adds two tables and three
additive deltas. Existing tables are read-only to this feature except the additive columns below and the
appended `personal_statuses` settings value. Types reuse `db/types.py`: `UtcDateTime` (strict tz-aware UTC),
`JSONType` (JSON1 / JSONB), `make_enum` (portable CHECK enum), `utcnow()`.

---

## New table: `project_scores` (1:1 with `projects`)

The latest opportunity score + breakdown, and the per-project lifecycle singletons (outcome + tracking).
Created lazily the first time a project is scored (backfill, re-check, or initial qualify).

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `project_id` | Integer | NO | — | **PK**, FK → `projects.id` (1:1, shared PK like `personal_records`) |
| `score` | Float | YES | — | Latest 0–100 opportunity score; `NULL` until first computed. **Indexed** (feed sort/filter, `/top`) |
| `breakdown` | JSONType | NO | `{}` | Per-component `{raw, sub_score, weight, contribution}` + `weights` block + `normalized` flag + `inputs` (see ScoreBreakdown DTO) |
| `computed_at` | UtcDateTime | YES | — | When `score` was last (re)computed |
| `outcome` | Outcome enum | NO | `open` | `open` / `closed_no_hire` / `hired` / `unknown` (fail-closed) |
| `tracking_active` | Boolean | NO | `True` | False once closed past the grace period; the re-check selector reads this |
| `last_checked_at` | UtcDateTime | YES | — | Last re-check time; enforces `recheck_min_interval_seconds` |
| `closed_observed_at` | UtcDateTime | YES | — | First time the project was observed closed/awarded; grace-period anchor |
| `created_at` | UtcDateTime | NO | `utcnow()` | |
| `updated_at` | UtcDateTime | NO | `utcnow()`, `onupdate=utcnow` | |

**Indexes**: `ix_project_scores_score` (`score`); `ix_project_scores_tracking` (`tracking_active`,
`last_checked_at`). **Relationship**: `Project.score_row` (uselist=False) ↔ `ProjectScore.project`;
non-cascading (owner/automation lifecycle, not project-delete cascade — consistent with house style).

---

## New table: `project_snapshots` (many per project, append-only)

One timestamped row per re-check; the project's trajectory. **Insert-only** — never updated or deleted by
automation.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | Integer | NO | — | PK |
| `project_id` | Integer | NO | — | FK → `projects.id`, indexed |
| `captured_at` | UtcDateTime | NO | `utcnow()` | Snapshot moment |
| `bids_count` | Integer | YES | — | Bids observed (Arabic-Indic safe via reused parser); `NULL` if unknown |
| `site_status` | ProjectStatus enum | NO | `unknown` | `open` / `closed` / `awarded` / `unknown` |
| `score` | Float | YES | — | Score at this moment (frozen value once closed) |

**Index**: `ix_project_snapshots_project_captured` (`project_id`, `captured_at`). **Relationship**:
`Project.snapshots` (list, order_by `captured_at`) ↔ `ProjectSnapshot.project`.

---

## Enum changes / new enums

- **`ProjectStatus`** (existing, `make_enum`) — **add `awarded`**: now `open` / `closed` / `awarded` /
  `unknown`. Migration batch-rebuilds the CHECK on `projects.site_status` and defines it on
  `project_snapshots.site_status`.
- **`Outcome`** (new, `make_enum`) — `open` / `closed_no_hire` / `hired` / `unknown`. Stored on
  `project_scores.outcome`.

(`EvalStatus`, `RunStatus` unchanged. `PersonalRecord.status` stays a config-driven string slug.)

---

## Additive columns on existing tables

| Table | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| `scrape_runs` | `kind` | String | NO | `"poll"` | `"poll"` \| `"recheck"`; `/health` filters to latest `kind="poll"`; re-check cycles log here too (Fail Loud) |
| `personal_records` | `auto_status_from` | String | YES | — | Status held immediately before an automated transition (enables one-click revert) |
| `personal_records` | `auto_status_at` | UtcDateTime | YES | — | When the automated transition fired |

All nullable/defaulted ⇒ additive and non-destructive on existing rows.

---

## State transitions

### Outcome (fail-closed) — set by the re-check loop from the latest observed status

```
open ──────────────► open            (still actionable; score live)
open ──► awarded ──► hired           (explicit award)
open ──► closed (award marker) ────► hired
open ──► closed (no award marker) ─► closed_no_hire
any  ──► unparseable/ambiguous ────► unknown   (NEVER hired)
```
`hired` is recorded ONLY on an explicit award signal; absence of evidence ⇒ `closed_no_hire` (a plain close)
or `unknown` (ambiguous). Once non-`open`, the score is frozen (no recompute).

### Tracking

```
qualified ─► tracking_active=True, last_checked_at=NULL          (created at first score)
each re-check ─► last_checked_at=now; snapshot appended
first close ─► closed_observed_at=now (kept tracking through grace)
now − closed_observed_at ≥ tracking_grace_hours ─► tracking_active=False  (stop re-checking)
```
Selector for a cycle: `tracking_active AND (last_checked_at IS NULL OR now−last_checked_at ≥
recheck_min_interval_seconds) AND (open OR closed/awarded within grace)`, ordered by stalest
`last_checked_at`, limited to `recheck_batch_size`.

### Auto personal-status (optional, off by default)

```
IF auto_status_personal_enabled
   AND latest status ∈ {closed, awarded}
   AND personal.status == "interested" AND personal.applied_at IS NULL:
      auto_status_from = "interested"; auto_status_at = now
      status = "expired_missed"; status_changed_at = now
Revert: status = auto_status_from; auto_status_from = NULL; auto_status_at = NULL
```
Never fires on Applied/Won/Lost or any non-`interested` status; never deletes data; never overwrites a
status changed by the owner after the close.

---

## New settings keys (added to `config/settings_store.py::DEFAULTS`)

Format `key: (default, "type")`. Tunable ones are also registered in `api/settings_spec.py` with min/max +
Arabic label.

### Scoring weights (float 0–1 each; **normalized at runtime**, never rejected for sum≠1)

| Key | Default | Editable | Label (ar) |
|---|---|---|---|
| `score_weight_hiring_rate` | 0.35 | yes | وزن معدل التوظيف |
| `score_weight_hire_volume` | 0.15 | yes | وزن حجم التوظيف |
| `score_weight_budget` | 0.15 | yes | وزن الميزانية |
| `score_weight_competition` | 0.20 | yes | وزن المنافسة |
| `score_weight_freshness` | 0.10 | yes | وزن الحداثة |
| `score_weight_rating` | 0.05 | yes | وزن تقييم العميل |

### Scoring tuning values

| Key | Default | Type | Editable | Notes |
|---|---|---|---|---|
| `score_hiring_baseline` | 50.0 | float | yes (0–100) | Neutral hiring-rate baseline for shrinkage |
| `score_hiring_shrink_k` | 5 | int | yes (≥0) | Pseudo-count (shrinkage strength) |
| `score_hire_volume_halfsat` | 10 | int | yes (≥1) | Half-saturation for hire count |
| `score_budget_cap_usd` | 1000 | int | yes (≥1) | Diminishing-returns cap |
| `score_budget_tier2_scale` | 0.6 | float | yes (0–1) | Tier-2 budget down-scale |
| `score_competition_halfsat_bids` | 15 | int | yes (≥1) | Half-saturation for bid crowdedness |
| `score_competition_vel_cap` | 3.0 | float | yes (>0) | Bids/hour at which velocity sub-score = 0 |
| `score_freshness_halflife_hours` | 12.0 | float | yes (>0) | Freshness decay half-life |
| `score_rating_min_reviews` | 3 | int | yes (≥1) | Reviews for full rating confidence |

### Re-check loop

| Key | Default | Type | Editable | Notes |
|---|---|---|---|---|
| `recheck_interval_seconds` | 1800 | int | yes (≥300) | Re-check job cadence (independent of poll) |
| `recheck_batch_size` | 20 | int | yes (≥1) | Max projects re-checked per cycle |
| `recheck_min_interval_seconds` | 1500 | int | yes (≥300) | Never re-check one project more often than this |
| `tracking_grace_hours` | 72 | int | yes (≥0) | Keep re-checking this long after close, then stop |

(`client_refresh_hours`, existing default 12, is reused for client-stat staleness.)

### Freshness signal thresholds

| Key | Default | Type | Editable |
|---|---|---|---|
| `freshness_green_max_bids` | 8 | int | yes (≥0) |
| `freshness_green_max_age_hours` | 12 | int | yes (≥0) |
| `freshness_red_min_bids` | 20 | int | yes (≥1) |
| `freshness_red_min_age_hours` | 48 | int | yes (≥1) |

### Telegram + auto-status toggles

| Key | Default | Type | Editable | Notes |
|---|---|---|---|---|
| `top_default_count` | 5 | int | yes (1–20) | `/top` default N |
| `auto_status_site_enabled` | true | bool | yes (toggle) | Auto-sync Mostaql status from the loop |
| `auto_status_personal_enabled` | false | bool | yes (toggle) | Optional Interested→Expired/Missed |

### Scraper marker (json) + first-run state

| Key | Default | Type | Notes |
|---|---|---|---|
| `awarded_markers` | `["label-prj-awarded","تم الترسية","مسند"]` | json | DOM/text markers for an awarded project (confined to `scraper/mostaql.py`) |

**App-state flags** (`app_state` KV, not `settings`): `scoring_backfilled` (`"true"` after the one-time
startup backfill).

### Appended config value (data migration)

`personal_statuses` gains `{"key":"expired_missed","label":"منتهي/فائت"}` if absent (idempotent append; the
default list for fresh DBs already includes it).

---

## DTOs (api/schemas.py additions)

- **`ProjectListItem`** (extend): `score: float | None`, `freshness: "green"|"yellow"|"red"|None`.
- **`ProjectDetail`** (extend): `score`, `freshness`, `outcome: str | None`, `score_breakdown:
  ScoreBreakdown | None`.
- **`ScoreComponent`**: `key: str`, `label: str`, `raw: float | None`, `sub_score: float` (0–1),
  `weight: float` (normalized), `contribution: float` (points 0–100).
- **`ScoreBreakdown`**: `score: float`, `components: list[ScoreComponent]`, `normalized: bool`,
  `computed_at: datetime | None`.
- **`Lifecycle`** (response of `GET /api/projects/{id}/lifecycle`): `outcome: str | None`,
  `snapshots: list[Snapshot]`, `status_timeline: list[StatusEvent]`.
- **`Snapshot`**: `captured_at: datetime`, `bids_count: int | None`, `site_status: str`,
  `score: float | None`.
- **`StatusEvent`**: `at: datetime`, `status: str` (deduped status changes derived from the snapshot
  series — only rows where `site_status` changed).
- **`SettingItem`** (extend): support `type: "bool"` (with a boolean `value`) alongside `int`/`float`.

---

## Query / index notes

- **Feed**: `LEFT JOIN project_scores` on `project_id`; `ORDER BY project_scores.score {asc|desc}` with
  `NULLS` handling (unscored/non-qualified sort last); `score_min`/`score_max` filter `WHERE score BETWEEN`.
  `ix_project_scores_score` covers the sort.
- **Re-check selector**: `ix_project_scores_tracking` covers `tracking_active` + `last_checked_at` ordering.
- **Lifecycle**: `ix_project_snapshots_project_captured` covers the per-project time-ordered read.
- **`/top`**: `eval_status==qualified` ∧ `site_status==open` ∧ `tracking_active`, `ORDER BY score DESC LIMIT
  n`.
