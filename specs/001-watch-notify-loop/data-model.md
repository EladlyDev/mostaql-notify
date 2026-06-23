# Data Model: Watch-and-Notify MVP Loop

**Feature**: `001-watch-notify-loop` | **Date**: 2026-06-23

Derived from the spec's Key Entities and FRs, the user's concrete schema, and the Phase 0 research
(`research.md`). All timestamps are **aware UTC** via the `UtcDateTime` type decorator (§3 research);
JSON via `JSONType` (`sa.JSON().with_variant(JSONB, "postgresql")`); enums via `Enum(..., native_enum=
False, name=...)`; money via `Numeric`. `Base.metadata` carries a `naming_convention` so Alembic batch
migrations (SQLite) can target constraints by name.

## Type conventions (apply everywhere)

| Concern | Convention | Why |
|---|---|---|
| Timestamps | `UtcDateTime` (rejects naive on write, returns aware UTC on read) | Portable UTC; fail-loud on naive |
| JSON | `JSONType = JSON().with_variant(JSONB,"postgresql")` | SQLite JSON1 now, JSONB later |
| Enums | `Enum(PyEnum, native_enum=False, name="...")` | Portable CHECK; survives batch migration |
| Money | `Numeric` (not `Float`) | Exact across engines |
| PK | `Integer primary_key` autoincrement | Portable surrogate key |
| Natural key | `mostaql_id` with `UniqueConstraint` | Idempotent upsert target |

---

## Entity: `clients`

The account that posted a project. Reputation signals; hiring rate may be **unknown** (NULL), which is
itself meaningful (fail-closed: unknown ≠ qualifying).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | surrogate |
| `mostaql_id` | String | no | **unique**; site identifier (username or numeric profile id) |
| `name` | String | yes | |
| `profile_url` | String | yes | `https://mostaql.com/u/{username}` |
| `hiring_rate` | Float | **yes** | **NULL = not-yet-calculated / unknown** (`لم يحسب بعد`). 0.0 is a real, distinct value |
| `projects_posted` | Integer | yes | |
| `projects_open` | Integer | yes | |
| `hires_count` | Integer | yes | when shown |
| `avg_rating` | Float | yes | |
| `reviews_count` | Integer | yes | |
| `total_spent` | Numeric | yes | when shown |
| `country` | String | yes | |
| `member_since` | Date | yes | parsed `تاريخ التسجيل` |
| `verified` | Boolean | no | default false |
| `last_refreshed_at` | UtcDateTime | no | drives the 12 h cache (`client_refresh_hours`) |
| `first_seen_at` | UtcDateTime | no | |
| `raw` | JSONType | no | raw scraped payload (re-parse insurance, FR-019) |

**Rules**: dedup/upsert by `mostaql_id`. Refresh the profile only if
`now − last_refreshed_at ≥ client_refresh_hours` (FR-009). `hiring_rate IS NULL` ⇒ any project from this
client is disqualified (FR-011/012).

## Entity: `projects`

A single posting, linked to its client, labeled Tier 1/2. **All hard-filter inputs (budget, status,
hiring rate) are read from the project page** (research R2), not the listing card.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | surrogate |
| `mostaql_id` | String | no | **unique**; numeric id from `/project/{id}` |
| `client_id` | Integer FK→clients.id | yes | NULL while client not yet captured (pending) |
| `title` | String | yes | |
| `description` | Text | yes | |
| `url` | String | yes | canonical `/project/{id}` |
| `category` | String | yes | e.g. `development` |
| `skills` | JSONType | yes | array of strings |
| `budget_min` | Numeric | yes | from project page |
| `budget_max` | Numeric | yes | from project page |
| `currency` | String | yes | `USD` or NULL when ambiguous (fail-closed) |
| `bids_count` | Integer | yes | display fact |
| `posted_at` | UtcDateTime | yes | **approximate** (parsed relative time); display-only, never a filter or the SLA/window basis |
| `scraped_at` | UtcDateTime | no | authoritative ingest time |
| `site_status` | Enum(`open`/`closed`/`unknown`) | no | default `unknown` (fail-closed) |
| `eval_status` | Enum(`baseline`/`pending`/`qualified`/`disqualified`/`eval_error`) | no | default `pending` |
| `eval_attempts` | Integer | no | default 0; bumped each evaluation try |
| `last_eval_at` | UtcDateTime | yes | |
| `qualified_at` | UtcDateTime | yes | set when first qualified; **the hysteresis-window basis** (research R5) |
| `tier` | Integer | yes | 1 or 2; NULL until qualified |
| `notified` | Boolean | no | default false; flipped atomically with the notification (research R9) |
| `raw` | JSONType | no | raw project-page payload |

