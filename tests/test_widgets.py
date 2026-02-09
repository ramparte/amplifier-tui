"""Widget import and basic instantiation tests.

Widget classes generally require a Textual App context to fully instantiate,
so these tests focus on importability and dataclass construction.
"""

from __future__ import annotations

from pathlib import Path


class TestWidgetImports:
    """Verify that all widgets can be imported without error."""

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
        from amplifier_tui.widgets import PinnedPanel, PinnedPanelHeader, PinnedPanelItem
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


class TestTabState:
    """TabState is a plain dataclass — can be tested without an app."""

    def test_default_construction(self):
        from amplifier_tui.widgets import TabState
        ts = TabState(name="tab1", tab_id="t1", container_id="c1")
        assert ts.name == "tab1"
        assert ts.tab_id == "t1"
        assert ts.container_id == "c1"

    def test_default_values(self):
        from amplifier_tui.widgets import TabState
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
        from amplifier_tui.widgets import TabState
        ts1 = TabState(name="a", tab_id="1", container_id="c1")
        ts2 = TabState(name="b", tab_id="2", container_id="c2")
        ts1.search_messages.append("x")
        assert ts2.search_messages == []


class TestAttachment:
    def test_construction(self):
        from amplifier_tui.widgets import Attachment
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
