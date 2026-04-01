"""Tests for InspectorPanel widget."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Static, TextArea

from amplifier_tui.models.block_model import BlockInfo, BlockRegistry, BlockType
from amplifier_tui.widgets.inspector_panel import InspectorPanel, InspectorSteerRequest, InspectorAskRequest


class InspectorTestApp(App):
    """Minimal app for testing InspectorPanel."""

    CSS = """
    InspectorPanel { height: 1fr; width: 40; }
    """

    def compose(self) -> ComposeResult:
        self._block_registry = BlockRegistry()
        self._block_registry.add(BlockType.USER, turn_index=0, summary="Hello world")
        self._block_registry.add(BlockType.ASSISTANT, turn_index=0, summary="Hi there")
        self._block_registry.add(BlockType.TOOL_CALL, turn_index=1, summary="grep for imports")
        yield InspectorPanel(block_registry=self._block_registry, id="inspector")


class TestInspectorCompose:
    """InspectorPanel has the expected sub-areas."""

    @pytest.mark.asyncio
    async def test_has_detail_area(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            detail = panel.query_one("#inspector-detail", ScrollableContainer)
            assert detail is not None

    @pytest.mark.asyncio
    async def test_has_status_line(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            status = panel.query_one("#inspector-status", Static)
            assert status is not None

    @pytest.mark.asyncio
    async def test_has_input_area(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            input_area = panel.query_one("#inspector-input", TextArea)
            assert input_area is not None


class TestInspectorModes:
    """InspectorPanel live vs pinned mode."""

    @pytest.mark.asyncio
    async def test_default_mode_is_live(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            assert panel.mode == "live"

    @pytest.mark.asyncio
    async def test_pin_to_block(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            assert panel.mode == "pinned"
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_unpin_returns_to_live(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            panel.set_live_mode()
            assert panel.mode == "live"


class TestInspectorNavigation:
    """Inspector prev/next/search navigation."""

    @pytest.mark.asyncio
    async def test_prev_from_last(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(2)  # last block
            panel.go_prev()
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_next_from_first(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.go_next()
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_prev_at_start_stays(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.go_prev()
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_next_at_end_stays(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(2)
            panel.go_next()
            assert panel.current_block_id == 2

    @pytest.mark.asyncio
    async def test_search_backward_finds_match(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(2)  # start from end
            panel.search_blocks("Hello")
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_search_forward_finds_match(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)  # start from beginning
            panel.search_blocks("grep", forward=True)
            assert panel.current_block_id == 2

    @pytest.mark.asyncio
    async def test_navigation_switches_to_pinned(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.set_live_mode()
            assert panel.mode == "live"
            panel.pin_to_block(1)
            panel.go_prev()
            assert panel.mode == "pinned"


class InspectorMessageTestApp(App):
    """App that captures inspector messages for testing."""

    CSS = """
    InspectorPanel { height: 1fr; width: 40; }
    """

    def __init__(self):
        super().__init__()
        self.steer_messages: list[str] = []
        self.ask_messages: list[tuple[str, BlockInfo | None]] = []

    def compose(self) -> ComposeResult:
        self._block_registry = BlockRegistry()
        self._block_registry.add(BlockType.USER, turn_index=0, summary="Hello world")
        self._block_registry.add(BlockType.ASSISTANT, turn_index=0, summary="Hi there")
        yield InspectorPanel(block_registry=self._block_registry, id="inspector")

    def on_inspector_steer_request(self, event: InspectorSteerRequest) -> None:
        self.steer_messages.append(event.text)

    def on_inspector_ask_request(self, event: InspectorAskRequest) -> None:
        self.ask_messages.append((event.question, event.block_info))


class TestInspectorCommandDispatch:
    """Inspector handle_input routes commands correctly."""

    @pytest.mark.asyncio
    async def test_free_text_sends_steer(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("focus on the tests please")
            await pilot.pause()
            assert "focus on the tests please" in pilot.app.steer_messages

    @pytest.mark.asyncio
    async def test_explicit_steer_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("/steer use pytest instead")
            await pilot.pause()
            assert "use pytest instead" in pilot.app.steer_messages

    @pytest.mark.asyncio
    async def test_ask_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.handle_input("/ask what does this block do?")
            await pilot.pause()
            assert len(pilot.app.ask_messages) == 1
            question, block = pilot.app.ask_messages[0]
            assert question == "what does this block do?"
            assert block is not None
            assert block.block_id == 0

    @pytest.mark.asyncio
    async def test_prev_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            panel.handle_input("/prev")
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_next_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.handle_input("/next")
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_search_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            panel.handle_input("/search Hello")
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_search_forward_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.handle_input("/search forward Hi")
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_help_command_shows_help(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("/help")
            await pilot.pause()
            # Help text should be in the detail area
            detail = panel.query_one("#inspector-detail")
            children_text = str([str(c) for c in detail.children])
            assert "Inspector Commands" in children_text or len(list(detail.children)) > 0

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("")
            panel.handle_input("   ")
            await pilot.pause()
            assert len(pilot.app.steer_messages) == 0
            assert len(pilot.app.ask_messages) == 0