"""Desktop search commands: find, grep."""

from __future__ import annotations

from PySide6.QtWidgets import QTextEdit


class DesktopSearchCommandsMixin:
    """Qt-native search commands."""

    def _cmd_find(self, args: str = "") -> None:
        """Show the find bar or search directly for a term."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return

        query = args.strip()
        if query:
            # Search directly in the current display
            display = app._current_display()
            if display:
                app._find_bar.show_bar()
                app._find_bar._input.setText(query)
                found = display.find(query)
                if found:
                    self._add_system_message(f"Found: **{query}**")
                else:
                    self._add_system_message(f"Not found: **{query}**")
            else:
                self._add_system_message("No active chat display.")
        else:
            # Just show the find bar (Ctrl+F equivalent)
            app._show_find()

    def _cmd_grep(self, args: str = "") -> None:
        """Search across all open tabs for a pattern."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return

        pattern = args.strip()
        if not pattern:
            self._add_system_message("Usage: /grep <search pattern>")
            return

        matches: list[str] = []
        for i in range(app._tab_widget.count()):
            widget = app._tab_widget.widget(i)
            if not isinstance(widget, QTextEdit):
                continue
            text = widget.toPlainText()
            tab_name = app._tab_widget.tabText(i)
            # Count occurrences
            count = text.lower().count(pattern.lower())
            if count > 0:
                matches.append(f"  **{tab_name}**: {count} match(es)")

        if matches:
            header = f"Search results for **{pattern}**:\n"
            self._add_system_message(header + "\n".join(matches))
        else:
            self._add_system_message(f"No matches for **{pattern}** in any tab.")
