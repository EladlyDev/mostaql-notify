# Phase 1 Data Model — Analytics and Insights

This feature is **read-only**. It adds **no table, no column, and no Alembic migration** — the Alembic head is
unchanged. The only new persisted state is additive `settings` rows (below). Everything else in this document
describes **derived, read-time shapes** (the aggregate dataclasses and the API DTOs) computed from existing
rows, not stored entities. Existing tables are read **without modification**; types referenced reuse
`db/types.py` (`UtcDateTime`, `make_enum`, `utcnow()`).

---

## Read-only data sources (existing tables this feature reads)

| Source (existing) | Fields read | Feeds |
|---|---|---|
| `projects` | `eval_status` (qualified predicate), `posted_at` (fallback `scraped_at`), `qualified_at`, `category`, `budget_min`/`budget_max`/`currency`, `tier`, `bids_count`, `id`/`title`/`url` | heatmap, volume, budget, competition (age base), outcomes, funnel base |
| `project_scores` | `score`, `outcome` (`open`/`closed_no_hire`/`hired`/`unknown`), `closed_observed_at` | outcomes (shares, time-to-close, missed), suggested-threshold tip |
| `project_snapshots` | `captured_at`, `bids_count`, `site_status` | competition (bids-vs-age curve, bidding-by-hour) |
| `personal_records` | `favorite`, `status`, `applied_at`, `status_changed_at` | funnel, missed-opportunity join |
| `settings` | `personal_statuses` (ordered), `category_slug`, `budget_comparison_basis`, `currency_usd_rates`, `owner_timezone`, the budget-floor keys, + the new `analytics_*` keys | status ranking, budget USD basis, tz, budget-fallback tip, thresholds |
| `app_state` | `active_budget_floor` (via `qualify.budget_policy.load_policy`) | budget-fallback tip |

**No write occurs to any of the above.** A test asserts the project/score/snapshot/personal tables are
byte-for-byte unchanged across an `/api/analytics/overview` call (Constitution IV).

---

## New settings keys (added to `config/settings_store.py::DEFAULTS`)

Format `key: (default, "type")`, seeded idempotently by `seed_defaults`. The numeric keys are also registered
in `api/settings_spec.py` as `SettingSpec(key, type, min, max, label_ar)` (a new **"التحليلات"** group on the
settings form). No app-state flag and no re-score trigger are added (analytics values are read at query time).

| Key | Default | Type | Editable (form) | Min/Max | Label (ar) |
|---|---|---|---|---|---|
| `analytics_timezone` | `""` | str | no (DB-edit, like `owner_timezone`) | — | (المنطقة الزمنية للتحليلات) |
| `analytics_default_range_days` | `90` | int | yes | ≥1 | المدى الزمني الافتراضي (أيام) |
| `analytics_min_support` | `30` | int | yes | ≥1 | الحد الأدنى للبيانات قبل إظهار التحليل |
| `analytics_min_wins_support` | `5` | int | yes | ≥1 | الحد الأدنى لعدد الصفقات الرابحة قبل نصائح الفوز |
| `analytics_crowded_bids` | `15` | int | yes | ≥1 | عدد العروض الذي يعتبر "مزدحمًا" |
| `analytics_early_bids` | `5` | int | yes | ≥1 | عدد العروض المبكّر |
| `analytics_max_tips` | `6` | int | yes | 1–20 | أقصى عدد للنصائح |
| `analytics_suggested_threshold_keep` | `0.9` | float | yes | 0–1 | نسبة الصفقات الرابحة المحتفظ بها عند اقتراح حد التقييم |

`analytics_timezone` resolution: **empty ⇒ follow `owner_timezone`**; an unparseable value ⇒ `Africa/Cairo`
(mirrors the existing `today_start_utc` fallback).

---

## Derived aggregate shapes (computed at read time — not stored)

Each `analytics/aggregates.py` function returns a small dataclass; every one carries `enough_data: bool` and
the support count behind it. (Field names below are the API DTO field names — see the DTO section.)

