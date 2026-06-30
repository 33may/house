"""Submit a Funda viewing request via Playwright, using a persistent logged-in profile.

The form is fully mapped (see docs/superpowers/specs/2026-06-22-funda-viewing-applier-design.md),
so submission is deterministic code — no LLM drives the browser.

One-time setup (log into Funda once; the profile persists on disk):
    python -m funda_tracker.applier --login

Apply (fills everything; --no-submit stops before the final click for review):
    python -m funda_tracker.applier --url <funda_detail_url> [--message "..."] [--no-submit]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

from funda_tracker.apply_command import DEFAULT_MESSAGE

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "logs" / "funda-profile"
SHOTS_DIR = ROOT / "logs" / "apply-shots"
SESSION_FILE = ROOT / "logs" / "funda-session.json"  # sessionStorage snapshot (oidc token)

# Per-application radio answers (constant policy).
RADIO_SELLING_NO = "#radioOption-sellNo"
RADIO_ADVICE_YES = "#radioOption-mortgageYes"
RADIO_MOVE_ASAP = "#radioOption-timeframeAsap"
RADIO_ING_OPT_OUT = "#mortgageAdviceRadioOptionOptOut"

# Address isn't stored on the Funda account, so we always fill it.
# Postcode field is maxlength=6 → no space.
APPLICANT_POSTCODE = "5627HT"
APPLICANT_HOUSENUMBER = "84"

# Funda is behind DataDome. Bundled Chromium gets challenged; real Chrome with the
# automation flag disabled passes. The manual login also clears DataDome once and
# that clearance persists in the profile.
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_STEALTH_JS = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"


@dataclass
class ApplyResult:
    ok: bool
    screenshot: str | None = None
    error: str | None = None


def _launch(pw, headless: bool):
    """Persistent, logged-in-capable Chrome context tuned to pass DataDome.

    Also restores the sessionStorage snapshot (Funda's oidc-client keeps the auth
    token in sessionStorage, which Chrome never writes to disk) so a relaunched
    browser starts logged in.
    """
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=headless, channel="chrome", locale="nl-NL",
        viewport={"width": 1280, "height": 1000}, args=_LAUNCH_ARGS,
    )
    ctx.add_init_script(_STEALTH_JS)
    if SESSION_FILE.exists():
        import json
        data = SESSION_FILE.read_text(encoding="utf-8")
        try:
            json.loads(data)  # validate
            ctx.add_init_script(
                "(() => { try { const d = " + data + ";"
                " if (location.hostname.endsWith('funda.nl'))"
                " for (const [k, v] of Object.entries(d)) sessionStorage.setItem(k, v);"
                " } catch (e) {} })()"
            )
        except ValueError:
            pass
    return ctx


def _save_session(page) -> None:
    """Snapshot the funda sessionStorage (oidc token) to disk for later restore."""
    import json
    data = page.evaluate("() => { const o = {}; for (let i=0;i<sessionStorage.length;i++)"
                         "{ const k = sessionStorage.key(i); o[k] = sessionStorage.getItem(k); } return o; }")
    SESSION_FILE.write_text(json.dumps(data), encoding="utf-8")


def _logged_in(page) -> bool:
    """Logged in ⇒ the account area doesn't bounce to login.funda.nl."""
    return "login.funda.nl" not in page.url


def _accept_cookies(page) -> None:
    """Dismiss the Didomi cookie wall if it shows (persistent profiles remember it)."""
    try:
        page.get_by_role("button", name="Alles accepteren").click(timeout=4000)
    except PWTimeout:
        pass


def _open_viewing_form(page) -> bool:
    """Click the 'Vraag bezichtiging aan' link and wait for the form to render.

    Clicking the anchor (SPA navigation with proper referer) is more reliable than
    a fresh goto, which Funda aborts (ERR_ABORTED). Returns True on success.
    """
    link = page.locator('a[href*="makelaar-contact"][href*="viewingRequest"]').first
    try:
        link.wait_for(timeout=15000)
    except PWTimeout:
        return False
    link.scroll_into_view_if_needed()
    link.click()
    try:
        page.wait_for_selector("#questionInput", timeout=15000)
    except PWTimeout:
        return False
    return True


def _tick_all_availability(page) -> None:
    """Check every availability checkbox (intent + all days + all dayparts).

    These are custom-styled: the real <input> is overlaid, so we click the <label>.
    Guarded by is_checked() so it's idempotent (never toggles one off)."""
    boxes = page.locator('input[type="checkbox"]')
    for i in range(boxes.count()):
        box = boxes.nth(i)
        if box.is_checked():
            continue
        cid = box.get_attribute("id")
        if cid:
            page.locator(f'label[for="{cid}"]').click()


def _type_verify(page, selector: str, text: str) -> bool:
    """Type into a masked Vue input that drops `fill()`/programmatic values.

    Clears, types key-by-key, and re-checks; retries a few times. The address
    fields silently reject `fill()` and the first keystroke on focus, so this
    clear-type-verify loop is the only thing that sticks."""
    el = page.locator(selector)
    for _ in range(3):
        el.click()
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(120)
        el.type(text, delay=80)
        page.wait_for_timeout(250)
        if page.input_value(selector) == text:
            return True
    return page.input_value(selector) == text


