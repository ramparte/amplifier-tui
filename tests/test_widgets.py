"""Widget behavioral tests -- TUI-003.

Covers dataclass construction, pure-logic methods on bar/indicator widgets,
and _PALETTE_COMMANDS data-integrity checks.  Textual DOM calls are stubbed
so tests run without a live app.
"""

from __future__ import annotations

from pathlib import Path
import pytest

# ── Datamodel imports ───────────────────────────────────────────────
from amplifier_tui.widgets import Attachment, TabState

# ── Palette commands data ───────────────────────────────────────────
from amplifier_tui.widgets.commands import _PALETTE_COMMANDS


# =====================================================================
# Import smoke tests (kept for regression)
# =====================================================================


class TestWidgetImports:
    """All widget classes are importable."""

    def test_bars_importable(self):
        from amplifier_tui.widgets import FindBar, HistorySearchBar, SuggestionBar

        assert FindBar is not None
        assert HistorySearchBar is not None
        assert SuggestionBar is not None

    def test_chat_input_importable(self):
        from amplifier_tui.widgets import ChatInput

        assert ChatInput is not None

    def test_commands_importable(self):
        from amplifier_tui.widgets import AmplifierCommandProvider

        assert AmplifierCommandProvider is not None

    def test_datamodels_importable(self):
        from amplifier_tui.widgets import Attachment, TabState

        assert TabState is not None
        assert Attachment is not None

    def test_indicators_importable(self):
        from amplifier_tui.widgets import (
            ErrorMessage,
            FoldToggle,
            NoteMessage,
            ProcessingIndicator,
            SystemMessage,
        )

        assert ErrorMessage is not None
        assert FoldToggle is not None
        assert NoteMessage is not None
        assert ProcessingIndicator is not None
        assert SystemMessage is not None

    def test_messages_importable(self):
        from amplifier_tui.widgets import (
            AssistantMessage,
            MessageMeta,
            ThinkingBlock,
            ThinkingStatic,
            UserMessage,
        )

        assert AssistantMessage is not None
        assert MessageMeta is not None
        assert ThinkingBlock is not None
        assert ThinkingStatic is not None
        assert UserMessage is not None

    def test_panels_importable(self):
        from amplifier_tui.widgets import (
            PinnedPanel,
            PinnedPanelHeader,
            PinnedPanelItem,
        )

        assert PinnedPanel is not None
        assert PinnedPanelHeader is not None
        assert PinnedPanelItem is not None

    def test_screens_importable(self):
        from amplifier_tui.widgets import HistorySearchScreen, ShortcutOverlay

        assert HistorySearchScreen is not None
        assert ShortcutOverlay is not None

    def test_tabs_importable(self):
        from amplifier_tui.widgets import TabBar, TabButton

        assert TabBar is not None
        assert TabButton is not None


# =====================================================================
# TabState  --  dataclass behavioral tests
# =====================================================================


class TestTabState:
    """TabState is a plain dataclass -- fully testable without an app."""

    def test_default_construction(self):
        ts = TabState(name="tab1", tab_id="t1", container_id="c1")
        assert ts.name == "tab1"
        assert ts.tab_id == "t1"
        assert ts.container_id == "c1"

    def test_default_values(self):
        ts = TabState(name="tab", tab_id="t", container_id="c")
        assert ts.sm_session is None
        assert ts.sm_session_id is None
        assert ts.session_title == ""
        assert ts.total_words == 0
        assert ts.user_message_count == 0
        assert ts.assistant_message_count == 0
        assert ts.tool_call_count == 0
        assert ts.user_words == 0
        assert ts.assistant_words == 0
        assert ts.response_times == []
        assert ts.tool_usage == {}
        assert ts.assistant_msg_index == 0
        assert ts.last_assistant_widget is None
        assert ts.last_assistant_text == ""
        assert ts.session_bookmarks == []
        assert ts.session_refs == []
        assert ts.message_pins == []
        assert ts.session_notes == []
        assert ts.created_at == ""
        assert ts.system_prompt == ""
        assert ts.system_preset_name == ""
        assert ts.active_mode is None
        assert ts.input_text == ""
        assert ts.custom_name == ""

    def test_mutable_defaults_isolated(self):
        """Each instance should get its own mutable containers."""
        ts1 = TabState(name="a", tab_id="1", container_id="c1")
        ts2 = TabState(name="b", tab_id="2", container_id="c2")
        ts1.search_messages.append("x")
        assert ts2.search_messages == []

    def test_field_mutation(self):
        ts = TabState(name="a", tab_id="1", container_id="c1")
        ts.user_message_count = 5
        ts.assistant_message_count = 3
        ts.total_words = 100
        assert ts.user_message_count == 5
        assert ts.assistant_message_count == 3
        assert ts.total_words == 100

    def test_response_times_accumulation(self):
        ts = TabState(name="a", tab_id="1", container_id="c1")
        ts.response_times.extend([1.2, 0.8, 2.5])
        assert len(ts.response_times) == 3
        assert sum(ts.response_times) == pytest.approx(4.5)

    def test_tool_usage_tracking(self):
        ts = TabState(name="a", tab_id="1", container_id="c1")
        ts.tool_usage["read_file"] = 10
        ts.tool_usage["bash"] = 3
        assert ts.tool_usage == {"read_file": 10, "bash": 3}


