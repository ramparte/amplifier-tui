"""Tab bar widgets for Amplifier TUI."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.widgets import Static


class TabButton(Static):
    """A clickable tab label in the tab bar."""

    def __init__(self, label: str, tab_index: int, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.tab_index = tab_index

    def on_click(self) -> None:
        self.app._switch_to_tab(self.tab_index)


class TabBar(Horizontal):
    """Horizontal tab bar showing conversation tabs."""

    def update_tabs(
        self,
        tabs: list,
        active_index: int,
        split_left: int | None = None,
        split_right: int | None = None,
    ) -> None:
        """Rebuild the tab bar buttons."""
        self.remove_children()
        for i, tab in enumerate(tabs):
            label = tab.custom_name or tab.name
            # Mark split panes in tab bar
            if split_left is not None and i == split_left:
                label = f"\u25e7 {label}"
            elif split_right is not None and i == split_right:
                label = f"\u25e8 {label}"
            cls = "tab-btn tab-active" if i == active_index else "tab-btn tab-inactive"
            if i == split_left or i == split_right:
                cls += " tab-in-split"
            btn = TabButton(f" {label} ", tab_index=i, classes=cls)
            self.mount(btn)
        # Hide tab bar when there's only one tab
        if len(tabs) <= 1:
            self.add_class("single-tab")
        else:
            self.remove_class("single-tab")
