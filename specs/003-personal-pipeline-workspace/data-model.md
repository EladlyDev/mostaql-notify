# Phase 1 Data Model: Personal Pipeline and Workspace

This feature **adds two persistent tables** and a handful of additive `settings` rows; everything else is a
projection/DTO over them and the existing Feature 1 entities. The existing schema (`clients`, `projects`,
`scrape_runs`, `notifications_log`, `settings`, `app_state`) is reused verbatim through the current
SQLAlchemy models and remains the single source of truth; scraped `projects`/`clients` rows stay **read-only**
to this feature. One new **Alembic** migration creates the two tables (down_revision = `8d0f765b34e3`).

Types reuse the existing helpers in `db/types.py`: `UtcDateTime` (tz-aware UTC, rejects naive datetimes),
`JSONType` (JSON on SQLite / JSONB on Postgres), and the `Base` + naming convention from `db/base.py`.

---

## New table: `personal_records` (1:1 with `projects`)

The owner's layer for one project. **PK = `project_id`** (also FK → `projects.id`) makes the 1:1 a structural
guarantee — a second record for the same project is impossible.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `project_id` | Integer | no | — | **PK** and FK → `projects.id`. One record per project. |
| `favorite` | Boolean | no | `false` | FR-002. |
| `status` | String | no | `"new"` | A **slug** from the configured `personal_statuses` set (FR-003). Not a DB enum (config-driven). |
| `tags` | JSONType | no | `[]` | Free-form list of strings (FR-004). |
| `applied_at` | UtcDateTime | yes | `null` | Set once on first entry into `applied`; never overwritten (FR-005). |
| `won_amount` | Numeric | yes | `null` | Owner-entered, ≥ 0, meaningful when `status="won"` (FR-006). |
| `lost_reason` | Text | yes | `null` | Owner-entered, meaningful when `status="lost"` (FR-006). |
| `notes` | Text | no | `""` | Markdown notes (FR-011). |
| `board_position` | Float | no | `0.0` | Manual order within a status column (FR-021); midpoint-insertion friendly. |
| `hidden` | Boolean | no | `false` | Hide/dismiss flag — distinct from the `ignored` status (FR-007). |
| `status_changed_at` | UtcDateTime | yes | `null` | Stamped on a real status change; drives the detail timeline (FR-008). |
| `reminder_at` | UtcDateTime | yes | `null` | **Reserved/inert** this feature (FR-035). |
| `created_at` | UtcDateTime | no | `utcnow()` | When the record was first created (first interaction). |
| `updated_at` | UtcDateTime | no | `utcnow()` (onupdate) | Last mutation time. |

**Indexes**: `ix_personal_records_status`, `ix_personal_records_hidden`, `ix_personal_records_favorite`
(support the feed's personal-status/favorites filters and the board's engaged predicate).
**Relationship**: `Project.personal` (uselist=False) ↔ `PersonalRecord.project`. FK is non-cascading;
scraped projects are retained (Constitution IV), so the record's parent is never deleted by automation.

---

## New table: `attachments` (many per `projects`)

A file the owner uploaded for a project. File bytes live on disk under `attachments_dir`; this row is the
metadata + the safe storage handle.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | Integer | no | — | **PK**, autoincrement. |
| `project_id` | Integer | no | — | FK → `projects.id`, indexed. Many attachments per project. |
| `original_name` | String | no | — | The owner's filename, retained verbatim for **display** (may be Arabic/long/odd). |
| `stored_name` | String | no | — | Server-generated safe name `"{uuid}.{ext}"`; **unique**; no user input → no traversal/collision. |
| `file_type` | String | no | — | `"pdf" \| "docx" \| "md"` (the validated, configured type). |
| `content_type` | String | no | — | MIME used when streaming (`application/pdf`, the OOXML type, `text/markdown`). |
| `size_bytes` | Integer | no | — | Byte size (≤ `upload_max_bytes`). |
| `uploaded_at` | UtcDateTime | no | `utcnow()` | Upload time (FR-014). |