### PostingHeatmap
- `cells: list[HeatmapCell]` — `{weekday: 0..6 (Sat..Fri), hour: 0..23, count: int}` (only non-zero cells, or
  the full 168 — frontend tolerates both); `weekday_labels: list[str]` (Arabic).
- `total: int`, `peak: HeatmapCell | None`, `enough_data: bool` (`total ≥ analytics_min_support`).

### VolumeTrends
- `by_day: list[VolumePoint]`, `by_week: list[VolumePoint]` — `{period: "YYYY-MM-DD" | "YYYY-Www", total: int,
  qualified: int}`.
- `category: str` (the configured slug; today `"development"`), `enough_data: bool` (≥2 non-empty buckets).

### BudgetDistribution
- `buckets: list[BudgetBucket]` — `{lo: number | null, hi: number | null, count: int}`; one bucket may be the
  `unknown` band (`lo=hi=null`) for projects with no usable budget.
- `tier1_count: int`, `tier2_count: int`, `unknown_count: int`, `total: int`, `enough_data: bool`.

### CompetitionDynamics
- `age_curve: list[CompetitionPoint]` — `{age_lo_h: number, age_hi_h: number, median: number, p25: number,
  p75: number, n: int}`.
- `crowded_bids: int` (echo of the setting), `crowded_after_hours: number | null` (first band median ≥
  `crowded_bids`; `null` if never), `headline: str` (plain Arabic).
- `by_hour: list[int]` (length 24, summed positive bid deltas per analytics-tz hour).
- `enough_data: bool`.

### OutcomeAnalytics
- `hired_count: int`, `no_hire_count: int`, `unknown_count: int`, `open_count: int` (open shown for context,
  excluded from shares), `hired_share: number | null`, `no_hire_share: number | null`.
- `time_to_close_hours: {mean: number | null, median: number | null, p25: number | null, p75: number | null}`.
- `missed: list[MissedProject]` — `{id, title, url, budget_usd: number | null}` (hired + never applied);
  `missed_count: int`.
- `enough_data: bool` (`concluded ≥ analytics_min_support`; the missed list renders even at 0).

### Funnel  *(monotonic — see research R4)*
- `stages: list[FunnelStage]` — ordered `seen, favourited, applied, in_discussion, won`, each
  `{key, label_ar, count: int, conv_from_prev: number | null, lag_median_hours: number | null}`.
  `conv_from_prev` is `null` for the base stage and for any zero-denominator step; `lag_median_hours` is
  populated only for `applied` (others `null` = unavailable).
- `seen: int`, `enough_data: bool` (`seen ≥ analytics_min_support`).

### Tips
- `tips: list[Tip]` — `{key, text: str (Arabic sentence), evidence: dict}` — ranked, length ≤
  `analytics_max_tips`; a tip is **absent** (not emitted) when its support is below threshold.

---

## DTOs (`api/schemas.py` additions)

All are computed response models — **no `from_attributes`** (none project an ORM row directly); not-calculated
numerics are `| None = None` (never coerced to 0), per the codebase convention.

- **`AnalyticsRange`**: `date_from: date`, `date_to: date`, `timezone: str` (the resolved analytics tz),
  `default_applied: bool` (true when no range was supplied).
- **`HeatmapCell`**: `weekday: int`, `hour: int`, `count: int`.
- **`PostingHeatmap`**: `cells: list[HeatmapCell]`, `weekday_labels: list[str]`, `total: int`,
  `peak: HeatmapCell | None = None`, `enough_data: bool`.
- **`VolumePoint`**: `period: str`, `total: int`, `qualified: int`.
- **`VolumeTrends`**: `by_day: list[VolumePoint]`, `by_week: list[VolumePoint]`, `category: str`,
  `enough_data: bool`.
- **`BudgetBucket`**: `lo: float | None = None`, `hi: float | None = None`, `count: int`.
- **`BudgetDistribution`**: `buckets: list[BudgetBucket]`, `tier1_count: int`, `tier2_count: int`,
  `unknown_count: int`, `total: int`, `enough_data: bool`.
- **`CompetitionPoint`**: `age_lo_h: float`, `age_hi_h: float`, `median: float`, `p25: float`, `p75: float`,
  `n: int`.
