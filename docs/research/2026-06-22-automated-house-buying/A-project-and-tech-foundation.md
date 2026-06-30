# A — Project & Technical Foundation

**Date:** 2026-06-22
**Scope:** Internal product/tech due-diligence on the Funda house-hunt project at `/Users/may/Documents/may/house`, written as the foundation for a business-strategy synthesis around an "automated house-buying" vision.
**Method:** Read-only analysis of source, config, state, specs, and `.remember/` handoff history. No apply/submit actions triggered; tracker not run against live Funda.

---

## 1. What the project is today

A single-user, locally-hosted, Obsidian-backed house-hunt automation for the Eindhoven region. It polls Funda for new listings matching per-city criteria, writes one Markdown page per house into an Obsidian vault, tracks each house through a status workflow, syncs broker email back into the pages, pushes booked viewings into Apple Calendar, talks to the user over Telegram, and — as of today — **submits real viewing-request forms on Funda via Playwright**.

Architecturally it is a set of small, single-purpose Python modules glued together by three macOS `launchd` daemons and one Codex-CLI-backed Telegram bot. The Obsidian vault (`houses/*.md`) is the declared single source of truth; everything else is an echo or a writer into it.

Stack (`requirements.txt`): `pyfunda>=3.1.1` (unofficial Funda mobile-API client), `PyYAML`, `deep-translator` (Google free endpoint, NL→EN), `playwright>=1.60`. Codex CLI (`gpt-5.4`) is an external dependency for the Telegram assistant and Gmail sync; the core poll and the auto-applier need no LLM.

Scale signals: `houses/` holds **150 pages**; `state.json` tracks **~145 seen listing ids** with `last_run` `2026-06-22T19:46`. Test suite: **43 tests** across 8 files (notably 16 for `apply_command`).

---

## 2. Module inventory — `funda_tracker/`

| Module | One-line purpose |
|---|---|
| `config.py` | Loads/validates `preferences.yaml`; splits the shared `search` block + per-city `searches:` into `(location, filters)` query pairs, dropping `None` filters so they don't override pyfunda defaults. |
| `fetcher.py` | Talks to Funda via pyfunda: `search_listings` (newest-first, `max_pages`-bounded) and `enrich` (full listing detail, returns `None` on failure rather than raising). |
| `matcher.py` | Local boolean **feature** filters (garden, solar, heat pump, monument, fixer-upper…) applied to listing-detail data the search API can't filter server-side. Returns `(passes, reason)`. |
| `state.py` | De-dup ledger. `State` loads/saves `state.json` (`seen` id set + `last_run`); `is_seen`/`mark_seen`. A listing is "seen" once a page is made or it fails filters — never reconsidered. |
| `translate.py` | Best-effort NL→EN via `deep_translator.GoogleTranslator`; returns original Dutch on any failure so translation never breaks page creation. |
| `notegen.py` | **Append-only** Obsidian page generator. Builds frontmatter + body (photo, facts table, features, translated description, Notes + Process log sections). `write_note` refuses to overwrite an existing page. |
| `telegram_notify.py` | Outbound, read-only Telegram echoes of vault changes (`format_new_pages`, `format_failure`); `send` + `send_throttled` (per-key min-gap stamp files). Never raises; no-op if `secrets.yaml` missing. |
| `telegram_bot.py` | Inbound long-poll bot. Single-user (only configured `chat_id`). Dispatches `apply to …` to the deterministic applier, everything else to a Codex CLI session (1 h thread TTL, crash-safe offset checkpoint). |
| `agenda_notify.py` | Builds a short "house agenda" (upcoming viewings + action items parsed out of process logs) and pushes missing calendar events; throttled; called at the end of every poll. |
| `calendar_push.py` | Pushes a `📅 Viewing booked` house into Apple Calendar via `osascript`/AppleScript. Idempotent via a `[house-tracker:<funda_id>]` marker; falls back to writing an `.ics` if Calendar automation is unavailable. |
| `apply_command.py` | Pure, browser-free orchestration of the auto-applier: `parse_apply` (Telegram text → intent), `resolve_house` (address → tracked note via frontmatter), `handle_apply` (parse→resolve→submit→mark note), `mark_viewing_requested` (flip status + log line). 16 unit tests. |
| `applier.py` | **Today's centerpiece.** Deterministic Playwright submitter of the Funda viewing-request form using a persistent logged-in Chrome profile. See §4. |

