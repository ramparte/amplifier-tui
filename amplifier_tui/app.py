"""Main Amplifier TUI application."""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
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
    ColorPreferences,
    THEMES,
    load_preferences,
    save_colors,
    save_notification_sound,
    save_preferred_model,
    save_session_sort,
    save_show_timestamps,
    save_theme_name,
    save_word_wrap,
)
from .theme import CHIC_THEME

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
    "/draft",
    "/tokens",
    "/sort",
    "/edit",
    "/wrap",
    "/alias",
    "/info",
    "/fold",
)

# Known context window sizes (tokens) for popular models.
# Used as fallback when the provider doesn't report context_window.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet": 200_000,
    "claude-haiku": 200_000,
    "claude-opus": 200_000,
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4": 128_000,
    "gpt-3.5": 16_000,
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

    # -- Key handling --------------------------------------------------------

    def _update_line_indicator(self) -> None:
        """Show line count in border subtitle when input is multi-line."""
        lines = self.text.count("\n") + 1
        if lines > 1:
            self.border_subtitle = f"{lines} lines"
        else:
            self.border_subtitle = ""

    async def _on_key(self, event) -> None:  # noqa: C901
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
─────────────────────────────────────

  Enter       Send message
  Shift+Enter Insert newline
  Ctrl+J      Insert newline (alt)
  Ctrl+B      Toggle sidebar
  Ctrl+N      New session
  Ctrl+L      Clear chat
  Ctrl+G      Open $EDITOR
  Ctrl+S      Stash/restore prompt
  Ctrl+Y      Copy last response
  Ctrl+M      Bookmark last response
  Ctrl+A      Toggle auto-scroll
  Ctrl+F      Search chat messages
  Ctrl+R      Search prompt history
  Ctrl+Home   Jump to top of chat
  Ctrl+End    Jump to bottom of chat
  Ctrl+Up     Scroll chat up
  Ctrl+Down   Scroll chat down
  Home/End    Top/bottom (empty input)
  Up/Down     Browse prompt history
  F1          This help
  F11         Focus mode
  Ctrl+Q      Quit

        Slash Commands
─────────────────────────────────────

  /help       Show help
  /clear      Clear chat
  /new        New session
  /sessions   Toggle sidebar
  /prefs      Show preferences
  /model      Model info / list / set
  /theme      Switch theme
  /colors     View/set colors
  /export     Export to markdown
  /rename     Rename session
  /pin        Pin/unpin session
  /delete     Delete session
  /stats      Session statistics
  /tokens     Token / context usage
  /info       Session details
  /copy [N]   Copy last response (or msg N)
  /bookmark   Bookmark last response
  /bookmarks  List / jump to bookmarks
  /scroll     Toggle auto-scroll
  /focus      Focus mode
  /notify     Toggle notifications
  /sound      Toggle notification sound
  /timestamps Toggle timestamps
  /wrap       Toggle word wrap
  /keys       This overlay
  /search     Search chat messages
  /sort       Sort sessions (date/name/project)
  /edit       Open $EDITOR for longer prompts
  /alias      List/create/remove shortcuts
  /draft      Show/save/clear input draft
  /compact    Clear chat, keep session
  /fold       Fold/unfold long messages
  /quit       Quit

       Press Escape to close\