# =====================================================================
# Attachment  --  dataclass tests
# =====================================================================


class TestAttachment:
    def test_construction(self):
        a = Attachment(
            path=Path("/tmp/test.txt"),
            name="test.txt",
            content="hello world",
            language="text",
            size=11,
        )
        assert a.name == "test.txt"
        assert a.content == "hello world"
        assert a.language == "text"
        assert a.size == 11
        assert a.path == Path("/tmp/test.txt")

    def test_path_type(self):
        a = Attachment(
            path=Path("/tmp/test.py"),
            name="test.py",
            content="import os",
            language="python",
            size=9,
        )
        assert isinstance(a.path, Path)

    def test_zero_size(self):
        a = Attachment(
            path=Path("/dev/null"),
            name="empty.txt",
            content="",
            language="text",
            size=0,
        )
        assert a.size == 0
        assert a.content == ""


# =====================================================================
# _PALETTE_COMMANDS  --  data integrity (zero mocking)
# =====================================================================


class TestPaletteCommands:
    """Validate the command palette data structure."""

    def test_all_entries_are_3_tuples(self):
        for entry in _PALETTE_COMMANDS:
            assert isinstance(entry, tuple), f"Not a tuple: {entry}"
            assert len(entry) == 3, f"Wrong length: {entry}"

    def test_no_empty_display_names(self):
        for display_name, _, _ in _PALETTE_COMMANDS:
            assert display_name.strip(), f"Empty display name: {display_name}"

    def test_no_empty_descriptions(self):
        for _, description, _ in _PALETTE_COMMANDS:
            assert description.strip(), "Empty description for entry"

    def test_command_keys_format(self):
        """All keys should start with / or action:"""
        for display_name, _, key in _PALETTE_COMMANDS:
            assert key.startswith("/") or key.startswith("action:"), (
                f"Bad key format: {key!r} for {display_name}"
            )

    def test_no_duplicate_display_names(self):
        names = [name for name, _, _ in _PALETTE_COMMANDS]
        dupes = [n for n in names if names.count(n) > 1]
        assert not dupes, f"Duplicate display names: {set(dupes)}"

    def test_minimum_commands_present(self):
        """Sanity check that we have a reasonable number of commands."""
        assert len(_PALETTE_COMMANDS) >= 50


# =====================================================================
# SuggestionBar  --  state machine tests
# =====================================================================


class _TestableSuggestionBar:
    """Binds real SuggestionBar methods to a plain object (no Textual DOM)."""

    from amplifier_tui.widgets.bars import SuggestionBar as _Real

    has_suggestions = _Real.has_suggestions  # property descriptor
    set_suggestions = _Real.set_suggestions
    accept_current = _Real.accept_current
    cycle_next = _Real.cycle_next
    dismiss = _Real.dismiss
    _render_bar = _Real._render_bar
    del _Real

    def __init__(self) -> None:
        self._suggestions: list[str] = []
        self._index: int = 0
        self.display: bool = True
        self._update_calls: list[str] = []

    def update(self, text: str) -> None:
        self._update_calls.append(text)