- **`CompetitionDynamics`**: `age_curve: list[CompetitionPoint]`, `crowded_bids: int`,
  `crowded_after_hours: float | None = None`, `headline: str`, `by_hour: list[int]`, `enough_data: bool`.
- **`TimeToClose`**: `mean: float | None = None`, `median: float | None = None`, `p25: float | None = None`,
  `p75: float | None = None`.
- **`MissedProject`**: `id: int`, `title: str | None = None`, `url: str | None = None`,
  `budget_usd: float | None = None`.
- **`OutcomeAnalytics`**: `hired_count: int`, `no_hire_count: int`, `unknown_count: int`, `open_count: int`,
  `hired_share: float | None = None`, `no_hire_share: float | None = None`, `time_to_close_hours: TimeToClose`,
  `missed: list[MissedProject]`, `missed_count: int`, `enough_data: bool`.
- **`FunnelStage`**: `key: str`, `label: str`, `count: int`, `conv_from_prev: float | None = None`,
  `lag_median_hours: float | None = None`.
- **`Funnel`**: `stages: list[FunnelStage]`, `seen: int`, `enough_data: bool`.
- **`Tip`**: `key: str`, `text: str`, `evidence: dict = {}`.
- **`AnalyticsOverview`** (response of `GET /api/analytics/overview`): `range: AnalyticsRange`,
  `heatmap: PostingHeatmap`, `volume: VolumeTrends`, `budget: BudgetDistribution`,
  `competition: CompetitionDynamics`, `outcomes: OutcomeAnalytics`, `funnel: Funnel`, `tips: list[Tip]`.

(Forward refs — `PostingHeatmap` referencing `HeatmapCell`, etc. — resolved with `model_rebuild()` at module
end, matching the existing `ProjectDetail.model_rebuild()` pattern.)

---

## Frontend DTO types (`frontend/lib/types.ts` additions)

Plain exported `interface`s, snake_case fields mirroring the API, nullable as `| null` — one per DTO above
(`AnalyticsOverview`, `AnalyticsRange`, `PostingHeatmap`/`HeatmapCell`, `VolumeTrends`/`VolumePoint`,
`BudgetDistribution`/`BudgetBucket`, `CompetitionDynamics`/`CompetitionPoint`, `OutcomeAnalytics`/`TimeToClose`/
`MissedProject`, `Funnel`/`FunnelStage`, `Tip`). No new string-union enums are required (weekday/hour are
plain ints; tip `key`s are free strings the UI maps to icons).

---

## State transitions

**None.** This feature introduces no entity with a lifecycle and performs no state change. The aggregates are
recomputed from current rows on every request; the only "transition" is the one-time `seed_defaults` insert of
the new `settings` rows on first run.

---

## Query / index notes (all covered by existing indexes — no new index)

- **Heatmap / volume / budget**: filtered scans of `projects` over `posted_at`/`scraped_at`/`qualified_at`
  within the UTC window + `eval_status` — covered by `ix_projects_posted_at`/`ix_projects_scraped_at`/
  `ix_projects_qualified_at`/`ix_projects_eval_status`. Budget USD basis via `qualify.filters.budget_usd`;
  tier from `projects.tier`.
- **Competition**: `project_snapshots` read time-ordered per project — covered by
  `ix_project_snapshots_project_captured` (`project_id`, `captured_at`); joined to `projects.posted_at` for
  age.
- **Outcomes**: `project_scores.outcome` + `closed_observed_at` for concluded projects (qualified join);
  missed = `outcome == hired` left-joined to `personal_records` where the record is absent or
  `applied_at IS NULL`.
- **Funnel**: `personal_records` (`favorite`, `status`, `applied_at`) joined to qualified `projects`; status
  rank from the configured `personal_statuses` list — covered by `ix_personal_records_status`/
  `ix_personal_records_favorite`.
- **Budget-fallback tip**: `qualify.budget_policy.load_policy(session, settings)` reads `app_state.
  active_budget_floor`; the recent Tier-1 count reuses the same windowed `qualified_at` scan as volume.
