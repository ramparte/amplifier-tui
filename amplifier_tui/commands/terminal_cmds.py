"""Embedded terminal panel commands (/terminal)."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static


# Feature gate: only available if pyte is installed
try:
    from amplifier_tui.widgets.terminal import TERMINAL_AVAILABLE, Terminal
except Exception:
    TERMINAL_AVAILABLE = False
    Terminal = None  # type: ignore[assignment,misc]


class TerminalCommandsMixin:
    """Mixin providing the /terminal command (embedded terminal panel)."""

    _terminal_widget: object | None = None  # Terminal instance when active

    def _cmd_terminal(self, args: str = "") -> None:
        """Toggle or control the embedded terminal panel."""
        if not TERMINAL_AVAILABLE:
            self._post_system(  # type: ignore[attr-defined]
                "Embedded terminal not available.\n"
                "Install pyte: pip install pyte\n"
                "Then restart the TUI."
            )
            return

        sub = args.strip().lower()
        if sub in ("", "toggle"):
            self._toggle_terminal_panel()
        elif sub == "close":
            self._close_terminal_panel()
        elif sub == "big":
            self._toggle_terminal_size(big=True)
        elif sub == "small":
            self._toggle_terminal_size(big=False)
        else:
            self._post_system(  # type: ignore[attr-defined]
                "Usage: /terminal [toggle|close|big|small]\n"
                "  (no args)  Toggle panel open/closed\n"
                "  close      Close panel and stop shell\n"
                "  big        Expand panel to 24 rows\n"
                "  small      Shrink panel to 12 rows"
            )

    def _toggle_terminal_panel(self) -> None:
        """Toggle the terminal panel visibility."""
        try:
            panel: Vertical = self.query_one("#terminal-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        if panel.has_class("visible"):
            self._close_terminal_panel()
        else:
            self._open_terminal_panel()

    def _open_terminal_panel(self) -> None:
        """Open the terminal panel and start a shell."""
        try:
            panel: Vertical = self.query_one("#terminal-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        if not panel.has_class("visible"):
            # Mount the terminal widget if not already there
            if self._terminal_widget is None or not self._terminal_widget.is_running:
                # Clear old widget if it exists
                try:
                    for child in list(panel.children):
                        child.remove()
                except Exception:
                    pass

                header = Static(
                    " Terminal (Ctrl+F1 to release focus, /terminal close to exit)",
                    classes="terminal-header",
                )
                self._terminal_widget = Terminal(id="embedded-terminal")
                panel.mount(header)
                panel.mount(self._terminal_widget)
                self._terminal_widget.start()

            panel.add_class("visible")
            self._terminal_widget.focus()  # type: ignore[union-attr]

    def _close_terminal_panel(self) -> None:
        """Close the terminal panel and stop the shell."""
        try:
            panel: Vertical = self.query_one("#terminal-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        # Move focus away BEFORE stopping (prevents Textual focus deadlock)
        try:
            chat_input = self.query_one("ChatInput")  # type: ignore[attr-defined]
            chat_input.focus()
        except Exception:
            pass

        panel.remove_class("visible")
        if self._terminal_widget is not None:
            try:
                self._terminal_widget.stop()
            except Exception:
                pass
            self._terminal_widget = None
        # Clear panel children
        try:
            for child in list(panel.children):
                child.remove()
        except Exception:
            pass

    def _toggle_terminal_size(self, *, big: bool) -> None:
        """Toggle terminal panel between small (12 rows) and big (24 rows)."""
        try:
            panel: Vertical = self.query_one("#terminal-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        if not panel.has_class("visible"):
            self._open_terminal_panel()

        if big:
            panel.add_class("terminal-large")
        else:
            panel.remove_class("terminal-large")

    def on_terminal_stopped(self, event: object) -> None:
        """Handle terminal command exit -- close the panel."""
        self._close_terminal_panel()
