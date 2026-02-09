"""Reverse history search (Ctrl+R) manager.

The :class:`ReverseSearchManager` encapsulates the five state variables and
all logic for the Ctrl+R reverse-i-search feature.  It communicates with
the Textual widget layer through two narrow callbacks injected at
construction time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Minimal protocols for the two collaborators
# ---------------------------------------------------------------------------


class PromptHistoryLike(Protocol):
    """Minimal interface used by reverse search on the history object."""

    @property
    def entry_count(self) -> int: ...
    def get_entry(self, index: int) -> str | None: ...
    def reverse_search_indices(self, query: str) -> list[int]: ...


class InputWidgetLike(Protocol):
    """Minimal interface for the chat-input widget."""

    text: str
    border_subtitle: str

    def clear(self) -> None: ...
    def insert(self, text: str) -> None: ...
    def focus(self) -> None: ...
    def _update_line_indicator(self) -> None: ...


class SearchBarLike(Protocol):
    """Minimal interface for the history-search-bar widget."""

    def show_search(
        self,
        *,
        query: str,
        match: str | None,
        index: int,
        total: int,
    ) -> None: ...

    def dismiss(self) -> None: ...


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ReverseSearchManager:
    """Manage Ctrl+R reverse-i-search state and transitions.

    Parameters
    ----------
    history:
        The :class:`PromptHistory` (or any object satisfying
        :class:`PromptHistoryLike`).
    get_input:
        Callable that returns the chat-input widget (may raise).
    get_search_bar:
        Callable that returns the history-search-bar widget (may raise).
    """

    def __init__(
        self,
        *,
        history: Any,
        get_input: Any,
        get_search_bar: Any,
    ) -> None:
        self._history: PromptHistoryLike = history
        self._get_input = get_input
        self._get_search_bar = get_search_bar

        # Owned state
        self.active: bool = False
        self.query: str = ""
        self.matches: list[int] = []
        self.match_idx: int = -1
        self.original: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, add_message: Any = None) -> None:
        """Begin a new reverse search session.

        If already active, cycles to the next match instead.

        Parameters
        ----------
        add_message:
            Optional callback to show "No prompt history" if history is empty.
        """
        if self._history.entry_count == 0:
            if add_message:
                add_message("No prompt history yet.")
            return

        if self.active:
            self.cycle_next()
            return

        input_widget = self._get_input()
        self.active = True
        self.query = ""
        self.matches = []
        self.match_idx = -1
        self.original = input_widget.text
        self.update_display()
        input_widget.focus()

    def handle_key(self, event: object) -> bool:
        """Handle a key press while reverse search is active.

        Returns ``True`` if the key was consumed (caller should
        ``prevent_default`` + ``stop``).  Returns ``False`` when
        search was accepted and the key should be handled normally.
        """
        key = getattr(event, "key", "")

        if key in ("escape", "ctrl+g"):
            self.cancel()
            return True

        if key in ("enter", "shift+enter"):
            self.accept()
            return True

        if key == "backspace":
            if self.query:
                self.query = self.query[:-1]
                self.do_search()
            return True

        if key == "ctrl+r":
            self.cycle_next()
            return True

        if key == "ctrl+s":
            self.cycle_prev()
            return True

        character = getattr(event, "character", None)
        is_printable = getattr(event, "is_printable", False)
        if character and is_printable:
            self.query += character
            self.do_search()
            return True

        # Any other key — accept result, fall through
        self.accept()
        return False

    def cycle_next(self) -> None:
        """Cycle to the next (older) match in the current result set."""
        if not self.matches:
            self.update_display()
            return
        self.match_idx = (self.match_idx + 1) % len(self.matches)
        entry = self._history.get_entry(self.matches[self.match_idx])
        if entry is not None:
            iw = self._get_input()
            iw.clear()
            iw.insert(entry)
        self.update_display()

    def cycle_prev(self) -> None:
        """Cycle to the previous (newer) match in the current result set."""
        if not self.matches:
            self.update_display()
            return
        self.match_idx = (self.match_idx - 1) % len(self.matches)
        entry = self._history.get_entry(self.matches[self.match_idx])
        if entry is not None:
            iw = self._get_input()
            iw.clear()
            iw.insert(entry)
        self.update_display()

    def do_search(self) -> None:
        """Execute a reverse search and display the best match."""
        iw = self._get_input()
        if not self.query:
            self.matches = []
            self.match_idx = -1
            iw.clear()
            iw.insert(self.original)
            self.update_display()
            return

        self.matches = self._history.reverse_search_indices(self.query)
        if self.matches:
            self.match_idx = 0
            entry = self._history.get_entry(self.matches[0])
            if entry is not None:
                iw.clear()
                iw.insert(entry)
        else:
            self.match_idx = -1
        self.update_display()

    def cancel(self) -> None:
        """Cancel reverse search and restore the original input."""
        self.active = False
        iw = self._get_input()
        iw.clear()
        iw.insert(self.original)
        self.clear_display()

    def accept(self) -> None:
        """Accept the current search result and exit search mode."""
        self.active = False
        self.clear_display()

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def update_display(self) -> None:
        """Show the search indicator in the dedicated search bar."""
        try:
            bar = self._get_search_bar()
            match_text: str | None = None
            if self.matches and self.match_idx >= 0:
                match_text = self._history.get_entry(self.matches[self.match_idx])
            bar.show_search(
                query=self.query,
                match=match_text,
                index=self.match_idx,
                total=len(self.matches),
            )
            iw = self._get_input()
            iw.border_subtitle = "(reverse-i-search active — Esc to cancel)"
        except Exception:
            pass

    def clear_display(self) -> None:
        """Hide the search bar and restore the line-count subtitle."""
        try:
            self._get_search_bar().dismiss()
        except Exception:
            pass
        try:
            self._get_input()._update_line_indicator()
        except Exception:
            pass
