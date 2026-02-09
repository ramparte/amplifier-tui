"""Command mixin import and attribute tests.

Command mixins depend on ``self`` being a full Textual app instance,
so we test importability and verify that expected method names exist.
"""

from __future__ import annotations

from amplifier_tui.commands import (
    ContentCommandsMixin,
    DisplayCommandsMixin,
    ExportCommandsMixin,
    FileCommandsMixin,
    GitCommandsMixin,
    PersistenceCommandsMixin,
    SearchCommandsMixin,
    SessionCommandsMixin,
    SplitCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    WatchCommandsMixin,
)


class TestCommandImports:
    """All command mixins should be importable."""

    def test_all_mixins_importable(self):
        # If we got here without ImportError, all imports succeeded
        assert True

    def test_session_mixin_type(self):
        assert isinstance(SessionCommandsMixin, type)

    def test_display_mixin_type(self):
        assert isinstance(DisplayCommandsMixin, type)

    def test_content_mixin_type(self):
        assert isinstance(ContentCommandsMixin, type)

    def test_file_mixin_type(self):
        assert isinstance(FileCommandsMixin, type)

    def test_persistence_mixin_type(self):
        assert isinstance(PersistenceCommandsMixin, type)

    def test_search_mixin_type(self):
        assert isinstance(SearchCommandsMixin, type)

    def test_git_mixin_type(self):
        assert isinstance(GitCommandsMixin, type)

    def test_theme_mixin_type(self):
        assert isinstance(ThemeCommandsMixin, type)

    def test_token_mixin_type(self):
        assert isinstance(TokenCommandsMixin, type)

    def test_export_mixin_type(self):
        assert isinstance(ExportCommandsMixin, type)

    def test_split_mixin_type(self):
        assert isinstance(SplitCommandsMixin, type)

    def test_watch_mixin_type(self):
        assert isinstance(WatchCommandsMixin, type)


class TestSessionCommandsMixin:
    def test_has_cmd_new(self):
        assert hasattr(SessionCommandsMixin, "_cmd_new")

    def test_has_cmd_sessions(self):
        assert hasattr(SessionCommandsMixin, "_cmd_sessions")


class TestDisplayCommandsMixin:
    def test_has_cmd_compact(self):
        assert hasattr(DisplayCommandsMixin, "_cmd_compact")

    def test_has_cmd_timestamps(self):
        assert hasattr(DisplayCommandsMixin, "_cmd_timestamps")


class TestGitCommandsMixin:
    def test_has_cmd_git(self):
        assert hasattr(GitCommandsMixin, "_cmd_git")

    def test_has_cmd_diff(self):
        assert hasattr(GitCommandsMixin, "_cmd_diff")


class TestExportCommandsMixin:
    def test_has_cmd_export(self):
        assert hasattr(ExportCommandsMixin, "_cmd_export")


class TestSearchCommandsMixin:
    def test_has_cmd_search(self):
        assert hasattr(SearchCommandsMixin, "_cmd_search")

    def test_has_cmd_grep(self):
        assert hasattr(SearchCommandsMixin, "_cmd_grep")


class TestContentCommandsMixin:
    def test_has_cmd_copy(self):
        assert hasattr(ContentCommandsMixin, "_cmd_copy")


class TestFileCommandsMixin:
    def test_has_cmd_include(self):
        assert hasattr(FileCommandsMixin, "_cmd_include")


class TestPersistenceCommandsMixin:
    def test_has_cmd_bookmark(self):
        assert hasattr(PersistenceCommandsMixin, "_cmd_bookmark")

    def test_has_cmd_snippet(self):
        assert hasattr(PersistenceCommandsMixin, "_cmd_snippet")


class TestThemeCommandsMixin:
    def test_has_cmd_theme(self):
        assert hasattr(ThemeCommandsMixin, "_cmd_theme")

    def test_has_cmd_colors(self):
        assert hasattr(ThemeCommandsMixin, "_cmd_colors")


class TestTokenCommandsMixin:
    def test_has_cmd_tokens(self):
        assert hasattr(TokenCommandsMixin, "_cmd_tokens")


class TestSplitCommandsMixin:
    def test_has_cmd_split(self):
        assert hasattr(SplitCommandsMixin, "_cmd_split")


class TestWatchCommandsMixin:
    def test_has_cmd_watch(self):
        assert hasattr(WatchCommandsMixin, "_cmd_watch")
