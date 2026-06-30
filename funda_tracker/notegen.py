"""Generates one Obsidian Markdown page per house.

Design rule: this module is APPEND-ONLY. It creates a page for a house it has never
seen, and never touches a page once it exists — so your notes, status changes, and
process log are always safe, no matter how often the tracker runs.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from funda_tracker import translate

log = logging.getLogger(__name__)

STATUS_NEW = "🆕 New"

# Funda feature keys -> human labels shown in the note body.
FEATURE_LABELS = {
    "has_garden": "Garden",
    "has_balcony": "Balcony",
    "has_roof_terrace": "Roof terrace",
    "has_solar_panels": "Solar panels",
    "has_heat_pump": "Heat pump",
    "has_parking_on_site": "Parking on site",
    "has_parking_enclosed": "Enclosed parking",
    "is_energy_efficient": "Energy efficient",
    "is_monument": "Monument",
    "is_fixer_upper": "Fixer-upper",
}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "house"


def _yaml_scalar(value) -> str:
    """Render a value as a YAML frontmatter scalar (bool before int — bool is an int)."""
    if value is None or value == "":
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', "'") + '"'


def note_path(houses_dir, listing) -> Path:
    """Stable path for a listing: keyed on the Funda id so re-runs resolve to the same file."""
    return Path(houses_dir) / f"{listing.id}-{_slug(listing.title)}.md"


def _first_photo(listing) -> str | None:
    media = getattr(listing, "media", None)
    for photo in getattr(media, "photos", None) or []:
        url = getattr(photo, "url", None) or getattr(photo, "embed_url", None)
        if url:
            return url
    return None


def _features_present(listing) -> list[str]:
    details = getattr(listing, "property_details", None)
    feats = getattr(details, "features", None) or {}
    return [FEATURE_LABELS.get(k, k) for k, v in feats.items() if v]


def _fmt_m2(value) -> str:
    return f"{value} m²" if value else "—"


def _date_only(value) -> str:
    """Trim an ISO timestamp ('2026-05-18T00:00:00Z') down to just the date."""
    return str(value or "").strip().split("T")[0].split(" ")[0]


def _frontmatter(listing, enriched: bool) -> str:
    price = getattr(getattr(listing, "price", None), "amount", None)
    fields = [
        ("funda_id", listing.id),
        ("address", listing.title),
        ("city", listing.city),
        ("price", price),
        ("m2", listing.living_area),
        ("rooms", listing.rooms_count),
        ("bedrooms", listing.bedrooms),
        ("energy_label", listing.energy_label),
        ("url", listing.url),
        ("status", STATUS_NEW),
        ("declined", False),  # tick this in Obsidian to decline; archive_declined.py sweeps it
        ("added", date.today().isoformat()),
        ("requested", ""),  # date you asked the broker for a viewing — you fill this in
        ("viewing_at", ""),  # ISO datetime when viewing is booked, e.g. 2026-05-27T11:30
        ("listed_date", _date_only(getattr(listing, "publication_date", ""))),
        ("enriched", enriched),
    ]
    lines = ["---"]
    lines += [f"{key}: {_yaml_scalar(val)}" for key, val in fields]
    lines += ["tags:", "  - house", "---"]
    return "\n".join(lines)


def _body(listing, enriched: bool) -> str:
    price = getattr(getattr(listing, "price", None), "formatted", None) or "—"
    parts: list[str] = [f"# {listing.title or 'House'}", ""]

    photo = _first_photo(listing)
    if photo:
        parts += [f"![]({photo})", ""]

    parts += [f"\U0001f517 **[Open on Funda]({listing.url})**", ""]

    parts += [
        "| | |",
        "|---|---|",
        f"| Price | {price} |",
        f"| City | {listing.city or '—'} |",
        f"| Living area | {_fmt_m2(listing.living_area)} |",
        f"| Rooms | {listing.rooms_count or '—'} "
        f"({listing.bedrooms or '—'} bedrooms) |",
        f"| Energy label | {listing.energy_label or '—'} |",
        f"| Listed on Funda | {_date_only(getattr(listing, 'publication_date', '')) or '—'} |",
        "",
    ]

    feats = _features_present(listing)
    if feats:
        parts += ["**Features:** " + ", ".join(feats), ""]

    broker = getattr(listing, "broker", None)
    broker_name = getattr(broker, "name", None) if broker else None
    if broker_name:
        parts += [f"**Agent:** {broker_name}", ""]

    description = translate.to_english(getattr(listing, "description", None))
    if description:
        snippet = description[:700].replace("\n", "\n> ")
        parts += ["> " + snippet, ""]

    if not enriched:
        parts += [
            "> [!warning] Detail fetch failed — this page has search data only.",
            "",
        ]

    parts += [
        "## Notes",
        "",
        "_Your thoughts on this house._",
        "",
        "## Process log",
        "",
        f"- {date.today().isoformat()} — listing found, page created",
        "",
    ]
    return "\n".join(parts)


def write_note(houses_dir, listing, enriched: bool) -> Path | None:
    """Create the page for a listing. Returns the path, or None if it already exists."""
    houses_dir = Path(houses_dir)
    houses_dir.mkdir(parents=True, exist_ok=True)

    path = note_path(houses_dir, listing)
    if path.exists():
        log.info("page already exists, skipping: %s", path.name)
        return None

    content = _frontmatter(listing, enriched) + "\n\n" + _body(listing, enriched) + "\n"
    path.write_text(content, encoding="utf-8")
    log.info("created page: %s", path.name)
    return path
