"""Persistent record of disclosures we've already seen.

The daily job uses this to report only *new* disclosures each run. The state is
a small JSON file; in GitHub Actions it's committed back to the repo so it
survives between scheduled runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Trade

DEFAULT_STATE_PATH = Path("state/seen_disclosures.json")


class SeenStore:
    def __init__(self, path: str | Path = DEFAULT_STATE_PATH):
        self.path = Path(path)
        self._seen: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._seen = set(json.loads(self.path.read_text()))
            except (json.JSONDecodeError, ValueError):
                self._seen = set()

    def new_trades(self, trades: list[Trade]) -> list[Trade]:
        """Return the subset of `trades` whose ids we haven't recorded yet."""
        return [t for t in trades if t.id not in self._seen]

    def mark_seen(self, trades: list[Trade]) -> None:
        for t in trades:
            self._seen.add(t.id)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(self._seen), indent=0))

    def __len__(self) -> int:
        return len(self._seen)
