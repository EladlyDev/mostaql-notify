# Contract: Scoring Model (Part A) — `scoring/model.py`

The precise, testable specification of the **pure** opportunity-scoring function, the freshness
deriver, and the stored breakdown shape. This file is the contract that
[`research.md`](../research.md) (R3 formulas, R6 freshness, R7 backfill, R10 normalization) and
[`data-model.md`](../data-model.md) (settings keys/defaults, `ScoreBreakdown`/`ScoreComponent` DTOs)
summarize — it does **not** contradict them; it pins them down to copyable formulas, worked numbers,
and the exact JSON written to `project_scores.breakdown`.

Two pure entry points are specified:

| Function | Module | Signature | Returns |
|---|---|---|---|
| **Scorer** | `scoring/model.py` | `score_project(project, client, *, settings, now_utc) -> ScoreResult` | `ScoreResult(score: float, breakdown: dict)` |
| **Freshness deriver** | `scoring/freshness.py` | `freshness(project, latest_snapshot, *, settings, now_utc) -> "green"\|"yellow"\|"red"` | one colour string |

Both are pure (no network, no DB, no clock read — `now_utc` is injected) and read only
already-materialized attributes off `project`, `client`, and the project's loaded `snapshots`
trajectory (the service eager-loads `project.snapshots`; the scorer never lazy-loads). Every constant
is a `settings` key (Config-over-Code, FR-008/FR-033); nothing about the model is a code literal.

---

## 1. Overview

The opportunity score is a single value on **0–100**:

```
score = 100 × Σ_i ( normalized_weight_i × sub_score_i )
```

over the **six** components below. Each component returns a sub-score `sub_score_i ∈ [0, 1]`
(bounded, monotonic, closed-form). Weights are normalized to sum to one at runtime (§2), so the
score is always a valid `0 ≤ score ≤ 100`.

- **Only `eval_status == qualified` projects are scored** (FR-011). The scorer itself is total over
  any inputs, but the service (`rescore_all`, the re-check loop, the settings-PUT re-score) only ever
  *calls* it for qualified projects; disqualified / pending projects keep `project_scores.score = NULL`
  and are excluded from score sort, score-range filter, and `/top`.
- The score is **recomputed while a project is `open`** and **frozen** at its last open value once the
  project is `closed`/`awarded` (the re-check loop stops calling the scorer for non-open projects —
  FR-015).
- Every component is **None-safe**: a missing input contributes the component's documented floor
  (never raises). The function returns for any project that is loaded.

`ScoreResult.score` is the float above (the canonical implementation keeps full precision and rounds
only for display). `ScoreResult.breakdown` is the dict persisted verbatim to `project_scores.breakdown`
(§4).

---

## 2. Weight normalization (FR-009)

Inputs: the six configured weights `w = [w_hiring, w_hire_volume, w_budget, w_competition,
w_freshness, w_rating]` read from `settings`. Let `W = Σ w_i`.

```
if W > 0:                      normalized_weight_i = w_i / W
elif W == 0:                   normalized_weight_i = 1/6   (equal fallback, all six)
record normalized = (abs(W - 1.0) > 1e-9)   # True whenever configured weights do NOT already sum to 1
```

- **Negatives / NaN are rejected upstream** by settings validation (`api/settings_spec.py` accepts only
  non-negative finite floats per weight; it does **not** force a sum of 1 — that would contradict
  FR-009). The scorer therefore assumes `w_i ≥ 0` and finite.
- Normalization is **scale-invariant**: doubling every weight leaves the score unchanged; only the
  *ratios* between components matter.
- The `normalized` flag is purely informational for the UI ("weights were rescaled"); it never changes
  the arithmetic.

| Configured weights | `W` | normalized weights | `normalized` |
|---|---|---|---|
| `0.35, 0.15, 0.15, 0.20, 0.10, 0.05` (defaults) | `1.00` | identical | `false` |
| `0.70, 0.30, 0.30, 0.40, 0.20, 0.10` (defaults ×2) | `2.00` | identical to defaults | `true` |
| `0.50, 0, 0, 0.50, 0, 0` | `1.00` | `0.50, 0, 0, 0.50, 0, 0` | `false` |
| `0, 0, 0, 0, 0, 0` | `0` | `1/6` each ≈ `0.1667` | `true` |

---

## 3. The six components

