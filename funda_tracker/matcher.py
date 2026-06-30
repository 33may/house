"""Local filters — the checks Funda's search API can't do server-side.

Funda filters price/area/rooms/etc. server-side already. This module only applies
the boolean *feature* filters (garden, fixer-upper, ...) which live on the listing
detail object, not on search results.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def listing_features(listing) -> dict:
    """The property_details.features dict, or {} if unavailable."""
    details = getattr(listing, "property_details", None)
    return dict(getattr(details, "features", None) or {})


def passes_local_filters(
    listing, require: list[str], exclude: list[str]
) -> tuple[bool, str]:
    """Return (passes, reason). reason is '' when the listing passes.

    require: a feature missing or false fails the listing.
    exclude: a feature present and true fails the listing.
    """
    features = listing_features(listing)

    for feat in require:
        if not features.get(feat):
            return False, f"missing required feature: {feat}"

    for feat in exclude:
        if features.get(feat):
            return False, f"has excluded feature: {feat}"

    return True, ""
