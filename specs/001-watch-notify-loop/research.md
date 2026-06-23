# Phase 0 Research: Watch-and-Notify MVP Loop

**Feature**: `001-watch-notify-loop` | **Date**: 2026-06-23

This document records the technical decisions that resolve every unknown in the plan's Technical
Context. Findings were produced by a parallel research sweep (5 investigators + a completeness
critic) and **verified against live mostaql.com pages on 2026-06-23**. Contradictions surfaced by
the critic are resolved in the final section.

---

## 1. Page rendering & fetcher choice

**Decision**: Default fetcher = **httpx (HTTP/2, `follow_redirects=True`) + selectolax**. Playwright
is **not** used in normal operation — it is a gated fallback wired behind the fetch interface,
triggered only by explicit anti-bot/structure signals (see §5). Everything needed is in the
server-rendered HTML.

**Rationale** (live-verified):
- mostaql.com is plain **nginx (Laravel)** — no Cloudflare, no WAF, no JS challenge, sub-second TTFB.
- The development listing `https://mostaql.com/projects/development` is SSR: one GET returns
  ~170 KB with **exactly 25 project cards** (`div.project-row`), default-sorted newest-first.
- `robots.txt` is minimal: `Disallow: /search*` and `Disallow: /ajax/`, **no `Crawl-delay`**.
  `/projects`, `/project/{id}`, and `/u/{username}` are all allowed.

**Alternatives rejected**: Playwright-by-default (heavier, more fingerprintable, breaks
deployment-portability — needs a browser binary); hitting `/ajax/` XHR endpoints (robots-disallowed);
POST filter form with CSRF (unnecessary — GET works).

**Risks / mitigations**: Site is Laravel and could later add Cloudflare or client-side hydration →
the §5 fail-loud detector surfaces it immediately. `/project/{id}` 301-redirects to a slug URL →
`follow_redirects=True` (the bare numeric id is the canonical key).

## 2. Worker architecture (single asyncio process)

**Decision**: One long-lived process: `asyncio.run(main())` owns the single event loop. Inside it:
- **Telegram**: `telegram.ext.ExtBot(token, rate_limiter=AIORateLimiter(max_retries=3))` used as an
  async context manager (`async with bot:`). **No `Application`/`Updater`, no `get_updates`** — the
  feature is outbound-only (no inbound handlers), so the framework polling layer is dead weight.
  Install `python-telegram-bot[rate-limiter]`.
- **Scheduler**: a standalone **`AsyncIOScheduler`** constructed *inside* the running loop (never at
  import). Poll job added with `coalesce=True, max_instances=1, misfire_grace_time=<config>`, `id="poll"`.
- **Fail-loud hook**: `scheduler.add_listener(on_job_error, EVENT_JOB_ERROR | EVENT_JOB_MISSED)` →
  loud log + Telegram alert (APScheduler otherwise swallows job exceptions).
- **Graceful shutdown**: `loop.add_signal_handler(SIGTERM/SIGINT, stop_event.set)`; on wake,
  `scheduler.shutdown(wait=True)` *before* leaving `async with bot:` so in-flight sends finish.

**Rationale**: For outbound-only, `ExtBot` gives the built-in `AIORateLimiter` (flood throttling +
automatic `RetryAfter` handling) without dragging in an `Application`. PTB's `JobQueue` is itself an
`AsyncIOScheduler` but is lifecycle-bound to an `Application` — using it reintroduces exactly what we
drop; the constitution also names APScheduler. Constructing scheduler + bot inside the running loop
avoids the entire "attached to a different loop" bug class.

**Critical detail**: `AIORateLimiter.max_retries` **defaults to 0** — must be set explicitly (=3) or
`RetryAfter` becomes a hard failure. Wrap each send in a small bounded retry for `TimedOut`/`NetworkError`
(AIORateLimiter only handles `RetryAfter`, not generic network blips).

**DB-in-async**: SQLAlchemy stays **synchronous**; the async poll job calls it directly (SQLite is
local and fast at single-user scale; brief loop-blocking is acceptable and documented). This keeps the
Postgres migration path a pure engine swap.

**Alternatives rejected**: full Application+Updater; PTB JobQueue; plain `telegram.Bot` (no
`rate_limiter` slot → hand-rolled throttling); sync `BackgroundScheduler` + `run_coroutine_threadsafe`
(second loop boundary = the loop-mismatch bug); two-process queue (over-engineered for one user).

