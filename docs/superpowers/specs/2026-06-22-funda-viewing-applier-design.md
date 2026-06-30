# Funda Viewing-Request Auto-Applier — Design

**Date:** 2026-06-22
**Status:** IMPLEMENTED & verified live (first real submit: Tinelstraat 186, Eindhoven → Kranen Makelaardij, 2026-06-22).

## Implementation notes (verified)

- Login persists via the **persistent profile cookies** (not sessionStorage as first
  feared) — confirmed by a fresh relaunch staying logged in and autofilling identity.
  The one-time `--login` auto-detects completion (account page stops bouncing to
  login.funda.nl) and saves a sessionStorage snapshot as belt-and-suspenders.
- Identity (email/first/last/phone) autofills from the account; **address does NOT**
  → we type postcode/huisnummer ourselves.
- Postcode field is `maxlength=6` and a masked Vue input that silently rejects
  `fill()` and drops the first keystroke → use a clear-type-verify-retry loop, and
  the value must be spaceless (`5627HT`).
- Radios are `role=radio` buttons (`#radioOption-*`, `#mortgageAdvice*`); set by
  click + aria-checked verify + retry.
- Submit success: Funda's SPA never reaches `networkidle`; detect by the message
  field detaching (form → confirmation panel) or a thank-you text. Analytics event
  `Contact Request Submitted` confirms server-side.

## Goal

From Telegram, the user sends `apply to {address}` (optionally with custom text).
The system submits a *Plan een bezichtiging* (viewing request) on Funda for the
matching tracked house, using the user's logged-in Funda account for identity,
then records it in the house's Obsidian page.

## Anti-bot (verified live, 2026-06-22)

- Bundled Playwright Chromium **gets the DataDome challenge** ("Je bent bijna op
  de pagina die je zoekt"). Fix: launch with **real Google Chrome**
  (`channel="chrome"`) + `--disable-blink-features=AutomationControlled` + a
  `navigator.webdriver` patch. That combination loads the real listing.
- The **manual login** also clears DataDome once; the clearance cookie persists in
  the profile, so later automated runs stay clean.
- Direct `goto` of the contact URL is aborted by Funda (ERR_ABORTED); **click the
  "Vraag bezichtiging aan" anchor** instead (SPA nav with referer).
- Logged-in detection = the form **autofills the email**; if `#emailAddress` is
  empty after load, treat as not-logged-in and abort before submitting.

## Research findings (verified live, 2026-06-22)

- Once past DataDome, listing + contact pages render fully; **no captcha, no login
  required by the form itself** (login only needed to autofill identity).
- Viewing-request form URL: `/makelaar-contact/?listingId={internalId}&viewingRequest=true`.
  The `internalId` (e.g. 8053820) differs from the detail id (44408283) and is
  exposed on the detail page as the "Vraag bezichtiging aan" link → so the applier
  navigates the detail page and clicks that link rather than guessing the id.
- Form fields (Dutch):
  - "Ik wil een bezichtiging aanvragen voor dit huis" — checkbox, checked by default.
  - Days: `Ma Di Wo Do Vr Za` checkboxes (**no Sunday**).
  - Daypart: `'s morgens`, `'s middags` (**no evening**).
  - Message: "Wil je iets kwijt aan de makelaar?" textbox.
  - Identity: E-mailadres, Voornaam, Achternaam, Telefoonnummer, Postcode,
    Huisnummer, Toevoeging — **auto-filled when logged in**.
  - "Overweeg je je huidige huis te verkopen?" → **Nee**.
  - "Heb je al een financieel adviesgesprek gehad?" → **Ja**.
  - "Wanneer wil je verhuizen?" → **Zo snel mogelijk**.
  - ING hypotheekadvies → opt-out (default).
  - Submit: "Verstuur".
- The day/daypart controls are custom button-toggles: the real `<input>` is
  overlaid, so clicks must target the **label**, not the input.

## Architecture

Deterministic Python Playwright — **no LLM drives the browser**. The form is
mapped, so submission is plain code: reliable and free. A model is not required
anywhere in the apply path (regex parse + script), so it runs fine under Sonnet
or any model.

### Components

1. **`funda_tracker/applier.py`** — browser automation.
   - Persistent browser profile at a gitignored `PROFILE_DIR`
     (`launch_persistent_context(user_data_dir=PROFILE_DIR, headless=False)`).
   - `--login` CLI mode: opens a headed window, user logs into Funda once,
     cookies persist on disk for all future runs.
   - `apply_viewing(detail_url, message) -> ApplyResult`:
     1. open `detail_url`, accept cookie wall if present.
     2. verify logged in (nav not showing "Inloggen"); else
        `ApplyResult(ok=False, error="not logged in — run --login")`.
     3. click "Vraag bezichtiging aan" → contact form.
     4. ensure "Ik wil een bezichtiging" checkbox checked.
     5. tick **all** day labels and **all** daypart labels present (dynamic).
     6. fill message textbox.
     7. verify identity fields (email, voornaam, telefoon) are non-empty
        (auto-filled by account); else abort without submitting.
     8. radios: advies=Ja, verkopen=Nee, verhuizen=Zo snel mogelijk; ING opt-out.
     9. click "Verstuur"; wait for success confirmation; screenshot.
     10. return `ApplyResult(ok, screenshot_path, error)`.
   - Success-confirmation text/URL to be captured empirically on first real submit.

2. **`funda_tracker/apply_command.py`** — orchestration (no browser, unit-testable).
   - `parse_apply(text) -> (address, message|None)`:
     matches `apply to {address}` and `apply to {address}: {custom text}`.
   - `resolve_house(address, houses_dir) -> Note | Ambiguous | NotFound`:
     matches `houses/*.md` front-matter `address` (+ `city`). Every applyable
     house is already in the tracker, so no Funda-search fallback is needed.
   - `default_message()` → `"I really like this house, let me know when it is
     possible to view it!"` (used when no custom text given).
   - `handle_apply(text) -> reply_str`: parse → resolve → call
     `applier.apply_viewing` → on success update the note → return Telegram reply.

3. **Note update on success** — set front-matter `status: "📨 Viewing requested"`,
   `requested: <today>`, and append a `## Process log` line
   `- {date} — viewing requested via Funda (auto-apply)`.

4. **Telegram wiring** — in `telegram_bot.py`, before the Codex/LLM dispatch:
   if the message matches the apply pattern, call `apply_command.handle_apply`
   directly and reply (with screenshot). Otherwise fall through to existing flow.

### Config / files

- `PROFILE_DIR` (e.g. `logs/funda-profile/`) — gitignored.
- Screenshots saved under `logs/` — gitignored.
- `.gitignore` updated for the profile dir and `.playwright-mcp/`.

## Error handling

- Not logged in → reply asks user to run `--login` (or a one-time setup).
- Address not found / ambiguous → reply lists candidates, applies to none.
- Identity fields blank after load → abort, reply (session likely logged out).
- Submission failure / no success confirmation → screenshot + reply error; retry once.
- Anti-bot: headed persistent logged-in profile, user-triggered low volume.

## Testing

- Unit (no browser): `parse_apply`, `resolve_house`, `default_message`,
  note-update logic — against fixtures.
- Integration: `apply_viewing` against the live form, gated behind an env flag;
  first real run is the user-confirmed submit that also captures success text.

## Out of scope (v1)

- Applying to houses not in the tracker.
- Fully headless operation.
- Multi-account / multiple applicants.
