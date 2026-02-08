"""Main Amplifier TUI application."""

from __future__ import annotations

import base64
import difflib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Collapsible,
    Input,
    Markdown,
    OptionList,
    Static,
    TextArea,
    Tree,
)
from textual.widgets.option_list import Option
from textual import work

from .history import PromptHistory
from .preferences import (
    COLOR_NAMES,
    ColorPreferences,
    THEME_DESCRIPTIONS,
    THEMES,
    load_preferences,
    resolve_color,
    save_colors,
    save_compact_mode,
    save_notification_enabled,
    save_notification_min_seconds,
    save_notification_sound,
    save_preferred_model,
    save_session_sort,
    save_show_timestamps,
    save_streaming_enabled,
    save_theme_name,
    save_vim_mode,
    save_word_wrap,
)
from .theme import TEXTUAL_THEMES

# Tool name -> human-friendly status label (without trailing "...")
TOOL_LABELS: dict[str, str] = {
    "read_file": "Reading file",
    "write_file": "Writing file",
    "edit_file": "Editing file",
    "grep": "Searching",
    "glob": "Finding files",
    "bash": "Running command",
    "web_search": "Searching web",
    "web_fetch": "Fetching page",
    "delegate": "Delegating to agent",
    "task": "Delegating to agent",
    "LSP": "Analyzing code",
    "python_check": "Checking code",
    "todo": "Planning",
    "recipes": "Running recipe",
    "load_skill": "Loading skill",
}

_MAX_LABEL_LEN = 38  # Keep status labels under ~40 chars total

# Canonical list of slash commands – used by both _handle_slash_command and
# ChatInput tab-completion.  Keep in sync with the handlers dict below.
SLASH_COMMANDS: tuple[str, ...] = (
    "/help",
    "/clear",
    "/new",
    "/sessions",
    "/preferences",
    "/prefs",
    "/model",
    "/quit",
    "/exit",
    "/focus",
    "/compact",
    "/copy",
    "/notify",
    "/sound",
    "/scroll",
    "/timestamps",
    "/keys",
    "/stats",
    "/theme",
    "/export",
    "/rename",
    "/delete",
    "/bookmark",
    "/bm",
    "/bookmarks",
    "/search",
    "/colors",
    "/pin",
    "/pins",
    "/unpin",
    "/pin-session",
    "/draft",
    "/tokens",
    "/context",
    "/sort",
    "/edit",
    "/editor",
    "/wrap",
    "/alias",
    "/info",
    "/fold",
    "/history",
    "/grep",
    "/redo",
    "/undo",
    "/snippet",
    "/snippets",
    "/template",
    "/templates",
    "/title",
    "/diff",
    "/ref",
    "/refs",
    "/vim",
    "/watch",
    "/split",
    "/stream",
    "/tab",
    "/tabs",
)


MAX_TABS = 10  # Maximum number of concurrent tabs


@dataclass
class TabState:
    """State for a single conversation tab."""

    name: str
    tab_id: str
    container_id: str  # ScrollableContainer widget ID for this tab
    # Session state (saved/restored when switching tabs)
    sm_session: object | None = None
    sm_session_id: str | None = None
    session_title: str = ""
    # Search index
    search_messages: list = field(default_factory=list)
    # Statistics
    total_words: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_call_count: int = 0
    user_words: int = 0
    assistant_words: int = 0
    response_times: list = field(default_factory=list)
    tool_usage: dict = field(default_factory=dict)
    assistant_msg_index: int = 0
    last_assistant_widget: object | None = None
    last_assistant_text: str = ""
    # Per-session data
    session_bookmarks: list = field(default_factory=list)
    session_refs: list = field(default_factory=list)
    message_pins: list = field(default_factory=list)
    created_at: str = ""


# Known context window sizes (tokens) for popular models.
# Used as fallback when the provider doesn't report context_window.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-3-5-sonnet": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-sonnet": 200_000,
    "claude-haiku": 200_000,
    "claude-opus": 200_000,
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "gpt-3.5": 16_385,
    "o1-mini": 128_000,
    "o1": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    "gemini": 1_000_000,
}
DEFAULT_CONTEXT_WINDOW = 200_000


def _get_tool_label(name: str, tool_input: dict | str | None) -> str:
    """Map a tool name (+ optional input) to a short, human-friendly label."""
    base = TOOL_LABELS.get(name, f"Running {name}")
    inp = tool_input if isinstance(tool_input, dict) else {}

    # Add file/path context for file-related tools
    if name in ("read_file", "write_file", "edit_file"):
        path = inp.get("file_path", "")
        if path:
            short = Path(path).name
            base = f"{base.rsplit('.', 1)[0].rstrip('.')} {short}"

    elif name == "grep":
        pattern = inp.get("pattern", "")
        if pattern:
            if len(pattern) > 20:
                pattern = pattern[:17] + "..."
            base = f"Searching: {pattern}"

    elif name == "delegate":
        agent = inp.get("agent", "")
        if agent:
            short = agent.split(":")[-1] if ":" in agent else agent
            base = f"Delegating to {short}"

    elif name == "bash":
        cmd = inp.get("command", "")
        if cmd:
            first_line = cmd.split("\n", 1)[0]
            if len(first_line) > 25:
                first_line = first_line[:22] + "\u2026"
            base = f"Running: {first_line}"

    elif name == "web_fetch":
        url = inp.get("url", "")
        if url:
            try:
                from urllib.parse import urlparse

                host = urlparse(url).netloc
                if host:
                    base = f"Fetching {host}"
            except Exception:
                pass

    elif name == "web_search":
        query = inp.get("query", "")
        if query:
            if len(query) > 20:
                query = query[:17] + "\u2026"
            base = f"Searching: {query}"

    elif name == "glob":
        pattern = inp.get("pattern", "")
        if pattern:
            if len(pattern) > 20:
                pattern = pattern[:17] + "\u2026"
            base = f"Finding: {pattern}"

    elif name == "LSP":
        op = inp.get("operation", "")
        if op:
            base = f"Analyzing: {op}"

    elif name == "python_check":
        paths = inp.get("paths")
        if paths and isinstance(paths, list) and paths[0]:
            short = Path(paths[0]).name
            base = f"Checking {short}"

    elif name == "load_skill":
        skill = inp.get("skill_name", "") or inp.get("search", "")
        if skill:
            base = f"Loading skill: {skill}"

    elif name == "todo":
        action = inp.get("action", "")
        if action:
            base = f"Planning: {action}"

    elif name == "recipes":
        op = inp.get("operation", "")
        if op:
            base = f"Recipe: {op}"

    # Truncate to keep status bar tidy, then add ellipsis
    if len(base) > _MAX_LABEL_LEN:
        base = base[: _MAX_LABEL_LEN - 1] + "\u2026"
    return f"{base}..."


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Tries OSC 52 first, then native tools."""
    # OSC 52: works in most modern terminals (WezTerm, iTerm2, kitty, etc.)
    # and even over SSH sessions.
    try:
        encoded = base64.b64encode(text.encode()).decode()
        sys.stdout.write(f"\033]52;c;{encoded}\a")
        sys.stdout.flush()
        return True
    except Exception:
        pass

    # Fallback: native clipboard tools with platform-specific handling
    try:
        uname_release = platform.uname().release.lower()
    except Exception:
        uname_release = ""

    # WSL: clip.exe expects UTF-16LE
    if "microsoft" in uname_release and shutil.which("clip.exe"):
        try:
            proc = subprocess.Popen(
                ["clip.exe"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.communicate(text.encode("utf-16-le"))
            if proc.returncode == 0:
                return True
        except Exception:
            pass

    # macOS
    if platform.system() == "Darwin" and shutil.which("pbcopy"):
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=2)
            return True
        except Exception:
            pass

    # Linux: try xclip, then xsel
    for cmd in [
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ]:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=2)
                return True
            except Exception:
                continue

    return False


# ── Widget Classes ──────────────────────────────────────────────────


class UserMessage(Static):
    """A user chat message (plain text with styling)."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message user-message")


class ThinkingStatic(Static):
    """A thinking block rendered as a static widget (for transcript replay)."""

    pass


class AssistantMessage(Markdown):
    """An assistant chat message rendered as markdown."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message assistant-message")


class ThinkingBlock(Static):
    """A dimmed thinking/reasoning block."""

    pass


class ChatInput(TextArea):
    """TextArea where Enter submits, Shift+Enter/Ctrl+J inserts a newline."""

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

        # Snippet name completion for /snippet use|send|remove|edit|tag <name>
        for prefix_cmd in (
            "/snippet use ",
            "/snippet send ",
            "/snippet remove ",
            "/snippet edit ",
            "/snippet tag ",
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

        if event.key == "shift+enter":
            # Insert newline (Shift+Enter = multi-line composition)
            event.prevent_default()
            event.stop()
            self._reset_tab_state()
            self.insert("\n")
            self._update_line_indicator()
        elif event.key == "enter":
            # Submit the message
            event.prevent_default()
            event.stop()
            self._reset_tab_state()
            self.post_message(self.Submitted(text_area=self))
        elif event.key == "tab":
            text = self.text.strip()
            if text.startswith("/"):
                event.prevent_default()
                event.stop()
                self._complete_slash_command(text)
                return
            # Not a slash prefix – let default tab_behavior ("focus") happen
            self._reset_tab_state()
            await super()._on_key(event)
        elif event.key == "ctrl+j":
            # Insert a newline (Ctrl+J = linefeed)
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
            await super()._on_key(event)


class ProcessingIndicator(Static):
    """Animated indicator shown during processing."""

    pass


class ErrorMessage(Static):
    """An inline error message."""

    pass


class SystemMessage(Static):
    """A system/command output message (slash command results)."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message system-message")


class FoldToggle(Static):
    """Clickable indicator to fold/unfold a long message."""

    def __init__(
        self, target: Static, line_count: int, *, folded: bool = False
    ) -> None:
        self._target = target
        self._line_count = line_count
        super().__init__(self._make_label(folded=folded), classes="fold-toggle")

    def _make_label(self, *, folded: bool) -> str:
        if folded:
            return f"▶ {self._line_count} lines (click to expand)"
        return f"▼ {self._line_count} lines (click to fold)"

    def on_click(self) -> None:
        folded = self._target.has_class("folded")
        if folded:
            self._target.remove_class("folded")
        else:
            self._target.add_class("folded")
        self.update(self._make_label(folded=not folded))


# ── Shortcut Overlay ────────────────────────────────────────

SHORTCUTS_TEXT = """\
         Keyboard Shortcuts
──────────────────────────────────────────

 NAVIGATION ─────────────────────────────
  Ctrl+↑/↓         Scroll chat up/down
  Ctrl+Home/End    Jump to top/bottom
  Home/End          Top/bottom (input empty)
  ↑/↓              Browse prompt history
  Ctrl+B           Toggle sidebar
  Tab              Cycle focus
  F11              Focus mode

 CHAT ───────────────────────────────────
  Enter            Send message
  Shift+Enter      New line (also Ctrl+J)
  Escape           Cancel AI streaming
  Ctrl+C           Cancel AI response
  Ctrl+L           Clear chat
  Ctrl+A           Toggle auto-scroll

 SEARCH & EDIT ──────────────────────────
  Ctrl+F           Search chat messages
  Ctrl+R           Reverse history search
  Ctrl+G           Open external editor
  Ctrl+Y           Copy last AI response
  Ctrl+M           Bookmark last response
  Ctrl+S           Stash/restore draft

 SESSIONS ───────────────────────────────
  Ctrl+N           New session
  Ctrl+T           New tab
  Ctrl+W           Close tab
  Ctrl+PgUp/Dn    Switch tabs
  F1 / Ctrl+/      This help
  Ctrl+Q           Quit

          Slash Commands
──────────────────────────────────────────
  Type /help for the full reference

 SESSION ────────────────────────────────
  /new             New session
  /sessions        Toggle session sidebar
  /rename          Rename session
  /title           View/set session title
  /delete          Delete current session
  /pin-session     Pin/unpin in sidebar
  /sort            Sort sessions
  /tab             Tab management
  /tabs            List open tabs
  /info            Session details
  /stats           Session statistics (tools, tokens)

 CHAT & HISTORY ─────────────────────────
  /clear           Clear chat display
  /copy            Copy response (N/all/code)
  /undo [N]        Undo last N exchange(s)
  /redo [N]        Resend last message
  /fold            Fold/unfold long messages
  /compact         Toggle compact mode
  /history         Browse/clear input history

 SEARCH ─────────────────────────────────
  /search          Search chat messages
  /grep            Search chat (regex)

 PINS & BOOKMARKS ──────────────────────
  /pin [N]         Pin a message
  /pins            List pinned messages
  /unpin N         Remove a pin
  /bookmark        Bookmark last response
  /bookmarks       List/jump to bookmarks
  /ref             Save URL/reference
  /refs             List saved references

 MODEL & DISPLAY ───────────────────────
  /model [name]    View/switch AI model
  /theme [name]    Switch color theme
  /colors          View/set custom colors
  /wrap            Toggle word wrap
  /timestamps      Toggle timestamps
  /focus           Toggle focus mode
  /stream          Toggle streaming display
  /scroll          Toggle auto-scroll

 EXPORT & DATA ─────────────────────────
  /export          Export chat (md/txt/json)
  /diff            Show git diff (color-coded)
  /watch           Watch files for changes
  /tokens          Token/context usage
  /context         Context window details

 INPUT & SETTINGS ──────────────────────
  /edit            Open $EDITOR for input
  /editor          Alias for /edit
  /draft           Save/load input drafts
  /snippet         Prompt snippets
  /template        Prompt templates with {{variables}}
  /alias           Custom command shortcuts
  /vim             Toggle vim keybindings
  /prefs           Preferences
  /notify          Toggle notifications
  /sound           Toggle notification sound (on|off|test)
  /keys            Show this overlay
  /quit            Quit

    Press F1, Ctrl+/, or Esc to close\
"""


class ShortcutOverlay(ModalScreen):
    """Modal overlay showing all keyboard shortcuts and slash commands."""

    BINDINGS = [
        Binding("escape", "dismiss_overlay", show=False),
        Binding("f1", "dismiss_overlay", show=False),
        Binding("ctrl+question_mark", "dismiss_overlay", show=False),
        Binding("ctrl+slash", "dismiss_overlay", show=False),
    ]

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="shortcut-modal"):
            yield Static(SHORTCUTS_TEXT, id="shortcut-content")

    def action_dismiss_overlay(self) -> None:
        self.app.pop_screen()

    def on_click(self, event) -> None:
        """Dismiss overlay when clicking outside the modal content."""
        modal = self.query_one("#shortcut-modal")
        if (event.screen_x, event.screen_y) not in modal.region:
            self.app.pop_screen()


