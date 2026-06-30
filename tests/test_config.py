"""Tests for preferences loading — especially per-city searches."""

from __future__ import annotations

import textwrap
from pathlib import Path

from funda_tracker.config import load_config


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "preferences.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_single_search_back_compat(tmp_path):
    """A plain `search:` block (no `searches:`) yields exactly one query."""
    path = _write(tmp_path, """
        search:
          category: buy
          location:
            - Tilburg
          max_price: 350000
          object_type:
            - house
    """)
    cfg = load_config(path)
    searches = cfg.searches
    assert len(searches) == 1
    location, filters = searches[0]
    assert location == ["Tilburg"]
    assert filters["max_price"] == 350000


def test_per_city_searches_merge_over_base(tmp_path):
    """Each `searches:` entry is merged over the shared `search` block, with
    entry keys (location, max_price) winning — one query per city."""
    path = _write(tmp_path, """
        search:
          category: buy
          object_type:
            - house
          sort: newest
        searches:
          - location: [Tilburg]
            max_price: 350000
          - location: [Eindhoven]
            max_price: 450000
    """)
    cfg = load_config(path)
    searches = cfg.searches
    assert len(searches) == 2

    tilburg_loc, tilburg_filters = searches[0]
    eindhoven_loc, eindhoven_filters = searches[1]

    assert tilburg_loc == ["Tilburg"]
    assert eindhoven_loc == ["Eindhoven"]
    assert tilburg_filters["max_price"] == 350000
    assert eindhoven_filters["max_price"] == 450000

    # shared base fields propagate to every search
    assert tilburg_filters["category"] == "buy"
    assert eindhoven_filters["category"] == "buy"
    assert tilburg_filters["sort"] == "newest"


def test_none_values_dropped_from_filters(tmp_path):
    """null preferences must not be sent as filters (would override Funda's
    defaults)."""
    path = _write(tmp_path, """
        search:
          category: buy
          min_price: null
          object_type:
            - house
        searches:
          - location: [Eindhoven]
            max_price: 450000
    """)
    cfg = load_config(path)
    _, filters = cfg.searches[0]
    assert "min_price" not in filters
    assert "location" not in filters