## 3. Persistence: SQLAlchemy 2.x + Alembic, SQLite now → Postgres later

**Decision**: Normalize portability at the SQLAlchemy **type layer** so models/queries run unchanged
on both backends (deployment-portable):
- **Datetimes**: a vendored `UtcDateTime(TypeDecorator)` (impl `DateTime(timezone=True)`, `cache_ok=True`)
  used for **every** timestamp. On write it **rejects naive datetimes** (fail-loud) and converts aware
  → UTC; on read it re-attaches `timezone.utc`. App code always uses `datetime.now(timezone.utc)`;
  owner-timezone conversion happens **only** at the Telegram render boundary. (~12 lines vendored; the
  `sqlalchemy-utc` package is unmaintained.)
- **JSON**: `JSONType = sa.JSON().with_variant(postgresql.JSONB, "postgresql")` for `raw` payloads and
  `skills` (JSON array of strings). SQLite JSON1 now, JSONB free on Postgres.
- **Enums**: **never native DB enums** — use `Enum(PyEnum, native_enum=False, name="...")` (portable
  CHECK constraint) or validated strings. Native enums diverge across dialects and break Alembic batch.
- **Upsert**: isolate the one dialect difference behind a helper that picks `sqlite_insert` vs
  `pg_insert` by `engine.dialect.name`, then builds `insert().on_conflict_do_update(index_elements=[...],
  set_={...excluded...})` identically. Conflict target = `mostaql_id` (requires a `UniqueConstraint`).