**Indexes**: unique(`mostaql_id`); index(`client_id`); index(`posted_at`); index(`scraped_at`);
index(`qualified_at`); index(`eval_status`).

### `eval_status` state machine (FR-005, research R4)

```
                 first ever run + baseline_on_first_run
   (new id) ──────────────────────────────────────────────▶ baseline   (never notified)
       │
       │ normal ingest
       ▼
   pending ──(cheap filters fail: hiring NULL/≤min, budget < floor, closed)──▶ disqualified
       │
       │ (client/profile fetch or parse fails)         eval_attempts++
       ├──────────────────────────────────────────────▶ pending (retry next cycle)
       │                                                    │
       │                                     attempts ≥ max_eval_attempts
       │                                     OR age > pending_max_age_hours
       │                                                    ▼
       │                                                eval_error  (alert; terminal)
       │
       │ all hard filters pass
       ▼
   qualified (set qualified_at, tier) ──notify (atomic)──▶ notified=true
```

Only `baseline`→never-notify; `disqualified`/`eval_error` are terminal and never notified;
`pending` rows are re-selected for (re)evaluation each cycle until resolved or capped. **Automation only
advances state forward and annotates — it never deletes rows** (constitution IV / FR-021).

## Entity: `scrape_runs`

One record per poll cycle (FR-026).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `started_at` | UtcDateTime | no | |
| `finished_at` | UtcDateTime | yes | NULL while running |
| `found_count` | Integer | no | rows seen on the listing |
| `new_count` | Integer | no | genuinely new ids |
| `updated_count` | Integer | no | existing ids re-observed/updated |
| `error_count` | Integer | no | per-project failures skipped |
| `status` | Enum(`running`/`success`/`partial`/`failed`/`blocked`) | no | `partial` = some projects errored; `blocked` = circuit-breaker/challenge |
| `notes` | Text | yes | error summaries, block reason, structure-change snapshot ref |

A `blocked`/structure-change run does **not** update `last_successful_poll_at` (research R5/R11).

## Entity: `notifications_log`

One record per Telegram send; the dedup guard for at-least-once (FR-024, research R9).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `project_id` | Integer FK→projects.id | no | |
| `sent_at` | UtcDateTime | no | |
| `channel` | String | no | `telegram` |
| `dedup_key` | String | no | **unique**; `"telegram:project:<mostaql_id>"` |
| `tier` | Integer | no | tier sent |
| `payload` | JSONType | no | rendered message + fields |

**Rule**: insert (guarded by unique `dedup_key`) + flip `projects.notified=true` in **one transaction**,
committed right after a successful `send_message`. A pre-existing `dedup_key` ⇒ skip the send.

## Entity: `settings`

All behavior-affecting tunables (constitution III). Seeded on first run; read at runtime.

| Column | Type | Null | Notes |
|---|---|---|---|
| `key` | String PK | no | |
| `value` | String | no | stored as text |
| `value_type` | String | no | `int`/`float`/`bool`/`str`/`json` for typed coercion |

### Seeded keys (defaults)

