"""Tests for the live tool introspection log (F4.1)."""

from __future__ import annotations

from datetime import datetime

from amplifier_tui.features.tool_log import (
    ToolEntry,
    ToolLog,
    summarize_tool_input,
    tool_color,
    TOOL_COLORS,
)
from amplifier_tui.commands.tool_cmds import ToolCommandsMixin


# ===========================================================================
# ToolEntry defaults
# ===========================================================================


class TestToolEntry:
    def test_defaults(self):
        now = datetime.now()
        entry = ToolEntry(tool_name="bash", summary="ls -la", timestamp=now)
        assert entry.tool_name == "bash"
        assert entry.summary == "ls -la"
        assert entry.timestamp == now
        assert entry.duration_ms is None
        assert entry.status == "running"

    def test_completed(self):
        entry = ToolEntry(
            tool_name="grep",
            summary='"pattern"',
            timestamp=datetime.now(),
            duration_ms=42.0,
            status="completed",
        )
        assert entry.status == "completed"
        assert entry.duration_ms == 42.0


# ===========================================================================
# tool_color
# ===========================================================================


class TestToolColor:
    def test_known_tools(self):
        assert tool_color("read_file") == "blue"
        assert tool_color("write_file") == "blue"
        assert tool_color("edit_file") == "blue"
        assert tool_color("glob") == "blue"
        assert tool_color("grep") == "yellow"
        assert tool_color("bash") == "green"
        assert tool_color("delegate") == "magenta"
        assert tool_color("task") == "magenta"
        assert tool_color("LSP") == "cyan"
        assert tool_color("python_check") == "cyan"
        assert tool_color("todo") == "dim"
        assert tool_color("load_skill") == "dim"

    def test_unknown_tool_returns_white(self):
        assert tool_color("unknown_tool") == "white"
        assert tool_color("") == "white"

    def test_all_color_keys_are_strings(self):
        for key, val in TOOL_COLORS.items():
            assert isinstance(key, str)
            assert isinstance(val, str)


# ===========================================================================
# summarize_tool_input
# ===========================================================================


class TestSummarizeToolInput:
    def test_read_file_basic(self):
        result = summarize_tool_input("read_file", {"file_path": "/src/auth.py"})
        assert "auth.py" in result

    def test_read_file_with_offset(self):
        result = summarize_tool_input(
            "read_file", {"file_path": "/src/auth.py", "offset": 10, "limit": 50}
        )
        assert "auth.py" in result
        assert "10" in result
        assert "60" in result  # offset + limit

    def test_read_file_offset_only(self):
        result = summarize_tool_input(
            "read_file", {"file_path": "/src/auth.py", "offset": 10}
        )
        assert "auth.py" in result
        assert "from line 10" in result

    def test_grep_with_path(self):
        result = summarize_tool_input(
            "grep", {"pattern": "validate_token", "path": "src/"}
        )
        assert '"validate_token"' in result
        assert "src/" in result

    def test_grep_without_path(self):
        result = summarize_tool_input("grep", {"pattern": "validate_token"})
        assert '"validate_token"' in result

    def test_bash(self):
        result = summarize_tool_input("bash", {"command": "git log --oneline -5"})
        assert "git log --oneline -5" in result

    def test_bash_truncates_long_command(self):
        long_cmd = "x" * 100
        result = summarize_tool_input("bash", {"command": long_cmd})
        assert len(result) <= 60

    def test_delegate(self):
        result = summarize_tool_input(
            "delegate",
            {"agent": "foundation:explorer", "instruction": "Find the auth module"},
        )
        assert "foundation:explorer" in result
        assert "Find the auth" in result

    def test_delegate_no_instruction(self):
        result = summarize_tool_input("delegate", {"agent": "self"})
        assert result == "self"

    def test_write_file(self):
        result = summarize_tool_input(
            "write_file", {"file_path": "/home/user/src/new.py"}
        )
        assert result == "new.py"

    def test_edit_file(self):
        result = summarize_tool_input(
            "edit_file", {"file_path": "/path/to/file.py", "old_string": "x"}
        )
        assert result == "file.py"

    def test_glob(self):
        result = summarize_tool_input("glob", {"pattern": "**/*.py"})
        assert result == "**/*.py"

    def test_web_search(self):
        result = summarize_tool_input("web_search", {"query": "python async"})
        assert result == "python async"

    def test_web_fetch_short_url(self):
        url = "https://example.com/page"
        result = summarize_tool_input("web_fetch", {"url": url})
        assert result == url

    def test_web_fetch_long_url_truncated(self):
        url = "https://example.com/" + "a" * 100
        result = summarize_tool_input("web_fetch", {"url": url})
        assert result.endswith("...")
        assert len(result) <= 64  # 60 + "..."

    def test_lsp(self):
        result = summarize_tool_input(
            "LSP", {"operation": "hover", "file_path": "/src/main.py", "line": 10}
        )
        assert "hover" in result
        assert "main.py" in result

    def test_todo(self):
        result = summarize_tool_input("todo", {"action": "create"})
        assert result == "create"

    def test_empty_input(self):
        assert summarize_tool_input("bash", None) == ""
        assert summarize_tool_input("bash", {}) == ""

    def test_non_dict_input(self):
        assert summarize_tool_input("bash", "not a dict") == ""  # type: ignore[arg-type]

    def test_generic_fallback(self):
        result = summarize_tool_input("custom_tool", {"some_key": "some_value"})
        assert result == "some_value"

    def test_generic_fallback_no_strings(self):
        result = summarize_tool_input("custom_tool", {"num": 42})
        assert result == ""