"""


class ShortcutOverlay(ModalScreen):
    """Modal overlay showing all keyboard shortcuts and slash commands."""

    BINDINGS = [
        Binding("escape", "dismiss_overlay", show=False),
        Binding("f1", "dismiss_overlay", show=False),
    ]

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="shortcut-modal"):
            yield Static(SHORTCUTS_TEXT, id="shortcut-content")

    def action_dismiss_overlay(self) -> None:
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


# ── Main Application ────────────────────────────────────────────────


class AmplifierChicApp(App):
    """Amplifier TUI - a clean TUI for Amplifier."""

    CSS_PATH = "styles.tcss"
    TITLE = "Amplifier TUI"

    MAX_STASHES = 5
    SESSION_NAMES_FILE = Path.home() / ".amplifier" / "tui-session-names.json"
    BOOKMARKS_FILE = Path.home() / ".amplifier" / "tui-bookmarks.json"
    PINNED_SESSIONS_FILE = Path.home() / ".amplifier" / "tui-pinned-sessions.json"
    DRAFTS_FILE = Path.home() / ".amplifier" / "tui-drafts.json"
    ALIASES_FILE = Path.home() / ".amplifier" / "tui-aliases.json"

    BINDINGS = [
        Binding("f1", "show_shortcuts", "Help", show=True),
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

        # Auto-scroll state
        self._auto_scroll = True

        # Focus mode state (zen mode - hides chrome)
        self._focus_mode = False

        # Word count tracking
        self._total_words: int = 0

        # Session statistics counters
        self._user_message_count: int = 0
        self._assistant_message_count: int = 0
        self._tool_call_count: int = 0
        self._user_words: int = 0
        self._assistant_words: int = 0
        self._session_start_time: float = time.monotonic()

        # Custom command aliases
        self._aliases: dict[str, str] = {}

        # Bookmark tracking
        self._assistant_msg_index: int = 0
        self._last_assistant_widget: Static | None = None
        self._session_bookmarks: list[dict] = []

        # Streaming display state
        self._stream_widget: Static | None = None
        self._stream_container: Collapsible | None = None
        self._stream_block_type: str | None = None

        # Search index: parallel list of (role, text, widget) for /search
        self._search_messages: list[tuple[str, str, Static | None]] = []

        # Pinned sessions (appear at top of sidebar)
        self._pinned_sessions: set[str] = set()

        # Message folding state
        self._fold_threshold: int = 30

    # ── Layout ──────────────────────────────────────────────────

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
                yield ScrollableContainer(id="chat-view")
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
                    yield Static("\u2195 ON", id="status-scroll")
                    yield Static("0 words", id="status-wordcount")
                    yield Static("", id="status-model")

    async def on_mount(self) -> None:
        self.register_theme(CHIC_THEME)
        self.theme = "chic"

        # Apply word-wrap preference (default: on; off adds no-wrap CSS class)
        if not self._prefs.display.word_wrap:
            self.query_one("#chat-view", ScrollableContainer).add_class("no-wrap")

        # Show UI immediately, defer Amplifier import to background
        self._show_welcome()
        self.query_one("#chat-input", ChatInput).focus()

        # Start the spinner timer
        self._spinner_frame = 0
        self._spinner_timer = self.set_interval(0.3, self._animate_spinner)

        # Load pinned sessions
        self._pinned_sessions = self._load_pinned_sessions()

        # Load custom command aliases
        self._aliases = self._load_aliases()

        # Periodic draft auto-save in case of crash
        self.set_interval(30, self._auto_save_draft)

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

    # ── Welcome Screen ──────────────────────────────────────────

    def _show_welcome(self, subtitle: str = "") -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
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
    ) -> str:
        """Build the display string for a session tree node.

        Returns e.g. ``"01/15 14:02  My Project"`` or ``"▪ 01/15 14:02  My Project"``
        with a pin marker when the session is pinned.
        """
        sid = s["session_id"]
        custom = custom_names.get(sid)
        name = s.get("name", "")
        desc = s.get("description", "")

        if custom:
            label = custom[:28] if len(custom) > 28 else custom
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
                display = self._session_display_label(s, custom_names)
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
            display = self._session_display_label(s, custom_names)
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
        """Handle Escape: exit focus mode, or clear session filter."""
        if event.key == "escape":
            # Exit focus mode first if active
            if self._focus_mode:
                self.action_toggle_focus_mode()
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

        def _matches(s: dict) -> bool:
            """Return True if the session matches the current filter query."""
            if not q:
                return True
            sid = s["session_id"]
            display = self._session_display_label(s, custom_names)
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
                display = self._session_display_label(s, custom_names)
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
            display = self._session_display_label(s, custom_names)
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
        """Toggle the keyboard shortcut overlay (F1)."""
        if isinstance(self.screen, ShortcutOverlay):
            self.pop_screen()
        else:
            self.push_screen(ShortcutOverlay())

    def action_search_history(self) -> None:
        """Open the prompt history search modal (Ctrl+R)."""
        if self._history.entry_count == 0:
            self._add_system_message("No prompt history yet.")
            return

        def _on_result(result: str) -> None:
            if result:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.clear()
                input_widget.insert(result)
                input_widget.focus()

        self.push_screen(HistorySearchScreen(self._history), _on_result)

    def action_search_chat(self) -> None:
        """Focus the input and pre-fill /search for quick chat searching (Ctrl+F)."""
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            input_widget.insert("/search ")
            input_widget.focus()
        except Exception:
            pass

    def action_scroll_chat_top(self) -> None:
        """Scroll chat to the very top (Ctrl+Home)."""
        try:
            chat = self.query_one("#chat-view", ScrollableContainer)
            chat.scroll_home(animate=False)
        except Exception:
            pass

    def action_scroll_chat_bottom(self) -> None:
        """Scroll chat to the very bottom (Ctrl+End)."""
        try:
            chat = self.query_one("#chat-view", ScrollableContainer)
            chat.scroll_end(animate=False)
        except Exception:
            pass

    def action_scroll_chat_up(self) -> None:
        """Scroll chat up by a small amount (Ctrl+Up)."""
        try:
            chat = self.query_one("#chat-view", ScrollableContainer)
            chat.scroll_up(animate=False)
        except Exception:
            pass

    def action_scroll_chat_down(self) -> None:
        """Scroll chat down by a small amount (Ctrl+Down)."""
        try:
            chat = self.query_one("#chat-view", ScrollableContainer)
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
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        for child in list(chat_view.children):
            child.remove()
        self._show_welcome("New session will start when you send a message.")
        self._update_session_display()
        self._update_token_display()
        self._update_status("Ready")
        self._total_words = 0
        self._user_message_count = 0
        self._assistant_message_count = 0
        self._tool_call_count = 0
        self._user_words = 0
        self._assistant_words = 0
        self._assistant_msg_index = 0
        self._last_assistant_widget = None
        self._session_bookmarks = []
        self._search_messages = []
        self._session_start_time = time.monotonic()
        self._update_word_count_display()
        self.query_one("#chat-input", ChatInput).focus()

    def action_clear_chat(self) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        for child in list(chat_view.children):
            child.remove()
        self._total_words = 0
        self._user_message_count = 0
        self._assistant_message_count = 0
        self._tool_call_count = 0
        self._user_words = 0
        self._assistant_words = 0
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
                chat_view = self.query_one("#chat-view", ScrollableContainer)
                chat_view.scroll_end(animate=False)
            except Exception:
                pass

    def action_toggle_focus_mode(self) -> None:
        """Toggle focus mode: hide all chrome, show only chat + input."""
        self._focus_mode = not self._focus_mode

        # Hide/show the status bar and breadcrumb
        try:
            self.query_one("#status-bar").display = not self._focus_mode
        except Exception:
            pass
        try:
            self.query_one("#breadcrumb-bar").display = not self._focus_mode
        except Exception:
            pass

        # If entering focus mode with sidebar open, close it
        if self._focus_mode and self._sidebar_visible:
            self.action_toggle_sidebar()

        if self._focus_mode:
            self._add_system_message("Focus mode ON (F11 or /focus to exit)")
        else:
            self._add_system_message("Focus mode OFF")

        # Keep input focused
        try:
            self.query_one("#chat-input", ChatInput).focus()
        except Exception:
            pass

    def _resolve_editor(self) -> str | None:
        """Return the first available editor from $EDITOR, $VISUAL, or common defaults."""
        for candidate in (
            os.environ.get("EDITOR"),
            os.environ.get("VISUAL"),
            "vim",
            "nano",
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
            "/focus": self._cmd_focus,
            "/compact": self._cmd_compact,
            "/copy": lambda: self._cmd_copy(text),
            "/notify": self._cmd_notify,
            "/sound": lambda: self._cmd_sound(text),
            "/scroll": self._cmd_scroll,
            "/timestamps": self._cmd_timestamps,
            "/keys": self._cmd_keys,
            "/stats": self._cmd_stats,
            "/tokens": self._cmd_tokens,
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
            "/pin": lambda: self._cmd_pin(text),
            "/draft": lambda: self._cmd_draft(text),
            "/sort": lambda: self._cmd_sort(text),
            "/edit": self.action_open_editor,
            "/wrap": lambda: self._cmd_wrap(text),
            "/fold": lambda: self._cmd_fold(text),
            "/alias": lambda: self._cmd_alias(args),
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
            "  /model        Show model info | /model list | /model <name>\n"
            "  /stats        Show session statistics\n"
            "  /tokens       Detailed token / context usage breakdown\n"
            "  /info         Show session details (ID, model, project, counts)\n"
            "  /copy         Copy last response | /copy N for message N\n"
            "  /bookmark     Bookmark last response (/bm alias, optional label)\n"
            "  /bookmarks    List bookmarks | /bookmarks <N> to jump\n"
            "  /rename       Rename current session (e.g. /rename My Project)\n"
            "  /pin          Pin/unpin session (pinned appear at top of sidebar)\n"
            "  /delete       Delete session (with confirmation)\n"
            "  /export       Export session to markdown file\n"
            "  /notify       Toggle completion notifications\n"
            "  /sound        Toggle notification sound (/sound on, /sound off)\n"
            "  /scroll       Toggle auto-scroll on/off\n"
            "  /timestamps   Toggle message timestamps on/off\n"
            "  /wrap         Toggle word wrap on/off (/wrap on, /wrap off)\n"
            "  /fold         Fold/unfold long messages (/fold all, /fold none, /fold <n>)\n"
            "  /theme        Switch color theme (dark, light, solarized, monokai, nord, dracula)\n"
            "  /colors       View/set colors (/colors reset, /colors <key> <#hex>)\n"
            "  /focus        Toggle focus mode (hide chrome)\n"
            "  /search       Search chat messages (e.g. /search my query)\n"
            "  /sort         Sort sessions: date, name, project (/sort <mode>)\n"
            "  /edit         Open $EDITOR for longer prompts (same as Ctrl+G)\n"
            "  /draft        Show/save/clear input draft (/draft save, /draft clear)\n"
            "  /alias        List/create/remove custom shortcuts\n"
            "  /compact      Clear chat, keep session\n"
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
            "  Ctrl+G        Open $EDITOR for longer prompts\n"
            "  Ctrl+Y        Copy last response to clipboard\n"
            "  Ctrl+M        Bookmark last response\n"
            "  Ctrl+S        Stash/restore prompt (stack of 5)\n"
            "  Ctrl+B        Toggle sidebar\n"
            "  Ctrl+N        New session\n"
            "  Ctrl+L        Clear chat\n"
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
                    "Usage: /alias <name> = <expansion>\n"
                    "       /alias remove <name>"
                )
                return
            lines = ["Defined aliases:"]
            for name, expansion in sorted(self._aliases.items()):
                lines.append(f"  /{name} = {expansion}")
            lines.append("")
            lines.append("Usage: /alias <name> = <expansion>")
            lines.append("       /alias remove <name>")
            self._add_system_message("\n".join(lines))
            return

        # Remove alias
        if text.startswith("remove "):
            name = text[7:].strip().lstrip("/")
            if name in self._aliases:
                del self._aliases[name]
                self._save_aliases()
                self._add_system_message(f"Alias '/{name}' removed")
            else:
                self._add_system_message(f"No alias '/{name}' found")
            return

        # Create/update alias: name = expansion
        if "=" not in text:
            self._add_system_message(
                "Usage: /alias <name> = <expansion>\n       /alias remove <name>"
            )
            return

        name, expansion = text.split("=", 1)
        name = name.strip().lstrip("/")
        expansion = expansion.strip()

        if not name or not expansion:
            self._add_system_message(
                "Both name and expansion required: /alias <name> = <expansion>"
            )
            return

        # Don't allow overriding built-in commands
        if "/" + name in SLASH_COMMANDS:
            self._add_system_message(f"Cannot override built-in command '/{name}'")
            return

        self._aliases[name] = expansion
        self._save_aliases()
        self._add_system_message(f"Alias set: /{name} = {expansion}")

    def _cmd_draft(self, text: str) -> None:
        """Show, save, or clear the input draft for this session."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "clear":
            self._clear_draft()
            self._add_system_message("Draft cleared")
            return

        if arg == "save":
            self._save_draft()
            self._add_system_message("Draft saved")
            return

        # Show current draft status
        session_id = self._get_session_id()
        drafts = self._load_drafts()
        if session_id and session_id in drafts:
            draft = drafts[session_id]
            preview = draft[:80].replace("\n", " ")
            suffix = "..." if len(draft) > 80 else ""
            self._add_system_message(
                f"Saved draft ({len(draft)} chars): {preview}{suffix}"
            )
        else:
            self._add_system_message("No draft saved for this session")

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
        """Show model info, list available models, or set preferred model.

        /model          Show current model and session token usage
        /model list     Show common models
        /model <name>   Set preferred model for new sessions
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg == "list":
            self._cmd_model_list()
            return

        if arg:
            self._cmd_model_set(arg)
            return

        # No argument — show current model info
        self._cmd_model_show()

    def _cmd_model_show(self) -> None:
        """Display current model, preferred model, and token usage."""
        sm = self.session_manager
        lines = ["Model Info\n"]

        current = sm.model_name if sm else ""
        preferred = self._prefs.preferred_model

        if current:
            lines.append(f"  Model:      {current}")
        else:
            lines.append("  Model:      (not set)")

        if preferred:
            if preferred != current:
                lines.append(f"  Preferred:  {preferred}  (used on /new)")
            else:
                lines.append(f"  Preferred:  {preferred}  (active)")

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

        self._add_system_message("\n".join(lines))

    def _cmd_model_list(self) -> None:
        """Show available models the user can select."""
        models = [
            ("claude-sonnet-4-20250514", "Anthropic"),
            ("claude-haiku-35-20241022", "Anthropic"),
            ("gpt-4o", "OpenAI"),
            ("gpt-4o-mini", "OpenAI"),
            ("o3", "OpenAI"),
            ("o3-mini", "OpenAI"),
        ]
        current = self.session_manager.model_name if self.session_manager else ""
        preferred = self._prefs.preferred_model

        lines = ["Available Models\n"]
        for name, provider in models:
            marker = ""
            if name == current:
                marker = "  (current)"
            elif name == preferred:
                marker = "  (preferred)"
            lines.append(f"  {provider:10s}  {name}{marker}")

        lines.append("")
        lines.append("Use /model <name> to set preferred model for new sessions.")
        lines.append("The change takes effect on /new (next session).")
        self._add_system_message("\n".join(lines))

    def _cmd_model_set(self, name: str) -> None:
        """Set the preferred model for new sessions."""
        self._prefs.preferred_model = name
        save_preferred_model(name)
        self._update_token_display()
        self._add_system_message(
            f"Preferred model set to: {name}\nWill be used for new sessions (/new)."
        )

    def _cmd_quit(self) -> None:
        # Use call_later so the current handler finishes before quit runs
        self.call_later(self.action_quit)

    def _cmd_compact(self) -> None:
        """Clear chat visually but keep the session alive."""
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        for child in list(chat_view.children):
            child.remove()
        self._search_messages = []
        self._add_system_message("Chat cleared. Session continues.")

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

    def _cmd_focus(self) -> None:
        """Toggle focus mode via slash command."""
        self.action_toggle_focus_mode()

    def _cmd_copy(self, text: str) -> None:
        """Copy a message to clipboard. /copy = last assistant, /copy N = message N."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

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
                "Usage: /copy (last response) or /copy N (message number)"
            )
            return

        # Default: copy last assistant message
        self.action_copy_response()

    def _cmd_scroll(self) -> None:
        """Toggle auto-scroll on/off."""
        self.action_toggle_auto_scroll()

    def _cmd_notify(self) -> None:
        """Toggle completion notifications on/off."""
        nprefs = self._prefs.notifications
        nprefs.enabled = not nprefs.enabled
        state = "on" if nprefs.enabled else "off"
        self._add_system_message(
            f"Notifications {state} (notify after {nprefs.min_seconds:.0f}s)"
        )

    def _cmd_sound(self, text: str) -> None:
        """Toggle notification sound on/off, or set explicitly."""
        arg = text.partition(" ")[2].strip().lower() if " " in text else ""

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
            self._add_system_message("Usage: /sound [on|off]")
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
        chat = self.query_one("#chat-view", ScrollableContainer)
        if wrap:
            chat.remove_class("no-wrap")
        else:
            chat.add_class("no-wrap")

        state = "on" if wrap else "off"
        self._add_system_message(f"Word wrap: {state}")

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

    def _cmd_keys(self) -> None:
        """Show the keyboard shortcut overlay."""
        self.action_show_shortcuts()

    def _cmd_stats(self) -> None:
        """Show session statistics."""
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

        # Session ID
        session_id = "none"
        model = "unknown"
        if self.session_manager:
            sid = getattr(self.session_manager, "session_id", None) or ""
            session_id = sid[:12] if sid else "none"
            model = getattr(self.session_manager, "model_name", None) or "unknown"

        # Word counts formatted
        total_words = self._user_words + self._assistant_words
        if total_words >= 1000:
            total_str = f"{total_words / 1000:.1f}k"
        else:
            total_str = str(total_words)
        if self._user_words >= 1000:
            user_str = f"{self._user_words / 1000:.1f}k"
        else:
            user_str = str(self._user_words)
        if self._assistant_words >= 1000:
            asst_str = f"{self._assistant_words / 1000:.1f}k"
        else:
            asst_str = str(self._assistant_words)

        est_tokens = int(total_words * 1.3)
        if est_tokens >= 1000:
            token_str = f"{est_tokens / 1000:.1f}k"
        else:
            token_str = str(est_tokens)

        stats = (
            "Session Statistics\n"
            "──────────────────\n"
            f"Session:    {session_id}\n"
            f"Duration:   {duration}\n"
            f"Messages:   {self._user_message_count} user · "
            f"{self._assistant_message_count} assistant\n"
            f"Tool calls: {self._tool_call_count}\n"
            f"Words:      {total_str} (user: {user_str} · assistant: {asst_str})\n"
            f"Est tokens: ~{token_str}\n"
            f"Model:      {model}"
        )
        self._add_system_message(stats)

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
        pct = (display_total / window * 100) if window > 0 else 0

        fmt = self._format_token_count

        lines = [
            "Context Usage",
            "\u2500" * 18,
        ]

        if api_total > 0:
            lines += [
                f"  Input tokens:     ~{fmt(input_tok)}",
                f"  Output tokens:    ~{fmt(output_tok)}",
                f"  Total (API):      ~{fmt(api_total)}",
            ]
        else:
            lines.append("  (no API token data yet)")

        lines += [
            "",
            "Chat estimate (~4 chars/token):",
            f"  User messages:    ~{fmt(est_user)}",
            f"  Assistant msgs:   ~{fmt(est_asst)}",
            f"  System msgs:      ~{fmt(est_sys)}",
            f"  Visible total:    ~{fmt(est_total)}",
            "",
            f"  Context window:   {fmt(window)}  ({model})",
            f"  Usage:            ~{pct:.1f}%",
            "",
            "Note: Actual context also includes system prompts, tool",
            "schemas, and other overhead not visible in chat",
            "(typically ~10-20K tokens). Use /compact to free space.",
        ]
        self._add_system_message("\n".join(lines))

    def _cmd_theme(self, text: str) -> None:
        """Switch color theme or show current/available themes."""
        parts = text.strip().split(None, 1)
        available = ", ".join(THEMES)

        if len(parts) < 2:
            # No argument: show current theme and list available
            current = self._prefs.theme_name
            lines = [
                f"Current theme: {current}",
                f"Available: {available}",
                "",
                "Usage: /theme <name>",
            ]
            self._add_system_message("\n".join(lines))
            return

        name = parts[1].strip().lower()
        if not self._prefs.apply_theme(name):
            self._add_system_message(f"Unknown theme: {name}\nAvailable: {available}")
            return

        self._prefs.theme_name = name
        save_colors(self._prefs.colors)
        save_theme_name(name)
        self._apply_theme_to_all_widgets()
        self._add_system_message(f"Theme switched to '{name}'.")

    def _apply_theme_to_all_widgets(self) -> None:
        """Re-style every visible chat widget with the current theme colors."""
        try:
            chat_view = self.query_one("#chat-view", ScrollableContainer)
        except Exception:
            return

        for widget in chat_view.children:
            classes = widget.classes if hasattr(widget, "classes") else set()

            if "user-message" in classes:
                self._style_user(widget)

            elif "assistant-message" in classes:
                self._style_assistant(widget)

            elif "system-message" in classes:
                self._style_system(widget)

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

    def _cmd_colors(self, text: str) -> None:
        """View, change, or reset individual color preferences."""
        import re
        from dataclasses import fields

        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg:
            # Show current color settings
            c = self._prefs.colors
            lines = [
                "Current colors:",
                f"  user_text:           {c.user_text}",
                f"  user_border:         {c.user_border}",
                f"  assistant_text:      {c.assistant_text}",
                f"  assistant_border:    {c.assistant_border}",
                f"  thinking_text:       {c.thinking_text}",
                f"  thinking_border:     {c.thinking_border}",
                f"  thinking_background: {c.thinking_background}",
                f"  tool_text:           {c.tool_text}",
                f"  tool_border:         {c.tool_border}",
                f"  tool_background:     {c.tool_background}",
                f"  system_text:         {c.system_text}",
                f"  system_border:       {c.system_border}",
                f"  status_bar:          {c.status_bar}",
                "",
                "Usage: /colors <key> <#hex>  e.g. /colors assistant_text #888888",
                "       /colors reset         Restore defaults",
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
                "Usage: /colors <key> <#hex>  e.g. /colors assistant_text #888888\n"
                "       /colors reset         Restore defaults"
            )
            return

        key, value = tokens
        if not hasattr(self._prefs.colors, key):
            valid = ", ".join(f.name for f in fields(ColorPreferences))
            self._add_system_message(f"Unknown color key '{key}'.\nValid keys: {valid}")
            return

        # Validate hex color
        if not re.match(r"^#[0-9a-fA-F]{6}$", value):
            self._add_system_message(
                f"Invalid hex color '{value}'. Use format: #rrggbb"
            )
            return

        setattr(self._prefs.colors, key, value)
        save_colors(self._prefs.colors)
        self._apply_theme_to_all_widgets()
        self._add_system_message(f"Color '{key}' set to {value}")

    def _cmd_export(self, text: str) -> None:
        """Export the current chat to a clean markdown file."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        sid = getattr(sm, "session_id", None) if sm else None

        # Parse optional filename argument
        parts = text.strip().split(None, 1)
        if len(parts) > 1:
            filename = parts[1].strip()
        else:
            filename = ""

        if not filename:
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
            filename = f"chat-export-{timestamp}.md"

        # Ensure .md extension
        if not filename.endswith(".md"):
            filename += ".md"

        # Check for messages to export
        exportable = [
            (role, msg_text)
            for role, msg_text, _widget in self._search_messages
            if role != "system"
        ]
        if not exportable:
            self._add_system_message("Nothing to export — chat is empty.")
            return

        # Resolve session name for the header
        session_label = "unknown"
        session_id_short = ""
        if sid:
            session_id_short = sid[:12]
            names = self._load_session_names()
            session_label = names.get(sid, session_id_short)

        # Build markdown content
        lines: list[str] = []

        # Header
        lines.append(f"# Chat Export: {session_label}")
        lines.append(f"*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        if session_id_short:
            lines.append(f"*Session: {session_id_short}*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Messages
        for role, msg_text in exportable:
            role_display = role.capitalize()
            lines.append(f"### {role_display}")
            lines.append("")
            lines.append(msg_text)
            lines.append("")
            lines.append("---")
            lines.append("")

        lines.append("*Exported from Amplifier TUI*")

        # Write file
        out_path = Path(filename).expanduser()
        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
        out_path = out_path.resolve()

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("\n".join(lines), encoding="utf-8")
            self._add_system_message(f"Chat exported to: {out_path}")
        except OSError as e:
            self._add_system_message(f"Export failed: {e}")

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

    def _cmd_pin(self, text: str) -> None:
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
        return Static(self._format_timestamp(dt), classes="msg-timestamp")

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

    def _maybe_add_fold_toggle(self, widget: Static, content: str) -> None:
        """Add a fold toggle after a long message for expand/collapse."""
        line_count = content.count("\n") + 1
        if line_count <= self._fold_threshold:
            return
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        widget.add_class("folded")
        toggle = FoldToggle(widget, line_count, folded=True)
        chat_view.mount(toggle, after=widget)

    def _add_user_message(self, text: str, ts: datetime | None = None) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
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

    def _add_assistant_message(self, text: str, ts: datetime | None = None) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
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

    def _add_system_message(self, text: str, ts: datetime | None = None) -> None:
        """Display a system message (slash command output)."""
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        ts_widget = self._make_timestamp(ts)
        if ts_widget:
            chat_view.mount(ts_widget)
        msg = SystemMessage(text)
        chat_view.mount(msg)
        self._style_system(msg)
        self._scroll_if_auto(msg)
        self._search_messages.append(("system", text, msg))

    def _add_thinking_block(self, text: str) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
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
        chat_view = self.query_one("#chat-view", ScrollableContainer)

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
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        msg = ErrorMessage(f"Error: {error_text}", classes="error-message")
        chat_view.mount(msg)
        self._scroll_if_auto(msg)

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
        inp = self.query_one("#chat-input", ChatInput)
        inp.disabled = True
        inp.add_class("disabled")

        chat_view = self.query_one("#chat-view", ScrollableContainer)
        frame = self._SPINNER[0]
        indicator = ProcessingIndicator(
            f" {frame} {label}...",
            classes="processing-indicator",
            id="processing-indicator",
        )
        chat_view.mount(indicator)
        self._scroll_if_auto(indicator)
        self._update_status(f"{label}...")

    def _finish_processing(self) -> None:
        self.is_processing = False
        self._processing_label = None
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
        self._maybe_send_notification()
        self._notify_sound()

    def _maybe_send_notification(self) -> None:
        """Send a terminal notification if processing took long enough."""
        if self._processing_start_time is None:
            return
        elapsed = time.monotonic() - self._processing_start_time
        self._processing_start_time = None
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

    def _notify_sound(self) -> None:
        """Play a terminal bell if notification sound is enabled.

        Uses sys.__stdout__ to bypass Textual's stdout capture.
        This is independent of the richer OSC notification system —
        it simply beeps so the user knows the response is ready.
        """
        if not self._prefs.notifications.sound_enabled:
            return
        out = sys.__stdout__
        if out is None:
            return
        try:
            out.write("\a")
            out.flush()
        except Exception:
            pass

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
            chat_view = self.query_one("#chat-view", ScrollableContainer)
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

    def _check_smart_scroll_pause(self) -> None:
        """During streaming, auto-pause if user has scrolled up."""
        if not self._auto_scroll or not self.is_processing:
            return
        try:
            chat_view = self.query_one("#chat-view", ScrollableContainer)
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
            pct = 0.0
            if sm:
                total = sm.total_input_tokens + sm.total_output_tokens
                window = self._get_context_window()
                if total > 0 and window > 0:
                    used = self._format_token_count(total)
                    cap = self._format_token_count(window)
                    pct = total / window * 100
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

        # Session name or truncated ID
        sm = self.session_manager if hasattr(self, "session_manager") else None
        sid = getattr(sm, "session_id", None) if sm else None
        if sid:
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
            accumulated["text"] += delta
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
            label = _get_tool_label(name, tool_input)
            bare = label.rstrip(".")
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
        chat_view = self.query_one("#chat-view", ScrollableContainer)

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
        self._update_status("Streaming\u2026")

    def _update_streaming_content(self, block_type: str, text: str) -> None:
        """Update the streaming widget with accumulated text so far.

        Called on content_block:delta (throttled to ~50ms). Shows a
        cursor character at the end to indicate more content is coming.
        """
        if not self._stream_widget:
            return
        self._stream_widget.update(text + " \u258d")
        self._check_smart_scroll_pause()
        self._scroll_if_auto(self._stream_widget)

    def _finalize_streaming_block(self, block_type: str, text: str) -> None:
        """Replace the streaming Static with the final rendered widget.

        Called on content_block:end. For text blocks, swaps the fast
        Static with a proper Markdown widget for rich rendering.
        For thinking blocks, collapses and sets the preview title.
        """
        chat_view = self.query_one("#chat-view", ScrollableContainer)

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
                await self.session_manager.start_new_session()
                self.call_from_thread(self._update_session_display)
                self.call_from_thread(self._update_token_display)

            self._setup_streaming_callbacks()
            self.call_from_thread(self._update_status, "Thinking...")

            response = await self.session_manager.send_message(message)

            # Fallback: if no hooks fired, show the full response
            if not self._got_stream_content and response:
                self.call_from_thread(self._add_assistant_message, response)

        except Exception as e:
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
            await self.session_manager.resume_session(session_id)
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

        chat_view = self.query_one("#chat-view", ScrollableContainer)

        # Clear existing content
        for child in list(chat_view.children):
            child.remove()

        self._total_words = 0
        self._user_message_count = 0
        self._assistant_message_count = 0
        self._tool_call_count = 0
        self._user_words = 0
        self._assistant_words = 0
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
