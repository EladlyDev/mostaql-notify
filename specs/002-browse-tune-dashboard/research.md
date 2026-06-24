# Phase 0 Research: Browse-and-Tune Dashboard

The owner's plan input fixed the stack, so this phase resolves the *integration* unknowns rather than
selecting technologies. Each decision below feeds Phase 1 contracts/data-model.

## R1 — Schema ownership: reuse vs. redefine

- **Decision**: The FastAPI backend imports Feature 1's SQLAlchemy models (`mostaql_notifier.db.models`)
  and session factory (`mostaql_notifier.db.session.get_sessionmaker`) directly. No models are
  redefined; no ORM/migrations are added for this feature.
- **Rationale**: Constitution X + the owner's explicit instruction — one schema, one language, zero
  drift. Alembic migrations stay owned by the worker. The API is a pure consumer plus a settings writer.
- **Alternatives considered**: Next.js full-stack reading SQLite via Drizzle (rejected: schema in two
  languages, drift risk); a separate read-replica DB (rejected: needless sync complexity for one box).

## R2 — Concurrent SQLite access (worker writes + API reads)

- **Decision**: Enable **WAL journal mode** and a **busy_timeout** on every engine connection
  (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`), set via a SQLAlchemy `connect` event in the
  shared session layer so both worker and API inherit it. API uses short-lived, read-only sessions per
  request; the single settings PUT is a tiny, fast write.
- **Rationale**: WAL lets readers proceed concurrently with a single writer without blocking — exactly
  the worker-writes/API-reads shape. `busy_timeout` absorbs the rare write-write overlap (settings PUT
  vs. a worker cycle) instead of erroring. This is the standard SQLite concurrency posture.
- **Where**: Extend `db/session.py`'s existing sqlite `connect` listener (which already sets
  `PRAGMA foreign_keys=ON`) to also set WAL + busy_timeout. This keeps it in the single source of truth
  so the worker benefits too. WAL persists on the database file, so enabling it once is durable.
- **Alternatives considered**: Default rollback journal (rejected: writer blocks readers); a connection
  pool/queue serializing access (rejected: over-engineered for one box); Postgres (rejected: violates
  single-box simplicity, not requested).

## R3 — Auth: shared password, session, disable toggle (Constitution IX)

- **Decision**: `POST /api/auth/login` takes a password, compares it (constant-time) against
  `DASHBOARD_PASSWORD` from env, and on success sets a **signed, HttpOnly, SameSite=Lax session
  cookie** (itsdangerous-signed token carrying an issued-at timestamp; max-age = configurable session
  TTL). An `auth` FastAPI dependency guards every data/settings route. A config flag
  `DASHBOARD_AUTH_ENABLED` (env, default **true**) disables the gate entirely when false (the dependency
  becomes a no-op) so a local-only run can skip login.
- **Rationale**: Minimal, stateless, trivially disableable — meets IX without an account system (I).
  HttpOnly+signed prevents trivial cookie forgery/JS theft; no DB session table needed (single box).
- **Secrets**: `DASHBOARD_PASSWORD` and a `DASHBOARD_SESSION_SECRET` live in `.env` (already gitignored),
  added to `.env.example` as blanks. Never committed. If `DASHBOARD_AUTH_ENABLED=true` and the password
  is empty → fail loud at startup (mirrors `require_telegram`).
- **Alternatives considered**: Per-user accounts/JWT refresh (rejected: violates I, overkill); HTTP
  Basic Auth (rejected: clumsy logout/disable, no clean session); storing the password hash in the DB
  (rejected: secret belongs in env per IX).

## R4 — CORS / process topology

- **Decision**: API enables CORS for **only** the configured frontend origin (`FRONTEND_ORIGIN` env,
  default `http://localhost:3000`), `allow_credentials=true` (for the cookie), methods limited to
  GET/POST/PUT/OPTIONS. In docker-compose the frontend talks to the API via the configured
  `API_BASE_URL`. Worker, API, and frontend are three services sharing the DB volume.
- **Rationale**: Credentialed cookie auth requires an explicit (non-wildcard) origin. Restricting to the
  local origin keeps the surface minimal (IX). Portable via env (X).
- **Alternatives considered**: Same-origin reverse proxy (viable later; deferred — adds an nginx service
  not requested for the MVP); wildcard CORS (rejected: insecure, incompatible with credentials).

## R5 — Projects feed: filtering / sorting / search across the join

- **Decision**: `GET /api/projects` builds a single SQLAlchemy query joining `Project`→`Client`
  (outer join — projects with no client still appear) with server-side:
  - **Filters** (all logical-AND, all optional): `tier` (1|2), `budget_min`/`budget_max` (compare on
    `Project.budget_max` using the existing `budget_comparison_basis`, default "max"), `min_hiring_rate`
    (`Client.hiring_rate >= x`, scale **0–100**; rows with NULL hiring_rate are *excluded* only when this
    filter is set), `bids_min`/`bids_max`, `posted_within_hours` (`posted_at >= now-N`), `site_status`
    (open|closed|unknown), `qualified_only` (`eval_status == 'qualified'`).
  - **Sort**: `sort` ∈ {posted_at (default, **desc**), budget, bids_count, hiring_rate} × `order` ∈
    {asc, desc}. NULLs sort last. `hiring_rate` sort orders by the joined `Client.hiring_rate`.
  - **Search** `q`: case-insensitive substring across `title`, `description`, and `skills` (JSON array →
    matched as text). Arabic and Latin both work because SQLite `LIKE` is byte/Unicode substring and the
    data is UTF-8; we lowercase via Python for the Latin side and match Arabic as-is (Arabic has no case).
    A normalized compare (strip tatweel/diacritics) is a noted enhancement, not required for MVP.
  - **Pagination**: `page` (1-based) + `page_size` (default 25, max 100); response carries
    `total`, `page`, `page_size`, `items`.
- **Rationale**: Server-side keeps the client thin and fast and lets pagination bound payloads (FR-015).
  Outer join honors "list **all** collected projects" (FR-009) including client-less rows. Fail-closed
  display: NULL hiring_rate is shown as not-calculated, and only filtered out when the owner explicitly
  asks for a minimum (a minimum can't be met by an unknown).
- **Alternatives considered**: SQLite FTS5 virtual table for search (rejected for MVP: adds schema/index
  the worker would own; `LIKE` is adequate at this scale; FTS noted as a future enhancement); client-side
  filtering (rejected: violates FR-015 at scale, ships every row).

## R6 — Budget representation for filter/sort

- **Decision**: Sort/filter "budget" on `Project.budget_max` (Numeric), consistent with the worker's
  default `budget_comparison_basis="max"`. Display shows the `budget_min–budget_max` range with currency.
  No currency normalization for sort in MVP (data is predominantly one currency; USD-normalization is the
  worker's qualification concern, not the feed's display ordering).
- **Rationale**: Matches the worker's own comparison basis; avoids importing the qualification USD-rate
  logic into the read path. Documented as an assumption.
- **Alternatives considered**: Sort on USD-normalized budget (deferred: needs the rate table on the read
  path; not worth it for single-currency data).

## R7 — Home figures derivation

- **Decision**: `GET /api/home` computes, against existing tables only:
  - `found_today` = projects with `scraped_at` ≥ start-of-today (owner timezone, converted to UTC bound);
  - `qualified_today` = projects with `qualified_at` ≥ start-of-today;
  - `total_projects` = count(projects), `total_clients` = count(clients);
  - `last_successful_scrape` = max `finished_at` where `scrape_runs.status == 'success'`;
  - `latest_run_status` = status of the most-recent `scrape_runs` row;
  - `health` = `green` if the latest run is `success`/`partial` **and** a successful run exists recently;
    `red` if the latest run is `failed`/`blocked`; `unknown` (not false-green) if there is no successful
    run yet (fresh DB).
- **Rationale**: All derivable from `projects` + `scrape_runs`; no new tables. "Today" uses
  `owner_timezone` from settings to match what the owner sees (V). Health mirrors the worker's
  `RunStatus` enum and avoids false green on a fresh DB (FR-026, SC-008).
- **Alternatives considered**: A materialized stats table (rejected: premature; counts are cheap at this
  scale and must reflect the live DB on manual refresh).

## R8 — Editable settings registry + validation (Constitution III & VII)

- **Decision**: A backend `settings_spec.py` registry lists exactly the 8 editable keys with type and
  inclusive range, derived from the worker's `DEFAULTS` and qualification semantics:

  | UI label | settings key | type | valid range |
  |---|---|---|---|
  | Polling interval (s) | `poll_interval_seconds` | int | ≥ 30 |
  | Client-profile refresh (h) | `client_refresh_hours` | int | ≥ 1 |
  | Primary budget floor | `budget_primary_floor` | int | ≥ 0 |
  | Fallback budget floor | `budget_fallback_floor` | int | ≥ 0 |
  | Fallback target | `fallback_target` | int | ≥ 0 |
  | Fallback buffer | `fallback_buffer` | int | ≥ 0 |
  | Fallback window (h) | `fallback_window_hours` | int | ≥ 1 |
  | Minimum hiring rate (%) | `min_hiring_rate` | float | 0 – 100 |

  GET returns each key's current value + spec (type, range, label) so the form can render and validate
  inline. PUT accepts a partial map `{key: value}`, validates **every** key against the registry
  (unknown key → 422; wrong type → 422; out of range → 422), and only on full success writes through
  `SettingsStore`/the `settings` table using the existing typed `_serialize`. Cross-field sanity:
  `budget_fallback_floor ≤ budget_primary_floor` (a fallback floor above the primary makes the dynamic
  policy meaningless) is enforced and rejected with a clear message.
- **Rationale**: Config-over-code (III): bounds live in a declarative registry, not scattered literals,
  and behavior stays in the `settings` table the worker reads next cycle (FR-023). "Never accept values
  that would break the worker" (VII-adjacent): e.g. a sub-30s poll interval risks politeness (II),
  negative floors corrupt qualification — both rejected. All-or-nothing write avoids partial corruption
  (SC-005).
- **Alternatives considered**: Editing arbitrary settings keys (rejected: out of scope per FR-024, and
  risks breaking the worker); storing ranges in the DB (deferred: the registry is config-as-data in one
  place; promoting ranges into the `settings` table itself is a future option, not needed for MVP).

## R9 — RTL & bidi rendering (Constitution V)

- **Decision**: `<html dir="rtl" lang="ar">` as the document default; Tailwind configured with logical
  properties (`ms-*/me-*/ps-*/pe-*`, `start/end`) and shadcn/ui in RTL mode so spacing, icons, and
  component anatomy mirror. Numbers/budgets/counts wrapped with Unicode bidi isolation (`bdi`/
  `unicode-bidi: isolate`) so mixed Arabic+Latin+digit strings (e.g. "٥٠٠ USD · Tier 1") don't reorder
  confusingly. A shared formatter renders absolute timestamps in `owner_timezone` and relative ages
  ("منذ ٣ دقائق" / "3 minutes ago") from the UTC basis.
- **Rationale**: Direct FR-003/FR-020 + SC-006 compliance; logical properties are the standard way to
  get a single codebase that mirrors correctly; bidi isolation is the standard fix for mixed-direction
  numeric strings.
- **Alternatives considered**: Manual per-component `rtl:` variants only (rejected: error-prone, misses
  bidi); separate LTR/RTL stylesheets (rejected: maintenance burden).

## R10 — Frontend data fetching & states

- **Decision**: TanStack Query against the API, with filters/sort/search/pagination encoded in the URL
  query string (shareable, back-button friendly, persists across paging per FR-014). Every screen
  renders four explicit states: **loading** (skeletons), **empty-no-data**, **empty-no-match** (feed
  only, distinct copy + clear-filters action), and **error** (backend/DB unreachable). Manual refresh
  control; no websockets/polling (FR-029).
- **Rationale**: Query-string state satisfies FR-014 and is the idiomatic Next App-Router approach;
  distinct states satisfy FR-030/SC-007.
- **Alternatives considered**: SWR (equivalent; TanStack chosen for richer cache/devtools); local React
  state for filters (rejected: loses persistence-across-paging and shareable URLs).

## R11 — Local orchestration

- **Decision**: Add `deploy/docker-compose.yml` with three services — `worker` (existing entrypoint),
  `api` (uvicorn `mostaql_notifier.api.app:app`), `frontend` (Next.js) — all mounting the same `./data`
  volume for the SQLite file; secrets via env-file. Feature 1 currently ships only a systemd unit, so
  this compose file is **new** (the plan input's "extend the compose" assumes one exists; we create it
  and keep the systemd unit as the bare-metal option).
- **Rationale**: One-command local bring-up (X, quickstart); shared volume realizes the single-DB design;
  env-only secrets (IX).
- **Alternatives considered**: Running three processes by hand (kept as the documented fallback in
  quickstart); a single container running all three (rejected: muddles process isolation and logs).

## Resolved unknowns

All Technical-Context items are concrete; no `NEEDS CLARIFICATION` remain. Open *enhancements*
explicitly deferred (not blockers): FTS5 search, Arabic diacritic/tatweel normalization, USD-normalized
budget sort, reverse-proxy same-origin topology.
