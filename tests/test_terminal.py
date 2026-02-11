"""Smoke tests for the terminal widget and command mixin."""

import asyncio
import pytest
from amplifier_tui.widgets.terminal import TERMINAL_AVAILABLE, Terminal


def test_terminal_available():
    """Feature flag should be True when pyte is installed."""
    assert TERMINAL_AVAILABLE is True


def test_terminal_widget_instantiates():
    """Terminal widget should create without errors."""
    t = Terminal(command="/bin/echo hello")
    assert t.command == "/bin/echo hello"
    assert t.ncol == 80
    assert t.nrow == 24
    assert t.is_running is False


def test_terminal_default_shell():
    """Terminal should default to SHELL env var or /bin/bash."""
    import os
    t = Terminal()
    expected = os.environ.get("SHELL", "/bin/bash")
    assert t.command == expected


def test_terminal_start_stop():
    """Terminal should start and stop a PTY subprocess."""
    async def _run():
        t = Terminal(command="/bin/echo hello")
        t.start()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False
    asyncio.run(_run())


def test_terminal_double_start():
    """Starting an already-running terminal should be a no-op."""
    async def _run():
        t = Terminal(command="/bin/sleep 5")
        t.start()
        emulator1 = t._emulator
        t.start()  # should not create a second emulator
        assert t._emulator is emulator1
        t.stop()
    asyncio.run(_run())


def test_terminal_stop_when_not_running():
    """Stopping a non-running terminal should not raise."""
    t = Terminal()
    t.stop()  # should be a no-op


def test_terminal_command_mixin_import():
    """TerminalCommandsMixin should import cleanly."""
    from amplifier_tui.commands.terminal_cmds import TerminalCommandsMixin
    assert hasattr(TerminalCommandsMixin, '_cmd_terminal')
    assert hasattr(TerminalCommandsMixin, '_toggle_terminal_panel')
    assert hasattr(TerminalCommandsMixin, '_open_terminal_panel')
    assert hasattr(TerminalCommandsMixin, '_close_terminal_panel')


def test_terminal_in_slash_commands():
    """The /terminal command should be registered."""
    from amplifier_tui.constants import SLASH_COMMANDS
    assert "/terminal" in SLASH_COMMANDS