Settings defaults are quoted from `data-model.md`. For each: the keys + defaults, the exact formula
(copied from research R3), the input fields, the None/missing floor, and a worked number.

Symbols used in examples assume `now_utc = 2026-06-28T10:00:00Z`.

### (a) Hiring rate — confidence-shrunk

| Setting | Default | Meaning |
|---|---|---|
| `score_weight_hiring_rate` | `0.35` | weight (largest by default — FR-003) |
| `score_hiring_baseline` | `50.0` | neutral baseline `b` (0–100) |
| `score_hiring_shrink_k` | `5` | pseudo-count `k` (shrinkage strength) |

**Inputs**: `client.hiring_rate` (`r`, a 0–100 percentage; `None` ⇒ unknown), `client.projects_posted`
(`n`, sample size; `None` ⇒ `0`).

**Formula** (Bayesian shrinkage toward the baseline by sample size):

```
r      = client.hiring_rate  if not None else b
n      = client.projects_posted if not None else 0
r_adj  = (r · n + b · k) / (n + k)
sub_a  = r_adj / 100                              # ∈ [0, 1]
```

A high rate from few projects is pulled toward `b/100 = 0.5`; a rate backed by many projects barely
moves. **Floor / None handling**: `r = None ⇒ r = b`; `n = None ⇒ 0`, which makes `r_adj = b` ⇒
`sub_a = 0.5` (pure baseline, never a crash). `n + k ≥ k ≥ ... > 0` for `k ≥ 0` because if `k = 0` and
`n = 0` the implementation guards the denominator and returns `b/100` (still 0.5).

**Worked example** — `r = 90`, `n = 8`:
`r_adj = (90·8 + 50·5)/(8+5) = (720+250)/13 = 970/13 = 74.615` ⇒ `sub_a = 0.7462`.
Same rate from many projects (`n = 40`): `r_adj = (3600+250)/45 = 85.56` ⇒ `0.8556`
(higher — more sample, less shrinkage). Same rate from `n = 2`: `r_adj = 430/7 = 61.43` ⇒ `0.6143`
(dampened — the low-sample case, SC-008).

### (b) Hire volume / reliability — diminishing returns

| Setting | Default | Meaning |
|---|---|---|
| `score_weight_hire_volume` | `0.15` | weight |
| `score_hire_volume_halfsat` | `10` | half-saturation `s` |

**Inputs**: `client.hires_count` (`h`; `None` ⇒ `0`).

**Formula** (half-saturation Hill curve, reaches `0.5` at `h = s`):

```
h     = client.hires_count if not None else 0
sub_b = h / (h + s)                                # ∈ [0, 1)
```

**Floor / None handling**: `h = None ⇒ 0 ⇒ sub_b = 0` (component floor; no proven track record).

**Worked example** — `h = 12`, `s = 10`: `12 / 22 = 0.5455`. (`h = 10 ⇒ 0.5`; `h = 30 ⇒ 0.75`.)

### (c) Budget — diminishing returns to a cap, Tier-2 down-scale

| Setting | Default | Meaning |
|---|---|---|
| `score_weight_budget` | `0.15` | weight |
| `score_budget_cap_usd` | `1000` | diminishing-returns cap `c` (USD) |
| `score_budget_tier2_scale` | `0.6` | Tier-2 multiplier |

**Inputs**: `qualify.filters.budget_usd(project, settings)` — **reused, not redefined** (it already
honours `budget_comparison_basis`, one-sided budgets, and the `currency_usd_rates` table, and returns
`None` for an unknown currency or missing budget). `project.tier` (1 or 2; the tier from Feature 1 is
consumed, not recomputed — FR-010).

**Formula**:

```
usd   = float(budget_usd(project, settings)) if budget_usd(...) is not None else 0.0
sub_c = min(usd, c) / c                             # clamp to the cap, then ∈ [0, 1]
if project.tier == 2:
    sub_c = sub_c · score_budget_tier2_scale        # fallback-floor projects scaled down
```

**Floor / None handling**: `budget_usd == None` (one-sided-but-unparseable currency, or no figure)
⇒ `usd = 0 ⇒ sub_c = 0` (floor, no error — FR-010). A midpoint **above the cap** clamps to `1.0`
*before* the Tier-2 scale.

**Worked examples** (`c = 1000`): `usd = 750`, tier 1 ⇒ `750/1000 = 0.75`. `usd = 1500`, tier 1 ⇒
`min(1500,1000)/1000 = 1.0` (capped). `usd = 750`, **tier 2** ⇒ `0.75 × 0.6 = 0.45`.

