"""Tests for the session dashboard stats engine and command mixin."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


from amplifier_tui.features.dashboard_stats import (
    DashboardData,
    DashboardStats,
    SessionRecord,
)
from amplifier_tui.commands.dashboard_cmds import DashboardCommandsMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    hour: int = 10,
    weekday: int = 0,
    project: str = "test-project",
    model: str = "claude-sonnet-4",
    tokens: int = 1000,
    duration: float = 300.0,
    commands: list[str] | None = None,
    tools: list[str] | None = None,
) -> SessionRecord:
    """Build a SessionRecord with a deterministic timestamp.

    weekday 0 = Monday.  We anchor on 2026-01-05 which is a Monday,
    then add *weekday* days so weekday=2 → Wednesday, etc.
    """
    base_date = datetime(2026, 1, 5)  # Monday
    dt = base_date + timedelta(days=weekday)
    dt = dt.replace(hour=hour, minute=0, second=0)
    return SessionRecord(
        session_id=f"test-{hour}-{weekday}",
        project=project,
        started_at=dt,
        ended_at=dt + timedelta(seconds=duration),
        duration_seconds=duration,
        model=model,
        token_count=tokens,
        turn_count=5,
        commands_used=["/help", "/include"] if commands is None else commands,
        tools_used=["read_file"] if tools is None else tools,
    )


def _write_session_info(
    base: Path,
    project: str,
    session_id: str,
    data: dict,  # type: ignore[type-arg]
    filename: str = "session-info.json",
) -> Path:
    """Create a fake session directory with a JSON metadata file."""
    session_dir = base / project / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / filename
    path.write_text(json.dumps(data))
    return path


# ===========================================================================
# SessionRecord dataclass
# ===========================================================================


class TestSessionRecord:
    def test_defaults(self) -> None:
        r = SessionRecord()
        assert r.session_id == ""
        assert r.project == ""
        assert r.started_at is None
        assert r.ended_at is None
        assert r.duration_seconds == 0
        assert r.model == ""
        assert r.turn_count == 0
        assert r.token_count == 0
        assert r.tools_used == []
        assert r.commands_used == []

    def test_all_fields(self) -> None:
        now = datetime.now()
        r = SessionRecord(
            session_id="abc",
            project="proj",
            started_at=now,
            ended_at=now,
            duration_seconds=120,
            model="claude",
            turn_count=3,
            token_count=5000,
            tools_used=["bash"],
            commands_used=["/help"],
        )
        assert r.session_id == "abc"
        assert r.project == "proj"
        assert r.token_count == 5000
        assert r.tools_used == ["bash"]

    def test_mutable_defaults_independent(self) -> None:
        """Ensure default lists are independent per instance."""
        a = SessionRecord()
        b = SessionRecord()
        a.tools_used.append("x")
        assert b.tools_used == []


# ===========================================================================
# DashboardData dataclass
# ===========================================================================


class TestDashboardData:
    def test_defaults(self) -> None:
        d = DashboardData()
        assert d.total_sessions == 0
        assert d.total_tokens == 0
        assert d.avg_duration_seconds == 0
        assert d.activity_grid == {}
        assert isinstance(d.command_counts, Counter)
        assert isinstance(d.model_counts, Counter)
        assert isinstance(d.project_counts, Counter)
        assert d.daily_tokens == {}
        assert d.streak_days == 0
        assert d.longest_streak == 0
        assert d.computed_at is None

    def test_all_fields(self) -> None:
        d = DashboardData(
            total_sessions=5,
            total_tokens=10000,
            streak_days=3,
            longest_streak=7,
        )
        assert d.total_sessions == 5
        assert d.total_tokens == 10000
        assert d.streak_days == 3
        assert d.longest_streak == 7


# ===========================================================================
# DashboardStats — core logic
# ===========================================================================


class TestDashboardStatsInit:
    def test_initial_state(self) -> None:
        stats = DashboardStats()
        assert not stats.is_cached
        assert stats.data.total_sessions == 0

    def test_custom_session_dir(self, tmp_path: Path) -> None:
        stats = DashboardStats(session_dir=tmp_path)
        assert stats._session_dir == tmp_path


class TestLoadFromRecords:
    def test_loads_and_caches(self) -> None:
        stats = DashboardStats()
        records = [_make_record()]
        stats.load_from_records(records)
        assert stats.is_cached
        assert stats.data.total_sessions == 1

    def test_empty_records(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])
        assert stats.is_cached
        assert stats.data.total_sessions == 0


class TestAggregate:
    def test_totals(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(tokens=1000, duration=300),
            _make_record(tokens=2000, duration=600),
        ]
        stats.load_from_records(records)
        assert stats.data.total_sessions == 2
        assert stats.data.total_tokens == 3000
        assert stats.data.total_duration_seconds == 900

    def test_avg_duration(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(duration=100),
            _make_record(duration=300),
        ]
        stats.load_from_records(records)
        assert stats.data.avg_duration_seconds == 200.0

    def test_avg_duration_zero_sessions(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])
        assert stats.data.avg_duration_seconds == 0

    def test_activity_grid(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(hour=9, weekday=0),  # Mon 9am
            _make_record(hour=9, weekday=0),  # Mon 9am again
            _make_record(hour=14, weekday=4),  # Fri 2pm
        ]
        stats.load_from_records(records)
        grid = stats.data.activity_grid
        assert grid[(9, 0)] == 2  # Two sessions Mon 9am
        assert grid[(14, 4)] == 1  # One session Fri 2pm
        assert grid.get((0, 0), 0) == 0  # No session at midnight Mon

    def test_model_counts(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(model="claude-sonnet-4"),
            _make_record(model="claude-sonnet-4"),
            _make_record(model="gpt-4o"),
        ]
        stats.load_from_records(records)
        assert stats.data.model_counts["claude-sonnet-4"] == 2
        assert stats.data.model_counts["gpt-4o"] == 1

    def test_project_counts(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(project="alpha"),
            _make_record(project="alpha"),
            _make_record(project="beta"),
        ]
        stats.load_from_records(records)
        assert stats.data.project_counts["alpha"] == 2
        assert stats.data.project_counts["beta"] == 1

    def test_command_counts(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(commands=["/help", "/stats"]),
            _make_record(commands=["/help"]),
        ]
        stats.load_from_records(records)
        assert stats.data.command_counts["/help"] == 2
        assert stats.data.command_counts["/stats"] == 1

    def test_daily_tokens(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(weekday=0, tokens=500),
            _make_record(weekday=0, tokens=700),  # same day
            _make_record(weekday=2, tokens=1000),  # different day
        ]
        stats.load_from_records(records)
        dt = stats.data.daily_tokens
        assert dt["2026-01-05"] == 1200  # Mon: 500 + 700
        assert dt["2026-01-07"] == 1000  # Wed

    def test_computed_at_set(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([_make_record()])
        assert stats.data.computed_at is not None
        assert isinstance(stats.data.computed_at, datetime)

    def test_empty_model_not_counted(self) -> None:
        stats = DashboardStats()
        records = [_make_record(model="")]
        stats.load_from_records(records)
        assert len(stats.data.model_counts) == 0

    def test_empty_project_not_counted(self) -> None:
        stats = DashboardStats()
        records = [_make_record(project="")]
        stats.load_from_records(records)
        assert len(stats.data.project_counts) == 0

    def test_no_started_at_skips_grid(self) -> None:
        stats = DashboardStats()
        r = SessionRecord(token_count=100)  # no started_at
        stats.load_from_records([r])
        assert stats.data.activity_grid == {}
        assert stats.data.daily_tokens == {}


# ===========================================================================
# Streak calculation
# ===========================================================================


class TestCalculateStreaks:
    def test_empty_list(self) -> None:
        stats = DashboardStats()
        assert stats._calculate_streaks([]) == (0, 0)

    def test_single_date_today(self) -> None:
        stats = DashboardStats()
        today = datetime.now().strftime("%Y-%m-%d")
        current, longest = stats._calculate_streaks([today])
        assert longest == 1
        assert current >= 1  # today counts

    def test_consecutive_dates(self) -> None:
        stats = DashboardStats()
        today = datetime.now().date()
        dates = [
            (today - timedelta(days=2)).isoformat(),
            (today - timedelta(days=1)).isoformat(),
            today.isoformat(),
        ]
        current, longest = stats._calculate_streaks(sorted(dates))
        assert longest == 3
        assert current == 3

    def test_gap_in_dates(self) -> None:
        stats = DashboardStats()
        # Two separate streaks of length 2 and 3, neither current
        dates = [
            "2025-06-01",
            "2025-06-02",
            # gap
            "2025-06-10",
            "2025-06-11",
            "2025-06-12",
        ]
        current, longest = stats._calculate_streaks(dates)
        assert longest == 3
        # Current streak is 0 (these dates are far in the past)
        assert current == 0

    def test_streak_from_yesterday(self) -> None:
        """If no session today but yesterday had one, streak still counts."""
        stats = DashboardStats()
        today = datetime.now().date()
        dates = [
            (today - timedelta(days=3)).isoformat(),
            (today - timedelta(days=2)).isoformat(),
            (today - timedelta(days=1)).isoformat(),
        ]
        current, longest = stats._calculate_streaks(sorted(dates))
        assert longest == 3
        assert current == 3  # yesterday-based streak


# ===========================================================================
# Parsing session info files
# ===========================================================================


class TestParseSessionInfo:
    def test_valid_json(self, tmp_path: Path) -> None:
        path = _write_session_info(
            tmp_path,
            "proj",
            "s1",
            {
                "session_id": "s1",
                "project_id": "my-project",
                "started_at": "2026-01-05T10:00:00+00:00",
                "ended_at": "2026-01-05T10:30:00+00:00",
                "model": "claude-sonnet-4",
                "turn_count": 5,
                "token_count": 2000,
                "tools_used": ["bash", "read_file"],
                "commands_used": ["/help"],
            },
        )
        stats = DashboardStats()
        record = stats._parse_session_info(path)
        assert record is not None
        assert record.session_id == "s1"
        assert record.project == "my-project"
        assert record.model == "claude-sonnet-4"
        assert record.turn_count == 5
        assert record.token_count == 2000
        assert record.duration_seconds == 1800.0
        assert record.tools_used == ["bash", "read_file"]
        assert record.commands_used == ["/help"]

    def test_metadata_json_format(self, tmp_path: Path) -> None:
        """Test parsing Amplifier's native metadata.json format."""
        path = _write_session_info(
            tmp_path,
            "proj",
            "s2",
            {
                "session_id": "s2",
                "created": "2026-01-05T10:00:00+00:00",
                "model": "unknown",
                "turn_count": 3,
            },
            filename="metadata.json",
        )
        stats = DashboardStats()
        record = stats._parse_session_info(path)
        assert record is not None
        assert record.session_id == "s2"
        assert record.started_at is not None
        assert record.turn_count == 3

    def test_malformed_json_returns_none(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "proj" / "sessions" / "bad"
        session_dir.mkdir(parents=True)
        bad_file = session_dir / "session-info.json"
        bad_file.write_text("{not valid json")
        stats = DashboardStats()
        assert stats._parse_session_info(bad_file) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        stats = DashboardStats()
        assert stats._parse_session_info(tmp_path / "nonexistent.json") is None

    def test_missing_fields_uses_defaults(self, tmp_path: Path) -> None:
        path = _write_session_info(tmp_path, "proj", "s3", {})
        stats = DashboardStats()
        record = stats._parse_session_info(path)
        assert record is not None
        assert record.session_id == ""
        assert record.model == ""
        assert record.token_count == 0
        assert record.started_at is None

    def test_project_fallback_to_dir_name(self, tmp_path: Path) -> None:
        """If no project_id or project field, fall back to dir name."""
        path = _write_session_info(
            tmp_path,
            "my-cool-project",
            "s4",
            {
                "session_id": "s4",
            },
        )
        stats = DashboardStats()
        record = stats._parse_session_info(path)
        assert record is not None
        assert record.project == "my-cool-project"

    def test_duration_from_timestamps(self, tmp_path: Path) -> None:
        """Duration computed from start/end when both present."""
        path = _write_session_info(
            tmp_path,
            "proj",
            "s5",
            {
                "started_at": "2026-01-05T10:00:00+00:00",
                "ended_at": "2026-01-05T10:05:00+00:00",
                "duration_seconds": 9999,  # should be ignored
            },
        )
        stats = DashboardStats()
        record = stats._parse_session_info(path)
        assert record is not None
        assert record.duration_seconds == 300.0  # 5 minutes

    def test_duration_fallback(self, tmp_path: Path) -> None:
        """Duration falls back to explicit field when no end time."""
        path = _write_session_info(
            tmp_path,
            "proj",
            "s6",
            {
                "started_at": "2026-01-05T10:00:00+00:00",
                "duration_seconds": 120,
            },
        )
        stats = DashboardStats()
        record = stats._parse_session_info(path)
        assert record is not None
        assert record.duration_seconds == 120

    def test_z_suffix_timestamp(self, tmp_path: Path) -> None:
        """Z-suffix timestamps are handled."""
        path = _write_session_info(
            tmp_path,
            "proj",
            "s7",
            {
                "started_at": "2026-01-05T10:00:00Z",
            },
        )
        stats = DashboardStats()
        record = stats._parse_session_info(path)
        assert record is not None
        assert record.started_at is not None


# ===========================================================================
# Scan sessions (integration with filesystem)
# ===========================================================================


class TestScanSessions:
    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        stats = DashboardStats(session_dir=tmp_path)
        count = stats.scan_sessions()
        assert count == 0
        assert stats.is_cached
        assert stats.data.total_sessions == 0

    def test_scan_nonexistent_dir(self, tmp_path: Path) -> None:
        stats = DashboardStats(session_dir=tmp_path / "nope")
        count = stats.scan_sessions()
        assert count == 0
        assert stats.is_cached

    def test_scan_finds_session_info(self, tmp_path: Path) -> None:
        _write_session_info(
            tmp_path,
            "proj-a",
            "s1",
            {
                "session_id": "s1",
                "project_id": "proj-a",
                "started_at": "2026-01-05T09:00:00+00:00",
                "model": "claude-sonnet-4",
                "token_count": 500,
            },
        )
        _write_session_info(
            tmp_path,
            "proj-b",
            "s2",
            {
                "session_id": "s2",
                "project_id": "proj-b",
                "started_at": "2026-01-06T14:00:00+00:00",
                "model": "gpt-4o",
                "token_count": 800,
            },
        )
        stats = DashboardStats(session_dir=tmp_path)
        count = stats.scan_sessions()
        assert count == 2
        assert stats.data.total_tokens == 1300
        assert stats.data.project_counts["proj-a"] == 1
        assert stats.data.project_counts["proj-b"] == 1

    def test_scan_finds_metadata_json(self, tmp_path: Path) -> None:
        _write_session_info(
            tmp_path,
            "proj",
            "s1",
            {
                "session_id": "s1",
                "created": "2026-01-05T09:00:00+00:00",
                "model": "claude-sonnet-4",
                "turn_count": 3,
            },
            filename="metadata.json",
        )
        stats = DashboardStats(session_dir=tmp_path)
        count = stats.scan_sessions()
        assert count == 1

    def test_scan_skips_malformed(self, tmp_path: Path) -> None:
        # One good, one bad
        _write_session_info(
            tmp_path,
            "proj",
            "good",
            {
                "session_id": "good",
                "token_count": 100,
            },
        )
        bad_dir = tmp_path / "proj" / "sessions" / "bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "session-info.json").write_text("not json!")
        stats = DashboardStats(session_dir=tmp_path)
        count = stats.scan_sessions()
        assert count == 1  # only good one


# ===========================================================================
# Formatting — heatmap
# ===========================================================================


class TestFormatHeatmap:
    def test_with_data(self) -> None:
        stats = DashboardStats()
        stats.load_from_records(
            [
                _make_record(hour=9, weekday=0),
                _make_record(hour=14, weekday=4),
            ]
        )
        output = stats.format_heatmap()
        assert "Activity Heatmap" in output
        assert "Mon" in output
        assert "Sun" in output
        # Should have 24 hour rows
        for h in range(24):
            assert f"{h:02d}:" in output

    def test_empty(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])
        output = stats.format_heatmap()
        assert "No activity data" in output

    def test_legend_present(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([_make_record()])
        output = stats.format_heatmap()
        assert "none" in output
        assert "peak" in output


# ===========================================================================
# Formatting — bar chart
# ===========================================================================


class TestFormatBarChart:
    def test_with_counter_data(self) -> None:
        stats = DashboardStats()
        counter: Counter[str] = Counter({"alpha": 10, "beta": 5, "gamma": 1})
        output = stats.format_bar_chart(counter, "Test Chart")
        assert "Test Chart" in output
        assert "alpha" in output
        assert "beta" in output
        assert "gamma" in output
        assert "█" in output
        assert "10" in output

    def test_empty_counter(self) -> None:
        stats = DashboardStats()
        counter: Counter[str] = Counter()
        output = stats.format_bar_chart(counter, "Empty Chart")
        assert "No empty chart data" in output

    def test_max_bars_limits(self) -> None:
        stats = DashboardStats()
        counter: Counter[str] = Counter({f"item{i}": i for i in range(20)})
        output = stats.format_bar_chart(counter, "Limited", max_bars=3)
        # Should only show top 3
        assert "item19" in output
        assert "item18" in output
        assert "item17" in output
        assert "item0" not in output


# ===========================================================================
# Formatting — sparkline
# ===========================================================================


class TestFormatSparkline:
    def test_with_daily_tokens(self) -> None:
        stats = DashboardStats()
        records = [
            _make_record(weekday=0, tokens=100),
            _make_record(weekday=1, tokens=500),
            _make_record(weekday=2, tokens=1000),
        ]
        stats.load_from_records(records)
        output = stats.format_sparkline()
        assert "Token Usage" in output
        assert "2026-01-05" in output  # first date
        assert "2026-01-07" in output  # last date
        # Should contain spark characters
        assert any(c in output for c in "▁▂▃▄▅▆▇█")

    def test_empty(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])
        output = stats.format_sparkline()
        assert "No token data" in output

    def test_single_value(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([_make_record(weekday=0, tokens=500)])
        output = stats.format_sparkline()
        assert "Token Usage" in output


# ===========================================================================
# Formatting — summary
# ===========================================================================


class TestFormatSummary:
    def test_with_data(self) -> None:
        stats = DashboardStats()
        stats.load_from_records(
            [
                _make_record(tokens=1000, duration=600),
                _make_record(tokens=2000, duration=1200),
            ]
        )
        output = stats.format_summary()
        assert "Summary Statistics" in output
        assert "Total sessions:" in output
        assert "2" in output
        assert "3,000" in output  # total tokens
        assert "Avg session:" in output
        assert "Current streak:" in output
        assert "Longest streak:" in output

    def test_zero_sessions(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])
        output = stats.format_summary()
        assert "0" in output
        assert "0.0 hours" in output


