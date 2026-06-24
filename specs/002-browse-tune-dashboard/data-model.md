# Phase 1 Data Model: Browse-and-Tune Dashboard

This feature **introduces no new persistent schema**. It reuses Feature 1's tables verbatim
(`clients`, `projects`, `scrape_runs`, `notifications_log`, `settings`, `app_state`) via the existing
SQLAlchemy models. What follows is (a) the read-only entities the API exposes, (b) the API's
response/request DTOs (projection over those entities), and (c) the only write contract — settings.

## Source entities (reused, read-only unless noted)

### Project (`projects`) — read-only
Fields consumed by the dashboard: `id`, `mostaql_id`, `client_id`, `title`, `description`, `url`,
`category`, `skills` (JSON array), `budget_min`, `budget_max`, `currency`, `bids_count`, `posted_at`
(UTC), `scraped_at` (UTC), `site_status` (open|closed|unknown), `eval_status`
(baseline|pending|qualified|disqualified|eval_error), `qualified_at` (UTC|null), `tier` (1|2|null),
`notified`. Indexed already on `posted_at`, `scraped_at`, `qualified_at`, `eval_status` — covers the
feed's default sort and the home counts.

### Client (`clients`) — read-only
Fields consumed: `id`, `name`, `hiring_rate` (float **0–100**, **NULL = not-yet-calculated**, distinct
from 0.0), `projects_posted`, `projects_open`, `hires_count`, `avg_rating`, `reviews_count`,
`total_spent`, `country`, `member_since` (raw display text), `verified`. A client has many projects
(`Client.projects`).

### ScrapeRun (`scrape_runs`) — read-only
Fields consumed: `started_at`, `finished_at`, `found_count`, `new_count`, `updated_count`,
`error_count`, `status` (running|success|partial|failed|blocked). Drives Home health + last-success.

### Setting (`settings`) — **read + write (the only writable entity)**
`key` (PK), `value` (string), `value_type` (int|float|bool|str|json). The dashboard writes **only** the
8 editable keys below, through the existing `SettingsStore` typed serialize path.

## Editable settings registry (write contract)

The backend exposes exactly these keys; PUT validates against this registry and rejects anything else.

| Key | Type | Range / rule | Worker meaning |
|---|---|---|---|
| `poll_interval_seconds` | int | ≥ 30 | how often the worker polls the listing |
| `client_refresh_hours` | int | ≥ 1 | client-profile refresh cadence |
| `budget_primary_floor` | int | ≥ 0 | Tier-1 budget floor (USD) |
| `budget_fallback_floor` | int | ≥ 0, **≤ `budget_primary_floor`** | relaxed floor when supply is low |
| `fallback_target` | int | ≥ 0 | desired recent Tier-1 supply |
| `fallback_buffer` | int | ≥ 0 | hysteresis buffer around the target |
| `fallback_window_hours` | int | ≥ 1 | window measuring recent Tier-1 supply |
| `min_hiring_rate` | float | 0 – 100 | client hiring-rate gate (strictly-greater-than) |

**Validation rules** (all enforced server-side before any write):
- Unknown key → reject (422). Type mismatch → reject. Out of range → reject.
- Cross-field: `budget_fallback_floor ≤ budget_primary_floor` (when either is in the payload, validated
  against the resulting combined state).
- All-or-nothing: a PUT with any invalid field writes **nothing** (no partial save → SC-005).
- Min poll interval ≥ 30 s defends politeness (Constitution II); negative floors/rates are refused to
  avoid corrupting qualification (VII).

## API response DTOs (projection — no schema change)

### ProjectListItem (feed row/card)
`id`, `title`, `url`, `client_name`, `client_hiring_rate` (number|null), `budget_min`, `budget_max`,
`currency`, `tier` (1|2|null), `tier_label` ("Tier 1"|"Tier 2"|null), `bids_count` (int|null),
`posted_at` (ISO-8601 UTC|null), `site_status`, `eval_status`, `qualified` (bool: `eval_status ==
'qualified'`). Relative age + absolute local time are derived client-side from `posted_at`.

### ProjectListResponse
`items: ProjectListItem[]`, `total: int`, `page: int`, `page_size: int`.

### ProjectDetail
All ProjectListItem fields **plus** `description`, `category`, `skills: string[]`, `scraped_at`,
`client: ClientPanel | null`, `same_client_projects: ProjectListItem[]` (other projects sharing
`client_id`, excluding the current one).

### ClientPanel
`id`, `name`, `hiring_rate` (number|null → null renders "لم يحسب بعد"/not-calculated), `projects_posted`,
`projects_open`, `hires_count`, `avg_rating`, `reviews_count`, `total_spent`, `country`, `member_since`,
`verified`. Any missing numeric field is serialized as `null` (never coerced to 0).

### HomeOverview
`found_today: int`, `qualified_today: int`, `total_projects: int`, `total_clients: int`,
`last_successful_scrape: ISO-8601 UTC | null`, `latest_run_status: string | null`,
`health: "green" | "red" | "unknown"`.

### SettingItem / SettingsResponse
`SettingItem`: `key`, `value`, `type`, `min` (number|null), `max` (number|null), `label`.
`SettingsResponse`: `items: SettingItem[]`. PUT request: `{ "<key>": <value>, ... }`. PUT response:
updated `SettingsResponse` (or 422 with per-field error messages).

### AuthStatus / LoginRequest
`LoginRequest`: `{ password: string }`. `AuthStatus`: `{ authenticated: bool, auth_enabled: bool }`.

## Query parameters — `GET /api/projects`

| Param | Type | Default | Notes |
|---|---|---|---|
| `tier` | int (1\|2) | — | exact tier |
| `budget_min` / `budget_max` | number | — | compares on `Project.budget_max` |
| `min_hiring_rate` | number (0–100) | — | `Client.hiring_rate >= x`; **NULL rates excluded when set** |
| `bids_min` / `bids_max` | int | — | inclusive range on `bids_count` |
| `posted_within_hours` | int | — | `posted_at >= now - N h` |
| `site_status` | open\|closed\|unknown | — | exact |
| `qualified_only` | bool | false | `eval_status == 'qualified'` |
| `q` | string | — | substring over title + description + skills (Arabic & Latin) |
| `sort` | posted_at\|budget\|bids_count\|hiring_rate | posted_at | |
| `order` | asc\|desc | desc | NULLs sort last |
| `page` | int | 1 | 1-based |
| `page_size` | int | 25 | max 100 |

All filters combine as logical AND. The base query is an **outer** join Project→Client so client-less
projects still appear (and show client fields as null) — except when `min_hiring_rate` is set, which
necessarily excludes unknown-rate rows.

## State / invariants

- **Read-only guarantee**: only the `settings` PUT path issues writes; all other sessions are read
  transactions. Project/client/scrape_run rows are never mutated (FR-027, Constitution IV).
- **No side effects**: no endpoint enqueues a scrape or notification (FR-028).
- **Fail-closed display**: `hiring_rate == NULL` → "not calculated", never 0; `eval_status ∈
  {baseline, pending}` → shown as not-qualified, not as error (Assumptions).
- **Concurrency**: WAL + busy_timeout on the shared engine; settings writes are small and atomic.
- **Time**: stored UTC; "today" boundaries and displayed timestamps computed in `owner_timezone`.
