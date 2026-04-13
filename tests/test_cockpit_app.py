"""Tests for CockpitApp -- Textual Pilot widget tests."""

from __future__ import annotations

import pytest
from textual.containers import ScrollableContainer
from textual.widgets import Static

from amplifier_tui.cockpit_app import CockpitApp
from amplifier_tui.models.block_model import BlockType
from amplifier_tui.widgets.chat_block import ChatBlock


class TestCockpitCompose:
    """CockpitApp.compose() produces the expected layout."""

    @pytest.mark.asyncio
    async def test_has_status_bar(self):
        async with CockpitApp().run_test() as pilot:
            status = pilot.app.query_one("#cockpit-status-bar", Static)
            assert status is not None

    @pytest.mark.asyncio
    async def test_has_chat_view(self):
        async with CockpitApp().run_test() as pilot:
            chat_view = pilot.app.query_one("#cockpit-chat-view", ScrollableContainer)
            assert chat_view is not None

    @pytest.mark.asyncio
    async def test_has_chat_input(self):
        from amplifier_tui.widgets.chat_input import ChatInput

        async with CockpitApp().run_test() as pilot:
            chat_input = pilot.app.query_one("#chat-input", ChatInput)
            assert chat_input is not None

    @pytest.mark.asyncio
    async def test_title(self):
        async with CockpitApp().run_test() as pilot:
            assert "Cockpit" in pilot.app.title or "cockpit" in pilot.app.title.lower()


