# Contract: Telegram Messages (outbound only)

**Feature**: `001-watch-notify-loop`

The only user-facing output. Two message kinds: **project notification** and **health alert** (plus a
periodic **heartbeat**). Sent via `ExtBot.send_message` to the configured private chat; `parse_mode=HTML`
(avoids MarkdownV2 escaping pain with `-`, `.`, `(` common in Arabic titles/budgets). Keep well under
4096 chars.

## Project notification (FR-022/023/025)

Required fields, in order: **title · budget range with tier · hiring rate · current bid count · time
since posting · category · direct link**. No opportunity score (out of scope; everything here already
passed the hard filters).

Template (HTML; Arabic title is RTL, numeric/LTR fields kept on their own lines so bidi does not scramble):

```
🆕 <b>{title}</b>

💰 {budget_min}–{budget_max} {currency}  ·  <b>Tier {tier}</b>
👤 Hiring rate: {hiring_rate:.0f}%
📨 Bids: {bids_count}
🕒 Posted: {time_since_posting}
🏷️ {category}

🔗 {project_url}
```

Rules:
- `title`, `category` HTML-escaped. Budget formatted without trailing `.00`. `time_since_posting` is
  **re-derived at render** from `posted_at` (fallback `scraped_at`) — e.g. "12m ago", "2h ago"; if
  `posted_at` is unknown, show "unknown".
- Absolute timestamps (if ever shown) render in `owner_timezone` (`zoneinfo`); stored values stay UTC.
- Sent **exactly once** per project: guarded by `notifications_log.dedup_key =
  "telegram:project:<mostaql_id>"`; insert + `projects.notified=true` committed in one transaction right
  after a successful send (at-least-once + dedup, research R9).

## Health alert (FR-027/028, fail-loud)

Sent on block/structure-change/circuit-breaker entry and on recovery. Must state **what** and **what the
system is doing** (backing off / paused until):

```
⚠️ <b>Mostaql Notifier — health alert</b>
Type: {BLOCKED | CHALLENGE | STRUCTURE_CHANGE | RUN_ERROR}
Detail: {http_status / marker / "0 rows on non-empty listing" / exception}
Action: backing off — paused until {resume_at owner-tz}
Run: found={f} new={n} updated={u} errors={e}
```

De-duplicated so a sustained block does not spam (alert on state transitions, not every cycle).

## Heartbeat (FR-029, research R11)

Every `heartbeat_hours`, a terse liveness ping so the owner can tell the loop is alive:

```
💚 Mostaql Notifier alive — last successful poll {ts owner-tz}, active floor ${active_floor}
```

> Limitation (documented): if the process/box is fully dead, no in-process message can be sent;
> downtime is then detectable only by the **absence** of the expected heartbeat (and via an optional
> off-box watchdog, deferred). `systemd Restart=always` is the recommended ops mitigation.

## Reliability contract

- Every send wrapped in a bounded retry for `telegram.error.TimedOut`/`NetworkError` (on top of
  `AIORateLimiter`, which handles only `RetryAfter`). `AIORateLimiter(max_retries=3)` set explicitly.
- A failed notification send leaves `notified=false` (no `notifications_log` row) so it retries next
  cycle — never silently dropped.
