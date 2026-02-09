"""URL/reference collector persistence store."""

from __future__ import annotations

from pathlib import Path

from ._base import JsonStore
from ..log import logger


class RefStore(JsonStore):
    """URL/reference collector (``{session_id: [ref_dict, ...]}``)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load_all(self) -> dict[str, list[dict]]:
        """Load the full refs dict from disk."""
        return self.load_raw()  # type: ignore[return-value]

    def save(self, session_id: str, refs: list[dict]) -> None:
        """Persist *refs* for *session_id*."""
        try:
            all_refs = self.load_all()
            all_refs[session_id] = refs
            self.save_raw(all_refs)
        except OSError:
            logger.debug(
                "failed to save refs for session %s", session_id, exc_info=True
            )

    def for_session(self, session_id: str | None) -> list[dict]:
        """Return refs for a single session (empty list if none)."""
        if not session_id:
            return []
        return self.load_all().get(session_id, [])
