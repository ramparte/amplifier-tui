"""File and external tool commands."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess

from ..log import logger
from ..constants import (
    _DANGEROUS_PATTERNS,
    _MAX_RUN_OUTPUT_LINES,
    _RUN_TIMEOUT,
)
from ..preferences import (
    save_editor_auto_send,
    save_notification_enabled,
    save_notification_min_seconds,
    save_notification_sound,
    save_notification_title_flash,
)


class FileCommandsMixin:
    """File and external tool commands."""

    def _cmd_editor(self, args: str) -> None:
        """Handle /editor command with optional 'submit' toggle."""
        arg = args.strip().lower()
        if arg == "submit":
            current = self._prefs.display.editor_auto_send
            self._prefs.display.editor_auto_send = not current
            state = "ON" if not current else "OFF"
            self._add_system_message(f"Editor auto-submit: {state}")
            save_editor_auto_send(not current)
            return
        # No argument (or unknown) — just open editor
        self.action_open_editor()

    def _cmd_run(self, text: str) -> None:
        """Execute a shell command and display output inline."""
        text = text.strip()
        if not text:
            self._add_system_message(
                "Usage: /run <command>\n"
                "  /run ls -la\n"
                "  /run git status\n"
                "  /! git diff     (shorthand)\n"
                "\nTimeout: 30s. Max output: 100 lines."
            )
            return

        # Safety check
        cmd_lower = text.lower()
        for pattern in _DANGEROUS_PATTERNS:
            if pattern in cmd_lower:
                self._add_system_message(
                    f"Blocked: potentially dangerous command\n  {text}"
                )
                return

        # Record in history so Ctrl+R can find it
        self._history.add(f"/run {text}", force=True)

        try:
            result = subprocess.run(
                text,
                shell=True,  # noqa: S602  — needed for pipes/globs
                capture_output=True,
                text=True,
                timeout=_RUN_TIMEOUT,
                cwd=os.getcwd(),
            )

            output_parts: list[str] = []

            if result.stdout:
                lines = result.stdout.splitlines()
                if len(lines) > _MAX_RUN_OUTPUT_LINES:
                    output_parts.append("\n".join(lines[:_MAX_RUN_OUTPUT_LINES]))
                    remaining = len(lines) - _MAX_RUN_OUTPUT_LINES
                    output_parts.append(f"\n... ({remaining} more lines)")
                else:
                    output_parts.append(result.stdout.rstrip())

            if result.stderr:
                output_parts.append(f"\n[stderr]\n{result.stderr.rstrip()}")

            if result.returncode != 0:
                output_parts.append(f"\n[exit code: {result.returncode}]")

            if not output_parts:
                output_parts.append("(no output)")

            header = f"$ {text}"
            output = "\n".join(output_parts)
            self._add_system_message(f"{header}\n```\n{output}\n```")

        except subprocess.TimeoutExpired:
            self._add_system_message(f"Command timed out after {_RUN_TIMEOUT}s: {text}")
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("Command execution failed", exc_info=True)
            self._add_system_message(f"Error running command: {e}")

    # -- /include helpers ------------------------------------------------------

    def _cmd_include(self, text: str) -> None:
        """Include file contents in the prompt."""
        text = text.strip()
        if not text:
            self._add_system_message(
                "Usage: /include <path> [--send]\n"
                "  /include src/main.py          Insert into input\n"
                "  /include src/main.py --send    Insert and send\n"
                "  /include src/*.py              Glob pattern\n"
                "  /include config.yaml           Auto-detect language\n\n"
                "Also: Type @./path/to/file in your prompt"
            )
            return

        auto_send = False
        if text.endswith("--send"):
            auto_send = True
            text = text[:-6].strip()

        # Expand ~ and resolve path
        raw = text
        path = Path(text).expanduser()

        # Check for glob pattern
        if any(c in raw for c in ["*", "?", "["]):
            files = sorted(Path(".").glob(raw))
            if not files:
                self._add_system_message(f"No files matching: {raw}")
                return

            parts: list[str] = []
            for f in files[:20]:  # Max 20 files
                content = self._read_file_for_include(f)
                if content:
                    parts.append(content)

            if len(files) > 20:
                parts.append(f"\n... and {len(files) - 20} more files")

            combined = "\n\n".join(parts)
            if auto_send:
                self._include_and_send(combined)
            else:
                self._include_into_input(combined)
                self._add_system_message(
                    f"Included {min(len(files), 20)} files. Edit and send."
                )
            return

        # Single file
        if not path.exists():
            # Try relative to CWD
            path = Path.cwd() / raw
            if not path.exists():
                self._add_system_message(f"File not found: {raw}")
                return

        content = self._read_file_for_include(path)
        if not content:
            return

        if auto_send:
            self._include_and_send(content)
        else:
            self._include_into_input(content)
            self._add_system_message(f"Included: {path.name}. Edit and send.")

    def _cmd_notify(self, text: str) -> None:
        """Toggle completion notifications, or set mode/threshold explicitly."""
        arg = text.partition(" ")[2].strip().lower() if " " in text else ""
        nprefs = self._prefs.notifications

        if arg in ("on", "sound"):
            nprefs.enabled = True
            save_notification_enabled(True)
            self._add_system_message(
                f"Notifications ON (after {nprefs.min_seconds:.0f}s)"
            )
        elif arg in ("off", "silent"):
            nprefs.enabled = False
            save_notification_enabled(False)
            self._add_system_message("Notifications OFF")
        elif arg == "flash":
            nprefs.title_flash = not nprefs.title_flash
            save_notification_title_flash(nprefs.title_flash)
            state = "ON" if nprefs.title_flash else "OFF"
            self._add_system_message(f"Title bar flash: {state}")
        elif arg.replace(".", "", 1).isdigit():
            secs = max(0.0, float(arg))
            nprefs.min_seconds = secs
            save_notification_min_seconds(secs)
            self._add_system_message(f"Notification threshold: {secs:.1f}s")
        elif not arg:
            # Toggle
            nprefs.enabled = not nprefs.enabled
            save_notification_enabled(nprefs.enabled)
            state = "ON" if nprefs.enabled else "OFF"
            self._add_system_message(
                f"Notifications {state} (after {nprefs.min_seconds:.0f}s)"
            )
        else:
            self._add_system_message(
                "Usage: /notify [on|off|sound|silent|flash|<seconds>]\n"
                "  /notify         Toggle on/off\n"
                "  /notify on      Enable completion notifications\n"
                "  /notify off     Disable notifications\n"
                "  /notify sound   Same as on\n"
                "  /notify silent  Same as off\n"
                "  /notify flash   Toggle title bar flash on response\n"
                "  /notify 5       Set minimum response time (seconds)"
            )

    def _cmd_sound(self, text: str) -> None:
        """Toggle notification sound on/off, test, or set explicitly."""
        arg = text.partition(" ")[2].strip().lower() if " " in text else ""

        if arg == "test":
            # Always play the bell — even when sound is disabled
            self._play_bell()
            self._add_system_message("Sound test played (BEL)")
            return

        if arg == "on":
            self._prefs.notifications.sound_enabled = True
        elif arg == "off":
            self._prefs.notifications.sound_enabled = False
        elif not arg:
            # Toggle
            self._prefs.notifications.sound_enabled = (
                not self._prefs.notifications.sound_enabled
            )
        else:
            self._add_system_message("Usage: /sound [on|off|test]")
            return

        save_notification_sound(self._prefs.notifications.sound_enabled)
        state = "on" if self._prefs.notifications.sound_enabled else "off"
        self._add_system_message(f"Notification sound: {state}")