class HistorySearchScreen(ModalScreen[str]):
    """Modal for searching prompt history with fuzzy filtering."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

    def __init__(self, history: PromptHistory) -> None:
        super().__init__()
        self._history = history

    def compose(self) -> ComposeResult:
        with Vertical(id="history-search-modal"):
            yield Static(
                "Search History  [dim](type to filter, Enter selects)[/]",
                id="history-search-title",
            )
            yield Input(placeholder="Type to filter…", id="history-search-input")
            yield OptionList(id="history-search-results")

    def on_mount(self) -> None:
        self._update_results("")
        self.query_one("#history-search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "history-search-input":
            self._update_results(event.value)

    def _update_results(self, query: str) -> None:
        option_list = self.query_one("#history-search-results", OptionList)
        option_list.clear_options()
        matches = self._history.search(query)
        for item in matches:
            display = item[:120] + "…" if len(item) > 120 else item
            option_list.add_option(Option(display, id=item))
        if matches:
            option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # Option id stores the full original text
        if event.option.id is not None:
            self.dismiss(event.option.id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "history-search-input":
            option_list = self.query_one("#history-search-results", OptionList)
            if option_list.option_count > 0 and option_list.highlighted is not None:
                opt = option_list.get_option_at_index(option_list.highlighted)
                if opt.id is not None:
                    self.dismiss(opt.id)
            else:
                self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")


class TabButton(Static):
    """A clickable tab label in the tab bar."""

    def __init__(self, label: str, tab_index: int, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.tab_index = tab_index

    def on_click(self) -> None:
        self.app._switch_to_tab(self.tab_index)


class TabBar(Horizontal):
    """Horizontal tab bar showing conversation tabs."""

    def update_tabs(self, tabs: list, active_index: int) -> None:
        """Rebuild the tab bar buttons."""
        self.remove_children()
        for i, tab in enumerate(tabs):
            label = tab.name
            cls = "tab-btn tab-active" if i == active_index else "tab-btn tab-inactive"
            btn = TabButton(f" {label} ", tab_index=i, classes=cls)
            self.mount(btn)
        # Hide tab bar when there's only one tab
        if len(tabs) <= 1:
            self.add_class("single-tab")
        else:
            self.remove_class("single-tab")


# ── Main Application ────────────────────────────────────────────────


class AmplifierChicApp(App):
    """Amplifier TUI - a clean TUI for Amplifier."""

    CSS_PATH = "styles.tcss"
    TITLE = "Amplifier TUI"

    MAX_STASHES = 5
    SESSION_NAMES_FILE = Path.home() / ".amplifier" / "tui-session-names.json"
    BOOKMARKS_FILE = Path.home() / ".amplifier" / "tui-bookmarks.json"
    PINNED_SESSIONS_FILE = Path.home() / ".amplifier" / "tui-pinned-sessions.json"
    MESSAGE_PINS_FILE = Path.home() / ".amplifier" / "tui-pins.json"
    DRAFTS_FILE = Path.home() / ".amplifier" / "tui-drafts.json"
    ALIASES_FILE = Path.home() / ".amplifier" / "tui-aliases.json"
    SNIPPETS_FILE = Path.home() / ".amplifier" / "tui-snippets.json"
    TEMPLATES_FILE = Path.home() / ".amplifier" / "tui-templates.json"
    SESSION_TITLES_FILE = Path.home() / ".amplifier" / "tui-session-titles.json"
    REFS_FILE = Path.home() / ".amplifier" / "tui-refs.json"
    CRASH_DRAFT_FILE = Path.home() / ".amplifier" / "tui-draft.txt"

    DEFAULT_SNIPPETS: dict[str, dict[str, str]] = {
        "review": {
            "content": "Please review this code for bugs, security issues, and best practices.",
            "category": "prompts",
        },
        "explain": {
            "content": "Explain this code step by step, focusing on the key logic and design decisions.",
            "category": "prompts",
        },
        "refactor": {
            "content": "Refactor this code to be more readable, maintainable, and following best practices.",
            "category": "prompts",
        },
        "test": {
            "content": "Write comprehensive tests for this code, covering edge cases and error conditions.",
            "category": "prompts",
        },
        "doc": {
            "content": "Add clear documentation comments to this code.",
            "category": "prompts",
        },
    }

    DEFAULT_TEMPLATES: dict[str, str] = {
        "review": (
            "Review this code for bugs, performance issues, and best practices:\n\n"
            "```{{language}}\n{{code}}\n```"
        ),
        "explain": (
            "Explain this {{language}} code in detail, covering what it does and why:\n\n"
            "```{{language}}\n{{code}}\n```"
        ),
        "refactor": (
            "Refactor this {{language}} code to improve {{aspect}}:\n\n"
            "```{{language}}\n{{code}}\n```"
        ),
        "test": (
            "Write comprehensive tests for this {{language}} function:\n\n"
            "```{{language}}\n{{code}}\n```"
        ),
        "debug": (
            "Help me debug this {{language}} code. The error is: {{error}}\n\n"
            "```{{language}}\n{{code}}\n```"
        ),
        "commit": "Write a commit message for these changes:\n\n{{diff}}",
    }

    BINDINGS = [
        Binding("f1", "show_shortcuts", "Help", show=True),
        Binding("ctrl+question_mark", "show_shortcuts", "Shortcuts", show=False),
        Binding("ctrl+slash", "show_shortcuts", "Shortcuts", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Sessions", show=True),
        Binding("ctrl+g", "open_editor", "Editor", show=True),
        Binding("ctrl+s", "stash_prompt", "Stash", show=True),
        Binding("ctrl+y", "copy_response", "Copy", show=True),
        Binding("ctrl+n", "new_session", "New", show=True),
        Binding("f11", "toggle_focus_mode", "Focus", show=False),
        Binding("ctrl+a", "toggle_auto_scroll", "Scroll", show=False),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
        Binding("ctrl+m", "bookmark_last", "Bookmark", show=False),
        Binding("ctrl+r", "search_history", "History", show=False),
        Binding("ctrl+f", "search_chat", "Search", show=False),
        Binding("ctrl+home", "scroll_chat_top", "Top of chat", show=False),
        Binding("ctrl+end", "scroll_chat_bottom", "Bottom of chat", show=False),
        Binding("ctrl+up", "scroll_chat_up", "Scroll up", show=False),
        Binding("ctrl+down", "scroll_chat_down", "Scroll down", show=False),
        Binding("ctrl+t", "new_tab", "New Tab", show=False),
        Binding("ctrl+w", "close_tab", "Close Tab", show=False),
        Binding("ctrl+pageup", "prev_tab", "Prev Tab", show=False),
        Binding("ctrl+pagedown", "next_tab", "Next Tab", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        resume_session_id: str | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.resume_session_id = resume_session_id
        self.initial_prompt = initial_prompt
        self.session_manager: object | None = None
        self.is_processing = False
        self._got_stream_content = False
        self._amplifier_available = True
        self._amplifier_ready = False
        self._session_list_data: list[dict] = []
        self._sidebar_visible = False
        self._spinner_frame = 0
        self._spinner_timer: object | None = None
        self._processing_label: str | None = None
        self._prefs = load_preferences()
        self._history = PromptHistory()
        self._stash_stack: list[str] = []
        self._last_assistant_text: str = ""
        self._processing_start_time: float | None = None

        # Pending delete confirmation (two-step delete)
        self._pending_delete: str | None = None

        # Pending undo confirmation (two-step for N>1)
        self._pending_undo: int | None = None

        # Auto-scroll state
        self._auto_scroll = True

        # Focus mode state (zen mode - hides chrome)
        self._focus_mode = False
        self._sidebar_was_visible_before_focus = False

        # Word count tracking
        self._total_words: int = 0

        # Per-turn tool counter (for progress labels like "[#3]")
        self._tool_count_this_turn: int = 0

        # Session statistics counters
        self._user_message_count: int = 0
        self._assistant_message_count: int = 0
        self._tool_call_count: int = 0
        self._user_words: int = 0
        self._assistant_words: int = 0
        self._session_start_time: float = time.monotonic()
        self._response_times: list[float] = []
        self._tool_usage: dict[str, int] = {}

        # Custom command aliases
        self._aliases: dict[str, str] = {}

        # Reusable prompt snippets (values: {content, category, created})
        self._snippets: dict[str, dict[str, str]] = {}

        # Prompt templates with {{variable}} placeholders
        self._templates: dict[str, str] = {}

        # Bookmark tracking
        self._assistant_msg_index: int = 0
        self._last_assistant_widget: Static | None = None
        self._session_bookmarks: list[dict] = []

        # URL/reference collector (/ref command)
        self._session_refs: list[dict] = []

        # Streaming display state
        self._stream_widget: Static | None = None
        self._stream_container: Collapsible | None = None
        self._stream_block_type: str | None = None
        self._streaming_cancelled: bool = False
        self._stream_accumulated_text: str = ""

        # Search index: parallel list of (role, text, widget) for /search
        self._search_messages: list[tuple[str, str, Static | None]] = []

        # Pinned sessions (appear at top of sidebar)
        self._pinned_sessions: set[str] = set()

        # Pinned messages (per-session bookmarks for quick recall)
        self._message_pins: list[dict] = []

        # Message folding state
        self._fold_threshold: int = 30

        # Crash-recovery draft timer (debounced save)
        self._crash_draft_timer: object | None = None

        # Session auto-title (extracted from first user message)
        self._session_title: str = ""

        # File watch state (/watch command)
        self._watched_files: dict[str, dict] = {}
        self._watch_timer: object | None = None

        # Tab management state
        self._tabs: list[TabState] = [
            TabState(
                name="Main",
                tab_id="tab-0",
                container_id="chat-view",
                created_at=datetime.now().isoformat(),
            )
        ]
        self._active_tab_index: int = 0
        self._tab_counter: int = 1

        # Reverse search state (Ctrl+R inline)
        self._rsearch_active: bool = False
        self._rsearch_query: str = ""
        self._rsearch_matches: list[int] = []
        self._rsearch_match_idx: int = -1
        self._rsearch_original: str = ""

    # ── Layout ──────────────────────────────────────────────────

    def _active_chat_view(self) -> ScrollableContainer:
        """Return the chat container for the currently active tab."""
        tab = self._tabs[self._active_tab_index]
        return self.query_one(f"#{tab.container_id}", ScrollableContainer)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            with Vertical(id="session-sidebar"):
                yield Static(" Sessions", id="sidebar-title")
                yield Input(
                    placeholder="Filter sessions...",
                    id="session-filter",
                )
                yield Tree("Sessions", id="session-tree")
            with Vertical(id="chat-area"):
                yield Static("", id="breadcrumb-bar")
                yield TabBar(id="tab-bar")
                with Horizontal(id="chat-split-container"):
                    yield ScrollableContainer(id="chat-view", classes="tab-chat-view")
                    yield ScrollableContainer(id="split-panel")
                yield ChatInput(
                    "",
                    id="chat-input",
                    soft_wrap=True,
                    show_line_numbers=False,
                    tab_behavior="focus",
                    compact=True,
                )
                yield Static("", id="input-counter")
                with Horizontal(id="status-bar"):
                    yield Static("No session", id="status-session")
                    yield Static("Ready", id="status-state")
                    yield Static("", id="status-stash")
                    yield Static("", id="status-vim")
                    yield Static("\u2195 ON", id="status-scroll")
                    yield Static("0 words", id="status-wordcount")
                    yield Static("", id="status-context")
                    yield Static("", id="status-model")

    async def on_mount(self) -> None:
        # Register all built-in color themes
        for _tname, tobj in TEXTUAL_THEMES.items():
            self.register_theme(tobj)

        # Apply the saved theme (or default to dark)
        saved = self._prefs.theme_name
        textual_theme = TEXTUAL_THEMES.get(saved, TEXTUAL_THEMES["dark"])
        self.theme = textual_theme.name

        # Apply word-wrap preference (default: on; off adds no-wrap CSS class)
        if not self._prefs.display.word_wrap:
            self._active_chat_view().add_class("no-wrap")

        # Apply compact-mode preference (default: off; on adds compact-mode CSS class)
        if self._prefs.display.compact_mode:
            self.add_class("compact-mode")

        # Apply vim-mode preference (default: off; starts in normal mode)
        if self._prefs.display.vim_mode:
            input_w = self.query_one("#chat-input", ChatInput)
            input_w._vim_enabled = True
            input_w._vim_state = "normal"
            input_w._update_vim_border()
            self._update_vim_status()

        # Initialize tab bar
        self._update_tab_bar()

        # Show UI immediately, defer Amplifier import to background
        self._show_welcome()
        self.query_one("#chat-input", ChatInput).focus()

        # Start the spinner timer
        self._spinner_frame = 0
        self._spinner_timer = self.set_interval(0.3, self._animate_spinner)

        # Load pinned sessions
        self._pinned_sessions = self._load_pinned_sessions()

        # Load message pins for current session
        self._message_pins = self._load_message_pins()

        # Load custom command aliases
        self._aliases = self._load_aliases()

        # Load reusable prompt snippets
        self._snippets = self._load_snippets()

        # Load prompt templates with {{variable}} placeholders
        self._templates = self._load_templates()

        # Periodic draft auto-save in case of crash
        self.set_interval(30, self._auto_save_draft)

        # Restore crash-recovery draft if one exists from a previous crash
        crash_draft = self._load_crash_draft()
        if crash_draft:
            try:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.insert(crash_draft)
                preview = crash_draft[:60].replace("\n", " ")
                if len(crash_draft) > 60:
                    preview += "..."
                self._add_system_message(
                    f"Recovered unsent draft ({len(crash_draft)} chars): "
                    f"{preview}\n"
                    "Press Enter to send, or edit as needed."
                )
            except Exception:
                pass

        # Heavy import in background
        self._init_amplifier_worker()

    @work(thread=True)
    def _init_amplifier_worker(self) -> None:
        """Import Amplifier in background so UI appears instantly."""
        self.call_from_thread(self._update_status, "Loading Amplifier...")
        try:
            from .session_manager import SessionManager

            self.session_manager = SessionManager()
            self._amplifier_ready = True
        except Exception:
            self._amplifier_available = False
            self.call_from_thread(
                self._show_welcome,
                "Amplifier not found. Install: uv tool install amplifier",
            )
            self.call_from_thread(self._update_status, "Not connected")
            return

        # Now handle resume or initial prompt
        if self.resume_session_id:
            self._resume_session_worker(self.resume_session_id)
        elif self.initial_prompt:
            prompt = self.initial_prompt
            self.initial_prompt = None
            self.call_from_thread(self._clear_welcome)
            self.call_from_thread(self._add_user_message, prompt)
            self.call_from_thread(self._start_processing, "Starting session")
            self._send_message_worker(prompt)
        else:
            self.call_from_thread(self._update_status, "Ready")

        self.call_from_thread(self._update_breadcrumb)
        self.call_from_thread(self._load_session_list)

    # ── Tab Management ──────────────────────────────────────────

    def _update_tab_bar(self) -> None:
        """Refresh the tab bar UI."""
        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            tab_bar.update_tabs(self._tabs, self._active_tab_index)
        except Exception:
            pass

    def _save_current_tab_state(self) -> None:
        """Save current app state into the active tab's TabState."""
        tab = self._tabs[self._active_tab_index]
        if self.session_manager:
            tab.sm_session = getattr(self.session_manager, "session", None)
            tab.sm_session_id = getattr(self.session_manager, "session_id", None)
        tab.session_title = self._session_title
        tab.search_messages = self._search_messages
        tab.total_words = self._total_words
        tab.user_message_count = self._user_message_count
        tab.assistant_message_count = self._assistant_message_count
        tab.tool_call_count = self._tool_call_count
        tab.user_words = self._user_words
        tab.assistant_words = self._assistant_words
        tab.response_times = self._response_times
        tab.tool_usage = self._tool_usage
        tab.assistant_msg_index = self._assistant_msg_index
        tab.last_assistant_widget = self._last_assistant_widget
        tab.last_assistant_text = self._last_assistant_text
        tab.session_bookmarks = self._session_bookmarks
        tab.session_refs = self._session_refs
        tab.message_pins = self._message_pins

    def _load_tab_state(self, tab: TabState) -> None:
        """Load a TabState's data into current app state."""
        if self.session_manager:
            self.session_manager.session = tab.sm_session
            self.session_manager.session_id = tab.sm_session_id
        self._session_title = tab.session_title
        self._search_messages = tab.search_messages
        self._total_words = tab.total_words
        self._user_message_count = tab.user_message_count
        self._assistant_message_count = tab.assistant_message_count
        self._tool_call_count = tab.tool_call_count
        self._user_words = tab.user_words
        self._assistant_words = tab.assistant_words
        self._response_times = tab.response_times
        self._tool_usage = tab.tool_usage
        self._assistant_msg_index = tab.assistant_msg_index
        self._last_assistant_widget = tab.last_assistant_widget
        self._last_assistant_text = tab.last_assistant_text
        self._session_bookmarks = tab.session_bookmarks
        self._session_refs = tab.session_refs
        self._message_pins = tab.message_pins

    def _switch_to_tab(self, index: int) -> None:
        """Switch to the tab at the given index."""
        if index == self._active_tab_index:
            return
        if index < 0 or index >= len(self._tabs):
            return
        if self.is_processing:
            self._add_system_message("Cannot switch tabs while processing.")
            return

        # Save current tab state
        self._save_current_tab_state()

        # Hide current tab's container
        old_tab = self._tabs[self._active_tab_index]
        try:
            old_container = self.query_one(
                f"#{old_tab.container_id}", ScrollableContainer
            )
            old_container.add_class("tab-chat-hidden")
        except Exception:
            pass

        # Switch index
        self._active_tab_index = index

        # Show new tab's container
        new_tab = self._tabs[index]
        try:
            new_container = self.query_one(
                f"#{new_tab.container_id}", ScrollableContainer
            )
            new_container.remove_class("tab-chat-hidden")
        except Exception:
            pass

        # Load new tab state
        self._load_tab_state(new_tab)

        # Update UI
        self._update_tab_bar()
        self._update_session_display()
        self._update_word_count_display()
        self._update_breadcrumb()
        self.sub_title = self._session_title or ""
        self.query_one("#chat-input", ChatInput).focus()

    def _create_new_tab(self, name: str | None = None) -> None:
        """Create a new conversation tab."""
        if len(self._tabs) >= MAX_TABS:
            self._add_system_message(
                f"Maximum {MAX_TABS} tabs allowed. Close a tab first."
            )
            return
        if self.is_processing:
            self._add_system_message("Cannot create tab while processing.")
            return

        tab_id = f"tab-{self._tab_counter}"
        container_id = f"chat-view-{self._tab_counter}"
        self._tab_counter += 1

        if not name:
            name = f"Tab {len(self._tabs) + 1}"

        tab = TabState(
            name=name,
            tab_id=tab_id,
            container_id=container_id,
            created_at=datetime.now().isoformat(),
        )

        # Save current tab state before switching
        self._save_current_tab_state()

        # Hide current tab's container
        old_tab = self._tabs[self._active_tab_index]
        try:
            old_container = self.query_one(
                f"#{old_tab.container_id}", ScrollableContainer
            )
            old_container.add_class("tab-chat-hidden")
        except Exception:
            pass

        # Create new container and mount it
        new_container = ScrollableContainer(id=container_id, classes="tab-chat-view")
        try:
            split_container = self.query_one("#chat-split-container", Horizontal)
            # Mount before split-panel
            split_panel = self.query_one("#split-panel", ScrollableContainer)
            split_container.mount(new_container, before=split_panel)
        except Exception:
            pass

        # Add tab and switch to it
        self._tabs.append(tab)
        self._active_tab_index = len(self._tabs) - 1

        # Reset app state for new tab
        if self.session_manager:
            self.session_manager.session = None
            self.session_manager.session_id = None
        self._session_title = ""
        self._search_messages = []
        self._total_words = 0
        self._user_message_count = 0
        self._assistant_message_count = 0
        self._tool_call_count = 0
        self._user_words = 0
        self._assistant_words = 0
        self._response_times = []
        self._tool_usage = {}
        self._assistant_msg_index = 0
        self._last_assistant_widget = None
        self._last_assistant_text = ""
        self._session_bookmarks = []
        self._session_refs = []
        self._message_pins = []

        # Update UI
        self._update_tab_bar()
        self._update_session_display()
        self._update_word_count_display()
        self._update_breadcrumb()
        self.sub_title = ""
        self._show_welcome(f"New tab: {name}")
        self.query_one("#chat-input", ChatInput).focus()

    def _close_tab(self, index: int | None = None) -> None:
        """Close a tab by index (default: current tab)."""
        if index is None:
            index = self._active_tab_index
        if index < 0 or index >= len(self._tabs):
            self._add_system_message("Invalid tab index.")
            return
        if len(self._tabs) <= 1:
            self._add_system_message("Cannot close the last tab.")
            return
        if self.is_processing and index == self._active_tab_index:
            self._add_system_message("Cannot close tab while processing.")
            return

        closing_tab = self._tabs[index]

        # Remove the container widget
        try:
            container = self.query_one(
                f"#{closing_tab.container_id}", ScrollableContainer
            )
            container.remove()
        except Exception:
            pass

        # Remove from tabs list
        self._tabs.pop(index)

        # Adjust active index
        if index == self._active_tab_index:
            # Was viewing this tab - switch to nearest
            self._active_tab_index = min(index, len(self._tabs) - 1)
            new_tab = self._tabs[self._active_tab_index]
            # Show new active container
            try:
                new_container = self.query_one(
                    f"#{new_tab.container_id}", ScrollableContainer
                )
                new_container.remove_class("tab-chat-hidden")
            except Exception:
                pass
            self._load_tab_state(new_tab)
        elif index < self._active_tab_index:
            self._active_tab_index -= 1

        # Update UI
        self._update_tab_bar()
        self._update_session_display()
        self._update_word_count_display()
        self._update_breadcrumb()
        self.sub_title = self._session_title or ""

    def _rename_tab(self, new_name: str) -> None:
        """Rename the current tab."""
        self._tabs[self._active_tab_index].name = new_name.strip()
        self._update_tab_bar()

    def _find_tab_by_name_or_index(self, query: str) -> int | None:
        """Find a tab by name or 1-based index number."""
        # Try as number first (1-based)
        try:
            idx = int(query) - 1
            if 0 <= idx < len(self._tabs):
                return idx
        except ValueError:
            pass
        # Try by name (case-insensitive)
        query_lower = query.lower().strip()
        for i, tab in enumerate(self._tabs):
            if tab.name.lower() == query_lower:
                return i
        return None

    # ── Tab Action Methods (keyboard shortcuts) ─────────────────

    def action_new_tab(self) -> None:
        """Create a new tab (Ctrl+T)."""
        self._create_new_tab()

    def action_close_tab(self) -> None:
        """Close current tab (Ctrl+W)."""
        if len(self._tabs) <= 1:
            self._add_system_message("Cannot close the last tab.")
            return
        # Check if current tab has content
        tab = self._tabs[self._active_tab_index]
        try:
            container = self.query_one(f"#{tab.container_id}", ScrollableContainer)
            has_content = len(list(container.children)) > 0
        except Exception:
            has_content = False
        if has_content:
            self._close_tab()
        else:
            self._close_tab()

    def action_prev_tab(self) -> None:
        """Switch to previous tab (Ctrl+PageUp)."""
        if len(self._tabs) <= 1:
            return
        new_index = (self._active_tab_index - 1) % len(self._tabs)
        self._switch_to_tab(new_index)

    def action_next_tab(self) -> None:
        """Switch to next tab (Ctrl+PageDown)."""
        if len(self._tabs) <= 1:
            return
        new_index = (self._active_tab_index + 1) % len(self._tabs)
        self._switch_to_tab(new_index)

    # ── Welcome Screen ──────────────────────────────────────────

    def _show_welcome(self, subtitle: str = "") -> None:
        chat_view = self._active_chat_view()
        # Remove any existing welcome first
        for w in self.query(".welcome-screen"):
            w.remove()
        lines = [
            "Amplifier TUI",
            "",
            "Type a message to start a new session.",
            "Ctrl+B to browse sessions.  Ctrl+N for new session.",
        ]
        if subtitle:
            lines.append(f"\n{subtitle}")
        chat_view.mount(Static("\n".join(lines), classes="welcome-screen"))

    def _clear_welcome(self) -> None:
        for w in self.query(".welcome-screen"):
            w.remove()

    # ── Session List Sidebar ────────────────────────────────────

    # ── Session Names ─────────────────────────────────────────────

    def _load_session_names(self) -> dict[str, str]:
        """Load custom session names from the JSON file."""
        try:
            if self.SESSION_NAMES_FILE.exists():
                return json.loads(self.SESSION_NAMES_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_session_name(self, session_id: str, name: str) -> None:
        """Save a custom session name to the JSON file."""
        names = self._load_session_names()
        names[session_id] = name
        self.SESSION_NAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.SESSION_NAMES_FILE.write_text(json.dumps(names, indent=2))

    # ── Session Titles ──────────────────────────────────────────

    @staticmethod
    def _extract_title(message: str, max_len: int = 50) -> str:
        """Extract a short title from a user message."""
        text = re.sub(r"```.*?```", "", message, flags=re.DOTALL)  # code blocks
        text = re.sub(r"`[^`]+`", "", text)  # inline code
        text = re.sub(r"[#*_~>\[\]()]", "", text)  # markdown chars
        text = re.sub(r"https?://\S+", "", text)  # URLs
        text = text.strip()

        if not text:
            return "Untitled"

        # Take first line
        first_line = text.split("\n")[0].strip()

        # Strip conversational filler prefixes for a cleaner title
        for prefix in (
            "please ",
            "can you ",
            "could you ",
            "would you ",
            "i want to ",
            "i need to ",
            "i'd like to ",
            "help me ",
            "hey ",
            "hi ",
            "hello ",
        ):
            if first_line.lower().startswith(prefix):
                first_line = first_line[len(prefix) :]
                break

        # Take first sentence (up to period, question mark, or exclamation)
        for i, ch in enumerate(first_line):
            if ch in ".?!" and i > 10:
                first_line = first_line[: i + 1]
                break

        # Truncate to max length at word boundary
        if len(first_line) > max_len:
            truncated = first_line[:max_len]
            last_space = truncated.rfind(" ")
            if last_space > max_len // 2:
                truncated = truncated[:last_space]
            first_line = truncated.rstrip(".!?, ") + "..."

        # Capitalize first letter for a polished look
        title = first_line.strip()
        return (title[0].upper() + title[1:]) if title else "Untitled"

    def _load_session_titles(self) -> dict[str, str]:
        """Load session titles from the JSON file."""
        try:
            if self.SESSION_TITLES_FILE.exists():
                return json.loads(self.SESSION_TITLES_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_session_title(self) -> None:
        """Save current session title to the JSON file."""
        sid = self._get_session_id()
        if not sid:
            return
        try:
            titles = self._load_session_titles()
            if self._session_title:
                titles[sid] = self._session_title
            elif sid in titles:
                del titles[sid]
            # Keep last 200 titles
            if len(titles) > 200:
                keys = list(titles.keys())
                for k in keys[:-200]:
                    del titles[k]
            self.SESSION_TITLES_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.SESSION_TITLES_FILE.write_text(json.dumps(titles, indent=2))
        except Exception:
            pass

    def _load_session_title_for(self, session_id: str) -> str:
        """Load the title for a specific session."""
        titles = self._load_session_titles()
        return titles.get(session_id, "")

    def _apply_session_title(self) -> None:
        """Update the UI to reflect the current session title."""
        self.sub_title = self._session_title
        self._update_breadcrumb()
        self._save_session_title()

    # ── Pinned Sessions ─────────────────────────────────────────

    def _load_pinned_sessions(self) -> set[str]:
        """Load pinned session IDs from the JSON file."""
        try:
            if self.PINNED_SESSIONS_FILE.exists():
                data = json.loads(self.PINNED_SESSIONS_FILE.read_text())
                return set(data)
        except Exception:
            pass
        return set()

    def _save_pinned_sessions(self) -> None:
        """Persist the current set of pinned session IDs."""
        try:
            self.PINNED_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.PINNED_SESSIONS_FILE.write_text(
                json.dumps(sorted(self._pinned_sessions), indent=2)
            )
        except Exception:
            pass

    def _remove_pinned_session(self, session_id: str) -> None:
        """Remove a session from pinned set (e.g. on delete)."""
        if session_id in self._pinned_sessions:
            self._pinned_sessions.discard(session_id)
            self._save_pinned_sessions()

    # ── Aliases ──────────────────────────────────────────────

    def _load_aliases(self) -> dict[str, str]:
        """Load custom command aliases from the JSON file."""
        try:
            if self.ALIASES_FILE.exists():
                return json.loads(self.ALIASES_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_aliases(self) -> None:
        """Persist custom command aliases."""
        try:
            self.ALIASES_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.ALIASES_FILE.write_text(
                json.dumps(self._aliases, indent=2, sort_keys=True)
            )
        except Exception:
            pass

    # ── Snippets ────────────────────────────────────────────

    def _load_snippets(self) -> dict[str, dict[str, str]]:
        """Load reusable prompt snippets from the JSON file.

        Handles migration from old ``{name: text}`` format to the new
        ``{name: {content, category, created}}`` structure.
        """
        try:
            if self.SNIPPETS_FILE.exists():
                raw = json.loads(self.SNIPPETS_FILE.read_text())
                migrated = self._migrate_snippets(raw)
                if migrated is not raw:
                    # Re-persist in the new format
                    try:
                        self.SNIPPETS_FILE.write_text(
                            json.dumps(migrated, indent=2, sort_keys=True)
                        )
                    except Exception:
                        pass
                return migrated
        except Exception:
            pass
        # First run: seed with default snippets
        defaults = dict(self.DEFAULT_SNIPPETS)
        try:
            self.SNIPPETS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.SNIPPETS_FILE.write_text(
                json.dumps(defaults, indent=2, sort_keys=True)
            )
        except Exception:
            pass
        return defaults

    @staticmethod
    def _migrate_snippets(
        data: dict[str, str | dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """Migrate old ``{name: text}`` format to ``{name: {content, category, created}}``."""
        needs_migration = any(isinstance(v, str) for v in data.values())
        if not needs_migration:
            return data  # type: ignore[return-value]
        migrated: dict[str, dict[str, str]] = {}
        today = datetime.now().strftime("%Y-%m-%d")
        for name, value in data.items():
            if isinstance(value, str):
                migrated[name] = {"content": value, "category": "", "created": today}
            else:
                migrated[name] = value  # type: ignore[assignment]
        return migrated

    def _save_snippets(self) -> None:
        """Persist reusable prompt snippets."""
        try:
            self.SNIPPETS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.SNIPPETS_FILE.write_text(
                json.dumps(self._snippets, indent=2, sort_keys=True)
            )
        except Exception:
            pass

    # ── Templates ─────────────────────────────────────────

    def _load_templates(self) -> dict[str, str]:
        """Load prompt templates from the JSON file."""
        try:
            if self.TEMPLATES_FILE.exists():
                return json.loads(self.TEMPLATES_FILE.read_text())
        except Exception:
            pass
        # First run: seed with default templates
        defaults = dict(self.DEFAULT_TEMPLATES)
        try:
            self.TEMPLATES_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.TEMPLATES_FILE.write_text(
                json.dumps(defaults, indent=2, sort_keys=True)
            )
        except Exception:
            pass
        return defaults

    def _save_templates(self) -> None:
        """Persist prompt templates."""
        try:
            self.TEMPLATES_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.TEMPLATES_FILE.write_text(
                json.dumps(self._templates, indent=2, sort_keys=True)
            )
        except Exception:
            pass

    # ── Drafts ────────────────────────────────────────────────

    def _load_drafts(self) -> dict[str, str]:
        """Load all drafts from the JSON file."""
        try:
            if self.DRAFTS_FILE.exists():
                return json.loads(self.DRAFTS_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_draft(self) -> None:
        """Save current input as draft for active session."""
        try:
            session_id = self._get_session_id()
            if not session_id:
                return

            input_widget = self.query_one("#chat-input", ChatInput)
            text = input_widget.text.strip()

            drafts = self._load_drafts()

            if text:
                drafts[session_id] = text
            elif session_id in drafts:
                del drafts[session_id]
            else:
                return  # Nothing to save or clear

            self.DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.DRAFTS_FILE.write_text(json.dumps(drafts, indent=2))
        except Exception:
            pass

    def _restore_draft(self) -> None:
        """Restore draft for current session if one exists."""
        try:
            session_id = self._get_session_id()
            if not session_id:
                return

            drafts = self._load_drafts()
            draft_text = drafts.get(session_id, "")

            if draft_text:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.clear()
                input_widget.insert(draft_text)
                self._add_system_message(f"Draft restored ({len(draft_text)} chars)")
        except Exception:
            pass

    def _clear_draft(self) -> None:
        """Remove draft for current session."""
        try:
            session_id = self._get_session_id()
            if not session_id:
                return
            drafts = self._load_drafts()
            if session_id in drafts:
                del drafts[session_id]
                self.DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
                self.DRAFTS_FILE.write_text(json.dumps(drafts, indent=2))
        except Exception:
            pass

    def _auto_save_draft(self) -> None:
        """Periodic auto-save of input draft (called by timer)."""
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            if input_widget.text.strip():
                self._save_draft()
        except Exception:
            pass

    # ── Crash-recovery draft (global, plain-text) ─────────────────

    def _save_crash_draft(self) -> None:
        """Save current input to global crash-recovery draft file."""
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            text = input_widget.text.strip()
            if text:
                self.CRASH_DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
                self.CRASH_DRAFT_FILE.write_text(text)
            elif self.CRASH_DRAFT_FILE.exists():
                self.CRASH_DRAFT_FILE.unlink()
        except Exception:
            pass

    def _clear_crash_draft(self) -> None:
        """Clear the global crash-recovery draft file."""
        try:
            if self.CRASH_DRAFT_FILE.exists():
                self.CRASH_DRAFT_FILE.unlink()
        except Exception:
            pass

    def _load_crash_draft(self) -> str | None:
        """Load crash-recovery draft if it exists and is non-empty."""
        try:
            if self.CRASH_DRAFT_FILE.exists():
                text = self.CRASH_DRAFT_FILE.read_text().strip()
                if text:
                    return text
        except Exception:
            pass
        return None

    # ── Bookmarks ─────────────────────────────────────────────

    def _get_session_id(self) -> str | None:
        """Return the current session ID, or None."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        return getattr(sm, "session_id", None) if sm else None

    def _load_bookmarks(self) -> dict[str, list[dict]]:
        """Load all bookmarks from the JSON file."""
        try:
            if self.BOOKMARKS_FILE.exists():
                return json.loads(self.BOOKMARKS_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_bookmark(self, session_id: str, bookmark: dict) -> None:
        """Append a bookmark for the given session."""
        all_bm = self._load_bookmarks()
        if session_id not in all_bm:
            all_bm[session_id] = []
        all_bm[session_id].append(bookmark)
        self.BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.BOOKMARKS_FILE.write_text(json.dumps(all_bm, indent=2))

    def _load_session_bookmarks(self, session_id: str | None = None) -> list[dict]:
        """Load bookmarks for the current (or given) session."""
        sid = session_id or self._get_session_id()
        if not sid:
            return []
        return self._load_bookmarks().get(sid, [])

    def _apply_bookmark_classes(self) -> None:
        """Re-apply the 'bookmarked' CSS class to bookmarked assistant messages."""
        if not self._session_bookmarks:
            return
        bookmarked_indices = {bm["message_index"] for bm in self._session_bookmarks}
        for widget in self.query(".assistant-message"):
            idx = getattr(widget, "msg_index", None)
            if idx is not None and idx in bookmarked_indices:
                widget.add_class("bookmarked")

    # ── URL/Reference Collector (/ref) ───────────────────────────────

    def _load_all_refs(self) -> dict[str, list[dict]]:
        """Load all refs from the JSON file."""
        try:
            if self.REFS_FILE.exists():
                return json.loads(self.REFS_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_refs(self) -> None:
        """Persist the current session's refs to disk."""
        sid = self._get_session_id()
        if not sid:
            return
        try:
            all_refs = self._load_all_refs()
            all_refs[sid] = self._session_refs
            self.REFS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.REFS_FILE.write_text(json.dumps(all_refs, indent=2))
        except Exception:
            pass

    def _load_session_refs(self, session_id: str | None = None) -> list[dict]:
        """Load refs for the current (or given) session."""
        sid = session_id or self._get_session_id()
        if not sid:
            return []
        return self._load_all_refs().get(sid, [])

    def _cmd_ref(self, text: str) -> None:
        """Handle /ref command for URL/reference collection."""
        # Strip the command prefix ("/ref" or "/refs")
        parts = text.strip().split(None, 1)
        args = parts[1].strip() if len(parts) > 1 else ""

        # /ref  or  /refs  — list all refs
        if not args:
            if not self._session_refs:
                self._add_system_message(
                    "No saved references.\n"
                    "Add: /ref <url-or-text> [label]\n"
                    "Example: /ref https://docs.python.org Python Docs"
                )
                return
            lines = ["Saved References:"]
            for i, ref in enumerate(self._session_refs, 1):
                label = ref.get("label", "")
                url = ref["url"]
                ts = ref.get("timestamp", "")[:10]
                if label:
                    lines.append(f"  {i}. [{label}] {url}  ({ts})")
                else:
                    lines.append(f"  {i}. {url}  ({ts})")
            lines.append("")
            lines.append("  /ref remove <#> | /ref clear | /ref export")
            self._add_system_message("\n".join(lines))
            return

        # /ref clear
        if args == "clear":
            count = len(self._session_refs)
            self._session_refs.clear()
            self._save_refs()
            self._add_system_message(f"Cleared {count} reference(s)")
            return

        # /ref remove <N>
        if args.startswith("remove"):
            remove_parts = args.split()
            if len(remove_parts) < 2:
                self._add_system_message("Usage: /ref remove <number>")
                return
            try:
                idx = int(remove_parts[1]) - 1
                if 0 <= idx < len(self._session_refs):
                    removed = self._session_refs.pop(idx)
                    self._save_refs()
                    self._add_system_message(f"Removed: {removed['url']}")
                else:
                    self._add_system_message(
                        f"Invalid index. Range: 1-{len(self._session_refs)}"
                    )
            except (ValueError, IndexError):
                self._add_system_message("Usage: /ref remove <number>")
            return

        # /ref export
        if args == "export":
            self._export_refs()
            return

        # /ref <url-or-text> [label]  — add a new reference
        add_parts = args.split(None, 1)
        url = add_parts[0]
        label = add_parts[1] if len(add_parts) > 1 else ""

        self._session_refs.append(
            {
                "url": url,
                "label": label,
                "timestamp": datetime.now().isoformat(),
                "source": "manual",
            }
        )
        self._save_refs()

        msg = f"Saved reference: {url}"
        if label:
            msg += f" [{label}]"
        self._add_system_message(msg)

    def _export_refs(self) -> None:
        """Export saved references to a markdown file."""
        if not self._session_refs:
            self._add_system_message("No references to export")
            return

        sid = self._get_session_id() or "default"
        lines = [
            "# Session References",
            "",
            f"Session: `{sid[:12]}`",
            f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for i, ref in enumerate(self._session_refs, 1):
            label = ref.get("label") or ref["url"]
            url = ref["url"]
            ts = ref.get("timestamp", "")[:10]
            source = ref.get("source", "manual")
            lines.append(f"{i}. [{label}]({url}) -- {ts} ({source})")

        filepath = Path.home() / ".amplifier" / "refs-export.md"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text("\n".join(lines) + "\n")
        self._add_system_message(
            f"Exported {len(self._session_refs)} reference(s) to {filepath}"
        )

    # ── Message Pins ─────────────────────────────────────────────

    def _load_message_pins(self) -> list[dict]:
        """Load pinned messages for the current session."""
        try:
            if self.MESSAGE_PINS_FILE.exists():
                all_pins = json.loads(self.MESSAGE_PINS_FILE.read_text())
                sid = self._get_session_id() or "default"
                return all_pins.get(sid, [])
        except Exception:
            pass
        return []

    def _save_message_pins(self) -> None:
        """Persist message pins keyed by session ID."""
        try:
            all_pins: dict[str, list[dict]] = {}
            if self.MESSAGE_PINS_FILE.exists():
                all_pins = json.loads(self.MESSAGE_PINS_FILE.read_text())
            sid = self._get_session_id() or "default"
            if self._message_pins:
                all_pins[sid] = self._message_pins
            elif sid in all_pins:
                del all_pins[sid]
            # Keep last 50 sessions worth of pins
            if len(all_pins) > 50:
                keys = list(all_pins.keys())
                for k in keys[:-50]:
                    del all_pins[k]
            self.MESSAGE_PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.MESSAGE_PINS_FILE.write_text(json.dumps(all_pins, indent=2))
        except Exception:
            pass

    def _add_message_pin(self, index: int, content: str) -> None:
        """Pin a message by its _search_messages index."""
        preview = content[:80].replace("\n", " ")
        if len(content) > 80:
            preview += "..."

        # Check if already pinned
        for pin in self._message_pins:
            if pin["index"] == index:
                self._add_system_message(f"Message {index + 1} is already pinned")
                return

        self._message_pins.append(
            {
                "index": index,
                "preview": preview,
                "pinned_at": datetime.now().isoformat(),
            }
        )
        self._save_message_pins()

        pin_num = len(self._message_pins)
        role = self._search_messages[index][0]
        label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(role, role)
        self._add_system_message(
            f"\U0001f4cc Pinned #{pin_num} ({label} msg #{index + 1}): {preview}"
        )

    def _load_session_list(self) -> None:
        """Show loading state then populate in background."""
        if not self._amplifier_available:
            return
        tree = self.query_one("#session-tree", Tree)
        tree.clear()
        tree.root.add_leaf("Loading sessions...")
        self._load_sessions_worker()

    @work(thread=True)
    def _load_sessions_worker(self) -> None:
        """Load session list in background thread."""
        from .session_manager import SessionManager

        sessions = SessionManager.list_all_sessions(limit=50)
        self.call_from_thread(self._populate_session_list, sessions)

    def _session_display_label(
        self,
        s: dict,
        custom_names: dict[str, str],
        session_titles: dict[str, str] | None = None,
    ) -> str:
        """Build the display string for a session tree node.

        Returns e.g. ``"01/15 14:02  My Project"`` or ``"▪ 01/15 14:02  My Project"``
        with a pin marker when the session is pinned.
        """
        sid = s["session_id"]
        custom = custom_names.get(sid)
        title = (session_titles or {}).get(sid, "")
        name = s.get("name", "")
        desc = s.get("description", "")

        if custom:
            label = custom[:28] if len(custom) > 28 else custom
        elif title:
            label = title[:28] if len(title) > 28 else title
        elif name:
            label = name[:28] if len(name) > 28 else name
        elif desc:
            label = desc[:28] if len(desc) > 28 else desc
        else:
            label = sid[:8]

        date = s["date_str"]
        pin = "▪ " if sid in self._pinned_sessions else ""
        return f"{pin}{date}  {label}"

    def _sort_sessions(
        self, sessions: list[dict], custom_names: dict[str, str]
    ) -> list[dict]:
        """Return *sessions* sorted according to the active sort preference."""
        mode = getattr(self._prefs, "session_sort", "date")
        if mode == "name":
            # Alphabetical by display name (custom name > metadata name > id)
            def _sort_name(s: dict) -> str:
                sid = s["session_id"]
                custom = custom_names.get(sid)
                if custom:
                    return custom.lower()
                name = s.get("name", "")
                if name:
                    return name.lower()
                return sid.lower()

            return sorted(sessions, key=_sort_name)
        elif mode == "project":
            # Group by project (alphabetical), then by date within each group
            return sorted(sessions, key=lambda s: (s["project"].lower(), -s["mtime"]))
        else:
            # "date" default: most recent first
            return sorted(sessions, key=lambda s: s["mtime"], reverse=True)

    def _populate_session_list(self, sessions: list[dict]) -> None:
        """Populate sidebar tree with sessions grouped by project folder.

        Pinned sessions are rendered first under a dedicated group, then the
        remaining sessions are sorted/grouped per the active sort preference.
        Session ID is stored as node ``data`` for selection handling.
        """
        self._session_list_data = []
        tree = self.query_one("#session-tree", Tree)
        tree.clear()
        tree.show_root = False

        if not sessions:
            tree.root.add_leaf("No sessions found")
            return

        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        # Partition into pinned / unpinned
        pinned = [s for s in sessions if s["session_id"] in self._pinned_sessions]
        unpinned = [s for s in sessions if s["session_id"] not in self._pinned_sessions]

        # Sort unpinned according to preference
        unpinned = self._sort_sessions(unpinned, custom_names)

        # ── Pinned group ──
        if pinned:
            pin_group = tree.root.add("▪ Pinned", expand=True)
            for s in pinned:
                sid = s["session_id"]
                display = self._session_display_label(s, custom_names, session_titles)
                node = pin_group.add(display, data=sid)
                node.add_leaf(f"id: {sid[:12]}...")
                node.collapse()
                self._session_list_data.append(s)

        # ── Unpinned, grouped by project ──
        current_group: str | None = None
        group_node = tree.root
        for s in unpinned:
            project = s["project"]
            if project != current_group:
                current_group = project
                parts = project.split("/")
                short = "/".join(parts[-2:]) if len(parts) > 2 else project
                group_node = tree.root.add(short, expand=True)

            sid = s["session_id"]
            display = self._session_display_label(s, custom_names, session_titles)
            session_node = group_node.add(display, data=sid)
            session_node.add_leaf(f"id: {sid[:12]}...")
            session_node.collapse()
            self._session_list_data.append(s)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter the session tree as the user types in the filter input."""
        if event.input.id == "session-filter":
            self._filter_sessions(event.value)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update the input counter and line indicator when the chat input changes."""
        if event.text_area.id == "chat-input":
            self._update_input_counter(event.text_area.text)
            # Update the border subtitle line indicator (handles paste, clear, etc.)
            if isinstance(event.text_area, ChatInput):
                event.text_area._update_line_indicator()
            # Debounced crash-recovery draft save (5-second delay)
            if self._crash_draft_timer is not None:
                self._crash_draft_timer.stop()
            self._crash_draft_timer = self.set_timer(5.0, self._save_crash_draft)

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        """Update cursor position in border title when selection/cursor moves."""
        if event.text_area.id == "chat-input" and isinstance(
            event.text_area, ChatInput
        ):
            event.text_area._update_line_indicator()

    def _update_input_counter(self, text: str) -> None:
        """Update the character/line counter below the chat input."""
        try:
            counter = self.query_one("#input-counter", Static)
        except Exception:
            return

        if not text.strip():
            counter.update("")
            counter.display = False
            return

        chars = len(text)
        lines = text.count("\n") + 1

        if chars >= 1000:
            char_str = f"{chars / 1000:.1f}k chars"
        else:
            char_str = f"{chars} chars"

        if lines > 1:
            counter.update(f"{lines} lines \u00b7 {char_str}")
        else:
            counter.update(char_str)
        counter.display = True

    def on_key(self, event) -> None:
        """Handle Escape: cancel streaming, exit focus mode, or clear session filter."""
        if event.key == "escape":
            # Cancel in-progress streaming takes highest priority
            if self.is_processing:
                self.action_cancel_streaming()
                event.prevent_default()
                event.stop()
                return

            # Exit focus mode first if active (only when input is empty
            # so we don't conflict with vim mode or other Escape uses)
            if self._focus_mode:
                input_empty = True
                try:
                    input_empty = not self.query_one(
                        "#chat-input", ChatInput
                    ).text.strip()
                except Exception:
                    pass
                if input_empty:
                    self._set_focus_mode(False)
                    event.prevent_default()
                    event.stop()
                    return
            try:
                filt = self.query_one("#session-filter", Input)
                if filt.has_focus and filt.value:
                    filt.value = ""
                    event.prevent_default()
                    event.stop()
            except Exception:
                pass

    def _filter_sessions(self, query: str) -> None:
        """Rebuild the session tree showing only sessions matching *query*.

        Matches against session name/description, session ID, and project path.
        Pinned sessions appear first under a dedicated group.
        When the query is empty, all sessions are shown.
        """
        tree = self.query_one("#session-tree", Tree)
        tree.clear()
        tree.show_root = False

        sessions = self._session_list_data
        if not sessions:
            return

        q = query.lower().strip()
        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        def _matches(s: dict) -> bool:
            """Return True if the session matches the current filter query."""
            if not q:
                return True
            sid = s["session_id"]
            display = self._session_display_label(s, custom_names, session_titles)
            project = s["project"]
            return q in display.lower() or q in sid.lower() or q in project.lower()

        # Partition into pinned / unpinned
        pinned = [
            s
            for s in sessions
            if s["session_id"] in self._pinned_sessions and _matches(s)
        ]
        unpinned = [
            s
            for s in sessions
            if s["session_id"] not in self._pinned_sessions and _matches(s)
        ]
        matched = len(pinned) + len(unpinned)

        # Sort unpinned according to preference
        unpinned = self._sort_sessions(unpinned, custom_names)

        # ── Pinned group ──
        if pinned:
            pin_group = tree.root.add("▪ Pinned", expand=True)
            for s in pinned:
                sid = s["session_id"]
                display = self._session_display_label(s, custom_names, session_titles)
                node = pin_group.add(display, data=sid)
                node.add_leaf(f"id: {sid[:12]}...")
                node.collapse()

        # ── Unpinned, grouped by project ──
        current_group: str | None = None
        group_node = tree.root
        for s in unpinned:
            project = s["project"]
            if project != current_group:
                current_group = project
                parts = project.split("/")
                short = "/".join(parts[-2:]) if len(parts) > 2 else project
                group_node = tree.root.add(short, expand=True)

            sid = s["session_id"]
            display = self._session_display_label(s, custom_names, session_titles)
            session_node = group_node.add(display, data=sid)
            session_node.add_leaf(f"id: {sid[:12]}...")
            session_node.collapse()

        if q and matched == 0:
            tree.root.add_leaf("No matching sessions")

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#session-sidebar")
        self._sidebar_visible = not self._sidebar_visible
        if self._sidebar_visible:
            sidebar.add_class("visible")
            self._load_session_list()
            # Focus the filter input so user can start typing immediately
            self.query_one("#session-filter", Input).focus()
        else:
            sidebar.remove_class("visible")
            # Clear filter when closing so next open shows all sessions
            self.query_one("#session-filter", Input).value = ""

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle session selection from the sidebar tree.

        Sessions are expandable nodes: click to toggle expand (shows session ID),
        double-click/Enter on the node OR its children loads the session.
        The sidebar stays open - user closes it manually with Ctrl+B.
        """
        node = event.node
        # Check the node itself, or its parent, for a session_id
        session_id = node.data
        if session_id is None and node.parent is not None:
            session_id = node.parent.data
        if session_id is None:
            return
        # Save draft for current session before switching
        self._save_draft()
        # Don't close sidebar - let user close it manually with Ctrl+B
        self._resume_session_worker(session_id)

    # ── Actions ─────────────────────────────────────────────────

    def action_show_shortcuts(self) -> None:
        """Toggle the keyboard shortcut overlay (F1 / Ctrl+/)."""
        if isinstance(self.screen, ShortcutOverlay):
            self.pop_screen()
        else:
            self.push_screen(ShortcutOverlay())

    def action_search_history(self) -> None:
        """Enter reverse-incremental search mode (Ctrl+R).

        If already in search mode (Ctrl+R pressed again), cycle to the
        next match.  Otherwise start a fresh search session.
        """
        if self._history.entry_count == 0:
            self._add_system_message("No prompt history yet.")
            return

        if self._rsearch_active:
            # Already searching – cycle to next older match
            self._rsearch_cycle_next()
            return

        input_widget = self.query_one("#chat-input", ChatInput)
        self._rsearch_active = True
        self._rsearch_query = ""
        self._rsearch_matches = []
        self._rsearch_match_idx = -1
        self._rsearch_original = input_widget.text
        self._update_rsearch_display()
        input_widget.focus()

    # ── Reverse search helpers ────────────────────────────────────

    def _handle_rsearch_key(self, widget: ChatInput, event: object) -> bool:
        """Handle a key press while reverse search is active.

        Returns ``True`` if the key was consumed (caller should
        ``prevent_default`` + ``stop``).  Returns ``False`` when
        search was accepted and the key should be handled normally.
        """
        key = getattr(event, "key", "")

        if key == "escape":
            self._rsearch_cancel()
            return True

        if key in ("enter", "shift+enter"):
            self._rsearch_accept()
            return True

        if key == "backspace":
            if self._rsearch_query:
                self._rsearch_query = self._rsearch_query[:-1]
                self._do_rsearch()
            return True

        if key == "ctrl+r":
            self._rsearch_cycle_next()
            return True

        character = getattr(event, "character", None)
        is_printable = getattr(event, "is_printable", False)
        if character and is_printable:
            self._rsearch_query += character
            self._do_rsearch()
            return True

        # Any other key (arrows, ctrl combos, …) – accept result, fall through
        self._rsearch_accept()
        return False

    def _rsearch_cycle_next(self) -> None:
        """Cycle to the next (older) match in the current result set."""
        if (
            not self._rsearch_matches
            or self._rsearch_match_idx >= len(self._rsearch_matches) - 1
        ):
            self._update_rsearch_display()
            return
        self._rsearch_match_idx += 1
        entry = self._history.get_entry(self._rsearch_matches[self._rsearch_match_idx])
        if entry is not None:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            input_widget.insert(entry)
        self._update_rsearch_display()

    def _do_rsearch(self) -> None:
        """Execute a reverse search and display the best match."""
        input_widget = self.query_one("#chat-input", ChatInput)
        query = self._rsearch_query
        if not query:
            self._rsearch_matches = []
            self._rsearch_match_idx = -1
            input_widget.clear()
            input_widget.insert(self._rsearch_original)
            self._update_rsearch_display()
            return

        self._rsearch_matches = self._history.reverse_search_indices(query)
        if self._rsearch_matches:
            self._rsearch_match_idx = 0
            entry = self._history.get_entry(self._rsearch_matches[0])
            if entry is not None:
                input_widget.clear()
                input_widget.insert(entry)
        else:
            self._rsearch_match_idx = -1
        self._update_rsearch_display()

    def _rsearch_cancel(self) -> None:
        """Cancel reverse search and restore the original input."""
        self._rsearch_active = False
        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget.clear()
        input_widget.insert(self._rsearch_original)
        self._clear_rsearch_display()

    def _rsearch_accept(self) -> None:
        """Accept the current search result and exit search mode."""
        self._rsearch_active = False
        self._clear_rsearch_display()

    def _update_rsearch_display(self) -> None:
        """Show the search indicator in the input border subtitle."""
        try:
            iw = self.query_one("#chat-input", ChatInput)
            if self._rsearch_matches:
                n = len(self._rsearch_matches)
                pos = self._rsearch_match_idx + 1
                iw.border_subtitle = (
                    f"(reverse-search) '{self._rsearch_query}' [{pos}/{n}]"
                )
            elif self._rsearch_query:
                iw.border_subtitle = (
                    f"(reverse-search) '{self._rsearch_query}' [no matches]"
                )
            else:
                iw.border_subtitle = "(reverse-search)"
        except Exception:
            pass

    def _clear_rsearch_display(self) -> None:
        """Remove the search indicator; restore the line-count subtitle."""
        try:
            self.query_one("#chat-input", ChatInput)._update_line_indicator()
        except Exception:
            pass

    def action_search_chat(self) -> None:
        """Focus the input and pre-fill /grep for quick chat searching (Ctrl+F)."""
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            input_widget.insert("/grep ")
            input_widget.focus()
        except Exception:
            pass

    def action_scroll_chat_top(self) -> None:
        """Scroll chat to the very top (Ctrl+Home)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_home(animate=False)
        except Exception:
            pass

    def action_scroll_chat_bottom(self) -> None:
        """Scroll chat to the very bottom (Ctrl+End)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_end(animate=False)
        except Exception:
            pass

    def action_scroll_chat_up(self) -> None:
        """Scroll chat up by a small amount (Ctrl+Up)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_up(animate=False)
        except Exception:
            pass

    def action_scroll_chat_down(self) -> None:
        """Scroll chat down by a small amount (Ctrl+Down)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_down(animate=False)
        except Exception:
            pass

    async def action_quit(self) -> None:
        """Clean up the Amplifier session before quitting.

        Cleanup must run in a @work(thread=True) worker because the session
        was created in a worker thread with its own asyncio event loop.
        Running async cleanup on Textual's main loop fails silently.
        """
        # Save any in-progress draft before exiting
        self._save_draft()

        if self.session_manager and getattr(self.session_manager, "session", None):
            self._update_status("Saving session...")
            try:
                worker = self._cleanup_session_worker()
                await worker.wait()
            except Exception:
                pass
        self.exit()

    @work(thread=True)
    async def _cleanup_session_worker(self) -> None:
        """End session in a worker thread with a proper async event loop."""
        await self.session_manager.end_session()

    def action_new_session(self) -> None:
        """Start a fresh session."""
        if self.is_processing:
            return
        # Save draft for current session before starting new one
        self._save_draft()
        # End the current session cleanly before starting a new one
        if self.session_manager and hasattr(self.session_manager, "end_session"):
            self._end_and_reset_session()
            return
        self._reset_for_new_session()

    @work(thread=True)
    async def _end_and_reset_session(self) -> None:
        """End current session in background, then reset UI."""
        try:
            await self.session_manager.end_session()
        except Exception:
            pass
        # Reset session manager state (but keep the manager)
        if self.session_manager:
            self.session_manager.session = None
            self.session_manager.session_id = None
        self.call_from_thread(self._reset_for_new_session)

    def _reset_for_new_session(self) -> None:
        """Reset UI for a new session."""
        if self.session_manager:
            self.session_manager.session = None
            self.session_manager.session_id = None
            self.session_manager.reset_usage()
        # Clear chat
        chat_view = self._active_chat_view()
        for child in list(chat_view.children):
            child.remove()
        self._show_welcome("New session will start when you send a message.")
        self._session_title = ""
        self.sub_title = ""
        self._update_session_display()
        self._update_token_display()
        self._update_status("Ready")
        self._total_words = 0
        self._user_message_count = 0
        self._assistant_message_count = 0
        self._tool_call_count = 0
        self._user_words = 0
        self._assistant_words = 0
        self._response_times = []
        self._tool_usage = {}
        self._assistant_msg_index = 0
        self._last_assistant_widget = None
        self._session_bookmarks = []
        self._session_refs = []
        self._message_pins = []
        self._search_messages = []
        self._session_start_time = time.monotonic()
        self._update_word_count_display()
        self.query_one("#chat-input", ChatInput).focus()

    def action_clear_chat(self) -> None:
        chat_view = self._active_chat_view()
        for child in list(chat_view.children):
            child.remove()
        self._total_words = 0
        self._user_message_count = 0
        self._assistant_message_count = 0
        self._tool_call_count = 0
        self._user_words = 0
        self._assistant_words = 0
        self._response_times = []
        self._tool_usage = {}
        self._search_messages = []
        self._update_word_count_display()

    def action_toggle_auto_scroll(self) -> None:
        """Toggle auto-scroll on/off (Ctrl+A)."""
        self._auto_scroll = not self._auto_scroll
        state = "ON" if self._auto_scroll else "OFF"
        self._update_scroll_indicator()
        self._add_system_message(f"Auto-scroll {state}")
        # If re-enabled, immediately scroll to bottom
        if self._auto_scroll:
            try:
                chat_view = self._active_chat_view()
                chat_view.scroll_end(animate=False)
            except Exception:
                pass

    def action_toggle_focus_mode(self) -> None:
        """Toggle focus mode: hide all chrome, show only chat + input."""
        self._set_focus_mode(not self._focus_mode)

    def _set_focus_mode(self, enabled: bool) -> None:
        """Apply focus mode state using a CSS class on the app."""
        if enabled == self._focus_mode:
            return

        if enabled:
            # Remember sidebar state so we can restore it on exit
            self._sidebar_was_visible_before_focus = self._sidebar_visible
            self._focus_mode = True
            self.add_class("focus-mode")
            self._add_system_message("Focus mode ON (F11 or /focus to exit)")
        else:
            self._focus_mode = False
            self.remove_class("focus-mode")
            # Restore sidebar to its pre-focus state
            if self._sidebar_was_visible_before_focus and not self._sidebar_visible:
                self.action_toggle_sidebar()
            self._add_system_message("Focus mode OFF")

        # Keep input focused
        try:
            self.query_one("#chat-input", ChatInput).focus()
        except Exception:
            pass

    def action_toggle_split_focus(self) -> None:
        """Switch focus between chat input, chat view, and split panel (Ctrl+T)."""
        if not self.has_class("split-mode"):
            return
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            split_panel = self.query_one("#split-panel", ScrollableContainer)
            chat_view = self._active_chat_view()
        except Exception:
            return

        focused = self.focused
        if focused is chat_input or (focused and focused.is_descendant_of(chat_input)):
            # Input -> split panel
            split_panel.focus()
        elif focused is split_panel or (
            focused and focused.is_descendant_of(split_panel)
        ):
            # Split panel -> chat view
            chat_view.focus()
        else:
            # Chat view (or anything else) -> input
            chat_input.focus()

    def _resolve_editor(self) -> str | None:
        """Return the first available editor ($VISUAL > $EDITOR > nano > vim > vi)."""
        for candidate in (
            os.environ.get("VISUAL"),
            os.environ.get("EDITOR"),
            "nano",
            "vim",
            "vi",
        ):
            if candidate and shutil.which(candidate):
                return candidate
        return None

    def action_open_editor(self) -> None:
        """Open $EDITOR for composing a longer prompt (Ctrl+G)."""
        editor = self._resolve_editor()
        if not editor:
            self._add_system_message(
                "No editor found. Set $EDITOR or install vim/nano."
            )
            return

        inp = self.query_one("#chat-input", ChatInput)
        current_text = inp.text

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            prefix="amplifier-prompt-",
            delete=False,
        ) as f:
            f.write(current_text)
            tmpfile = f.name

        try:
            with self.suspend():
                result = subprocess.run([editor, tmpfile])

            if result.returncode != 0:
                self._add_system_message(
                    f"Editor exited with code {result.returncode}."
                )
                return

            with open(tmpfile) as f:
                new_text = f.read().strip()

            if not new_text or new_text == current_text.strip():
                self._add_system_message("Editor closed with no changes — cancelled.")
                return

            inp.clear()
            inp.insert(new_text)
            inp.focus()

            # Auto-send if preference is enabled
            if self._prefs.display.editor_auto_send:
                self._submit_message()
        except Exception as e:
            self._add_system_message(f"Could not open editor: {e}")
        finally:
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    def action_stash_prompt(self) -> None:
        """Toggle stash: push current input or pop most recent stash."""
        inp = self.query_one("#chat-input", ChatInput)
        text = inp.text.strip()
        if text:
            # Push to stash
            self._stash_stack.append(text)
            if len(self._stash_stack) > self.MAX_STASHES:
                self._stash_stack.pop(0)  # drop oldest
            inp.clear()
            self._update_stash_indicator()
            self._add_system_message(
                f"Prompt stashed ({len(self._stash_stack)} in stack)"
            )
        elif self._stash_stack:
            # Pop from stash
            restored = self._stash_stack.pop()
            inp.clear()
            inp.insert(restored)
            self._update_stash_indicator()
            self._add_system_message("Prompt restored from stash")
        else:
            self._add_system_message("Nothing to stash or restore")

    def _update_stash_indicator(self) -> None:
        """Update the status bar stash indicator."""
        try:
            count = len(self._stash_stack)
            label = f"Stash: {count}" if count > 0 else ""
            self.query_one("#status-stash", Static).update(label)
        except Exception:
            pass

    def action_copy_response(self) -> None:
        """Copy the last assistant response to the system clipboard."""
        # Try _last_assistant_text first; fall back to _search_messages
        text = self._last_assistant_text
        if not text:
            for role, msg_text, _widget in reversed(self._search_messages):
                if role == "assistant":
                    text = msg_text
                    break
        if not text:
            self._add_system_message("No assistant messages to copy")
            return
        if _copy_to_clipboard(text):
            self._add_system_message(
                f"Copied last assistant message ({len(text)} chars)"
            )
        else:
            self._add_system_message(
                "Failed to copy — no clipboard tool available (install xclip or xsel)"
            )

    # ── Input Handling ──────────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle Enter in the chat input."""
        self._submit_message()

    def _submit_message(self) -> None:
        """Extract text from input and send it."""
        input_widget = self.query_one("#chat-input", ChatInput)
        text = input_widget.text.strip()
        if not text:
            return
        if self.is_processing:
            return

        # Re-enable auto-scroll when user sends a new message
        if not self._auto_scroll:
            self._auto_scroll = True
            self._update_scroll_indicator()

        # Record in history (add() skips slash commands internally)
        self._history.add(text)

        # Slash commands work even before Amplifier is ready
        if text.startswith("/"):
            input_widget.clear()
            self._clear_welcome()
            self._add_user_message(text)
            self._handle_slash_command(text)
            return

        if not self._amplifier_available:
            return
        if not self._amplifier_ready:
            self._update_status("Still loading Amplifier...")
            return

        input_widget.clear()
        self._clear_draft()
        self._clear_crash_draft()

        self._clear_welcome()
        self._add_user_message(text)
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(text)

    # ── Slash Commands ────────────────────────────────────────

    def _handle_slash_command(self, text: str, _alias_depth: int = 0) -> None:
        """Route a slash command to the appropriate handler."""
        if _alias_depth > 5:
            self._add_system_message("Alias recursion limit reached")
            return

        parts = text.strip().split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Check aliases BEFORE built-in commands
        alias_name = cmd.lstrip("/")
        if alias_name in self._aliases:
            expansion = self._aliases[alias_name]
            if expansion.startswith("/"):
                # Command alias – recurse
                full = expansion + (" " + args if args else "")
                self._handle_slash_command(full, _alias_depth + 1)
            else:
                # Prompt alias – send expanded text to Amplifier
                full = expansion + (" " + args if args else "")
                if not self._amplifier_available:
                    return
                if not self._amplifier_ready:
                    self._add_system_message("Still loading Amplifier...")
                    return
                has_session = self.session_manager and getattr(
                    self.session_manager, "session", None
                )
                self._start_processing(
                    "Starting session" if not has_session else "Thinking"
                )
                self._send_message_worker(full)
            return

        handlers = {
            "/help": self._cmd_help,
            "/clear": self._cmd_clear,
            "/new": self._cmd_new,
            "/sessions": self._cmd_sessions,
            "/preferences": self._cmd_prefs,
            "/prefs": self._cmd_prefs,
            "/model": lambda: self._cmd_model(text),
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
            "/focus": lambda: self._cmd_focus(text),
            "/compact": lambda: self._cmd_compact(text),
            "/copy": lambda: self._cmd_copy(text),
            "/notify": lambda: self._cmd_notify(text),
            "/sound": lambda: self._cmd_sound(text),
            "/scroll": self._cmd_scroll,
            "/timestamps": self._cmd_timestamps,
            "/keys": self._cmd_keys,
            "/stats": lambda: self._cmd_stats(args),
            "/tokens": self._cmd_tokens,
            "/context": self._cmd_context,
            "/info": self._cmd_info,
            "/theme": lambda: self._cmd_theme(text),
            "/export": lambda: self._cmd_export(text),
            "/rename": lambda: self._cmd_rename(text),
            "/delete": lambda: self._cmd_delete(text),
            "/bookmark": lambda: self._cmd_bookmark(text),
            "/bm": lambda: self._cmd_bookmark(text),
            "/bookmarks": lambda: self._cmd_bookmarks(text),
            "/search": lambda: self._cmd_search(text),
            "/colors": lambda: self._cmd_colors(text),
            "/pin": lambda: self._cmd_pin_msg(text),
            "/pins": lambda: self._cmd_pins(text),
            "/unpin": lambda: self._cmd_unpin(text),
            "/pin-session": lambda: self._cmd_pin_session(text),
            "/draft": lambda: self._cmd_draft(text),
            "/sort": lambda: self._cmd_sort(text),
            "/edit": self.action_open_editor,
            "/editor": self.action_open_editor,
            "/wrap": lambda: self._cmd_wrap(text),
            "/fold": lambda: self._cmd_fold(text),
            "/alias": lambda: self._cmd_alias(args),
            "/history": lambda: self._cmd_history(args),
            "/grep": lambda: self._cmd_grep(text),
            "/redo": lambda: self._cmd_redo(args),
            "/undo": lambda: self._cmd_undo(args),
            "/snippet": lambda: self._cmd_snippet(args),
            "/snippets": lambda: self._cmd_snippet(""),
            "/template": lambda: self._cmd_template(args),
            "/templates": lambda: self._cmd_template(""),
            "/title": lambda: self._cmd_title(args),
            "/diff": lambda: self._cmd_diff(args),
            "/ref": lambda: self._cmd_ref(text),
            "/refs": lambda: self._cmd_ref(text),
            "/vim": lambda: self._cmd_vim(args),
            "/watch": lambda: self._cmd_watch(args),
            "/split": lambda: self._cmd_split(args),
            "/stream": lambda: self._cmd_stream(args),
            "/tab": lambda: self._cmd_tab(args),
            "/tabs": lambda: self._cmd_tab(""),
        }

        handler = handlers.get(cmd)
        if handler:
            handler()
        else:
            self._add_system_message(
                f"Unknown command: {cmd}\nType /help for available commands."
            )

    def _cmd_help(self) -> None:
        help_text = (
            "Amplifier TUI Commands\n"
            "\n"
            "  /help         Show this help\n"
            "  /clear        Clear chat\n"
            "  /new          New session\n"
            "  /sessions     Toggle session sidebar\n"
            "  /prefs        Show preferences\n"
            "  /model        Show/switch model | /model list | /model <name>\n"
            "  /stats        Show session statistics | /stats tools | /stats tokens\n"
            "  /tokens       Detailed token / context usage breakdown\n"
            "  /context      Visual context window usage bar\n"
            "  /info         Show session details (ID, model, project, counts)\n"
            "  /copy         Copy last response | /copy N | /copy all | /copy code\n"
            "  /bookmark     Bookmark last response (/bm alias, optional label)\n"
            "  /bookmarks    List bookmarks | /bookmarks <N> to jump\n"
            "  /ref          Save a URL/reference (/ref <url> [label], /ref remove/clear/export)\n"
            "  /refs         List all saved references (same as /ref with no args)\n"
            "  /title        View/set session title (/title <text> or /title clear)\n"
            "  /rename       Rename current session (e.g. /rename My Project)\n"
            "  /pin          Pin last AI message | /pin <N> | /pin clear\n"
            "  /pins         List all pinned messages\n"
            "  /unpin <N>    Remove a pin by its pin number\n"
            "  /pin-session  Pin/unpin session (pinned appear at top of sidebar)\n"
            "  /delete       Delete session (with confirmation)\n"
            "  /export       Export chat (md/txt/json) | /export <file> | /export <fmt>\n"
            "  /notify       Toggle notifications (/notify on|off|sound|silent|<secs>)\n"
            "  /sound        Toggle notification sound (/sound on|off|test)\n"
            "  /scroll       Toggle auto-scroll on/off\n"
            "  /timestamps   Toggle message timestamps on/off\n"
            "  /wrap         Toggle word wrap on/off (/wrap on, /wrap off)\n"
            "  /fold         Fold/unfold long messages (/fold all, /fold none, /fold <n>)\n"
            "  /theme        Switch color theme (dark, light, solarized, monokai, nord, dracula)\n"
            "  /colors       View/set colors (/colors <role> <#hex>, /colors reset)\n"
            "  /focus        Toggle focus mode (/focus on, /focus off)\n"
            "  /search       Search chat messages (e.g. /search my query)\n"
            "  /grep         Search with options (/grep <pattern>, /grep -c <pattern> for case-sensitive)\n"
            "  /diff         Show git diff (/diff staged|all|last|<file>|<f1> <f2>|HEAD~N)\n"
            "  /watch        Watch files for changes (/watch <path>, stop, diff)\n"
            "  /sort         Sort sessions: date, name, project (/sort <mode>)\n"
            "  /edit         Open $EDITOR for longer prompts (same as Ctrl+G)\n"
            "  /editor       Alias for /edit\n"
            "  /draft        Show/save/clear/load input draft (/draft save, /draft clear, /draft load)\n"
            "  /snippet      Prompt snippets (/snippet save|use|remove|search|cat|tag|export|import|<name>)\n"
            "  /template     Prompt templates with {{variables}} (/template save|use|remove|clear|<name>)\n"
            "  /alias        List/create/remove custom shortcuts\n"
            "  /compact      Toggle compact view mode (/compact on, /compact off)\n"
            "  /history      Browse input history (/history clear, /history <N>)\n"
            "  /undo         Remove last exchange (/undo <N> for last N exchanges)\n"
            "  /redo         Re-send last user message (/redo <N> for Nth-to-last)\n"
            "  /split        Toggle split view (/split pins|chat|file <path>|on|off)\n"
            "  /stream       Toggle streaming display (/stream on, /stream off)\n"
            "  /vim          Toggle vim keybindings (/vim on, /vim off)\n"
            "  /tab          Tab management (/tab new|switch|close|rename|list)\n"
            "  /tabs         List all open tabs\n"
            "  /keys         Keyboard shortcut overlay\n"
            "  /quit         Quit\n"
            "\n"
            "Key Bindings  (press F1 for full overlay)\n"
            "\n"
            "  Enter         Send message\n"
            "  Shift+Enter   Insert newline (multi-line input)\n"
            "  Ctrl+J        Insert newline (alt)\n"
            "  Up/Down       Browse prompt history\n"
            "  F1            Keyboard shortcuts overlay\n"
            "  F11           Toggle focus mode (hide chrome)\n"
            "  Ctrl+A        Toggle auto-scroll\n"
            "  Ctrl+F        Search chat messages\n"
            "  Ctrl+R        Reverse search prompt history\n"
            "  Ctrl+G        Open $EDITOR for longer prompts\n"
            "  Ctrl+Y        Copy last response to clipboard\n"
            "  Ctrl+M        Bookmark last response\n"
            "  Ctrl+S        Stash/restore prompt (stack of 5)\n"
            "  Ctrl+B        Toggle sidebar\n"
            "  Ctrl+N        New session\n"
            "  Ctrl+L        Clear chat\n"
            "  Escape        Cancel streaming generation\n"
            "  Ctrl+T        New conversation tab\n"
            "  Ctrl+W        Close current tab\n"
            "  Ctrl+PgUp/Dn  Switch between tabs\n"
            "  Ctrl+Home     Jump to top of chat\n"
            "  Ctrl+End      Jump to bottom of chat\n"
            "  Ctrl+Up/Down  Scroll chat up/down\n"
            "  Home/End      Top/bottom of chat (when input empty)\n"
            "  Ctrl+Q        Quit"
        )
        self._add_system_message(help_text)

    def _cmd_alias(self, text: str) -> None:
        """List, create, or remove custom command aliases."""
        text = text.strip()

        if not text:
            # List all aliases
            if not self._aliases:
                self._add_system_message(
                    "No aliases defined.\n"
                    "Usage: /alias <name> <command>\n"
                    "Example: /alias r /clear\n"
                    "         /alias review /diff all"
                )
                return
            lines = ["Aliases:"]
            for name, expansion in sorted(self._aliases.items()):
                lines.append(f"  /{name} \u2192 {expansion}")
            lines.append("")
            lines.append("Use /alias remove <name> to delete")
            self._add_system_message("\n".join(lines))
            return

        # Clear all aliases
        if text == "clear":
            self._aliases.clear()
            self._save_aliases()
            self._add_system_message("All aliases cleared")
            return

        # Remove alias
        if text.startswith("remove "):
            name = text[7:].strip().lstrip("/")
            if name in self._aliases:
                del self._aliases[name]
                self._save_aliases()
                self._add_system_message(f"Alias /{name} removed")
            else:
                self._add_system_message(f"No alias '/{name}' found")
            return

        # Create/update alias: supports both "name = expansion" and "name expansion"
        if "=" in text:
            name, expansion = text.split("=", 1)
            name = name.strip().lstrip("/")
            expansion = expansion.strip()
        else:
            parts = text.split(None, 1)
            if len(parts) < 2:
                self._add_system_message(
                    "Usage: /alias <name> <command>\n"
                    "Example: /alias r /clear\n"
                    "         /alias review /diff all\n"
                    "         /alias remove <name>\n"
                    "         /alias clear"
                )
                return
            name = parts[0].lstrip("/")
            expansion = parts[1]

        if not name or not expansion:
            self._add_system_message(
                "Both name and command required: /alias <name> <command>"
            )
            return

        # Don't allow overriding built-in commands
        if "/" + name in SLASH_COMMANDS:
            self._add_system_message(f"Cannot override built-in command /{name}")
            return

        # Ensure command aliases start with /
        if not expansion.startswith("/"):
            expansion = f"/{expansion}"

        self._aliases[name] = expansion
        self._save_aliases()
        self._add_system_message(f"Alias created: /{name} \u2192 {expansion}")

    # -- Snippet helpers ------------------------------------------------

    @staticmethod
    def _snippet_content(data: dict[str, str] | str) -> str:
        """Return the text content regardless of old/new format."""
        if isinstance(data, dict):
            return data.get("content", "")
        return data  # legacy plain-string value

    @staticmethod
    def _snippet_category(data: dict[str, str] | str) -> str:
        """Return the category (empty string for uncategorised)."""
        if isinstance(data, dict):
            return data.get("category", "")
        return ""

    # -- /snippet command -----------------------------------------------

    def _cmd_snippet(self, text: str) -> None:
        """List, save, search, tag, export, import, use, remove, clear, or edit snippets."""
        text = text.strip()

        # ── No arguments → list all snippets grouped by category ──
        if not text:
            if not self._snippets:
                self._add_system_message(
                    "No snippets saved.\n"
                    "Save: /snippet save <name> [#category] <text>\n"
                    "Use:  /snippet <name>"
                )
                return
            categorized: dict[str, list[str]] = defaultdict(list)
            uncategorized: list[str] = []
            for name, data in sorted(self._snippets.items()):
                cat = self._snippet_category(data)
                if cat:
                    categorized[cat].append(name)
                else:
                    uncategorized.append(name)
            lines: list[str] = ["Saved snippets:"]
            for cat in sorted(categorized):
                lines.append(f"\n  [{cat}]")
                for name in categorized[cat]:
                    content = self._snippet_content(self._snippets[name])
                    preview = content[:60].replace("\n", " ")
                    if len(content) > 60:
                        preview += "..."
                    lines.append(f"    {name}: {preview}")
            if uncategorized:
                if categorized:
                    lines.append("\n  [uncategorised]")
                for name in uncategorized:
                    content = self._snippet_content(self._snippets[name])
                    preview = content[:60].replace("\n", " ")
                    if len(content) > 60:
                        preview += "..."
                    lines.append(f"    {name}: {preview}")
            lines.append("")
            lines.append("Insert: /snippet <name>  |  Send: /snippet use <name>")
            self._add_system_message("\n".join(lines))
            return

        # ── Parse subcommand ──
        parts = text.split(maxsplit=2)
        subcmd = parts[0].lower()

        if subcmd == "clear":
            self._snippets.clear()
            self._save_snippets()
            self._add_system_message("All snippets cleared")

        elif subcmd == "save":
            self._cmd_snippet_save(parts)

        elif subcmd in ("use", "send"):
            self._cmd_snippet_use(parts)

        elif subcmd == "remove":
            if len(parts) < 2:
                self._add_system_message("Usage: /snippet remove <name>")
                return
            sname = parts[1]
            if sname in self._snippets:
                del self._snippets[sname]
                self._save_snippets()
                self._add_system_message(f"Snippet '{sname}' removed")
            else:
                self._add_system_message(f"No snippet named '{sname}'")

        elif subcmd == "edit":
            if len(parts) < 2:
                self._add_system_message("Usage: /snippet edit <name>")
                return
            sname = parts[1]
            content = (
                self._snippet_content(self._snippets[sname])
                if sname in self._snippets
                else ""
            )
            self._edit_snippet_in_editor(sname, content)

        elif subcmd == "search":
            query = text[len("search") :].strip()
            if not query:
                self._add_system_message("Usage: /snippet search <query>")
                return
            self._cmd_snippet_search(query)

        elif subcmd == "cat":
            category = text[len("cat") :].strip()
            if not category:
                self._add_system_message("Usage: /snippet cat <category>")
                return
            self._cmd_snippet_cat(category)

        elif subcmd == "tag":
            self._cmd_snippet_tag(parts)

        elif subcmd == "export":
            self._cmd_snippet_export()

        elif subcmd == "import":
            path = text[len("import") :].strip()
            if not path:
                self._add_system_message("Usage: /snippet import <path>")
                return
            self._cmd_snippet_import(path)

        else:
            # Default: insert snippet into input (doesn't send)
            if subcmd in self._snippets:
                try:
                    inp = self.query_one("#chat-input", ChatInput)
                    inp.clear()
                    inp.insert(self._snippet_content(self._snippets[subcmd]))
                    inp.focus()
                    self._add_system_message(f"Snippet '{subcmd}' inserted")
                except Exception:
                    pass
            else:
                self._add_system_message(
                    f"No snippet '{subcmd}'.\n"
                    "Use /snippet to list, /snippet save <name> <text> to create."
                )

    # -- /snippet sub-command implementations ---------------------------

    def _cmd_snippet_save(self, parts: list[str]) -> None:
        """Save a snippet with an optional ``#category`` tag."""
        if len(parts) < 3:
            self._add_system_message("Usage: /snippet save <name> [#category] <text>")
            return
        sname = parts[1]
        if not re.match(r"^[a-zA-Z0-9_-]+$", sname):
            self._add_system_message(
                "Snippet names must be alphanumeric (hyphens and underscores allowed)"
            )
            return
        remaining = parts[2]
        # Parse optional #category prefix
        category = ""
        cat_match = re.match(r"#(\w+)\s+", remaining)
        if cat_match:
            category = cat_match.group(1)
            remaining = remaining[cat_match.end() :]
        today = datetime.now().strftime("%Y-%m-%d")
        self._snippets[sname] = {
            "content": remaining,
            "category": category,
            "created": today,
        }
        self._save_snippets()
        cat_note = f" [{category}]" if category else ""
        self._add_system_message(
            f"Snippet '{sname}'{cat_note} saved ({len(remaining)} chars)"
        )

    def _cmd_snippet_use(self, parts: list[str]) -> None:
        """Send a snippet as a chat message immediately."""
        if len(parts) < 2:
            self._add_system_message("Usage: /snippet use <name>")
            return
        sname = parts[1]
        if sname not in self._snippets:
            self._add_system_message(f"No snippet named '{sname}'")
            return
        if self.is_processing:
            self._add_system_message("Please wait for the current response to finish.")
            return
        if not self._amplifier_available:
            self._add_system_message("Amplifier is not available.")
            return
        if not self._amplifier_ready:
            self._add_system_message("Still loading Amplifier...")
            return
        message = self._snippet_content(self._snippets[sname])
        self._add_system_message(f"Sending snippet '{sname}'")
        self._clear_welcome()
        self._add_user_message(message)
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(message)

    def _cmd_snippet_search(self, query: str) -> None:
        """Fuzzy search across snippet names, content, and categories."""
        query_lower = query.lower()
        matches: list[tuple[str, str, str]] = []
        for name, data in self._snippets.items():
            content = self._snippet_content(data)
            category = self._snippet_category(data)
            if (
                query_lower in name.lower()
                or query_lower in content.lower()
                or query_lower in category.lower()
            ):
                matches.append((name, content, category))

        if not matches:
            self._add_system_message(f"No snippets matching: {query}")
            return

        lines = [f"Snippets matching '{query}':"]
        for name, content, cat in sorted(matches):
            cat_str = f" [{cat}]" if cat else ""
            preview = content[:60].replace("\n", " ")
            if len(content) > 60:
                preview += "..."
            lines.append(f"  {name}{cat_str}: {preview}")
        lines.append(f"\n{len(matches)} match(es)")
        self._add_system_message("\n".join(lines))

    def _cmd_snippet_cat(self, category: str) -> None:
        """List all snippets belonging to *category*."""
        matches: list[tuple[str, str]] = []
        for name, data in self._snippets.items():
            cat = self._snippet_category(data)
            if cat.lower() == category.lower():
                matches.append((name, self._snippet_content(data)))

        if not matches:
            self._add_system_message(f"No snippets in category: {category}")
            return

        lines = [f"Category '{category}':"]
        for name, content in sorted(matches):
            preview = content[:60].replace("\n", " ")
            if len(content) > 60:
                preview += "..."
            lines.append(f"  {name}: {preview}")
        lines.append(f"\n{len(matches)} snippet(s)")
        self._add_system_message("\n".join(lines))

    def _cmd_snippet_tag(self, parts: list[str]) -> None:
        """Add or change the category tag on an existing snippet."""
        if len(parts) < 3:
            self._add_system_message("Usage: /snippet tag <name> <category>")
            return
        sname = parts[1]
        category = parts[2]
        if sname not in self._snippets:
            self._add_system_message(f"No snippet named '{sname}'")
            return
        data = self._snippets[sname]
        if isinstance(data, str):
            # Shouldn't happen after migration, but be safe
            data = {
                "content": data,
                "category": "",
                "created": datetime.now().strftime("%Y-%m-%d"),
            }
        data["category"] = category
        self._snippets[sname] = data
        self._save_snippets()
        self._add_system_message(f"Snippet '{sname}' tagged [{category}]")

    def _cmd_snippet_export(self) -> None:
        """Export all snippets as JSON to ``~/.amplifier/tui-snippets-export.json``."""
        if not self._snippets:
            self._add_system_message("No snippets to export")
            return
        export_path = Path.home() / ".amplifier" / "tui-snippets-export.json"
        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text(json.dumps(self._snippets, indent=2, sort_keys=True))
            self._add_system_message(
                f"Exported {len(self._snippets)} snippets to:\n{export_path}"
            )
        except Exception as e:
            self._add_system_message(f"Export error: {e}")

    def _cmd_snippet_import(self, path: str) -> None:
        """Import snippets from a JSON file (additive — existing names are kept)."""
        abs_path = Path(path).expanduser().resolve()
        if not abs_path.exists():
            self._add_system_message(f"File not found: {path}")
            return
        try:
            raw = json.loads(abs_path.read_text())
            data = self._migrate_snippets(raw) if isinstance(raw, dict) else {}
            count = 0
            for name, value in data.items():
                if name not in self._snippets:
                    self._snippets[name] = value
                    count += 1
            self._save_snippets()
            skipped = len(data) - count
            self._add_system_message(
                f"Imported {count} new snippet(s)"
                + (f" ({skipped} already existed)" if skipped else "")
            )
        except Exception as e:
            self._add_system_message(f"Import error: {e}")

    # -- Snippet editor -------------------------------------------------

    def _edit_snippet_in_editor(self, name: str, content: str) -> None:
        """Edit a snippet in $EDITOR, reusing the Ctrl+G infrastructure."""
        editor = self._resolve_editor()
        if not editor:
            self._add_system_message(
                "No editor found. Set $EDITOR or install vim/nano."
            )
            return

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            prefix=f"snippet-{name}-",
            delete=False,
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            with self.suspend():
                result = subprocess.run([editor, tmpfile])

            if result.returncode != 0:
                self._add_system_message(
                    f"Editor exited with code {result.returncode}."
                )
                return

            with open(tmpfile) as f:
                new_content = f.read().strip()

            if not new_content:
                self._add_system_message(f"Snippet '{name}' unchanged (empty content)")
                return

            # Preserve existing metadata when editing
            existing = self._snippets.get(name, {})
            if isinstance(existing, dict):
                existing["content"] = new_content
                self._snippets[name] = existing
            else:
                self._snippets[name] = {
                    "content": new_content,
                    "category": "",
                    "created": datetime.now().strftime("%Y-%m-%d"),
                }
            self._save_snippets()
            self._add_system_message(
                f"Snippet '{name}' updated ({len(new_content)} chars)"
            )
        except Exception as e:
            self._add_system_message(f"Could not open editor: {e}")
        finally:
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    def _cmd_template(self, text: str) -> None:
        """List, save, use, remove, or clear prompt templates with {{variable}} placeholders."""
        text = text.strip()

        if not text:
            # List all templates
            if not self._templates:
                self._add_system_message(
                    "No templates saved.\n"
                    "Save: /template save <name> <text with {{vars}}>\n"
                    "Use:  /template <name>"
                )
                return
            lines = ["Saved templates:"]
            for name, tmpl in sorted(self._templates.items()):
                variables = re.findall(r"\{\{(\w+)\}\}", tmpl)
                vars_str = (
                    ", ".join(dict.fromkeys(variables)) if variables else "no variables"
                )
                preview = tmpl[:60].replace("\n", " ")
                if len(tmpl) > 60:
                    preview += "..."
                lines.append(f"  {name:15s} ({vars_str})")
                lines.append(f"                  {preview}")
            lines.append("")
            lines.append(f"{len(self._templates)} template(s)")
            lines.append("Insert: /template <name>  |  Use: /template use <name>")
            self._add_system_message("\n".join(lines))
            return

        parts = text.split(maxsplit=2)
        subcmd = parts[0].lower()

        if subcmd == "clear":
            self._templates.clear()
            self._save_templates()
            self._add_system_message("All templates cleared")

        elif subcmd == "save":
            if len(parts) < 3:
                self._add_system_message(
                    "Usage: /template save <name> <text with {{vars}}>"
                )
                return
            tname = parts[1]
            if not re.match(r"^[a-zA-Z0-9_-]+$", tname):
                self._add_system_message(
                    "Template names must be alphanumeric "
                    "(hyphens and underscores allowed)"
                )
                return
            content = parts[2]
            self._templates[tname] = content
            self._save_templates()
            variables = re.findall(r"\{\{(\w+)\}\}", content)
            unique_vars = list(dict.fromkeys(variables))
            self._add_system_message(
                f"Template '{tname}' saved ({len(content)} chars)"
                + (f" — variables: {', '.join(unique_vars)}" if unique_vars else "")
            )

        elif subcmd == "use":
            # Insert template into input (doesn't send)
            if len(parts) < 2:
                self._add_system_message("Usage: /template use <name>")
                return
            tname = parts[1]
            if tname not in self._templates:
                self._add_system_message(f"No template named '{tname}'")
                return
            tmpl = self._templates[tname]
            variables = re.findall(r"\{\{(\w+)\}\}", tmpl)
            unique_vars = list(dict.fromkeys(variables))
            try:
                inp = self.query_one("#chat-input", ChatInput)
                inp.clear()
                inp.insert(tmpl)
                inp.focus()
            except Exception:
                pass
            if unique_vars:
                self._add_system_message(
                    f"Template '{tname}' inserted. "
                    f"Fill in placeholders: {', '.join(unique_vars)}"
                )
            else:
                self._add_system_message(f"Template '{tname}' inserted")

        elif subcmd == "remove":
            if len(parts) < 2:
                self._add_system_message("Usage: /template remove <name>")
                return
            tname = parts[1]
            if tname in self._templates:
                del self._templates[tname]
                self._save_templates()
                self._add_system_message(f"Template '{tname}' removed")
            else:
                self._add_system_message(f"No template named '{tname}'")

        else:
            # Default: treat subcmd as a template name (shortcut for /template use <name>)
            if subcmd in self._templates:
                self._cmd_template(f"use {subcmd}")
            else:
                self._add_system_message(
                    f"No template '{subcmd}'.\n"
                    "Usage:\n"
                    "  /template              List templates\n"
                    "  /template save <name> <text>  Save template with {{vars}}\n"
                    "  /template use <name>   Insert template into input\n"
                    "  /template remove <name>  Remove template\n"
                    "  /template clear        Remove all\n"
                    "  /template <name>       Quick insert"
                )

    def _cmd_draft(self, text: str) -> None:
        """Show, save, clear, or load the input draft."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "clear":
            self._clear_draft()
            self._clear_crash_draft()
            self._add_system_message("Draft cleared")
            return

        if arg == "save":
            self._save_draft()
            self._save_crash_draft()
            self._add_system_message("Draft saved")
            return

        if arg == "load":
            draft = self._load_crash_draft()
            if draft:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.clear()
                input_widget.insert(draft)
                self._add_system_message(f"Draft loaded ({len(draft)} chars)")
            else:
                self._add_system_message("No saved draft")
            return

        # Show current draft status
        lines: list[str] = []
        session_id = self._get_session_id()
        drafts = self._load_drafts()
        if session_id and session_id in drafts:
            draft = drafts[session_id]
            preview = draft[:80].replace("\n", " ")
            suffix = "..." if len(draft) > 80 else ""
            lines.append(f"Session draft ({len(draft)} chars): {preview}{suffix}")

        crash = self._load_crash_draft()
        if crash:
            preview = crash[:80].replace("\n", " ")
            suffix = "..." if len(crash) > 80 else ""
            lines.append(
                f"Crash-recovery draft ({len(crash)} chars): {preview}{suffix}"
            )

        if not lines:
            # Check if there's unsaved input
            try:
                input_text = self.query_one("#chat-input", ChatInput).text.strip()
            except Exception:
                input_text = ""
            if input_text:
                lines.append(
                    f"Unsaved input: {len(input_text)} chars (auto-saves in 5s)"
                )
            else:
                lines.append("No draft or unsaved input")

        self._add_system_message("\n".join(lines))

    def _cmd_tab(self, args: str) -> None:
        """Handle /tab subcommands."""
        args = args.strip()
        if not args:
            # List tabs (same as /tabs)
            lines = ["Tabs:"]
            for i, tab in enumerate(self._tabs):
                marker = " ▶" if i == self._active_tab_index else "  "
                sid = ""
                if tab.sm_session_id or (
                    i == self._active_tab_index
                    and self.session_manager
                    and getattr(self.session_manager, "session_id", None)
                ):
                    s = (
                        tab.sm_session_id
                        if i != self._active_tab_index
                        else getattr(self.session_manager, "session_id", "")
                    )
                    if s:
                        sid = f" [{s[:8]}]"
                lines.append(f"{marker} {i + 1}. {tab.name}{sid}")
            lines.append("")
            lines.append(
                "Usage: /tab new [name] | switch <n> | close [n] | rename <name>"
            )
            self._add_system_message("\n".join(lines))
            return

        parts = args.split(None, 1)
        subcmd = parts[0].lower()
        subargs = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "new":
            self._create_new_tab(subargs or None)
        elif subcmd == "switch":
            if not subargs:
                self._add_system_message("Usage: /tab switch <name|number>")
                return
            idx = self._find_tab_by_name_or_index(subargs)
            if idx is None:
                self._add_system_message(f"Tab not found: {subargs}")
                return
            self._switch_to_tab(idx)
        elif subcmd == "close":
            if not subargs:
                self._close_tab()
            else:
                idx = self._find_tab_by_name_or_index(subargs)
                if idx is None:
                    self._add_system_message(f"Tab not found: {subargs}")
                    return
                self._close_tab(idx)
        elif subcmd == "rename":
            if not subargs:
                self._add_system_message("Usage: /tab rename <new-name>")
                return
            self._rename_tab(subargs)
            self._add_system_message(f"Tab renamed to: {subargs}")
        elif subcmd == "list":
            # Recurse with empty args to show list
            self._cmd_tab("")
        else:
            # Maybe a number or name for quick switch
            idx = self._find_tab_by_name_or_index(subcmd)
            if idx is not None:
                self._switch_to_tab(idx)
            else:
                self._add_system_message(
                    "Unknown /tab subcommand. "
                    "Usage: /tab new [name] | switch <n> | close [n] | rename <name>"
                )

    def _cmd_clear(self) -> None:
        self.action_clear_chat()
        # No system message needed - the chat is cleared

    def _cmd_new(self) -> None:
        self.action_new_session()
        # new session shows its own welcome message

    def _cmd_sessions(self) -> None:
        self.action_toggle_sidebar()
        state = "opened" if self._sidebar_visible else "closed"
        self._add_system_message(f"Session sidebar {state}.")

    def _cmd_prefs(self) -> None:
        from .preferences import PREFS_PATH

        c = self._prefs.colors
        lines = [
            "Color Preferences\n",
            f"  user_text:            {c.user_text}",
            f"  user_border:          {c.user_border}",
            f"  assistant_text:       {c.assistant_text}",
            f"  assistant_border:     {c.assistant_border}",
            f"  thinking_text:        {c.thinking_text}",
            f"  thinking_border:      {c.thinking_border}",
            f"  thinking_background:  {c.thinking_background}",
            f"  tool_text:            {c.tool_text}",
            f"  tool_border:          {c.tool_border}",
            f"  tool_background:      {c.tool_background}",
            f"  system_text:          {c.system_text}",
            f"  system_border:        {c.system_border}",
            f"  status_bar:           {c.status_bar}",
            f"\nPreferences file: {PREFS_PATH}",
        ]
        self._add_system_message("\n".join(lines))

    def _cmd_model(self, text: str) -> None:
        """Show model info, list available models, or switch models.

        /model          Show current model and available models
        /model list     Show available models
        /model <name>   Switch to a different model
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg == "list":
            self._cmd_model_list()
            return

        if arg:
            self._cmd_model_set(arg)
            return

        # No argument — show current model info + available models
        self._cmd_model_show()

    def _cmd_model_show(self) -> None:
        """Display current model, token usage, and available models."""
        sm = self.session_manager
        lines = ["Model Info\n"]

        current = sm.model_name if sm else ""
        preferred = self._prefs.preferred_model

        if current:
            lines.append(f"  Active:     {current}")
        else:
            lines.append("  Active:     (no session)")

        if preferred and preferred != current:
            lines.append(f"  Preferred:  {preferred}")

        if sm:
            total_in = getattr(sm, "total_input_tokens", 0)
            total_out = getattr(sm, "total_output_tokens", 0)
            ctx = getattr(sm, "context_window", 0)

            if total_in or total_out:
                lines.append(
                    f"  Input:      {self._format_token_count(total_in)} tokens"
                )
                lines.append(
                    f"  Output:     {self._format_token_count(total_out)} tokens"
                )
                lines.append(
                    f"  Total:      {self._format_token_count(total_in + total_out)} tokens"
                )
            else:
                lines.append("  Tokens:     (no usage yet)")

            if ctx > 0:
                pct = int((total_in + total_out) / ctx * 100) if ctx else 0
                lines.append(
                    f"  Context:    {self._format_token_count(ctx)} window ({pct}% used)"
                )

            sid = getattr(sm, "session_id", None)
            if sid:
                lines.append(f"  Session:    {sid[:12]}...")

        # Append available models for quick reference
        available = self._get_available_models()
        if available:
            lines.append("")
            lines.append("Available models:")
            for model, provider in available:
                marker = " *" if model == current else "  "
                lines.append(f"  {marker} {provider:10s}  {model}")
            lines.append("")
            lines.append("Switch: /model <name>")

        self._add_system_message("\n".join(lines))

    # Well-known models used as a fallback when no session is active.
    _KNOWN_MODELS: list[tuple[str, str]] = [
        ("claude-sonnet-4-20250514", "Anthropic"),
        ("claude-haiku-35-20241022", "Anthropic"),
        ("gpt-4o", "OpenAI"),
        ("gpt-4o-mini", "OpenAI"),
        ("o3", "OpenAI"),
        ("o3-mini", "OpenAI"),
    ]

    def _get_available_models(self) -> list[tuple[str, str]]:
        """Return ``(model_name, provider)`` pairs.

        Tries the live session's providers first, falls back to
        ``_KNOWN_MODELS``.
        """
        sm = self.session_manager
        if sm and sm.session:
            dynamic = sm.get_provider_models()
            if dynamic:
                return dynamic
        return list(self._KNOWN_MODELS)

    def _cmd_model_list(self) -> None:
        """Show available models the user can select."""
        models = self._get_available_models()
        current = self.session_manager.model_name if self.session_manager else ""

        lines = ["Available Models\n"]
        for name, provider in models:
            marker = ""
            if name == current:
                marker = "  (active)"
            lines.append(f"  {provider:10s}  {name}{marker}")

        lines.append("")
        lines.append("Switch: /model <name>")
        has_session = bool(self.session_manager and self.session_manager.session)
        if has_session:
            lines.append("Takes effect immediately on the current session.")
        else:
            lines.append("Takes effect when the next session starts.")
        self._add_system_message("\n".join(lines))

    def _cmd_model_set(self, name: str) -> None:
        """Switch the active model and save as preferred default."""
        # Persist preference for future sessions
        self._prefs.preferred_model = name
        save_preferred_model(name)

        # Try to switch the live session's provider immediately
        sm = self.session_manager
        switched = sm.switch_model(name) if sm and sm.session else False

        self._update_token_display()
        self._update_breadcrumb()

        if switched:
            self._add_system_message(
                f"Model switched to: {name}\nNext AI response will use this model."
            )
        else:
            self._add_system_message(
                f"Preferred model set to: {name}\n"
                "Will take effect on the next session start."
            )

    def _cmd_quit(self) -> None:
        # Use call_later so the current handler finishes before quit runs
        self.call_later(self.action_quit)

    def _cmd_compact(self, text: str) -> None:
        """Toggle compact view mode on/off for denser chat display."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg in ("on", "true", "1"):
            compact = True
        elif arg in ("off", "false", "0"):
            compact = False
        elif not arg:
            compact = not self._prefs.display.compact_mode
        else:
            self._add_system_message("Usage: /compact [on|off]")
            return

        self._prefs.display.compact_mode = compact
        save_compact_mode(compact)

        # Toggle CSS class on the app for cascading style changes
        if compact:
            self.add_class("compact-mode")
            # Collapse tool and thinking blocks for maximum density
            for widget in self.query(".tool-use, .thinking-block"):
                if hasattr(widget, "collapsed"):
                    widget.collapsed = True
        else:
            self.remove_class("compact-mode")

        state = "ON" if compact else "OFF"
        self._update_status()
        self._add_system_message(f"Compact mode: {state}")

    def _cmd_vim(self, text: str) -> None:
        """Toggle vim-style keybindings in the input area."""
        text = text.strip().lower()

        if text in ("on", "true", "1"):
            vim = True
        elif text in ("off", "false", "0"):
            vim = False
        elif not text:
            vim = not self._prefs.display.vim_mode
        else:
            self._add_system_message("Usage: /vim [on|off]")
            return

        self._prefs.display.vim_mode = vim
        save_vim_mode(vim)

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget._vim_enabled = vim

        if vim:
            input_widget._vim_state = "normal"
            input_widget._vim_key_buffer = ""
            input_widget._update_vim_border()
            self._add_system_message(
                "Vim mode enabled (NORMAL mode — press i for INSERT)"
            )
        else:
            input_widget._vim_state = "insert"
            input_widget._vim_key_buffer = ""
            input_widget.border_title = ""
            self._add_system_message("Vim mode disabled")

        self._update_vim_status()

    # ── /split – side-by-side reference panel ────────────────────────────

    def _cmd_split(self, text: str) -> None:
        """Toggle or configure split view with a reference panel.

        /split          Toggle split view on/off
        /split on       Open split (default: pins)
        /split off      Close split
        /split pins     Show pinned messages in right panel
        /split chat     Mirror of chat at independent scroll position
        /split file <p> Show file content in right panel
        """
        raw = text.strip() if text else ""
        lower = raw.lower()

        if lower == "off":
            self._close_split()
            return

        if lower == "on" or not lower:
            if self.has_class("split-mode"):
                self._close_split()
            else:
                self._open_split_pins()
            return

        if lower == "pins":
            self._open_split_pins()
            return

        if lower == "chat":
            self._open_split_chat()
            return

        # /split file <path> – preserve original case for the path
        if lower.startswith("file ") or lower.startswith("file\t"):
            path = raw[5:].strip()
            if not path:
                self._add_system_message("Usage: /split file <path>")
                return
            self._open_split_file(path)
            return

        self._add_system_message(
            "Usage: /split [on|off|pins|chat|file <path>]\n"
            "  /split          Toggle split view on/off\n"
            "  /split pins     Pinned messages in right panel\n"
            "  /split chat     Chat mirror (independent scroll)\n"
            "  /split file <p> File content in right panel\n"
            "  Tab             Switch focus between panels"
        )

    def _open_split_pins(self) -> None:
        """Open split panel showing pinned messages."""
        panel = self.query_one("#split-panel", ScrollableContainer)
        panel.remove_children()

        panel.mount(Static("\U0001f4cc Pinned Messages", classes="split-panel-title"))

        if not self._message_pins:
            panel.mount(
                Static(
                    "No pinned messages.\nUse /pin to pin messages.",
                    classes="split-panel-hint",
                )
            )
        else:
            total = len(self._search_messages)
            for i, pin in enumerate(self._message_pins, 1):
                idx = pin["index"]
                if idx < total:
                    role, content, _widget = self._search_messages[idx]
                else:
                    role = "?"
                    content = pin.get("preview", "(unavailable)")
                label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                    role, role
                )
                # Truncate very long content for display
                display = content[:500]
                if len(content) > 500:
                    display += "\n..."
                panel.mount(
                    Static(
                        f"[bold]#{i} ({label} msg {idx + 1}):[/bold]\n{display}",
                        classes="split-panel-content",
                    )
                )

        panel.mount(
            Static(
                "Tab to switch focus • /split off to close",
                classes="split-panel-hint",
            )
        )

        self.add_class("split-mode")
        self._add_system_message("Split view: pinned messages (Tab to switch panels)")

    def _open_split_chat(self) -> None:
        """Open split panel with a copy of current chat messages."""
        panel = self.query_one("#split-panel", ScrollableContainer)
        panel.remove_children()

        panel.mount(Static("\U0001f4ac Chat Reference", classes="split-panel-title"))

        if not self._search_messages:
            panel.mount(Static("No messages yet.", classes="split-panel-hint"))
        else:
            for role, content, _widget in self._search_messages:
                label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                    role, role
                )
                # Truncate very long messages
                display = content[:800]
                if len(content) > 800:
                    display += "\n..."
                panel.mount(
                    Static(
                        f"[bold]{label}:[/bold] {display}",
                        classes="split-panel-content",
                    )
                )

        panel.mount(
            Static(
                "Tab to switch focus • /split off to close",
                classes="split-panel-hint",
            )
        )

        self.add_class("split-mode")
        self._add_system_message("Split view: chat reference (Tab to switch panels)")

    def _open_split_file(self, path: str) -> None:
        """Open split panel showing file content."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(abs_path):
            self._add_system_message(f"File not found: {path}")
            return

        try:
            with open(abs_path) as f:
                content = f.read()
        except Exception as e:
            self._add_system_message(f"Cannot read file: {e}")
            return

        panel = self.query_one("#split-panel", ScrollableContainer)
        panel.remove_children()

        rel = os.path.relpath(abs_path)
        panel.mount(Static(f"\U0001f4c4 {rel}", classes="split-panel-title"))

        # Truncate very large files for display
        display = content
        if len(display) > 10_000:
            display = (
                display[:10_000] + f"\n\n... ({len(content):,} chars total, truncated)"
            )

        panel.mount(Static(display, classes="split-panel-content"))

        panel.mount(
            Static(
                "Tab to switch focus • /split off to close",
                classes="split-panel-hint",
            )
        )

        self.add_class("split-mode")
        self._add_system_message(f"Split view: {rel}")

    def _close_split(self) -> None:
        """Close the split panel."""
        self.remove_class("split-mode")
        try:
            panel = self.query_one("#split-panel", ScrollableContainer)
            panel.remove_children()
        except Exception:
            pass
        self._add_system_message("Split view closed")

    # ── /watch – file change monitoring ──────────────────────────────────

    def _cmd_watch(self, text: str) -> None:
        """Watch files for changes, list watches, stop, or show diffs."""
        text = text.strip()

        # /watch  — list current watches
        if not text:
            if not self._watched_files:
                self._add_system_message(
                    "No files being watched.\n"
                    "Watch: /watch <path>\n"
                    "Stop:  /watch stop <path> | /watch stop all\n"
                    "Diff:  /watch diff <path>"
                )
                return
            lines = ["Watched files:"]
            for path, info in self._watched_files.items():
                rel = os.path.relpath(path)
                lines.append(f"  {rel} (since {info['added_at'][:16]})")
            lines.append(f"\n{len(self._watched_files)} file(s) watched")
            self._add_system_message("\n".join(lines))
            return

        # /watch stop <path> | /watch stop all
        if text.startswith("stop ") or text == "stop":
            target = text[5:].strip() if text.startswith("stop ") else ""
            if not target:
                self._add_system_message("Usage: /watch stop <path> | /watch stop all")
                return
            if target == "all":
                count = len(self._watched_files)
                self._watched_files.clear()
                self._stop_watch_timer()
                self._add_system_message(f"Stopped watching {count} file(s)")
            else:
                abs_path = os.path.abspath(os.path.expanduser(target))
                if abs_path in self._watched_files:
                    del self._watched_files[abs_path]
                    if not self._watched_files:
                        self._stop_watch_timer()
                    self._add_system_message(
                        f"Stopped watching: {os.path.relpath(abs_path)}"
                    )
                else:
                    self._add_system_message(f"Not watching: {target}")
            return

        # /watch diff <path>
        if text.startswith("diff ") or text == "diff":
            target = text[5:].strip() if text.startswith("diff ") else ""
            if not target:
                self._add_system_message("Usage: /watch diff <path>")
                return
            abs_path = os.path.abspath(os.path.expanduser(target))
            if abs_path in self._watched_files:
                self._show_watch_diff(abs_path)
            else:
                self._add_system_message(f"Not watching: {target}")
            return

        # /watch <path>  — add a watch
        abs_path = os.path.abspath(os.path.expanduser(text))

        if not os.path.exists(abs_path):
            self._add_system_message(f"Path not found: {text}")
            return

        if len(self._watched_files) >= 10:
            self._add_system_message(
                "Maximum 10 watched files. Use /watch stop <path> to remove one."
            )
            return

        if abs_path in self._watched_files:
            self._add_system_message(f"Already watching: {os.path.relpath(abs_path)}")
            return

        stat = os.stat(abs_path)
        # Read initial content for future diff comparisons
        initial_content: str | None = None
        if os.path.isfile(abs_path):
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as f:
                    initial_content = f.read()
            except OSError:
                pass

        self._watched_files[abs_path] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "added_at": datetime.now().isoformat(),
            "prev_content": None,
            "last_content": initial_content,
        }

        self._start_watch_timer()
        self._add_system_message(f"Watching: {os.path.relpath(abs_path)}")

    def _start_watch_timer(self) -> None:
        """Start the 2-second polling timer for watched files."""
        if self._watch_timer is None:
            self._watch_timer = self.set_interval(2.0, self._check_watched_files)

    def _stop_watch_timer(self) -> None:
        """Stop the polling timer when no files are watched."""
        if self._watch_timer is not None:
            self._watch_timer.stop()
            self._watch_timer = None

    def _check_watched_files(self) -> None:
        """Periodic check for file changes (runs every 2s)."""
        for path, info in list(self._watched_files.items()):
            try:
                if not os.path.exists(path):
                    rel = os.path.relpath(path)
                    self._add_system_message(f"[watch] File removed: {rel}")
                    del self._watched_files[path]
                    continue

                stat = os.stat(path)
                if stat.st_mtime != info["mtime"] or stat.st_size != info["size"]:
                    rel = os.path.relpath(path)

                    # Read new content for diff (only on change, not every poll)
                    new_content: str | None = None
                    line_delta_str = ""
                    if os.path.isfile(path):
                        try:
                            with open(path, encoding="utf-8", errors="replace") as f:
                                new_content = f.read()
                        except OSError:
                            pass

                        if new_content is not None and info["last_content"] is not None:
                            old_lines = info["last_content"].splitlines()
                            new_lines = new_content.splitlines()
                            added = 0
                            removed = 0
                            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                                None, old_lines, new_lines
                            ).get_opcodes():
                                if tag == "insert":
                                    added += j2 - j1
                                elif tag == "delete":
                                    removed += i2 - i1
                                elif tag == "replace":
                                    added += j2 - j1
                                    removed += i2 - i1
                            parts = []
                            if added:
                                parts.append(f"+{added}")
                            if removed:
                                parts.append(f"-{removed}")
                            if parts:
                                line_delta_str = f" ({', '.join(parts)} lines)"

                    # Byte-level fallback when line diff isn't available
                    size_delta = stat.st_size - info["size"]
                    if not line_delta_str:
                        if size_delta > 0:
                            line_delta_str = f" (+{size_delta} bytes)"
                        elif size_delta < 0:
                            line_delta_str = f" ({size_delta} bytes)"

                    # Rotate content snapshots and update tracking
                    info["prev_content"] = info["last_content"]
                    info["last_content"] = new_content
                    info["mtime"] = stat.st_mtime
                    info["size"] = stat.st_size

                    self._add_system_message(f"[watch] Changed: {rel}{line_delta_str}")
                    self._notify_sound(event="file_change")
            except Exception:
                pass

        if not self._watched_files:
            self._stop_watch_timer()

    def _show_watch_diff(self, abs_path: str) -> None:
        """Show a unified diff for the last change to a watched file."""
        info = self._watched_files[abs_path]
        rel = os.path.relpath(abs_path)

        prev = info.get("prev_content")
        current = info.get("last_content")

        if prev is None and current is None:
            self._add_system_message(f"[watch] No content captured yet for: {rel}")
            return

        if prev is None:
            self._add_system_message(
                f"[watch] No previous version to diff against: {rel}\n"
                "Waiting for first change..."
            )
            return

        diff_lines = list(
            difflib.unified_diff(
                prev.splitlines(keepends=True),
                current.splitlines(keepends=True) if current else [],
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )

        if not diff_lines:
            self._add_system_message(f"[watch] No diff available for: {rel}")
            return

        # Truncate very long diffs to keep the chat readable
        max_lines = 80
        truncated = len(diff_lines) > max_lines
        display = diff_lines[:max_lines]
        text = "".join(display)
        if truncated:
            text += f"\n... ({len(diff_lines) - max_lines} more lines)"

        self._add_system_message(f"[watch] Diff for {rel}:\n{text}")

    def _cmd_search(self, text: str) -> None:
        """Search all chat messages for a query string."""
        parts = text.strip().split(None, 1)
        query = parts[1] if len(parts) > 1 else ""
        if not query:
            self._add_system_message("Usage: /search <query>")
            return

        query_lower = query.lower()
        matches: list[dict] = []

        for i, (role, msg_text, widget) in enumerate(self._search_messages):
            if query_lower in msg_text.lower():
                idx = msg_text.lower().index(query_lower)
                start = max(0, idx - 30)
                end = min(len(msg_text), idx + len(query) + 30)
                snippet = msg_text[start:end].replace("\n", " ")
                if start > 0:
                    snippet = "..." + snippet
                if end < len(msg_text):
                    snippet = snippet + "..."
                matches.append(
                    {"index": i + 1, "role": role, "snippet": snippet, "widget": widget}
                )

        if not matches:
            self._add_system_message(f"No matches found for '{query}'")
            return

        count = len(matches)
        label = "match" if count == 1 else "matches"
        lines = [f"Found {count} {label} for '{query}':"]
        for m in matches[:20]:
            lines.append(f"  [{m['role']}] {m['snippet']}")
        if count > 20:
            lines.append(f"  ... and {count - 20} more")
        self._add_system_message("\n".join(lines))

        # Scroll to the first match
        first_widget = matches[0].get("widget")
        if first_widget is not None:
            try:
                first_widget.scroll_visible()
            except Exception:
                pass

    def _cmd_grep(self, text: str) -> None:
        """Search chat messages with options (case-sensitive flag, role labels)."""
        parts = text.strip().split(None, 1)
        args = parts[1] if len(parts) > 1 else ""

        if not args.strip():
            self._add_system_message(
                "Usage: /grep <pattern>  (search conversation, case-insensitive)\n"
                "       /grep -c <pattern>  (case-sensitive search)"
            )
            return

        # Parse flags
        case_sensitive = False
        pattern = args.strip()
        if pattern.startswith("-c "):
            case_sensitive = True
            pattern = pattern[3:].strip()

        if not pattern:
            self._add_system_message("Please provide a search pattern.")
            return

        if not self._search_messages:
            self._add_system_message("No messages to search.")
            return

        # Search through messages
        search_pat = pattern if case_sensitive else pattern.lower()
        matches: list[tuple[int, str, str, "Static | None"]] = []

        for i, (role, msg_text, widget) in enumerate(self._search_messages):
            text_to_search = msg_text if case_sensitive else msg_text.lower()
            if search_pat not in text_to_search:
                continue
            # Find matching lines for context
            for line in msg_text.split("\n"):
                line_search = line if case_sensitive else line.lower()
                if search_pat in line_search:
                    preview = line.strip()
                    if len(preview) > 80:
                        preview = preview[:80] + "..."
                    matches.append((i, role, preview, widget))
                    break  # one match per message is enough

        if not matches:
            flag_hint = "" if case_sensitive else " (case-insensitive)"
            self._add_system_message(f"No matches for '{pattern}'{flag_hint}")
            return

        # Format results
        count = len(matches)
        label = "match" if count == 1 else "matches"
        cs_label = " (case-sensitive)" if case_sensitive else ""
        lines = [f"Found {count} {label} for '{pattern}'{cs_label}:"]

        role_labels = {"user": "You", "assistant": "AI", "system": "Sys"}
        shown = min(count, 20)
        for msg_idx, role, preview, _widget in matches[:shown]:
            role_label = role_labels.get(role, role)
            lines.append(f"  [{role_label} #{msg_idx + 1}] {preview}")

        if count > shown:
            lines.append(f"  ... and {count - shown} more matches")

        self._add_system_message("\n".join(lines))

        # Scroll to the first match
        first_widget = matches[0][3]
        if first_widget is not None:
            try:
                first_widget.scroll_visible()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    def _run_git(self, *args: str, cwd: str | None = None) -> tuple[bool, str]:
        """Run a git command and return *(success, output)*."""
        try:
            result = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd or os.getcwd(),
            )
            return (
                result.returncode == 0,
                result.stdout.strip() or result.stderr.strip(),
            )
        except FileNotFoundError:
            return False, "git not found"
        except subprocess.TimeoutExpired:
            return False, "git command timed out"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Diff display helpers
    # ------------------------------------------------------------------

    def _looks_like_commit_ref(self, text: str) -> bool:
        """Check if *text* looks like a git commit reference."""
        if text.startswith("HEAD"):
            return True
        # SHA-like hex string (7-40 chars)
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", text):
            return True
        # Contains ~ or ^ (e.g., main~3, abc123^2)
        if "~" in text or "^" in text:
            return True
        return False

    def _colorize_diff(self, diff_text: str) -> str:
        """Apply Rich markup colors to diff output."""
        from rich.markup import escape

        lines: list[str] = []
        for line in diff_text.split("\n"):
            escaped = escape(line)
            if line.startswith("+++") or line.startswith("---"):
                lines.append(f"[bold]{escaped}[/bold]")
            elif line.startswith("@@"):
                lines.append(f"[cyan]{escaped}[/cyan]")
            elif line.startswith("+"):
                lines.append(f"[green]{escaped}[/green]")
            elif line.startswith("-"):
                lines.append(f"[red]{escaped}[/red]")
            elif line.startswith("diff "):
                lines.append(f"[bold yellow]{escaped}[/bold yellow]")
            else:
                lines.append(escaped)
        return "\n".join(lines)

    def _show_diff(self, diff_output: str, header: str = "") -> None:
        """Display colorized diff output, truncating if too large."""
        max_lines = 500
        all_lines = diff_output.split("\n")
        total = len(all_lines)
        truncated = total > max_lines

        text = "\n".join(all_lines[:max_lines]) if truncated else diff_output
        colored = self._colorize_diff(text)

        if header:
            from rich.markup import escape

            colored = escape(header) + colored

        if truncated:
            colored += (
                f"\n\n... truncated ({total} total lines)."
                " Use /diff <file> to see specific files."
            )

        self._add_system_message(colored)

    # ------------------------------------------------------------------
    # /diff command
    # ------------------------------------------------------------------

    def _cmd_diff(self, text: str) -> None:
        """Show git diff with color-coded output.

        /diff              Unstaged changes (or file summary when clean)
        /diff staged       Staged changes
        /diff all          All unstaged (+ staged fallback)
        /diff last         Changes in last commit
        /diff <file>       Diff for one file (tries staged too)
        /diff <f1> <f2>    Compare two files
        /diff HEAD~N       Changes since N commits ago
        /diff <commit>     Changes since a commit
        """
        text = text.strip()

        # Check if we're inside a git repo
        ok, _ = self._run_git("rev-parse", "--is-inside-work-tree")
        if not ok:
            self._add_system_message("Not in a git repository")
            return

        # --- /diff (no args) -> unstaged diff, or status summary ---
        if not text:
            ok, output = self._run_git("diff", "--color=never")
            if not ok:
                self._add_system_message(f"git error: {output}")
                return
            if not output:
                # No unstaged diff — show status summary as guidance
                ok, status = self._run_git("status", "--short")
                if not ok or not status:
                    self._add_system_message("No changes detected (working tree clean)")
                    return
                lines = ["No unstaged changes. Changed files:", ""]
                for line in status.split("\n"):
                    if line.strip():
                        lines.append(f"  {line}")
                lines.append("")
                lines.append("Use /diff staged, /diff <file>, or /diff all")
                self._add_system_message("\n".join(lines))
                return
            self._show_diff(output)
            return

        # --- /diff all ---
        if text == "all":
            ok, output = self._run_git("diff", "--color=never")
            if not ok or not output:
                # Also check staged changes
                ok2, staged = self._run_git("diff", "--staged", "--color=never")
                if staged:
                    output = staged
                elif not output:
                    self._add_system_message("No changes")
                    return
            self._show_diff(output)
            return

        # --- /diff staged ---
        if text == "staged":
            ok, output = self._run_git("diff", "--staged", "--color=never")
            if not ok or not output:
                self._add_system_message("No staged changes")
                return
            self._show_diff(output)
            return

        # --- /diff last ---
        if text == "last":
            ok, output = self._run_git("diff", "HEAD~1", "HEAD", "--color=never")
            if not ok:
                self._add_system_message(f"git error: {output}")
                return
            if not output:
                self._add_system_message("No changes in last commit")
                return
            # Prepend the commit summary line when available
            ok2, msg = self._run_git("log", "-1", "--oneline")
            header = f"Last commit: {msg}\n\n" if ok2 and msg else ""
            self._show_diff(output, header=header)
            return

        # --- /diff <file1> <file2> (two paths) ---
        if " " in text:
            parts = text.split(None, 1)
            if len(parts) == 2:
                # --no-index returns exit-code 1 when files differ (normal)
                _ok, output = self._run_git(
                    "diff",
                    "--no-index",
                    "--color=never",
                    parts[0],
                    parts[1],
                )
                if not output:
                    self._add_system_message(
                        f"No differences between '{parts[0]}' and '{parts[1]}'"
                    )
                    return
                self._show_diff(output)
                return

        # --- /diff HEAD~N or commit-ish ---
        if self._looks_like_commit_ref(text):
            ok, output = self._run_git("diff", text, "--color=never")
            if not ok:
                self._add_system_message(f"git error: {output}")
                return
            if not output:
                self._add_system_message(f"No changes from {text}")
                return
            self._show_diff(output)
            return

        # --- /diff <file> ---
        ok, output = self._run_git("diff", "--color=never", "--", text)
        if not ok:
            self._add_system_message(f"git error: {output}")
            return
        if not output:
            # Try staged changes for this file
            ok, output = self._run_git("diff", "--staged", "--color=never", "--", text)
            if not ok or not output:
                self._add_system_message(f"No changes for '{text}'")
                return
        self._show_diff(output)

    def _cmd_focus(self, text: str = "") -> None:
        """Toggle focus mode via slash command.

        /focus      - toggle
        /focus on   - enable
        /focus off  - disable
        """
        arg = text.strip().lower()
        if arg == "on":
            self._set_focus_mode(True)
        elif arg == "off":
            self._set_focus_mode(False)
        else:
            self._set_focus_mode(not self._focus_mode)

    def _cmd_copy(self, text: str) -> None:
        """Copy a message to clipboard.

        /copy        — last assistant response
        /copy N      — message N (1-based index)
        /copy all    — entire conversation
        /copy code   — last code block from any message
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        arg_lower = arg.lower()

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
                self._add_system_message(
                    f"Copied entire conversation"
                    f" ({len(self._search_messages)} messages,"
                    f" {len(full_text)} chars)"
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
                        preview = code[:60].replace("\n", " ")
                        if len(code) > 60:
                            preview += "..."
                        self._add_system_message(
                            f"Copied code block ({len(code)} chars): {preview}"
                        )
                    else:
                        self._add_system_message(
                            "Failed to copy — no clipboard tool available"
                            " (install xclip or xsel)"
                        )
                    return
            self._add_system_message("No code blocks found in conversation")
            return

        # --- /copy N ---
        if arg and arg.isdigit():
            # Copy specific message by index (1-based, from /search results)
            idx = int(arg) - 1
            if 0 <= idx < len(self._search_messages):
                role, msg_text, _widget = self._search_messages[idx]
                if _copy_to_clipboard(msg_text):
                    self._add_system_message(
                        f"Copied message #{arg} [{role}] ({len(msg_text)} chars)"
                    )
                else:
                    self._add_system_message(
                        "Failed to copy — no clipboard tool available"
                        " (install xclip or xsel)"
                    )
            else:
                total = len(self._search_messages)
                self._add_system_message(
                    f"Message {arg} not found (range: 1-{total})"
                    if total
                    else "No messages yet"
                )
            return

        if arg:
            self._add_system_message(
                "Usage: /copy [all|code|N] — copy response, conversation, or code block"
            )
            return

        # Default: copy last assistant message
        self.action_copy_response()

    def _cmd_scroll(self) -> None:
        """Toggle auto-scroll on/off."""
        self.action_toggle_auto_scroll()

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
                "Usage: /notify [on|off|sound|silent|<seconds>]\n"
                "  /notify         Toggle on/off\n"
                "  /notify on      Enable completion notifications\n"
                "  /notify off     Disable notifications\n"
                "  /notify sound   Same as on\n"
                "  /notify silent  Same as off\n"
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

    def _cmd_timestamps(self) -> None:
        """Toggle message timestamps on/off."""
        self._prefs.display.show_timestamps = not self._prefs.display.show_timestamps
        save_show_timestamps(self._prefs.display.show_timestamps)
        state = "on" if self._prefs.display.show_timestamps else "off"
        # Show/hide existing timestamp widgets
        for ts_widget in self.query(".msg-timestamp"):
            ts_widget.display = self._prefs.display.show_timestamps
        self._add_system_message(f"Timestamps {state}")

    def _cmd_wrap(self, text: str) -> None:
        """Toggle word wrap on/off for chat messages."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "on":
            wrap = True
        elif arg == "off":
            wrap = False
        elif not arg:
            wrap = not self._prefs.display.word_wrap
        else:
            self._add_system_message("Usage: /wrap [on|off]")
            return

        self._prefs.display.word_wrap = wrap
        save_word_wrap(wrap)

        # Toggle CSS class on chat view
        chat = self._active_chat_view()
        if wrap:
            chat.remove_class("no-wrap")
        else:
            chat.add_class("no-wrap")

        state = "on" if wrap else "off"
        self._add_system_message(f"Word wrap: {state}")

    def _cmd_stream(self, args: str) -> None:
        """Toggle streaming token display on/off."""
        arg = args.strip().lower()

        if arg in ("on", "true", "1"):
            enabled = True
        elif arg in ("off", "false", "0"):
            enabled = False
        elif not arg:
            enabled = not self._prefs.display.streaming_enabled
        else:
            self._add_system_message(
                "Usage: /stream [on|off]\n"
                "  /stream      Toggle streaming display\n"
                "  /stream on   Enable progressive token streaming\n"
                "  /stream off  Disable streaming (show full response at once)"
            )
            return

        self._prefs.display.streaming_enabled = enabled
        save_streaming_enabled(enabled)

        if enabled:
            self._add_system_message(
                "Streaming: ON\n"
                "Tokens appear progressively as they arrive.\n"
                "Press Escape to cancel mid-stream."
            )
        else:
            self._add_system_message(
                "Streaming: OFF\nFull response will appear after generation completes."
            )

    def _cmd_fold(self, text: str) -> None:
        """Fold/unfold long messages or set fold threshold."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "all":
            self._fold_all_messages()
            return
        if arg in ("none", "off"):
            self._unfold_all_messages()
            return
        if arg.isdigit():
            threshold = max(5, int(arg))
            self._fold_threshold = threshold
            self._add_system_message(f"Fold threshold set to {threshold} lines")
            return
        if not arg:
            self._toggle_fold_all()
            return

        self._add_system_message(
            "Usage: /fold [all|none|<n>]\n"
            "  /fold        Toggle fold on long messages\n"
            "  /fold all    Fold all long messages\n"
            "  /fold none   Unfold all messages\n"
            "  /fold <n>    Set fold threshold (min 5)"
        )

    def _fold_all_messages(self) -> None:
        """Fold all messages that have fold toggles."""
        count = 0
        for toggle in self.query(FoldToggle):
            if not toggle._target.has_class("folded"):
                toggle._target.add_class("folded")
                toggle.update(toggle._make_label(folded=True))
                count += 1
        self._add_system_message(f"Folded {count} message{'s' if count != 1 else ''}")

    def _unfold_all_messages(self) -> None:
        """Unfold all folded messages."""
        count = 0
        for toggle in self.query(FoldToggle):
            if toggle._target.has_class("folded"):
                toggle._target.remove_class("folded")
                toggle.update(toggle._make_label(folded=False))
                count += 1
        self._add_system_message(f"Unfolded {count} message{'s' if count != 1 else ''}")

    def _toggle_fold_all(self) -> None:
        """Toggle: fold unfolded messages, or unfold all if all are folded."""
        toggles = list(self.query(FoldToggle))
        if not toggles:
            self._add_system_message("No foldable messages")
            return
        any_unfolded = any(not t._target.has_class("folded") for t in toggles)
        if any_unfolded:
            self._fold_all_messages()
        else:
            self._unfold_all_messages()

    def _cmd_history(self, text: str) -> None:
        """Browse or clear prompt history."""
        text = text.strip()

        if text == "clear":
            self._history.clear()
            self._add_system_message("Input history cleared.")
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
            "Up/Down arrows to recall, Ctrl+R to search, /history clear to reset"
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

    def _execute_undo(self, count: int) -> None:
        """Remove the last *count* user+assistant exchanges from chat."""
        # Walk backward through _search_messages collecting entries to remove.
        # An "exchange" is an assistant message together with its preceding
        # user message.  An orphan user message (no response yet) also counts
        # as one exchange.
        to_remove: list[tuple[str, str, Static | None]] = []
        remaining = count
        i = len(self._search_messages) - 1

        while i >= 0 and remaining > 0:
            role, _content, _widget = self._search_messages[i]

            if role == "system":
                # Skip system messages — never undo them
                i -= 1
                continue

            if role == "assistant":
                # Found an assistant message — include it
                to_remove.append(self._search_messages[i])
                # Look backward for the paired user message
                j = i - 1
                while j >= 0:
                    r2 = self._search_messages[j][0]
                    if r2 == "user":
                        to_remove.append(self._search_messages[j])
                        i = j - 1
                        break
                    elif r2 == "system":
                        j -= 1
                        continue
                    else:
                        # Adjacent assistant without a user — unusual but stop
                        i = j - 1
                        break
                else:
                    # Reached the beginning without finding a user message
                    i = -1
                remaining -= 1

            elif role == "user":
                # Orphan user message (no assistant response yet)
                to_remove.append(self._search_messages[i])
                remaining -= 1
                i -= 1
            else:
                i -= 1

        if not to_remove:
            self._add_system_message("Nothing to undo.")
            return

        # Build a set of indices for fast removal from _search_messages
        indices_to_remove: set[int] = set()
        for entry in to_remove:
            try:
                idx = self._search_messages.index(entry)
                indices_to_remove.add(idx)
            except ValueError:
                pass

        # Remove widgets from the DOM (message + adjacent timestamp / fold toggle)
        for _role, _content, widget in to_remove:
            if widget is None:
                continue

            # Remove a FoldToggle that immediately follows the message
            try:
                next_sib = widget.next_sibling  # type: ignore[attr-defined]
                if isinstance(next_sib, FoldToggle):
                    next_sib.remove()
            except Exception:
                pass

            # Remove a timestamp widget that immediately precedes the message
            try:
                prev_sib = widget.previous_sibling  # type: ignore[attr-defined]
                if prev_sib is not None and prev_sib.has_class("msg-timestamp"):
                    prev_sib.remove()
            except Exception:
                pass

            # Remove the message widget itself
            widget.remove()

        # Adjust stats counters
        for role, content, _widget in to_remove:
            words = self._count_words(content)
            self._total_words = max(0, self._total_words - words)
            if role == "user":
                self._user_message_count = max(0, self._user_message_count - 1)
                self._user_words = max(0, self._user_words - words)
            elif role == "assistant":
                self._assistant_message_count = max(
                    0, self._assistant_message_count - 1
                )
                self._assistant_words = max(0, self._assistant_words - words)

        # Remove entries from _search_messages (in reverse index order)
        for idx in sorted(indices_to_remove, reverse=True):
            del self._search_messages[idx]

        # If the last assistant widget was among those removed, update the ref
        for _role, _content, widget in to_remove:
            if widget is self._last_assistant_widget:
                self._last_assistant_widget = None
                self._last_assistant_text = ""
                break

        self._update_word_count_display()

        # Feedback
        exchanges = count - remaining
        preview = to_remove[0][1][:60].replace("\n", " ")
        if len(to_remove[0][1]) > 60:
            preview += "\u2026"
        self._add_system_message(
            f"Undid {exchanges} exchange(s) "
            f"({len(to_remove)} message{'s' if len(to_remove) != 1 else ''} removed)\n"
            f"Last removed: {preview}\n"
            "Note: messages remain in the LLM context for this session."
        )

    def _cmd_keys(self) -> None:
        """Show the keyboard shortcut overlay."""
        self.action_show_shortcuts()

    def _cmd_stats(self, text: str = "") -> None:
        """Show session statistics, or a subcommand view.

        Subcommands:
            /stats          Full overview
            /stats tools    Detailed tool usage breakdown
            /stats tokens   Detailed token breakdown with cost estimate
        """
        sub = text.strip().lower()

        if sub == "tools":
            self._cmd_stats_tools()
            return
        if sub == "tokens":
            self._cmd_stats_tokens()
            return
        if sub:
            self._add_system_message(
                f"Unknown subcommand: /stats {sub}\n"
                "Usage: /stats | /stats tools | /stats tokens"
            )
            return

        fmt = self._format_token_count

        # --- Duration ---
        elapsed = time.monotonic() - self._session_start_time
        if elapsed < 60:
            duration = f"{int(elapsed)}s"
        elif elapsed < 3600:
            duration = f"{int(elapsed / 60)}m"
        else:
            hours = int(elapsed / 3600)
            mins = int((elapsed % 3600) / 60)
            duration = f"{hours}h {mins}m"

        # --- Session / model ---
        session_id = "none"
        model = "unknown"
        if self.session_manager:
            sid = getattr(self.session_manager, "session_id", None) or ""
            session_id = sid[:12] if sid else "none"
            model = getattr(self.session_manager, "model_name", None) or "unknown"

        # --- Message counts ---
        total_msgs = self._user_message_count + self._assistant_message_count

        # --- Word counts ---
        user_w = self._format_count(self._user_words)
        asst_w = self._format_count(self._assistant_words)

        # --- Token estimates (words * 1.3) ---
        total_words = self._user_words + self._assistant_words
        est_tokens = int(total_words * 1.3)

        # --- Title ---
        title = getattr(self, "_session_title", "") or ""

        # --- Build output ---
        lines: list[str] = [
            "Session Statistics",
            "─" * 40,
            f"  Session:         {session_id}",
        ]
        if title:
            lines.append(f"  Title:           {title}")
        lines += [
            f"  Model:           {model}",
            f"  Duration:        {duration}",
            "",
            f"  Messages:        {total_msgs} total",
            f"    You:           {self._user_message_count} ({user_w} words)",
            f"    AI:            {self._assistant_message_count} ({asst_w} words)",
            f"    Tool calls:    {self._tool_call_count}",
            "",
            f"  Est. tokens:     ~{fmt(est_tokens)}",
        ]

        # Real API token data from session manager
        sm = self.session_manager
        if sm:
            inp_tok = getattr(sm, "total_input_tokens", 0) or 0
            out_tok = getattr(sm, "total_output_tokens", 0) or 0
            if inp_tok or out_tok:
                lines.append(
                    f"  API tokens:      {fmt(inp_tok)} in / {fmt(out_tok)} out"
                )
                # Context usage percentage
                window = self._get_context_window()
                if window > 0:
                    pct = min(100.0, inp_tok / window * 100)
                    lines.append(f"  Context:         {pct:.1f}% of {fmt(window)}")

        # --- Response times ---
        if self._response_times:
            times = self._response_times
            avg_t = sum(times) / len(times)
            min_t = min(times)
            max_t = max(times)
            lines.append("")
            lines.append(f"  Response times:  {len(times)} requests")
            lines.append(f"    Avg:           {avg_t:.1f}s")
            lines.append(f"    Min:           {min_t:.1f}s")
            lines.append(f"    Max:           {max_t:.1f}s")

        # --- Top tools ---
        if self._tool_usage:
            lines.append("")
            lines.append("  Top tools:")
            sorted_tools = sorted(self._tool_usage.items(), key=lambda x: -x[1])
            for name, count in sorted_tools[:5]:
                label = TOOL_LABELS.get(name, name)
                lines.append(f"    {label:<20s} {count}")
            if len(self._tool_usage) > 5:
                lines.append(
                    f"    ... {len(self._tool_usage) - 5} more "
                    "(use /stats tools for full list)"
                )

        lines.append("")
        lines.append("Tip: /stats tools | /stats tokens for details")

        self._add_system_message("\n".join(lines))

    def _cmd_stats_tools(self) -> None:
        """Show detailed tool usage breakdown."""
        if not self._tool_usage:
            self._add_system_message("No tools used in this session yet.")
            return

        sorted_tools = sorted(self._tool_usage.items(), key=lambda x: -x[1])
        total_calls = sum(self._tool_usage.values())

        lines: list[str] = [
            "Tool Usage Breakdown",
            "─" * 40,
        ]

        for name, count in sorted_tools:
            label = TOOL_LABELS.get(name, name)
            pct = count / total_calls * 100
            bar_w = 15
            filled = int(pct / 100 * bar_w)
            bar = "█" * filled + "░" * (bar_w - filled)
            lines.append(f"  {label:<20s} {count:3d}  {bar} {pct:4.1f}%")

        lines += [
            "",
            f"  Total:             {total_calls:3d} calls",
            f"  Unique tools:      {len(self._tool_usage):3d}",
        ]

        self._add_system_message("\n".join(lines))

    def _cmd_stats_tokens(self) -> None:
        """Show detailed token breakdown with cost estimate."""
        fmt = self._format_token_count
        sm = self.session_manager

        inp_tok = (getattr(sm, "total_input_tokens", 0) or 0) if sm else 0
        out_tok = (getattr(sm, "total_output_tokens", 0) or 0) if sm else 0
        api_total = inp_tok + out_tok

        # Word-based estimates
        total_words = self._user_words + self._assistant_words
        est_tokens = int(total_words * 1.3)

        # Context window
        window = self._get_context_window()
        model = (sm.model_name if sm else "") or "unknown"

        lines: list[str] = [
            "Token Breakdown",
            "─" * 40,
            f"  Model:             {model}",
            f"  Context window:    {fmt(window)}",
            "",
        ]

        if api_total > 0:
            pct_in = inp_tok / api_total * 100 if api_total else 0
            pct_out = out_tok / api_total * 100 if api_total else 0
            ctx_pct = min(100.0, inp_tok / window * 100) if window > 0 else 0

            lines += [
                "  API Tokens (actual)",
                "  " + "─" * 20,
                f"  Input:             {inp_tok:>10,}  ({pct_in:.1f}%)",
                f"  Output:            {out_tok:>10,}  ({pct_out:.1f}%)",
                f"  Total:             {api_total:>10,}",
                f"  Context used:      {ctx_pct:.1f}%",
                "",
            ]

            # Cost estimate (Claude Sonnet pricing: $3/M input, $15/M output)
            cost_in = inp_tok * 3.0 / 1_000_000
            cost_out = out_tok * 15.0 / 1_000_000
            cost_total = cost_in + cost_out
            lines += [
                "  Estimated Cost (Sonnet pricing)",
                "  " + "─" * 33,
                f"  Input  ($3/M):     ${cost_in:.4f}",
                f"  Output ($15/M):    ${cost_out:.4f}",
                f"  Total:             ${cost_total:.4f}",
                "",
            ]
        else:
            lines.append("  (no API token data yet)")
            lines.append("")

        lines += [
            "  Word-based Estimate",
            "  " + "─" * 21,
            f"  User words:        {self._user_words:>10,}",
            f"  Assistant words:   {self._assistant_words:>10,}",
            f"  Total words:       {total_words:>10,}",
            f"  Est. tokens:       ~{fmt(est_tokens)}  (words × 1.3)",
        ]

        self._add_system_message("\n".join(lines))

    @staticmethod
    def _format_count(n: int) -> str:
        """Format a count with k/M suffix: 1234 -> '1.2k'."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    def _cmd_info(self) -> None:
        """Show comprehensive session information."""
        session_id = self._get_session_id()
        if not session_id:
            self._add_system_message("No active session")
            return

        sm = self.session_manager
        names = self._load_session_names()
        pins = self._pinned_sessions
        bookmarks = self._load_bookmarks()

        # Gather info
        custom_name = names.get(session_id, "")
        is_pinned = session_id in pins
        bookmark_count = len(bookmarks.get(session_id, []))

        # Message counts
        user_msgs = self._user_message_count
        asst_msgs = self._assistant_message_count
        total_msgs = user_msgs + asst_msgs
        tool_calls = self._tool_call_count

        # Token info from session manager
        input_tokens = getattr(sm, "total_input_tokens", 0) if sm else 0
        output_tokens = getattr(sm, "total_output_tokens", 0) if sm else 0
        context_window = getattr(sm, "context_window", 0) if sm else 0

        # Word-based estimate as fallback
        total_words = self._user_words + self._assistant_words
        est_tokens = int(total_words * 1.3)

        # Model info
        model = (getattr(sm, "model_name", "") if sm else "") or ""
        preferred = getattr(self._prefs, "preferred_model", "")
        model_display = model or preferred or "unknown"

        # Project directory
        project = str(Path.cwd())

        # Duration
        elapsed = time.monotonic() - self._session_start_time
        if elapsed < 60:
            duration = f"{int(elapsed)} seconds"
        elif elapsed < 3600:
            duration = f"{int(elapsed / 60)} minutes"
        else:
            hours = int(elapsed / 3600)
            mins = int((elapsed % 3600) / 60)
            duration = f"{hours}h {mins}m"

        # Build display
        lines = [
            "Session Information",
            "\u2500" * 40,
            f"  ID:          {session_id[:12]}{'...' if len(session_id) > 12 else ''}",
        ]

        if custom_name:
            lines.append(f"  Name:        {custom_name}")

        lines.extend(
            [
                f"  Model:       {model_display}",
                f"  Project:     {project}",
                f"  Duration:    {duration}",
                f"  Pinned:      {'Yes' if is_pinned else 'No'}",
                f"  Bookmarks:   {bookmark_count}",
                "",
                f"  Messages:    {total_msgs} total",
                f"    User:      {user_msgs}",
                f"    Assistant: {asst_msgs}",
                f"  Tool calls:  {tool_calls}",
            ]
        )

        # Show actual token usage if available, otherwise estimate
        if input_tokens or output_tokens:
            lines.append(
                f"  Tokens:      {input_tokens:,} in \u00b7 {output_tokens:,} out"
            )
            if context_window:
                lines.append(f"  Context:     {context_window:,} window")
        else:
            lines.append(f"  Est. tokens: ~{est_tokens:,}")

        # Theme and sort info
        theme = getattr(self._prefs, "theme_name", "dark")
        sort_mode = getattr(self._prefs, "session_sort", "date")
        lines.extend(
            [
                "",
                f"  Theme:       {theme}",
                f"  Sort:        {sort_mode}",
            ]
        )

        self._add_system_message("\n".join(lines))

    def _cmd_tokens(self) -> None:
        """Show detailed token / context usage breakdown."""
        sm = self.session_manager
        model = (sm.model_name if sm else "") or "unknown"
        window = self._get_context_window()

        # Real API-reported tokens (accumulated from llm:response hooks)
        input_tok = sm.total_input_tokens if sm else 0
        output_tok = sm.total_output_tokens if sm else 0
        api_total = input_tok + output_tok

        # Character-based estimate from visible messages
        user_chars = sum(len(t) for r, t, _w in self._search_messages if r == "user")
        asst_chars = sum(
            len(t) for r, t, _w in self._search_messages if r == "assistant"
        )
        sys_chars = sum(len(t) for r, t, _w in self._search_messages if r == "system")
        est_user = user_chars // 4
        est_asst = asst_chars // 4
        est_sys = sys_chars // 4
        est_total = est_user + est_asst + est_sys

        # Prefer real API tokens when available; fall back to estimate
        display_total = api_total if api_total > 0 else est_total
        pct = min(100.0, (display_total / window * 100)) if window > 0 else 0.0

        # Visual progress bar (20 chars wide)
        bar_width = 20
        filled = int(pct / 100 * bar_width)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)

        # Message counts
        msg_count = len(self._search_messages)
        user_msg_count = sum(1 for r, _, _ in self._search_messages if r == "user")
        asst_msg_count = sum(1 for r, _, _ in self._search_messages if r == "assistant")
        sys_msg_count = sum(1 for r, _, _ in self._search_messages if r == "system")

        fmt = self._format_token_count
        source = "API" if api_total > 0 else "estimated"

        lines = [
            f"Context Usage  [{bar}] {pct:.0f}%",
            "\u2500" * 40,
            f"  Model:       {model}",
            f"  Window:      {fmt(window)} tokens",
            f"  Used:        ~{fmt(display_total)} tokens ({source})",
            f"  Remaining:   ~{fmt(max(0, window - display_total))} tokens",
        ]

        if api_total > 0:
            lines += [
                "",
                "API tokens:",
                f"  Input:       ~{fmt(input_tok)}",
                f"  Output:      ~{fmt(output_tok)}",
                f"  Total:       ~{fmt(api_total)}",
            ]

        lines += [
            "",
            "Breakdown (~4 chars/token):",
            f"  User:        ~{fmt(est_user)} tokens",
            f"  Assistant:   ~{fmt(est_asst)} tokens",
            f"  System:      ~{fmt(est_sys)} tokens",
            "",
            f"Messages: {msg_count} total"
            f" ({user_msg_count} user,"
            f" {asst_msg_count} assistant,"
            f" {sys_msg_count} system)",
            "",
            "Note: Token counts are estimates (~4 chars/token).",
            "Actual usage may vary by model tokenizer. Context also",
            "includes system prompts, tool schemas, and overhead",
            "(typically ~10-20K tokens). Use /compact to free space.",
        ]
        self._add_system_message("\n".join(lines))

    def _cmd_context(self) -> None:
        """Show visual context window usage with a progress bar."""
        sm = self.session_manager
        model = (sm.model_name if sm else "") or "unknown"
        window = self._get_context_window()
        fmt = self._format_token_count

        # --- Gather token counts (prefer real API data) ---
        input_tokens = 0
        output_tokens = 0

        if sm:
            input_tokens = getattr(sm, "total_input_tokens", 0) or 0
            output_tokens = getattr(sm, "total_output_tokens", 0) or 0

        # Fallback: estimate from visible message text (~4 chars/token)
        estimated = False
        if input_tokens == 0 and output_tokens == 0:
            estimated = True
            for role, content, _widget in self._search_messages:
                tok_est = len(content) // 4
                if role == "user":
                    input_tokens += tok_est
                elif role == "assistant":
                    output_tokens += tok_est
                else:
                    input_tokens += tok_est  # system msgs count toward input

        total = input_tokens + output_tokens

        # Input tokens are the best proxy for how full the context window is
        # (each request sends the full conversation as input).
        effective_used = input_tokens
        pct = min(100.0, (effective_used / window * 100)) if window > 0 else 0.0

        # --- Visual bar (30 chars wide) ---
        bar_width = 30
        filled = int(pct / 100 * bar_width)
        empty = bar_width - filled

        if pct < 50:
            color_label = "green"
        elif pct < 75:
            color_label = "yellow"
        else:
            color_label = "red"

        bar = f"[{'█' * filled}{'░' * empty}]"

        # --- Build output ---
        source = "estimated" if estimated else "API"
        lines = [
            "Context Usage",
            "\u2500" * 40,
            f"  Model:     {model}",
            f"  Window:    {fmt(window)} tokens",
            "",
            f"  {bar} {pct:.1f}%",
            "",
            f"  Input:     ~{fmt(input_tokens)} ({source})",
            f"  Output:    ~{fmt(output_tokens)} ({source})",
            f"  Total:     ~{fmt(total)}",
            f"  Remaining: ~{fmt(max(0, window - effective_used))}",
        ]

        if pct > 90:
            lines += [
                "",
                "  \u26a0 Context nearly full! Start a new session with /new.",
            ]
        elif pct > 75:
            lines += [
                "",
                f"  \u26a0 Context is getting full ({color_label}). Consider /clear or /new.",
            ]

        self._add_system_message("\n".join(lines))

    def _cmd_theme(self, text: str) -> None:
        """Switch color theme or show current/available themes."""
        parts = text.strip().split(None, 1)

        if len(parts) < 2:
            # No argument: list themes with descriptions and active marker
            current = self._prefs.theme_name
            lines = ["Available themes:"]
            for name, desc in THEME_DESCRIPTIONS.items():
                marker = " *" if name == current else "  "
                lines.append(f"{marker} {name}: {desc}")
            lines.append("")
            lines.append("Use: /theme <name>")
            self._add_system_message("\n".join(lines))
            return

        name = parts[1].strip().lower()
        if not self._prefs.apply_theme(name):
            available = ", ".join(THEMES)
            self._add_system_message(f"Unknown theme: {name}\nAvailable: {available}")
            return

        self._prefs.theme_name = name
        save_colors(self._prefs.colors)
        save_theme_name(name)

        # Switch the Textual base theme (background, surface, panel, etc.)
        textual_theme = TEXTUAL_THEMES.get(name)
        if textual_theme:
            self.theme = textual_theme.name

        self._apply_theme_to_all_widgets()
        desc = THEME_DESCRIPTIONS.get(name, "")
        self._add_system_message(
            f"Theme: {name} — {desc}" if desc else f"Theme: {name}"
        )

    def _apply_theme_to_all_widgets(self) -> None:
        """Re-style every visible chat widget with the current theme colors."""
        try:
            chat_view = self._active_chat_view()
        except Exception:
            return

        ts_color = self._prefs.colors.timestamp
        for widget in chat_view.children:
            classes = widget.classes if hasattr(widget, "classes") else set()

            if "msg-timestamp" in classes:
                widget.styles.color = ts_color

            elif "user-message" in classes:
                self._style_user(widget)

            elif "assistant-message" in classes:
                self._style_assistant(widget)

            elif "system-message" in classes:
                self._style_system(widget)

            elif "error-message" in classes:
                self._style_error(widget)

            elif "thinking-block" in classes:
                # Collapsible with an inner Static
                inner_list = widget.query(".thinking-text")
                inner = inner_list.first() if inner_list else None
                if inner is not None:
                    self._style_thinking(widget, inner)

            elif "tool-use" in classes:
                # Collapsible with an inner Static
                inner_list = widget.query(".tool-detail")
                inner = inner_list.first() if inner_list else None
                if inner is not None:
                    self._style_tool(widget, inner)

    # Role shortcuts: simple names map to the primary _text key.
    _COLOR_ROLE_ALIASES: dict[str, str] = {
        "user": "user_text",
        "assistant": "assistant_text",
        "system": "system_text",
        "error": "error_text",
        "tool": "tool_text",
        "thinking": "thinking_text",
        "timestamp": "timestamp",
    }

    def _cmd_colors(self, text: str) -> None:
        """View, change, or reset individual color preferences."""
        from dataclasses import fields

        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg:
            # Show current color settings with colored swatches
            c = self._prefs.colors

            def _swatch(hex_color: str) -> str:
                """Return a Rich-markup colored swatch block."""
                return f"[{hex_color}]\u2588\u2588\u2588\u2588[/]"

            lines = [
                "Text Colors:",
                "",
                f"  user        {c.user_text:<10} {_swatch(c.user_text)}",
                f"  assistant   {c.assistant_text:<10} {_swatch(c.assistant_text)}",
                f"  system      {c.system_text:<10} {_swatch(c.system_text)}",
                f"  error       {c.error_text:<10} {_swatch(c.error_text)}",
                f"  tool        {c.tool_text:<10} {_swatch(c.tool_text)}",
                f"  thinking    {c.thinking_text:<10} {_swatch(c.thinking_text)}",
                f"  timestamp   {c.timestamp:<10} {_swatch(c.timestamp)}",
                "",
                "All keys:",
                f"  user_text           {c.user_text:<10} {_swatch(c.user_text)}",
                f"  user_border         {c.user_border:<10} {_swatch(c.user_border)}",
                f"  assistant_text      {c.assistant_text:<10} {_swatch(c.assistant_text)}",
                f"  assistant_border    {c.assistant_border:<10} {_swatch(c.assistant_border)}",
                f"  thinking_text       {c.thinking_text:<10} {_swatch(c.thinking_text)}",
                f"  thinking_border     {c.thinking_border:<10} {_swatch(c.thinking_border)}",
                f"  thinking_background {c.thinking_background:<10} {_swatch(c.thinking_background)}",
                f"  tool_text           {c.tool_text:<10} {_swatch(c.tool_text)}",
                f"  tool_border         {c.tool_border:<10} {_swatch(c.tool_border)}",
                f"  tool_background     {c.tool_background:<10} {_swatch(c.tool_background)}",
                f"  system_text         {c.system_text:<10} {_swatch(c.system_text)}",
                f"  system_border       {c.system_border:<10} {_swatch(c.system_border)}",
                f"  error_text          {c.error_text:<10} {_swatch(c.error_text)}",
                f"  error_border        {c.error_border:<10} {_swatch(c.error_border)}",
                f"  timestamp           {c.timestamp:<10} {_swatch(c.timestamp)}",
                f"  status_bar          {c.status_bar:<10} {_swatch(c.status_bar)}",
                "",
                "Change: /colors <role> <color>  e.g. /colors user white",
                "        /colors <key> <color>   e.g. /colors user_border #ff8800",
                "Reset:  /colors reset",
                "Roles:  user, assistant, system, error, tool, thinking, timestamp",
                "Colors: white, gray, cyan, red, green, blue, yellow, magenta, orange, dim, #RRGGBB",
            ]
            self._add_system_message("\n".join(lines))
            return

        if arg == "reset":
            self._prefs.colors = ColorPreferences()
            save_colors(self._prefs.colors)
            self._apply_theme_to_all_widgets()
            self._add_system_message("Colors reset to defaults.")
            return

        # Parse: key value
        tokens = arg.split(None, 1)
        if len(tokens) != 2:
            self._add_system_message(
                "Usage: /colors <role> <color>  e.g. /colors user white\n"
                "       /colors <key> <color>   e.g. /colors user_border #ff8800\n"
                "       /colors reset           Restore defaults\n"
                "Roles: user, assistant, system, error, tool, thinking, timestamp\n"
                "Colors: white, gray, cyan, red, green, blue, yellow, magenta, orange, dim, #RRGGBB"
            )
            return

        key, value = tokens
        # Resolve role shortcuts (e.g. "user" -> "user_text")
        key = self._COLOR_ROLE_ALIASES.get(key, key)

        if not hasattr(self._prefs.colors, key):
            aliases = ", ".join(sorted(self._COLOR_ROLE_ALIASES.keys()))
            valid = ", ".join(f.name for f in fields(ColorPreferences))
            self._add_system_message(
                f"Unknown color key '{key}'.\n"
                f"Role shortcuts: {aliases}\n"
                f"All keys: {valid}"
            )
            return

        # Resolve color: accept named colors (white, gray, cyan...) or hex (#RRGGBB)
        resolved = resolve_color(value)
        if resolved is None:
            names = ", ".join(sorted(COLOR_NAMES.keys()))
            self._add_system_message(
                f"Unknown color '{value}'.\n"
                f"Use a color name ({names})\n"
                f"or a hex code (#RRGGBB)."
            )
            return

        setattr(self._prefs.colors, key, resolved)
        save_colors(self._prefs.colors)
        self._apply_theme_to_all_widgets()
        self._add_system_message(
            f"Set {key} to [{resolved}]\u2588\u2588\u2588\u2588[/] {resolved}"
        )

    # ------------------------------------------------------------------
    # Export formatters
    # ------------------------------------------------------------------

    def _export_markdown(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as markdown."""
        lines = ["# Amplifier Chat Export", ""]
        if self._session_title:
            lines.append(f"**Session:** {self._session_title}")
        lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Messages:** {len(messages)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for role, content, _widget in messages:
            if role == "user":
                lines.append("## You")
            elif role == "assistant":
                lines.append("## Assistant")
            elif role == "system":
                lines.append("## System")
            else:
                lines.append(f"## {role.title()}")
            lines.append("")
            lines.append(content)
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*Exported from Amplifier TUI*")
        return "\n".join(lines)

    def _export_text(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as plain text."""
        lines: list[str] = []
        for role, content, _widget in messages:
            label = {"user": "You", "assistant": "AI", "system": "System"}.get(
                role, role
            )
            lines.append(f"[{label}]")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    def _export_json(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as JSON."""
        data = {
            "session_title": self._session_title or "",
            "exported_at": datetime.now().isoformat(),
            "message_count": len(messages),
            "messages": [
                {"role": role, "content": content}
                for role, content, _widget in messages
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # /export command
    # ------------------------------------------------------------------

    def _cmd_export(self, text: str) -> None:
        """Export the current chat to markdown, plain text, or JSON."""
        # text is the full command, e.g. "/export md" or "/export myfile.json"
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not self._search_messages:
            self._add_system_message("No messages to export")
            return

        # Determine format and filename
        fmt = "md"
        filename = ""

        if arg in ("md", "markdown"):
            fmt = "md"
        elif arg in ("txt", "text"):
            fmt = "txt"
        elif arg in ("json",):
            fmt = "json"
        elif arg:
            filename = arg
            if arg.endswith(".json"):
                fmt = "json"
            elif arg.endswith(".txt"):
                fmt = "txt"
            else:
                fmt = "md"

        # Auto-generate filename if not specified
        if not filename:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"amplifier-chat-{ts}.{fmt}"
        elif not filename.endswith(f".{fmt}"):
            filename = f"{filename}.{fmt}"

        # Generate content
        if fmt == "json":
            content = self._export_json(self._search_messages)
        elif fmt == "txt":
            content = self._export_text(self._search_messages)
        else:
            content = self._export_markdown(self._search_messages)

        # Write file
        out_path = Path(filename).expanduser()
        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
        out_path = out_path.resolve()

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            size = out_path.stat().st_size
            size_str = f"{size:,} bytes" if size < 1024 else f"{size / 1024:.1f} KB"
            self._add_system_message(
                f"Exported {len(self._search_messages)} messages to {out_path}\n"
                f"Format: {fmt.upper()}, Size: {size_str}"
            )
        except OSError as e:
            self._add_system_message(f"Export failed: {e}")

    def _cmd_title(self, text: str) -> None:
        """View or set the session title."""
        text = text.strip()

        if not text:
            # Show current title
            if self._session_title:
                self._add_system_message(f"Session title: {self._session_title}")
            else:
                self._add_system_message(
                    "No session title set (auto-generates from first message)"
                )
            return

        if text == "clear":
            self._session_title = ""
            self.sub_title = ""
            self._save_session_title()
            self._update_breadcrumb()
            self._add_system_message("Session title cleared")
            return

        # Set custom title (max 80 chars for manual titles)
        self._session_title = text[:80]
        self._apply_session_title()
        self._add_system_message(f"Session title set: {self._session_title}")

    def _cmd_rename(self, text: str) -> None:
        """Rename the current session in the sidebar."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        sid = getattr(sm, "session_id", None) if sm else None
        if not sid:
            self._add_system_message("No active session to rename.")
            return

        parts = text.strip().split(None, 1)
        if len(parts) < 2:
            # No argument: show current name
            custom_names = self._load_session_names()
            current = custom_names.get(sid)
            if current:
                self._add_system_message(f'Session name: "{current}"')
            else:
                self._add_system_message(
                    f"Session {sid[:8]} has no custom name.\n"
                    "Usage: /rename My Custom Name"
                )
            return

        new_name = parts[1].strip()
        if not new_name:
            self._add_system_message("Usage: /rename My Custom Name")
            return

        try:
            self._save_session_name(sid, new_name)
        except Exception as e:
            self._add_system_message(f"Failed to save name: {e}")
            return

        # Refresh sidebar if it has data loaded
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        self._add_system_message(f'Session renamed to "{new_name}"')
        self._update_breadcrumb()

    def _cmd_pin_session(self, text: str) -> None:
        """Pin or unpin a session so it appears at the top of the sidebar."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        sid = getattr(sm, "session_id", None) if sm else None
        if not sid:
            self._add_system_message("No active session to pin.")
            return

        # Toggle pin state
        if sid in self._pinned_sessions:
            self._pinned_sessions.discard(sid)
            self._save_pinned_sessions()
            verb = "unpinned"
        else:
            self._pinned_sessions.add(sid)
            self._save_pinned_sessions()
            verb = "pinned"

        # Refresh sidebar if it has data loaded
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        short = sid[:8]
        if verb == "pinned":
            self._add_system_message(
                f"Session {short} pinned (will appear at top of sidebar)."
            )
        else:
            self._add_system_message(f"Session {short} unpinned.")

    # ── Message Pin Commands ─────────────────────────────────────

    def _cmd_pin_msg(self, text: str) -> None:
        """Pin a message for quick recall.

        /pin          – pin last assistant message
        /pin <N>      – pin message number N (1-based)
        /pin clear    – clear all pins
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg.lower() == "clear":
            self._message_pins = []
            self._save_message_pins()
            self._add_system_message("All message pins cleared.")
            return

        if not arg:
            # Pin last assistant message
            for i in range(len(self._search_messages) - 1, -1, -1):
                role, content, _widget = self._search_messages[i]
                if role == "assistant":
                    self._add_message_pin(i, content)
                    return
            self._add_system_message("No assistant message to pin.")
            return

        if arg.isdigit():
            idx = int(arg) - 1  # 1-based for user
            if 0 <= idx < len(self._search_messages):
                _role, content, _widget = self._search_messages[idx]
                self._add_message_pin(idx, content)
            else:
                total = len(self._search_messages)
                self._add_system_message(f"Message {arg} not found (valid: 1-{total})")
            return

        self._add_system_message(
            "Usage: /pin [N] | /pin clear\n"
            "  /pin        Pin last AI message\n"
            "  /pin <N>    Pin message number N\n"
            "  /pin clear  Clear all pins"
        )

    def _cmd_pins(self, text: str) -> None:
        """List all pinned messages."""
        if not self._message_pins:
            self._add_system_message("No pinned messages. Use /pin to pin one.")
            return

        lines = ["\U0001f4cc Pinned messages:"]
        total = len(self._search_messages)
        for i, pin in enumerate(self._message_pins, 1):
            idx = pin["index"]
            if idx < total:
                role = self._search_messages[idx][0]
            else:
                role = "?"
            label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(role, role)
            lines.append(f"  #{i} [{label} msg {idx + 1}]: {pin['preview']}")
        lines.append("")
        lines.append("Use /unpin <N> to remove, /pin clear to clear all")
        self._add_system_message("\n".join(lines))

    def _cmd_unpin(self, text: str) -> None:
        """Remove a message pin by its pin number."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg or not arg.isdigit():
            self._add_system_message("Usage: /unpin <pin-number>")
            return

        n = int(arg)
        if 1 <= n <= len(self._message_pins):
            removed = self._message_pins.pop(n - 1)
            self._save_message_pins()
            preview = removed["preview"][:40]
            self._add_system_message(f"Unpinned #{n}: {preview}...")
        else:
            total = len(self._message_pins)
            if total == 0:
                self._add_system_message("No pins to remove.")
            else:
                self._add_system_message(f"Pin #{n} not found (valid: 1-{total})")

    _SORT_MODES = ("date", "name", "project")

    def _cmd_sort(self, text: str) -> None:
        """Show or change the session sort order in the sidebar."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if not arg:
            current = getattr(self._prefs, "session_sort", "date")
            self._add_system_message(
                f"Session sort: {current}\n"
                f"Available: {', '.join(self._SORT_MODES)}\n"
                f"Usage: /sort <mode>"
            )
            return

        if arg not in self._SORT_MODES:
            self._add_system_message(
                f"Unknown sort mode '{arg}'.\nAvailable: {', '.join(self._SORT_MODES)}"
            )
            return

        self._prefs.session_sort = arg
        save_session_sort(arg)

        # Refresh sidebar if it has data loaded
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        self._add_system_message(f"Sessions sorted by: {arg}")

    def _cmd_delete(self, text: str) -> None:
        """Delete a session with two-step confirmation."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # Handle confirmation
        if arg == "confirm" and self._pending_delete:
            session_id = self._pending_delete
            self._pending_delete = None
            self._execute_session_delete(session_id)
            return

        # Handle cancellation
        if arg == "cancel":
            self._pending_delete = None
            self._add_system_message("Delete cancelled.")
            return

        # Determine which session to delete
        if arg and arg not in ("confirm", "cancel"):
            session_id = arg
        elif self.session_manager and getattr(self.session_manager, "session_id", None):
            session_id = self.session_manager.session_id
        else:
            self._add_system_message("No active session to delete.")
            return

        # Set up confirmation
        self._pending_delete = session_id
        short_id = session_id[:12] if session_id else "unknown"
        self._add_system_message(
            f"Delete session {short_id}...?\n"
            "Type /delete confirm to proceed or /delete cancel to abort."
        )

    def _execute_session_delete(self, session_id: str) -> None:
        """Delete session files from disk and update UI."""
        short_id = session_id[:12]

        # Find the session directory on disk
        session_dir = self._find_session_dir(session_id)

        # If this is the currently loaded session, clear it first
        is_current = (
            self.session_manager
            and getattr(self.session_manager, "session_id", None) == session_id
        )
        if is_current and self.session_manager:
            self.session_manager.session = None
            self.session_manager.session_id = None
            self.session_manager.reset_usage()

        # Delete session files from disk
        if session_dir and session_dir.exists():
            try:
                shutil.rmtree(session_dir)
            except OSError as e:
                self._add_system_message(f"Failed to delete session files: {e}")
                return
        else:
            self._add_system_message(
                f"Session {short_id}... files not found on disk (already deleted?)."
            )

        # Remove from cached session list
        self._session_list_data = [
            s for s in self._session_list_data if s["session_id"] != session_id
        ]

        # Remove custom name, pin state, and draft if any
        self._remove_session_name(session_id)
        self._remove_pinned_session(session_id)
        # Clean up draft for deleted session
        try:
            drafts = self._load_drafts()
            if session_id in drafts:
                del drafts[session_id]
                self.DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
                self.DRAFTS_FILE.write_text(json.dumps(drafts, indent=2))
        except Exception:
            pass

        # Refresh sidebar
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        # Reset UI to a fresh state
        self._reset_for_new_session()

        self._add_system_message(f"Session {short_id}... deleted.")

    def _find_session_dir(self, session_id: str) -> Path | None:
        """Find the directory for a session by searching all projects."""
        sessions_dir = Path.home() / ".amplifier" / "projects"
        if not sessions_dir.exists():
            return None

        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / "sessions" / session_id
            if candidate.is_dir():
                return candidate

        return None

    def _remove_session_name(self, session_id: str) -> None:
        """Remove a custom session name from the JSON file."""
        try:
            names = self._load_session_names()
            if session_id in names:
                del names[session_id]
                self.SESSION_NAMES_FILE.write_text(json.dumps(names, indent=2))
        except Exception:
            pass

    # ── Bookmark Commands ─────────────────────────────────────────────

    def action_bookmark_last(self) -> None:
        """Bookmark the last assistant message (Ctrl+M)."""
        self._cmd_bookmark("/bookmark")

    def _cmd_bookmark(self, text: str) -> None:
        """Bookmark the last assistant message with an optional label."""
        sid = self._get_session_id()
        if not sid:
            self._add_system_message("No active session — send a message first.")
            return

        # Find the last assistant message widget
        assistant_widgets = [
            w
            for w in self.query(".assistant-message")
            if isinstance(w, AssistantMessage)
        ]
        if not assistant_widgets:
            self._add_system_message("No assistant message to bookmark.")
            return

        target = assistant_widgets[-1]
        msg_idx = getattr(target, "msg_index", None)
        if msg_idx is None:
            self._add_system_message("Cannot bookmark this message.")
            return

        # Check if already bookmarked
        for bm in self._session_bookmarks:
            if bm["message_index"] == msg_idx:
                self._add_system_message(f"Already bookmarked: {bm['label']}")
                return

        # Parse optional label from command text
        parts = text.strip().split(None, 1)
        label = parts[1].strip() if len(parts) > 1 else None

        # Build preview from the message content
        preview = self._last_assistant_text or ""
        for line in preview.split("\n"):
            line = line.strip()
            if line:
                preview = line
                break
        preview = preview[:80]

        bookmark = {
            "message_index": msg_idx,
            "label": label or f"Bookmark {len(self._session_bookmarks) + 1}",
            "timestamp": datetime.now().strftime("%H:%M"),
            "preview": preview,
        }

        # Save and apply visual
        self._save_bookmark(sid, bookmark)
        self._session_bookmarks.append(bookmark)
        target.add_class("bookmarked")

        self._add_system_message(f"Bookmarked: {bookmark['label']}")

    def _cmd_bookmarks(self, text: str) -> None:
        """List bookmarks or jump to a specific bookmark by number."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not self._session_bookmarks:
            self._add_system_message("No bookmarks in this session.")
            return

        # Jump to bookmark by number
        if arg.isdigit():
            num = int(arg)
            if num < 1 or num > len(self._session_bookmarks):
                self._add_system_message(
                    f"Bookmark {num} not found. "
                    f"Valid range: 1-{len(self._session_bookmarks)}"
                )
                return
            bm = self._session_bookmarks[num - 1]
            target_idx = bm["message_index"]
            for widget in self.query(".assistant-message"):
                if getattr(widget, "msg_index", None) == target_idx:
                    widget.scroll_visible()
                    self._add_system_message(f"Jumped to bookmark {num}: {bm['label']}")
                    return
            self._add_system_message(
                f"Bookmark {num} widget not found (message may have been cleared)."
            )
            return

        # List all bookmarks
        lines = ["Bookmarks:"]
        for i, bm in enumerate(self._session_bookmarks, 1):
            lines.append(f"  {i}. [{bm['timestamp']}] {bm['label']}")
            if bm.get("preview"):
                prev = bm["preview"][:60]
                if len(bm["preview"]) > 60:
                    prev += "..."
                lines.append(f"     {prev}")
        lines.append("")
        lines.append("Jump to a bookmark: /bookmarks <number>")

        self._add_system_message("\n".join(lines))

    # ── Message Display ─────────────────────────────────────────

    @staticmethod
    def _format_timestamp(dt: datetime) -> str:
        """Format a datetime for display.

        Returns ``"HH:MM"`` for today's messages or ``"Feb 5 14:32"`` for
        older ones so users can orient themselves in long conversations.
        """
        today = datetime.now(tz=dt.tzinfo).date()
        if dt.date() == today:
            return dt.strftime("%H:%M")
        # Non-zero-padded day: "Feb 5 14:32"
        return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%H:%M')}"

    def _make_timestamp(
        self,
        dt: datetime | None = None,
        *,
        fallback_now: bool = True,
    ) -> Static | None:
        """Create a dim right-aligned timestamp label, or *None* if disabled.

        Parameters
        ----------
        dt:
            The datetime to display.  When *None* and *fallback_now* is True
            (the default for live messages), ``datetime.now()`` is used.
        fallback_now:
            If *False* and *dt* is None (e.g. a replayed transcript with no
            stored timestamp), skip the widget entirely rather than showing an
            incorrect "now" time.
        """
        if not self._prefs.display.show_timestamps:
            return None
        if dt is None:
            if not fallback_now:
                return None
            dt = datetime.now()
        widget = Static(self._format_timestamp(dt), classes="msg-timestamp")
        widget.styles.color = self._prefs.colors.timestamp
        return widget

    @staticmethod
    def _extract_transcript_timestamp(msg: dict) -> datetime | None:
        """Extract a datetime from a transcript message dict.

        Looks for common timestamp keys (``timestamp``, ``created_at``,
        ``ts``) and returns a :class:`datetime` so the caller can decide
        on display formatting (today vs. older).
        """
        for key in ("timestamp", "created_at", "ts"):
            val = msg.get(key)
            if val:
                try:
                    return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
        return None

    def _style_user(self, widget: Static) -> None:
        """Apply preference colors to a user message."""
        c = self._prefs.colors
        widget.styles.color = c.user_text
        widget.styles.border_left = ("thick", c.user_border)

    def _style_assistant(self, widget: Markdown) -> None:
        """Apply preference colors to an assistant message."""
        c = self._prefs.colors
        widget.styles.color = c.assistant_text
        widget.styles.border_left = ("wide", c.assistant_border)

    def _style_thinking(self, container: Collapsible, inner: Static) -> None:
        """Apply preference colors to a thinking block."""
        c = self._prefs.colors
        inner.styles.color = c.thinking_text
        container.styles.border_left = ("wide", c.thinking_border)
        container.styles.background = c.thinking_background

    def _style_tool(self, container: Collapsible, inner: Static) -> None:
        """Apply preference colors to a tool use block."""
        c = self._prefs.colors
        inner.styles.color = c.tool_text
        container.styles.border_left = ("wide", c.tool_border)
        container.styles.background = c.tool_background

    @staticmethod
    def _tool_title(tool_name: str, tool_input: dict | str | None, result: str) -> str:
        """Build a descriptive collapsible title for a tool block.

        Format: ``tool_name: key_arg (N lines)``
        """
        # Extract the most useful single argument for the summary line.
        summary = ""
        if tool_input:
            if isinstance(tool_input, dict):
                for key in (
                    "command",
                    "query",
                    "path",
                    "file_path",
                    "pattern",
                    "url",
                    "instruction",
                    "agent",
                    "operation",
                    "action",
                    "skill_name",
                    "content",
                ):
                    if key in tool_input:
                        summary = str(tool_input[key])
                        break
                if not summary:
                    summary = json.dumps(tool_input)
            else:
                summary = str(tool_input)
            # First line only, capped at 80 chars.
            summary = summary.split("\n")[0]
            if len(summary) > 80:
                summary = summary[:77] + "..."

        # Count lines in the result.
        line_count = len(result.strip().split("\n")) if result.strip() else 0

        # Assemble: "▶ bash: ls -la (12 lines)"
        title = f"\u25b6 {tool_name}"
        if summary:
            title += f": {summary}"
        if line_count > 0:
            title += f" ({line_count} line{'s' if line_count != 1 else ''})"
        return title

    def _style_system(self, widget: Static) -> None:
        """Apply preference colors to a system message."""
        c = self._prefs.colors
        widget.styles.color = c.system_text
        widget.styles.border_left = ("thick", c.system_border)

    def _style_error(self, widget: Static) -> None:
        """Apply preference colors to an error message."""
        c = self._prefs.colors
        widget.styles.color = c.error_text
        widget.styles.border_left = ("wide", c.error_border)

    def _maybe_add_fold_toggle(self, widget: Static, content: str) -> None:
        """Add a fold toggle after a long message for expand/collapse."""
        line_count = content.count("\n") + 1
        if line_count <= self._fold_threshold:
            return
        chat_view = self._active_chat_view()
        widget.add_class("folded")
        toggle = FoldToggle(widget, line_count, folded=True)
        chat_view.mount(toggle, after=widget)

    def _add_user_message(self, text: str, ts: datetime | None = None) -> None:
        chat_view = self._active_chat_view()
        ts_widget = self._make_timestamp(ts)
        if ts_widget:
            chat_view.mount(ts_widget)
        msg = UserMessage(text)
        chat_view.mount(msg)
        self._style_user(msg)
        self._scroll_if_auto(msg)
        self._search_messages.append(("user", text, msg))
        self._maybe_add_fold_toggle(msg, text)
        words = self._count_words(text)
        self._total_words += words
        self._user_message_count += 1
        self._user_words += words
        self._update_word_count_display()
        self._update_token_display()

    def _add_assistant_message(self, text: str, ts: datetime | None = None) -> None:
        chat_view = self._active_chat_view()
        ts_widget = self._make_timestamp(ts)
        if ts_widget:
            chat_view.mount(ts_widget)
        msg = AssistantMessage(text)
        msg.msg_index = self._assistant_msg_index  # type: ignore[attr-defined]
        self._assistant_msg_index += 1
        chat_view.mount(msg)
        self._style_assistant(msg)
        self._scroll_if_auto(msg)
        self._last_assistant_text = text
        self._last_assistant_widget = msg
        self._search_messages.append(("assistant", text, msg))
        self._maybe_add_fold_toggle(msg, text)
        words = self._count_words(text)
        self._total_words += words
        self._assistant_message_count += 1
        self._assistant_words += words
        self._update_word_count_display()
        self._update_token_display()

    def _add_system_message(self, text: str, ts: datetime | None = None) -> None:
        """Display a system message (slash command output)."""
        chat_view = self._active_chat_view()
        ts_widget = self._make_timestamp(ts)
        if ts_widget:
            chat_view.mount(ts_widget)
        msg = SystemMessage(text)
        chat_view.mount(msg)
        self._style_system(msg)
        self._scroll_if_auto(msg)
        self._search_messages.append(("system", text, msg))

    def _add_thinking_block(self, text: str) -> None:
        chat_view = self._active_chat_view()
        # Show abbreviated preview, full text on expand
        preview = text.split("\n")[0][:55]
        if len(text) > 55:
            preview += "..."
        full_text = text[:800] + "..." if len(text) > 800 else text
        inner = Static(full_text, classes="thinking-text")
        collapsible = Collapsible(
            inner,
            title=f"\u25b6 Thinking: {preview}",
            collapsed=True,
            classes="thinking-block",
        )
        chat_view.mount(collapsible)
        self._style_thinking(collapsible, inner)

    def _add_tool_use(
        self,
        tool_name: str,
        tool_input: dict | str | None = None,
        result: str = "",
    ) -> None:
        self._tool_call_count += 1
        self._tool_usage[tool_name] = self._tool_usage.get(tool_name, 0) + 1
        chat_view = self._active_chat_view()

        detail_parts: list[str] = []
        if tool_input:
            input_str = (
                json.dumps(tool_input, indent=2)
                if isinstance(tool_input, dict)
                else str(tool_input)
            )
            if len(input_str) > 800:
                input_str = input_str[:800] + "..."
            detail_parts.append(f"Input:\n{input_str}")
        if result:
            r = result[:1500] + "..." if len(result) > 1500 else result
            detail_parts.append(f"Result:\n{r}")

        detail = "\n\n".join(detail_parts) if detail_parts else "(no details)"

        title = self._tool_title(tool_name, tool_input, result)
        inner = Static(detail, classes="tool-detail")
        collapsible = Collapsible(
            inner,
            title=title,
            collapsed=True,
        )
        collapsible.add_class("tool-use")
        chat_view.mount(collapsible)
        self._style_tool(collapsible, inner)
        self._scroll_if_auto(collapsible)

    def _show_error(self, error_text: str) -> None:
        chat_view = self._active_chat_view()
        msg = ErrorMessage(f"Error: {error_text}", classes="error-message")
        chat_view.mount(msg)
        self._style_error(msg)
        self._scroll_if_auto(msg)
        # Beep immediately on errors (no duration gate)
        self._notify_sound(event="error")

    # ── Processing State ────────────────────────────────────────

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _animate_spinner(self) -> None:
        """Timer callback: animate the processing indicator."""
        if not self.is_processing:
            return
        self._spinner_frame = (self._spinner_frame + 1) % len(self._SPINNER)
        frame = self._SPINNER[self._spinner_frame]
        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            label = self._processing_label or "Thinking"
            indicator.update(f" {frame} {label}...")
        except Exception:
            pass

    def _start_processing(self, label: str = "Thinking") -> None:
        self.is_processing = True
        self._got_stream_content = False
        self._processing_label = label
        self._processing_start_time = time.monotonic()
        self._tool_count_this_turn = 0
        inp = self.query_one("#chat-input", ChatInput)
        inp.disabled = True
        inp.add_class("disabled")

        chat_view = self._active_chat_view()
        frame = self._SPINNER[0]
        indicator = ProcessingIndicator(
            f" {frame} {label}...",
            classes="processing-indicator",
            id="processing-indicator",
        )
        chat_view.mount(indicator)
        self._scroll_if_auto(indicator)
        self._update_status(f"{label}...")

    def action_cancel_streaming(self) -> None:
        """Cancel in-progress streaming (Escape key).

        If we're not processing, this is a no-op so it doesn't interfere
        with other Escape uses (modals, search, etc.).
        """
        if not self.is_processing:
            return
        self._streaming_cancelled = True

        # Finalize whatever has been streamed so far
        if self._stream_widget and self._stream_accumulated_text:
            block_type = self._stream_block_type or "text"
            self._finalize_streaming_block(block_type, self._stream_accumulated_text)

        # Cancel running workers (send_message_worker)
        self.workers.cancel_group(self, "default")

        self._add_system_message("Generation cancelled.")
        self._finish_processing()

    def _finish_processing(self) -> None:
        if not self.is_processing:
            return  # Already finished (e.g. cancel + worker finally)
        self.is_processing = False
        self._processing_label = None
        self._tool_count_this_turn = 0
        self._streaming_cancelled = False
        self._stream_accumulated_text = ""
        # Clean up any leftover streaming state
        self._stream_widget = None
        self._stream_container = None
        self._stream_block_type = None
        inp = self.query_one("#chat-input", ChatInput)
        inp.disabled = False
        inp.remove_class("disabled")
        inp.focus()
        self._remove_processing_indicator()
        self._update_token_display()
        self._update_status("Ready")
        # Compute elapsed time once for both notification methods
        elapsed: float | None = None
        if self._processing_start_time is not None:
            elapsed = time.monotonic() - self._processing_start_time
            self._processing_start_time = None
            self._response_times.append(elapsed)
        self._maybe_send_notification(elapsed)
        self._notify_sound(elapsed)

    def _maybe_send_notification(self, elapsed: float | None = None) -> None:
        """Send a terminal notification if processing took long enough."""
        if elapsed is None:
            return
        nprefs = self._prefs.notifications
        if not nprefs.enabled:
            return
        if elapsed < nprefs.min_seconds:
            return
        self._send_terminal_notification(
            "Amplifier", f"Response ready ({elapsed:.0f}s)"
        )

    @staticmethod
    def _send_terminal_notification(title: str, body: str = "") -> None:
        """Send a terminal notification via OSC escape sequences.

        Uses multiple methods for broad terminal compatibility:
        - OSC 9: iTerm2, WezTerm, kitty
        - OSC 777: rxvt-unicode
        - BEL: universal fallback (triggers terminal bell / visual bell)

        Writes to sys.__stdout__ to bypass Textual's stdout capture.
        """
        out = sys.__stdout__
        if out is None:
            return
        try:
            out.write(f"\033]9;{title}: {body}\a")
            out.write(f"\033]777;notify;{title};{body}\a")
            out.write("\a")
            out.flush()
        except Exception:
            pass  # Don't crash if the terminal doesn't support these

    @staticmethod
    def _play_bell() -> None:
        """Write BEL character to the real terminal via *sys.__stdout__*.

        Textual captures ``sys.stdout``, so we use the original fd directly.
        """
        out = sys.__stdout__
        if out is None:
            return
        try:
            out.write("\a")
            out.flush()
        except Exception:
            pass

    def _notify_sound(
        self,
        elapsed: float | None = None,
        *,
        event: str = "response",
    ) -> None:
        """Play a terminal bell if notification sound is enabled for *event*.

        Uses ``_play_bell()`` (writes BEL to ``sys.__stdout__``) to bypass
        Textual's stdout capture.

        Parameters
        ----------
        elapsed:
            How long the operation took (seconds).  Used to suppress beeps for
            fast responses (below ``min_seconds``).
        event:
            ``"response"`` (default), ``"error"``, or ``"file_change"``.
            Each event type respects its own per-event toggle in preferences.
        """
        nprefs = self._prefs.notifications
        if not nprefs.sound_enabled:
            return
        # Per-event gating
        if event == "error" and not nprefs.sound_on_error:
            return
        if event == "file_change" and not nprefs.sound_on_file_change:
            return
        # Respect minimum duration — don't beep for instant responses
        if event == "response" and elapsed is not None and elapsed < nprefs.min_seconds:
            return
        self._play_bell()

    def _remove_processing_indicator(self) -> None:
        try:
            self.query_one("#processing-indicator").remove()
        except Exception:
            pass

    def _ensure_processing_indicator(self, label: str | None = None) -> None:
        """Ensure the processing indicator is visible with the given label.

        If the indicator widget exists, updates it in place.
        If it was removed (e.g. by streaming), re-mounts a fresh one.
        """
        if label is not None:
            self._processing_label = label
        display_label = self._processing_label or "Thinking"
        frame = self._SPINNER[self._spinner_frame % len(self._SPINNER)]
        text = f" {frame} {display_label}..."

        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            indicator.update(text)
        except Exception:
            if not self.is_processing:
                return
            chat_view = self._active_chat_view()
            indicator = ProcessingIndicator(
                text,
                classes="processing-indicator",
                id="processing-indicator",
            )
            chat_view.mount(indicator)
            self._scroll_if_auto(indicator)

    # ── Auto-scroll ──────────────────────────────────────────────────────────────

    def _scroll_if_auto(self, widget: Static | Collapsible) -> None:
        """Scroll widget into view only if auto-scroll is enabled."""
        if not self._auto_scroll:
            return
        widget.scroll_visible()

    def _update_scroll_indicator(self) -> None:
        """Update the status bar auto-scroll indicator."""
        label = "\u2195 ON" if self._auto_scroll else "\u2195 OFF"
        try:
            self.query_one("#status-scroll", Static).update(label)
        except Exception:
            pass

    def _update_vim_status(self) -> None:
        """Update the status bar vim mode indicator."""
        label = "[vim]" if self._prefs.display.vim_mode else ""
        try:
            self.query_one("#status-vim", Static).update(label)
        except Exception:
            pass

    def _check_smart_scroll_pause(self) -> None:
        """During streaming, auto-pause if user has scrolled up."""
        if not self._auto_scroll or not self.is_processing:
            return
        try:
            chat_view = self._active_chat_view()
            if chat_view.max_scroll_y > 0:
                distance_from_bottom = chat_view.max_scroll_y - chat_view.scroll_y
                if distance_from_bottom > 5:
                    self._auto_scroll = False
                    self._update_scroll_indicator()
        except Exception:
            pass

    # ── Status Bar ──────────────────────────────────────────────

    def _update_status(self, state: str = "Ready") -> None:
        try:
            if self._prefs.display.compact_mode:
                state = f"{state} [compact]"
            self.query_one("#status-state", Static).update(state)
        except Exception:
            pass

    @staticmethod
    def _format_token_count(count: int) -> str:
        """Format token count: 1234 -> '1.2k', 200000 -> '200k'."""
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 10_000:
            val = count / 1_000
            return f"{val:.0f}k" if val >= 100 else f"{val:.1f}k"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}k"
        return str(count)

    def _get_context_window(self) -> int:
        """Get context window size for the current model.

        Uses the provider-reported value when available, otherwise falls
        back to ``MODEL_CONTEXT_WINDOWS`` keyed by model name substring.
        """
        sm = self.session_manager
        if sm and sm.context_window > 0:
            return sm.context_window

        # Build a model string from whatever is available.
        model = ""
        if sm and sm.model_name:
            model = sm.model_name
        elif self._prefs.preferred_model:
            model = self._prefs.preferred_model

        if model:
            model_lower = model.lower()
            for key, size in MODEL_CONTEXT_WINDOWS.items():
                if key in model_lower:
                    return size

        return DEFAULT_CONTEXT_WINDOW

    def _update_token_display(self) -> None:
        """Update the status bar with current token usage and model info."""
        try:
            sm = self.session_manager
            parts: list[str] = []

            current_name = sm.model_name if sm else ""
            preferred = self._prefs.preferred_model

            if current_name:
                name = current_name
                if name.startswith("claude-"):
                    name = name[7:]
                parts.append(name)
            elif preferred:
                # No active session — show the preferred model as a hint
                pname = preferred
                if pname.startswith("claude-"):
                    pname = pname[7:]
                parts.append(f"[{pname}]")

            # Token usage with context-window percentage
            window = self._get_context_window()
            pct = 0.0

            # Prefer real API tokens; fall back to char-based estimate
            total = 0
            if sm:
                total = sm.total_input_tokens + sm.total_output_tokens
            if total == 0 and self._search_messages:
                total = sum(
                    len(content) // 4 for _role, content, _w in self._search_messages
                )

            if total > 0 and window > 0:
                used = self._format_token_count(total)
                cap = self._format_token_count(window)
                pct = min(100.0, total / window * 100)
                parts.append(f"~{used}/{cap} ({pct:.0f}%)")
            elif total > 0:
                parts.append(f"~{self._format_token_count(total)} tokens")

            widget = self.query_one("#status-model", Static)
            widget.update(" | ".join(parts) if parts else "")

            # Color-code by context usage percentage
            if pct > 80:
                widget.styles.color = "#ff4444"  # red
            elif pct > 50:
                widget.styles.color = "#ffaa00"  # yellow
            else:
                widget.styles.color = "#44aa44"  # green

            # Update the context fuel gauge bar (8 chars wide, █/░)
            ctx_widget = self.query_one("#status-context", Static)
            if pct > 0:
                filled = int(pct * 8 / 100)
                bar = "\u2588" * filled + "\u2591" * (8 - filled)
                ctx_widget.update(f"{bar} {pct:.0f}%")
                if pct > 80:
                    ctx_widget.styles.color = "#ff4444"  # red
                elif pct > 50:
                    ctx_widget.styles.color = "#ffaa00"  # yellow
                else:
                    ctx_widget.styles.color = "#44aa44"  # green
            else:
                ctx_widget.update("")
        except Exception:
            pass

    def _update_session_display(self) -> None:
        if self.session_manager and getattr(self.session_manager, "session_id", None):
            sid = self.session_manager.session_id[:8]
            self.query_one("#status-session", Static).update(f"Session: {sid}")
        else:
            self.query_one("#status-session", Static).update("No session")
        self._update_breadcrumb()

    # ── Breadcrumb Bar ──────────────────────────────────────

    def _update_breadcrumb(self) -> None:
        """Update the breadcrumb bar with project / session / model context."""
        try:
            breadcrumb = self.query_one("#breadcrumb-bar", Static)
        except Exception:
            return

        parts: list[str] = []

        # Project directory
        project_dir = os.getcwd()
        home = str(Path.home())
        if project_dir.startswith(home):
            project_dir = "~" + project_dir[len(home) :]
        # Show last 2 components for brevity if path is long
        segments = project_dir.split("/")
        if len(segments) > 3:
            project_dir = "…/" + "/".join(segments[-2:])
        parts.append(project_dir)

        # Session title > custom name > truncated ID
        sm = self.session_manager if hasattr(self, "session_manager") else None
        sid = getattr(sm, "session_id", None) if sm else None
        if sid:
            if self._session_title:
                label = self._session_title
                if len(label) > 30:
                    label = label[:27] + "..."
                parts.append(label)
            else:
                names = self._load_session_names()
                parts.append(names.get(sid, sid[:12]))

        # Model (shortened)
        model = getattr(sm, "model_name", "") if sm else ""
        if model:
            model = (
                model.replace("claude-", "")
                .replace("-20250514", "")
                .replace("-20241022", "")
                .replace("-latest", "")
            )
            parts.append(model)

        breadcrumb.update(" › ".join(parts))

    # ── Word Count ──────────────────────────────────────────────

    @staticmethod
    def _count_words(text: str) -> int:
        """Count words in a text string."""
        return len(text.split())

    def _update_word_count_display(self) -> None:
        """Update the status bar word count and reading time."""
        total = self._total_words
        if total >= 1000:
            word_str = f"{total / 1000:.1f}k words"
        else:
            word_str = f"{total} words"

        if total == 0:
            display = "0 words"
        else:
            minutes = max(1, total // 200)
            display = f"{word_str} · ~{minutes} min read"

        try:
            self.query_one("#status-wordcount", Static).update(display)
        except Exception:
            pass

    # ── Streaming Callbacks ─────────────────────────────────────

    def _setup_streaming_callbacks(self) -> None:
        """Wire session manager hooks to UI updates via call_from_thread.

        Supports three levels of streaming granularity:
        1. content_block:delta  - true token streaming (when orchestrator emits)
        2. content_block:start  - create widget early, remove spinner
        3. content_block:end    - finalize with complete text (always fires)
        """
        # Per-turn state captured by closures (reset each message send)
        accumulated = {"text": ""}
        last_update = {"t": 0.0}
        block_started = {"v": False}

        def on_block_start(block_type: str, block_index: int) -> None:
            accumulated["text"] = ""
            last_update["t"] = 0.0
            block_started["v"] = True
            self.call_from_thread(self._begin_streaming_block, block_type)

        def on_block_delta(block_type: str, delta: str) -> None:
            if self._streaming_cancelled:
                return
            accumulated["text"] += delta
            # Keep app-level accumulator in sync for cancel-recovery
            self._stream_accumulated_text = accumulated["text"]
            now = time.monotonic()
            if now - last_update["t"] >= 0.05:  # Throttle: 50ms minimum
                last_update["t"] = now
                snapshot = accumulated["text"]
                self.call_from_thread(
                    self._update_streaming_content, block_type, snapshot
                )

        def on_block_end(block_type: str, text: str) -> None:
            self._got_stream_content = True
            if block_started["v"]:
                # Streaming widget exists - finalize it with complete text
                block_started["v"] = False
                accumulated["text"] = ""
                self.call_from_thread(self._finalize_streaming_block, block_type, text)
            else:
                # No start event received - direct display (fallback)
                self.call_from_thread(self._remove_processing_indicator)
                if block_type in ("thinking", "reasoning"):
                    self.call_from_thread(self._add_thinking_block, text)
                else:
                    self.call_from_thread(self._add_assistant_message, text)

        def on_tool_start(name: str, tool_input: dict) -> None:
            self._tool_count_this_turn += 1
            label = _get_tool_label(name, tool_input)
            bare = label.rstrip(".")
            # Append raw tool name for extra detail
            bare = f"{bare} ({name})"
            # Show sequential counter when this isn't the first tool
            if self._tool_count_this_turn > 1:
                bare = f"{bare} [#{self._tool_count_this_turn}]"
            self._processing_label = bare
            self.call_from_thread(self._ensure_processing_indicator, bare)
            self.call_from_thread(self._update_status, label)

        def on_tool_end(name: str, tool_input: dict, result: str) -> None:
            self._processing_label = "Thinking"
            self.call_from_thread(self._add_tool_use, name, tool_input, result)
            self.call_from_thread(self._ensure_processing_indicator, "Thinking")
            self.call_from_thread(self._update_status, "Thinking...")

        def on_usage():
            self.call_from_thread(self._update_token_display)

        self.session_manager.on_content_block_start = on_block_start
        self.session_manager.on_content_block_delta = on_block_delta
        self.session_manager.on_content_block_end = on_block_end
        self.session_manager.on_tool_pre = on_tool_start
        self.session_manager.on_tool_post = on_tool_end
        self.session_manager.on_usage_update = on_usage

    # ── Streaming Display ─────────────────────────────────────────

    def _begin_streaming_block(self, block_type: str) -> None:
        """Create an empty widget to stream content into.

        Called on content_block:start. Removes the spinner immediately
        so the user knows content is arriving.
        """
        self._remove_processing_indicator()
        chat_view = self._active_chat_view()

        if block_type in ("thinking", "reasoning"):
            inner = Static("\u258d", classes="thinking-text")
            container = Collapsible(
                inner,
                title="\u25b6 Thinking\u2026",
                collapsed=False,
                classes="thinking-block",
            )
            chat_view.mount(container)
            self._style_thinking(container, inner)
            self._stream_widget = inner
            self._stream_container = container
        else:
            widget = Static(
                "\u258d", classes="chat-message assistant-message streaming-content"
            )
            chat_view.mount(widget)
            c = self._prefs.colors
            widget.styles.color = c.assistant_text
            widget.styles.border_left = ("wide", c.assistant_border)
            self._scroll_if_auto(widget)
            self._stream_widget = widget
            self._stream_container = None

        self._stream_block_type = block_type
        self._stream_accumulated_text = ""
        self._update_status("Streaming\u2026")

    def _update_streaming_content(self, block_type: str, text: str) -> None:
        """Update the streaming widget with accumulated text so far.

        Called on content_block:delta (throttled to ~50ms). Shows a
        cursor character at the end to indicate more content is coming.

        For text blocks, renders progressively through Rich Markdown so
        the user sees formatted output (headings, code, lists) as it
        streams in.  Falls back to plain text on any rendering error.
        """
        if not self._stream_widget:
            return

        display_text = text + " \u258d"

        if block_type not in ("thinking", "reasoning"):
            try:
                from rich.markdown import Markdown as RichMarkdown

                self._stream_widget.update(RichMarkdown(display_text))
            except Exception:
                self._stream_widget.update(display_text)
        else:
            self._stream_widget.update(display_text)

        self._check_smart_scroll_pause()
        self._scroll_if_auto(self._stream_widget)

    def _finalize_streaming_block(self, block_type: str, text: str) -> None:
        """Replace the streaming Static with the final rendered widget.

        Called on content_block:end. For text blocks, swaps the fast
        Static with a proper Markdown widget for rich rendering.
        For thinking blocks, collapses and sets the preview title.
        """
        chat_view = self._active_chat_view()

        if block_type in ("thinking", "reasoning"):
            full_text = text[:800] + "\u2026" if len(text) > 800 else text
            if self._stream_widget:
                self._stream_widget.update(full_text)
            if self._stream_container:
                preview = text.split("\n")[0][:55]
                if len(text) > 55:
                    preview += "\u2026"
                self._stream_container.title = f"\u25b6 Thinking: {preview}"
                self._stream_container.collapsed = True
        else:
            self._last_assistant_text = text
            old = self._stream_widget
            if old:
                msg = AssistantMessage(text)
                msg.msg_index = self._assistant_msg_index  # type: ignore[attr-defined]
                self._assistant_msg_index += 1
                ts_widget = self._make_timestamp()
                if ts_widget:
                    chat_view.mount(ts_widget, before=old)
                chat_view.mount(msg, before=old)
                self._style_assistant(msg)
                old.remove()
                self._scroll_if_auto(msg)
                self._last_assistant_widget = msg
                self._search_messages.append(("assistant", text, msg))
                self._maybe_add_fold_toggle(msg, text)
                words = self._count_words(text)
                self._total_words += words
                self._assistant_message_count += 1
                self._assistant_words += words
                self._update_word_count_display()
            else:
                self._add_assistant_message(text)

        # Reset streaming state for next block
        self._stream_widget = None
        self._stream_container = None
        self._stream_block_type = None

    # ── Workers (background execution) ──────────────────────────

    @work(thread=True)
    async def _send_message_worker(self, message: str) -> None:
        """Send a message to Amplifier in a background thread."""
        try:
            # Auto-create session on first message
            if not self.session_manager.session:
                self.call_from_thread(self._update_status, "Starting session...")
                model = self._prefs.preferred_model or ""
                await self.session_manager.start_new_session(
                    model_override=model,
                )
                self.call_from_thread(self._update_session_display)
                self.call_from_thread(self._update_token_display)

            # Auto-title from first user message
            if not self._session_title:
                self._session_title = self._extract_title(message)
                self.call_from_thread(self._apply_session_title)

            if self._prefs.display.streaming_enabled:
                self._setup_streaming_callbacks()
            self.call_from_thread(self._update_status, "Thinking...")

            response = await self.session_manager.send_message(message)

            if self._streaming_cancelled:
                return  # Already finalized in action_cancel_streaming

            # Fallback: if no hooks fired, show the full response
            if not self._got_stream_content and response:
                self.call_from_thread(self._add_assistant_message, response)

        except Exception as e:
            if self._streaming_cancelled:
                return  # Suppress errors from cancelled workers
            self.call_from_thread(self._show_error, str(e))
        finally:
            self.call_from_thread(self._finish_processing)

    @work(thread=True)
    async def _resume_session_worker(self, session_id: str) -> None:
        """Resume a session in a background thread."""
        self.call_from_thread(self._clear_welcome)
        self.call_from_thread(self._update_status, "Loading session...")

        try:
            # Handle "most recent" shortcut
            if session_id == "__most_recent__":
                session_id = self.session_manager._find_most_recent_session()

            # Display the transcript in the chat view
            transcript_path = self.session_manager.get_session_transcript_path(
                session_id
            )
            self.call_from_thread(self._display_transcript, transcript_path)

            # Resume the actual session (restores LLM context)
            model = self._prefs.preferred_model or ""
            await self.session_manager.resume_session(session_id, model_override=model)

            # Restore session title
            title = self._load_session_title_for(session_id)
            if title:
                self._session_title = title
                self.call_from_thread(self._apply_session_title)

            self.call_from_thread(self._update_session_display)
            self.call_from_thread(self._update_token_display)
            self.call_from_thread(self._update_status, "Ready")

            # Restore any saved draft for this session
            if not self.initial_prompt:
                self.call_from_thread(self._restore_draft)

            # Handle initial prompt if provided
            if self.initial_prompt:
                prompt = self.initial_prompt
                self.initial_prompt = None
                self.call_from_thread(self._add_user_message, prompt)
                self.call_from_thread(self._start_processing)
                if self._prefs.display.streaming_enabled:
                    self._setup_streaming_callbacks()
                response = await self.session_manager.send_message(prompt)
                if not self._got_stream_content and response:
                    self.call_from_thread(self._add_assistant_message, response)
                self.call_from_thread(self._finish_processing)

        except Exception as e:
            self.call_from_thread(self._show_error, f"Failed to resume: {e}")
            self.call_from_thread(self._update_status, "Error")

    # ── Transcript Display ──────────────────────────────────────

    def _display_transcript(self, transcript_path: Path) -> None:
        """Render a session transcript in the chat view."""
        from .transcript_loader import load_transcript, parse_message_blocks

        chat_view = self._active_chat_view()

        # Clear existing content
        for child in list(chat_view.children):
            child.remove()

        self._total_words = 0
        self._user_message_count = 0
        self._assistant_message_count = 0
        self._tool_call_count = 0
        self._user_words = 0
        self._assistant_words = 0
        self._response_times = []
        self._tool_usage = {}
        self._assistant_msg_index = 0
        self._last_assistant_widget = None
        self._session_start_time = time.monotonic()
        self._search_messages = []
        tool_results: dict[str, str] = {}

        for msg in load_transcript(transcript_path):
            msg_ts = self._extract_transcript_timestamp(msg)
            ts_shown = False
            blocks = parse_message_blocks(msg)
            for block in blocks:
                if block.kind == "user":
                    if not ts_shown:
                        ts_widget = self._make_timestamp(msg_ts, fallback_now=False)
                        if ts_widget:
                            chat_view.mount(ts_widget)
                        ts_shown = True
                    widget = UserMessage(block.content)
                    chat_view.mount(widget)
                    self._style_user(widget)
                    self._search_messages.append(("user", block.content, widget))
                    self._maybe_add_fold_toggle(widget, block.content)
                    words = self._count_words(block.content)
                    self._total_words += words
                    self._user_message_count += 1
                    self._user_words += words

                elif block.kind == "text":
                    if not ts_shown:
                        ts_widget = self._make_timestamp(msg_ts, fallback_now=False)
                        if ts_widget:
                            chat_view.mount(ts_widget)
                        ts_shown = True
                    self._last_assistant_text = block.content
                    widget = AssistantMessage(block.content)
                    widget.msg_index = self._assistant_msg_index  # type: ignore[attr-defined]
                    self._assistant_msg_index += 1
                    self._last_assistant_widget = widget
                    chat_view.mount(widget)
                    self._style_assistant(widget)
                    self._search_messages.append(("assistant", block.content, widget))
                    self._maybe_add_fold_toggle(widget, block.content)
                    words = self._count_words(block.content)
                    self._total_words += words
                    self._assistant_message_count += 1
                    self._assistant_words += words

                elif block.kind == "thinking":
                    preview = block.content.split("\n")[0][:55]
                    if len(block.content) > 55:
                        preview += "..."
                    full_text = (
                        block.content[:800] + "..."
                        if len(block.content) > 800
                        else block.content
                    )
                    inner = Static(full_text, classes="thinking-text")
                    collapsible = Collapsible(
                        inner,
                        title=f"\u25b6 Thinking: {preview}",
                        collapsed=True,
                        classes="thinking-block",
                    )
                    chat_view.mount(collapsible)
                    self._style_thinking(collapsible, inner)

                elif block.kind == "tool_use":
                    result = tool_results.get(block.tool_id, "")
                    self._add_tool_use(block.tool_name, block.tool_input, result)

                elif block.kind == "tool_result":
                    tool_results[block.tool_id] = block.content

        self._update_word_count_display()

        # Restore bookmarks for this session
        self._session_bookmarks = self._load_session_bookmarks()
        self._apply_bookmark_classes()

        # Restore message pins for this session
        self._message_pins = self._load_message_pins()

        # Restore saved references for this session
        self._session_refs = self._load_session_refs()

        chat_view.scroll_end(animate=False)


# ── Entry Point ─────────────────────────────────────────────────────


def run_app(
    resume_session_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Run the Amplifier TUI application."""
    app = AmplifierChicApp(
        resume_session_id=resume_session_id,
        initial_prompt=initial_prompt,
    )
    app.run()
