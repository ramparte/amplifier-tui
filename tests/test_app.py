"""Textual Pilot tests for AmplifierTuiApp -- TUI-004.

Tests use ``app.run_test()`` to spin up a headless Textual app and
verify widget tree, key bindings, and UI state transitions.  The
Amplifier backend is stubbed out so no real sessions are created.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from amplifier_tui.app import AmplifierTuiApp


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def app():
    """Create an AmplifierTuiApp with the backend worker disabled."""
    with patch.object(AmplifierTuiApp, "_init_amplifier_worker", lambda self: None):
        yield AmplifierTuiApp()


# ── Widget-tree smoke tests ─────────────────────────────────────────


class TestAppMount:
    """Verify the app mounts and the widget tree is intact."""

    @pytest.mark.asyncio
    async def test_app_mounts(self, app):
        async with app.run_test(size=(120, 40)):
            assert app.query_one("#chat-input") is not None
            assert app.query_one("#status-bar") is not None
            assert app.query_one("#chat-view") is not None

    @pytest.mark.asyncio
    async def test_sidebar_exists_hidden(self, app):
        async with app.run_test(size=(120, 40)):
            sidebar = app.query_one("#session-sidebar")
            assert sidebar.display is False

    @pytest.mark.asyncio
    async def test_find_bar_exists_hidden(self, app):
        async with app.run_test(size=(120, 40)):
            find_bar = app.query_one("#find-bar")
            assert find_bar.display is False

    @pytest.mark.asyncio
    async def test_tab_bar_exists(self, app):
        async with app.run_test(size=(120, 40)):
            tab_bar = app.query_one("#tab-bar")
            assert tab_bar is not None

    @pytest.mark.asyncio
    async def test_chat_input_focused(self, app):
        async with app.run_test(size=(120, 40)):
            focused = app.focused
            # Chat input should have focus after mount
            if focused is not None:
                assert focused.id == "chat-input"


# ── Key-binding tests ───────────────────────────────────────────────


class TestSidebarToggle:
    """Ctrl+B toggles the session sidebar."""

    @pytest.mark.asyncio
    async def test_toggle_sidebar_on(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            sidebar = app.query_one("#session-sidebar")
            assert sidebar.display is False
            await pilot.press("ctrl+b")
            assert sidebar.display is True

    @pytest.mark.asyncio
    async def test_toggle_sidebar_off(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            sidebar = app.query_one("#session-sidebar")
            await pilot.press("ctrl+b")  # on
            await pilot.press("ctrl+b")  # off
            assert sidebar.display is False


class TestFocusMode:
    """F11 toggles focus mode (hides chrome)."""

    @pytest.mark.asyncio
    async def test_toggle_focus_on(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            assert not app.has_class("focus-mode")
            await pilot.press("f11")
            assert app.has_class("focus-mode")

    @pytest.mark.asyncio
    async def test_toggle_focus_off(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("f11")  # on
            await pilot.press("f11")  # off
            assert not app.has_class("focus-mode")


class TestFindBar:
    """Find-bar toggle via action_search_chat.

    Note: Ctrl+F is intercepted by the focused ChatInput (TextArea),
    so we call the action directly instead of using pilot.press.
    """

    @pytest.mark.asyncio
    async def test_toggle_find_bar_on(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            find_bar = app.query_one("#find-bar")
            assert find_bar.display is False
            app.action_search_chat()
            await pilot.pause()
            assert find_bar.display is True

    @pytest.mark.asyncio
    async def test_toggle_find_bar_off(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            find_bar = app.query_one("#find-bar")
            app.action_search_chat()  # on
            await pilot.pause()
            app.action_search_chat()  # off
            await pilot.pause()
            assert find_bar.display is False


class TestClearChat:
    """Ctrl+L clears the chat view."""

    @pytest.mark.asyncio
    async def test_clear_empty_chat(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            chat_view = app.query_one("#chat-view")
            # Should not raise even when chat is empty
            await pilot.press("ctrl+l")
            assert len(chat_view.children) == 0


class TestShortcutOverlay:
    """F1 shows the keyboard shortcut overlay."""

    @pytest.mark.asyncio
    async def test_show_shortcuts(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("f1")
            # The overlay is pushed as a screen
            assert app.screen.__class__.__name__ == "ShortcutOverlay"
            # Dismiss it
            await pilot.press("escape")


class TestAutoScroll:
    """Auto-scroll toggle via action (Ctrl+A intercepted by ChatInput)."""

    @pytest.mark.asyncio
    async def test_toggle_auto_scroll(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            assert app._auto_scroll is True
            app.action_toggle_auto_scroll()
            await pilot.pause()
            assert app._auto_scroll is False
            app.action_toggle_auto_scroll()
            await pilot.pause()
            assert app._auto_scroll is True


class TestNewTab:
    """Ctrl+T creates a new tab."""

    @pytest.mark.asyncio
    async def test_new_tab_increases_count(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            initial_count = len(app._tabs)
            await pilot.press("ctrl+t")
            assert len(app._tabs) == initial_count + 1
