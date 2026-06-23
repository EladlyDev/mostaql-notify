# Contract: Fetch Layer Interface (the httpx ↔ Playwright swap boundary)

**Feature**: `001-watch-notify-loop`

The fetch layer is isolated behind ONE interface so swapping httpx → Playwright is a swap, not a
rewrite (user requirement; constitution X). Everything above this seam (parsing, qualification,
notification) depends only on `FetchResult`, never on httpx/Playwright types.

## Interface

```python
class FetchResult:
    url: str                 # final URL after redirects
    status: int              # HTTP status (0 for transport error)
    body: str                # decoded UTF-8 text (empty on transport error)
    body_bytes: int          # len of raw body, for size-based block detection
    headers: Mapping[str, str]
    elapsed_ms: int
    error: str | None        # transport/exception summary, else None

class Fetcher(Protocol):
    async def get(self, url: str, *, referer: str | None = None) -> FetchResult: ...
    async def aclose(self) -> None: ...
```

## Implementations

- **`HttpxFetcher`** (default): one persistent `httpx.AsyncClient(http2=True, follow_redirects=True)`,
  shared cookie jar, one stable header set chosen per process run, per-request `Referer`, ~20 s timeout.
- **`PlaywrightFetcher`** (fallback, lazily constructed): headless Chromium; same interface. Only
  instantiated when an escalation trigger fires (see below). Absent Playwright install ⇒ alert + skip,
  never crash.

## Behavioral contract

1. **Politeness is enforced ABOVE this interface** by the scheduler/orchestrator (delays, concurrency=1,
   per-request backoff). `Fetcher.get` performs exactly one HTTP GET; it does not sleep or retry.
2. **No exceptions for HTTP errors**: a 403/429/5xx returns a `FetchResult` with that `status`. Only
   unrecoverable programmer errors raise. Transport failures return `status=0, error=<summary>`.
3. **Redirects followed** (`/project/{id}` → slug URL). `FetchResult.url` is the final URL.
4. **Decoding**: body decoded as UTF-8 (Arabic preserved); `body_bytes` is the raw length for the
   size thresholds in block detection.

## Escalation to Playwright (fail-loud triggers — research §1/§5)

The orchestrator (not the fetcher) decides escalation. Escalate / alert when ANY:
- `status` in {403, 503} with a small body; or `status` 429 on the **listing**;
- body contains a challenge marker (`challenge_markers` config) or `cf-ray` header present;
- `status == 200` with a non-trivial body but the expected SSR selectors yield **zero** matches
  (listing project rows, or the project-page hiring-rate row) → structure-change.

On escalation: log loudly, push a Telegram health alert, optionally try **one** Playwright fetch to
confirm/bypass before tripping the circuit breaker (so a one-off interstitial doesn't cause a long pause).
Never silently return empty results.

## Pinned endpoints (verified 2026-06-23)

| Purpose | URL | Selector / notes |
|---|---|---|
| Listing (discovery only) | `https://mostaql.com/projects/development` (`?page=N`) | `div.project-row` ×25; links `a[href*="/project/"]` → `https://mostaql.com/project/{id}` |
| Project page (source of truth) | `https://mostaql.com/project/{id}` (redirects to slug) | budget, status `حالة المشروع`, client sidebar incl. hiring rate `معدل التوظيف` |
| Client profile (full record) | `https://mostaql.com/u/{username}` | rating, reviews, total spent, member-since `تاريخ التسجيل`, country, verification |

> Selectors are confirmed against a committed golden HTML fixture (research R13). The Mostaql-specific
> module is the ONLY place selectors live; changing them must not touch the orchestrator.
