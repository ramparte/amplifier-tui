"""Pinned panel widgets for Amplifier TUI."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static


class PinnedPanelHeader(Static):
    """Header for the pinned panel. Click to collapse/expand."""

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "_toggle_pinned_panel"):
            app._toggle_pinned_panel()


class PinnedPanelItem(Static):
    """A single pinned message preview. Click to scroll to the original message."""

    def __init__(
        self, pin_number: int, msg_index: int, content: str, **kwargs: object
    ) -> None:
        super().__init__(content, **kwargs)
        self.pin_number = pin_number
        self.msg_index = msg_index

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "_scroll_to_pinned_message"):
            app._scroll_to_pinned_message(self.msg_index)


class PinnedPanel(Vertical):
    """Collapsible panel at top of chat showing pinned message previews."""

    pass
