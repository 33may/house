#!/usr/bin/env python3
"""Funda house-hunt tracker — entry point.

Polls Funda for listings matching preferences.yaml and writes one Obsidian page per
new match. Safe to run on a schedule: it only ever creates pages, never edits them.

Usage:
    python3 run.py            # normal run
    python3 run.py --dry-run  # search and report only — writes no pages, no state
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from funda import Funda, FundaError

from funda_tracker.config import load_config
from funda_tracker.agenda_notify import send_agenda
from funda_tracker.fetcher import enrich, search_listings
from funda_tracker.matcher import passes_local_filters
from funda_tracker.notegen import note_path, write_note
from funda_tracker.telegram_notify import format_failure, format_new_pages, send, send_throttled
from funda_tracker.state import State

ROOT = Path(__file__).resolve().parent
HOUSES_DIR = ROOT / "houses"
LOG_DIR = ROOT / "logs"


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "tracker.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main(dry_run: bool = False) -> int:
    setup_logging()
    log = logging.getLogger("run")
    log.info("=== run started%s ===", " (dry-run)" if dry_run else "")

    try:
        cfg = load_config(ROOT / "preferences.yaml")
    except (OSError, ValueError) as e:
        log.error("could not load preferences.yaml: %s", e)
        return 1

    state = State(ROOT / "state.json")
    searches = cfg.searches
    created = []

    try:
        with Funda() as client:
            # Each city is its own query (own price cap, own newest-N window).
            # Dedup by id so a listing in overlapping areas is handled once.
            listings = []
            seen_ids = set()
            for location, filters in searches:
                for lst in search_listings(client, location, filters, cfg.pages):
                    if lst.id not in seen_ids:
                        seen_ids.add(lst.id)
                        listings.append(lst)
            new = [lst for lst in listings if not state.is_seen(lst.id)]
            log.info("%d listing(s) returned, %d new", len(listings), len(new))

            for summary in new:
                detail = enrich(client, summary.id)
                listing = detail if detail is not None else summary
                is_enriched = detail is not None

                # Feature filters need detail data; skip them if enrichment failed.
                if is_enriched:
                    ok, reason = passes_local_filters(
                        listing, cfg.require_features, cfg.exclude_features
                    )
                    if not ok:
                        log.info("filtered out %s — %s", summary.id, reason)
                        state.mark_seen(summary.id)
                        continue

                if dry_run:
                    log.info("[dry-run] would create page for %s — %s",
                             summary.id, listing.title)
                    created.append(note_path(HOUSES_DIR, listing))
                    continue

                path = write_note(HOUSES_DIR, listing, is_enriched)
                if path is not None:
                    created.append(path)
                state.mark_seen(summary.id)
    except FundaError as e:
        log.error("Funda request failed — will retry next run: %s", e)
        if not dry_run:
            send_throttled(
                format_failure(
                    "Funda poll failed — will retry in 20 min.",
                    f"{type(e).__name__}: {e}",
                ),
                key="funda-fail",
                min_gap_seconds=10800,
            )
        return 1
    finally:
        if not dry_run:
            state.save()

    if created and not dry_run:
        send(format_new_pages(created))
    if not dry_run:
        try:
            if send_agenda():
                log.info("agenda notification sent")
        except Exception as e:  # noqa: BLE001 — agenda must never break Funda polling
            log.warning("agenda notification failed: %s", e)
    log.info("done — %d new page(s)%s",
             len(created), " (dry-run, none written)" if dry_run else "")
    log.info("=== run finished ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
