# Gmail sync — Funda house tracker

You are running under Codex CLI, not Claude Code. Use Codex tools and the configured [Gmail](app://connector_2128aebfecb84f64a069897515042a44) connector/plugin if available. If Gmail access is unavailable, report that clearly and make no house-page edits.

Sync the user's Gmail into their local Funda house-tracker pages: update each house's
`status` and `## Process log` from broker / Funda emails. This runs both unattended
(via launchd, soon after the laptop is opened) and on demand. The user does not read
Dutch — emails are in Dutch.

**Working directory:** `/Users/may/Documents/may/house` (paths below are relative to it).

**Dry-run mode:** if the launcher says `DRY_RUN=1` or the prompt includes `dry-run`, perform every search and read step but make **no changes** — do not edit any file. Instead print exactly what you *would* have done.

## The tracker

House pages live in `houses/*.md`. Each has YAML frontmatter including
`funda_id`, `address`, `city`, `status`, `requested`, `viewing_at`, `listed_date`.
Body sections, in order: a description quote, `## Notes` (the user's private notes),
`## Process log` (dated event lines like `- 2026-05-19 — viewing requested via Funda`).

**Status values, in forward order:**

1. `🆕 New`
2. `📨 Viewing requested`
3. `📅 Viewing booked`
4. `🏠 Viewed`
5. `🎯 Offer made`

Plus the terminal `❌ Rejected`.

## Hard rules — do not break these

- **NEVER edit the `## Notes` section** of any page. It belongs to the user. Off limits.
- **Status only ever moves forward** (New → Requested → Booked → Viewed → Offer).
  Never move it backward. `❌ Rejected` may be set **only** from `🆕 New` or
  `📨 Viewing requested` — never from `📅 Viewing booked` or any later stage.
- When you are not sure which house an email is about, or how to classify it:
  **do not guess and do not change anything** — report it under "Needs your attention".
- The only frontmatter fields you may change are `status:`, `requested:`, and
  `viewing_at:`. Fill `requested:` only when it is empty *and* you are setting
  `📨 Viewing requested`. Fill or update `viewing_at:` only when an email gives
  one concrete confirmed viewing date and time; write it as local ISO
  `YYYY-MM-DDTHH:MM`. Do not set `viewing_at:` for multiple proposed slots or an
  invitation link without a confirmed appointment.

## Deduplication — how to avoid re-doing work

The Gmail connector is **read-only** (no labels can be applied). The `## Process log`
of each house page is therefore the **single source of truth** for what has already
been synced. Before acting on any email, check the matched house's process log: if a
line already records that same event — whether from a previous run or written by the
user by hand — **skip it**. This makes the command safe to run any number of times.

## Steps

### 1. Load the houses

List `houses/*.md`. Read each page's frontmatter. Build a table of
`funda_id, address, city, status, requested, filepath`.

### 2. Find candidate emails

Search Gmail for mail about the tracked houses from roughly the last 30 days. Use the Codex Gmail connector/search capability. Run several Gmail queries and merge the results:

- `from:funda.nl newer_than:30d`
- For each house whose status is past `🆕 New`, search its street name:
  `newer_than:30d "<street name>"` — the street name is the `address` without the
  house number, e.g. `Generaal de Wetstraat`.

Use judgment: the goal is to catch every Funda or broker email about a tracked
house. Ignore clearly unrelated mail.

### 3. Process each candidate thread

For each candidate result/thread, read the relevant thread/messages. For each message:

**a. Match it to a house** by the street address in the subject or body.
No confident match → skip the message and report it under "Needs your attention".

**b. Classify it** and decide the action:

| Email is… | Recognise by (Dutch) | Action |
|---|---|---|
| A Funda viewing-request confirmation | from Funda; `bevestiging`, `we hebben je reactie ontvangen`, `je reactie op` | If the house is `🆕 New` → set `📨 Viewing requested`; if `requested:` is empty, set it to the email's date (`YYYY-MM-DD`). If already at/past `📨 Viewing requested` → no status change. |
| A viewing being scheduled / confirmed | broker confirms one concrete date **and** time to visit | If status is `🆕 New` or `📨 Viewing requested` → set `📅 Viewing booked` and set `viewing_at:` to `YYYY-MM-DDTHH:MM`. If status is already `📅 Viewing booked` and the email changes the appointment time, update `viewing_at:`. Note the confirmed date/time in the log line. |
| Proposed slots / booking invitation | broker offers multiple slots, asks you to choose, or sends a link to book an appointment | Log the proposal/invitation only. Do **not** set `📅 Viewing booked` and do **not** set `viewing_at:` until a single appointment is confirmed. |
| A rejection / no availability | `helaas`, `niet meer mogelijk`, `volgeboekt`, `vol`, `reservelijst`, `afgewezen`, no viewing possible, house sold | If status is `🆕 New` or `📨 Viewing requested` → set `❌ Rejected`. If status is `📅 Viewing booked` or later → do **not** change it; report it instead. |
| Anything else | a question, extra info, generic newsletter | No status change. If it concerns a tracked house, still log it. Report it. |

**c. Update the page** (skip every write in dry-run):

- **First, read the matched house's `## Process log`.** If a line already records
  this same event, this email is already synced — make no change and move on.
- Otherwise, if a status transition applies *and* is allowed by the forward-only
  rule, replace the `status:` line in the frontmatter. Change nothing else in the
  frontmatter except `requested:` and `viewing_at:` per the rules above.
- Append exactly **one** line to the `## Process log` section:
  `- YYYY-MM-DD — <one-line English summary of the email>`, dated with the email's
  date. Translate the gist to English — the user does not read Dutch.
- Never touch `## Notes` or any other section.

**d. If the new status is `📅 Viewing booked`** *and* this is a real run (not dry-run):
also push the viewing into Apple Calendar by running:

```sh
.venv/bin/python3 -m funda_tracker.calendar_push houses/<id>-<slug>.md
```

The helper is idempotent — it tags the calendar event with a `[house-tracker:<funda_id>]`
marker, so re-running the sync never creates duplicates. Skip on dry-run.

### 4. Report

Print a summary:

- **Updated** — each house changed, as `old status → new status`, and why.
- **Logged only** — emails logged with no status change.
- **Needs your attention** — unmatched emails, ambiguous ones, rejections that
  arrived after a viewing was already booked — anything you did not act on.
- If nothing relevant was found, say so in one line.

In dry-run, prefix the whole report with `DRY RUN — no changes were made`.

### 5. Write the Telegram echo

If this run changed the vault — any house whose `status` you changed, or any page
you appended a process-log line to — write a short echo of
those changes to `logs/gmail-sync-message.txt`. The wrapper `gmail-sync.sh` sends
this file to the user on Telegram. The message is a mirror of what you wrote to the
vault — never more than that.

Format — a header line, a blank line, then one line per page you touched. Each line
is the address and the change you made to that page:

```
📬 House updates

📅 Coba Pulskenslaan 9 — 📨 Viewing requested → 📅 Viewing booked
❌ Generaal de Wetstraat 35 — 📨 Viewing requested → ❌ Rejected (slots full)
⚠️ Boekweitstraat 19 — broker asked a question, no status change
```

Lead each line with the new status emoji (📅 / ❌ / 🆕). Use ⚠️ for a page where you
appended a process-log line but did **not** change its status (e.g. a broker question
you logged). Include a line **only for a page you actually edited** — an email you
merely flagged under "Needs your attention" without editing any page does not belong
in this file. Keep each line to one short sentence in English. Plain text only — no
Markdown. If this run edited no page, do not create the file at all — the wrapper
sends nothing when the file is absent.

In dry-run, do not write the file; instead print what it would contain.

## Final response requirements

End with a concise report only. Do not include chain-of-thought. If Gmail connector access is missing, say: `Gmail access unavailable in Codex exec; no changes made.` and include any setup hint Codex provided.
