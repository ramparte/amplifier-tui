"""Bookmark persistence store."""

from __future__ import annotations

from pathlib import Path

from ._base import JsonStore


class BookmarkStore(JsonStore):
    """Session bookmarks (``{session_id: [bookmark_dict, ...]}``)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load_all(self) -> dict[str, list[dict]]:
        """Load the full bookmarks dict from disk."""
        return self.load_raw()  # type: ignore[return-value]

    def add(self, session_id: str, bookmark: dict) -> None:
        """Append a bookmark for *session_id* and persist."""
        all_bm = self.load_all()
        if session_id not in all_bm:
            all_bm[session_id] = []
        all_bm[session_id].append(bookmark)
        self.save_raw(all_bm)

    def for_session(self, session_id: str | None) -> list[dict]:
        """Return bookmarks for a single session (empty list if none)."""
        if not session_id:
            return []
        return self.load_all().get(session_id, [])

    def save_for_session(self, session_id: str, bookmarks: list[dict]) -> None:
        """Overwrite all bookmarks for *session_id* (used by remove/clear)."""
        all_bm = self.load_all()
        all_bm[session_id] = list(bookmarks)
        self.save_raw(all_bm)
