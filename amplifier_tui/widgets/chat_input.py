"""Chat input widget for Amplifier TUI."""

from __future__ import annotations

import os
import re

from textual.widgets import TextArea

from textual.css.query import NoMatches

from ..constants import SLASH_COMMANDS, SYSTEM_PRESETS
from ..log import logger
from .bars import SuggestionBar


class ChatInput(TextArea):
    """Chat input with smart Enter key behavior.

    Key dispatch (three modes):

    Slash commands (text starts with ``/``):
        Enter → submit, Ctrl+J / Shift+Enter / Ctrl+Enter → literal newline.
        This ensures /help, /tabs etc. always work with a plain Enter.

    Multiline mode (``_multiline_mode=True``, no leading ``/``):
        Enter → newline, Ctrl+J / Shift+Enter / Ctrl+Enter → submit.

    Normal mode (``_multiline_mode=False``, no leading ``/``):
        Enter → submit, Ctrl+J / Shift+Enter / Ctrl+Enter → newline.
    """

    class Submitted(TextArea.Changed):
        """Fired when the user presses Enter."""

    # Maximum number of content lines before the input scrolls internally
    MAX_INPUT_LINES = 10

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # Tab-completion state for slash commands
        self._tab_matches: list[str] = []
        self._tab_index: int = 0
        self._tab_prefix: str = ""
        # Vim mode state
        self._vim_enabled: bool = False
        self._vim_state: str = "insert"  # "normal" or "insert"
        self._vim_key_buffer: str = ""  # for multi-char combos like dd, gg
        # Multiline mode: Enter = newline, Ctrl+Enter = send
        self._multiline_mode: bool = False
        # Smart suggestion state
        self._suggestions_enabled: bool = True
        self._suggestion_accepted: bool = (
            False  # Track if last Tab accepted a suggestion
        )

    # -- Slash command tab-completion ----------------------------------------

    def _complete_slash_command(self, text: str) -> None:
        """Complete or cycle through matching slash commands."""
        # If we're mid-cycle and text matches the current suggestion, advance
        if self._tab_matches and self._tab_prefix and text in self._tab_matches:
            self._tab_index = (self._tab_index + 1) % len(self._tab_matches)
            choice = self._tab_matches[self._tab_index]
            self.clear()
            self.insert(choice)
            return

        # Snippet name completion for /snippet use|send|remove|delete|edit|tag <name>
        # Also supports /snip alias
        for prefix_cmd in (
            "/snippet use ",
            "/snippet send ",
            "/snippet remove ",
            "/snippet delete ",
            "/snippet edit ",
            "/snippet tag ",
            "/snip use ",
            "/snip send ",
            "/snip remove ",
            "/snip delete ",
            "/snip edit ",
            "/snip tag ",
        ):
            if text.startswith(prefix_cmd):
                partial = text[len(prefix_cmd) :]
                app_snippets = getattr(self.app, "_snippets", {})
                snippet_matches = sorted(
                    prefix_cmd + n for n in app_snippets if n.startswith(partial)
                )
                if not snippet_matches:
                    return
                if len(snippet_matches) == 1:
                    self.clear()
                    self.insert(snippet_matches[0])
                    self._tab_matches = []
                    self._tab_prefix = ""
                    return
                prefix = os.path.commonprefix(snippet_matches)
                if len(prefix) > len(text):
                    self.clear()
                    self.insert(prefix)
                    self._tab_matches = []
                    self._tab_prefix = ""
                    return
                self._tab_matches = snippet_matches
                self._tab_prefix = text
                self._tab_index = 0
                self.clear()
                self.insert(self._tab_matches[0])
                return

        # Template name completion for /template use|remove <name>
        for prefix_cmd in (
            "/template use ",
            "/template remove ",
        ):
            if text.startswith(prefix_cmd):
                partial = text[len(prefix_cmd) :]
                app_templates = getattr(self.app, "_templates", {})
                tmpl_matches = sorted(
                    prefix_cmd + n for n in app_templates if n.startswith(partial)
                )
                if not tmpl_matches:
                    return
                if len(tmpl_matches) == 1:
                    self.clear()
                    self.insert(tmpl_matches[0])
                    self._tab_matches = []
                    self._tab_prefix = ""
                    return
                prefix = os.path.commonprefix(tmpl_matches)
                if len(prefix) > len(text):
                    self.clear()
                    self.insert(prefix)
                    self._tab_matches = []
                    self._tab_prefix = ""
                    return
                self._tab_matches = tmpl_matches
                self._tab_prefix = text
                self._tab_index = 0
                self.clear()
                self.insert(self._tab_matches[0])
                return

        # Preset completion for /system use <preset>
        if text.startswith("/system use "):
            partial = text[len("/system use ") :]
            preset_matches = sorted(
                "/system use " + n for n in SYSTEM_PRESETS if n.startswith(partial)
            )
            if not preset_matches:
                return
            if len(preset_matches) == 1:
                self.clear()
                self.insert(preset_matches[0])
                self._tab_matches = []
                self._tab_prefix = ""
                return
            prefix = os.path.commonprefix(preset_matches)
            if len(prefix) > len(text):
                self.clear()
                self.insert(prefix)
                self._tab_matches = []
                self._tab_prefix = ""
                return
            self._tab_matches = preset_matches
            self._tab_prefix = text
            self._tab_index = 0
            self.clear()
            self.insert(self._tab_matches[0])
            return

        # Subcommand completion for /system <subcommand>
        if text.startswith("/system "):
            partial = text[len("/system ") :]
            subs = ["clear", "presets", "use", "append"]
            sub_matches = sorted("/system " + s for s in subs if s.startswith(partial))
            if not sub_matches:
                return
            if len(sub_matches) == 1:
                self.clear()
                self.insert(sub_matches[0] + " ")
                self._tab_matches = []
                self._tab_prefix = ""
                return
            prefix = os.path.commonprefix(sub_matches)
            if len(prefix) > len(text):
                self.clear()
                self.insert(prefix)
                self._tab_matches = []
                self._tab_prefix = ""
                return
            self._tab_matches = sub_matches
            self._tab_prefix = text
            self._tab_index = 0
            self.clear()
            self.insert(self._tab_matches[0])
            return

        # Path completion for /include <path>
        if text.startswith("/include "):
            partial_path = text[len("/include ") :].rstrip()
            # Strip --send flag for completion purposes
            if partial_path.endswith("--send"):
                return
            partial_path = partial_path.strip()
            if not partial_path:
                partial_path = ""
            try:
                from pathlib import Path

                p = Path(os.path.expanduser(partial_path or "."))
                if p.is_dir():
                    parent = p
                    prefix = ""
                else:
                    parent = p.parent if p.parent.is_dir() else Path(".")
                    prefix = p.name
                entries = sorted(parent.iterdir())
                path_matches = []
                for entry in entries:
                    name = str(entry)
                    if entry.name.startswith("."):
                        continue  # skip hidden files
                    if prefix and not entry.name.startswith(prefix):
                        continue
                    display = name + ("/" if entry.is_dir() else "")
                    path_matches.append(f"/include {display}")
                if not path_matches:
                    return
                if len(path_matches) == 1:
                    self.clear()
                    self.insert(path_matches[0])
                    self._tab_matches = []
                    self._tab_prefix = ""
                    return
                common = os.path.commonprefix(path_matches)
                if len(common) > len(text):
                    self.clear()
                    self.insert(common)
                    self._tab_matches = []
                    self._tab_prefix = ""
                    return
                self._tab_matches = path_matches
                self._tab_prefix = text
                self._tab_index = 0
                self.clear()
                self.insert(self._tab_matches[0])
            except OSError:
                pass
            return

        # Fresh completion: include built-in commands + user aliases
        app_aliases = getattr(self.app, "_aliases", {})
        all_commands = list(SLASH_COMMANDS) + ["/" + a for a in app_aliases]
        matches = sorted(c for c in all_commands if c.startswith(text))

        if not matches:
            return  # nothing to complete

        if len(matches) == 1:
            # Unique match – complete with a trailing space
            self.clear()
            self.insert(matches[0] + " ")
            self._tab_matches = []
            self._tab_prefix = ""
            return

        # Multiple matches – complete to the longest common prefix first
        prefix = os.path.commonprefix(matches)
        if len(prefix) > len(text):
            self.clear()
            self.insert(prefix)
            self._tab_matches = []
            self._tab_prefix = ""
            return

        # Common prefix == typed text already → start cycling
        self._tab_matches = matches
        self._tab_prefix = text
        self._tab_index = 0
        self.clear()
        self.insert(self._tab_matches[0])

    def _reset_tab_state(self) -> None:
        """Reset tab-completion cycling state."""
        self._tab_matches = []
        self._tab_index = 0
        self._tab_prefix = ""

    def _complete_snippet_mention(self) -> bool:
        """Complete @@name snippet mentions in the input.

        Finds the last @@partial token in the input text and completes it
        against saved snippet names.  Uses the same cycling mechanism as
        slash-command completion.

        Returns True if a completion was applied, False otherwise.
        """
        raw = self.text
        # Find the last @@token being typed (cursor is always at the end
        # for practical purposes — Textual TextArea cursor may be mid-text
        # but we complete the last @@ occurrence for simplicity).
        match = re.search(r"@@([\w-]*)$", raw)
        if match is None:
            return False

        partial = match.group(1)
        prefix_pos = match.start()  # position of the first @

        app_snippets = getattr(self.app, "_snippets", {})
        if not app_snippets:
            return False

        candidates = sorted(n for n in app_snippets if n.startswith(partial))
        if not candidates:
            return False

        # Build full-text replacements so cycling works with _tab_matches
        before = raw[:prefix_pos]
        full_matches = [before + "@@" + c for c in candidates]

        # Mid-cycle: advance to next match
        if self._tab_matches and self._tab_prefix and raw in self._tab_matches:
            self._tab_index = (self._tab_index + 1) % len(self._tab_matches)
            self.clear()
            self.insert(self._tab_matches[self._tab_index])
            return True

        if len(full_matches) == 1:
            # Unique match — complete with a trailing space
            self.clear()
            self.insert(full_matches[0] + " ")
            self._tab_matches = []
            self._tab_prefix = ""
            return True

        # Multiple matches — complete to longest common prefix first
        common = os.path.commonprefix(full_matches)
        if len(common) > len(raw):
            self.clear()
            self.insert(common)
            self._tab_matches = []
            self._tab_prefix = ""
            return True

        # Common prefix == typed text already → start cycling
        self._tab_matches = full_matches
        self._tab_prefix = raw
        self._tab_index = 0
        self.clear()
        self.insert(self._tab_matches[0])
        return True

    # -- Vim mode ------------------------------------------------------------

    def _update_vim_border(self) -> None:
        """Update the border title to show vim mode indicator."""
        if not self._vim_enabled:
            # When vim is off, let _update_line_indicator manage border_title
            return
        if self._vim_state == "normal":
            self.border_title = "-- NORMAL --"
        else:
            self.border_title = "-- INSERT --"

    def _handle_vim_normal_key(self, event) -> bool:
        """Handle a keypress in vim normal mode.

        Returns True if the event was consumed and should not propagate.
        """
        key = event.key
        buf = self._vim_key_buffer

        # Multi-char combos: accumulate into buffer
        if buf == "d" and key == "d":
            self._vim_key_buffer = ""
            self.action_delete_line()
            return True
        if buf == "g" and key == "g":
            self._vim_key_buffer = ""
            self.action_cursor_document_start()
            return True
        # If buffer was waiting for a second char but got something else, reset
        if buf:
            self._vim_key_buffer = ""

        # Start of potential multi-char combo
        if key == "d":
            self._vim_key_buffer = "d"
            return True
        if key == "g":
            self._vim_key_buffer = "g"
            return True

        # Mode switching
        if key == "i":
            self._vim_state = "insert"
            self._update_vim_border()
            return True
        if key == "a":
            self._vim_state = "insert"
            self.action_cursor_right()
            self._update_vim_border()
            return True
        if key == "shift+a" or key == "A":
            self._vim_state = "insert"
            self.action_cursor_line_end()
            self._update_vim_border()
            return True
        if key == "shift+i" or key == "I":
            self._vim_state = "insert"
            self.action_cursor_line_start()
            self._update_vim_border()
            return True
        if key == "o":
            self._vim_state = "insert"
            self.action_cursor_line_end()
            self.insert("\n")
            self._update_vim_border()
            return True
        if key == "shift+o" or key == "O":
            self._vim_state = "insert"
            self.action_cursor_line_start()
            self.insert("\n")
            self.action_cursor_up()
            self._update_vim_border()
            return True

        # Navigation
        if key == "h":
            self.action_cursor_left()
            return True
        if key == "j":
            self.action_cursor_down()
            return True
        if key == "k":
            self.action_cursor_up()
            return True
        if key == "l":
            self.action_cursor_right()
            return True
        if key == "w":
            self.action_cursor_word_right()
            return True
        if key == "b":
            self.action_cursor_word_left()
            return True
        if key == "0" or key == "home":
            self.action_cursor_line_start()
            return True
        if key in ("$", "end"):
            self.action_cursor_line_end()
            return True
        if key in ("shift+g", "G"):
            self.action_cursor_document_end()
            return True

        # Fold toggle
        if key == "z":
            self.app._toggle_fold_nearest()  # type: ignore[attr-defined]
            return True

        # Bookmark: Ctrl+B toggles bookmark on nearest message
        if key == "ctrl+b":
            self.app._toggle_bookmark_nearest()  # type: ignore[attr-defined]
            return True

        # Bookmark navigation: [ prev, ] next
        if key == "[":
            self.app._jump_prev_bookmark()  # type: ignore[attr-defined]
            return True
        if key == "]":
            self.app._jump_next_bookmark()  # type: ignore[attr-defined]
            return True

        # Editing in normal mode
        if key == "x":
            self.action_delete_right()
            return True
        if key in ("shift+x", "X"):
            self.action_delete_left()
            return True

        # Enter in normal mode enters insert mode (like vim's Enter moves down)
        if key == "enter":
            # Submit message just like non-vim mode
            return False  # Let _on_key handle it

        # Ignore other printable characters in normal mode (don't insert them)
        if len(key) == 1 and key.isprintable():
            return True

        # Let unrecognized keys pass through (ctrl combos, etc.)
        return False

    # -- Key handling --------------------------------------------------------

    def _update_line_indicator(self) -> None:
        """Show cursor position in border title and word/char count in border subtitle."""
        text = self.text

        if not text.strip():
            self.border_title = ""
            self.border_subtitle = ""
            return

        # Line/cursor info in border_title (multi-line only)
        total_lines = text.count("\n") + 1
        if total_lines > 1:
            row, col = self.cursor_location
            self.border_title = f"L{row + 1}/{total_lines} C{col + 1}"
        else:
            self.border_title = ""

        # Word/char count in border_subtitle
        words = len(text.split())
        chars = len(text)
        if chars > 500:
            est_tokens = int(words * 1.3)
            self.border_subtitle = f"{words}w {chars}c ~{est_tokens}tok"
        else:
            self.border_subtitle = f"{words}w {chars}c"

    async def _on_key(self, event) -> None:  # noqa: C901
        # ── Reverse search mode intercepts all keys ──────────────
        if getattr(self.app, "_rsearch_active", False):
            if self.app._handle_rsearch_key(self, event):
                event.prevent_default()
                event.stop()
                return
            # Returned False → search accepted, fall through to normal handling

        # ── Vim mode intercept ──────────────────────────────────
        if self._vim_enabled:
            if self._vim_state == "normal":
                consumed = self._handle_vim_normal_key(event)
                if consumed:
                    event.prevent_default()
                    event.stop()
                    self._update_vim_border()
                    return
                # Not consumed → fall through to normal handlers (enter, ctrl combos)
            elif self._vim_state == "insert" and event.key == "escape":
                self._vim_state = "normal"
                self._vim_key_buffer = ""
                self._update_vim_border()
                event.prevent_default()
                event.stop()
                return

        # Keys that always mean "send" regardless of mode
        _submit_keys = {"ctrl+j", "shift+enter", "ctrl+enter"}
        # Keys that always mean "newline" regardless of mode
        _newline_keys = {"shift+enter", "ctrl+enter"}

        # Slash commands: Enter always submits, alt keys always insert newline.
        # This reverses multiline-mode behavior for commands so /help, /tabs etc.
        # work naturally regardless of the multiline preference.
        _text_starts_with_slash = self.text.lstrip().startswith("/")

        if _text_starts_with_slash:
            # Slash command mode: Enter = send, Ctrl+J / Shift+Enter / Ctrl+Enter = literal newline
            if event.key in _submit_keys:
                event.prevent_default()
                event.stop()
                self._reset_tab_state()
                self.insert("\n")
                self._update_line_indicator()
                return
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self._reset_tab_state()
                self.post_message(self.Submitted(text_area=self))
                return
        elif self._multiline_mode:
            # Multiline mode: Enter = newline, Ctrl+J / Shift+Enter / Ctrl+Enter = send
            if event.key in _submit_keys:
                event.prevent_default()
                event.stop()
                self._reset_tab_state()
                self.post_message(self.Submitted(text_area=self))
                return
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self._reset_tab_state()
                self.insert("\n")
                self._update_line_indicator()
                return
        else:
            # Normal mode: Enter = send, Shift+Enter / Ctrl+J / Ctrl+Enter = newline
            if event.key in _submit_keys:
                event.prevent_default()
                event.stop()
                self._reset_tab_state()
                self.insert("\n")
                self._update_line_indicator()
                return
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self._reset_tab_state()
                self.post_message(self.Submitted(text_area=self))
                return

        if event.key == "tab":
            text = self.text.strip()
            if text.startswith("/"):
                event.prevent_default()
                event.stop()
                self._complete_slash_command(text)
                return
            # @@snippet tab-completion anywhere in input
            if "@@" in self.text:
                completed = self._complete_snippet_mention()
                if completed:
                    event.prevent_default()
                    event.stop()
                    return
            # Smart suggestion acceptance / cycling
            if self._suggestions_enabled:
                try:
                    bar = self.app.query_one("#suggestion-bar", SuggestionBar)
                except NoMatches:
                    logger.debug("Suggestion bar not found", exc_info=True)
                    bar = None
                if bar and bar.has_suggestions:
                    if self._suggestion_accepted:
                        # Repeated Tab → cycle to next suggestion
                        accepted = bar.cycle_next()
                    else:
                        # First Tab → accept current suggestion
                        accepted = bar.accept_current()
                    if accepted is not None:
                        self.clear()
                        self.insert(accepted)
                        self._suggestion_accepted = True
                        event.prevent_default()
                        event.stop()
                        return
            # Not a slash prefix – let default tab_behavior ("focus") happen
            self._reset_tab_state()
            await super()._on_key(event)
        elif event.key == "ctrl+j" and not self._multiline_mode:
            # Insert a newline (Ctrl+J = linefeed) — normal mode only
            # (In multiline mode, ctrl+j is handled above as "send")
            event.prevent_default()
            event.stop()
            self._reset_tab_state()
            self.insert("\n")
            self._update_line_indicator()
        elif event.key == "up":
            # History navigation when cursor is on the first line
            self._reset_tab_state()
            history = getattr(self.app, "_history", None)
            if history and history.entry_count > 0 and self.cursor_location[0] == 0:
                if not history.is_browsing:
                    history.start_browse(self.text)
                entry = history.previous()
                if entry is not None:
                    self.clear()
                    self.insert(entry)
                event.prevent_default()
                event.stop()
            else:
                await super()._on_key(event)
        elif event.key == "down":
            # History navigation when cursor is on the last line
            self._reset_tab_state()
            history = getattr(self.app, "_history", None)
            last_row = self.text.count("\n")
            if history and history.is_browsing and self.cursor_location[0] >= last_row:
                entry = history.next()
                if entry is not None:
                    self.clear()
                    self.insert(entry)
                event.prevent_default()
                event.stop()
            else:
                await super()._on_key(event)
        elif event.key == "home" and not self.text.strip():
            # When input is empty, Home jumps to top of chat
            self._reset_tab_state()
            self.app.action_scroll_chat_top()
            event.prevent_default()
            event.stop()
        elif event.key == "end" and not self.text.strip():
            # When input is empty, End jumps to bottom of chat
            self._reset_tab_state()
            self.app.action_scroll_chat_bottom()
            event.prevent_default()
            event.stop()
        else:
            self._reset_tab_state()
            self._suggestion_accepted = False
            await super()._on_key(event)