- **Money**: budget columns use **`Numeric`**, not `Float` (exactness across engines).
- **Alembic**: `render_as_batch=True` (SQLite can't `ALTER`); define `MetaData(naming_convention=...)`
  on `Base` so batch mode can target constraints by name; name every Enum/Boolean type.

**Rationale**: SQLite has no `timestamptz`, no native JSONB, no `CREATE TYPE`, no `ALTER` — so the safe
strategy is to normalize in SQLAlchemy, not rely on backend behavior. UTC-everywhere with aware reads
prevents the classic naive-datetime drift on the Postgres move.

**Alternatives rejected**: `sqlalchemy-utc` dependency; epoch-int/ISO-text timestamps (lose native
comparison/indexing); native enums; a generic upsert abstraction (SQLAlchemy intentionally has none);
query-then-update (non-atomic, races).

## 4. Arabic-first parsing

**Decision**: A small **dependency-free** module of pure functions sharing one `normalize()`
preprocessor; **no `dateparser`** (heavy CLDR/tzlocal/dateutil, hard to keep strictly fail-closed for a
tiny closed vocabulary). `now_utc` is **injected** into every function (deterministic, unit-testable).
Live pages render **Western ASCII digits**, so Arabic-Indic handling is a cheap defensive `str.translate`
safety net, not the hot path — but it is required by the Arabic-first constitution.

- **normalize(s)**: `unicodedata.normalize("NFKC", s)` → `str.translate` map covering **both** digit
  ranges (Arabic-Indic `U+0660–0669` *and* Extended/Persian `U+06F0–06F9` → ASCII), Arabic thousands
  `U+066C`→delete, decimal `U+066B`→`.`, percent `U+066A`→`%`, strip bidi marks `U+200E/200F/202A–202E`,
  NBSP→space, tatweel `U+0640`→delete; then strip ASCII `,` between digits.
- **parse_budget(s) → (min, max, currency)**: regex for one/two numbers split by dash/`إلى`. Single
  number → point estimate. Currency: `$`/`دولار` → `USD`; **anything else → `currency=None` and log
  loudly** (never assume USD — fail-closed).
- **parse_hiring_rate(s) → float | None**: if normalized text contains the stem **`يحسب`** (matches
  `لم يحسب`, `لم يحسب بعد`, and diacritic/whitespace variants) → **`None`** (NULL = unknown). Else
  extract `(\d+(?:\.\d+)?)\s*%` → float.
- **parse_relative_time(s, now_utc) → aware UTC**: strip leading `منذ`/`قبل`; match optional integer
  (default 1) + unit by **Arabic stem prefix** with explicit dual forms. Units (seconds, config-driven):
  `ثاني*`=1, `دقيق*`/`دقيقتين`=60, `ساع*`/`ساعتين`=3600, `يوم`/`يومين`/`أيام`=86400, `أسبوع*`=604800,
  `شهر*`/`شهرين`=2592000 (30 d), `سنة`/`سنوات`/`عام`/`أعوام`/`سنتين`=31536000 (365 d). Month/year are
  approximate — acceptable because posted-at is a **display fact, not a filter** (see §6).

**Fail-loud sentinel**: any budget/time/rate that normalizes but matches no pattern → `None` + a
structured warning that feeds the Telegram alert path, so a silent format change can't pass qualification.

**Alternatives rejected**: `dateparser` (over-weight); Babel/PyICU (native libs hurt portability);
exact full-string match for `لم يحسب بعد` (brittle vs the `يحسب` stem test); assuming USD on ambiguity.

## 5. Politeness & block / structure-change detection

**Decision (seeded config defaults)**:
- One persistent `httpx.Client(http2=True, follow_redirects=True)` with a cookie jar; **concurrency = 1**.
- Self-imposed delays (robots has no crawl-delay): `delay_min=2.5s`, `delay_max=7.0s` between any two
  requests; `project_to_profile_gap = 4.0–9.0s`. Poll every `120s` ± `15s` jitter. Safety cap
  `max_fetches_per_cycle=12` (overflow rolls to next cycle). SLA math: ≤6 new × 2 fetches × ~7 s ≈ 90 s,
  well inside the 5-minute notify budget.
- **Headers**: a small static pool of 3–4 *fully self-consistent* desktop header sets (UA + `sec-ch-ua`
  trio + `Accept` + `Accept-Encoding` + `Accept-Language: ar,en-US;q=0.9,en;q=0.8` + `Sec-Fetch-*` +
  per-step `Referer`). Pick **one set per process run** and hold it stable (rotate only across restarts) —
  internal consistency beats per-request churn.
- **Per-request backoff** on 403/429/5xx: respect `Retry-After` (int seconds **or** HTTP-date) first;
  else full-jitter exponential `uniform(0, min(60, 2·2^attempt))`, `max_retries_per_request=5`.
- **Circuit breaker** (pause whole loop, Telegram-alert on entry & recovery): trip on listing 403/429,
  ≥2 consecutive 429s, any challenge marker, or ≥3 consecutive fully-failed cycles. Cooldown 30 min,
  doubling to a 4 h ceiling.
- **Detection (fail-closed — a block is NEVER treated as "no new projects")**: classify each listing
  response → `BLOCKED` (403/429); `TRANSIENT` (5xx/transport → per-request backoff); `CHALLENGE`
  (200 + challenge marker, or body < 30 KB vs ~170 KB norm); `STRUCTURE_CHANGE` (200, no markers, but
  **0 parsed rows on a clearly-non-empty page**). "Clearly non-empty" = `body ≥ 50 KB` AND shell markers
  present (`project-row` class and/or `مشروع`) AND not an explicit empty-state (`لا توجد`). Cross-check
  two selectors so a single rename can't both break parsing and suppress the alarm. On
  `STRUCTURE_CHANGE`/`CHALLENGE`/`BLOCKED`: alert, do **not** advance seen-state, and do **not** update
  `last_successful_poll_at`.

**Rationale**: low average request rate (≪1 req/s) is polite for a personal tool yet meets the SLA;
because the site is not behind Cloudflare today, any CF/CAPTCHA marker or a sudden tiny body is a
high-signal anomaly. Honoring robots is free here (`/projects` is allowed).

---

## Resolved contradictions & cross-cutting decisions

The critic flagged contradictions between investigators and gaps versus the spec. Resolutions
(several **verified by a direct fetch on 2026-06-23**):

- **R1 — Canonical listing URL & row selector (VERIFIED)**: both `/projects/development` (path) and
  `/projects?category=development` (query) return 200/~170 KB. **Use the path form**
  `https://mostaql.com/projects/development`, paginate `?page=N`. **Row selector = `div.project-row`
  (exactly 25/page)** with `.project__brief`/`.project__meta`; project links are absolute
  `https://mostaql.com/project/{id}` (50 per page). `table-meta` does not appear on the listing.
- **R2 — Listing is discovery-only; project page is the single source of truth (VERIFIED)**: on the
  listing, the hiring-rate label `معدل التوظيف` appears **0×** and the budget label `الميزانية` only
  **5×** (not per-row). Therefore the **listing yields only new project IDs**; **all hard-filter inputs
  (budget, hiring rate, status) are read from the fetched project page**, where the client sidebar
  carries hiring rate + several client stats. This also resolves the FR-008 wording: the hiring rate is
  on the **project page** (fewer requests than a profile fetch — a strict politeness win).
- **R3 — Two-stage client fetch (reconciles FR-007/008/009 with the politeness optimization)**: (1) fetch
  the **project page** → read budget, status, hiring rate + sidebar client stats; **early-disqualify
  losers here and skip the profile fetch** (politeness). (2) For projects that pass the cheap filters,
  fetch the **client `/u/` profile** (subject to the 12 h cache) to complete the full client record
  required by FR-007 (rating, reviews, total spent, member-since, country, verification). The profile
  fetch and 12 h cache are therefore **not** optional for qualifying projects.
- **R4 — Pending/retry state machine (FR-005)**: a project that can't be fully evaluated (client/profile
  fetch or parse failure) is **recorded** (raw payload retained, FR-019) in a tracked `pending` state with
  `eval_attempts` + `first_seen_at`, retried on later runs up to `max_eval_attempts` / `pending_max_age_hours`,
  and **never marked notified** until it qualifies. At the cap it moves to a terminal `eval_error` state
  and is alerted (not silently dropped). This overrides the "stays unseen, retry next cycle" phrasing.
