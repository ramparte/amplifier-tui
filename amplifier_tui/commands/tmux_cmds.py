"""Tmux-specific slash commands for TmuxApp.

Commands:
    /move-to <project>   Move tmux window to a named session group
    /shell               Open a horizontal split pane for shell access
    /amp help            Display amp CLI help text inline
"""

from __future__ import annotations

import os
import subprocess

from ..core.log import logger


class TmuxCommandsMixin:
    """Mixin providing tmux-specific slash commands."""

    def _cmd_tmux_move_to(self, project: str) -> None:
        """Move the current tmux window to a session named amp-<project>.

        If the target session doesn't exist, it is created first.
        """
        project = project.strip()
        if not project:
            self._add_system_message(  # type: ignore[attr-defined]
                "Usage: /move-to <project>\n"
                "  Moves this tmux window to the amp-<project> session.\n"
                "  Creates the session if it doesn't exist."
            )
            return

        target_session = f"amp-{project}"

        # Ensure the target session exists (create detached if not)
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", target_session],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                subprocess.run(
                    ["tmux", "new-session", "-d", "-s", target_session],
                    capture_output=True,
                    timeout=5,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.debug("tmux session check failed: %s", exc)
            self._add_system_message(  # type: ignore[attr-defined]
                f"Failed to create tmux session '{target_session}': {exc}"
            )
            return

        # Move current window to the target session
        try:
            subprocess.run(
                ["tmux", "move-window", "-t", target_session],
                capture_output=True,
                check=True,
                timeout=5,
            )
            self._add_system_message(  # type: ignore[attr-defined]
                f"Moved window to session '{target_session}'."
            )
        except subprocess.CalledProcessError as exc:
            self._add_system_message(  # type: ignore[attr-defined]
                f"Failed to move window: {exc.stderr.decode(errors='replace').strip()}"
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self._add_system_message(  # type: ignore[attr-defined]
                f"tmux move-window failed: {exc}"
            )

    def _cmd_tmux_shell(self) -> None:
        """Open a horizontal split pane in tmux for shell access."""
        if not os.environ.get("TMUX"):
            self._add_system_message(  # type: ignore[attr-defined]
                "Not running inside tmux — /shell requires a tmux session."
            )
            return
        try:
            subprocess.run(
                ["tmux", "split-window", "-h"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            self._add_system_message(  # type: ignore[attr-defined]
                "Opened shell pane. Use Ctrl+B then arrow keys to navigate."
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            self._add_system_message(  # type: ignore[attr-defined]
                f"Failed to open shell pane: {exc}"
            )

    def _cmd_tmux_amp_help(self) -> None:
        """Display the amp CLI help text inline as a system message."""
        try:
            result = subprocess.run(
                ["amp", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout.strip() or result.stderr.strip()
            if output:
                self._add_system_message(f"amp --help\n\n{output}")  # type: ignore[attr-defined]
            else:
                self._add_system_message("amp --help returned no output.")  # type: ignore[attr-defined]
        except FileNotFoundError:
            self._add_system_message("'amp' command not found on PATH.")  # type: ignore[attr-defined]
        except (subprocess.TimeoutExpired, OSError) as exc:
            self._add_system_message(f"Failed to run amp --help: {exc}")  # type: ignore[attr-defined]