Entry point `run.py` orchestrates the poll: load config → per-city search (dedup by id) → diff vs `state.json` → enrich → local-filter → `write_note` → mark seen → Telegram echo of new pages → `send_agenda`. It only ever creates pages; a `--dry-run` path reports without writing.

### launchd / external pieces (repo root)
- `com.may.funda.plist` — schedules the Funda poll (~every 20 min; Mac must be awake).
- `com.may.funda-gmail.plist` — schedules `gmail-sync.sh` (hourly + on wake).
- `com.may.funda-bot.plist` — runs the Telegram bot listener daemon.
- `gmail-sync.sh` — throttled (≤1 real sync/h) headless launcher for the Codex Gmail prompt.
- `.codex/prompts/gmail-sync.md` — the Codex prompt that reads Gmail (read-only connector) and advances `status`/`viewing_at` in house pages, using each page's `## Process log` as the dedup source of truth. Hard rules: never touch `## Notes`, status only moves forward, `❌ Rejected` only from New/Requested.

---

## 3. The data model & status workflow (the spine everything writes to)

Each `houses/<funda_id>-<slug>.md` page carries frontmatter: `funda_id, address, city, price, m2, rooms, bedrooms, energy_label, url, status, declined, added, requested, viewing_at, listed_date, enriched`, plus `tags: [house]`. Body: photo, facts table, features, broker, translated description, `## Notes` (user-owned, off-limits to automation), `## Process log` (dated event lines, the dedup ledger for Gmail sync and calendar push).

Status workflow: `🆕 New → 📨 Viewing requested → 📅 Viewing booked → 🏠 Viewed → 🎯 Offer made`, terminal `❌ Rejected`. A separate `declined: true` checkbox is a manual reject. `Houses Board.md` (Dataview) groups by stage and filters declined out.

This Markdown-as-database model is the integration bus: the poll writes it, the applier flips it, Gmail sync advances it, calendar push and agenda read it. Cheap and human-auditable, but it is the main scaling constraint (see §6).

---

## 4. TODAY'S KEY ITERATION — the Playwright Funda auto-applier (the technical moat)

Implemented and **verified live today**: first real submit was *Tinelstraat 186, Eindhoven → Kranen Makelaardij, 2026-06-22* (spec `docs/superpowers/specs/2026-06-22-funda-viewing-applier-design.md`). Code in `funda_tracker/applier.py` (+ `apply_command.py` orchestration). This is the piece that turns the project from a *tracker* into an *actor* — it submits real, irreversible viewing requests to brokers.

### 4.1 The "real infrastructure" breakthrough

The conceptual leap, captured in the spec's Architecture section, is that **the form is fully mapped, so submission is plain deterministic Python — no LLM drives the browser.** Earlier framing assumed a Sonnet/agent would click through the form; the breakthrough was discovering that once the form's selectors and answer policy are known, the whole apply path is a regex-parse + a scripted Playwright sequence. Consequences:

- **Reliable and free** — no per-apply model cost, no nondeterministic clicking.
- **Model-agnostic** — runs under any model (or none); the Telegram bot calls `apply_command.handle_apply` *before* any Codex dispatch.
- It is **real outbound infrastructure**: a logged-in browser session that submits genuine forms to real brokers — not a simulation or a draft. That is the moat: a working, authenticated, anti-bot-beating write path into Funda.

### 4.2 DataDome anti-bot bypass (the hard-won part)

