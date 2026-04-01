"""Tests for InspectorPanel widget."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Static, TextArea

from amplifier_tui.models.block_model import BlockInfo, BlockRegistry, BlockType
from amplifier_tui.widgets.inspector_panel import InspectorPanel


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