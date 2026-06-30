"""Loads preferences.yaml into a typed Config used by the rest of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_RADII = (1, 2, 5, 10, 15, 30, 50)


@dataclass
class Config:
    search: dict             # raw search block from preferences.yaml
    require_features: list[str]
    exclude_features: list[str]
    pages: int
    raw: dict

    @staticmethod
    def _split(block: dict) -> tuple[list[str] | None, dict]:
        """Split one search block into (location, filters) for pyfunda's search().

        pyfunda treats every kwarg as a filter, so None values must be dropped —
        otherwise we'd send `min_price=None` and override pyfunda's own defaults.
        """
        block = dict(block)
        location = block.pop("location", None)
        if isinstance(location, str):
            location = [location]

        # radius_km is only accepted with exactly one location.
        if block.get("radius_km") is not None and (not location or len(location) != 1):
            block.pop("radius_km", None)

        filters = {k: v for k, v in block.items() if v is not None}
        return location, filters

    @property
    def search_kwargs(self) -> tuple[list[str] | None, dict]:
        """The single (location, filters) pair for the base `search` block."""
        return self._split(self.search)

    @property
    def searches(self) -> list[tuple[list[str] | None, dict]]:
        """One (location, filters) pair per query to run.

        If preferences defines a `searches:` list, each entry is merged over the
        shared `search` block (entry keys win) and becomes its own query. This
        lets each city carry its own max_price and be scanned independently, so
        a busy city can't crowd a quiet one out of the newest-N window.

        With no `searches:` list, falls back to the single `search` block.
        """
        entries = self.raw.get("searches")
        if not entries:
            return [self.search_kwargs]
        return [self._split({**self.search, **(entry or {})}) for entry in entries]


def load_config(path: str | Path = "preferences.yaml") -> Config:
    """Read and validate preferences.yaml."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    search = data.get("search") or {}

    radius = search.get("radius_km")
    if radius is not None and radius not in VALID_RADII:
        raise ValueError(f"radius_km must be one of {VALID_RADII}, got {radius!r}")

    poll = data.get("poll") or {}
    return Config(
        search=search,
        require_features=list(data.get("require_features") or []),
        exclude_features=list(data.get("exclude_features") or []),
        pages=int(poll.get("pages", 2)),
        raw=data,
    )
