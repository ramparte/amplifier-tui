"""Clipboard ring persistence store."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ._base import JsonStore

_MAX_ENTRIES = 50


class ClipboardStore(JsonStore):
    """Ordered list of clipboard entries (newest first).

    Each entry: ``{content: str, timestamp: str, source: str}``.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def _default(self) -> list:  # type: ignore[override]  # noqa: PLR6301
        return []

    def load(self) -> list[dict[str, str]]:
        """Load clipboard ring entries."""
        raw = self.load_raw()
        if isinstance(raw, list):
            return raw
        return []

    def save(self, data: list[dict[str, str]]) -> None:
        """Persist clipboard ring to disk."""
        self.save_raw(data)

    def add(self, content: str, source: str = "manual") -> None:
        """Prepend an entry and prune to max size."""
        entries = self.load()
        entry = {
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
        }
        entries.insert(0, entry)
        entries = entries[:_MAX_ENTRIES]
        self.save(entries)

    def clear(self) -> int:
        """Clear all entries. Returns the count that was cleared."""
        entries = self.load()
        count = len(entries)
        self.save([])
        return count

    def search(self, query: str) -> list[tuple[int, dict[str, str]]]:
        """Search entries by content (case-insensitive).

        Returns matching ``(1-based-index, entry)`` pairs.
        """
        entries = self.load()
        query_lower = query.lower()
        matches: list[tuple[int, dict[str, str]]] = []
        for i, entry in enumerate(entries, 1):
            if query_lower in entry.get("content", "").lower():
                matches.append((i, entry))
        return matches
