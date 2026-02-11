"""Session monitor panel commands (/monitor).

Displays a live-updating table of recent Amplifier sessions with their
current state, project, model, and an LLM-generated status summary.

Architecture
------------
* ``#monitor-panel`` is a :class:`~textual.containers.Vertical` in the
  DOM, hidden by default (``display: none`` in CSS).
* ``/monitor`` mounts a :class:`~textual.widgets.DataTable` and a header
  :class:`~textual.widgets.Static` into the panel, then starts two timers:

  - **fast** (2 s) -- calls :meth:`SessionScanner.scan` and refreshes the
    table.  This is pure filesystem reads, always instant.
  - **slow** (15 s) -- calls :meth:`SessionSummarizer.process_pending` to
    run queued LLM summarisations (haiku-class, ~$0.001 each).

* ``/monitor close`` stops timers, unmounts children, hides panel.
* ``/monitor big|small`` toggles panel height.
"""

from __future__ import annotations

import logging

from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Static

from amplifier_tui.features.session_scanner import SessionScanner
from amplifier_tui.features.session_summarizer import (
    SessionSummarizer,
    make_anthropic_summarizer,
)

logger = logging.getLogger(__name__)

# Column definitions: (key, label, width)
_COLUMNS: list[tuple[str, str, int | None]] = [
    ("state", "", 3),
    ("project", "Project", 18),
    ("model", "Model", 14),
    ("turns", "Turns", 6),
    ("age", "Age", 6),
    ("activity", "Status", None),  # None = auto / fill
]


class MonitorCommandsMixin:
    """Mixin providing the /monitor command (session monitor panel)."""

    _monitor_scanner: SessionScanner | None = None
    _monitor_summarizer: SessionSummarizer | None = None
    _monitor_fast_timer: Timer | None = None
    _monitor_slow_timer: Timer | None = None

    def _cmd_monitor(self, args: str = "") -> None:
        """Toggle or control the session monitor panel."""
        sub = args.strip().lower()
        if sub in ("", "toggle"):
            self._toggle_monitor_panel()
        elif sub == "close":
            self._close_monitor_panel()
        elif sub == "big":
            self._toggle_monitor_size(big=True)
        elif sub == "small":
            self._toggle_monitor_size(big=False)
        else:
            self._post_system(  # type: ignore[attr-defined]
                "Usage: /monitor [toggle|close|big|small]\n"
                "  (no args)  Toggle panel open/closed\n"
                "  close      Close panel and stop refresh\n"
                "  big        Expand panel (28 rows)\n"
                "  small      Shrink panel (16 rows)"
            )

    # -- Panel lifecycle ----------------------------------------------------

    def _toggle_monitor_panel(self) -> None:
        try:
            panel: Vertical = self.query_one("#monitor-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        if panel.has_class("visible"):
            self._close_monitor_panel()
        else:
            self._open_monitor_panel()

    def _open_monitor_panel(self) -> None:
        try:
            panel: Vertical = self.query_one("#monitor-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        if panel.has_class("visible"):
            return

        # Clear any stale children.
        try:
            for child in list(panel.children):
                child.remove()
        except Exception:
            pass

        # Build scanner + summarizer on first open.
        if self._monitor_scanner is None:
            self._monitor_scanner = SessionScanner()
        if self._monitor_summarizer is None:
            summarize_fn = make_anthropic_summarizer()
            self._monitor_summarizer = SessionSummarizer(
                self._monitor_scanner, summarize_fn=summarize_fn
            )

        # Mount header + table.
        header = Static(
            " Session Monitor (/monitor close to exit, /monitor big|small to resize)",
            classes="monitor-header",
        )
        table = DataTable(id="monitor-table", cursor_type="row", zebra_stripes=True)
        panel.mount(header)
        panel.mount(table)

        # Configure columns.
        for key, label, width in _COLUMNS:
            if width is not None:
                table.add_column(label, key=key, width=width)
            else:
                table.add_column(label, key=key)

        # Initial scan.
        self._refresh_monitor_table()

        # Start timers.
        self._monitor_fast_timer = self.set_interval(  # type: ignore[attr-defined]
            2.0, self._refresh_monitor_table
        )
        self._monitor_slow_timer = self.set_interval(  # type: ignore[attr-defined]
            15.0, self._process_monitor_summaries
        )

        panel.add_class("visible")

    def _close_monitor_panel(self) -> None:
        # Stop timers first.
        if self._monitor_fast_timer is not None:
            self._monitor_fast_timer.stop()
            self._monitor_fast_timer = None
        if self._monitor_slow_timer is not None:
            self._monitor_slow_timer.stop()
            self._monitor_slow_timer = None

        try:
            panel: Vertical = self.query_one("#monitor-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        panel.remove_class("visible")
        try:
            for child in list(panel.children):
                child.remove()
        except Exception:
            pass

    def _toggle_monitor_size(self, *, big: bool) -> None:
        try:
            panel: Vertical = self.query_one("#monitor-panel", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return

        if not panel.has_class("visible"):
            self._open_monitor_panel()

        if big:
            panel.add_class("monitor-large")
        else:
            panel.remove_class("monitor-large")

    # -- Table refresh ------------------------------------------------------

    def _refresh_monitor_table(self) -> None:
        """Scan sessions and update the DataTable."""
        if self._monitor_summarizer is None:
            return

        try:
            table: DataTable = self.query_one("#monitor-table", DataTable)  # type: ignore[attr-defined]
        except Exception:
            return

        sessions = self._monitor_summarizer.scan(limit=10)

        # Clear and rebuild rows.  DataTable doesn't support in-place row
        # updates without row keys, and with only ~10 rows the cost is nil.
        table.clear()

        for s in sessions:
            icon = SessionScanner.state_icon(s.state)
            color = SessionScanner.state_color(s.state)
            age = SessionScanner.format_age(s.age_seconds)

            # Model: abbreviate for space.
            model = s.model
            if model.startswith("claude-"):
                model = model.replace("claude-", "c-")
            if len(model) > 14:
                model = model[:13] + "\u2026"

            # Activity: use state-colored text.
            activity = s.activity or ""
            if len(activity) > 60:
                activity = activity[:59] + "\u2026"

            state_cell = f"[{color}]{icon}[/{color}]"
            project_cell = s.project[:18] if len(s.project) > 18 else s.project

            table.add_row(
                state_cell,
                project_cell,
                model,
                str(s.turn_count),
                age,
                f"[{color}]{activity}[/{color}]",
                key=s.session_id,
            )

    def _process_monitor_summaries(self) -> None:
        """Process pending LLM summarizations (slow timer)."""
        if self._monitor_summarizer is None:
            return

        try:
            processed = self._monitor_summarizer.process_pending(max_count=3)
            if processed > 0:
                # Immediately refresh to show new summaries.
                self._refresh_monitor_table()
        except Exception:
            logger.debug("Monitor summary processing failed", exc_info=True)
