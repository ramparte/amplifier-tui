"""Persistent prompt history with Up/Down browsing and search."""

from __future__ import annotations

from pathlib import Path


class PromptHistory:
    """Persistent prompt history stored as one entry per line.

    Supports Up/Down arrow browsing (like a shell) and substring search.
    Multiline prompts are flattened to a single line for storage.
    """

    HISTORY_FILE = Path.home() / ".amplifier" / "tui-history.txt"
    MAX_ENTRIES = 500

    def __init__(self) -> None:
        self._entries: list[str] = []  # oldest first
        self._cursor: int = -1  # -1 means "not browsing"
        self._draft: str = ""  # saves current input when browsing starts
        self._load()

    def _load(self) -> None:
        """Load history from disk."""
        if self.HISTORY_FILE.exists():
            try:
                lines = self.HISTORY_FILE.read_text().splitlines()
                self._entries = [line for line in lines if line.strip()][
                    -self.MAX_ENTRIES :
                ]
            except OSError:
                self._entries = []

    def _save(self) -> None:
        """Save history to disk."""
        try:
            self.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.HISTORY_FILE.write_text(
                "\n".join(self._entries[-self.MAX_ENTRIES :]) + "\n"
            )
        except OSError:
            pass  # Non-fatal: history is a convenience feature

    @property
    def is_browsing(self) -> bool:
        """True when the user is navigating history with Up/Down."""
        return self._cursor != -1

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def add(self, prompt: str) -> None:
        """Add a prompt to history (deduplicates, skips slash commands)."""
        # Flatten multiline to single line
        prompt = " ".join(prompt.split())
        if not prompt or prompt.startswith("/"):
            # Always reset browsing state even for skipped prompts
            self._cursor = -1
            self._draft = ""
            return
        # Remove previous occurrence so most recent position wins
        self._entries = [e for e in self._entries if e != prompt]
        self._entries.append(prompt)
        self._entries = self._entries[-self.MAX_ENTRIES :]
        self._cursor = -1
        self._draft = ""
        self._save()

    def start_browse(self, current_text: str) -> None:
        """Begin browsing history. Saves the current input as a draft."""
        self._draft = current_text
        self._cursor = len(self._entries)  # one past the end

    def previous(self) -> str | None:
        """Move back in history (Up arrow).

        Returns the entry text, or None if already at the oldest entry.
        Caller must call start_browse() first if not already browsing.
        """
        if not self._entries or self._cursor == -1:
            return None
        if self._cursor > 0:
            self._cursor -= 1
            return self._entries[self._cursor]
        return None  # Already at oldest

    def next(self) -> str | None:
        """Move forward in history (Down arrow).

        Returns the next entry, the saved draft when reaching the end,
        or None if not currently browsing.
        """
        if self._cursor == -1:
            return None
        self._cursor += 1
        if self._cursor >= len(self._entries):
            self._cursor = -1
            return self._draft
        return self._entries[self._cursor]

    def search(self, query: str) -> list[str]:
        """Search history for entries containing query (most recent first)."""
        if not query:
            return list(reversed(self._entries[-20:]))
        q = query.lower()
        return [e for e in reversed(self._entries) if q in e.lower()][:20]

    def reset_browse(self) -> None:
        """Reset browsing state."""
        self._cursor = -1
        self._draft = ""
