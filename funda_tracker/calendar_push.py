"""Pushes a booked viewing into Apple Calendar via osascript.

Idempotent: re-running on the same viewing finds the existing event (matched by
funda_id baked into the description) and does nothing. Safe to call from gmail-sync
on every run.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CALENDAR_NAME = "Домашній"  # writable calendar to receive viewings
DEFAULT_DURATION_MIN = 30
DEFAULT_TIMEZONE = "Europe/Amsterdam"
FALLBACK_DIR = ROOT / "logs" / "calendar-imports"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = yaml.safe_load(parts[1])
    return fm if isinstance(fm, dict) else {}


def _process_log(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## Process log\s*\n(.*)\Z", text, re.DOTALL | re.MULTILINE)
    return m.group(1) if m else ""


def _broker_from_log(log_text: str) -> str | None:
    """Best-effort: pick the broker name out of the most recent broker mention."""
    m = re.search(r"\(([^)]+(?:Makelaars?|Makelaardij|Makelaar)[^)]*)\)", log_text)
    return m.group(1) if m else None


def _parse_viewing_at(value) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    # Accept '2026-05-27T11:30' and '2026-05-27 11:30' and '2026-05-27T11:30:00'
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _applescript_str(s: str) -> str:
    """Escape a Python string for an AppleScript literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", '" & return & "')


def _build_script(*, summary: str, location: str, description: str,
                  start: datetime, end: datetime, calendar: str,
                  marker: str) -> str:
    """Build the AppleScript. Idempotent: skip if any event description contains marker."""
    return f'''
set targetCal to "{_applescript_str(calendar)}"
set marker to "{_applescript_str(marker)}"

set startDate to current date
set year of startDate to {start.year}
set month of startDate to {start.month}
set day of startDate to {start.day}
set hours of startDate to {start.hour}
set minutes of startDate to {start.minute}
set seconds of startDate to 0

set endDate to current date
set year of endDate to {end.year}
set month of endDate to {end.month}
set day of endDate to {end.day}
set hours of endDate to {end.hour}
set minutes of endDate to {end.minute}
set seconds of endDate to 0

tell application "Calendar"
  tell calendar targetCal
    set existing to every event whose description contains marker
    if (count of existing) > 0 then
      return "skip: event with marker already exists"
    end if
    set newEvent to make new event at end with properties ¬
      {{summary:"{_applescript_str(summary)}", ¬
       start date:startDate, ¬
       end date:endDate, ¬
       location:"{_applescript_str(location)}", ¬
       description:"{_applescript_str(description)}"}}
  end tell
  return "created: " & (summary of newEvent) & " at " & (start date of newEvent as string)
end tell
'''


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def _ics_datetime(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def _ics_dtstamp(value: datetime, timezone_name: str) -> str:
    try:
        zoned = value.replace(tzinfo=ZoneInfo(timezone_name))
        return zoned.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    except Exception:  # noqa: BLE001 - ICS fallback should stay best-effort
        return value.strftime("%Y%m%dT%H%M%SZ")


def _fallback_ics_path(*, funda_id: str, start: datetime) -> Path:
    stamp = start.strftime("%Y%m%dT%H%M")
    return FALLBACK_DIR / f"{funda_id}-{stamp}.ics"


def _build_ics(*, uid: str, summary: str, location: str, description: str,
               start: datetime, end: datetime, timezone_name: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Funda Tracker//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{_ics_escape(uid)}",
        f"DTSTAMP:{_ics_dtstamp(start, timezone_name)}",
        f"DTSTART;TZID={timezone_name}:{_ics_datetime(start)}",
        f"DTEND;TZID={timezone_name}:{_ics_datetime(end)}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"LOCATION:{_ics_escape(location)}",
        f"DESCRIPTION:{_ics_escape(description)}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines)


def _write_fallback_ics(*, funda_id: str, summary: str, location: str,
                        description: str, start: datetime, end: datetime) -> str:
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = _fallback_ics_path(funda_id=funda_id, start=start)
    uid = f"house-tracker-{funda_id}-{start.strftime('%Y%m%dT%H%M%S')}"
    content = _build_ics(
        uid=uid,
        summary=summary,
        location=location,
        description=description,
        start=start,
        end=end,
        timezone_name=DEFAULT_TIMEZONE,
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if existing == content.replace("\r\n", "\n"):
            return f"fallback: .ics already exists at {path}"
    path.write_text(content, encoding="utf-8", newline="")
    return f"fallback: wrote .ics to {path}"


def push(page_path: Path, *, duration_min: int = DEFAULT_DURATION_MIN,
         calendar: str = CALENDAR_NAME) -> str:
    fm = _frontmatter(page_path)
    viewing_at = _parse_viewing_at(fm.get("viewing_at"))
    if not viewing_at:
        return f"skip: no parseable viewing_at in {page_path.name}"
    if str(fm.get("status") or "").startswith("📅") is False:
        return f"skip: status is not '📅 Viewing booked' on {page_path.name}"

    funda_id = str(fm.get("funda_id") or "")
    address = str(fm.get("address") or "House")
    city = str(fm.get("city") or "")
    url = str(fm.get("url") or "")
    broker = _broker_from_log(_process_log(page_path)) or "broker"
    marker = f"[house-tracker:{funda_id}]"

    summary = f"🏠 Viewing — {address}, {city}".strip(", ")
    location = f"{address}, {city}".strip(", ")
    description_parts = [f"{broker} · ~{duration_min} min", url, marker]
    description = "\n".join(p for p in description_parts if p)

    end = viewing_at + timedelta(minutes=duration_min)
    script = _build_script(
        summary=summary, location=location, description=description,
        start=viewing_at, end=end, calendar=calendar, marker=marker,
    )

    try:
        result = subprocess.run(
            ["osascript", "-"], input=script, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
        return result.stdout.strip()
    except Exception as exc:  # noqa: BLE001 - fallback is intentional here
        log.warning("Apple Calendar push failed for %s: %s", page_path.name, exc)
        fallback = _write_fallback_ics(
            funda_id=funda_id,
            summary=summary,
            location=location,
            description=description,
            start=viewing_at,
            end=end,
        )
        return f"{fallback} (Apple Calendar automation unavailable)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page", help="path to the houses/<id>-<slug>.md page")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_MIN,
                        help=f"event length in minutes (default {DEFAULT_DURATION_MIN})")
    parser.add_argument("--calendar", default=CALENDAR_NAME,
                        help=f"target calendar name (default '{CALENDAR_NAME}')")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    msg = push(Path(args.page), duration_min=args.duration, calendar=args.calendar)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
