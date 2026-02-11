"""Session tag persistence store."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ._base import JsonStore


class TagStore(JsonStore):
    """Session tags (``{session_id: [tag1, tag2, ...]}``)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    @staticmethod
    def _normalize(tag: str) -> str:
        """Strip whitespace, leading ``#``, and lowercase."""
        return tag.strip().lstrip("#").lower()

    def load(self) -> dict[str, list[str]]:
        """Load all session tags."""
        raw = self.load_raw()
        if not isinstance(raw, dict):
            return {}
        return raw

    def save(self, data: dict[str, list[str]]) -> None:
        """Persist session tags to disk."""
        self.save_raw(data, sort_keys=True)

    def get_tags(self, session_id: str) -> list[str]:
        """Return the tags for *session_id* (empty list if none)."""
        return self.load().get(session_id, [])

    def add_tag(self, session_id: str, tag: str) -> bool:
        """Add *tag* to *session_id*. Return ``False`` if already present."""
        tag = self._normalize(tag)
        data = self.load()
        tags = data.get(session_id, [])
        if tag in tags:
            return False
        tags.append(tag)
        data[session_id] = tags
        self.save(data)
        return True

    def remove_tag(self, session_id: str, tag: str) -> bool:
        """Remove *tag* from *session_id*. Return ``False`` if not found."""
        tag = self._normalize(tag)
        data = self.load()
        tags = data.get(session_id, [])
        if tag not in tags:
            return False
        tags.remove(tag)
        if tags:
            data[session_id] = tags
        else:
            data.pop(session_id, None)
        self.save(data)
        return True

    def all_tags(self) -> dict[str, int]:
        """Return ``{tag: count}`` across all sessions, sorted by count desc."""
        data = self.load()
        counter: Counter[str] = Counter()
        for tags in data.values():
            counter.update(tags)
        return dict(counter.most_common())

    def sessions_with_tag(self, tag: str) -> list[str]:
        """Return session IDs that have *tag*."""
        tag = self._normalize(tag)
        data = self.load()
        return [sid for sid, tags in data.items() if tag in tags]