# ===========================================================================
# Formatting — full dashboard
# ===========================================================================


class TestFormatDashboard:
    def test_full_output(self) -> None:
        stats = DashboardStats()
        stats.load_from_records(
            [
                _make_record(hour=9, weekday=0, project="proj-a", model="claude"),
                _make_record(hour=14, weekday=2, project="proj-b", model="gpt-4o"),
                _make_record(hour=9, weekday=0, project="proj-a", model="claude"),
            ]
        )
        output = stats.format_dashboard()
        assert "Summary Statistics" in output
        assert "Activity Heatmap" in output
        assert "Top Projects" in output
        assert "Models Used" in output
        assert "Token Usage" in output
        assert "/dashboard refresh" in output

    def test_no_sessions_cached(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])  # marks cached
        output = stats.format_dashboard()
        assert "No sessions found" in output

    def test_no_sessions_not_cached(self) -> None:
        stats = DashboardStats()
        output = stats.format_dashboard()
        assert "No session data loaded" in output
        assert "/dashboard refresh" in output

    def test_commands_section_only_if_data(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([_make_record(commands=[])])
        output = stats.format_dashboard()
        assert "Top Commands" not in output


# ===========================================================================
# HTML export
# ===========================================================================


class TestExportHtml:
    def test_produces_valid_html(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([_make_record()])
        html = stats.export_html()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_key_elements(self) -> None:
        stats = DashboardStats()
        stats.load_from_records(
            [
                _make_record(hour=9, weekday=0, project="my-proj"),
            ]
        )
        html = stats.export_html()
        assert "<h1>" in html
        assert "Amplifier TUI Dashboard" in html
        assert "<h2>Summary</h2>" in html
        assert "<h2>Activity Heatmap</h2>" in html
        assert "<table>" in html
        assert "my-proj" in html
        assert "Total sessions: 1" in html

    def test_empty_sessions_still_valid(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])
        html = stats.export_html()
        assert "<!DOCTYPE html>" in html
        assert "Total sessions: 0" in html

    def test_no_heatmap_table_when_empty(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([])
        html = stats.export_html()
        assert "<table>" not in html


# ===========================================================================
# Clear
# ===========================================================================


class TestClear:
    def test_clears_cache(self) -> None:
        stats = DashboardStats()
        stats.load_from_records([_make_record()])
        assert stats.is_cached
        assert stats.data.total_sessions == 1

        stats.clear()
        assert not stats.is_cached
        assert stats.data.total_sessions == 0

    def test_is_cached_property(self) -> None:
        stats = DashboardStats()
        assert not stats.is_cached
        stats.load_from_records([])
        assert stats.is_cached
        stats.clear()
        assert not stats.is_cached


# ===========================================================================
# Integration: filesystem → scan → stats
# ===========================================================================


class TestIntegration:
    def test_full_pipeline(self, tmp_path: Path) -> None:
        """Create tmp session dirs, scan, verify stats."""
        _write_session_info(
            tmp_path,
            "proj-alpha",
            "s1",
            {
                "session_id": "s1",
                "project_id": "proj-alpha",
                "started_at": "2026-01-05T09:00:00+00:00",
                "ended_at": "2026-01-05T09:30:00+00:00",
                "model": "claude-sonnet-4",
                "token_count": 1500,
                "commands_used": ["/help", "/stats"],
            },
        )
        _write_session_info(
            tmp_path,
            "proj-alpha",
            "s2",
            {
                "session_id": "s2",
                "project_id": "proj-alpha",
                "started_at": "2026-01-06T14:00:00+00:00",
                "ended_at": "2026-01-06T14:45:00+00:00",
                "model": "claude-sonnet-4",
                "token_count": 3000,
                "commands_used": ["/include"],
            },
        )
        _write_session_info(
            tmp_path,
            "proj-beta",
            "s3",
            {
                "session_id": "s3",
                "project_id": "proj-beta",
                "started_at": "2026-01-07T11:00:00+00:00",
                "ended_at": "2026-01-07T11:15:00+00:00",
                "model": "gpt-4o",
                "token_count": 800,
            },
        )

        stats = DashboardStats(session_dir=tmp_path)
        count = stats.scan_sessions()
        assert count == 3
        assert stats.data.total_tokens == 5300
        assert stats.data.model_counts["claude-sonnet-4"] == 2
        assert stats.data.model_counts["gpt-4o"] == 1
        assert stats.data.project_counts["proj-alpha"] == 2
        assert stats.data.project_counts["proj-beta"] == 1
        assert stats.data.command_counts["/help"] == 1
        assert stats.data.command_counts["/stats"] == 1
        assert stats.data.command_counts["/include"] == 1

        # Heatmap grid checks
        assert stats.data.activity_grid[(9, 0)] == 1  # Mon 9am
        assert stats.data.activity_grid[(14, 1)] == 1  # Tue 2pm
        assert stats.data.activity_grid[(11, 2)] == 1  # Wed 11am

        # Daily tokens
        assert stats.data.daily_tokens["2026-01-05"] == 1500
        assert stats.data.daily_tokens["2026-01-06"] == 3000
        assert stats.data.daily_tokens["2026-01-07"] == 800

        # Full dashboard renders without error
        dashboard = stats.format_dashboard()
        assert "Summary Statistics" in dashboard
        assert "Activity Heatmap" in dashboard

        # HTML export works
        html = stats.export_html()
        assert "proj-alpha" in html
        assert "proj-beta" in html

    def test_rescan_replaces_data(self, tmp_path: Path) -> None:
        _write_session_info(
            tmp_path,
            "proj",
            "s1",
            {
                "session_id": "s1",
                "token_count": 100,
            },
        )
        stats = DashboardStats(session_dir=tmp_path)
        stats.scan_sessions()
        assert stats.data.total_sessions == 1

        # Add another session and rescan
        _write_session_info(
            tmp_path,
            "proj",
            "s2",
            {
                "session_id": "s2",
                "token_count": 200,
            },
        )
        count = stats.scan_sessions()
        assert count == 2
        assert stats.data.total_tokens == 300


# ===========================================================================
# Command mixin
# ===========================================================================


class TestDashboardCommandsMixin:
    def test_has_cmd_dashboard(self) -> None:
        assert hasattr(DashboardCommandsMixin, "_cmd_dashboard")

    def test_cmd_dashboard_is_callable(self) -> None:
        assert callable(getattr(DashboardCommandsMixin, "_cmd_dashboard"))
