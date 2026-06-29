# Contract Delta: Inbound Telegram Bot (Feature 4)

This documents **only the Feature 4 additions** to the Telegram surface already specified in
`../../003-personal-pipeline-workspace/contracts/telegram-bot.md`. Everything in that contract still
holds unchanged — the single-owner gate, the `pf:` callback codec, the Feature 3 action buttons
(Favorite / Applied / Dismiss / Add-note / Open), the `/find /pause /resume /health /stats` commands,
the add-note conversation, and the long-poll process/lifecycle. Feature 4 adds, on top of that:

1. a **score + tier line** in the project notification body,
2. a **"Why?" inline button** (`pf:why:{id}`) that replies with the score breakdown,
3. a **`/top [n]`** command listing the top open projects by score.

All three are **owner-chat-gated** (`is_owner`) and **reads-only** — they take no action on
mostaql.com and never mutate the personal record (Constitution VIII; FR-036). The Why reply and
`/top` both read the same `scoring/service.py` the dashboard uses, so the numbers always agree across
surfaces (FR-031, FR-032).

---

## 1. Score + tier in the project notification (FR-030)

`notify/format.py::build_project_message` gains one line. The current field order is

```
<b>title</b>
💰 {budget} · Tier T
📈 Hiring rate: NN%
🧮 Bids: NN
🕒 Posted: …
🏷️ {category}
🔗 {url}
```

Feature 4 inserts the **score line as the new headline field, directly under the bold title and
above the budget line** (the score is the value this feature introduces, so it leads):

```
<b>title</b>
🎯 Score: 82 · Tier 1      ← NEW
💰 {budget} · Tier T
📈 Hiring rate: NN%
🧮 Bids: NN
🕒 Posted: …
🏷️ {category}
🔗 {url}
```

- **Format**: `🎯 Score: {NN} · {Tier T}`, where `NN` is the latest `project_scores.score` rounded
  to an integer and `Tier T` reuses the existing `f"Tier {project.tier}"` / `"Tier ?"` rendering.
  The line **restates the tier next to the score** so the score field is self-contained per FR-030
  ("the project's opportunity score **and** its tier"); the existing `💰 … · Tier T` line is left
  exactly as-is (intentional, not a contradiction).
- **Own line / RTL-safe**: like every other field it sits on its own line, so the LTR score/tier
  numbers never visually scramble against an RTL Arabic title (matches the module's one-field-per-line
  convention).
- **HTML-escaped**: the value is rendered through the existing `html_escape(...)` before going into
  the `parse_mode=HTML` body, identical to the other numeric fields.
- **Null score → omit gracefully**: an as-yet-unscored project (no `project_scores` row, or
  `score IS NULL` — e.g. a brand-new project the backfill/re-check has not reached) **omits the score
  line entirely** rather than printing `🎯 Score: unknown`. The notification is never gated or delayed
  by the score (scoring is out of the notification path; gating is explicitly out of scope). The
  `_MAX_LEN` truncation logic is unchanged — the score line is short and fixed-width.

The score value comes from the project's loaded `project_scores` relationship (`project.score_row`);
`build_project_message` stays pure (no I/O) — the caller passes a project whose score row is already
loaded, consistent with how `client` is passed in today.

---

## 2. "Why?" inline button (FR-031)

### Codec & button

A new callback action joins the existing `pf:` codec in `notify/format.py`:

```python
CB_WHY = "why"
_CALLBACK_ACTIONS = frozenset({CB_FAVORITE, CB_APPLIED, CB_DISMISS, CB_NOTE, CB_WHY})
```

`build_callback_data(CB_WHY, project_id)` → **`pf:why:{project_id}`** (e.g. `pf:why:123`) — well
within Telegram's 64-byte limit (the DB integer id is short). `parse_callback_data` decodes it with
no other change (the new action is simply in the accepted set).

### Keyboard layout

`build_project_keyboard` gains the Why button. It is a **callback** button (not a URL button) and
shares the final row with the existing **Open** URL button — both are single-tap "inspect / leave"
actions, so they pair naturally and keep the 2-per-row shape:

```
[ ⭐ مفضّل (Favorite) ]   [ ✅ تقدّمت (Applied) ]
[ 🙈 إخفاء (Dismiss) ]    [ 📝 ملاحظة (Add note) ]
[ 🎯 لماذا؟ (Why?) ]      [ 🔗 فتح على مستقل (Open) ]
```

- `🎯 لماذا؟` → `callback_data = pf:why:{project_id}`.
- `🔗 فتح على مستقل` → unchanged URL button to `project.url`.
- When `project.url` is absent, Open is not rendered (existing behavior), so **Why stands alone on
  its own row** — it is never dropped. The four Feature 3 callback buttons and their `pf:` data are
  unchanged.

### Handler (`bot/callbacks.py`)

`handle_callback` routes `CB_WHY` in its own branch, parallel to the early `CB_NOTE` short-circuit,
**before** the Feature 3 mutation block — because Why is a read and must not run any
`personal/service.py` mutation or any message edit:

1. `is_owner(update)` gate first (non-owner taps are silently ignored, as today).
2. `parse_callback_data` → `(CB_WHY, project_id)`.
3. Open a `session_scope()`; if `session.get(Project, project_id) is None` → `query.answer(_NOT_FOUND)`
   ("المشروع غير موجود") and return (old/expired notification or deleted project).
4. `breakdown = scoring.service.get_breakdown(session, project_id)` — returns the **last stored**
   `ScoreBreakdown` (`{score, components:[{key,label,raw,sub_score,weight,contribution}], normalized,
   computed_at}`) read straight from `project_scores.breakdown`. For a closed project this is the
   value **frozen at its last open re-check** (the loop stops recomputing once closed); for an open
   one it is the most recent recompute.
5. If `breakdown is None` (project exists but was never scored — not qualified, or backfill hasn't
   reached it) → `query.answer()` to clear the spinner, then `reply_text("لا يوجد تقييم لهذا المشروع
   بعد")`. No error.
6. Otherwise: `query.answer()` to clear the spinner, then **send a reply** (`query.message.reply_text(
   build_score_breakdown_message(project, breakdown), parse_mode="HTML")`).

**Non-destructive (key difference from Feature 3 actions)**: the Why handler **does not call
`_confirm` / `edit_message_text`** — it sends a *new reply message* and never touches the original
notification's text or its inline keyboard. The Feature 3 Favorite/Applied/Dismiss/Add-note/Open
buttons therefore survive intact and remain tappable after asking "Why?".

### Breakdown message format (`build_score_breakdown_message`, Arabic-first)

A new pure builder in `notify/format.py`, mirroring the other HTML builders (no I/O, no clock). It
lists each component's **Arabic label · contribution in points**, the **total**, and the **project
title**:

```
🎯 تقييم الفرصة: 82 / 100
<b>{project title}</b>

• معدل التوظيف: 28.5 نقطة
• حجم التوظيف: 9.2 نقطة
• الميزانية: 11.0 نقطة
• المنافسة: 14.8 نقطة
• الحداثة: 6.5 نقطة
• تقييم العميل: 2.0 نقطة
```

- The header line is the **total** (`breakdown.score`, rounded) out of 100; the bold line is the
  HTML-escaped `project.title` so the owner sees *which* project this explains.
- One bullet per `ScoreComponent`, in the fixed model order (hiring rate, hire volume, budget,
  competition, freshness, rating). The Arabic `label` is server-provided on each component (the same
  labels the settings/detail bars use, minus the "وزن" prefix); the number is `component.contribution`
  (points out of 100, the `100 × weight × sub_score` term) rounded to **1 decimal** and suffixed
  `نقطة` ("points"). The contributions sum (within rounding) to the total — that visible accounting is
  the explainability FR-007/FR-031 require.
- Every interpolated value is `html_escape`d; each component is on its **own line** so an RTL Arabic
  label and its LTR number stay stable (same rationale as the notification body). `parse_mode=HTML`.

---

## 3. `/top [n]` command (FR-032)

### Registration (`bot/app.py`)

One more handler beside the existing five commands:

```python
application.add_handler(CommandHandler("top", commands.top_command))
```