Funda sits behind **DataDome**. Findings, verified live today (`applier.py` lines 47–51; spec "Anti-bot"):

- **Bundled Playwright Chromium gets challenged** ("Je bent bijna op de pagina die je zoekt"). The fix is a three-part combination:
  1. Launch **real Google Chrome**, not bundled Chromium: `pw.chromium.launch_persistent_context(..., channel="chrome", ...)`.
  2. `--disable-blink-features=AutomationControlled` launch arg (`_LAUNCH_ARGS`).
  3. A `navigator.webdriver` stealth patch injected as an init script (`_STEALTH_JS = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"`).
- **The one-time manual login also clears DataDome once, and that clearance cookie persists in the on-disk profile**, so subsequent automated runs start already cleared. This is the key durability trick — the anti-bot clearance is amortized across all future runs.
- **Direct `goto` of the contact URL is aborted** by Funda (`ERR_ABORTED`). Instead the applier navigates the detail page and **clicks the "Vraag bezichtiging aan" anchor** (`a[href*="makelaar-contact"][href*="viewingRequest"]`) — an SPA navigation that carries the proper referer (`_open_viewing_form`, lines 109–127). It also avoids needing to guess the listing's internal id (the `internalId` in the contact URL differs from the detail id and is only exposed via that anchor).
- Volume is kept low and user-triggered (one apply per Telegram command), which keeps the footprint under DataDome's radar.

### 4.3 Login & session persistence

- `login()` (lines 256–286) opens a **headed** Chrome window pointed at `https://www.funda.nl/mijn/` and **never types credentials** — the user logs in by hand. It auto-detects completion by polling whether the account page stops bouncing to `login.funda.nl` (`_logged_in`, line 96–98), re-confirms, then saves the session.
- **Login persists primarily via the persistent-profile cookies** on disk at `logs/funda-profile/` (`PROFILE_DIR`). The spec records this was empirically confirmed (a fresh relaunch stayed logged in and autofilled identity) — contrary to the initial fear that sessionStorage was load-bearing.
- **Belt-and-suspenders:** Funda's `oidc-client` keeps an auth token in **sessionStorage**, which Chrome never writes to disk. `_save_session` snapshots all of sessionStorage to `logs/funda-session.json` (lines 88–93); `_launch` restores it via an init script that re-populates sessionStorage on any `funda.nl` page (lines 72–84). Validated JSON only; restore is best-effort.
- Both the profile dir and session file are gitignored.

### 4.4 Form filling (selectors & answer policy)

`apply_viewing` (lines 199–253) drives the form deterministically:

1. `goto(detail_url)` → `_accept_cookies` (Didomi wall, "Alles accepteren", best-effort).
2. `_open_viewing_form` clicks the bezichtiging anchor, waits for `#questionInput`.
3. `_fill_form` (lines 175–196):
   - `_tick_all_availability` — ticks every availability checkbox (intent + all days `Ma–Za`, no Sunday; dayparts `'s morgens`/`'s middags`, no evening). These are custom-styled inputs overlaid by a label, so it **clicks the `<label for=...>`, not the input**, and is idempotent (`is_checked` guard).
   - Fills the message textbox `#questionInput`.
   - **Identity gate:** reads `#emailAddress`; if empty, returns an error ("not logged in? run `applier --login`") and aborts *before* submitting. Identity (email/first/last/phone) autofills from the logged-in account.
   - **Address is NOT on the account**, so it is typed locally: postcode `5627HT` (spaceless — field is `maxlength=6`) and house number `84` (constants lines 43–45). The masked Vue inputs silently reject `fill()` and drop the first keystroke, so `_type_verify` (lines 144–160) runs a **clear → type key-by-key (delay 80ms) → verify → retry ×3** loop — the only thing that sticks.
   - **Radio policy** (constant per-application answers, lines 37–40): "Overweeg je je huidige huis te verkopen?" → **Nee** (`#radioOption-sellNo`); "financieel adviesgesprek gehad?" → **Ja** (`#radioOption-mortgageYes`); "Wanneer wil je verhuizen?" → **Zo snel mogelijk** (`#radioOption-timeframeAsap`); ING hypotheekadvies → **opt-out** (`#mortgageAdviceRadioOptionOptOut`). `_set_radio` clicks + verifies `aria-checked="true"` with one retry.
