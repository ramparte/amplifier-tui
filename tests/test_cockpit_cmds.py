"""Tests for CockpitCommandsMixin -- tmux helpers and commands."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from amplifier_tui.commands.cockpit_cmds import (
    CockpitCommandsMixin,
    _send_bel,
    _tmux_get_pane_var,
    _tmux_set_pane_var,
)


class TestTmuxHelpers:
    """Tmux helper functions work correctly outside tmux."""

    def test_get_pane_var_outside_tmux(self):
        """Returns None when $TMUX is not set."""
        with patch.dict("os.environ", {}, clear=True):
            assert _tmux_get_pane_var("@amp_session_id") is None

    def test_set_pane_var_outside_tmux(self):
        """No-op when $TMUX is not set (no exception)."""
        with patch.dict("os.environ", {}, clear=True):
            _tmux_set_pane_var("@amp_session_id", "test-123")  # should not raise

    @patch("subprocess.run")
    def test_get_pane_var_inside_tmux(self, mock_run):
        """Reads pane variable when inside tmux."""
        mock_run.return_value = MagicMock(stdout="session-abc123\n")
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            result = _tmux_get_pane_var("@amp_session_id")
        assert result == "session-abc123"
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_pane_var_empty_returns_none(self, mock_run):
        """Returns None for empty pane variable."""
        mock_run.return_value = MagicMock(stdout="\n")
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            result = _tmux_get_pane_var("@amp_session_id")
        assert result is None

    def test_send_bel_no_crash(self):
        """_send_bel doesn't crash."""
        _send_bel()  # should not raise


class TestCockpitCommandsMixin:
    """CockpitCommandsMixin provides /shell and /help commands."""

    def test_mixin_has_shell_command(self):
        assert hasattr(CockpitCommandsMixin, "_cmd_cockpit_shell")

    def test_mixin_has_help_command(self):
        assert hasattr(CockpitCommandsMixin, "_cmd_cockpit_help")