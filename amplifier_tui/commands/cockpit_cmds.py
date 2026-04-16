"""Cockpit-specific slash commands and tmux helpers.

Commands:
    /shell     Open a horizontal split pane in tmux for shell access
    /help      Display cockpit command list

Tmux helpers:
    _tmux_get_pane_var  Read a tmux pane user variable
    _tmux_set_pane_var  Write a tmux pane user variable
    _send_bel           Write BEL character to stdout
"""

from __future__ import annotations

import os
import subprocess
import sys


# ---------------------------------------------------------------------------
# Tmux helpers (module-level, reusable)
# ---------------------------------------------------------------------------


def _tmux_get_pane_var(name: str) -> str | None:
    """Read a tmux pane user variable. Returns None outside tmux."""
    if not os.environ.get("TMUX"):
        return None
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", f"#{{{name}}}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        val = result.stdout.strip()
        return val if val else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _tmux_set_pane_var(name: str, value: str) -> None:
    """Write a tmux pane user variable. No-op outside tmux."""
    if not os.environ.get("TMUX"):
        return
    try:
        subprocess.run(
            ["tmux", "set-option", "-p", name, value],
            capture_output=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass


def _send_bel() -> None:
    """Write BEL character to stdout (triggers tmux monitor-activity)."""
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


class CockpitCommandsMixin:
    """Mixin providing cockpit-specific slash commands."""

    def _cmd_cockpit_shell(self) -> None:
        """Open a horizontal split pane in tmux for shell access."""
        if not os.environ.get("TMUX"):
            self._add_system_message(  # type: ignore[attr-defined]
                "Not running inside tmux -- /shell requires a tmux session."
            )
            return
        try:
            subprocess.run(
                ["tmux", "split-window", "-v", "-l", "30%"],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self._add_system_message(  # type: ignore[attr-defined]
                f"Failed to open shell split: {exc}"
            )

    def _cmd_cockpit_help(self) -> None:
        """Display cockpit command list."""
        help_text = (
            "Cockpit Commands:\n"
            "  /help        Show this help\n"
            "  /shell       Open tmux split for shell access\n"
            "  /clear       Clear chat and session context\n"
            "  /status      Show session info (ID, model, providers)\n"
            "  /new         Start a new session\n"
            "  /quit        Exit cockpit  (also: /q, /exit)\n"
            "\n"
            "Session Commands (forwarded to Amplifier):\n"
            "  /mode NAME   Activate a mode (e.g. /mode plan)\n"
            "  /modes       List available modes\n"
            "  /save        Save conversation transcript\n"
            "  /config      Show current configuration\n"
            "  /tools       List available tools\n"
            "  /agents      List available agents\n"
            "  /rename NAME Rename current session\n"
            "  /compact     Compact context to free token space\n"
            "\n"
            "Any other /command is sent to the session as a message.\n"
            "Skills and mode shortcuts (e.g. /brainstorm) also work."
        )
        self._add_system_message(help_text)  # type: ignore[attr-defined]
