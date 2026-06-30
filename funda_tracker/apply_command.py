"""Apply-command orchestration: decide WHAT house to apply to and with what text.

This is the pure, browser-free layer. parse_apply turns a Telegram message into an
intent; resolve_house matches an address against the tracked house notes. The
actual form submission lives in applier.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
HOUSES_DIR = ROOT / "houses"

DEFAULT_MESSAGE = (
    "I really like this house, let me know when it is possible to view it!"
)

# "apply to <address>" optionally followed by ": <custom message>"
_APPLY_RE = re.compile(r"^\s*apply\s+to\s+(?P<rest>.+)$", re.IGNORECASE | re.DOTALL)


@dataclass
class ApplyCommand:
    address: str
    message: str | None


@dataclass
class House:
    funda_id: str
    address: str
    city: str
    url: str
    path: Path


def default_message() -> str:
    return DEFAULT_MESSAGE


def parse_apply(text: str) -> ApplyCommand | None:
    """Parse 'apply to <address>[: <message>]'. Returns None if not an apply command."""
    if not text:
        return None
    m = _APPLY_RE.match(text)
    if not m:
        return None
    rest = m.group("rest").strip()
    if ":" in rest:
        address, message = rest.split(":", 1)
        address, message = address.strip(), message.strip()
    else:
        address, message = rest, None
    # collapse internal whitespace in the address ("Apply To   X" -> "X")
    address = re.sub(r"\s+", " ", address)
    if not address:
        return None
    return ApplyCommand(address=address, message=message or None)


VIEWING_REQUESTED_STATUS = "📨 Viewing requested"


def mark_viewing_requested(path: str | Path, date: str) -> None:
    """Flip a house note to 'Viewing requested' and log it.

    Sets front-matter `status` and `requested`, and prepends a process-log line
    (reverse-chronological, matching the existing notes).
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    text = re.sub(
        r'^status:.*$',
        f'status: "{VIEWING_REQUESTED_STATUS}"',
        text, count=1, flags=re.MULTILINE,
    )
    text = re.sub(
        r'^requested:.*$',
        f'requested: "{date}"',
        text, count=1, flags=re.MULTILINE,
    )

    log_line = f"- {date} — viewing requested via Funda (auto-apply)"
    text = re.sub(
        r'(^## Process log\s*\n\n)',
        rf'\1{log_line}\n',
        text, count=1, flags=re.MULTILINE,
    )

    path.write_text(text, encoding="utf-8")


def handle_apply(text, houses_dir=HOUSES_DIR, *, apply_fn=None, today=None) -> str:
    """End-to-end: parse → resolve house → submit viewing request → mark note.

    Returns a short plain-text reply for Telegram. `apply_fn` and `today` are
    injectable for testing; by default `apply_fn` is the real Playwright submitter.
    """
    cmd = parse_apply(text)
    if cmd is None:
        return "Not an apply command. Use: apply to <address>[: message]"

    matches = resolve_house(cmd.address, houses_dir)
    if not matches:
        return f"❌ No tracked house matches “{cmd.address}”."
    if len(matches) > 1:
        where = ", ".join(f"{m.address} ({m.city})" for m in matches)
        return f"⚠️ Multiple houses match “{cmd.address}”: {where}. Be more specific."

    house = matches[0]
    message = cmd.message or default_message()

    if apply_fn is None:
        from funda_tracker.applier import apply_viewing
        apply_fn = apply_viewing

    result = apply_fn(house.url, message)
    if not result.ok:
        return f"❌ Apply failed for {house.address}: {result.error}"

    mark_viewing_requested(house.path, today or date.today().isoformat())
    return f"✅ Applied to {house.address}, {house.city} — viewing requested."


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end]) or {}


def resolve_house(address: str, houses_dir: str | Path) -> list[House]:
    """Return every tracked house whose address matches `address` (case-insensitive)."""
    query = _normalize(address)
    matches: list[House] = []
    for path in sorted(Path(houses_dir).glob("*.md")):
        fm = _read_frontmatter(path)
        note_addr = _normalize(str(fm.get("address", "")))
        if not note_addr:
            continue
        if note_addr == query or query in note_addr:
            matches.append(House(
                funda_id=str(fm.get("funda_id", "")),
                address=str(fm.get("address", "")),
                city=str(fm.get("city", "")),
                url=str(fm.get("url", "")),
                path=path,
            ))
    return matches