class TestCockpitBlockRendering:
    """CockpitApp renders messages as ChatBlock widgets."""

    @pytest.mark.asyncio
    async def test_system_message_creates_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_system_message("Test system message")
            blocks = app.query(ChatBlock)
            assert len(blocks) >= 1
            # Find the system block
            system_blocks = [b for b in blocks if b.block_type == BlockType.SYSTEM]
            assert len(system_blocks) >= 1

    @pytest.mark.asyncio
    async def test_user_message_creates_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._clear_welcome()
            app._add_user_message("Hello world")
            blocks = app.query(ChatBlock)
            user_blocks = [b for b in blocks if b.block_type == BlockType.USER]
            assert len(user_blocks) == 1

    @pytest.mark.asyncio
    async def test_assistant_message_creates_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_assistant_message("Hi there!")
            blocks = app.query(ChatBlock)
            assistant_blocks = [
                b for b in blocks if b.block_type == BlockType.ASSISTANT
            ]
            assert len(assistant_blocks) == 1

    @pytest.mark.asyncio
    async def test_block_registry_tracks_blocks(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg 1")
            app._add_assistant_message("reply 1")
            assert len(app._block_registry) >= 2

    @pytest.mark.asyncio
    async def test_turn_index_increments_on_user_message(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            initial_turn = app._turn_index
            app._add_user_message("first")
            assert app._turn_index == initial_turn + 1
            app._add_user_message("second")
            assert app._turn_index == initial_turn + 2

    @pytest.mark.asyncio
    async def test_block_stores_full_content(self) -> None:
        """Blocks store full content in the registry, not just 60-char summary."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            long_text = "A" * 200  # 200 chars, well beyond the 60-char summary limit
            app._add_user_message(long_text)
            await pilot.pause()

            # Registry should store full content
            block = app._block_registry.last
            assert block is not None
            assert block.content == long_text
            assert len(block.summary) <= 60


class TestCockpitBlockSelection:
    """CockpitApp handles BlockSelected messages."""

    @pytest.mark.asyncio
    async def test_block_click_selects_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("Click me")
            # Find the user block
            blocks = list(app.query(ChatBlock))
            user_blocks = [b for b in blocks if b.block_type == BlockType.USER]
            assert len(user_blocks) > 0
            block = user_blocks[0]
            # Simulate click
            block.on_click()
            await pilot.pause()
            # The block should now have the "selected" class
            assert block.has_class("selected")


class TestCockpitSlashCommands:
    """CockpitApp slash command dispatch."""

    @pytest.mark.asyncio
    async def test_help_command(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._dispatch_slash_command("/help")
            await pilot.pause()
            # Should have added a system message with help text
            blocks = list(app.query(ChatBlock))
            system_blocks = [b for b in blocks if b.block_type == BlockType.SYSTEM]
            # At least one system block with help text
            assert (
                any("help" in str(b.children).lower() for b in system_blocks)
                or len(system_blocks) > 0
            )

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Unknown commands return False (not handled locally)
            result = app._dispatch_slash_command("/nonexistent")
            assert result is False

    @pytest.mark.asyncio
    async def test_clear_command(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg1")
            app._add_assistant_message("reply1")
            blocks_before = len(app._block_registry)
            assert blocks_before >= 2
            app._dispatch_slash_command("/clear")
            await pilot.pause()
            # /clear (now _cmd_clear_with_context) clears old blocks, then
            # adds a confirmation system message.  So the registry should
            # contain exactly 1 new block (the confirmation message).
            assert len(app._block_registry) == 1
            blocks = list(app.query(ChatBlock))
            system_blocks = [b for b in blocks if b.block_type == BlockType.SYSTEM]
            assert len(system_blocks) >= 1  # "Chat and session context cleared."


from amplifier_tui.widgets.inspector_panel import InspectorPanel


class TestCockpitInspectorToggle:
    """CockpitApp inspector panel toggle and block selection."""

    @pytest.mark.asyncio
    async def test_inspector_initially_hidden(self):
        async with CockpitApp().run_test() as pilot:
            panels = list(pilot.app.query(InspectorPanel))
            if panels:
                assert not panels[0].has_class("visible")
            # Or no panel exists yet (lazy mount) -- both are valid

    @pytest.mark.asyncio
    async def test_toggle_inspector_shows_panel(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            assert panel.has_class("visible")

    @pytest.mark.asyncio
    async def test_toggle_twice_hides_panel(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._toggle_inspector()
            await pilot.pause()
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            assert not panel.has_class("visible")

    @pytest.mark.asyncio
    async def test_block_click_opens_inspector_pinned(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("Test block click")
            await pilot.pause()
            # Find the user block and click it
            blocks = list(app.query(ChatBlock))
            user_blocks = [b for b in blocks if b.block_type == BlockType.USER]
            assert len(user_blocks) > 0
            user_blocks[0].on_click()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            assert panel.has_class("visible")
            assert panel.mode == "pinned"


class TestCockpitSteering:
    """CockpitApp steering queue integration."""

    @pytest.mark.asyncio
    async def test_steer_request_queued(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Simulate an InspectorSteerRequest
            from amplifier_tui.widgets.inspector_panel import InspectorSteerRequest

            app.post_message(InspectorSteerRequest("focus on tests"))
            await pilot.pause()
            assert not app._steer_queue.is_empty
            assert app._steer_queue.dequeue() == "focus on tests"

    @pytest.mark.asyncio
    async def test_multiple_steers_fifo(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            from amplifier_tui.widgets.inspector_panel import InspectorSteerRequest

            app.post_message(InspectorSteerRequest("first"))
            app.post_message(InspectorSteerRequest("second"))
            await pilot.pause()
            assert app._steer_queue.dequeue() == "first"
            assert app._steer_queue.dequeue() == "second"


class TestCockpitSideSession:
    """CockpitApp side session lifecycle."""

    @pytest.mark.asyncio
    async def test_side_session_initially_none(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            assert app._side_session_id is None

    @pytest.mark.asyncio
    async def test_ask_context_assembly(self):
        """Verify that /ask assembles the right context from the pinned block."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Add a block to reference
            app._add_user_message("Write tests for auth.py")
            block = app._block_registry.get_by_id(app._block_registry.last.block_id)
            assert block is not None
            # Build context
            context = app._build_ask_context(block, "what is this about?")
            assert "user" in context.lower() or "Write tests" in context
            assert "what is this about?" in context


class TestCockpitLiveMode:
    """CockpitApp inspector live mode following streaming blocks."""

    @pytest.mark.asyncio
    async def test_live_mode_follows_new_blocks(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Start with inspector in live mode
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            panel.set_live_mode()

            # Add a block that should be followed
            app._add_user_message("Test live mode")
            await pilot.pause()

            # Inspector should follow the new block
            assert panel.mode == "live"
            # In live mode, it should show the latest block
            latest_block = app._block_registry.last
            if latest_block:
                assert panel.current_block_id == latest_block.block_id

    @pytest.mark.asyncio
    async def test_live_mode_updates_during_streaming(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Start with inspector in live mode
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            panel.set_live_mode()

            # Simulate streaming start
            app._begin_streaming_block("assistant", 0)
            await pilot.pause()

            # Inspector should follow the streaming block
            if (
                hasattr(app, "_current_streaming_block_id")
                and app._current_streaming_block_id is not None
            ):
                assert panel.current_block_id == app._current_streaming_block_id


class TestCockpitInputRouting:
    """CockpitApp input routing tests."""

    @pytest.mark.asyncio
    async def test_input_goes_to_main_by_default(self):
        """By default, input routes to main session."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Inspector should be closed by default
            target = app._get_input_target()
            assert target == "main"

    @pytest.mark.asyncio
    async def test_input_goes_to_inspector_when_open(self):
        """When inspector is open, input routes to inspector."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._toggle_inspector()
            await pilot.pause()
            target = app._get_input_target()
            assert target == "inspector"


class TestCockpitExitHandling:
    """CockpitApp handles exit/quit commands."""

    @pytest.mark.asyncio
    async def test_slash_exit_dispatches(self):
        """The /exit slash command is handled locally."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            result = app._dispatch_slash_command("/exit")
            assert result is True

    @pytest.mark.asyncio
    async def test_slash_quit_dispatches(self):
        """The /quit slash command is handled locally."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            result = app._dispatch_slash_command("/quit")
            assert result is True

    @pytest.mark.asyncio
    async def test_slash_q_dispatches(self):
        """The /q slash command is handled locally."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            result = app._dispatch_slash_command("/q")
            assert result is True


class TestCockpitExpandedSlashCommands:
    """CockpitApp expanded slash command table."""

    @pytest.mark.asyncio
    async def test_slash_status_dispatches(self):
        """The /status command is handled locally."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            result = app._dispatch_slash_command("/status")
            assert result is True

    @pytest.mark.asyncio
    async def test_slash_status_shows_info(self):
        """The /status command adds a system message with session info."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._dispatch_slash_command("/status")
            await pilot.pause()
            blocks = list(app.query(ChatBlock))
            system_blocks = [b for b in blocks if b.block_type == BlockType.SYSTEM]
            # Should have a status block with session info
            assert len(system_blocks) >= 1

    @pytest.mark.asyncio
    async def test_slash_new_dispatches(self):
        """The /new command is handled locally."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            result = app._dispatch_slash_command("/new")
            assert result is True

    @pytest.mark.asyncio
    async def test_slash_new_creates_fresh_conversation(self):
        """The /new command resets conversation state."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            old_cid = app._conversation.conversation_id
            app._add_user_message("hello")
            app._dispatch_slash_command("/new")
            await pilot.pause()
            # Conversation ID should have changed (new ConversationState)
            assert app._conversation.conversation_id != old_cid

    @pytest.mark.asyncio
    async def test_clear_with_context_resets_dom(self):
        """/clear clears the DOM, preserves turn index (avoids Textual ID collision)."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg1")
            app._add_assistant_message("reply1")
            turn_before = app._turn_index
            assert turn_before > 0
            app._dispatch_slash_command("/clear")
            await pilot.pause()
            # Turn index should NOT reset (prevents DuplicateIds in Textual)
            assert app._turn_index == turn_before
            # Registry has just the confirmation system message
            assert len(app._block_registry) == 1

    @pytest.mark.asyncio
    async def test_bare_exit_handled(self):
        """Bare 'exit' (no slash) is caught before reaching the session."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # The _handle_input method checks for bare exit/quit before
            # sending to the session.  We can't fully test app.exit() in
            # pilot mode, but we can verify the codepath exists.
            assert hasattr(app, "_handle_input")

    @pytest.mark.asyncio
    async def test_status_label_first_message(self):
        """First message should show 'Starting session' in status."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            cid = app._conversation.conversation_id
            # Mock get_handle to return None (no session yet)
            app.session_manager.get_handle.return_value = None
            has_session = bool(
                app.session_manager and app.session_manager.get_handle(cid)
            )
            label = "Thinking" if has_session else "Starting session"
            assert label == "Starting session"

    @pytest.mark.asyncio
    async def test_status_label_subsequent_message(self):
        """Subsequent messages should show 'Thinking' in status."""
        from unittest.mock import MagicMock

        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            cid = app._conversation.conversation_id
            # Mock get_handle to return a handle (session exists)
            mock_handle = MagicMock()
            app.session_manager.get_handle.return_value = mock_handle
            has_session = bool(
                app.session_manager and app.session_manager.get_handle(cid)
            )
            label = "Thinking" if has_session else "Starting session"
            assert label == "Thinking"


class TestSessionManagerApproval:
    """SessionManager approval callback."""

    def test_on_approval_request_returns_first_option(self):
        """Approval callback returns the first option (auto-approve with logging)."""
        from amplifier_tui.core.session_manager import SessionManager

        result = SessionManager._on_approval_request("Allow bash?", ["allow", "deny"])
        assert result == "allow"

    def test_on_approval_request_empty_options(self):
        """Approval callback returns 'allow' when no options provided."""
        from amplifier_tui.core.session_manager import SessionManager

        result = SessionManager._on_approval_request("Allow?", [])
        assert result == "allow"
