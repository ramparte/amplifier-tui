"""Session dashboard stats engine.

Aggregates data from Amplifier session files and generates
text-based visualizations using Unicode block/braille characters.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class SessionRecord:
    """Parsed metadata from a single session."""

    session_id: str = ""
    project: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float = 0
    model: str = ""
    turn_count: int = 0
    token_count: int = 0
    tools_used: list[str] = field(default_factory=list)
    commands_used: list[str] = field(default_factory=list)


@dataclass
class DashboardData:
    """Aggregated dashboard statistics."""

    sessions: list[SessionRecord] = field(default_factory=list)
    total_sessions: int = 0
    total_tokens: int = 0
    total_duration_seconds: float = 0
    avg_duration_seconds: float = 0
    # Hour x Weekday activity: {(hour, weekday): count}
    activity_grid: dict[tuple[int, int], int] = field(default_factory=dict)
    # Top commands: {command: count}
    command_counts: Counter = field(default_factory=Counter)
    # Models used: {model: count}
    model_counts: Counter = field(default_factory=Counter)
    # Projects: {project: session_count}
    project_counts: Counter = field(default_factory=Counter)
    # Daily token counts: {date_str: tokens}
    daily_tokens: dict[str, int] = field(default_factory=dict)
    # Streak info
    streak_days: int = 0
    longest_streak: int = 0
    # Computed at aggregation
    computed_at: datetime | None = None


class DashboardStats:
    """Aggregates session data and generates visualizations."""

    DEFAULT_SESSION_DIR = Path.home() / ".amplifier" / "projects"

    def __init__(self, session_dir: Path | None = None) -> None:
        self._session_dir = session_dir or self.DEFAULT_SESSION_DIR
        self._data: DashboardData = DashboardData()
        self._cached: bool = False

    @property
    def data(self) -> DashboardData:
        return self._data

    @property
    def is_cached(self) -> bool:
        return self._cached

    def scan_sessions(self) -> int:
        """Scan session directories and aggregate statistics.

        Returns the number of sessions found.
        """
        sessions: list[SessionRecord] = []

        if self._session_dir.exists():
            # Look for session-info.json files
            for info_file in self._session_dir.rglob("session-info.json"):
                record = self._parse_session_info(info_file)
                if record:
                    sessions.append(record)

            # Also look for metadata.json (Amplifier's actual format)
            for info_file in self._session_dir.rglob("metadata.json"):
                record = self._parse_session_info(info_file)
                if record:
                    sessions.append(record)

        self._aggregate(sessions)
        self._cached = True
        return len(sessions)

    def load_from_records(self, records: list[SessionRecord]) -> None:
        """Load from pre-built records (useful for testing)."""
        self._aggregate(records)
        self._cached = True

    def _parse_session_info(self, path: Path) -> SessionRecord | None:
        """Parse a session-info.json or metadata.json file into a SessionRecord."""
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        record = SessionRecord(
            session_id=data.get("session_id", ""),
            project=(
                data.get("project_id", "")
                or data.get("project", "")
                or path.parent.parent.parent.name
            ),
        )

        # Parse timestamps — try multiple field names
        started = (
            data.get("started_at", "")
            or data.get("created_at", "")
            or data.get("created", "")
        )
        if started:
            try:
                record.started_at = datetime.fromisoformat(
                    started.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        ended = data.get("ended_at", "") or data.get("completed_at", "")
        if ended:
            try:
                record.ended_at = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Duration
        if record.started_at and record.ended_at:
            record.duration_seconds = (
                record.ended_at - record.started_at
            ).total_seconds()
        else:
            record.duration_seconds = data.get("duration_seconds", 0) or data.get(
                "duration", 0
            )

        # Model
        record.model = data.get("model", "") or data.get("provider", "") or ""

        # Counts
        record.turn_count = data.get("turn_count", 0) or data.get("turns", 0)
        record.token_count = (
            data.get("token_count", 0)
            or data.get("tokens", 0)
            or data.get("total_tokens", 0)
        )

        # Tools and commands
        record.tools_used = data.get("tools_used", []) or []
        record.commands_used = data.get("commands_used", []) or []

        return record

    def _aggregate(self, sessions: list[SessionRecord]) -> None:
        """Aggregate session records into dashboard data."""
        data = DashboardData()
        data.sessions = sessions
        data.total_sessions = len(sessions)
        data.computed_at = datetime.now()

        active_dates: set[str] = set()

        for s in sessions:
            data.total_tokens += s.token_count
            data.total_duration_seconds += s.duration_seconds

            # Activity grid (hour x weekday)
            if s.started_at:
                hour = s.started_at.hour
                weekday = s.started_at.weekday()  # 0=Mon, 6=Sun
                key = (hour, weekday)
                data.activity_grid[key] = data.activity_grid.get(key, 0) + 1

                date_str = s.started_at.strftime("%Y-%m-%d")
                active_dates.add(date_str)

                # Daily tokens
                data.daily_tokens[date_str] = (
                    data.daily_tokens.get(date_str, 0) + s.token_count
                )

            # Commands
            for cmd in s.commands_used:
                data.command_counts[cmd] += 1

            # Models
            if s.model:
                data.model_counts[s.model] += 1

            # Projects
            if s.project:
                data.project_counts[s.project] += 1

        # Average duration
        if data.total_sessions > 0:
            data.avg_duration_seconds = (
                data.total_duration_seconds / data.total_sessions
            )

        # Streak calculation
        if active_dates:
            sorted_dates = sorted(active_dates)
            data.streak_days, data.longest_streak = self._calculate_streaks(
                sorted_dates
            )

        self._data = data

    def _calculate_streaks(self, sorted_dates: list[str]) -> tuple[int, int]:
        """Calculate current and longest streaks from sorted date strings.

        Returns (current_streak, longest_streak).
        """
        if not sorted_dates:
            return 0, 0

        dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in sorted_dates]

        # Calculate longest streak
        longest = 1
        current = 1
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                current += 1
                longest = max(longest, current)
            elif (dates[i] - dates[i - 1]).days > 1:
                current = 1
        longest = max(longest, current)

        # Current streak (from today backwards)
        today = datetime.now().date()
        current_streak = 0
        check_date = today
        date_set = set(dates)
        while check_date in date_set:
            current_streak += 1
            check_date -= timedelta(days=1)
        # Also check if yesterday counts (session might not have started today yet)
        if current_streak == 0:
            check_date = today - timedelta(days=1)
            while check_date in date_set:
                current_streak += 1
                check_date -= timedelta(days=1)

        return current_streak, longest

    def format_heatmap(self) -> str:
        """Format activity heatmap as text using block characters.

        Rows = hours (0-23), Columns = days (Mon-Sun)
        """
        data = self._data
        if not data.activity_grid:
            return "[dim]No activity data available.[/dim]"

        # Block characters by intensity
        BLOCKS = [" ", "░", "▒", "▓", "█"]

        max_count = max(data.activity_grid.values()) if data.activity_grid else 1

        lines = ["[bold]Activity Heatmap[/bold] (hour x day)"]
        lines.append("")
        lines.append("       Mon Tue Wed Thu Fri Sat Sun")

        for hour in range(24):
            row = f"  {hour:02d}:  "
            for weekday in range(7):
                count = data.activity_grid.get((hour, weekday), 0)
                if count == 0:
                    row += " ·  "
                else:
                    intensity = min(4, int((count / max_count) * 4))
                    block = BLOCKS[intensity]
                    row += f" {block}  "
            lines.append(row)

        # Legend
        lines.append("")
        legend = "· = none  ░ = low  ▒ = medium  ▓ = high  █ = peak"
        lines.append(f"  [dim]{legend}[/dim]")

        return "\n".join(lines)

    def format_bar_chart(
        self,
        counter: Counter,  # type: ignore[type-arg]
        title: str,
        max_bars: int = 8,
        bar_width: int = 20,
    ) -> str:
        """Format a counter as a horizontal bar chart."""
        if not counter:
            return f"[dim]No {title.lower()} data.[/dim]"

        top = counter.most_common(max_bars)
        if not top:
            return f"[dim]No {title.lower()} data.[/dim]"

        max_val = top[0][1]
        max_label_len = max(len(str(k)) for k, _ in top)

        lines = [f"[bold]{title}[/bold]"]
        lines.append("")

        for name, count in top:
            bar_len = int((count / max_val) * bar_width) if max_val > 0 else 0
            bar = "█" * bar_len + "░" * (bar_width - bar_len)
            lines.append(f"  {str(name):<{max_label_len}} {bar} {count}")

        return "\n".join(lines)

    def format_sparkline(self, max_points: int = 30) -> str:
        """Format daily token usage as a sparkline."""
        data = self._data
        if not data.daily_tokens:
            return "[dim]No token data available.[/dim]"

        SPARKS = "▁▂▃▄▅▆▇█"

        # Get last N days of data
        sorted_dates = sorted(data.daily_tokens.keys())[-max_points:]
        values = [data.daily_tokens[d] for d in sorted_dates]

        if not values:
            return "[dim]No token data.[/dim]"

        max_val = max(values) if values else 1
        min_val = min(values) if values else 0
        range_val = max_val - min_val if max_val != min_val else 1

        spark = ""
        for v in values:
            idx = min(
                len(SPARKS) - 1, int(((v - min_val) / range_val) * (len(SPARKS) - 1))
            )
            spark += SPARKS[idx]

        lines = [
            "[bold]Token Usage (daily)[/bold]",
            "",
            f"  {spark}",
            f"  [dim]{sorted_dates[0]} → {sorted_dates[-1]}[/dim]",
            f"  [dim]Range: {min_val:,} - {max_val:,} tokens/day[/dim]",
        ]

        return "\n".join(lines)

    def format_summary(self) -> str:
        """Format summary statistics."""
        data = self._data

        # Format duration
        avg_mins = data.avg_duration_seconds / 60
        total_hours = data.total_duration_seconds / 3600

        lines = [
            "[bold]Summary Statistics[/bold]",
            "",
            f"  Total sessions:    {data.total_sessions:,}",
            f"  Total tokens:      {data.total_tokens:,}",
            f"  Total time:        {total_hours:.1f} hours",
            f"  Avg session:       {avg_mins:.1f} minutes",
            f"  Current streak:    {data.streak_days} days",
            f"  Longest streak:    {data.longest_streak} days",
        ]

        return "\n".join(lines)

    def format_dashboard(self) -> str:
        """Format the complete dashboard."""
        data = self._data

        if not data.sessions and not self._cached:
            return (
                "[dim]No session data loaded.[/dim]\n\n"
                "Use /dashboard refresh to scan session files."
            )

        if not data.sessions:
            return (
                "[dim]No sessions found.[/dim]\n\n"
                f"Searched: {self._session_dir}\n"
                "Make sure you have Amplifier sessions in ~/.amplifier/projects/"
            )

        sections = []

        # Summary
        sections.append(self.format_summary())

        # Heatmap
        sections.append(self.format_heatmap())

        # Top projects
        sections.append(
            self.format_bar_chart(data.project_counts, "Top Projects", max_bars=5)
        )

        # Models used
        sections.append(
            self.format_bar_chart(data.model_counts, "Models Used", max_bars=5)
        )

        # Commands
        if data.command_counts:
            sections.append(
                self.format_bar_chart(data.command_counts, "Top Commands", max_bars=5)
            )

        # Sparkline
        sections.append(self.format_sparkline())

        # Footer
        computed = data.computed_at.strftime("%H:%M:%S") if data.computed_at else "N/A"
        sections.append(
            f"[dim]Last updated: {computed} | /dashboard refresh to rescan[/dim]"
        )

        return "\n\n".join(sections)

    def export_html(self) -> str:
        """Export dashboard as basic HTML."""
        data = self._data

        # Simple HTML with inline CSS
        html_parts = [
            "<!DOCTYPE html>",
            "<html><head>",
            "<meta charset='utf-8'>",
            "<title>Amplifier TUI Dashboard</title>",
            "<style>",
            "body { font-family: monospace; background: #1a1a2e; color: #e0e0e0;"
            " padding: 2em; }",
            "h1 { color: #64ffda; }",
            "h2 { color: #82aaff; margin-top: 2em; }",
            ".stat { margin: 0.3em 0; }",
            ".bar { background: #333; display: inline-block; height: 1.2em; }",
            ".bar-fill { background: #64ffda; display: inline-block; height: 1.2em; }",
            "table { border-collapse: collapse; }",
            "td { padding: 2px 4px; text-align: center; }",
            ".heat-0 { background: #1a1a2e; }",
            ".heat-1 { background: #2d4a3e; }",
            ".heat-2 { background: #3d7a5e; }",
            ".heat-3 { background: #4daa7e; }",
            ".heat-4 { background: #64ffda; color: #000; }",
            "pre { white-space: pre-wrap; }",
            "</style>",
            "</head><body>",
            "<h1>Amplifier TUI Dashboard</h1>",
            f"<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>",
        ]

        # Summary
        avg_mins = data.avg_duration_seconds / 60
        total_hours = data.total_duration_seconds / 3600
        html_parts.append("<h2>Summary</h2>")
        html_parts.append(f"<p class='stat'>Total sessions: {data.total_sessions}</p>")
        html_parts.append(f"<p class='stat'>Total tokens: {data.total_tokens:,}</p>")
        html_parts.append(f"<p class='stat'>Total time: {total_hours:.1f} hours</p>")
        html_parts.append(f"<p class='stat'>Avg session: {avg_mins:.1f} minutes</p>")
        html_parts.append(
            f"<p class='stat'>Current streak: {data.streak_days} days</p>"
        )
        html_parts.append(
            f"<p class='stat'>Longest streak: {data.longest_streak} days</p>"
        )

        # Heatmap as HTML table
        if data.activity_grid:
            max_count = max(data.activity_grid.values())
            html_parts.append("<h2>Activity Heatmap</h2>")
            html_parts.append("<table>")
            days_header = "".join(
                f"<td>{d}</td>"
                for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            )
            html_parts.append(f"<tr><td></td>{days_header}</tr>")
            for hour in range(24):
                html_parts.append(f"<tr><td>{hour:02d}</td>")
                for weekday in range(7):
                    count = data.activity_grid.get((hour, weekday), 0)
                    intensity = (
                        min(4, int((count / max_count) * 4))
                        if count > 0 and max_count > 0
                        else 0
                    )
                    html_parts.append(
                        f"<td class='heat-{intensity}'>{count or ''}</td>"
                    )
                html_parts.append("</tr>")
            html_parts.append("</table>")

        # Projects
        if data.project_counts:
            html_parts.append("<h2>Top Projects</h2>")
            for name, count in data.project_counts.most_common(10):
                html_parts.append(f"<p class='stat'>{name}: {count}</p>")

        html_parts.append("</body></html>")
        return "\n".join(html_parts)

    def clear(self) -> None:
        """Clear cached data."""
        self._data = DashboardData()
        self._cached = False
