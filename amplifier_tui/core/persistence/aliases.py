"""Alias persistence store."""

from __future__ import annotations

from pathlib import Path

from ._base import JsonStore


class AliasStore(JsonStore):
    """Custom command aliases (``{name: expansion}``)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load(self) -> dict[str, str]:
        """Load aliases from disk."""
        return self.load_raw()  # type: ignore[return-value]

    def save(self, aliases: dict[str, str]) -> None:
        """Persist aliases to disk."""
        self.save_raw(aliases, sort_keys=True)
