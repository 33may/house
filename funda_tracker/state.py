"""Persists which Funda listing IDs have already been processed (de-duplication).

A listing is 'seen' once we have either created its page or confirmed it fails the
local filters. Seen IDs are never reconsidered, so the tracker is safe to run on a
tight schedule without ever regenerating a page or touching your notes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class State:
    def __init__(self, path: str | Path = "state.json"):
        self.path = Path(path)
        self._seen: set[int] = set()
        self.last_run: str | None = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self._seen = {int(x) for x in data.get("seen", [])}
            self.last_run = data.get("last_run")

    def is_seen(self, listing_id: int) -> bool:
        return int(listing_id) in self._seen

    def mark_seen(self, listing_id: int) -> None:
        self._seen.add(int(listing_id))

    def save(self) -> None:
        payload = {
            "seen": sorted(self._seen),
            "last_run": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