**Index**: `ix_attachments_project_id`.
**Relationship**: `Project.attachments` (list) ↔ `Attachment.project`. On-disk path is derived as
`{attachments_dir}/{project_id}/{stored_name}` — the absolute path is **not** stored, for portability
(Principle X). Owner-initiated delete removes both the row and the file; automation never deletes either
(FR-017, FR-032).

---

## New `settings` rows (additive — seeded by `seed_defaults`, runtime-editable; Constitution III)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `watcher_paused` | bool | `false` | When true, the worker skips its poll cycle (FR-028); toggled by `/pause`·`/resume` and the dashboard. |
| `personal_statuses` | json | the 7-entry ordered `[{key,label}]` list (see research §2) | The pipeline stages → board columns + feed status filter (FR-003, FR-018, FR-031). |
| `upload_max_bytes` | int | `10485760` (10 MB) | Max upload size (FR-013, FR-031). |
| `upload_allowed_types` | json | `["pdf","docx","md"]` | Allowed upload types (FR-013, FR-031). |

**Not a setting** (env/secret instead): `attachments_dir` (default `./data/attachments`) is added to the
`Secrets` model — a deployment path, like `database_url` (research §7). The bot's owner allowlist reuses the
existing `telegram_chat_id` secret.

---

## API DTOs (projection — Pydantic, `from_attributes=True`, nulls never coerced to 0)

### PersonalRecord (detail/get)
`project_id`, `favorite: bool`, `status: str` (slug), `status_label: str`, `tags: string[]`,
`applied_at: datetime|null`, `won_amount: number|null`, `lost_reason: string|null`, `notes: string`,
`board_position: number`, `hidden: bool`, `status_changed_at: datetime|null`, `reminder_at: datetime|null`.

### ProjectListItem — **extended** (feed row/card)
All existing Feature 2 fields **plus** the personal projection (defaulted when no record exists):
`favorite: bool` (default `false`), `personal_status: str` (default `"new"`), `personal_status_label: str`,
`tags: string[]` (default `[]`), `hidden: bool` (default `false`). `ProjectDetail` additionally embeds the
full `personal: PersonalRecord` object.

### Board
- **BoardCard**: `project_id`, `title`, `url`, `client_hiring_rate: number|null`, `budget_min/max`, `currency`, `tier`, `tier_label`, `bids_count`, `posted_at`, `tags: string[]`, `status: str`, `board_position: number`.
- **BoardColumn**: `key: str`, `label: str`, `cards: BoardCard[]` (ordered by `board_position`).
- **BoardResponse**: `columns: BoardColumn[]` in configured order (including empty columns), followed by a labeled **fallback column** if any record holds a status key no longer in the configured set.
- **BoardMoveRequest**: `{ project_id: int, to_status: str, position: number }`. **BoardMoveResponse**: the updated `BoardCard` (or the refreshed board).

### Attachment
- **AttachmentItem**: `id`, `project_id`, `original_name`, `file_type`, `size_bytes`, `uploaded_at`, `can_preview: bool` (true for pdf/md). Download/preview URLs are `/api/attachments/{id}/download` and `/{id}/preview`.
- **AttachmentListResponse**: `{ items: AttachmentItem[] }`.
- **Upload**: `multipart/form-data` with a `file` part → `201` `AttachmentItem`, or `400/422` `{detail, errors}` on type/size failure (nothing stored).
- **Rename**: `PATCH {original_name: str}` → `AttachmentItem`.

### Control / Home
- **ControlState**: `{ paused: bool }`. `POST /pause`·`/resume` → `ControlState`.
- **HomeOverview** — **extended** with `paused: bool` (so the dashboard shows the intentional-idle state).

### Stats (bot `/stats`, computed by `personal/stats.py`)
`found_today`, `qualified_today`, `total_projects`, `total_clients`, plus `per_stage: { <status_key>: count }`
across the configured statuses (engaged records), and `paused` + last-run status for `/health`.

