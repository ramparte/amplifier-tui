"""Search and suggestion bar widgets for Amplifier TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Static


class SuggestionBar(Static):
    """Thin bar below input showing the current smart prompt suggestion."""

    def __init__(self) -> None:
        super().__init__("", id="suggestion-bar")
        self._suggestions: list[str] = []
        self._index: int = 0

    @property
    def has_suggestions(self) -> bool:
        return len(self._suggestions) > 0

    def set_suggestions(self, suggestions: list[str]) -> None:
        """Replace the suggestion list and reset the cycle index."""
        self._suggestions = suggestions
        self._index = 0
        self._render_bar()

    def accept_current(self) -> str | None:
        """Return the currently highlighted suggestion (Tab press)."""
        if not self._suggestions:
            return None
        return self._suggestions[self._index]

    def cycle_next(self) -> str | None:
        """Advance to the next suggestion and return it."""
        if not self._suggestions:
            return None
        self._index = (self._index + 1) % len(self._suggestions)
        self._render_bar()
        return self._suggestions[self._index]

    def dismiss(self) -> None:
        """Hide the suggestion bar."""
        self._suggestions = []
        self._index = 0
        self._render_bar()

    def _render_bar(self) -> None:
        if not self._suggestions:
            self.display = False
            return
        self.display = True
        current = self._suggestions[self._index]
        total = len(self._suggestions)
        if total == 1:
            self.update(f"[dim]Tab \u2192 {current}[/dim]")
        else:
            self.update(f"[dim]Tab \u2192 {current}  ({self._index + 1}/{total})[/dim]")


class HistorySearchBar(Static):
    """Thin bar below input showing the reverse-i-search state.

    Visible only while Ctrl+R reverse search is active.  Displays the
    current query and matched history entry in a visually distinct style.
    """

    def __init__(self) -> None:
        super().__init__("", id="history-search-bar")

    def show_search(
        self,
        query: str,
        match: str | None,
        index: int,
        total: int,
    ) -> None:
        """Update the bar with the current search state."""
        q_display = f"'{query}'" if query else ""
        if match is not None and total > 0:
            counter = f"[{index + 1}/{total}]"
            # Truncate long matches to keep the bar single-line
            max_len = 80
            display_match = (
                match if len(match) <= max_len else match[:max_len] + "\u2026"
            )
            self.update(
                f"[bold #e5c07b](reverse-i-search)[/bold #e5c07b]"
                f"[#e5c07b]{q_display}[/#e5c07b]"
                f"[dim]: {display_match}  {counter}[/dim]"
            )
        elif query:
            self.update(
                f"[bold #e5c07b](reverse-i-search)[/bold #e5c07b]"
                f"[#e5c07b]{q_display}[/#e5c07b]"
                f"[dim #e06c75]  [no matches][/dim #e06c75]"
            )
        else:
            self.update(
                "[bold #e5c07b](reverse-i-search)[/bold #e5c07b]"
                "[dim]  type to search history \u00b7 Ctrl+R next \u00b7 Enter accept \u00b7 Esc cancel[/dim]"
            )
        self.display = True

    def dismiss(self) -> None:
        """Hide the search bar."""
        self.display = False
        self.update("")


class FindBar(Horizontal):
    """Inline search bar for finding text in chat (Ctrl+F)."""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Find in chat\u2026", id="find-input")
        yield Static("Aa", id="find-case-btn", classes="find-btn")
        yield Static("\u25b2", id="find-prev-btn", classes="find-btn")
        yield Static("\u25bc", id="find-next-btn", classes="find-btn")
        yield Static("0/0", id="find-count")
        yield Static("\u2715", id="find-close-btn", classes="find-btn")

    def on_click(self, event) -> None:
        """Route clicks on the inline buttons."""
        target = event.widget
        if hasattr(target, "id"):
            if target.id == "find-close-btn":
                self.app._hide_find_bar()
            elif target.id == "find-prev-btn":
                self.app._find_prev()
            elif target.id == "find-next-btn":
                self.app._find_next()
            elif target.id == "find-case-btn":
                self.app._find_toggle_case()
