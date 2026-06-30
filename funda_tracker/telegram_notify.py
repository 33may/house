"""Sends tracker notifications to Telegram.

The Obsidian vault is the source of truth; these messages are a short read-only
echo of what an automation added to it. Best-effort: a send failure (or a missing
secrets.yaml) is logged and never raised, so a Funda poll or Gmail sync is never
broken by a notification problem. Messages are plain text — Telegram auto-links
raw URLs, which avoids every Markdown/HTML escaping pitfall.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / "secrets.yaml"
LOG_DIR = ROOT / "logs"

_API = "https://api.telegram.org"
_TIMEOUT = 10
_MAX_LISTINGS = 10


# --- message formatting -----------------------------------------------------

def _read_frontmatter(path: Path | str) -> dict:
    """Parse the YAML frontmatter of a house page. Returns {} if unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def _page_line(fm: dict) -> str:
    """Render one house page's frontmatter as a short plain-text block."""
    address = fm.get("address") or "House"
    city = fm.get("city") or ""
    price = fm.get("price")
    m2 = fm.get("m2")
    rooms = fm.get("rooms")
    label = fm.get("energy_label")
    status = fm.get("status") or ""
    url = fm.get("url") or ""

    facts = []
    if isinstance(price, (int, float)) and price:
        facts.append(f"€ {int(price):,}".replace(",", "."))
    if m2:
        facts.append(f"{m2} m²")
    if rooms:
        facts.append(f"{rooms} rooms")
    if label:
        facts.append(f"label {label}")

    lines = ["🏠 " + str(address) + (f", {city}" if city else "")]
    if facts:
        lines.append(" · ".join(facts))
    if status:
        lines.append(str(status))
    if url:
        lines.append(str(url))
    return "\n".join(lines)


def format_new_pages(paths: Iterable[Path | str]) -> str:
    """Build the 'new houses on Funda' message by reading each created page."""
    paths = list(paths)
    n = len(paths)
    header = f"🆕 {n} new house{'s' if n != 1 else ''} on Funda"
    blocks = []
    for p in paths[:_MAX_LISTINGS]:
        fm = _read_frontmatter(p)
        if fm:
            blocks.append(_page_line(fm))
    if not blocks:
        return header
    text = header + "\n\n" + "\n\n".join(blocks)
    if n > _MAX_LISTINGS:
        text += f"\n\n…and {n - _MAX_LISTINGS} more"
    return text


def format_failure(what: str, detail: str = "") -> str:
    """Build a failure-alert message. (Operational — not vault data.)"""
    text = f"⚠️ {what}"
    if detail:
        text += f"\n{detail}"
    return text


# --- sending ----------------------------------------------------------------

def _read_secrets() -> dict:
    """Raw contents of secrets.yaml, or {} if it is missing/unreadable."""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except OSError:
        return {}


def _load_secrets() -> tuple[str, str] | None:
    """Return (bot_token, chat_id), or None if either is missing."""
    data = _read_secrets()
    token = str(data.get("telegram_bot_token") or "").strip()
    chat_id = str(data.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


def send(text: str) -> bool:
    """POST a plain-text message to the configured Telegram chat.

    Returns True on success. Never raises. A no-op returning False when
    secrets.yaml is missing or incomplete, or when text is empty.
    """
    if not (text or "").strip():
        return False
    secrets = _load_secrets()
    if secrets is None:
        log.warning("telegram: secrets.yaml missing/incomplete — notification skipped")
        return False
    token, chat_id = secrets
    url = f"{_API}/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    try:
        with urllib.request.urlopen(url, data=payload, timeout=_TIMEOUT) as resp:
            resp.read()
        return True
    except Exception as e:  # noqa: BLE001 — notifications must never break a run
        log.warning("telegram: send failed: %s", e)
        return False


def send_throttled(text: str, key: str, min_gap_seconds: int) -> bool:
    """Like send(), but sends at most once per min_gap_seconds for the given key."""
    stamp = LOG_DIR / f".notify-{key}"
    now = time.time()
    try:
        last = float(stamp.read_text())
    except Exception:  # noqa: BLE001 — throttle must never break the never-raise contract
        last = 0.0
    if now - last < min_gap_seconds:
        log.info("telegram: '%s' throttled (last sent %.0fs ago)", key, now - last)
        return False
    ok = send(text)
    if ok:
        try:
            LOG_DIR.mkdir(exist_ok=True)
            stamp.write_text(str(now))
        except OSError as e:
            log.warning("telegram: could not write throttle stamp: %s", e)
    return ok


# --- command-line interface -------------------------------------------------

def _probe() -> int:
    """Print recent chat IDs from getUpdates — a setup helper for finding chat_id."""
    token = str(_read_secrets().get("telegram_bot_token") or "").strip()
    if not token:
        print("No telegram_bot_token in secrets.yaml — add it first.")
        return 1
    try:
        with urllib.request.urlopen(f"{_API}/bot{token}/getUpdates", timeout=_TIMEOUT) as resp:
            data = json.load(resp)
    except Exception as e:  # noqa: BLE001
        print(f"getUpdates failed: {e}")
        return 1
    chats: dict = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            chats[chat["id"]] = (
                chat.get("first_name") or chat.get("title") or chat.get("username") or ""
            )
    if not chats:
        print("No chats yet. Send your bot a message in Telegram, then run --probe again.")
        return 1
    print("Recent chats — copy the right id into secrets.yaml as telegram_chat_id:")
    for cid, name in chats.items():
        print(f"  {cid}  {name}")
    return 0


def _main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not argv:
        print("usage: python3 -m funda_tracker.telegram_notify [--probe | --file PATH | TEXT]")
        return 2
    if argv[0] == "--probe":
        return _probe()
    if argv[0] == "--file":
        if len(argv) < 2:
            print("--file needs a path")
            return 2
        try:
            text = Path(argv[1]).read_text(encoding="utf-8").strip()
        except OSError as e:
            print(f"could not read {argv[1]}: {e}")
            return 1
        if not text:
            return 0
        return 0 if send(text) else 1
    return 0 if send(" ".join(argv)) else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
