"""Behavioral tests for command mixins -- TUI-002.

Uses a lightweight MockApp base class that satisfies the self.* contracts
each mixin relies on.  Tests verify state changes, system messages, and
persistence calls rather than just importability.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

# ── Imports under test ──────────────────────────────────────────────
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
from amplifier_tui.preferences import THEMES


# ── Mock infrastructure ─────────────────────────────────────────────


@dataclass
class _MockDisplay:
    show_timestamps: bool = True
    word_wrap: bool = True
    compact_mode: bool = False
    vim_mode: bool = False
    streaming_enabled: bool = True
    editor_auto_send: bool = False
    multiline_default: bool = False
    show_token_usage: bool = True
    context_window_size: int = 0
    fold_threshold: int = 20
    show_suggestions: bool = True
    progress_labels: bool = True


@dataclass
class _MockPrefs:
    display: _MockDisplay = field(default_factory=_MockDisplay)
    theme_name: str = "dark"

    # Minimal colors stub used by theme apply
    class _Colors:
        pass

    colors: _Colors = field(default_factory=_Colors)

    def apply_theme(self, name: str) -> bool:
        if name in THEMES:
            self.theme_name = name
            return True
        return False


class MockApp:
    """Minimal stub satisfying the self.* contract for command mixins."""

    def __init__(self) -> None:
        self._prefs = _MockPrefs()
        self._search_messages: list[tuple[str, str, object | None]] = []
        self._last_search_results: list = []
        self._previewing_theme: str | None = None
        self._session_title: str = ""
        self._snippets: dict = {}
        self._aliases: dict = {}
        self._message_pins: list = []
        self._session_notes: list = []
        self._session_refs: list = []
        self._messages: list[str] = []  # captures _add_system_message
        self._classes_added: list[str] = []
        self._classes_removed: list[str] = []

        self.theme: str = "textual-dark"
        self._timestamp_timer = None
        self.is_processing = False
        self._amplifier_available = True
        self._amplifier_ready = True
        self.session_manager = None
        self._new_session_called = False
        self._user_words = 100
        self._assistant_words = 200

    # ── shared contract stubs ──
    def _add_system_message(self, text: str) -> None:
        self._messages.append(text)

    def _update_status(self) -> None:
        pass

    def _apply_theme_to_all_widgets(self) -> None:
        pass

    def _save_snippets(self) -> None:
        pass

    def _save_message_pins(self) -> None:
        pass

    def _save_notes(self) -> None:
        pass

    def _save_refs(self) -> None:
        pass

    def action_new_session(self) -> None:
        self._new_session_called = True

    # Textual DOM stubs
    def add_class(self, cls: str) -> None:
        self._classes_added.append(cls)

    def remove_class(self, cls: str) -> None:
        self._classes_removed.append(cls)

    def query(self, selector: str):  # noqa: ARG002
        return []

    # Snippet helpers (static on real app)
    @staticmethod
    def _snippet_content(data: dict | str) -> str:
        if isinstance(data, dict):
            return data.get("content", "")
        return data

    @staticmethod
    def _snippet_category(data: dict | str) -> str:
        if isinstance(data, dict):
            return data.get("category", "")
        return ""


# ── Testable composites ─────────────────────────────────────────────


class _CompactApp(DisplayCommandsMixin, MockApp):
    def __init__(self) -> None:
        MockApp.__init__(self)


class _ThemeApp(ThemeCommandsMixin, MockApp):
    def __init__(self) -> None:
        MockApp.__init__(self)


class _SearchApp(SearchCommandsMixin, MockApp):
    def __init__(self) -> None:
        MockApp.__init__(self)


class _SnippetApp(PersistenceCommandsMixin, MockApp):
    def __init__(self) -> None:
        MockApp.__init__(self)


class _SessionApp(SessionCommandsMixin, MockApp):
    def __init__(self) -> None:
        MockApp.__init__(self)


class _ExportApp(ExportCommandsMixin, MockApp):
    def __init__(self) -> None:
        MockApp.__init__(self)


# =====================================================================
# Import / existence smoke tests (kept for regression)
# =====================================================================


class TestCommandImports:
    """All command mixins are importable and are types."""

    def test_all_mixins_importable(self):
        assert True  # import at top succeeded

    @pytest.mark.parametrize(
        "cls",
        [
            SessionCommandsMixin,
            DisplayCommandsMixin,
            ContentCommandsMixin,
            FileCommandsMixin,
            PersistenceCommandsMixin,
            SearchCommandsMixin,
            GitCommandsMixin,
            ThemeCommandsMixin,
            TokenCommandsMixin,
            ExportCommandsMixin,
            SplitCommandsMixin,
            WatchCommandsMixin,
        ],
    )
    def test_mixin_is_type(self, cls):
        assert isinstance(cls, type)


# =====================================================================
# /compact  --  DisplayCommandsMixin
# =====================================================================


class TestCmdCompact:
    def test_toggle_on_from_off(self, monkeypatch):
        monkeypatch.setattr(
            "amplifier_tui.commands.display_cmds.save_compact_mode", lambda v: None
        )
        app = _CompactApp()
        assert app._prefs.display.compact_mode is False

        app._cmd_compact("/compact")
        assert app._prefs.display.compact_mode is True
        assert "compact-mode" in app._classes_added
        assert any("ON" in m for m in app._messages)

    def test_toggle_off_from_on(self, monkeypatch):
        monkeypatch.setattr(
            "amplifier_tui.commands.display_cmds.save_compact_mode", lambda v: None
        )
        app = _CompactApp()
        app._prefs.display.compact_mode = True

        app._cmd_compact("/compact")
        assert app._prefs.display.compact_mode is False
        assert "compact-mode" in app._classes_removed
        assert any("OFF" in m for m in app._messages)

    def test_explicit_on(self, monkeypatch):
        monkeypatch.setattr(
            "amplifier_tui.commands.display_cmds.save_compact_mode", lambda v: None
        )
        app = _CompactApp()
        app._cmd_compact("/compact on")
        assert app._prefs.display.compact_mode is True

    def test_explicit_off(self, monkeypatch):
        monkeypatch.setattr(
            "amplifier_tui.commands.display_cmds.save_compact_mode", lambda v: None
        )
        app = _CompactApp()
        app._prefs.display.compact_mode = True
        app._cmd_compact("/compact off")
        assert app._prefs.display.compact_mode is False

    def test_bad_arg_shows_usage(self, monkeypatch):
        monkeypatch.setattr(
            "amplifier_tui.commands.display_cmds.save_compact_mode", lambda v: None
        )
        app = _CompactApp()
        app._cmd_compact("/compact banana")
        assert any("Usage" in m for m in app._messages)
        # compact_mode unchanged
        assert app._prefs.display.compact_mode is False


# =====================================================================
# /theme  --  ThemeCommandsMixin
# =====================================================================


class TestCmdTheme:
    def _patch_saves(self, monkeypatch):
        monkeypatch.setattr(
            "amplifier_tui.core.commands.theme_cmds.save_colors", lambda c: None
        )
        monkeypatch.setattr(
            "amplifier_tui.core.commands.theme_cmds.save_theme_name", lambda n: None
        )

    def test_list_themes_no_arg(self, monkeypatch):
        self._patch_saves(monkeypatch)
        app = _ThemeApp()
        app._cmd_theme("/theme")
        assert len(app._messages) == 1
        assert "Available themes" in app._messages[0]

    def test_apply_known_theme(self, monkeypatch):
        self._patch_saves(monkeypatch)
        # Pick the first available theme that isn't the default
        first_theme = next(iter(THEMES))
        app = _ThemeApp()
        app._cmd_theme(f"/theme {first_theme}")
        assert app._prefs.theme_name == first_theme
        assert any(first_theme in m for m in app._messages)

    def test_apply_unknown_theme(self, monkeypatch):
        self._patch_saves(monkeypatch)
        app = _ThemeApp()
        app._cmd_theme("/theme nonexistent_theme_xyz")
        assert "Unknown theme" in app._messages[0]
        assert app._prefs.theme_name == "dark"  # unchanged

    def test_apply_clears_preview(self, monkeypatch):
        self._patch_saves(monkeypatch)
        first_theme = next(iter(THEMES))
        app = _ThemeApp()
        app._previewing_theme = "some_preview"
        app._cmd_theme(f"/theme {first_theme}")
        assert app._previewing_theme is None


# =====================================================================
# /search here  --  SearchCommandsMixin
# =====================================================================


class TestCmdSearchHere:
    def test_search_finds_match(self):
        app = _SearchApp()
        app._search_messages = [
            ("user", "Hello world", None),
            ("assistant", "Goodbye world", None),
            ("user", "Nothing to see", None),
        ]
        app._search_current_chat("world")
        assert len(app._messages) == 1
        assert "2 matches" in app._messages[0]
        assert "world" in app._messages[0].lower()

    def test_search_no_match(self):
        app = _SearchApp()
        app._search_messages = [("user", "Hello", None)]
        app._search_current_chat("zzzzz")
        assert "No matches" in app._messages[0]

    def test_search_empty_query_shows_usage(self):
        app = _SearchApp()
        app._search_current_chat("")
        assert "Usage" in app._messages[0]

    def test_search_case_insensitive(self):
        app = _SearchApp()
        app._search_messages = [("user", "Python is great", None)]
        app._search_current_chat("PYTHON")
        assert "1 match" in app._messages[0]

    def test_search_dispatch_here(self):
        """'/search here foo' routes to _search_current_chat."""
        app = _SearchApp()
        app._search_messages = [("user", "foo bar baz", None)]
        app._cmd_search("/search here foo")
        assert len(app._messages) == 1
        assert "1 match" in app._messages[0]

    def test_search_no_query_shows_usage(self):
        app = _SearchApp()
        app._cmd_search("/search")
        assert "Usage" in app._messages[0]


# =====================================================================
# /snippet  --  PersistenceCommandsMixin
# =====================================================================


class TestCmdSnippet:
    def test_snippet_list_empty(self):
        app = _SnippetApp()
        app._cmd_snippet("")
        assert "No snippets" in app._messages[0]

    def test_snippet_save_and_list(self):
        app = _SnippetApp()
        app._cmd_snippet_save(["save", "greeting", "Hello there!"])
        assert "greeting" in app._snippets
        assert app._snippets["greeting"]["content"] == "Hello there!"
        assert any("greeting" in m and "saved" in m for m in app._messages)

    def test_snippet_save_with_category(self):
        app = _SnippetApp()
        app._cmd_snippet_save(["save", "greeting", "#social Hello there!"])
        assert app._snippets["greeting"]["category"] == "social"

    def test_snippet_delete(self):
        app = _SnippetApp()
        app._snippets["tmp"] = {"content": "x", "category": "", "created": "2026-01-01"}
        app._cmd_snippet("delete tmp")
        assert "tmp" not in app._snippets
        assert any("deleted" in m for m in app._messages)

    def test_snippet_delete_missing(self):
        app = _SnippetApp()
        app._cmd_snippet("delete nope")
        assert any("No snippet" in m for m in app._messages)

    def test_snippet_clear(self):
        app = _SnippetApp()
        app._snippets = {"a": {"content": "1"}, "b": {"content": "2"}}
        app._cmd_snippet("clear")
        assert app._snippets == {}
        assert any("cleared" in m for m in app._messages)

    def test_snippet_save_invalid_name(self):
        app = _SnippetApp()
        app._cmd_snippet_save(["save", "bad name!", "content"])
        assert "alphanumeric" in app._messages[0]

    def test_snippet_save_missing_args(self):
        app = _SnippetApp()
        app._cmd_snippet_save(["save"])
        assert "Usage" in app._messages[0]


# =====================================================================
# /new  --  SessionCommandsMixin
# =====================================================================


class TestCmdNew:
    def test_new_delegates_to_action(self):
        app = _SessionApp()
        app._cmd_new()
        assert app._new_session_called is True


# =====================================================================
# /export  --  ExportCommandsMixin
# =====================================================================


class TestCmdExport:
    def test_export_empty_chat(self):
        app = _ExportApp()
        app._cmd_export("/export")
        assert any("No messages" in m for m in app._messages)

    def test_export_help(self):
        app = _ExportApp()
        app._cmd_export("/export help")
        assert any("Export conversation" in m or "Markdown" in m for m in app._messages)

    def test_export_markdown_to_file(self, tmp_path, monkeypatch):
        app = _ExportApp()
        app._search_messages = [
            ("user", "Hello", None),
            ("assistant", "World", None),
        ]
        out = tmp_path / "test-export.md"
        app._cmd_export(f"/export md {out}")
        assert out.exists()
        content = out.read_text()
        assert "Hello" in content
        assert "World" in content
        assert any("Exported" in m or "export" in m.lower() for m in app._messages)


# =====================================================================
# /search open  --  SearchCommandsMixin
# =====================================================================


class TestCmdSearchOpen:
    def test_open_no_results(self):
        app = _SearchApp()
        app._cmd_search("/search open 1")
        assert "No search results" in app._messages[0]

    def test_open_invalid_number(self):
        app = _SearchApp()
        app._last_search_results = [{"session_id": "s1"}]
        app._search_open_result("abc")
        assert "Usage" in app._messages[0]

    def test_open_out_of_range(self):
        app = _SearchApp()
        app._last_search_results = [{"session_id": "s1"}]
        app._search_open_result("5")
        assert "Invalid" in app._messages[0]