- **R5 — Hysteresis window timestamp basis**: the rolling 24 h Tier-1 count keys on the **authoritative
  local `qualified_at` (UTC, set by us)** — **never** the fuzzy parsed `posted_at` (which is approximate
  per §4). Budget Policy State (`active_budget_floor`) persists in `app_state` so the hysteresis decision
  survives restarts; the floor is recomputed **once per poll cycle**, before evaluating that cycle's projects.
- **R6 — Budget basis & currency (wires the qualifier)**: budget is sourced from the **project page**;
  compared to the active floor using config `budget_comparison_basis` (default **max**; one-sided → the
  available bound; none → disqualify). Non-USD is normalized via a configurable
  `currency_usd_rates` map before comparison; **unmapped/unknown currency → disqualify** (fail-closed).
- **R7 — First-run baseline (SC-002)**: on the first ever run (empty seen-state), upsert all currently
  visible project IDs in a `baseline` state and **send nothing**; only genuinely new IDs thereafter
  notify. Controlled by config `baseline_on_first_run` (default true).
- **R8 — `0.00%` vs `None` are two disqualify paths**: `None` (the `يحسب` stem) and a parsed `0.00%`
  (numeric failing the `> min_hiring_rate` floor) both disqualify but via different code — both get
  explicit tests (spec Acceptance 1.2 vs 1.3).
- **R9 — At-least-once + dedup atomicity (FR-024)**: the `notifications_log` insert (unique
  `dedup_key = "telegram:project:<mostaql_id>"`) and the project's `notified` flip happen in **one
  transaction**, committed **immediately after** a successful `send_message`. A crash mid-send can at
  worst **re-send once** (acceptable, at-least-once) but never drop.
- **R10 — Telegram render**: `parse_mode=HTML` (avoids MarkdownV2 escaping pain with `-`, `.`, `(` in
  Arabic titles/budgets); "time since posting" is **re-derived at render** from `posted_at`/`scraped_at`;
  absolute timestamps shown in `owner_timezone` (`zoneinfo`); messages kept well under 4096 chars.
- **R11 — Heartbeat / downtime (FR-029, honest single-box boundary)**: the worker persists
  `last_successful_poll_at` and sends a periodic Telegram **heartbeat** (config cadence). A self-check job
  alerts when `now − last_successful_poll_at > 2 × poll_interval` (covers *scheduler-alive-but-poll-failing*).
  **Box/process fully dead is inherently undetectable from the box** — documented limitation; recommended
  ops mitigation is `systemd` `Restart=always` plus an optional off-box uptime check (deferred, not code
  in this feature).
- **R12 — Secrets vs tunables (constitution III + IX)**: behavior tunables live in the DB `settings`
  table (seeded on first run); **secrets** (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`) live
  in `.env` (gitignored), loaded via typed settings at startup. A committed `.env.example` documents them.
- **R13 — Golden HTML fixtures**: capture real fixtures (listing, project page, `/u/` profile, a
  challenge/blocked page) committed as test inputs, plus a **synthetic** fixture for the
  `لم يحسب بعد` not-yet-calculated state (never observed live — the single most constitution-critical case).
- **R14 — Delay defaults reconciled**: adopt §5's scheme (it has SLA math); discard the looser "3–5 s"
  suggestion so there is one canonical default per knob.
