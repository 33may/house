"""Talks to Funda via pyfunda: runs the search and fetches full listing detail."""

from __future__ import annotations

import logging

from funda import Funda, FundaError

log = logging.getLogger(__name__)


def search_listings(client: Funda, location, filters: dict, pages: int) -> list:
    """Return Listing summaries for the configured search, newest first.

    iter_search yields listings flattened across pages; max_pages bounds how far
    back we scan each run (pages * 15 listings).
    """
    filters = dict(filters)
    filters.setdefault("sort", "newest")
    results = list(client.iter_search(location, max_pages=pages, **filters))
    log.info("search returned %d listing(s) across %d page(s)", len(results), pages)
    return results


def enrich(client: Funda, listing_id: int):
    """Fetch the full listing detail. Returns the Listing, or None if the fetch fails.

    A failed enrich is not fatal — run.py falls back to the search summary and flags
    the page as not enriched.
    """
    try:
        return client.listing(listing_id)
    except FundaError as e:
        log.warning("detail fetch failed for %s: %s", listing_id, e)
        return None
