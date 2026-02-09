"""Content manipulation commands."""

from __future__ import annotations

from pathlib import Path
import re
import time


from ..log import logger
from .._utils import _copy_to_clipboard
from ..constants import (
    AUTOSAVE_DIR,
    EXTENSION_TO_LANGUAGE,
    MODES,
    SYSTEM_PRESETS,
)
from ..preferences import (
    save_autosave_enabled,
)


class ContentCommandsMixin:
    """Content manipulation commands."""

    def _cmd_system(self, text: str) -> None:
        """Set, view, or clear the custom system prompt."""
        text = text.strip()

        # No args → show current prompt or usage
        if not text:
            if self._system_prompt:
                label = (
                    f" (preset: {self._system_preset_name})"
                    if self._system_preset_name
                    else ""
                )
                self._add_system_message(
                    f"Current system prompt{label}:\n\n{self._system_prompt}"
                )
            else:
                self._add_system_message(
                    "No system prompt set.\n\n"
                    "Usage:\n"
                    "  /system <text>           Set system prompt\n"
                    "  /system clear            Remove system prompt\n"
                    "  /system append <text>    Add to existing prompt\n"
                    "  /system presets          Show available presets\n"
                    "  /system use <preset>     Apply a preset"
                )
            return

        # /system clear
        if text.lower() == "clear":
            self._system_prompt = ""
            self._system_preset_name = ""
            self._update_system_indicator()
            self._add_system_message("System prompt cleared.")
            return

        # /system presets
        if text.lower() == "presets":
            lines = ["Available system prompt presets:\n"]
            for name, prompt in SYSTEM_PRESETS.items():
                lines.append(f"  {name:10s}  {prompt[:60]}...")
            lines.append("\nUsage: /system use <preset>")
            self._add_system_message("\n".join(lines))
            return

        parts = text.split(None, 1)

        # /system use <preset>
        if parts[0].lower() == "use" and len(parts) > 1:
            preset_name = parts[1].lower().strip()
            if preset_name in SYSTEM_PRESETS:
                self._system_prompt = SYSTEM_PRESETS[preset_name]
                self._system_preset_name = preset_name
                self._update_system_indicator()
                self._add_system_message(
                    f"System prompt set to '{preset_name}':\n\n{self._system_prompt}"
                )
            else:
                self._add_system_message(
                    f"Unknown preset: {preset_name}\n"
                    f"Available: {', '.join(SYSTEM_PRESETS.keys())}"
                )
            return

        if parts[0].lower() == "use" and len(parts) == 1:
            self._add_system_message(
                "Usage: /system use <preset>\n"
                f"Available: {', '.join(SYSTEM_PRESETS.keys())}"
            )
            return

        # /system append <text>
        if parts[0].lower() == "append" and len(parts) > 1:
            addition = parts[1]
            if self._system_prompt:
                self._system_prompt += f"\n{addition}"
            else:
                self._system_prompt = addition
            self._system_preset_name = ""  # custom after append
            self._update_system_indicator()
            self._add_system_message(f"System prompt updated:\n\n{self._system_prompt}")
            return

        if parts[0].lower() == "append" and len(parts) == 1:
            self._add_system_message("Usage: /system append <text>")
            return

        # Anything else → set as the full system prompt
        self._system_prompt = text
        self._system_preset_name = ""
        self._update_system_indicator()
        self._add_system_message(f"System prompt set:\n\n{text}")

    def _cmd_autosave(self, text: str) -> None:
        """Manage session auto-save (/autosave [on|off|now|restore])."""
        text = text.strip().lower()

        if not text:
            # Show status
            status = "enabled" if self._autosave_enabled else "disabled"
            last = "never"
            if self._last_autosave:
                ago = time.time() - self._last_autosave
                if ago < 60:
                    last = f"{ago:.0f}s ago"
                else:
                    last = f"{ago / 60:.0f}m ago"
            try:
                count = len(list(AUTOSAVE_DIR.glob("autosave-*.json")))
            except OSError:
                logger.debug("Failed to list autosave files", exc_info=True)
                count = 0
            self._add_system_message(
                f"Auto-save: {status}\n"
                f"  Interval: {self._autosave_interval}s\n"
                f"  Last save: {last}\n"
                f"  Files: {count}\n"
                f"  Location: {AUTOSAVE_DIR}"
            )
            return

        if text == "on":
            self._autosave_enabled = True
            self._prefs.autosave.enabled = True
            save_autosave_enabled(True)
            # Start timer if not already running
            if self._autosave_timer is not None:
                try:
                    self._autosave_timer.stop()  # type: ignore[union-attr]
                except Exception:
                    logger.debug("Failed to stop autosave timer", exc_info=True)
            self._autosave_timer = self.set_interval(
                self._autosave_interval,
                self._do_autosave,
                name="autosave",
            )
            self._add_system_message("Auto-save enabled")

        elif text == "off":
            self._autosave_enabled = False
            self._prefs.autosave.enabled = False
            save_autosave_enabled(False)
            if self._autosave_timer is not None:
                try:
                    self._autosave_timer.stop()  # type: ignore[union-attr]
                except Exception:
                    logger.debug("Failed to stop autosave timer", exc_info=True)
                self._autosave_timer = None
            self._add_system_message("Auto-save disabled")

        elif text == "now":
            self._do_autosave()
            if self._last_autosave:
                self._add_system_message("Auto-save completed")
            else:
                self._add_system_message(
                    "Nothing to auto-save (no messages in current session)"
                )

        elif text == "restore":
            self._autosave_restore()

        else:
            self._add_system_message(
                "Usage: /autosave [on|off|now|restore]\n"
                "  /autosave          Show auto-save status\n"
                "  /autosave on       Enable periodic auto-save\n"
                "  /autosave off      Disable periodic auto-save\n"
                "  /autosave now      Force immediate save\n"
                "  /autosave restore  List & restore auto-saves"
            )

    def _cmd_attach(self, text: str) -> None:
        """Attach files to include in next message."""
        text = text.strip()

        if not text:
            self._show_attachments()
            return

        if text.lower() == "clear":
            self._attachments.clear()
            self._update_attachment_indicator()
            self._add_system_message("Attachments cleared")
            return

        parts = text.split(None, 1)
        if parts[0].lower() == "remove" and len(parts) > 1:
            try:
                n = int(parts[1])
                if 1 <= n <= len(self._attachments):
                    removed = self._attachments.pop(n - 1)
                    self._update_attachment_indicator()
                    self._add_system_message(f"Removed: {removed.name}")
                else:
                    self._add_system_message(
                        f"Invalid attachment number (1-{len(self._attachments)})"
                    )
            except ValueError:
                self._add_system_message("Usage: /attach remove <number>")
            return

        # Attach file(s) — check for glob patterns
        raw = text
        if any(c in raw for c in ["*", "?", "["]):
            files = sorted(Path(".").glob(raw))
            if not files:
                self._add_system_message(f"No files matching: {raw}")
                return
            for f in files[:20]:
                if f.is_file():
                    self._attach_file(f)
            if len(files) > 20:
                self._add_system_message(
                    f"... and {len(files) - 20} more files skipped"
                )
            return

        path = Path(text).expanduser()
        if not path.exists():
            path = Path.cwd() / text
        if not path.exists():
            self._add_system_message(f"File not found: {text}")
            return
        if path.is_dir():
            self._add_system_message(f"Cannot attach directory: {text}")
            return
        self._attach_file(path)

    def _cmd_cat(self, text: str) -> None:
        """Display file contents in chat."""
        text = text.strip()
        if not text:
            self._add_system_message(
                "Usage: /cat <path>\n"
                "  Displays file contents in chat (does not attach)."
            )
            return

        path = Path(text).expanduser()
        if not path.exists():
            path = Path.cwd() / text
        if not path.exists():
            self._add_system_message(f"File not found: {text}")
            return
        if path.is_dir():
            self._add_system_message(f"Cannot display directory: {text}")
            return
        if self._is_binary(path):
            self._add_system_message(f"Cannot display binary file: {path.name}")
            return

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("Failed to read file %s", path, exc_info=True)
            self._add_system_message(f"Error reading {path.name}: {e}")
            return

        ext = path.suffix.lower()
        lang = EXTENSION_TO_LANGUAGE.get(ext, "")

        lines = content.split("\n")
        if len(lines) > 200:
            content = "\n".join(lines[:200])
            content += f"\n\n... ({len(lines) - 200} more lines)"

        size_str = f"{len(content.encode('utf-8')) / 1024:.1f}KB"
        self._add_system_message(
            f"{path.name} ({len(lines)} lines, {size_str})\n```{lang}\n{content}\n```"
        )

    def _cmd_mode(self, text: str) -> None:
        """Activate, deactivate, or list Amplifier modes.

        /mode           List available modes and show current
        /mode <name>    Activate a mode (toggle off if already active)
        /mode off       Deactivate the current mode
        """
        text = text.strip().lower()

        if not text:
            # List modes
            lines = ["Available modes:", ""]
            for name, mode in MODES.items():
                active = " (active)" if name == self._active_mode else ""
                marker = "▶" if name == self._active_mode else " "
                lines.append(f"  {marker} {name}: {mode['description']}{active}")

            if self._active_mode:
                lines.append(f"\nActive: {self._active_mode}")
                lines.append("Use /mode off to deactivate")
            else:
                lines.append("\nNo mode active. Use /mode <name> to activate.")

            self._add_system_message("\n".join(lines))
            return

        if text == "off":
            if self._active_mode:
                old = self._active_mode
                self._active_mode = None
                self._update_mode_display()
                self._add_system_message(f"Mode deactivated: {old}")
            else:
                self._add_system_message("No mode is currently active")
            return

        if text in MODES:
            if text == self._active_mode:
                # Toggle off
                self._active_mode = None
                self._update_mode_display()
                self._add_system_message(f"Mode deactivated: {text}")
            else:
                self._active_mode = text
                self._update_mode_display()
                mode = MODES[text]
                self._add_system_message(
                    f"Mode activated: {text}\n{mode['description']}"
                )
        else:
            self._add_system_message(
                f"Unknown mode: {text}\nAvailable: {', '.join(MODES.keys())}"
            )

    def _cmd_copy(self, text: str) -> None:
        """Copy a message to clipboard.

        /copy        — last assistant response
        /copy last   — same as /copy (last assistant response)
        /copy N      — message N from bottom (1 = last message)
        /copy all    — entire conversation
        /copy code   — last code block from any message
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        arg_lower = arg.lower()

        # --- /copy last  (alias for default) ---
        if arg_lower == "last":
            arg = ""
            arg_lower = ""

        # --- /copy all ---
        if arg_lower == "all":
            if not self._search_messages:
                self._add_system_message("No messages to copy")
                return
            lines: list[str] = []
            for role, content, _widget in self._search_messages:
                label = {"user": "You", "assistant": "AI", "system": "System"}.get(
                    role, role
                )
                lines.append(f"--- {label} ---")
                lines.append(content)
                lines.append("")
            full_text = "\n".join(lines)
            if _copy_to_clipboard(full_text):
                preview = self._copy_preview(full_text)
                self._add_system_message(
                    f"Copied entire conversation"
                    f" ({len(self._search_messages)} messages,"
                    f" {len(full_text)} chars)\n"
                    f"Preview: {preview}"
                )
            else:
                self._add_system_message(
                    "Failed to copy — no clipboard tool available"
                    " (install xclip or xsel)"
                )
            return

        # --- /copy code ---
        if arg_lower == "code":
            for _role, content, _widget in reversed(self._search_messages):
                blocks = re.findall(r"```(?:\w*\n)?(.*?)```", content, re.DOTALL)
                if blocks:
                    code = blocks[-1].strip()
                    if _copy_to_clipboard(code):
                        preview = self._copy_preview(code)
                        self._add_system_message(
                            f"Copied code block ({len(code)} chars)\nPreview: {preview}"
                        )
                    else:
                        self._add_system_message(
                            "Failed to copy — no clipboard tool available"
                            " (install xclip or xsel)"
                        )
                    return
            self._add_system_message("No code blocks found in conversation")
            return

        # --- /copy N  (1 = last message, 2 = second-to-last, etc.) ---
        if arg and arg.isdigit():
            n = int(arg)
            total = len(self._search_messages)
            idx = total - n  # count from bottom
            if 0 <= idx < total:
                role, msg_text, _widget = self._search_messages[idx]
                if _copy_to_clipboard(msg_text):
                    preview = self._copy_preview(msg_text)
                    self._add_system_message(
                        f"Copied message #{arg} [{role}]"
                        f" ({len(msg_text)} chars)\n"
                        f"Preview: {preview}"
                    )
                else:
                    self._add_system_message(
                        "Failed to copy — no clipboard tool available"
                        " (install xclip or xsel)"
                    )
            else:
                self._add_system_message(
                    f"Message {arg} not found (range: 1-{total})"
                    if total
                    else "No messages yet"
                )
            return

        if arg:
            self._add_system_message(
                "Usage: /copy [target]\n"
                "  /copy           Last assistant response\n"
                "  /copy last      Last assistant response\n"
                "  /copy all       Entire conversation\n"
                "  /copy code      Last code block\n"
                "  /copy N         Message #N from bottom (1 = last)"
            )
            return

        # Default: copy last assistant message
        self.action_copy_response()

    def _cmd_history(self, text: str) -> None:
        """Browse or clear prompt history."""
        text = text.strip()

        if text == "clear":
            self._history.clear()
            self._add_system_message("Input history cleared.")
            return

        if text.startswith("search ") or text == "search":
            query = text[7:].strip() if text.startswith("search ") else ""
            if not query:
                self._add_system_message(
                    "Usage: /history search <query>\n"
                    "  Searches input history for entries containing <query>."
                )
                return
            matches = self._history.search(query)
            if not matches:
                self._add_system_message(f"No history matching: {query}")
                return
            noun = "result" if len(matches) == 1 else "results"
            lines = [f"History matching '{query}' ({len(matches)} {noun}):"]
            for i, entry in enumerate(matches, 1):
                preview = entry[:80].replace("\n", " ")
                if len(entry) > 80:
                    preview += "\u2026"
                lines.append(f"  {i}. {preview}")
            self._add_system_message("\n".join(lines))
            return

        n = 20
        if text.isdigit():
            n = int(text)

        entries = self._history.entries
        if not entries:
            self._add_system_message("No input history yet.")
            return

        show = entries[-n:]
        lines = [f"Last {len(show)} of {len(entries)} inputs:"]
        for i, entry in enumerate(show, 1):
            preview = entry[:80].replace("\n", " ")
            if len(entry) > 80:
                preview += "\u2026"
            lines.append(f"  {i}. {preview}")
        lines.append("")
        lines.append(
            "Up/Down arrows to recall, Ctrl+R to search, /history clear to reset\n"
            "  /history search <query> to find specific entries"
        )
        self._add_system_message("\n".join(lines))

    def _cmd_redo(self, text: str) -> None:
        """Re-send a previous user message to Amplifier."""
        text = text.strip()

        # Parse the optional index argument
        n = 1
        if text:
            if text.isdigit():
                n = int(text)
            else:
                self._add_system_message(
                    "Usage: /redo [N]  (re-send Nth-to-last message, default: 1)"
                )
                return

        if n < 1:
            self._add_system_message(
                "Usage: /redo [N]  (re-send Nth-to-last message, default: 1)"
            )
            return

        # Gather user messages from the current session
        user_messages = [
            content
            for role, content, _widget in self._search_messages
            if role == "user"
        ]

        if not user_messages:
            self._add_system_message("No previous messages to redo")
            return

        if n > len(user_messages):
            self._add_system_message(
                f"Only {len(user_messages)} user message{'s' if len(user_messages) != 1 else ''} "
                f"in this session"
            )
            return

        # Guard: don't send while already processing
        if self.is_processing:
            self._add_system_message("Please wait for the current response to finish.")
            return

        if not self._amplifier_available:
            self._add_system_message("Amplifier is not available.")
            return

        if not self._amplifier_ready:
            self._add_system_message("Still loading Amplifier...")
            return

        message = user_messages[-n]

        # Show a short preview of what we're re-sending
        preview = message[:100].replace("\n", " ")
        if len(message) > 100:
            preview += "\u2026"
        self._add_system_message(f"Re-sending: {preview}")

        # Send as a new user message (shows in chat, starts processing)
        self._clear_welcome()
        self._add_user_message(message)
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(message)

    def _cmd_retry(self, text: str) -> None:
        """Retry the last exchange, optionally with a modified prompt.

        /retry         — undo the last exchange and re-send the same message
        /retry <text>  — undo the last exchange and send <text> instead
        /redo          — alias for /retry
        """
        text = text.strip()

        # Guard: don't retry while processing
        if self.is_processing:
            self._add_system_message("Please wait for the current response to finish.")
            return

        if not self._amplifier_available:
            self._add_system_message("Amplifier is not available.")
            return

        if not self._amplifier_ready:
            self._add_system_message("Still loading Amplifier...")
            return

        # Find the last user message content before undo removes it
        last_user_content: str | None = None
        for role, content, _widget in reversed(self._search_messages):
            if role == "user":
                last_user_content = content
                break

        if last_user_content is None:
            self._add_system_message(
                "Nothing to retry \u2014 no previous message found."
            )
            return

        # Determine what to send
        retry_prompt = text if text else last_user_content

        # Remove the last exchange (reuses full undo logic: DOM cleanup,
        # stats, _search_messages, etc.) — silently, we show our own message.
        self._execute_undo(1, silent=True)

        # Brief indicator
        preview = retry_prompt[:80].replace("\n", " ")
        if len(retry_prompt) > 80:
            preview += "\u2026"
        self._add_system_message(f"Retrying: {preview}")

        # Re-send through the normal flow
        self._clear_welcome()
        self._add_user_message(retry_prompt)
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(retry_prompt)

    def _cmd_undo(self, text: str) -> None:
        """Remove the last N user+assistant exchange(s) from the chat.

        This removes messages from the display and internal tracking
        (_search_messages, word counts).  Note: messages already sent to the
        Amplifier session's LLM context cannot be retracted — this is a
        UI-level undo only.
        """
        text = text.strip()

        # Handle two-step confirmation for multi-exchange undo
        if text == "confirm" and self._pending_undo is not None:
            count = self._pending_undo
            self._pending_undo = None
            self._execute_undo(count)
            return

        if text == "cancel":
            if self._pending_undo is not None:
                self._pending_undo = None
                self._add_system_message("Undo cancelled.")
            else:
                self._add_system_message("Nothing to cancel.")
            return

        # Parse optional count argument
        count = 1
        if text:
            if text.isdigit():
                count = int(text)
                if count < 1:
                    self._add_system_message(
                        "Usage: /undo [N]  (remove last N exchanges, default: 1)"
                    )
                    return
            else:
                self._add_system_message(
                    "Usage: /undo [N]  (remove last N exchanges, default: 1)"
                )
                return

        # Guard: don't undo while processing
        if self.is_processing:
            self._add_system_message("Please wait for the current response to finish.")
            return

        # Check there are undoable messages
        has_undoable = any(
            role in ("user", "assistant") for role, _, _ in self._search_messages
        )
        if not has_undoable:
            self._add_system_message("Nothing to undo.")
            return

        # For count > 1, require confirmation
        if count > 1:
            self._pending_undo = count
            self._add_system_message(
                f"Remove the last {count} exchange(s)?\n"
                "Type /undo confirm to proceed or /undo cancel to abort."
            )
            return

        self._execute_undo(count)
