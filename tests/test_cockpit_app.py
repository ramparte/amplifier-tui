"""Tests for CockpitApp -- Textual Pilot widget tests."""

from __future__ import annotations

import pytest
from textual.containers import ScrollableContainer
from textual.widgets import Static

from amplifier_tui.cockpit_app import CockpitApp


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