### Behavior (`bot/commands.py::top_command`)

- **Owner-gated** (`is_owner`) like every command; returns silently otherwise.
- **Parse `n`** from `context.args[0]`:
  - omitted → default `SettingsStore(session).get_int("top_default_count")` (default **5**).
  - a non-integer token → fall back to the default (never raises; FR-032 "never an error").
  - clamp to a **sane range `1 … 20`** (`max(1, min(n, 20))`) so `/top 9999` cannot ask for an
    unbounded list.
- **Query**: `scoring.service.top_open(session, n)` returns the **qualified + open + actively-tracked**
  projects ordered by `project_scores.score` **descending**, limited to `n`
  (`eval_status==qualified ∧ site_status==open ∧ tracking_active`, `ORDER BY score DESC LIMIT n`).
  Closed/awarded/unknown and non-qualified projects are excluded by construction (FR-011, FR-032).
- **Reply**: one project per entry, rank-numbered, RTL-safe (title on its own line, the LTR
  `score · tier` and the link each clearly separated):

```
🏆 أفضل 3 مشاريع مفتوحة

1. تصميم متجر إلكتروني · 88 · Tier 1
https://mostaql.com/project/abc123
2. تطبيق جوال للحجوزات · 81 · Tier 1
https://mostaql.com/project/def456
3. موقع تعريفي للشركة · 74 · Tier 2
https://mostaql.com/project/ghi789
```

  (Score rounded to integer; tier via the existing `Tier {n}` / `Tier ?` rendering; title falls back
  to `(بدون عنوان)` and the link is omitted when `project.url` is empty, mirroring `/find`.)
- **Fewer than `n` open** → the **available (shorter) list** is returned, no padding, no error.
- **None open** → a friendly message, e.g. `🏆 لا مشاريع مفتوحة حاليًا` ("no open projects right
  now"). Never an error.

`/top` is read-only — it issues no scrape and no write (Constitution VIII).

---

## 4. Idempotency & safety

Every Feature 4 handler is **owner-chat-gated** (`is_owner`) and **reads-only** (no
`personal/service.py` mutation, no settings write, no platform write). Each degrades to a harmless,
friendly result — never an exception, never a dropped spinner.

| Action | Behavior |
|---|---|
| **Re-tap "Why?"** (same or later) | Re-reads `project_scores.breakdown` and replies with the same last-known breakdown each time; the callback is answered (spinner cleared) on every tap; no state changes (read-only), and the original notification + its action buttons are left untouched. (FR-031) |
| **"Why?" on a since-closed project** | Returns the breakdown **frozen at the project's last open re-check** (the loop stopped recomputing once closed). Same render, no error — the close is invisible to this reply. (FR-031, US5 scenario 6) |
| **"Why?" on an old / expired notification** | Resolved by the embedded `project_id`, independent of message age; returns the current stored breakdown. If the project was deleted → `query.answer("المشروع غير موجود")`. If it exists but has no score (non-qualified / not yet scored) → `query.answer()` then `reply_text("لا يوجد تقييم لهذا المشروع بعد")`. No error in any case. |
| **`/top` with a huge `n`** (`/top 9999`) | Clamped to the max (20) before the query; returns at most that many. No error. |
| **`/top` with a non-integer arg** (`/top abc`) | Falls back to the default `top_default_count`; replies with the normal list. No error. (FR-032) |
| **`/top` with 0 open projects** | Friendly `🏆 لا مشاريع مفتوحة حاليًا`; never an empty/error reply. (FR-032, US5 scenario 5) |
| **`/top` with fewer than `n` open** | Returns the available shorter list as-is. (US5 scenario 5) |

## Consistency with the dashboard

`get_breakdown` and `top_open` read the **same** `project_scores` rows (score, breakdown, outcome,
tracking) that the feed, the score column/sort/filter, and the detail breakdown bars read, so the
score, the "Why?" breakdown, and `/top` in Telegram always agree with the dashboard on its next
refresh (FR-031, FR-032; SC-007). No new state and no new settings beyond `top_default_count` (the
`/top` default, registered in settings, range 1–20) are introduced by this Telegram surface.
