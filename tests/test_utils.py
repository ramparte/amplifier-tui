"""Tests for the _utils module."""

from __future__ import annotations

from amplifier_tui._utils import (
    _context_color,
    _context_color_name,
    _get_tool_label,
)


class TestContextColor:
    def test_green_low(self):
        assert _context_color(10) == "#44aa44"

    def test_green_boundary(self):
        assert _context_color(49.9) == "#44aa44"

    def test_yellow(self):
        assert _context_color(50) == "#ffaa00"

    def test_orange(self):
        assert _context_color(75) == "#ff8800"

    def test_red(self):
        assert _context_color(90) == "#ff4444"

    def test_red_extreme(self):
        assert _context_color(100) == "#ff4444"

    def test_returns_string(self):
        for pct in (0, 25, 50, 75, 90, 100):
            result = _context_color(pct)
            assert isinstance(result, str)
            assert result.startswith("#")


class TestContextColorName:
    def test_green(self):
        assert _context_color_name(10) == "green"

    def test_yellow(self):
        assert _context_color_name(60) == "yellow"

    def test_orange(self):
        assert _context_color_name(80) == "orange"

    def test_red(self):
        assert _context_color_name(95) == "red"

    def test_boundary_50(self):
        assert _context_color_name(50) == "yellow"

    def test_boundary_75(self):
        assert _context_color_name(75) == "orange"

    def test_boundary_90(self):
        assert _context_color_name(90) == "red"


class TestGetToolLabel:
    def test_known_tool(self):
        result = _get_tool_label("read_file", None)
        assert isinstance(result, str)
        assert result.endswith("...")

    def test_unknown_tool(self):
        result = _get_tool_label("unknown_tool", None)
        assert "unknown_tool" in result
        assert result.endswith("...")

    def test_read_file_with_path(self):
        result = _get_tool_label("read_file", {"file_path": "/some/dir/config.py"})
        assert "config.py" in result

    def test_grep_with_pattern(self):
        result = _get_tool_label("grep", {"pattern": "TODO"})
        assert "TODO" in result

    def test_delegate_with_agent(self):
        result = _get_tool_label("delegate", {"agent": "foundation:explorer"})
        assert "explorer" in result

    def test_bash_with_command(self):
        result = _get_tool_label("bash", {"command": "ls -la"})
        assert "ls" in result

    def test_web_fetch_with_url(self):
        result = _get_tool_label("web_fetch", {"url": "https://example.com/page"})
        assert "example.com" in result

    def test_web_search_with_query(self):
        result = _get_tool_label("web_search", {"query": "python tutorial"})
        assert "python" in result

    def test_glob_with_pattern(self):
        result = _get_tool_label("glob", {"pattern": "**/*.py"})
        assert "*.py" in result

    def test_lsp_with_operation(self):
        result = _get_tool_label("LSP", {"operation": "goToDefinition"})
        assert "goToDefinition" in result

    def test_python_check_with_path(self):
        result = _get_tool_label("python_check", {"paths": ["src/main.py"]})
        assert "main.py" in result

    def test_load_skill_with_name(self):
        result = _get_tool_label("load_skill", {"skill_name": "python-patterns"})
        assert "python-patterns" in result

    def test_todo_with_action(self):
        result = _get_tool_label("todo", {"action": "create"})
        assert "create" in result

    def test_recipes_with_operation(self):
        result = _get_tool_label("recipes", {"operation": "execute"})
        assert "execute" in result

    def test_truncation(self):
        """Very long labels get truncated."""
        result = _get_tool_label("bash", {"command": "a" * 200})
        # Should be truncated to ~38 chars + "..."
        assert len(result) <= 42  # _MAX_LABEL_LEN + "..."

    def test_string_input_treated_as_empty(self):
        """When tool_input is a string instead of dict, treat as empty."""
        result = _get_tool_label("read_file", "some string")
        assert isinstance(result, str)

    def test_none_input(self):
        result = _get_tool_label("read_file", None)
        assert isinstance(result, str)
