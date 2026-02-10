"""Tests for the inline diff view feature (F2.4)."""

from __future__ import annotations

from amplifier_tui.features.diff_view import (
    _short_path,
    diff_summary,
    format_edit_diff,
    format_new_file_diff,
    new_file_summary,
)


# ===========================================================================
# format_edit_diff
# ===========================================================================


class TestFormatEditDiff:
    def test_added_lines_green(self):
        result = format_edit_diff("src/app.py", "old\n", "old\nnew\n")
        assert "[green]" in result

    def test_removed_lines_red(self):
        result = format_edit_diff("src/app.py", "old\nremoved\n", "old\n")
        assert "[red]" in result

    def test_file_path_in_header(self):
        result = format_edit_diff("src/auth.py", "a\n", "b\n")
        assert "src/auth.py" in result

    def test_no_changes_returns_dim(self):
        result = format_edit_diff("f.py", "same", "same")
        assert "[dim]" in result
        assert "No changes" in result

    def test_context_lines_dim(self):
        old = "line1\nline2\nline3\n"
        new = "line1\nchanged\nline3\n"
        result = format_edit_diff("f.py", old, new)
        # Context lines should be dim
        assert "[dim]" in result

    def test_hunk_header_cyan(self):
        result = format_edit_diff("f.py", "a\n", "b\n")
        assert "[cyan]" in result

    def test_multiline_edit(self):
        old = "def foo():\n    return 1\n"
        new = "def foo():\n    return 2\n    # updated\n"
        result = format_edit_diff("main.py", old, new)
        assert "[green]" in result
        assert "[red]" in result
        assert "main.py" in result

    def test_empty_old_string(self):
        """Replacing empty string with content (append-like edit)."""
        result = format_edit_diff("f.py", "", "new content\n")
        assert "[green]" in result

    def test_empty_new_string(self):
        """Replacing content with empty string (deletion)."""
        result = format_edit_diff("f.py", "old content\n", "")
        assert "[red]" in result

    def test_rich_markup_escaped(self):
        """Ensure Rich markup in file content is escaped."""
        result = format_edit_diff("f.py", "[bold]old[/bold]\n", "new\n")
        # The literal [bold] should be escaped, not interpreted
        assert "\\[bold]" in result or "\\[" in result


# ===========================================================================
# format_new_file_diff
# ===========================================================================


class TestFormatNewFileDiff:
    def test_all_lines_green(self):
        result = format_new_file_diff("new.py", "line1\nline2\nline3")
        assert result.count("[green]") == 3

    def test_new_file_indicator(self):
        result = format_new_file_diff("new.py", "content")
        assert "(new file)" in result

    def test_file_path_in_header(self):
        result = format_new_file_diff("src/models/user.py", "class User: pass")
        assert "src/models/user.py" in result

    def test_line_numbers_present(self):
        result = format_new_file_diff("f.py", "line1\nline2\nline3")
        assert "   1" in result
        assert "   2" in result
        assert "   3" in result

    def test_empty_content(self):
        result = format_new_file_diff("empty.py", "")
        assert "(new file)" in result

    def test_truncation_for_long_files(self):
        content = "\n".join(f"line {i}" for i in range(300))
        result = format_new_file_diff("big.py", content)
        assert "more lines" in result

    def test_no_truncation_for_short_files(self):
        content = "\n".join(f"line {i}" for i in range(10))
        result = format_new_file_diff("small.py", content)
        assert "more lines" not in result

    def test_rich_markup_escaped(self):
        result = format_new_file_diff("f.py", "[red]not markup[/red]")
        assert "\\[red]" in result or "\\[" in result


# ===========================================================================
# diff_summary
# ===========================================================================


class TestDiffSummary:
    def test_basic_summary(self):
        result = diff_summary("src/auth.py", "old\n", "old\nnew\n")
        assert "Edited" in result
        assert "auth.py" in result
        assert "+1" in result

    def test_counts_additions(self):
        old = "a\n"
        new = "a\nb\nc\n"
        result = diff_summary("f.py", old, new)
        assert "+2" in result

    def test_counts_deletions(self):
        old = "a\nb\nc\n"
        new = "a\n"
        result = diff_summary("f.py", old, new)
        assert "-2" in result

    def test_mixed_changes(self):
        old = "line1\nline2\nline3\n"
        new = "line1\nchanged\nline3\nnew_line\n"
        result = diff_summary("f.py", old, new)
        assert "Edited" in result
        # Should have both additions and deletions
        assert "+" in result
        assert "-" in result

    def test_no_changes(self):
        result = diff_summary("f.py", "same\n", "same\n")
        assert "+0" in result
        assert "-0" in result

    def test_long_path_shortened(self):
        result = diff_summary("/home/user/projects/myapp/src/auth.py", "a\n", "b\n")
        # Should show shortened path
        assert "auth.py" in result


# ===========================================================================
# new_file_summary
# ===========================================================================


class TestNewFileSummary:
    def test_basic_summary(self):
        result = new_file_summary("src/new.py", "line1\nline2\nline3")
        assert "Wrote" in result
        assert "new.py" in result
        assert "+3" in result

    def test_empty_content(self):
        result = new_file_summary("empty.py", "")
        assert "+0" in result

    def test_single_line(self):
        result = new_file_summary("f.py", "single line")
        assert "+1" in result


# ===========================================================================
# _short_path
# ===========================================================================


class TestShortPath:
    def test_short_path_unchanged(self):
        assert _short_path("src/main.py") == "src/main.py"

    def test_long_path_shortened(self):
        result = _short_path("/home/user/projects/myapp/src/main.py")
        assert result == "src/main.py" or result.count("/") <= 2

    def test_windows_path(self):
        result = _short_path("C:\\Users\\dev\\project\\src\\main.py")
        assert "main.py" in result

    def test_three_components(self):
        result = _short_path("a/b/c")
        assert result == "a/b/c"

    def test_four_components_truncated(self):
        result = _short_path("a/b/c/d")
        assert result == "b/c/d"
