"""Base JSON persistence store."""

from __future__ import annotations

import json
from pathlib import Path

from ..log import logger


class JsonStore:
    """Simple JSON file store with atomic write.

    Subclasses override ``_default()`` to provide the empty-state value
    (``{}`` for dicts, ``[]`` for lists).
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    # -- core I/O -------------------------------------------------------------

    def load_raw(self) -> dict | list:
        """Read and parse the JSON file, returning ``_default()`` on any error."""
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.debug("failed to load JSON store from %s", self.path, exc_info=True)
        return self._default()

    def save_raw(self, data: dict | list, *, sort_keys: bool = False) -> None:
        """Write *data* as pretty-printed JSON, creating parents as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=sort_keys),
            encoding="utf-8",
        )

    # -- override point -------------------------------------------------------

    def _default(self) -> dict | list:  # noqa: PLR6301
        """Return the empty-state value for this store (dict by default)."""
        return {}
