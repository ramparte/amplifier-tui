"""Session-notes persistence store."""

from __future__ import annotations

import json
from pathlib import Path

from ._base import JsonStore


class NoteStore(JsonStore):
    """Session notes keyed by session ID.

    On-disk format: ``{session_id: [note_dict, ...]}``
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load(self, session_id: str) -> list[dict]:
        """Load notes for *session_id* (defaults to ``"default"``)."""
        sid = session_id or "default"
        all_notes = self.load_raw()
        if isinstance(all_notes, dict):
            return all_notes.get(sid, [])
        return []

    def save(self, session_id: str, notes: list[dict]) -> None:
        """Persist *notes* for *session_id*, pruning to 50 sessions max."""
        sid = session_id or "default"
        try:
            all_notes: dict[str, list[dict]] = {}
            if self.path.exists():
                all_notes = json.loads(self.path.read_text(encoding="utf-8"))
            if notes:
                all_notes[sid] = notes
            elif sid in all_notes:
                del all_notes[sid]
            # Keep last 50 sessions worth of notes
            if len(all_notes) > 50:
                keys = list(all_notes.keys())
                for k in keys[:-50]:
                    del all_notes[k]
            self.save_raw(all_notes)
        except Exception:
            pass
