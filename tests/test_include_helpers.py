"""Tests for include_helpers feature module."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from amplifier_tui.features.include_helpers import (
    _build_tree,
    _render_tree,
    file_preview,
    get_directory_tree,
    get_git_status_and_diff,
)


# ===========================================================================
# _build_tree
# ===========================================================================


class TestBuildTreeEmpty:
    def test_empty_file_list(self):
        result = _build_tree("myproject", [], 200)
        assert "myproject/" in result
        assert "(empty)" in result

    def test_empty_file_list_returns_two_lines(self):
        result = _build_tree("root", [], 200)
        lines = result.strip().split("\n")
        assert len(lines) == 2


class TestBuildTreeFlat:
    def test_flat_files(self):
        files = ["README.md", "setup.py", "main.py"]
        result = _build_tree("proj", files, 200)
        assert "proj/" in result
        assert "README.md" in result
        assert "setup.py" in result
        assert "main.py" in result

    def test_flat_files_sorted(self):
        files = ["c.txt", "a.txt", "b.txt"]
        result = _build_tree("proj", files, 200)
        lines = result.split("\n")
        # Files should be sorted in the tree output
        file_lines = [ln for ln in lines if ".txt" in ln]
        names = [ln.strip().split(" ")[-1] for ln in file_lines]
        assert names == ["a.txt", "b.txt", "c.txt"]


class TestBuildTreeNested:
    def test_nested_directories(self):
        files = ["src/main.py", "src/utils.py", "tests/test_main.py", "README.md"]
        result = _build_tree("proj", files, 200)
        assert "src/" in result
        assert "tests/" in result
        assert "main.py" in result
        assert "utils.py" in result
        assert "test_main.py" in result
        assert "README.md" in result

    def test_deeply_nested(self):
        files = ["a/b/c/d.txt"]
        result = _build_tree("proj", files, 200)
        assert "a/" in result
        assert "b/" in result
        assert "c/" in result
        assert "d.txt" in result


class TestBuildTreeMaxEntries:
    def test_truncation_message(self):
        files = [f"file{i}.txt" for i in range(300)]
        result = _build_tree("proj", files, 10)
        assert "... and 290 more files" in result

    def test_no_truncation_within_limit(self):
        files = [f"file{i}.txt" for i in range(5)]
        result = _build_tree("proj", files, 200)
        assert "more files" not in result

    def test_exact_limit_no_truncation(self):
        files = [f"file{i}.txt" for i in range(10)]
        result = _build_tree("proj", files, 10)
        # Exactly at limit -- no truncation message
        assert "more files" not in result


# ===========================================================================
# _render_tree (box-drawing connectors)
# ===========================================================================


class TestRenderTreeConnectors:
    def test_last_item_uses_corner(self):
        tree = {"file.txt": {}}
        lines: list[str] = []
        _render_tree(tree, lines, "")
        assert any("\u2514\u2500\u2500 " in line for line in lines)

    def test_non_last_item_uses_tee(self):
        tree = {"a.txt": {}, "b.txt": {}}
        lines: list[str] = []
        _render_tree(tree, lines, "")
        assert any("\u251c\u2500\u2500 " in line for line in lines)
        assert any("\u2514\u2500\u2500 " in line for line in lines)

    def test_directory_has_trailing_slash(self):
        tree = {"src": {"main.py": {}}}
        lines: list[str] = []
        _render_tree(tree, lines, "")
        src_lines = [ln for ln in lines if "src" in ln]
        assert any(ln.endswith("src/") for ln in src_lines)

    def test_nested_prefix_has_pipe(self):
        # Two top-level items with first being a directory
        tree = {"src": {"main.py": {}}, "z.txt": {}}
        lines: list[str] = []
        _render_tree(tree, lines, "")
        # main.py line should have a pipe prefix from "src" not being last
        main_lines = [ln for ln in lines if "main.py" in ln]
        assert len(main_lines) == 1
        assert "\u2502   " in main_lines[0]


# ===========================================================================
# file_preview
# ===========================================================================


class TestFilePreviewPython:
    def test_detects_python(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n")
        result = file_preview(f)
        assert "Language: Python" in result
        assert "hello.py" in result

    def test_shows_line_count(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("a\nb\nc\n")
        result = file_preview(f)
        assert "Lines: 3" in result


class TestFilePreviewJson:
    def test_detects_json(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}\n')
        result = file_preview(f)
        assert "Language: JSON" in result


class TestFilePreviewMissing:
    def test_missing_file(self, tmp_path):
        result = file_preview(tmp_path / "nonexistent.py")
        assert "File not found" in result

    def test_directory_not_file(self, tmp_path):
        result = file_preview(tmp_path)
        assert "Not a file" in result


class TestFilePreviewLineCount:
    def test_correct_line_count(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("\n".join(f"line {i}" for i in range(25)))
        result = file_preview(f)
        assert "Lines: 25" in result

    def test_preview_shows_first_10(self, tmp_path):
        f = tmp_path / "many.txt"
        content = "\n".join(f"line {i}" for i in range(20))
        f.write_text(content)
        result = file_preview(f)
        assert "line 0" in result
        assert "line 9" in result
        assert "10 more lines" in result

    def test_short_file_no_truncation_message(self, tmp_path):
        f = tmp_path / "short.txt"
        f.write_text("one\ntwo\nthree\n")
        result = file_preview(f)
        assert "more lines" not in result


class TestFilePreviewSizeFormat:
    def test_bytes_format(self, tmp_path):
        f = tmp_path / "tiny.txt"
        f.write_text("hi")
        result = file_preview(f)
        assert "B" in result

    def test_kilobytes_format(self, tmp_path):
        f = tmp_path / "medium.txt"
        f.write_text("x" * 2048)
        result = file_preview(f)
        assert "KB" in result

    def test_megabytes_format(self, tmp_path):
        f = tmp_path / "large.txt"
        f.write_text("x" * (1024 * 1024 + 100))
        result = file_preview(f)
        assert "MB" in result


class TestFilePreviewLanguages:
    """Test language detection for various extensions."""

    @pytest.mark.parametrize(
        "ext,expected_lang",
        [
            (".py", "Python"),
            (".js", "JavaScript"),
            (".ts", "TypeScript"),
            (".rs", "Rust"),
            (".go", "Go"),
            (".rb", "Ruby"),
            (".yaml", "YAML"),
            (".yml", "YAML"),
            (".md", "Markdown"),
            (".sh", "Shell"),
            (".html", "HTML"),
            (".css", "CSS"),
            (".sql", "SQL"),
        ],
    )
    def test_language_detection(self, tmp_path, ext, expected_lang):
        f = tmp_path / f"test{ext}"
        f.write_text("content\n")
        result = file_preview(f)
        assert f"Language: {expected_lang}" in result

    def test_unknown_extension(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("content\n")
        result = file_preview(f)
        assert "Language: XYZ" in result


# ===========================================================================
# get_git_status_and_diff
# ===========================================================================


class TestGetGitStatusNotGitRepo:
    def test_non_git_directory(self, tmp_path):
        result = get_git_status_and_diff(str(tmp_path))
        assert "not a git" in result.lower() or "unavailable" in result.lower()

    def test_returns_string(self, tmp_path):
        result = get_git_status_and_diff(str(tmp_path))
        assert isinstance(result, str)


class TestGetGitStatusInRepo:
    def test_clean_repo(self, tmp_path):
        """Create a minimal git repo and verify clean status."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        result = get_git_status_and_diff(str(tmp_path))
        assert "clean" in result.lower()

    def test_dirty_repo(self, tmp_path):
        """Create a repo with uncommitted changes."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        # Make an uncommitted change
        (tmp_path / "file.txt").write_text("changed")
        result = get_git_status_and_diff(str(tmp_path))
        assert "Git Status:" in result

    @patch("amplifier_tui.features.include_helpers.subprocess.run")
    def test_git_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        result = get_git_status_and_diff("/tmp")
        assert "unavailable" in result.lower()


# ===========================================================================
# get_directory_tree
# ===========================================================================


class TestGetDirectoryTree:
    def test_basic_tree(self, tmp_path):
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.txt").write_text("world")
        result = get_directory_tree(tmp_path)
        assert tmp_path.name in result
        assert "file1.txt" in result
        assert "file2.txt" in result

    def test_nested_tree(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')")
        (tmp_path / "README.md").write_text("# Readme")
        result = get_directory_tree(tmp_path)
        assert "src/" in result
        assert "main.py" in result
        assert "README.md" in result


class TestGetDirectoryTreeWithExcludes:
    def test_excludes_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.cpython-312.pyc").write_text("")
        (tmp_path / "main.py").write_text("print('hi')")
        result = get_directory_tree(tmp_path)
        assert "__pycache__" not in result
        assert "main.py" in result

    def test_excludes_node_modules(self, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        (project / "node_modules").mkdir()
        (project / "node_modules" / "pkg").mkdir()
        (project / "node_modules" / "pkg" / "index.js").write_text("")
        (project / "index.js").write_text("console.log('hi')")
        result = get_directory_tree(project)
        assert "node_modules" not in result
        assert "index.js" in result

    def test_excludes_venv(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "bin").mkdir()
        (tmp_path / ".venv" / "bin" / "python").write_text("")
        (tmp_path / "app.py").write_text("pass")
        result = get_directory_tree(tmp_path)
        assert ".venv" not in result
        assert "app.py" in result

    def test_excludes_git_dir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (tmp_path / "code.py").write_text("pass")
        result = get_directory_tree(tmp_path)
        assert ".git" not in result
        assert "code.py" in result

    def test_excludes_egg_info(self, tmp_path):
        (tmp_path / "mypackage.egg-info").mkdir()
        (tmp_path / "mypackage.egg-info" / "PKG-INFO").write_text("")
        (tmp_path / "setup.py").write_text("pass")
        result = get_directory_tree(tmp_path)
        assert "egg-info" not in result
        assert "setup.py" in result

    def test_max_depth(self, tmp_path):
        # Create a deeply nested structure
        deep = tmp_path
        for i in range(10):
            deep = deep / f"level{i}"
            deep.mkdir()
        (deep / "deep_file.txt").write_text("hi")
        result = get_directory_tree(tmp_path, max_depth=2)
        # Should not include files deeper than max_depth
        assert "deep_file.txt" not in result

    def test_max_entries(self, tmp_path):
        for i in range(20):
            (tmp_path / f"file{i:02d}.txt").write_text(f"content {i}")
        result = get_directory_tree(tmp_path, max_entries=5)
        assert "more files" in result


# ===========================================================================
# Command subcommands existence
# ===========================================================================


class TestCommandSubcommandsExist:
    """Verify the _cmd_include method handles all subcommands."""

    def test_cmd_include_exists(self):
        from amplifier_tui.commands.file_cmds import FileCommandsMixin

        assert hasattr(FileCommandsMixin, "_cmd_include")

    def test_cmd_include_docstring_mentions_subcommands(self):
        from amplifier_tui.commands.file_cmds import FileCommandsMixin

        doc = FileCommandsMixin._cmd_include.__doc__ or ""
        assert "tree" in doc
        assert "git" in doc
        assert "recent" in doc
        assert "preview" in doc


class TestSlashCommandsIncludeSubcommands:
    """Verify new subcommands are registered in SLASH_COMMANDS."""

    def test_include_tree_in_commands(self):
        from amplifier_tui.constants import SLASH_COMMANDS

        assert "/include tree" in SLASH_COMMANDS

    def test_include_git_in_commands(self):
        from amplifier_tui.constants import SLASH_COMMANDS

        assert "/include git" in SLASH_COMMANDS

    def test_include_recent_in_commands(self):
        from amplifier_tui.constants import SLASH_COMMANDS

        assert "/include recent" in SLASH_COMMANDS

    def test_include_preview_in_commands(self):
        from amplifier_tui.constants import SLASH_COMMANDS

        assert "/include preview" in SLASH_COMMANDS


class TestPaletteIncludeSubcommands:
    """Verify new subcommands are in the command palette."""

    def test_palette_has_include_tree(self):
        from amplifier_tui.widgets.commands import _PALETTE_COMMANDS

        names = [entry[0] for entry in _PALETTE_COMMANDS]
        assert "/include tree" in names

    def test_palette_has_include_git(self):
        from amplifier_tui.widgets.commands import _PALETTE_COMMANDS

        names = [entry[0] for entry in _PALETTE_COMMANDS]
        assert "/include git" in names

    def test_palette_has_include_recent(self):
        from amplifier_tui.widgets.commands import _PALETTE_COMMANDS

        names = [entry[0] for entry in _PALETTE_COMMANDS]
        assert "/include recent" in names

    def test_palette_has_include_preview(self):
        from amplifier_tui.widgets.commands import _PALETTE_COMMANDS

        names = [entry[0] for entry in _PALETTE_COMMANDS]
        assert "/include preview" in names
