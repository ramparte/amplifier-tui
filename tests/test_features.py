"""Tests for feature modules (git, export, notifications, file_watch, reverse_search)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from amplifier_tui.features.export import (
    export_html,
    export_json,
    export_markdown,
    export_text,
    get_export_metadata,
    html_escape,
    md_to_html,
)
from amplifier_tui.features.file_watch import FileWatcher
from amplifier_tui.features.git_integration import (
    colorize_diff,
    looks_like_commit_ref,
    run_git,
    show_diff,
)
from amplifier_tui.features.notifications import play_bell, send_terminal_notification
from amplifier_tui.features.reverse_search import ReverseSearchManager


# ===========================================================================
# Git integration
# ===========================================================================


class TestLooksLikeCommitRef:
    def test_head(self):
        assert looks_like_commit_ref("HEAD") is True

    def test_head_tilde(self):
        assert looks_like_commit_ref("HEAD~3") is True

    def test_head_caret(self):
        assert looks_like_commit_ref("HEAD^2") is True

    def test_short_hash(self):
        assert looks_like_commit_ref("abc1234") is True

    def test_full_hash(self):
        assert looks_like_commit_ref("a" * 40) is True

    def test_not_hash_too_short(self):
        assert looks_like_commit_ref("abc") is False

    def test_not_hash_non_hex(self):
        assert looks_like_commit_ref("hello") is False

    def test_not_hash_empty(self):
        assert looks_like_commit_ref("") is False

    def test_branch_with_tilde(self):
        assert looks_like_commit_ref("main~3") is True

    def test_branch_with_caret(self):
        assert looks_like_commit_ref("feature^2") is True

    def test_seven_char_hex(self):
        assert looks_like_commit_ref("1234567") is True

    def test_six_char_hex_too_short(self):
        assert looks_like_commit_ref("123456") is False


class TestColorizeDiff:
    def test_added_line(self):
        result = colorize_diff("+added line")
        assert "[green]" in result

    def test_removed_line(self):
        result = colorize_diff("-removed line")
        assert "[red]" in result

    def test_hunk_header(self):
        result = colorize_diff("@@ -1,3 +1,4 @@")
        assert "[cyan]" in result

    def test_file_header_plus(self):
        result = colorize_diff("+++ b/file.py")
        assert "[bold]" in result

    def test_file_header_minus(self):
        result = colorize_diff("--- a/file.py")
        assert "[bold]" in result

    def test_diff_line(self):
        result = colorize_diff("diff --git a/f.py b/f.py")
        assert "[bold yellow]" in result

    def test_normal_line_unchanged(self):
        result = colorize_diff(" normal context line")
        assert "[green]" not in result
        assert "[red]" not in result

    def test_multiline(self):
        diff = "+added\n-removed\n normal"
        result = colorize_diff(diff)
        assert "[green]" in result
        assert "[red]" in result


class TestShowDiff:
    def test_returns_string(self):
        result = show_diff("+line1\n-line2")
        assert isinstance(result, str)

    def test_with_header(self):
        result = show_diff("+line", header="Changes: ")
        assert "Changes:" in result

    def test_truncation(self):
        long_diff = "\n".join(f"+line{i}" for i in range(600))
        result = show_diff(long_diff, max_lines=10)
        assert "truncated" in result


class TestRunGit:
    def test_run_git_version(self):
        """git --version should succeed on most systems."""
        success, output = run_git("--version")
        assert success is True
        assert "git" in output.lower()

    def test_run_git_in_non_repo(self, tmp_path):
        success, output = run_git("status", cwd=str(tmp_path))
        assert success is False
        assert isinstance(output, str)

    def test_run_git_returns_tuple(self):
        result = run_git("--version")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ===========================================================================
# Export
# ===========================================================================


class TestHtmlEscape:
    def test_angle_brackets(self):
        assert "&lt;" in html_escape("<script>")
        assert "&gt;" in html_escape("<script>")

    def test_ampersand(self):
        assert "&amp;" in html_escape("a & b")

    def test_quotes(self):
        assert "&quot;" in html_escape('say "hello"')

    def test_safe_text_unchanged(self):
        assert html_escape("hello world") == "hello world"


class TestMdToHtml:
    def test_inline_code(self):
        result = md_to_html("use `print()`")
        assert "<code>" in result

    def test_bold(self):
        result = md_to_html("this is **bold** text")
        assert "<strong>" in result

    def test_italic(self):
        result = md_to_html("this is *italic* text")
        assert "<em>" in result

    def test_newlines_become_br(self):
        result = md_to_html("line1\nline2")
        assert "<br>" in result


class TestGetExportMetadata:
    def test_returns_dict(self):
        result = get_export_metadata()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = get_export_metadata(session_id="s1", model="m1")
        for key in ("date", "session_id", "session_title", "model", "message_count", "token_estimate"):
            assert key in result

    def test_token_estimate_format(self):
        result = get_export_metadata(user_words=100, assistant_words=200)
        assert result["token_estimate"].startswith("~")

    def test_message_count_is_string(self):
        result = get_export_metadata(message_count=42)
        assert result["message_count"] == "42"


class TestExportMarkdown:
    def test_contains_messages(self, sample_messages, sample_metadata):
        result = export_markdown(sample_messages, sample_metadata)
        assert "Hello" in result
        assert "Hi there" in result
        assert "Python" in result

    def test_has_header(self, sample_messages, sample_metadata):
        result = export_markdown(sample_messages, sample_metadata)
        assert "# Amplifier Chat Export" in result

    def test_has_metadata(self, sample_messages, sample_metadata):
        result = export_markdown(sample_messages, sample_metadata)
        assert sample_metadata["model"] in result

    def test_has_role_headers(self, sample_messages, sample_metadata):
        result = export_markdown(sample_messages, sample_metadata)
        assert "## User" in result
        assert "## Assistant" in result

    def test_thinking_role(self, sample_metadata):
        msgs = [("thinking", "internal thought", None)]
        result = export_markdown(msgs, sample_metadata)
        assert "Thinking" in result

    def test_system_role(self, sample_metadata):
        msgs = [("system", "system message", None)]
        result = export_markdown(msgs, sample_metadata)
        assert "System" in result


class TestExportText:
    def test_contains_messages(self, sample_messages, sample_metadata):
        result = export_text(sample_messages, sample_metadata)
        assert "Hello" in result
        assert isinstance(result, str)

    def test_has_role_labels(self, sample_messages, sample_metadata):
        result = export_text(sample_messages, sample_metadata)
        assert "[You]" in result
        assert "[AI]" in result


class TestExportJson:
    def test_valid_json(self, sample_messages, sample_metadata):
        result = export_json(sample_messages, sample_metadata)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_has_messages(self, sample_messages, sample_metadata):
        result = export_json(sample_messages, sample_metadata)
        parsed = json.loads(result)
        assert "messages" in parsed
        assert len(parsed["messages"]) == len(sample_messages)

    def test_has_metadata_fields(self, sample_messages, sample_metadata):
        result = export_json(sample_messages, sample_metadata)
        parsed = json.loads(result)
        assert "session_id" in parsed
        assert "model" in parsed


class TestExportHtml:
    def test_has_html_structure(self, sample_messages, sample_metadata):
        result = export_html(sample_messages, sample_metadata)
        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "</html>" in result

    def test_has_messages(self, sample_messages, sample_metadata):
        result = export_html(sample_messages, sample_metadata)
        assert "Hello" in result

    def test_has_css(self, sample_messages, sample_metadata):
        result = export_html(sample_messages, sample_metadata)
        assert "<style>" in result

    def test_thinking_uses_details(self, sample_metadata):
        msgs = [("thinking", "deep thought", None)]
        result = export_html(msgs, sample_metadata)
        assert "<details" in result


# ===========================================================================
# Notifications
# ===========================================================================


class TestNotifications:
    def test_send_terminal_notification_no_crash(self):
        """Just ensure no exception is raised."""
        send_terminal_notification("Test", "Body")

    def test_play_bell_no_crash(self):
        """Just ensure no exception is raised."""
        play_bell()


# ===========================================================================
# FileWatcher
# ===========================================================================


class TestFileWatcher:
    def _make_watcher(self):
        timer = MagicMock()
        timer.stop = MagicMock()
        return FileWatcher(
            add_message=MagicMock(),
            notify_sound=MagicMock(),
            set_interval=MagicMock(return_value=timer),
        )

    def test_create(self):
        watcher = self._make_watcher()
        assert watcher is not None
        assert watcher.count == 0

    def test_add_file(self, tmp_path):
        watcher = self._make_watcher()
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        result = watcher.add(str(test_file))
        assert result is None  # None means success
        assert watcher.count == 1

    def test_add_nonexistent_returns_error(self, tmp_path):
        watcher = self._make_watcher()
        result = watcher.add(str(tmp_path / "nope.txt"))
        assert result is not None
        assert "not found" in result.lower()

    def test_add_duplicate_returns_error(self, tmp_path):
        watcher = self._make_watcher()
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        watcher.add(str(test_file))
        result = watcher.add(str(test_file))
        assert result is not None
        assert "already" in result.lower()

    def test_add_respects_max_watched(self, tmp_path):
        watcher = self._make_watcher()
        for i in range(FileWatcher.MAX_WATCHED):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"content {i}")
            assert watcher.add(str(f)) is None
        # One more should fail
        extra = tmp_path / "extra.txt"
        extra.write_text("too many")
        result = watcher.add(str(extra))
        assert result is not None
        assert "maximum" in result.lower()

    def test_remove_file(self, tmp_path):
        watcher = self._make_watcher()
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        watcher.add(str(test_file))
        result = watcher.remove(str(test_file))
        assert result is None
        assert watcher.count == 0

    def test_remove_nonexistent_returns_error(self, tmp_path):
        watcher = self._make_watcher()
        result = watcher.remove(str(tmp_path / "nope.txt"))
        assert result is not None
        assert "not watching" in result.lower()

    def test_remove_all(self, tmp_path):
        watcher = self._make_watcher()
        for i in range(3):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"content {i}")
            watcher.add(str(f))
        count = watcher.remove_all()
        assert count == 3
        assert watcher.count == 0

    def test_list_watches(self, tmp_path):
        watcher = self._make_watcher()
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        watcher.add(str(test_file))
        lines = watcher.list_watches()
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_line_delta(self):
        result = FileWatcher._line_delta("line1\nline2", "line1\nline2\nline3")
        assert "+1" in result

    def test_line_delta_removal(self):
        result = FileWatcher._line_delta("line1\nline2\nline3", "line1")
        assert "-2" in result

    def test_line_delta_no_change(self):
        result = FileWatcher._line_delta("same", "same")
        assert result == ""

    def test_check_detects_change(self, tmp_path):
        watcher = self._make_watcher()
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")
        watcher.add(str(test_file))
        # Modify file
        test_file.write_text("modified content")
        watcher.check()
        # Should have called add_message callback
        watcher._add_message.assert_called()

    def test_check_detects_removal(self, tmp_path):
        watcher = self._make_watcher()
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        watcher.add(str(test_file))
        test_file.unlink()
        watcher.check()
        watcher._add_message.assert_called()
        assert watcher.count == 0

    def test_get_diff_not_watching(self, tmp_path):
        watcher = self._make_watcher()
        result = watcher.get_diff(str(tmp_path / "nope.txt"))
        assert result is None


# ===========================================================================
# ReverseSearchManager
# ===========================================================================


class TestReverseSearchManager:
    def _make_manager(self, entries=None):
        """Create a manager with mock collaborators."""
        history = MagicMock()
        history.entry_count = len(entries) if entries else 0
        history.get_entry = MagicMock(side_effect=lambda i: entries[i] if entries and 0 <= i < len(entries) else None)
        history.reverse_search_indices = MagicMock(
            side_effect=lambda q: [i for i, e in enumerate(entries or []) if q.lower() in e.lower()]
        )

        input_widget = MagicMock()
        input_widget.text = ""
        input_widget.border_subtitle = ""
        input_widget.clear = MagicMock()
        input_widget.insert = MagicMock()
        input_widget.focus = MagicMock()
        input_widget._update_line_indicator = MagicMock()

        search_bar = MagicMock()
        search_bar.show_search = MagicMock()
        search_bar.dismiss = MagicMock()

        mgr = ReverseSearchManager(
            history=history,
            get_input=MagicMock(return_value=input_widget),
            get_search_bar=MagicMock(return_value=search_bar),
        )
        return mgr, history, input_widget, search_bar

    def test_create(self):
        mgr, *_ = self._make_manager()
        assert mgr is not None
        assert mgr.active is False
        assert mgr.query == ""
        assert mgr.matches == []

    def test_start_with_empty_history(self):
        mgr, *_ = self._make_manager(entries=[])
        add_msg = MagicMock()
        mgr.start(add_message=add_msg)
        assert mgr.active is False  # Should not activate

    def test_start_activates(self):
        mgr, _, input_widget, _ = self._make_manager(entries=["hello", "world"])
        mgr.start()
        assert mgr.active is True
        input_widget.focus.assert_called()

    def test_cancel_restores_original(self):
        mgr, _, input_widget, search_bar = self._make_manager(entries=["hello"])
        input_widget.text = "original text"
        mgr.start()
        mgr.cancel()
        assert mgr.active is False
        input_widget.clear.assert_called()
        search_bar.dismiss.assert_called()

    def test_accept(self):
        mgr, *_ = self._make_manager(entries=["hello"])
        mgr.start()
        mgr.accept()
        assert mgr.active is False

    def test_do_search_with_match(self):
        mgr, history, input_widget, _ = self._make_manager(entries=["hello world", "goodbye"])
        mgr.start()
        mgr.query = "hello"
        mgr.do_search()
        assert len(mgr.matches) == 1
        assert mgr.match_idx == 0

    def test_do_search_empty_query(self):
        mgr, _, input_widget, _ = self._make_manager(entries=["hello"])
        mgr.start()
        mgr.query = ""
        mgr.do_search()
        assert mgr.matches == []
        assert mgr.match_idx == -1

    def test_do_search_no_match(self):
        mgr, *_ = self._make_manager(entries=["hello", "world"])
        mgr.start()
        mgr.query = "zzzzz"
        mgr.do_search()
        assert mgr.matches == []
        assert mgr.match_idx == -1

    def test_cycle_next(self):
        mgr, *_ = self._make_manager(entries=["hello1", "hello2", "other"])
        mgr.start()
        mgr.query = "hello"
        mgr.do_search()
        assert mgr.match_idx == 0
        mgr.cycle_next()
        assert mgr.match_idx == 1

    def test_cycle_prev(self):
        mgr, *_ = self._make_manager(entries=["hello1", "hello2"])
        mgr.start()
        mgr.query = "hello"
        mgr.do_search()
        mgr.cycle_next()
        assert mgr.match_idx == 1
        mgr.cycle_prev()
        assert mgr.match_idx == 0

    def test_cycle_wraps(self):
        mgr, *_ = self._make_manager(entries=["hello1", "hello2"])
        mgr.start()
        mgr.query = "hello"
        mgr.do_search()
        # Two matches: cycle_next twice wraps back to 0
        mgr.cycle_next()
        mgr.cycle_next()
        assert mgr.match_idx == 0
