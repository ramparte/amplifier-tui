"""Draft persistence store."""

from __future__ import annotations

from pathlib import Path

from ._base import JsonStore
from ..log import logger


class DraftStore(JsonStore):
    """Input drafts (``{session_id: {text, timestamp, preview}}``)."""

    def __init__(self, path: Path, crash_path: Path) -> None:
        super().__init__(path)
        self.crash_path = crash_path

    def load(self) -> dict:
        """Load all drafts from disk."""
        return self.load_raw()  # type: ignore[return-value]

    def save_all(self, drafts: dict) -> None:
        """Persist the full drafts dict to disk."""
        self.save_raw(drafts)

    def remove(self, session_id: str) -> None:
        """Remove a single session's draft."""
        try:
            drafts = self.load()
            if session_id in drafts:
                del drafts[session_id]
                self.save_all(drafts)
        except OSError:
            logger.debug(
                "failed to remove draft for session %s", session_id, exc_info=True
            )

    # -- crash-recovery draft -------------------------------------------------

    def save_crash(self, text: str) -> None:
        """Write *text* to the crash-recovery file (plain text, not JSON)."""
        try:
            if text:
                self.crash_path.parent.mkdir(parents=True, exist_ok=True)
                self.crash_path.write_text(text)
            elif self.crash_path.exists():
                self.crash_path.unlink()
        except OSError:
            logger.debug("failed to save crash-recovery draft", exc_info=True)

    def load_crash(self) -> str | None:
        """Load crash-recovery draft if it exists and is non-empty."""
        try:
            if self.crash_path.exists():
                text = self.crash_path.read_text().strip()
                if text:
                    return text
        except OSError:
            logger.debug("failed to load crash-recovery draft", exc_info=True)
        return None

    def clear_crash(self) -> None:
        """Clear the crash-recovery draft file."""
        try:
            if self.crash_path.exists():
                self.crash_path.unlink()
        except OSError:
            logger.debug("failed to clear crash-recovery draft", exc_info=True)
