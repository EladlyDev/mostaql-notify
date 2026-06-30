# Contract: Analytics Aggregates & Tips (Feature 6)

The computation contract for `src/mostaql_notifier/analytics/`. Every function here is **pure / total**
(side-effect-free, raises on no input) and is unit-tested in isolation with injected `settings` and `now`.
All read from existing rows; **none write**. Symbols in `code` are `settings` keys (defaults in parentheses)
or existing helpers. "Qualified" ≡ `Project.eval_status == EvalStatus.qualified`. "Window" ≡ the half-open
UTC range `[utc_start, utc_end)` derived from the request's analytics-tz calendar date range.

---

## 0. Timezone & windowing — `analytics/timezone.py`

- `analytics_tz(session) -> ZoneInfo`: read `analytics_timezone` (`""`); **empty ⇒ read `owner_timezone`
  (`"Africa/Cairo"`)**; unparseable ⇒ `ZoneInfo("Africa/Cairo")`. Single source of the analytics tz.
- `local_parts(dt_utc, tz) -> (weekday, hour, local_date)`: `dt_utc.astimezone(tz)`, then
  `weekday = (local.weekday() + 2) % 7` (**0=Sat … 6=Fri**), `hour = local.hour`, `local_date = local.date()`.
  DST-correct because `astimezone` applies the offset valid at `dt_utc`.
- `day_key(dt_utc, tz) -> "YYYY-MM-DD"`, `iso_week_key(dt_utc, tz) -> "YYYY-Www"` (ISO year+week of the local
  date).
- `window_bounds(date_from, date_to, tz) -> (utc_start, utc_end)`: `utc_start =
  midnight(date_from, tz).astimezone(UTC)`; `utc_end = midnight(date_to + 1 day, tz).astimezone(UTC)`
  (half-open ⇒ no double-count at the boundary). If `date_from` omitted ⇒ `date_to − analytics_default_range_days
  (90)`; if `date_to` omitted ⇒ today in `tz`. `date_from > date_to` ⇒ the router returns 422.