class TestSuggestionBar:
    """Test the suggestion cycling state machine without DOM."""

    @pytest.fixture()
    def bar(self):
        return _TestableSuggestionBar()

    def test_initially_no_suggestions(self, bar):
        assert bar.has_suggestions is False

    def test_set_suggestions(self, bar):
        bar.set_suggestions(["hello", "world"])
        assert bar.has_suggestions is True
        assert bar._suggestions == ["hello", "world"]
        assert bar._index == 0

    def test_accept_current_empty(self, bar):
        assert bar.accept_current() is None

    def test_accept_current_returns_first(self, bar):
        bar.set_suggestions(["alpha", "beta"])
        assert bar.accept_current() == "alpha"

    def test_cycle_next_advances(self, bar):
        bar.set_suggestions(["a", "b", "c"])
        result = bar.cycle_next()
        assert result == "b"
        assert bar._index == 1

    def test_cycle_wraps_around(self, bar):
        bar.set_suggestions(["a", "b"])
        bar.cycle_next()  # index 1
        result = bar.cycle_next()  # wraps to 0
        assert result == "a"
        assert bar._index == 0

    def test_cycle_empty_returns_none(self, bar):
        assert bar.cycle_next() is None

    def test_dismiss_clears(self, bar):
        bar.set_suggestions(["x", "y"])
        bar.dismiss()
        assert bar.has_suggestions is False
        assert bar._index == 0

    def test_set_resets_index(self, bar):
        bar.set_suggestions(["a", "b", "c"])
        bar.cycle_next()
        bar.cycle_next()
        assert bar._index == 2
        bar.set_suggestions(["new"])
        assert bar._index == 0


# =====================================================================
# HistorySearchBar  --  display format tests
# =====================================================================


class _TestableHistoryBar:
    """Binds real HistorySearchBar methods to a plain object (no Textual DOM)."""

    from amplifier_tui.widgets.bars import HistorySearchBar as _Real

    show_search = _Real.show_search
    dismiss = _Real.dismiss
    del _Real

    def __init__(self) -> None:
        self._captured_updates: list[str] = []
        self.display: bool = False

    def update(self, text: str) -> None:
        self._captured_updates.append(text)


class TestHistorySearchBar:
    """Test search bar formatting without DOM."""

    @pytest.fixture()
    def bar(self):
        return _TestableHistoryBar()

    def test_match_found_format(self, bar):
        bar.show_search("test", "this is a test entry", index=0, total=3)
        assert bar.display is True
        assert len(bar._captured_updates) == 1
        text = bar._captured_updates[0]
        assert "reverse-i-search" in text
        assert "'test'" in text
        assert "[1/3]" in text

    def test_no_matches_format(self, bar):
        bar.show_search("xyz", None, index=0, total=0)
        assert bar.display is True
        text = bar._captured_updates[0]
        assert "reverse-i-search" in text
        assert "'xyz'" in text
        assert "no matches" in text

    def test_empty_query_format(self, bar):
        bar.show_search("", None, index=0, total=0)
        assert bar.display is True
        text = bar._captured_updates[0]
        assert "reverse-i-search" in text
        assert "type to search" in text

    def test_long_match_truncated(self, bar):
        long_match = "x" * 200
        bar.show_search("q", long_match, index=0, total=1)
        text = bar._captured_updates[0]
        # Should contain ellipsis char for truncation
        assert "\u2026" in text

    def test_dismiss_hides(self, bar):
        bar.show_search("test", "match", index=0, total=1)
        assert bar.display is True
        bar.dismiss()
        assert bar.display is False


# =====================================================================
# FoldToggle  --  label generation tests
# =====================================================================


class _TestableFoldToggle:
    """Binds real FoldToggle._make_label to a plain object (no Textual DOM)."""

    from amplifier_tui.widgets.indicators import FoldToggle as _Real

    _make_label = _Real._make_label
    del _Real

    def __init__(self, line_count: int) -> None:
        self._line_count = line_count


class TestFoldToggle:
    """Test fold/unfold label strings."""

    def _make_toggle(self, line_count: int):
        return _TestableFoldToggle(line_count)

    def test_folded_label(self):
        toggle = self._make_toggle(42)
        label = toggle._make_label(folded=True)
        assert "42 lines hidden" in label
        assert "expand" in label
        assert "\u25b6" in label  # right-pointing triangle

    def test_unfolded_label(self):
        toggle = self._make_toggle(42)
        label = toggle._make_label(folded=False)
        assert "42 lines" in label
        assert "fold" in label
        assert "\u25bc" in label  # down-pointing triangle

    def test_label_includes_count(self):
        toggle = self._make_toggle(100)
        assert "100" in toggle._make_label(folded=True)
        assert "100" in toggle._make_label(folded=False)

    def test_single_line(self):
        toggle = self._make_toggle(1)
        label = toggle._make_label(folded=True)
        assert "1 lines hidden" in label