# ===========================================================================
# ToolLog lifecycle
# ===========================================================================


class TestToolLogStartEnd:
    def test_start_creates_entry(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        assert len(log.entries) == 1
        assert log.entries[0].tool_name == "bash"
        assert log.entries[0].status == "running"

    def test_end_completes_entry(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        log.on_tool_end("bash")
        entries = log.entries
        assert entries[0].status == "completed"
        assert entries[0].duration_ms is not None
        assert entries[0].duration_ms >= 0

    def test_end_failed_status(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "false"})
        log.on_tool_end("bash", status="failed")
        assert log.entries[0].status == "failed"

    def test_end_matches_most_recent_running(self):
        log = ToolLog()
        log.on_tool_start("read_file", {"file_path": "a.py"})
        log.on_tool_end("read_file")
        log.on_tool_start("read_file", {"file_path": "b.py"})
        log.on_tool_end("read_file")
        assert log.entries[0].status == "completed"
        assert log.entries[1].status == "completed"
        assert log.entries[0].summary == "a.py"
        assert log.entries[1].summary == "b.py"

    def test_end_with_no_matching_start_is_noop(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        log.on_tool_end("grep")  # no matching running entry
        assert log.entries[0].status == "running"  # unchanged

    def test_multiple_tools_interleaved(self):
        log = ToolLog()
        log.on_tool_start("read_file", {"file_path": "a.py"})
        log.on_tool_start("grep", {"pattern": "foo"})
        # End grep first (it started second)
        log.on_tool_end("grep")
        log.on_tool_end("read_file")
        entries = log.entries
        assert entries[0].tool_name == "read_file"
        assert entries[0].status == "completed"
        assert entries[1].tool_name == "grep"
        assert entries[1].status == "completed"


# ===========================================================================
# ToolLog turn count
# ===========================================================================


class TestToolLogTurnCount:
    def test_initial_count(self):
        log = ToolLog()
        assert log.turn_count == 0
        assert log.total_count == 0

    def test_increments_on_start(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        assert log.turn_count == 1
        assert log.total_count == 1

    def test_reset_turn_count(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        log.on_tool_start("grep", {"pattern": "x"})
        assert log.turn_count == 2
        log.reset_turn_count()
        assert log.turn_count == 0
        assert log.total_count == 2  # total not reset

    def test_total_count_survives_reset(self):
        log = ToolLog()
        for _ in range(5):
            log.on_tool_start("bash", {"command": "ls"})
        log.reset_turn_count()
        for _ in range(3):
            log.on_tool_start("bash", {"command": "ls"})
        assert log.turn_count == 3
        assert log.total_count == 8


# ===========================================================================
# ToolLog max entries
# ===========================================================================


class TestToolLogMaxEntries:
    def test_prunes_to_max(self):
        log = ToolLog()
        for i in range(250):
            log.on_tool_start("bash", {"command": f"cmd-{i}"})
        assert len(log.entries) == ToolLog.MAX_ENTRIES
        assert log.total_count == 250
        # Oldest should have been pruned; newest should be present
        assert "cmd-249" in log.entries[-1].summary

    def test_exactly_at_max(self):
        log = ToolLog()
        for i in range(200):
            log.on_tool_start("bash", {"command": f"cmd-{i}"})
        assert len(log.entries) == 200


# ===========================================================================
# ToolLog formatting
# ===========================================================================


class TestToolLogFormatLive:
    def test_empty(self):
        log = ToolLog()
        result = log.format_live_log()
        assert "No tool calls yet" in result

    def test_has_entries(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "git status"})
        log.on_tool_end("bash")
        result = log.format_live_log()
        assert "bash" in result
        assert "git status" in result

    def test_respects_last_n(self):
        log = ToolLog()
        for i in range(10):
            log.on_tool_start("bash", {"command": f"cmd-{i}"})
        result = log.format_live_log(last_n=3)
        # Should only contain the last 3
        assert "cmd-7" in result
        assert "cmd-8" in result
        assert "cmd-9" in result
        assert "cmd-0" not in result

    def test_running_shows_running(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "sleep 100"})
        result = log.format_live_log()
        assert "running" in result

    def test_failed_shows_failed(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "false"})
        log.on_tool_end("bash", status="failed")
        result = log.format_live_log()
        assert "failed" in result

    def test_duration_shown(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        log.on_tool_end("bash")
        result = log.format_live_log()
        # Should have a duration (ms or s)
        assert "ms" in result or "s" in result


class TestToolLogFormatStats:
    def test_empty(self):
        log = ToolLog()
        assert "No tool calls" in log.format_stats()

    def test_has_counts(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        log.on_tool_end("bash")
        log.on_tool_start("grep", {"pattern": "x"})
        log.on_tool_end("grep")
        log.on_tool_start("bash", {"command": "pwd"})
        log.on_tool_end("bash")
        result = log.format_stats()
        assert "bash" in result
        assert "grep" in result
        assert "3 total calls" in result

    def test_turn_count_in_stats(self):
        log = ToolLog()
        log.on_tool_start("bash", {"command": "ls"})
        result = log.format_stats()
        assert "This turn: 1" in result


class TestToolLogFormatFullLog:
    def test_empty(self):
        log = ToolLog()
        assert "No tool calls" in log.format_full_log()

    def test_has_entries(self):
        log = ToolLog()
        log.on_tool_start("read_file", {"file_path": "auth.py"})
        log.on_tool_end("read_file")
        result = log.format_full_log()
        assert "1 calls" in result
        assert "read_file" in result
        assert "auth.py" in result


# ===========================================================================
# ToolLog clear
# ===========================================================================


class TestToolLogClear:
    def test_clear_resets_everything(self):
        log = ToolLog()
        for _ in range(5):
            log.on_tool_start("bash", {"command": "ls"})
        log.clear()
        assert len(log.entries) == 0
        assert log.turn_count == 0
        assert log.total_count == 0


# ===========================================================================
# Command mixin exists
# ===========================================================================


class TestCommandMixinExists:
    def test_has_cmd_tools_method(self):
        assert hasattr(ToolCommandsMixin, "_cmd_tools")

    def test_cmd_tools_is_callable(self):
        assert callable(getattr(ToolCommandsMixin, "_cmd_tools"))