---

## Query parameters — `GET /api/projects` (new, added to Feature 2's set)

| Param | Type | Default | Notes |
|---|---|---|---|
| `personal_status` | str (a configured slug) | — | Exact match on the personal record's status; absence of a record counts as `"new"`. |
| `favorites_only` | bool | `false` | Only favorited projects. |
| `include_hidden` | bool | `false` | When false (default), hidden projects are excluded; when true, they are included (the "show hidden" view). |

The base query **LEFT JOINs** `personal_records` so projects without a record still appear with defaulted
personal fields. All filters remain logical-AND and compose with Feature 2's existing filters/sort/paging.

---

## State & transitions

**Personal status lifecycle**: any configured status → any configured status (free, owner-driven; no auto
transitions except the applied-date stamp). On every status change the service sets `status_changed_at = now`.
On the **first** transition into `applied` (from any surface), if `applied_at is null` it is set to *today*;
it is never overwritten thereafter (FR-005). `won_amount`/`lost_reason` are editable at any time but are the
meaningful outcome fields for `won`/`lost` (FR-006).

**Engaged (board membership)**: a project is on the board ⇔ `(favorite = true OR status != default 'new') AND
hidden = false`. Untouched (no record ⇒ `new`, not favorite) and hidden projects are excluded (FR-019).

**Hide/unhide**: `hide()` sets `hidden=true` (drops from active feed + board, data intact); `unhide()` clears
it. Hidden is independent of the `ignored` status; a hidden project stays hidden until the owner restores it,
even if other fields change via Telegram (Edge Cases).

**Attachment lifecycle**: validated upload → row + file on disk → owner rename (display name only) / owner
delete (row + file). No automated deletion ever (FR-017).

**Pause/resume**: `watcher_paused` flips false↔true; the worker reads it at the top of each poll cycle and
skips quietly when true (no `scrape_run` written); `/pause`·`/resume` and the dashboard toggle are idempotent
(setting it to its current value is harmless).

**Telegram action idempotency**: callbacks resolve a project by id and apply the service mutation; Favorite
toggles, Applied/Dismiss are no-ops once already applied/hidden — so a double tap or a tap on an old message
converges to the same state (FR-026, SC-008).

---

## Validation rules (enforced in the service / routers before any write)

- `status` must be a key in the current `personal_statuses` set; an unknown key is rejected (422). A stored
  status whose key was later removed from config is **displayed** under a fallback column but cannot be set anew.
- `won_amount` must be a number ≥ 0; negative/non-numeric is rejected. `lost_reason`, when provided, is
  non-empty trimmed text.
- Uploads: extension ∈ `upload_allowed_types`, content-type consistent, **magic bytes** confirm the real type,
  and `size_bytes ≤ upload_max_bytes`; any failure → clear message, nothing stored (FR-013).
- `original_name` on upload/rename is retained for display but never used to build a filesystem path; the
  stored path uses only the server UUID name under `{attachments_dir}/{project_id}/` (no traversal).
- `board_position` is server-managed on move; the client supplies a target index/position which the service
  normalizes.

## Invariants

- **One record per project** — guaranteed by `project_id` as PK; both the API and the bot create-or-fetch via
  the same service (FR-029, SC-006).
- **Non-destructive** — automation never deletes/overwrites any personal field, note, or file; only
  owner-initiated actions delete (FR-017, FR-032, Constitution IV).
- **Read-only on scraped data** — no personal action writes to `projects`/`clients`/`scrape_runs`; the only
  writes are to `personal_records`, `attachments`, the additive `settings` rows, and the `watcher_paused`
  flag (FR-010).
- **Files outside the web path** — attachment bytes are only ever served through the gated streaming
  endpoints with explicit content types + `nosniff`; never via a static mount, never executed (Constitution IX).
- **Time** — all new timestamps stored UTC (`UtcDateTime`), displayed in `owner_timezone` (Constitution V).