4. `_save_session` refreshes the oidc snapshot, screenshots, and (unless `--no-submit`) clicks **"Verstuur"**.

### 4.5 Success detection

Funda's SPA **never reaches `networkidle`** (analytics keep polling), so success can't be detected by load state. Instead (lines 237–251): wait for `#questionInput` to **detach** (form replaced by a confirmation panel) → success; else fall back to matching thank-you text (`re.compile(r"bedankt|verzonden|verstuurd|aanvraag is|ontvangen", re.I)`). A `…-done.png` full-page screenshot is always saved. Server-side, the analytics event `Contact Request Submitted` confirms the request landed.

On success, `apply_command.mark_viewing_requested` flips the note: `status: "📨 Viewing requested"`, `requested: <today>`, and prepends a process-log line `- <date> — viewing requested via Funda (auto-apply)`.

### 4.6 Safety properties
- Identity gate aborts before submit if not logged in.
- `--no-submit` fills everything and stops for human review.
- Address resolution is exact/substring match against tracked notes; **multiple matches → applies to none** and asks the user to disambiguate.
- v1 explicitly out of scope: applying to houses not in the tracker, fully headless operation, multi-applicant.

---

## 5. Full automation surface — automated vs manual

### Automated end-to-end
- **Polling/search** — `launchd` (~20 min) runs `run.py`; per-city independent queries via `searches:` so a busy city can't crowd a quiet one out of the newest-N window.
- **Per-city price caps** — Tilburg/Best/Boxtel ≤ €350k, Eindhoven ≤ €450k, houses only, `buy` (`preferences.yaml`); each merged over a shared `search` block.
- **Dedup** — `state.json` id ledger; pages never regenerated, notes never lost.
- **Page generation** — append-only Obsidian pages with translated descriptions, photos, facts, features.
- **Notifications** — Telegram echo of every new page + throttled failure alerts; throttled "house agenda" (upcoming viewings + parsed action items) at end of each poll.
- **Apple Calendar sync** — booked viewings auto-land in calendar "Домашній", idempotent, with `.ics` fallback.
- **Auto-applier** — `apply to <address>[: msg]` from Telegram submits a real Funda viewing request and flips the note. **Fully working today.**

### Semi-automated (LLM/agent in the loop)
- **Gmail → vault sync** — Codex prompt advances `status`/`viewing_at` from Dutch broker email, gated by process-log dedup and forward-only rules. Read-only Gmail connector. Caveat: the README notes Gmail access can be unavailable in headless `codex exec`, which the wrapper treats as a failed sync.
- **Telegram conversational assistant** — free-form messages spawn a Codex session with the house-tracker system prompt (workspace-write), 1 h thread memory.