def _set_radio(page, selector: str) -> bool:
    """Select a role=radio button and confirm it took; retry once. Returns success."""
    el = page.locator(selector)
    el.scroll_into_view_if_needed()
    for _ in range(2):
        if el.get_attribute("aria-checked") == "true":
            return True
        el.click()
        page.wait_for_timeout(300)
    return el.get_attribute("aria-checked") == "true"


def _fill_form(page, message: str) -> str | None:
    """Fill the contact form. Returns an error string, or None on success."""
    page.wait_for_selector("#questionInput", timeout=15000)

    _tick_all_availability(page)
    page.fill("#questionInput", message)

    # Identity comes from the logged-in account; bail if it didn't autofill.
    email = page.input_value("#emailAddress")
    if not email.strip():
        return "details not autofilled — not logged in? run `applier --login`"

    # Address is not on the account, so fill it ourselves (masked inputs).
    if not _type_verify(page, "#postCode", APPLICANT_POSTCODE):
        log.warning("postcode didn't stick")
    if not _type_verify(page, "#houseNumber", APPLICANT_HOUSENUMBER):
        log.warning("housenumber didn't stick")

    for selector in (RADIO_SELLING_NO, RADIO_ADVICE_YES, RADIO_MOVE_ASAP, RADIO_ING_OPT_OUT):
        if not _set_radio(page, selector):
            log.warning("radio not set: %s", selector)
    return None


def apply_viewing(
    detail_url: str,
    message: str | None = None,
    *,
    submit: bool = True,
    headless: bool = False,
) -> ApplyResult:
    """Open a listing, fill the viewing-request form, and (optionally) submit it."""
    message = message or DEFAULT_MESSAGE
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    shot = SHOTS_DIR / f"apply-{date.today().isoformat()}.png"

    with sync_playwright() as pw:
        ctx = _launch(pw, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(detail_url, wait_until="domcontentloaded")
            _accept_cookies(page)

            if not _open_viewing_form(page):
                return ApplyResult(False, error="couldn't open the viewing-request form")
            _accept_cookies(page)

            err = _fill_form(page, message)
            if err:
                page.screenshot(path=str(shot))
                return ApplyResult(False, screenshot=str(shot), error=err)

            _save_session(page)  # keep the oidc token snapshot fresh
            page.screenshot(path=str(shot), full_page=True)
            if not submit:
                return ApplyResult(True, screenshot=str(shot), error="(not submitted — review)")

            page.get_by_role("button", name="Verstuur").click()
            # Funda's SPA never reaches networkidle (analytics keep polling), so
            # detect success by the form being replaced with a confirmation panel
            # (the message field detaches) or a thank-you message appearing.
            ok = False
            try:
                page.wait_for_selector("#questionInput", state="detached", timeout=15000)
                ok = True
            except PWTimeout:
                ok = page.get_by_text(
                    re.compile(r"bedankt|verzonden|verstuurd|aanvraag is|ontvangen", re.I)
                ).count() > 0
            page.wait_for_timeout(1000)
            done = SHOTS_DIR / f"apply-{date.today().isoformat()}-done.png"
            page.screenshot(path=str(done), full_page=True)
            return ApplyResult(
                ok, screenshot=str(done),
                error=None if ok else "submitted but no confirmation detected — check screenshot",
            )
        finally:
            ctx.close()


def login(timeout_s: int = 300) -> bool:
    """Open the browser ONCE so you can log into Funda by hand.

    Never types credentials — just opens a window. Auto-detects when login finishes
    (the account page stops redirecting to login.funda.nl), then saves the full
    session (cookies via the profile + the sessionStorage oidc token). Returns True
    on success.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = _launch(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.funda.nl/mijn/", wait_until="domcontentloaded")
        print("Browser opened. Log into Funda in that window — I'll detect when you're done...")

        waited = 0
        while waited < timeout_s:
            page.wait_for_timeout(2500)
            waited += 2.5
            if _logged_in(page):
                # confirm by re-checking the account area
                page.goto("https://www.funda.nl/mijn/", wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                if _logged_in(page):
                    _save_session(page)
                    print(f"✅ Logged in. Session saved ({PROFILE_DIR.name} + {SESSION_FILE.name}).")
                    ctx.close()
                    return True
        print("⏱️ Timed out waiting for login.")
        ctx.close()
        return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="one-time Funda login")
    ap.add_argument("--url", help="Funda listing detail URL to apply to")
    ap.add_argument("--message", help="message to the broker (default: English fallback)")
    ap.add_argument("--no-submit", action="store_true", help="fill but don't submit")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args(argv)

    if args.login:
        return 0 if login() else 1
    if not args.url:
        ap.error("--url is required (or use --login)")

    result = apply_viewing(
        args.url, args.message, submit=not args.no_submit, headless=args.headless,
    )
    print(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
