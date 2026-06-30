"""Build and send a short house-hunt agenda via Telegram.

This module is safe to call from frequent launchd jobs. Calendar pushes are
idempotent through `calendar_push`, and Telegram messages are throttled so the
20-minute Funda poll can call it without spamming.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from funda_tracker import calendar_push, telegram_notify

ROOT = Path(__file__).resolve().parent.parent
HOUSES_DIR = ROOT / "houses"
DEFAULT_MIN_GAP_SECONDS = 6 * 60 * 60
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
DATE_HINT_RE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+(\d{4}))?"
    r"(?:\s+(?:at|from)\s+(\d{1,2}):(\d{2}))?",
    re.IGNORECASE,
)


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1])
    return data if isinstance(data, dict) else {}


def _process_log(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^## Process log\s*\n(.*)\Z", text, re.DOTALL | re.MULTILINE)
    return match.group(1) if match else ""


def _houses(houses_dir: Path = HOUSES_DIR) -> list[dict]:
    return [
        {"path": path, "frontmatter": _frontmatter(path), "log": _process_log(path)}
        for path in sorted(houses_dir.glob("*.md"))
    ]


def _status(house: dict) -> str:
    return str(house["frontmatter"].get("status") or "")


def _address(house: dict) -> str:
    return str(house["frontmatter"].get("address") or house["path"].stem)


def _parse_viewing_at(house: dict) -> datetime | None:
    return calendar_push._parse_viewing_at(house["frontmatter"].get("viewing_at"))


def _format_when(value: datetime) -> str:
    return value.strftime("%a %-d %b %H:%M")


def _future_datetime_hints(text: str, now: datetime) -> list[datetime]:
    hints: list[datetime] = []
    for match in DATE_HINT_RE.finditer(text):
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3) or now.year)
        hour = int(match.group(4) or 23)
        minute = int(match.group(5) or 59)
        try:
            value = datetime(year, month, day, hour, minute)
        except ValueError:
            continue
        if not match.group(3) and value < now - timedelta(days=180):
            try:
                value = datetime(year + 1, month, day, hour, minute)
            except ValueError:
                continue
        if value >= now:
            hints.append(value)
    return hints


def _has_future_datetime_hint(text: str, now: datetime) -> bool:
    return bool(_future_datetime_hints(text, now))


def _has_future_keyword_datetime(log: str, keyword: str, now: datetime) -> bool:
    keyword = keyword.lower()
    return any(
        keyword in line.lower() and _has_future_datetime_hint(line, now)
        for line in log.splitlines()
    )


def _active(house: dict) -> bool:
    if house["frontmatter"].get("declined") is True:
        return False
    return not _status(house).startswith("❌")


def _upcoming_viewings(houses: list[dict], now: datetime) -> list[str]:
    dated = [
        (_parse_viewing_at(house), house)
        for house in houses
        if (
            _active(house)
            and _status(house).startswith("📅")
            and _parse_viewing_at(house)
            and _parse_viewing_at(house) >= now
        )
    ]
    return [
        f"- {_format_when(viewing_at)} — {_address(house)}"
        for viewing_at, house in sorted(dated, key=lambda item: item[0])
    ]


def _action_items(houses: list[dict], now: datetime) -> list[str]:
    items: list[str] = []
    for house in houses:
        if not _active(house):
            continue
        log = house["log"]
        address = _address(house)
        status = _status(house)
        if (
            status.startswith("📅")
            and not _parse_viewing_at(house)
            and _has_future_datetime_hint(log, now)
        ):
            items.append(f"- {address} — choose/confirm proposed viewing slot")
        if status.startswith("📨"):
            if "asked you to call to schedule" in log:
                items.append(f"- {address} — call broker to schedule viewing")
            if "invited you to book a viewing appointment" in log:
                items.append(f"- {address} — book viewing appointment")
            match = re.search(r"please call back at ([^\n]+)", log)
            if match:
                phone = match.group(1).strip().rstrip(".")
                items.append(f"- {address} — call back {phone}")
        if _has_future_keyword_datetime(log, "bidding deadline", now):
            items.append(f"- {address} — check bidding deadline")
    return list(dict.fromkeys(items))[:10]


def build_agenda_message(*, houses_dir: Path = HOUSES_DIR, now: datetime | None = None) -> str:
    now = now or datetime.now()
    houses = _houses(houses_dir)
    viewings = _upcoming_viewings(houses, now)
    actions = _action_items(houses, now)
    if not viewings and not actions:
        return ""
    sections = ["📌 House agenda"]
    if viewings:
        sections.append("📅 Upcoming viewings\n" + "\n".join(viewings[:8]))
    if actions:
        sections.append("✉️ To answer / do\n" + "\n".join(actions))
    return "\n\n".join(sections)


def push_missing_calendar_events(*, houses_dir: Path = HOUSES_DIR,
                                 now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    results: list[str] = []
    for house in _houses(houses_dir):
        if not _active(house):
            continue
        if not _status(house).startswith("📅"):
            continue
        viewing_at = _parse_viewing_at(house)
        if not viewing_at:
            continue
        if viewing_at < now:
            continue
        try:
            results.append(f"{house['path'].name}: {calendar_push.push(house['path'])}")
        except Exception as exc:  # noqa: BLE001 — agenda must not break poll/sync jobs
            results.append(f"{house['path'].name}: calendar failed: {exc}")
    return results


def send_agenda(*, houses_dir: Path = HOUSES_DIR,
                min_gap_seconds: int = DEFAULT_MIN_GAP_SECONDS,
                force: bool = False,
                push_calendar: bool = True) -> bool:
    if push_calendar:
        push_missing_calendar_events(houses_dir=houses_dir)
    message = build_agenda_message(houses_dir=houses_dir)
    if not message:
        return False
    if force:
        return telegram_notify.send(message)
    return telegram_notify.send_throttled(message, key="house-agenda", min_gap_seconds=min_gap_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="send even if throttle stamp is fresh")
    parser.add_argument("--dry-run", action="store_true", help="print agenda without sending")
    parser.add_argument("--no-calendar", action="store_true", help="skip idempotent Calendar push")
    parser.add_argument("--min-gap-seconds", type=int, default=DEFAULT_MIN_GAP_SECONDS)
    args = parser.parse_args()

    message = build_agenda_message()
    if args.dry_run:
        print(message or "No agenda items.")
        return 0
    sent = send_agenda(
        min_gap_seconds=args.min_gap_seconds,
        force=args.force,
        push_calendar=not args.no_calendar,
    )
    print("agenda sent" if sent else "agenda skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
