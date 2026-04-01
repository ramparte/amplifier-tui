"""Tests for ChatBlock widget -- Textual Pilot tests."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer

from amplifier_tui.models.block_model import BlockType
from amplifier_tui.widgets.chat_block import BlockSelected, ChatBlock


class ChatBlockTestApp(App):
    """Minimal test app for ChatBlock widget tests."""

    CSS = """
    ChatBlock { height: 1; }
    ChatBlock.selected { background: $accent; }
    ChatBlock:hover { background: $surface; }
    """

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="chat-view"):
            yield ChatBlock(
                block_id=0,
                block_type=BlockType.USER,
                turn_index=0,
                id="block-0",
            )
            yield ChatBlock(
                block_id=1,
                block_type=BlockType.ASSISTANT,
                turn_index=0,
                id="block-1",
            )
            yield ChatBlock(
                block_id=2,
                block_type=BlockType.TOOL_CALL,
                turn_index=1,
                id="block-2",
            )


class TestChatBlockConstruction:
    """ChatBlock widget construction and properties."""

    @pytest.mark.asyncio
    async def test_block_properties(self):
        async with ChatBlockTestApp().run_test() as pilot:
            app = pilot.app
            block = app.query_one("#block-0", ChatBlock)
            assert block.block_id == 0
            assert block.block_type == BlockType.USER
            assert block.turn_index == 0

    @pytest.mark.asyncio
    async def test_block_has_css_class_for_type(self):
        async with ChatBlockTestApp().run_test() as pilot:
            app = pilot.app
            block0 = app.query_one("#block-0", ChatBlock)
            assert block0.has_class("block-user")
            block1 = app.query_one("#block-1", ChatBlock)
            assert block1.has_class("block-assistant")
            block2 = app.query_one("#block-2", ChatBlock)
            assert block2.has_class("block-tool-call")

    @pytest.mark.asyncio
    async def test_three_blocks_rendered(self):
        async with ChatBlockTestApp().run_test() as pilot:
            app = pilot.app
            blocks = app.query(ChatBlock)
            assert len(blocks) == 3


class TestChatBlockMessages:
    """ChatBlock emits BlockSelected message on click."""

    @pytest.mark.asyncio
    async def test_click_emits_block_selected(self):
        messages_received = []

        class ClickTestApp(ChatBlockTestApp):
            def on_block_selected(self, event: BlockSelected) -> None:
                messages_received.append(event.block_id)

        async with ClickTestApp().run_test() as pilot:
            block = pilot.app.query_one("#block-1", ChatBlock)
            await pilot.click(block)
            await pilot.pause()  # Allow Click event to be processed
            await pilot.pause()  # Allow BlockSelected message to bubble and be delivered
            assert 1 in messages_received
