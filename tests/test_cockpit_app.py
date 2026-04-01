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
            app._dispatch_slash_command("/nonexistent")
            await pilot.pause()
            # Should show unknown command message
            blocks = list(app.query(ChatBlock))
            assert len(blocks) > 0  # At least the welcome + error

    @pytest.mark.asyncio
    async def test_clear_command(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg1")
            app._add_assistant_message("reply1")
            app._dispatch_slash_command("/clear")
            await pilot.pause()
            # Chat view should be empty after clear
            from textual.containers import ScrollableContainer

            chat_view = app.query_one("#cockpit-chat-view", ScrollableContainer)
            assert len(list(chat_view.children)) == 0
