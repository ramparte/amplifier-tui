"""Desktop session/tab commands: split, tabs, close, rename."""

from __future__ import annotations


class DesktopSessionCommandsMixin:
    """Qt-native tab management commands."""

    def _cmd_split(self, args: str = "") -> None:  # noqa: ARG002
        """Open a new tab (duplicating the current conversation context)."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return
        app._new_tab()
        self._add_system_message("Opened new tab.")

    def _cmd_tabs(self, args: str = "") -> None:  # noqa: ARG002
        """List all open tabs with their conversation IDs."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return

        if not app._tabs:
            self._add_system_message("No tabs open.")
            return

        current = app._tab_widget.currentIndex()
        lines = ["**Open Tabs:**"]
        for i, tab in enumerate(app._tabs):
            marker = " *" if i == current else "  "
            cid_short = tab.tab_id[:8] if tab.tab_id else "---"
            lines.append(f"{marker} {i + 1}. {tab.name}  ({cid_short})")
        self._add_system_message("\n".join(lines))

    def _cmd_close(self, args: str = "") -> None:
        """Close the current tab (or tab N)."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return

        if app._tab_widget.count() <= 1:
            self._add_system_message("Cannot close the last tab.")
            return

        arg = args.strip()
        if arg.isdigit():
            index = int(arg) - 1  # 1-based for user
            if 0 <= index < app._tab_widget.count():
                app._close_tab(index)
                self._add_system_message(f"Closed tab {int(arg)}.")
            else:
                self._add_system_message(
                    f"Invalid tab number. Use 1-{app._tab_widget.count()}."
                )
        else:
            index = app._tab_widget.currentIndex()
            app._close_tab(index)
            self._add_system_message("Closed current tab.")

    def _cmd_rename(self, args: str = "") -> None:
        """Rename the current tab."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return

        new_name = args.strip()
        if not new_name:
            self._add_system_message("Usage: /rename <new tab name>")
            return

        index = app._tab_widget.currentIndex()
        if 0 <= index < len(app._tabs):
            app._tabs[index].name = new_name
            app._tab_widget.setTabText(index, new_name)
            self._add_system_message(f"Tab renamed to **{new_name}**.")
        else:
            self._add_system_message("No active tab to rename.")