- **Posting-time rule** (used everywhere a project's "when" is needed): `posting_time(project) = project.posted_at
  or project.scraped_at` (`posted_at` is nullable + approximate; `scraped_at` is NOT NULL — so a project is
  always placeable). Unknown bid counts and unknown hiring rates remain **distinct from 0** (never coerced).

---

## 1. `posting_heatmap(session, settings, *, utc_start, utc_end) -> PostingHeatmap`

- Rows: qualified projects with `posting_time` in window.
- For each: `(weekday, hour, _) = local_parts(posting_time)`; increment `grid[weekday][hour]`.
- `total = Σ grid`; `peak =` the `(weekday, hour)` with the max count (`None` if `total == 0`).
- `enough_data = total ≥ analytics_min_support (30)`.
- Output `cells` (non-zero cells suffice; frontend tolerates a sparse list) + Arabic `weekday_labels`
  (`["السبت","الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة"]`).

## 2. `volume_trends(session, settings, *, utc_start, utc_end) -> VolumeTrends`

- Rows: **all** projects with `posting_time` in window (not only qualified).
- `by_day`: group by `day_key(posting_time)` → `{period, total = count, qualified = count where qualified}`.
- `by_week`: same grouping on `iso_week_key`.
- `category = category_slug ("development")`; the result is shaped as a list so additional categories slot in
  later (today a single category).
- `enough_data =` at least **2** non-empty day buckets.

## 3. `budget_distribution(session, settings, *, utc_start, utc_end) -> BudgetDistribution`

- Rows: qualified projects with `posting_time` in window.
- USD basis: `budget_usd(project, settings)` (reuses `qualify.filters` — honours `budget_comparison_basis`,
  one-sided budgets, and `currency_usd_rates`). `None` ⇒ the **unknown** band (counted, never dropped).
- Buckets: fixed USD bands `[0–100), [100–250), [250–500), [500–1000), [1000–2500), [2500+)` plus the
  `unknown` band (`lo=hi=null`). (Band edges are presentation constants, not behaviour thresholds.)
- `tier1_count = count(tier == 1)`, `tier2_count = count(tier == 2)`, `unknown_count = count(budget_usd is
  None)`, `total = len(rows)`.
- `enough_data =` qualified-with-budget `≥ analytics_min_support`.

## 4. `competition_dynamics(session, settings, *, utc_start, utc_end) -> CompetitionDynamics`

Built from `project_snapshots` of qualified projects whose `posting_time` is in window.

- **Age curve**: for each snapshot with a known `bids_count`, `age_h = (captured_at − posting_time)/3600`
  (drop negative ages from clock skew). Bucket ages into bands
  `[0,1),[1,2),[2,4),[4,8),[8,16),[16,24),[24,48),[48,72),[72,∞)`. Per band: `median`, `p25`, `p75`
  (`statistics.quantiles`), `n`. **Median + IQR, never mean alone** (FR-032).
- **Crowded headline**: `crowded_bids = analytics_crowded_bids (15)`; `crowded_after_hours =` the `age_lo_h`
  of the first band whose `median ≥ crowded_bids` (`None` if no band reaches it). `headline` (Arabic): either
  "عادةً يتجاوز المشروع {crowded_bids} عرضًا خلال حوالي {hours} ساعة من نشره" or, if never, a "لا يصل عادةً
  إلى هذا الازدحام ضمن الفترة المرصودة" message.
- **Bidding-by-hour**: per project, over consecutive snapshots ordered by `captured_at`,
  `delta = max(0, bids[i] − bids[i−1])`; add `delta` to `by_hour[hour_of(captured_at[i])]` (analytics tz).
  Length-24 array. Approximation bounded by the re-check cadence (documented as a relative pattern).
- `enough_data =` (#projects with ≥2 snapshots ≥ 3) **and** (total snapshots in window ≥ `analytics_min_support`).
  A single-snapshot project contributes to the age curve but not to velocity/by-hour.

## 5. `outcome_analytics(session, settings, *, utc_start, utc_end) -> OutcomeAnalytics`

- Rows: qualified projects whose `posting_time` is in window, joined to `project_scores`.
- Counts by `outcome`: `hired_count`, `no_hire_count` (`closed_no_hire`), `unknown_count`, `open_count`.
- Shares over **concluded** only (`hired + no_hire`): `hired_share = hired/(hired+no_hire)` (`None` if
  denominator 0 or below support); `no_hire_share` likewise. **Open excluded; unknown never folded into
  hired** (FR-017, FR-020, Constitution VII).
- **Time-to-close** (concluded, `closed_observed_at` present): `ttc_h = (closed_observed_at − posting_time)/3600`;
  report `mean`, `median`, `p25`, `p75` (median always alongside mean — FR-032).
- **Missed opportunities**: `outcome == hired` AND (no `personal_records` row **or** `applied_at IS NULL`) →
  `missed` list `{id, title, url, budget_usd}` (cap the list to a sane length for display; `missed_count` is
  the full count) and `missed_count`.
- `enough_data =` concluded `≥ analytics_min_support` (the `missed` list and `missed_count` render even at 0).

## 6. `funnel(session, settings, *, utc_start, utc_end) -> Funnel`  *(monotonic — research R4)*

- **Seen** = qualified projects surfaced in window (by `qualified_at` fallback `scraped_at`). Base denominator.
- Status rank from the configured ordered `personal_statuses` (via `personal/statuses.py`); `applied`,
  `in_discussion`, `won` are matched by their config keys (`APPLIED_KEY` for the applied stamp).
- Per seen project, compute its reached set so stages are **monotonic** (`seen ≥ favourited ≥ applied ≥
  in_discussion ≥ won`):
  - `reached_applied = applied_at is not None OR rank(status) ≥ rank("applied")`
  - `reached_discussion = rank(status) ≥ rank("in_discussion")`
  - `reached_won = status == "won"`
  - `reached_favourited = favorite OR reached_applied` (applying implies interest)
- Stage counts = number of seen projects with the corresponding `reached_*` true (`seen` itself = all).
- `conv_from_prev` = `stage / prev_stage`, `None` for `seen` and for any zero-denominator step (FR-023).
- `lag_median_hours`: **`applied` only** = median of `(applied_at − seen_time)/3600` over projects with
  `applied_at`; `favourited`/`in_discussion`/`won` lags = `None` (**unavailable** — no per-stage timestamp is
  retained; never fabricated — FR-022).
- `enough_data =` `seen ≥ analytics_min_support`.

## 7. `tips.generate_tips(overview, settings, *, session) -> list[Tip]`

Pure rules over the already-computed aggregates; **no external service / model** (FR-029). Each rule emits at
most one tip and **only** when its support gate holds; the list is ranked (order below) and truncated to
`analytics_max_tips (6)`. Every tip carries `evidence` (the figures it cites).

| key | Gate | Computation → `text` (Arabic) | `evidence` |
|---|---|---|---|
| `peak_window` | `heatmap.enough_data` | from `heatmap.peak` (+ near-peak cells) → "أكثر المشاريع المؤهلة تظهر يوم {day} حوالي الساعة {hour} — كن جاهزًا حينها" | peak weekday/hour, count, share |
| `bid_speed` | `competition.enough_data` | smallest age band whose median ≥ `analytics_early_bids (5)` → "تتجاوز نصف المشاريع {early} عروض خلال ~{X} ساعة — قدّم خلال {X} ساعة" | early_bids, hours |
| `win_timing` | wins ≥ `analytics_min_wins_support (5)` | compare median applied-lag of won vs all applied; if shorter → "صفقاتك الرابحة غالبًا من مشاريع تقدّمت لها مبكرًا (خلال ~{Z} ساعة)" | won_applied_lag, overall_applied_lag, n_wins |
| `score_threshold` | wins ≥ `analytics_min_wins_support` AND wins are scored | replay (below) → "حدّ تقييم حوالي {T} كان سيحتفظ بـ{keep%} من صفقاتك الرابحة مع استبعاد {cut%} من الباقي — مجرد اقتراح" | T, kept_wins, total_wins, cut_share |
| `budget_fallback` | `load_policy().active_floor == budget_fallback_floor` AND recent Tier-1 count < `fallback_target` | "عرض مشاريع الفئة الأولى منخفض، لذا انخفض حدّ الميزانية إلى المستوى الاحتياطي" | active_floor, tier1_recent, fallback_target |

**Suggested-threshold replay** (`score_threshold`): let `W` = scores of past wins (qualified, `status=="won"`,
scored). Candidate cut-offs = the distinct win scores, descending. Pick the **highest** `T` such that
`|{w ∈ W : w ≥ T}| / |W| ≥ analytics_suggested_threshold_keep (0.9)`. Report `T`, the wins retained, and
`cut_share` = the fraction of *non-win* qualified scored projects with score `< T` (the noise it would cut).
**Advisory only** — sets nothing, gates nothing, sends nothing (FR-027).

**Honesty rules**: a tip below its gate is **omitted entirely** (FR-025) — never shown weakened. The
`budget_fallback` tip states the live condition (low Tier-1 supply → relaxed floor) and does **not** claim a
duration (no floor-change history is stored). No rule consults anything outside the owner's own data.

---

## Invariants (test gates)

- **Read-only**: computing any aggregate / tip issues no `INSERT`/`UPDATE`/`DELETE` to projects, clients,
  scores, snapshots, outcomes, or personal records (asserted before/after an `/api/analytics/overview` call).
- **Honest under thin data**: every section returns `enough_data`, and `len(tips) == 0` on an empty DB.
- **Fail-closed outcomes**: `unknown` is never added to `hired`; open is never in the shares.
- **Timezone**: a project at 23:30 local on the last day of the range is counted on that local day/hour, and a
  DST-shift instant buckets to the correct local hour.
- **Robust stats**: `time_to_close` and the age curve always expose a median; a single extreme outlier moves
  the mean but not the reported median/headline.
- **Funnel monotonic**: `seen ≥ favourited ≥ applied ≥ in_discussion ≥ won`; a zero-denominator step yields
  `conv_from_prev == null`, never an error.
- **Config over code**: changing any `analytics_*` setting changes the output on the next call with no code
  change and no recompute trigger.
