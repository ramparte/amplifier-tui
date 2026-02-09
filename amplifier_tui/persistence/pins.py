"""Message-pin persistence store."""

from __future__ import annotations

import json
from pathlib import Path

from ._base import JsonStore


class MessagePinStore(JsonStore):
    """Pinned messages keyed by session ID.

    On-disk format: ``{session_id: [pin_dict, ...]}``
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load(self, session_id: str) -> list[dict]:
        """Load pins for *session_id* (defaults to ``"default"``)."""
        sid = session_id or "default"
        all_pins = self.load_raw()
        if isinstance(all_pins, dict):
            return all_pins.get(sid, [])
        return []

    def save(self, session_id: str, pins: list[dict]) -> None:
        """Persist *pins* for *session_id*, pruning to 50 sessions max."""
        sid = session_id or "default"
        try:
            all_pins: dict[str, list[dict]] = {}
            if self.path.exists():
                all_pins = json.loads(self.path.read_text(encoding="utf-8"))
            if pins:
                all_pins[sid] = pins
            elif sid in all_pins:
                del all_pins[sid]
            # Keep last 50 sessions worth of pins
            if len(all_pins) > 50:
                keys = list(all_pins.keys())
                for k in keys[:-50]:
                    del all_pins[k]
            self.save_raw(all_pins)
        except Exception:
            pass