### (d) Competition — crowdedness × velocity

| Setting | Default | Meaning |
|---|---|---|
| `score_weight_competition` | `0.20` | weight |
| `score_competition_halfsat_bids` | `15` | bid half-saturation for crowdedness |
| `score_competition_vel_cap` | `3.0` | bids/hour at which velocity sub-score hits `0` |

**Inputs**: `project.bids_count` (`bids`; `None` ⇒ `0`), the project's age (`age_hours`, from
`posted_at` ⇒ fallback `scraped_at`, see §3(e)), and the loaded `project.snapshots` trajectory
(ordered by `captured_at`; each has `captured_at` + `bids_count`).

**Formula** — the component is the **mean** of two sub-scores (fewer bids ⇒ higher; slower bid arrival
⇒ higher):

```
# crowdedness (fewer bids better)
crowd = 1 − bids / (bids + score_competition_halfsat_bids)

# velocity v = bids per hour
if len(snapshots) ≥ 2:
    earliest, latest = snapshots[0], snapshots[-1]      # first & last of the loaded window
    Δbids  = max((latest.bids_count or 0) − (earliest.bids_count or 0), 0)
    Δhours = max((latest.captured_at − earliest.captured_at).total_seconds()/3600, ε)   # ε = a small guard
    v = Δbids / Δhours
else:                                                   # first re-check — no prior snapshot
    v = bids / max(age_hours, 1.0)

vel   = 1 − min(v / score_competition_vel_cap, 1.0)
sub_d = (crowd + vel) / 2                               # ∈ [0, 1]
```

