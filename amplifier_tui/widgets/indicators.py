"""Status indicator and simple message widgets for Amplifier TUI."""

from __future__ import annotations

from textual.widgets import Static


class ProcessingIndicator(Static):
    """Animated indicator shown during processing."""

    pass


class ErrorMessage(Static):
    """An inline error message."""

    pass


class SystemMessage(Static):
    """A system/command output message (slash command results)."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message system-message")


class NoteMessage(Static):
    """A user annotation/note displayed as a sticky-note in the chat."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message note-message")


class FoldToggle(Static):
    """Clickable indicator to fold/unfold a long message."""

    def __init__(
        self, target: Static, line_count: int, *, folded: bool = False
    ) -> None:
        self._target = target
        self._line_count = line_count
        super().__init__(self._make_label(folded=folded), classes="fold-toggle")

    def _make_label(self, *, folded: bool) -> str:
        if folded:
            return f"\u25b6 \u00b7\u00b7\u00b7 {self._line_count} lines hidden (click to expand)"
        return f"\u25bc {self._line_count} lines (click to fold)"

    def on_click(self) -> None:
        folded = self._target.has_class("folded")
        if folded:
            self._target.remove_class("folded")
        else:
            self._target.add_class("folded")
        self.update(self._make_label(folded=not folded))