### Still manual
- Funda **login** (one-time, by hand — by design, no credential typing).
- Deciding **which** house to apply to and the message (user triggers each apply; this project's own copilot role is to recommend, not decide).
- **Viewing attendance** and post-viewing judgment (the `.remember/` archive shows the user physically visited Merelstraat 6, Breukelsestraat 140, Bellinistraat 191).
- **Offers/bidding, negotiation, financing, notary/conveyancing** — entirely outside the system.
- **Cross-platform coverage** — Funda only; no Pararius, Jaap, broker sites, or new-build portals.

---

## 6. Foundation assessment for a "Tinder for houses" / fully-automated NL house-buying vision

### Reusable building blocks that already exist
1. **A working authenticated write path into Funda past DataDome.** This is the rare, defensible asset — most competitors can read listings; submitting authenticated forms through DataDome with a persistent cleared profile is the hard part, and it's done and live.
2. **Deterministic, mapped form automation** — the "no LLM drives the browser" pattern (regex-parse → scripted Playwright with verify-retry loops on masked Vue inputs) is a reusable template for any portal/broker form. The masked-input `_type_verify`, label-click, and `aria-checked`-verify patterns are portable.
3. **Listing ingestion + normalization** — pyfunda search/enrich, per-city query splitting, NL→EN translation, feature extraction, dedup ledger.
4. **A status/workflow engine + audit log** — the status state machine, process-log dedup, forward-only rules, declined handling. This is essentially a lightweight CRM for property pursuit.
5. **Multi-channel I/O** — Telegram bot (single-user auth, session memory, direct-command vs LLM dispatch), Gmail read-sync, Apple Calendar write. A user-facing "swipe" surface (Tinder UX) could sit directly on the existing Telegram command layer.
6. **Scheduling/orchestration** — `launchd` daemons, throttling, never-raise notification contract, screenshots-as-evidence on every apply.
7. **A test culture** — 43 tests, pure orchestration layer (`apply_command`) deliberately separated from the browser so it's unit-testable.

### Hardest technical gaps remaining
1. **Anti-bot durability & scale.** The DataDome bypass is verified at *one user, low volume, headed, one manual login.* A multi-tenant product means many concurrent authenticated sessions, headless operation, profile/cookie rotation, and surviving DataDome model updates — a continuous adversarial maintenance burden, and the single biggest risk. The spec itself lists "fully headless" as out of scope.
2. **Multi-platform breadth.** Everything is Funda-specific (pyfunda API + one mapped form). Pararius, Jaap, makelaar sites, and new-build portals each need their own ingestion + their own anti-bot + their own mapped form. There's no abstraction layer yet for "a portal" or "a contact form."
3. **Form-mapping brittleness.** The applier hardcodes Dutch selectors and a fixed answer policy. Funda redesigns break it silently; other brokers' forms differ entirely. Self-healing or LLM-assisted re-mapping (used only when deterministic selectors fail) is unbuilt.
4. **Per-applicant identity/profile management.** Identity is single-user constants (`5627HT`/`84`, Anton's account). Multi-user needs secure credential vaulting, per-user Funda login automation (currently manual by design), and per-user answer policies (mortgage status, timeframe, selling — currently hardcoded).
5. **Data model scale.** 150 flat Markdown files with regex frontmatter edits and glob scans is fine for one user; a real product needs a proper datastore, concurrency-safe writes, and the Obsidian dependency removed.
6. **The ML claim is aspirational.** There is **zero ML** today — matching is rule-based (price/city/feature booleans). A "Tinder for houses" implies learned preference modeling from swipes, ranking, and dedup across platforms; none of the ingestion currently produces training signal beyond binary `declined`. The swipe UX and the preference-learning loop are greenfield.
7. **Downstream of the viewing request is empty.** Bidding/offer submission, financing, valuation, and conveyancing — the actual "buying" — are unautomated and far more legally/financially sensitive (and irreversible) than a viewing request. The auto-applier proves the *write-path pattern*; extending it to offers raises real liability and trust requirements.

### Bottom line
The project has already crossed the hardest *conceptual* line for this space: it is a real, authenticated, anti-bot-beating actor that submits genuine forms on the dominant NL portal, with a clean separation between deterministic automation and the LLM layer, plus a working workflow/CRM spine and multi-channel I/O. That auto-applier and its DataDome-cleared persistent profile are the moat. The gap from here to "Tinder for houses across platforms with ML" is mostly *breadth and multi-tenancy* (more portals, headless-at-scale anti-bot, per-user identity, a real datastore, and an actual preference-learning model) rather than a missing core capability — but each of those is substantial, and the anti-bot maintenance treadmill is the standing risk that never goes away.
