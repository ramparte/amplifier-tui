"""Desktop display commands: wrap, fold, scroll, zoom."""

from __future__ import annotations

from PySide6.QtWidgets import QTextEdit


class DesktopDisplayCommandsMixin:
    """Qt-native display commands (override TUI equivalents)."""

    def _cmd_wrap(self, args: str = "") -> None:
        """Toggle or set word wrap on the chat display."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return
        display = app._current_display()
        if not display:
            self._add_system_message("No active chat display.")
            return

        arg = args.strip().lower()
        if arg in ("on", "yes", "true"):
            display.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self._add_system_message("Word wrap **enabled**.")
        elif arg in ("off", "no", "false"):
            display.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            self._add_system_message("Word wrap **disabled**.")
        elif arg == "":
            # Toggle
            current = display.lineWrapMode()
            if current == QTextEdit.LineWrapMode.NoWrap:
                display.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
                self._add_system_message("Word wrap **enabled**.")
            else:
                display.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
                self._add_system_message("Word wrap **disabled**.")
        else:
            self._add_system_message("Usage: /wrap [on|off]")

    def _cmd_fold(self, args: str = "") -> None:  # noqa: ARG002
        """Toggle collapsible sections (thinking blocks, tool calls)."""
        self._add_system_message(
            "Collapsible sections are not yet implemented in the desktop interface."
        )

    def _cmd_scroll(self, args: str = "") -> None:
        """Scroll control: 'top', 'bottom', or a line number."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return
        display = app._current_display()
        if not display:
            self._add_system_message("No active chat display.")
            return

        arg = args.strip().lower()
        sb = display.verticalScrollBar()
        if arg in ("bottom", "end", ""):
            sb.setValue(sb.maximum())
            self._add_system_message("Scrolled to bottom.")
        elif arg in ("top", "start"):
            sb.setValue(sb.minimum())
            self._add_system_message("Scrolled to top.")
        elif arg.isdigit():
            # Scroll to approximate position by fraction
            line = int(arg)
            total_blocks = display.document().blockCount()
            if total_blocks > 0:
                fraction = min(line / total_blocks, 1.0)
                sb.setValue(int(sb.maximum() * fraction))
            self._add_system_message(f"Scrolled to line ~{line}.")
        else:
            self._add_system_message("Usage: /scroll [top|bottom|<line>]")

    def _cmd_zoom(self, args: str = "") -> None:
        """Font size: 'in', 'out', 'reset', or specific size like '14'."""
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return

        arg = args.strip().lower()
        if arg == "in":
            app._zoom_in()
            self._add_system_message(f"Zoom in -> {app._font_size}pt")
        elif arg == "out":
            app._zoom_out()
            self._add_system_message(f"Zoom out -> {app._font_size}pt")
        elif arg == "reset":
            app._font_size = 14
            app._apply_font_size()
            self._add_system_message("Zoom reset to 14pt.")
        elif arg.isdigit():
            size = max(8, min(int(arg), 32))
            app._font_size = size
            app._apply_font_size()
            self._add_system_message(f"Font size set to {size}pt.")
        elif arg == "":
            self._add_system_message(
                f"Current font size: **{app._font_size}pt**\n"
                "Usage: /zoom [in|out|reset|<size>]"
            )
        else:
            self._add_system_message("Usage: /zoom [in|out|reset|<size>]")