**Floor / None handling**: `bids = None ⇒ 0 ⇒ crowd = 1.0` and `v = 0 ⇒ vel = 1.0 ⇒ sub_d = 1.0`
(an unknown bid count is treated as *uncrowded*, the documented `None ⇒ 0` rule — never a crash).
With `< 2` snapshots, velocity falls back to `current / age` (first-re-check case); with `≥ 2` it uses
the trajectory (FR's "rate of bids relative to time open").

**Worked examples**:
- *First check*, `bids = 6`, `age_hours = 9`: `crowd = 1 − 6/21 = 0.7143`; `v = 6/9 = 0.667` ⇒
  `vel = 1 − 0.667/3 = 0.7778`; `sub_d = (0.7143+0.7778)/2 = 0.7460`.
- *Climbing*, two snapshots `5 → 12` bids over `2 h`, current `bids = 12`: `crowd = 1 − 12/27 = 0.5556`;
  `v = (12−5)/2 = 3.5 ⇒ vel = 1 − min(3.5/3, 1) = 0`; `sub_d = 0.2778` — the score drops as bids pile
  up fast (acceptance scenario US2-3).

### (e) Freshness — exponential age decay

| Setting | Default | Meaning |
|---|---|---|
| `score_weight_freshness` | `0.10` | weight |
| `score_freshness_halflife_hours` | `12.0` | decay half-life `H` |

**Inputs**: project age. `age_hours = (now_utc − posted_at)` in hours; if `posted_at is None`, fall back
to `scraped_at` (which is **NOT NULL**, so an age is always computable). Guard `age_hours = max(age_hours, 0)`
against clock skew / a future `posted_at`.

**Formula** (halves every `H` hours):

```
sub_e = 0.5 ** (age_hours / H)                      # ∈ (0, 1]
```

**Floor / None handling**: `posted_at = None ⇒ use scraped_at`; both absent is structurally impossible
(`scraped_at` non-null) — in that impossible case `age_hours = 0 ⇒ sub_e = 1.0`. Never raises.

**Worked example** — `posted_at = 2026-06-28T01:00:00Z` ⇒ `age_hours = 9`, `H = 12`:
`0.5 ** (9/12) = 0.5 ** 0.75 = 0.5946`. (`age = 0 ⇒ 1.0`; `age = 12 ⇒ 0.5`; `age = 24 ⇒ 0.25`.)

### (f) Client-rating adjustment — small signed nudge by review confidence

| Setting | Default | Meaning |
|---|---|---|
| `score_weight_rating` | `0.05` | weight (smallest by default) |
| `score_rating_min_reviews` | `3` | reviews for full confidence |

**Inputs**: `client.avg_rating` (`rating`, 0–5; `None` ⇒ neutral `3`), `client.reviews_count`
(`None` ⇒ `0`).

**Formula** (centred at the neutral 3-star, scaled by review confidence and a `0.5` damping):

```
rating     = client.avg_rating if not None else 3.0
reviews    = client.reviews_count if not None else 0
confidence = min(reviews / score_rating_min_reviews, 1.0)
sub_f      = clamp( 0.5 + ((rating − 3)/2) · confidence · 0.5 , 0.0, 1.0 )   # ∈ [0, 1]
```

Few reviews ⇒ `confidence → 0` ⇒ stays near neutral `0.5`. Full-confidence swing is `±0.5` from
neutral (so this component's *contribution* is at most `100 × 0.05 × 1.0 = 5` points — intentionally
"small").

**Floor / None handling**: `rating = None` **or** `reviews = 0/None ⇒ sub_f = 0.5` (neutral, no nudge).

**Worked example** — `rating = 4.5`, `reviews = 6`, `min_reviews = 3`:
`confidence = min(6/3, 1) = 1.0`; `sub_f = 0.5 + ((4.5−3)/2)·1·0.5 = 0.5 + 0.375 = 0.875`.
(`rating = 1, reviews = 10 ⇒ 0.5 + (−1)·0.5 = 0.0`; `rating = 5, reviews = 1 ⇒ 0.5 + 1·0.333·0.5 = 0.667`.)

---

## 4. Breakdown shape (`project_scores.breakdown` + the "Why?" / detail DTO)

The scorer returns `breakdown` as the dict below, persisted verbatim. It is a **superset** of the API
`ScoreBreakdown` DTO (`data-model.md`): the DTO exposes `score`, `components[]`, `normalized`,
`computed_at`; the stored dict additionally carries the `weights` block and the `inputs` echo for full
reproducibility (FR-004/FR-007).

Each entry of `components` is a **`ScoreComponent`**: `key`, `label`, `raw`, `sub_score`, `weight`
(the *normalized* weight), `contribution` (= `100 × weight × sub_score`, i.e. points out of 100). The
six `contribution` values sum to `score` (within float rounding). `raw` is each component's single
headline input (the full set is in `inputs`).

| `key` | `label` (ar, RTL) | `raw` source |
|---|---|---|
| `hiring_rate` | `معدل التوظيف` | `client.hiring_rate` |
| `hire_volume` | `حجم التوظيف` | `client.hires_count` |
| `budget` | `الميزانية` | `budget_usd` |
| `competition` | `المنافسة` | `project.bids_count` |
| `freshness` | `الحداثة` | `age_hours` |
| `rating` | `تقييم العميل` | `client.avg_rating` |

**Full JSON example** — the worked project from §3 (client `r=90, n=8, h=12, rating=4.5, reviews=6`;
project `budget_usd=750, tier 1, bids=6, posted 9 h ago`; first re-check, one snapshot;
`now_utc = 2026-06-28T10:00:00Z`). Default weights ⇒ `W = 1.0` ⇒ `normalized = false`:

```json
{
  "score": 70.80,
  "normalized": false,
  "computed_at": "2026-06-28T10:00:00Z",
  "components": [
    { "key": "hiring_rate", "label": "معدل التوظيف", "raw": 90.0,  "sub_score": 0.7462, "weight": 0.35, "contribution": 26.12 },
    { "key": "hire_volume", "label": "حجم التوظيف", "raw": 12,    "sub_score": 0.5455, "weight": 0.15, "contribution": 8.18 },
    { "key": "budget",      "label": "الميزانية",   "raw": 750.0, "sub_score": 0.7500, "weight": 0.15, "contribution": 11.25 },
    { "key": "competition", "label": "المنافسة",    "raw": 6,     "sub_score": 0.7460, "weight": 0.20, "contribution": 14.92 },
    { "key": "freshness",   "label": "الحداثة",     "raw": 9.0,   "sub_score": 0.5946, "weight": 0.10, "contribution": 5.95 },
    { "key": "rating",      "label": "تقييم العميل", "raw": 4.5,   "sub_score": 0.8750, "weight": 0.05, "contribution": 4.38 }
  ],
  "weights": {
    "configured": { "hiring_rate": 0.35, "hire_volume": 0.15, "budget": 0.15, "competition": 0.20, "freshness": 0.10, "rating": 0.05 },
    "sum": 1.0,
    "normalized": { "hiring_rate": 0.35, "hire_volume": 0.15, "budget": 0.15, "competition": 0.20, "freshness": 0.10, "rating": 0.05 }
  },
  "inputs": {
    "hiring_rate": 90.0,
    "projects_posted": 8,
    "hiring_rate_adjusted": 74.62,
    "hires_count": 12,
    "budget_usd": 750.0,
    "tier": 1,
    "bids_count": 6,
    "posted_at": "2026-06-28T01:00:00Z",
    "age_hours": 9.0,
    "avg_rating": 4.5,
    "reviews_count": 6,
    "snapshot_count": 1,
    "velocity_bph": 0.6667,
    "velocity_source": "current_over_age"
  }
}
```

`Σ contribution = 26.12 + 8.18 + 11.25 + 14.92 + 5.95 + 4.38 = 70.80 = score` ✓ (the detail-view bars
must therefore visibly add up to the total — SC-002). `velocity_source ∈ {"trajectory",
"current_over_age"}` records which velocity branch (§3d) fired, so "Why?" can explain a first-check
vs trajectory-derived velocity. `raw`, `sub_score`, `weight`, `contribution` are the four numbers each
detail bar renders.

---

## 5. Freshness signal (`scoring/freshness.py`) — separate from the freshness component

The green/yellow/red "still good?" traffic light (FR-024/FR-025, research R6) is **derived on read**,
**not stored**, and is **distinct** from the smooth freshness *component* of §3(e): the component is a
decay term in the score; the signal is a coarse, action-oriented colour.

| Setting | Default |
|---|---|
| `freshness_green_max_bids` | `8` |
| `freshness_green_max_age_hours` | `12` |
| `freshness_red_min_bids` | `20` |
| `freshness_red_min_age_hours` | `48` |

**Inputs**: `status` (from `latest_snapshot.site_status`, else `project.site_status`), `bids` (from
`latest_snapshot.bids_count`, else `project.bids_count`; `None ⇒ 0`), `age_hours` (as in §3e:
`posted_at` ⇒ fallback `scraped_at`).

**Rules** (evaluated **red → green → else yellow**; red wins):

```
RED    if status ∈ {closed, awarded, unknown}
       OR bids      ≥ freshness_red_min_bids        (default 20)
       OR age_hours ≥ freshness_red_min_age_hours   (default 48)

GREEN  if status == open
       AND bids      ≤ freshness_green_max_bids      (default 8)
       AND age_hours ≤ freshness_green_max_age_hours (default 12)

YELLOW otherwise   (cooling: aging and/or bids climbing, still open)
```

- A `closed` / `awarded` / `unknown` project always reads **red** regardless of its last score
  (acceptance US3-3; "looks unattractive even if its raw score was once high").
- **Low-data fallback (FR-025)**: the rule needs only *current* bids + age + status, so with a single
  snapshot (no velocity to compute) it degrades gracefully and never errors. `bids = None` is treated
  as `0` (won't trip the bid axis); status and age still apply.

**Worked transitions** (defaults): open, `bids = 4`, `age = 6 h` ⇒ **green**. open, `bids = 12`,
`age = 30 h` ⇒ **yellow** (cooling). open, `bids = 25` ⇒ **red** (crowded). `bids = 4`, `age = 50 h`
⇒ **red** (aged out). status `closed` (any bids/age) ⇒ **red**.

---

## 6. Edge-case behaviour table

| Spec edge case | Model behaviour |
|---|---|
| **Low-sample client** (few projects) | §3a shrinkage: `r_adj = (r·n + b·k)/(n+k)` pulls a high rate from small `n` toward `b/100 = 0.5`; same rate from large `n` barely moves. Dampens, never hides — the Feature-1 low-sample flag stays independent and honest (SC-008). |
| **One-sided budget** (only min or only max) | Delegated to `qualify.filters.budget_usd`, which already picks the present bound per `budget_comparison_basis`; the scorer never re-implements it (FR-010). |
| **Budget midpoint over the cap** | `sub_c = min(usd, c)/c` clamps to `1.0` **before** any Tier-2 scale — extra budget above `c` adds nothing. |
| **Tier-2 (fallback-floor) project** | After the cap clamp, `sub_c ×= score_budget_tier2_scale (0.6)`; tier is read from `project.tier`, not recomputed. |
| **No usable budget figure** | `budget_usd == None ⇒ usd = 0 ⇒ sub_c = 0` (component floor, no error). |
| **First re-check vs long history** (velocity) | `< 2` snapshots ⇒ `v = bids / max(age_hours, 1)` (`velocity_source = "current_over_age"`); `≥ 2` ⇒ `v = Δbids/Δhours` over the loaded window (`velocity_source = "trajectory"`). |
| **Missing bids** (`bids_count = None`) | Treated as `0`: `crowd = 1.0`, `v = 0 ⇒ vel = 1.0 ⇒ sub_d = 1.0` (uncrowded); the freshness signal likewise treats `None` bids as `0`. |
| **Missing `posted_at`** | Age from `scraped_at` (NOT NULL) in both the freshness component and the freshness signal; `age_hours = max(age, 0)` guards future timestamps. |
| **Weights not summing to one** | Normalized `w_i / Σw` (not rejected); `normalized = true`. `Σw = 0 ⇒ equal 1/6` each, `normalized = true`. Score stays `0–100` (FR-009). |
| **All-zero / missing components** | Each missing input contributes its documented floor (0 for hire-volume/budget, 0.5 neutral for hiring/rating, 1.0 uncrowded for competition, 1.0 newest for freshness); scoring never crashes (edge "all-zero or missing components"). |
| **Non-qualified project** | Not scored by the service (`eval_status != qualified` is skipped); `project_scores.score = NULL`; excluded from score sort/filter and `/top` (FR-011). |
| **Closed/awarded project** | The re-check loop stops calling the scorer; the last open score is **frozen** in `project_scores.score`; the freshness signal reads **red** (§5). |

---

## 7. Determinism & testability

`score_project` and `freshness` are **pure**: deterministic in their arguments, take an injected
`now_utc` (no `datetime.utcnow()` inside), perform **no network or DB I/O**, and read only
already-materialized attributes (`project.*`, `client.*`, and the eager-loaded `project.snapshots`).
Re-running with identical inputs yields an identical `score` and `breakdown` — exactly like the
existing `qualify` / `budget_policy` pure modules. This makes every behaviour below a fast, isolated
unit test (stub `project` / `client` / `snapshot` objects; a fixed `now_utc`).

**Required unit tests** (`tests/scoring/`):

1. **Per component (6)** — one test module each, asserting the §3 worked numbers and the floor/None
   path: `test_hiring_rate` (shrinkage: high-rate-low-`n` < high-rate-high-`n`; `None ⇒ 0.5`),
   `test_hire_volume` (`h=s ⇒ 0.5`; `None ⇒ 0`), `test_budget` (cap clamp to `1.0`; Tier-2 scale;
   `budget_usd None ⇒ 0`; one-sided delegated), `test_competition` (first-check fallback vs
   `≥2`-snapshot trajectory; climbing bids drop the sub-score; `None ⇒ 1.0`), `test_freshness_component`
   (`age=H ⇒ 0.5`; `posted_at None ⇒ scraped_at`), `test_rating` (full-confidence swing `±0.5`;
   low-reviews stays near `0.5`; `None ⇒ 0.5`).
2. **Normalization** — `test_normalization`: defaults (`W=1 ⇒ normalized false`, unchanged); defaults×2
   (`normalized true`, score identical → scale-invariance); `W=0 ⇒ equal 1/6, normalized true`;
   arbitrary `W ⇒ Σ normalized weight = 1`.
3. **Breakdown completeness** — `test_breakdown`: exactly six `ScoreComponent`s with all of
   `{key,label,raw,sub_score,weight,contribution}`; every `sub_score ∈ [0,1]`; `Σ contribution == score`
   (within tolerance); `0 ≤ score ≤ 100`; the `weights` block + `inputs` echo + `computed_at == now_utc`
   present; JSON-serializable.
4. **Freshness transitions** — `test_freshness_signal`: green/yellow/red at and across the default
   boundaries (`bids` 8↔9, `age` 12↔13, `bids` 19↔20, `age` 47↔48); `closed`/`awarded`/`unknown ⇒ red`
   irrespective of bids/age; single-snapshot low-data fallback returns a colour without error; a
   threshold change in settings moves the boundary.

(Service-level concerns — backfill scoring all qualified projects, the settings-PUT re-score, `/top`
ordering, the re-check freeze-on-close — live in `scoring/service.py` tests, not in this pure-model
contract.)
