"""Tool introspection commands (/tools)."""

from __future__ import annotations


class ToolCommandsMixin:
    """Mixin providing the /tools command for live tool introspection."""

    def _cmd_tools(self, args: str = "") -> None:
        """Show tool call log, statistics, or manage the log.

        Subcommands:
            /tools          Recent tool calls (same as /tools live)
            /tools live     Scrolling log of recent tool calls
            /tools log      Full session tool log
            /tools stats    Aggregate statistics
            /tools clear    Clear the tool log
        """
        sub = args.strip().lower()

        if not sub or sub == "live":
            log_text = self._tool_log.format_live_log(last_n=25)  # type: ignore[attr-defined]
            self._add_system_message(f"Live Tool Log:\n\n{log_text}")  # type: ignore[attr-defined]
            return

        if sub == "log":
            self._add_system_message(  # type: ignore[attr-defined]
                self._tool_log.format_full_log()  # type: ignore[attr-defined]
            )
            return

        if sub == "stats":
            self._add_system_message(  # type: ignore[attr-defined]
                self._tool_log.format_stats()  # type: ignore[attr-defined]
            )
            return

        if sub == "clear":
            self._tool_log.clear()  # type: ignore[attr-defined]
            self._add_system_message("Tool log cleared.")  # type: ignore[attr-defined]
            return

        self._add_system_message(  # type: ignore[attr-defined]
            "Usage: /tools [live|log|stats|clear]\n"
            "  /tools live   Recent tool calls (default)\n"
            "  /tools log    Full session tool log\n"
            "  /tools stats  Aggregate statistics\n"
            "  /tools clear  Clear log"
        )