| Key | Default | Source FR |
|---|---|---|
| `poll_interval_seconds` | 120 | FR-001 |
| `poll_jitter_seconds` | 15 | research §5 |
| `misfire_grace_seconds` | 60 | research §2 |
| `client_refresh_hours` | 12 | FR-009 |
| `delay_min_seconds` | 2.5 | FR-031 |
| `delay_max_seconds` | 7.0 | FR-031 |
| `project_to_profile_gap_min` | 4.0 | research §5 |
| `project_to_profile_gap_max` | 9.0 | research §5 |
| `max_fetches_per_cycle` | 12 | research §5 |
| `retry_base_seconds` | 2 | FR-028 |
| `retry_cap_seconds` | 60 | FR-028 |
| `max_retries_per_request` | 5 | FR-028 |
| `cb_cooldown_minutes` | 30 | research §5 |
| `cb_cooldown_factor` | 2 | research §5 |
| `cb_cooldown_max_minutes` | 240 | research §5 |
| `block_body_max_bytes` | 30000 | FR-027 |
| `nonempty_body_min_bytes` | 50000 | FR-027 |
| `challenge_markers` | `["just a moment","cf-chl","__cf_chl","cf_chl_opt","challenges.cloudflare.com","cf-mitigated","checking your browser","attention required","g-recaptcha","recaptcha/api.js","hcaptcha.com","h-captcha"]` | FR-027 |
| `listing_shell_markers` | `["project-row","مشروع"]` | FR-027 |
| `empty_state_markers` | `["لا توجد","no results"]` | FR-027 |
| `budget_primary_floor` | 250 | FR-014 |
| `budget_fallback_floor` | 100 | FR-015 |
| `fallback_target` | 10 | FR-015 |
| `fallback_buffer` | 2 | FR-016 |
| `fallback_window_hours` | 24 | FR-015 |
| `budget_comparison_basis` | `max` | research R6 |
| `currency_usd_rates` | `{"USD": 1.0}` | research R6 |
| `min_hiring_rate` | 0 | FR-011 (strictly `>`) |
| `max_eval_attempts` | 5 | FR-005 |
| `pending_max_age_hours` | 24 | FR-005 |
| `baseline_on_first_run` | true | research R7 |
| `owner_timezone` | `Africa/Cairo` | FR-035 (configurable) |
| `heartbeat_hours` | 12 | FR-029 |
| `listing_url` | `https://mostaql.com/projects/development` | research R1 |
| `category_slug` | `development` | spec scope |

> **Not in `settings`** (secrets, constitution IX): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
> `DATABASE_URL` live in `.env` (gitignored), loaded via typed settings at startup.

## Entity: `app_state`

Small key/value table for state that must survive restarts (distinct from tunables).

| Column | Type | Null | Notes |
|---|---|---|---|
| `key` | String PK | no | |
| `value` | String | no | |

Keys: `active_budget_floor` (`250`/`100`, hysteresis survives restart — research R5);
`last_successful_poll_at` (heartbeat/downtime — research R11); `last_heartbeat_at`;
`run_header_set` (the stable header set chosen for this run); `cb_state`/`cb_resume_at` (circuit breaker).

---

## Relationships

- `clients (1) ──< (N) projects` via `projects.client_id` (nullable while pending).
- `projects (1) ──< (N) notifications_log` via `notifications_log.project_id` (≤1 in this feature).
- `scrape_runs`, `settings`, `app_state` are standalone.

## Cross-cutting validation rules

- **Fail-closed qualification** (FR-010/012): a project qualifies only if `hiring_rate IS NOT NULL AND
  hiring_rate > min_hiring_rate` **AND** USD-normalized budget-basis `≥ active_budget_floor` **AND**
  `site_status == open` **AND** `category == development` **AND** exclusion check passes (pass-through).
- **Tier**: USD-budget `≥ 250` → Tier 1; `[active_floor, 250)` → Tier 2 (only reachable when
  `active_budget_floor == 100`).
- **Non-destructive** (FR-021): updates are additive/annotative; no automated deletes.
- **UTC storage, owner-tz display** (FR-035): all columns stored UTC; convert only at render.
