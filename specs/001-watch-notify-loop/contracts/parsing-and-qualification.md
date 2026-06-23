# Contract: Parsing & Qualification

**Feature**: `001-watch-notify-loop`

Defines the pure parsing functions (Arabic-first) and the fail-closed qualification decision. These are
the constitution-critical seams (Principles V and VII).

## Parsing (pure, dependency-free; `now_utc` injected)

```python
def normalize_text(s: str) -> str
    # NFKC; map Arabic-Indic (U+0660–0669) AND Persian (U+06F0–06F9) digits → ASCII;
    # U+066C(thousands)→delete, U+066B(decimal)→".", U+066A(percent)→"%";
    # strip bidi marks (U+200E/200F/202A–202E), tatweel (U+0640); NBSP→space; drop "," between digits.

def parse_budget(s: str) -> tuple[Decimal | None, Decimal | None, str | None]
    # returns (min, max, currency). One number → point estimate (min==max).
    # currency: "$"/"دولار" → "USD"; otherwise None + log loudly (NEVER assume USD).

def parse_hiring_rate(s: str) -> float | None
    # if normalized contains stem "يحسب" → None (unknown / لم يحسب بعد).
    # else extract (\d+(?:\.\d+)?)\s*% → float. No "%" found → None + log.

def parse_relative_time(s: str, now_utc: datetime) -> datetime | None
    # strip منذ/قبل; optional int (default 1) + Arabic stem unit incl. dual forms; now_utc - delta (UTC).
    # unrecognized → None + log. Month=30d, year=365d (approx; display-only).
```

**Contract**: every function is total and side-effect-free except structured logging. On any
unrecognized input it returns `None` and emits a warning routed to the Telegram alert path (fail-loud
sentinel) — it never raises and never guesses.

## Qualification (fail-closed — FR-010/011/012)

```python
@dataclass(frozen=True)
class Qualification:
    qualified: bool
    tier: int | None            # 1 or 2 when qualified
    reason: str                 # human-readable disqualification reason when not qualified

def qualify(project, client, policy: BudgetPolicy, settings) -> Qualification
```

A project qualifies **iff ALL** hold (any failure ⇒ `qualified=False` with a `reason`):

1. **Hiring rate real & above floor**: `client.hiring_rate is not None` AND
   `client.hiring_rate > settings.min_hiring_rate`. (NULL ⇒ disqualify; `0.0` ⇒ disqualify — two
   distinct code paths, both tested.)
2. **Budget meets active floor**: let `basis = settings.budget_comparison_basis` (default `max`);
   pick `budget_max`/`budget_min`/midpoint; one-sided ⇒ use the present bound; **none ⇒ disqualify**.
   Normalize to USD via `settings.currency_usd_rates[currency]`; **currency None or unmapped ⇒
   disqualify**. Qualifies if `usd_value ≥ policy.active_floor`.
3. **Open & development**: `site_status == open` AND `category == development`.
   (`unknown` status ⇒ disqualify — fail-closed.)
4. **Exclusion check**: `exclusion_passes(project, settings)` — pass-through (no rules) in this feature;
   structured as a distinct stage so rules can be added later without touching the flow (FR-013).

**Tier**: USD-budget `≥ 250` → 1; `[active_floor, 250)` → 2.

## Dynamic budget policy with hysteresis (FR-014–018, research R5)

```python
@dataclass
class BudgetPolicy:
    active_floor: Decimal       # 250 or 100; persisted in app_state

def recompute_floor(current_floor, settings, session) -> Decimal
    # window_count = COUNT(projects WHERE tier==1 AND qualified_at >= now_utc - fallback_window_hours)
    # if current == 250 and window_count <  fallback_target            -> 100
    # if current == 100 and window_count >  fallback_target + buffer   -> 250
    # else: unchanged (the [target, target+buffer] dead-band prevents flapping)
```

**Contract**: `recompute_floor` runs **once per poll cycle, before** evaluating that cycle's projects;
the window keys on the authoritative `qualified_at` (never the fuzzy `posted_at`). The result is
persisted to `app_state.active_budget_floor` so the decision survives restarts.
