"""Command mixin for /dashboard command."""

from __future__ import annotations

from pathlib import Path


class DashboardCommandsMixin:
    """Mixin providing /dashboard command."""

    def _cmd_dashboard(self, args: str = "") -> None:  # type: ignore[override]
        """Handle /dashboard subcommands."""
        sub = args.strip().lower() if args else ""

        if not sub:
            if not self._dashboard_stats.is_cached:  # type: ignore[attr-defined]
                count = self._dashboard_stats.scan_sessions()  # type: ignore[attr-defined]
                self._add_system_message(f"[dim]Scanned {count} sessions.[/dim]")  # type: ignore[attr-defined]
            self._add_system_message(self._dashboard_stats.format_dashboard())  # type: ignore[attr-defined]
            return

        if sub == "refresh":
            count = self._dashboard_stats.scan_sessions()  # type: ignore[attr-defined]
            self._add_system_message(f"Rescanned {count} sessions.")  # type: ignore[attr-defined]
            self._add_system_message(self._dashboard_stats.format_dashboard())  # type: ignore[attr-defined]
            return

        if sub == "export":
            html = self._dashboard_stats.export_html()  # type: ignore[attr-defined]
            export_path = Path("dashboard.html")
            try:
                export_path.write_text(html)
                self._add_system_message(  # type: ignore[attr-defined]
                    f"Dashboard exported to [cyan]{export_path.resolve()}[/cyan]"
                )
            except OSError as e:
                self._add_system_message(f"[red]Export failed:[/red] {e}")  # type: ignore[attr-defined]
            return

        if sub == "heatmap":
            if not self._dashboard_stats.is_cached:  # type: ignore[attr-defined]
                self._dashboard_stats.scan_sessions()  # type: ignore[attr-defined]
            self._add_system_message(self._dashboard_stats.format_heatmap())  # type: ignore[attr-defined]
            return

        if sub == "summary":
            if not self._dashboard_stats.is_cached:  # type: ignore[attr-defined]
                self._dashboard_stats.scan_sessions()  # type: ignore[attr-defined]
            self._add_system_message(self._dashboard_stats.format_summary())  # type: ignore[attr-defined]
            return

        if sub == "clear":
            self._dashboard_stats.clear()  # type: ignore[attr-defined]
            self._add_system_message("Dashboard cache cleared.")  # type: ignore[attr-defined]
            return

        self._add_system_message(  # type: ignore[attr-defined]
            "Usage:\n"
            "  /dashboard            Show full dashboard\n"
            "  /dashboard refresh    Re-scan session data\n"
            "  /dashboard export     Export as HTML\n"
            "  /dashboard heatmap    Show activity heatmap only\n"
            "  /dashboard summary    Show summary stats only\n"
            "  /dashboard clear      Clear cached stats"
        )
