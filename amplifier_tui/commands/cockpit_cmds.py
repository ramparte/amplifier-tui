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
        """Display help with cockpit commands + dynamic modes/skills from session."""
        lines = [
            "Cockpit Commands:",
            "  /help        Show this help",
            "  /shell       Open tmux split for shell access",
            "  /clear       Clear chat and session context",
            "  /status      Show session info (ID, model, providers)",
            "  /new         Start a new session",
            "  /quit        Exit cockpit  (also: /q, /exit)",
            "",
            "Session Commands (forwarded to Amplifier):",
            "  /mode NAME   Activate a mode (e.g. /mode plan)",
            "  /modes       List available modes",
            "  /save        Save conversation transcript",
            "  /config      Show current configuration",
            "  /tools       List available tools",
            "  /agents      List available agents",
            "  /skills      List available skills",
            "  /skill NAME  Load a skill (e.g. /skill simplify)",
            "  /rename NAME Rename current session",
            "  /compact     Compact context to free token space",
        ]

        # Dynamic mode shortcuts from the session (same API as CLI)
        modes = self._discover_mode_shortcuts()
        if modes:
            lines.append("")
            lines.append("Mode Shortcuts:")
            for name, description in modes:
                if description:
                    lines.append(f"  /{name:<11} - {description}")
                else:
                    lines.append(f"  /{name}")

        # Dynamic skill commands from the session (same API as CLI)
        skills = self._discover_skill_shortcuts()
        if skills:
            lines.append("")
            lines.append("Skill Commands:")
            for name in sorted(skills.keys()):
                info = skills[name]
                desc = (
                    info.get("description", "") if isinstance(info, dict) else str(info)
                )
                # Truncate long descriptions for readability
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                lines.append(f"  /{name:<11} - {desc}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _discover_mode_shortcuts(self) -> list[tuple[str, str]]:
        """Query the session for available mode shortcuts."""
        try:
            session = self._get_active_session()  # type: ignore[attr-defined]
            if not session:
                return []
            discovery = session.coordinator.session_state.get("mode_discovery")
            if discovery and hasattr(discovery, "list_modes"):
                modes = discovery.list_modes()
                # Normalise to list of (name, description) tuples
                return [(item[0], item[1]) for item in modes] if modes else []
        except Exception:  # noqa: BLE001
            pass
        return []

    def _discover_skill_shortcuts(self) -> dict[str, object]:
        """Query the session for user-invokable skill shortcuts."""
        try:
            session = self._get_active_session()  # type: ignore[attr-defined]
            if not session:
                return {}
            discovery = session.coordinator.get_capability("skills_discovery")
            if discovery and hasattr(discovery, "get_shortcuts"):
                return discovery.get_shortcuts() or {}
        except Exception:  # noqa: BLE001
            pass
        return {}
