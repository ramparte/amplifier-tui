"""Pinned-session persistence store."""

from __future__ import annotations

from pathlib import Path

from ._base import JsonStore


class PinnedSessionStore(JsonStore):
    """Pinned session IDs (stored as a sorted JSON list on disk)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def _default(self) -> list:
        return []

    def load(self) -> set[str]:
        """Load pinned session IDs from disk."""
        try:
            if self.path.exists():
                import json

                data = json.loads(self.path.read_text(encoding="utf-8"))
                return set(data)
        except Exception:
            pass
        return set()

    def save(self, session_ids: set[str]) -> None:
        """Persist the current set of pinned session IDs."""
        try:
            self.save_raw(sorted(session_ids))
        except Exception:
            pass
