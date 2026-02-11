"""Main Amplifier TUI application."""

from __future__ import annotations


import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


from .platform import amplifier_home, no_editor_message

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import (
    Collapsible,
    Input,
    Markdown,
    Static,
    TextArea,
    Tree,
)
from textual import work
from textual.css.query import NoMatches
from textual.timer import Timer

from .log import logger
from .history import PromptHistory
from .preferences import (
    THEME_DESCRIPTIONS,
    THEMES,
    load_preferences,
    save_preferred_model,
)
from .session_manager import SessionManager
from .theme import TEXTUAL_THEMES, make_custom_textual_theme

from .constants import (
    AUTOSAVE_DIR,
    AVAILABLE_MODELS,
    DEFAULT_CONTEXT_WINDOW,
    EXTENSION_TO_LANGUAGE,
    MAX_ATTACHMENT_SIZE,
    MAX_AUTOSAVES_PER_TAB,
    MAX_INCLUDE_LINES,
    MAX_INCLUDE_SIZE,
    MAX_TABS,
    MODEL_ALIASES,
    MODEL_CONTEXT_WINDOWS,
    MODES,
    PROMPT_TEMPLATES,
    SLASH_COMMANDS,
)
from .widgets import (
    AmplifierCommandProvider,
    AssistantMessage,
    Attachment,
    ChatInput,
    ErrorMessage,
    FindBar,
    FoldToggle,
    HistorySearchBar,
    MessageMeta,
    NoteMessage,
    AgentTreePanel,
    PinnedPanel,
    PinnedPanelHeader,
    PinnedPanelItem,
    ProcessingIndicator,
    ShortcutOverlay,
    SuggestionBar,
    SystemMessage,
    TabBar,
    TabState,
    TodoPanel,
    UserMessage,
)

from .core.app_base import SharedAppBase

from .commands import (
    AgentCommandsMixin,
    SessionCommandsMixin,
    DisplayCommandsMixin,
    ContentCommandsMixin,
    FileCommandsMixin,
    PersistenceCommandsMixin,
    SearchCommandsMixin,
    GitCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    ExportCommandsMixin,
    SplitCommandsMixin,
    WatchCommandsMixin,
    ToolCommandsMixin,
    RecipeCommandsMixin,
)
from .commands.branch_cmds import BranchCommandsMixin
from .commands.compare_cmds import CompareCommandsMixin
from .commands.replay_cmds import ReplayCommandsMixin
from .commands.plugin_cmds import PluginCommandsMixin
from .commands.dashboard_cmds import DashboardCommandsMixin
from .commands.shell_cmds import ShellCommandsMixin
from .commands.terminal_cmds import TerminalCommandsMixin
from .commands.monitor_cmds import MonitorCommandsMixin
from .features.agent_tracker import AgentTracker, is_delegate_tool, make_delegate_key
from .features.tool_log import ToolLog
from .features.recipe_tracker import RecipeTracker
from .features.plugin_loader import PluginLoader
from .features.branch_manager import BranchManager
from .features.compare_manager import CompareManager
from .features.replay_engine import ReplayEngine
from .features.dashboard_stats import DashboardStats
from .persistence import (
    AliasStore,
    BookmarkStore,
    ClipboardStore,
    DraftStore,
    MessagePinStore,
    NoteStore,
    PinnedSessionStore,
    RefStore,
    SessionNameStore,
    SnippetStore,
    TagStore,
    TemplateStore,
)
from ._utils import _context_color, _copy_to_clipboard, _get_tool_label  # noqa: E402


_amp_home = amplifier_home()


class AmplifierTuiApp(
    MonitorCommandsMixin,
    TerminalCommandsMixin,
    ShellCommandsMixin,
    DashboardCommandsMixin,
    ReplayCommandsMixin,
    CompareCommandsMixin,
    BranchCommandsMixin,
    PluginCommandsMixin,
    AgentCommandsMixin,
    ToolCommandsMixin,
    RecipeCommandsMixin,
    SessionCommandsMixin,
    DisplayCommandsMixin,
    ContentCommandsMixin,
    FileCommandsMixin,
    PersistenceCommandsMixin,
    SearchCommandsMixin,
    GitCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    ExportCommandsMixin,
    SplitCommandsMixin,
    WatchCommandsMixin,
    SharedAppBase,
    App,
):
    """Amplifier TUI - a clean TUI for Amplifier."""

    COMMANDS = {AmplifierCommandProvider}

    CSS_PATH = "styles.tcss"
    TITLE = "Amplifier TUI"

    MAX_STASHES = 5
    SESSION_NAMES_FILE = _amp_home / "tui-session-names.json"
    BOOKMARKS_FILE = _amp_home / "tui-bookmarks.json"
    PINNED_SESSIONS_FILE = _amp_home / "tui-pinned-sessions.json"
    MESSAGE_PINS_FILE = _amp_home / "tui-pins.json"
    DRAFTS_FILE = _amp_home / "tui-drafts.json"
    ALIASES_FILE = _amp_home / "tui-aliases.json"
    SNIPPETS_FILE = _amp_home / "tui-snippets.json"
    TEMPLATES_FILE = _amp_home / "tui-templates.json"
    SESSION_TITLES_FILE = _amp_home / "tui-session-titles.json"
    REFS_FILE = _amp_home / "tui-refs.json"
    NOTES_FILE = _amp_home / "tui-notes.json"
    CRASH_DRAFT_FILE = _amp_home / "tui-draft.txt"

    DEFAULT_SNIPPETS: dict[str, dict[str, str]] = {
        "review": {
            "content": "Review {file_or_code} for bugs, performance issues, and best practices:",
            "category": "prompts",
        },
        "explain": {
            "content": "Explain {file_or_code} in detail:",
            "category": "prompts",
        },
        "tests": {
            "content": "Write comprehensive tests for {file_or_code}:",
            "category": "prompts",
        },
        "fix": {
            "content": "Fix the bug in {file_or_code}:",
            "category": "prompts",
        },
        "refactor": {
            "content": "Refactor {file_or_code} to be cleaner and more maintainable:",
            "category": "prompts",
        },
        "doc": {
            "content": "Write documentation for {file_or_code}:",
            "category": "prompts",
        },
        "debug": {
            "content": "Debug this error:",
            "category": "prompts",
        },
        "plan": {
            "content": "Create a detailed plan for implementing {feature_or_task}:",
            "category": "prompts",
        },
        "optimize": {
            "content": "Optimize {file_or_code} for better performance:",
            "category": "prompts",
        },
        "security": {
            "content": "Review {file_or_code} for security vulnerabilities:",
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
        Binding("ctrl+shift+c", "copy_response", "Copy", show=False),
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
        Binding("alt+left", "prev_tab", "Prev Tab", show=False),
        Binding("alt+right", "next_tab", "Next Tab", show=False),
        Binding("alt+1", "switch_tab(1)", "Tab 1", show=False),
        Binding("alt+2", "switch_tab(2)", "Tab 2", show=False),
        Binding("alt+3", "switch_tab(3)", "Tab 3", show=False),
        Binding("alt+4", "switch_tab(4)", "Tab 4", show=False),
        Binding("alt+5", "switch_tab(5)", "Tab 5", show=False),
        Binding("alt+6", "switch_tab(6)", "Tab 6", show=False),
        Binding("alt+7", "switch_tab(7)", "Tab 7", show=False),
        Binding("alt+8", "switch_tab(8)", "Tab 8", show=False),
        Binding("alt+9", "switch_tab(9)", "Tab 9", show=False),
        Binding("alt+0", "switch_tab(0)", "Last Tab", show=False),
        Binding("f2", "rename_tab", "Rename Tab", show=False),
        Binding("alt+m", "toggle_multiline", "Multiline", show=False),
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
        self.session_manager: SessionManager | None = None
        self.is_processing = False
        self._queued_message: str | None = None
        self._auto_mode: str = "full"
        self._got_stream_content = False
        self._amplifier_available = True
        self._amplifier_ready = False
        self._session_list_data: list[dict] = []
        self._sidebar_visible = False
        self._spinner_frame = 0
        self._spinner_timer: Timer | None = None
        self._timestamp_timer: Timer | None = None
        self._processing_label: str | None = None
        self._status_activity_label: str = "Ready"
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

        # Custom system prompt (per-tab, injected before each message)
        self._system_prompt: str = ""
        self._system_preset_name: str = ""  # name of active preset (if any)

        # Amplifier mode (planning, research, review, debug) — per-tab
        self._active_mode: str | None = None

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
        self._bookmark_cursor: int = -1  # Navigation cursor for [ / ] cycling

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

        # Cross-session search results (for /search open N)
        self._last_search_results: list[dict] = []
        self._active_search_query: str = (
            ""  # Auto-trigger find bar on next transcript display
        )
        self._last_search_query: str = ""  # Query from last cross-session search

        # Find-in-chat state (Ctrl+F interactive search bar)
        self._find_visible: bool = False
        self._find_matches: list[int] = []  # indices into _search_messages
        self._find_index: int = -1
        self._find_case_sensitive: bool = False
        self._find_highlighted: set[int] = set()  # indices with .find-match

        # Pinned sessions (appear at top of sidebar)
        self._pinned_sessions: set[str] = set()

        # Pinned messages (per-session bookmarks for quick recall)
        self._message_pins: list[dict] = []
        self._pinned_panel_collapsed: bool = False

        # Session notes (user annotations, not sent to AI)
        self._session_notes: list[dict] = []

        # Theme preview state (temporarily applied theme, not yet saved)
        self._previewing_theme: str | None = None

        # Message folding state (from preferences, 0 = disabled)
        self._fold_threshold: int = self._prefs.display.fold_threshold or 20

        # Crash-recovery draft timer (debounced save)
        self._crash_draft_timer: Timer | None = None

        # Draft auto-save change detection
        self._last_saved_draft: str = ""

        # Session auto-title (extracted from first user message)
        self._session_title: str = ""

        # File watch state (/watch command)
        from .features.file_watch import FileWatcher

        self._file_watcher = FileWatcher(
            add_message=self._add_system_message,
            notify_sound=self._notify_sound,
            set_interval=self.set_interval,
        )
        # Backward-compat aliases used by watch_cmds mixin
        self._watched_files = self._file_watcher.watched_files
        self._watch_timer: Timer | None = None

        # Tab management state
        self._tabs: list[TabState] = [
            TabState(
                name="Main",
                tab_id="tab-0",
                container_id="chat-view",
            )
        ]
        self._tabs[0].conversation.created_at = datetime.now().isoformat()
        self._active_tab_index: int = 0
        self._tab_counter: int = 1

        # Tab split view state (two tabs side by side)
        self._tab_split_mode: bool = False
        self._tab_split_left_index: int | None = None
        self._tab_split_right_index: int | None = None
        self._tab_split_active: str = "left"  # "left" or "right"

        # Auto-save state
        self._autosave_enabled: bool = self._prefs.autosave.enabled
        self._autosave_interval: int = self._prefs.autosave.interval
        self._last_autosave: float = 0.0
        self._autosave_timer: Timer | None = None

        # File attachments (cleared after sending)
        self._attachments: list[Attachment] = []

        # Reverse search state (Ctrl+R inline)
        # NOTE: _rsearch_mgr is created lazily in _init_rsearch_manager()
        # because self._history isn't available until after __init__.
        self._rsearch_mgr: object | None = None  # ReverseSearchManager (lazy)
        # Backward-compat aliases — set when manager is created
        self._rsearch_active: bool = False
        self._rsearch_query: str = ""
        self._rsearch_matches: list[int] = []
        self._rsearch_match_idx: int = -1
        self._rsearch_original: str = ""

        # ── Persistence stores ──────────────────────────────────────────
        self._alias_store = AliasStore(_amp_home / "tui-aliases.json")
        self._bookmark_store = BookmarkStore(_amp_home / "tui-bookmarks.json")
        self._draft_store = DraftStore(
            _amp_home / "tui-drafts.json", _amp_home / "tui-draft.txt"
        )
        self._note_store = NoteStore(_amp_home / "tui-notes.json")
        self._pin_store = MessagePinStore(_amp_home / "tui-pins.json")
        self._pinned_session_store = PinnedSessionStore(
            _amp_home / "tui-pinned-sessions.json"
        )
        self._ref_store = RefStore(_amp_home / "tui-refs.json")
        self._session_name_store = SessionNameStore(
            _amp_home / "tui-session-names.json",
            _amp_home / "tui-session-titles.json",
        )
        self._snippet_store = SnippetStore(_amp_home / "tui-snippets.json")
        self._template_store = TemplateStore(_amp_home / "tui-templates.json")
        self._tag_store = TagStore(_amp_home / "tui-session-tags.json")
        self._clipboard_store = ClipboardStore(_amp_home / "tui-clipboard-ring.json")

        # Recently included files (/include recent)
        self._recent_includes: list[str] = []

        # Agent delegation tracking (/agents command)
        self._agent_tracker = AgentTracker()

        # Live tool introspection log (/tools command)
        self._tool_log = ToolLog()

        # Recipe pipeline tracking (/recipe command)
        self._recipe_tracker = RecipeTracker()

        # Conversation branch manager (/fork, /branches, /branch commands)
        self._branch_manager = BranchManager()

        # Model A/B testing manager (/compare command)
        self._compare_manager = CompareManager()

        # Session replay engine (/replay command)
        self._replay_engine = ReplayEngine()

        # Plugin system (/plugins command)
        self._plugin_loader = PluginLoader()
        self._plugin_loader.load_all()

        # Context window profiler history (/context history)
        from .features.context_profiler import ContextHistory

        self._context_history = ContextHistory()

        # Session dashboard stats (/dashboard command)
        self._dashboard_stats = DashboardStats()

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
                yield FindBar(id="find-bar")
                yield PinnedPanel(id="pinned-panel")
                with Horizontal(id="chat-split-container"):
                    yield ScrollableContainer(id="chat-view", classes="tab-chat-view")
                    yield ScrollableContainer(id="split-panel")
                yield Vertical(id="terminal-panel")
                yield Vertical(id="monitor-panel")
                yield ChatInput(
                    "",
                    id="chat-input",
                    soft_wrap=True,
                    show_line_numbers=False,
                    tab_behavior="focus",
                    compact=True,
                )
                yield SuggestionBar()
                yield HistorySearchBar()
                yield Static("", id="attachment-indicator")
                yield Static("", id="input-counter")
                with Horizontal(id="status-bar"):
                    yield Static("No session", id="status-session")
                    yield Static("", id="status-tabs")
                    yield Static("Ready", id="status-state")
                    yield Static("", id="status-stash")
                    yield Static("", id="status-vim")
                    yield Static("", id="status-ml")
                    yield Static("", id="status-system")
                    yield Static("", id="status-mode")
                    yield Static("\u2195 ON", id="status-scroll")
                    yield Static("0 words", id="status-wordcount")
                    yield Static("", id="status-context")
                    yield Static("", id="status-model")
            yield TodoPanel(id="todo-panel")
            yield AgentTreePanel(id="agent-tree-panel")

    async def on_mount(self) -> None:
        # Register all built-in color themes
        for _tname, tobj in TEXTUAL_THEMES.items():
            self.register_theme(tobj)

        # Register Textual base themes for any user-defined custom themes
        for cname in THEMES:
            if cname not in TEXTUAL_THEMES:
                base = "dark"  # custom themes inherit the dark Textual base
                custom_tobj = make_custom_textual_theme(cname, base)
                TEXTUAL_THEMES[cname] = custom_tobj
                self.register_theme(custom_tobj)

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

        # Apply multiline-mode preference (default: off)
        if self._prefs.display.multiline_default:
            ml_input = self.query_one("#chat-input", ChatInput)
            ml_input._multiline_mode = True
            self._update_multiline_status()

        # Apply show-suggestions preference (default: on)
        if not self._prefs.display.show_suggestions:
            sg_input = self.query_one("#chat-input", ChatInput)
            sg_input._suggestions_enabled = False

        # Initialize tab bar
        self._update_tab_bar()

        # Show UI immediately, defer Amplifier import to background
        self._show_welcome()
        self.query_one("#chat-input", ChatInput).focus()

        # Start the spinner timer
        self._spinner_frame = 0
        self._spinner_timer = self.set_interval(0.3, self._animate_spinner)

        # Periodic timestamp refresh (updates relative times like "2m ago")
        if self._prefs.display.show_timestamps:
            self._timestamp_timer = self.set_interval(30.0, self._refresh_timestamps)

        # Load pinned sessions
        self._pinned_sessions = self._load_pinned_sessions()

        # Load message pins for current session
        self._message_pins = self._load_message_pins()
        self._update_pinned_panel()

        # Load custom command aliases
        self._aliases = self._load_aliases()

        # Load reusable prompt snippets
        self._snippets = self._load_snippets()

        # Load prompt templates with {{variable}} placeholders
        self._templates = self._load_templates()

        # Periodic draft auto-save (every 5s, only writes when content changes)
        self.set_interval(5, self._auto_save_draft)

        # Initialize session auto-save system
        self._setup_autosave()

        # Restore crash-recovery draft if one exists from a previous crash
        crash_draft = self._load_crash_draft()
        if crash_draft:
            try:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.insert(crash_draft)
                self._last_saved_draft = input_widget.text.strip()
                preview = crash_draft[:60].replace("\n", " ")
                if len(crash_draft) > 60:
                    preview += "..."
                self._add_system_message(
                    f"Recovered unsent draft ({len(crash_draft)} chars): "
                    f"{preview}\n"
                    "Press Enter to send, or edit as needed."
                )
            except NoMatches:
                logger.debug(
                    "Chat input widget not found for crash draft recovery",
                    exc_info=True,
                )

        # Check for auto-save recovery from a previous crash
        self._check_autosave_recovery()

        # Heavy import in background
        self._init_amplifier_worker()

    @work(thread=True)
    def _init_amplifier_worker(self) -> None:
        """Import Amplifier in background so UI appears instantly."""
        self.call_from_thread(self._update_status, "Loading Amplifier...")

        # SessionManager.__init__ is lightweight (no amplifier imports), so it
        # essentially never fails.  The real failures happen at session-creation
        # time inside LocalBridge.  We probe the environment here to give users
        # structured guidance *before* they hit a raw exception on first message.
        try:
            self.session_manager = SessionManager()
        except Exception:
            logger.debug(
                "Failed to initialize Amplifier session manager", exc_info=True
            )
            self._amplifier_available = False
            self.call_from_thread(
                self._show_welcome,
                "Amplifier session manager failed to initialise.\n"
                "Use /environment for diagnostics.",
            )
            self.call_from_thread(self._update_status, "Not connected")
            return

        # Proactive readiness check -- catches the common "clean machine" case
        # where libraries or bundles aren't set up yet, BEFORE the user sends a
        # message and gets a raw exception.
        from .environment import check_environment, format_status

        env_status = check_environment(self._prefs.environment.workspace)
        if not env_status.ready:
            self._amplifier_available = False
            diag = format_status(env_status)
            self.call_from_thread(
                self._show_welcome,
                diag
                + "\n\nFix the issues above, then restart or use /environment to re-check.",
            )
            self.call_from_thread(self._update_status, "Setup needed")
            return

        self._amplifier_ready = True

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
            tab_bar.update_tabs(
                self._tabs,
                self._active_tab_index,
                split_left=self._tab_split_left_index if self._tab_split_mode else None,
                split_right=self._tab_split_right_index
                if self._tab_split_mode
                else None,
            )
        except NoMatches:
            logger.debug("Tab bar widget not found", exc_info=True)
        self._update_tab_indicator()

    def _update_tab_indicator(self) -> None:
        """Update the 'Tab N/M' indicator in the status bar."""
        try:
            widget = self.query_one("#status-tabs", Static)
            count = len(self._tabs)
            if self._tab_split_mode:
                left = (self._tab_split_left_index or 0) + 1
                right = (self._tab_split_right_index or 0) + 1
                side = "L" if self._tab_split_active == "left" else "R"
                widget.update(f"Split {left}|{right} [{side}]")
            elif count > 1:
                widget.update(f"Tab {self._active_tab_index + 1}/{count}")
            else:
                widget.update("")
        except NoMatches:
            logger.debug("Status tabs widget not found", exc_info=True)

    def _save_current_tab_state(self) -> None:
        """Save current app state into the active tab's TabState."""
        tab = self._tabs[self._active_tab_index]
        conv = tab.conversation
        if self.session_manager:
            conv.session = getattr(self.session_manager, "session", None)
            conv.session_id = getattr(self.session_manager, "session_id", None)
        conv.title = self._session_title
        conv.search_messages = self._search_messages
        conv.total_words = self._total_words
        conv.user_message_count = self._user_message_count
        conv.assistant_message_count = self._assistant_message_count
        conv.tool_call_count = self._tool_call_count
        conv.user_words = self._user_words
        conv.assistant_words = self._assistant_words
        conv.response_times = self._response_times
        conv.tool_usage = self._tool_usage
        conv.assistant_msg_index = self._assistant_msg_index
        conv.last_assistant_text = self._last_assistant_text
        conv.bookmarks = self._session_bookmarks
        conv.refs = self._session_refs
        conv.pins = self._message_pins
        conv.notes = self._session_notes
        conv.system_prompt = self._system_prompt
        conv.system_preset_name = self._system_preset_name
        conv.active_mode = self._active_mode
        # UI-only fields stay on tab
        tab.last_assistant_widget = self._last_assistant_widget
        # Preserve unsent input text across tab switches
        try:
            tab.input_text = self.query_one("#chat-input", ChatInput).text
        except NoMatches:
            logger.debug(
                "Chat input widget not found when saving tab state", exc_info=True
            )

    def _load_tab_state(self, tab: TabState) -> None:
        """Load a TabState's data into current app state."""
        conv = tab.conversation
        if self.session_manager:
            self.session_manager.session = conv.session
            self.session_manager.session_id = conv.session_id
        self._session_title = conv.title
        self._search_messages = conv.search_messages
        self._total_words = conv.total_words
        self._user_message_count = conv.user_message_count
        self._assistant_message_count = conv.assistant_message_count
        self._tool_call_count = conv.tool_call_count
        self._user_words = conv.user_words
        self._assistant_words = conv.assistant_words
        self._response_times = conv.response_times
        self._tool_usage = conv.tool_usage
        self._assistant_msg_index = conv.assistant_msg_index
        self._last_assistant_text = conv.last_assistant_text
        self._session_bookmarks = conv.bookmarks
        self._session_refs = conv.refs
        self._message_pins = conv.pins
        self._session_notes = conv.notes
        self._system_prompt = conv.system_prompt
        self._system_preset_name = conv.system_preset_name
        self._active_mode = conv.active_mode
        # UI-only fields from tab
        self._last_assistant_widget = tab.last_assistant_widget

    def _switch_to_tab(self, index: int) -> None:
        """Switch to the tab at the given index."""
        if index == self._active_tab_index:
            return
        if index < 0 or index >= len(self._tabs):
            return
        if self.is_processing:
            self._add_system_message("Cannot switch tabs while processing.")
            return

        # Exit tab split mode if active
        if self._tab_split_mode:
            self._exit_tab_split()
            if index == self._active_tab_index:
                return  # Already on this tab after exiting split

        # Save current tab state
        self._save_current_tab_state()

        # Hide current tab's container
        old_tab = self._tabs[self._active_tab_index]
        try:
            old_container = self.query_one(
                f"#{old_tab.container_id}", ScrollableContainer
            )
            old_container.add_class("tab-chat-hidden")
        except NoMatches:
            logger.debug(
                "Old tab container not found when switching tabs", exc_info=True
            )

        # Switch index
        self._active_tab_index = index

        # Show new tab's container
        new_tab = self._tabs[index]
        try:
            new_container = self.query_one(
                f"#{new_tab.container_id}", ScrollableContainer
            )
            new_container.remove_class("tab-chat-hidden")
        except NoMatches:
            logger.debug(
                "New tab container not found when switching tabs", exc_info=True
            )

        # Load new tab state
        self._load_tab_state(new_tab)

        # Restore unsent input text for this tab
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            if new_tab.input_text:
                input_widget.insert(new_tab.input_text)
            self._last_saved_draft = (new_tab.input_text or "").strip()
        except NoMatches:
            logger.debug(
                "Chat input widget not found when restoring tab input", exc_info=True
            )

        # Update UI
        self._update_tab_bar()
        self._update_session_display()
        self._update_word_count_display()
        self._update_breadcrumb()
        self._update_pinned_panel()
        self.sub_title = self._session_title or ""
        self.query_one("#chat-input", ChatInput).focus()

    def _create_new_tab(
        self, name: str | None = None, *, show_welcome: bool = True
    ) -> None:
        """Create a new conversation tab."""
        if len(self._tabs) >= MAX_TABS:
            self._add_system_message(
                f"Maximum {MAX_TABS} tabs allowed. Close a tab first."
            )
            return
        if self.is_processing:
            self._add_system_message("Cannot create tab while processing.")
            return

        # Exit tab split mode before creating a new tab
        if self._tab_split_mode:
            self._exit_tab_split()

        tab_id = f"tab-{self._tab_counter}"
        container_id = f"chat-view-{self._tab_counter}"
        self._tab_counter += 1

        if not name:
            name = f"Tab {len(self._tabs) + 1}"

        tab = TabState(
            name=name,
            tab_id=tab_id,
            container_id=container_id,
        )
        tab.conversation.created_at = datetime.now().isoformat()

        # Save current tab state before switching
        self._save_current_tab_state()

        # Hide current tab's container
        old_tab = self._tabs[self._active_tab_index]
        try:
            old_container = self.query_one(
                f"#{old_tab.container_id}", ScrollableContainer
            )
            old_container.add_class("tab-chat-hidden")
        except NoMatches:
            logger.debug(
                "Old tab container not found when creating new tab", exc_info=True
            )

        # Create new container and mount it
        new_container = ScrollableContainer(id=container_id, classes="tab-chat-view")
        try:
            split_container = self.query_one("#chat-split-container", Horizontal)
            # Mount before split-panel
            split_panel = self.query_one("#split-panel", ScrollableContainer)
            split_container.mount(new_container, before=split_panel)
        except NoMatches:
            logger.debug(
                "Split container or panel not found when mounting new tab",
                exc_info=True,
            )

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
        self._session_notes = []
        self._update_pinned_panel()

        # Update UI
        self._update_tab_bar()
        self._update_session_display()
        self._update_word_count_display()
        self._update_breadcrumb()
        self.sub_title = ""
        if show_welcome:
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

        # Exit tab split mode if closing a tab that's part of the split
        if self._tab_split_mode and index in (
            self._tab_split_left_index,
            self._tab_split_right_index,
        ):
            self._exit_tab_split()

        closing_tab = self._tabs[index]

        # Remove the container widget
        try:
            container = self.query_one(
                f"#{closing_tab.container_id}", ScrollableContainer
            )
            container.remove()
        except NoMatches:
            logger.debug("Tab container not found when closing tab", exc_info=True)

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
            except NoMatches:
                logger.debug(
                    "New active tab container not found after closing tab",
                    exc_info=True,
                )
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
        """Rename the current tab (max 30 chars)."""
        name = new_name.strip()[:30]
        tab = self._tabs[self._active_tab_index]
        tab.custom_name = name
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
        # Try by name (case-insensitive, prefer custom_name)
        query_lower = query.lower().strip()
        for i, tab in enumerate(self._tabs):
            display = tab.custom_name or tab.name
            if display.lower() == query_lower:
                return i
        return None

    # ── Tab Action Methods (keyboard shortcuts) ─────────────────

    def action_rename_tab(self) -> None:
        """Rename current tab (F2). Pre-fills input with /rename."""
        tab = self._tabs[self._active_tab_index]
        current = tab.custom_name or tab.name
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.value = f"/rename {current}"
            chat_input.focus()
        except NoMatches:
            logger.debug("Chat input widget not found for tab rename", exc_info=True)

    def action_new_tab(self) -> None:
        """Create a new tab (Ctrl+T)."""
        self._create_new_tab()

    def action_close_tab(self) -> None:
        """Close current tab (Ctrl+W), or switch pane in split mode."""
        if self._tab_split_mode:
            self._switch_split_pane()
            return
        if len(self._tabs) <= 1:
            self._add_system_message("Cannot close the last tab.")
            return
        # Check if current tab has content
        tab = self._tabs[self._active_tab_index]
        try:
            container = self.query_one(f"#{tab.container_id}", ScrollableContainer)
            has_content = len(list(container.children)) > 0
        except NoMatches:
            logger.debug(
                "Tab container not found when checking for content", exc_info=True
            )
            has_content = False
        if has_content:
            self._close_tab()
        else:
            self._close_tab()

    def action_prev_tab(self) -> None:
        """Switch to previous tab, or left pane in split mode."""
        if self._tab_split_mode:
            if self._tab_split_active != "left":
                self._switch_split_pane()
            return
        if len(self._tabs) <= 1:
            return
        new_index = (self._active_tab_index - 1) % len(self._tabs)
        self._switch_to_tab(new_index)

    def action_next_tab(self) -> None:
        """Switch to next tab, or right pane in split mode."""
        if self._tab_split_mode:
            if self._tab_split_active != "right":
                self._switch_split_pane()
            return
        if len(self._tabs) <= 1:
            return
        new_index = (self._active_tab_index + 1) % len(self._tabs)
        self._switch_to_tab(new_index)

    def action_switch_tab(self, number: int) -> None:
        """Switch to tab by number (Alt+1-9) or last tab (Alt+0)."""
        if number == 0:
            # Alt+0 → last tab (browser convention)
            self._switch_to_tab(len(self._tabs) - 1)
        else:
            # Alt+N → tab N (1-based → 0-based index)
            self._switch_to_tab(number - 1)

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
        return self._session_name_store.load_names()

    def _save_session_name(self, session_id: str, name: str) -> None:
        """Save a custom session name to the JSON file."""
        self._session_name_store.save_name(session_id, name)

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
        return self._session_name_store.load_titles()

    def _save_session_title(self) -> None:
        """Save current session title to the JSON file."""
        sid = self._get_session_id()
        if not sid:
            return
        self._session_name_store.save_title(sid, self._session_title or None)

    def _load_session_title_for(self, session_id: str) -> str:
        """Load the title for a specific session."""
        return self._session_name_store.title_for(session_id)

    def _apply_session_title(self) -> None:
        """Update the UI to reflect the current session title."""
        self.sub_title = self._session_title
        self._update_breadcrumb()
        self._save_session_title()

    # ── Pinned Sessions ─────────────────────────────────────────

    def _load_pinned_sessions(self) -> set[str]:
        """Load pinned session IDs from the JSON file."""
        return self._pinned_session_store.load()

    def _save_pinned_sessions(self) -> None:
        """Persist the current set of pinned session IDs."""
        self._pinned_session_store.save(self._pinned_sessions)

    def _remove_pinned_session(self, session_id: str) -> None:
        """Remove a session from pinned set (e.g. on delete)."""
        if session_id in self._pinned_sessions:
            self._pinned_sessions.discard(session_id)
            self._save_pinned_sessions()

    # ── Aliases ──────────────────────────────────────────────

    def _load_aliases(self) -> dict[str, str]:
        """Load custom command aliases from the JSON file."""
        return self._alias_store.load()

    def _save_aliases(self) -> None:
        """Persist custom command aliases."""
        self._alias_store.save(self._aliases)

    # ── Snippets ────────────────────────────────────────────

    def _load_snippets(self) -> dict[str, dict[str, str]]:
        """Load reusable prompt snippets from the JSON file."""
        return self._snippet_store.load()

    @staticmethod
    def _migrate_snippets(
        data: dict[str, str | dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """Migrate old ``{name: text}`` format to ``{name: {content, category, created}}``."""
        return SnippetStore._migrate(data)

    def _save_snippets(self) -> None:
        """Persist reusable prompt snippets."""
        self._snippet_store.save(self._snippets)

    # ── Templates ─────────────────────────────────────────

    def _load_templates(self) -> dict[str, str]:
        """Load prompt templates from the JSON file."""
        return self._template_store.load()

    def _save_templates(self) -> None:
        """Persist prompt templates."""
        self._template_store.save(self._templates)

    # ── Drafts ────────────────────────────────────────────────

    def _load_drafts(self) -> dict:
        """Load all drafts from the JSON file."""
        return self._draft_store.load()

    @staticmethod
    def _draft_text(entry: object) -> str:
        """Extract plain text from a draft entry (handles old str or new dict format)."""
        if isinstance(entry, dict):
            return entry.get("text", "")
        if isinstance(entry, str):
            return entry
        return ""

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
                drafts[session_id] = {
                    "text": text,
                    "timestamp": datetime.now().isoformat(),
                    "preview": text[:100].replace("\n", " "),
                }
            elif session_id in drafts:
                del drafts[session_id]
            else:
                return  # Nothing to save or clear

            self._purge_old_drafts(drafts)
            self._draft_store.save_all(drafts)
        except (OSError, KeyError):
            logger.debug("failed to save draft", exc_info=True)

    def _restore_draft(self) -> None:
        """Restore draft for current session if one exists."""
        try:
            session_id = self._get_session_id()
            if not session_id:
                return

            drafts = self._load_drafts()
            entry = drafts.get(session_id)
            draft_text = self._draft_text(entry) if entry else ""

            if draft_text:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.clear()
                input_widget.insert(draft_text)
                self._last_saved_draft = draft_text.strip()
                self._add_system_message(f"Draft restored ({len(draft_text)} chars)")
        except (OSError, KeyError):
            logger.debug("failed to restore draft", exc_info=True)

    def _clear_draft(self) -> None:
        """Remove draft for current session."""
        try:
            session_id = self._get_session_id()
            if not session_id:
                return
            self._draft_store.remove(session_id)
            self._last_saved_draft = ""
        except (OSError, KeyError):
            logger.debug("failed to clear draft", exc_info=True)

    def _auto_save_draft(self) -> None:
        """Periodic auto-save of input draft (called every 5s by timer).

        Only writes to disk when the input text has actually changed since
        the last save, and briefly flashes a 'Draft saved' notification.
        """
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            current = input_widget.text.strip()
            if current != self._last_saved_draft:
                self._last_saved_draft = current
                session_id = self._get_session_id()
                if session_id:
                    self._save_draft()
                    if current:
                        self.notify("Draft saved", timeout=1.5, severity="information")
        except (OSError, KeyError):
            logger.debug("failed to auto-save draft", exc_info=True)

    def _purge_old_drafts(self, drafts: dict) -> None:
        """Remove drafts older than 30 days and cap at 50 entries."""
        try:
            now = datetime.now()
            expired = []
            for sid, entry in drafts.items():
                if isinstance(entry, dict):
                    ts = entry.get("timestamp", "")
                    if ts:
                        try:
                            age = now - datetime.fromisoformat(ts)
                            if age.days > 30:
                                expired.append(sid)
                        except (ValueError, TypeError):
                            pass
            for sid in expired:
                del drafts[sid]
            # Cap at 50 entries – drop oldest first
            if len(drafts) > 50:
                by_ts = sorted(
                    drafts.items(),
                    key=lambda kv: (
                        kv[1].get("timestamp", "") if isinstance(kv[1], dict) else ""
                    ),
                )
                for sid, _ in by_ts[: len(drafts) - 50]:
                    del drafts[sid]
        except (OSError, KeyError):
            logger.debug("failed to purge old drafts", exc_info=True)

    # ── Session auto-save ───────────────────────────────────────────────────

    def _setup_autosave(self) -> None:
        """Initialize the periodic session auto-save system."""
        AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        if self._autosave_enabled:
            self._autosave_timer = self.set_interval(
                self._autosave_interval,
                self._do_autosave,
                name="autosave",
            )

    def _do_autosave(self) -> None:
        """Auto-save ALL tabs and workspace state.

        Silently fails — never interrupts the user.
        """
        if not self._autosave_enabled:
            return
        try:
            # Sync active tab state so all tabs are up-to-date
            self._save_current_tab_state()

            ts = int(time.time())
            saved_tabs_info: list[dict] = []

            for tab in self._tabs:
                messages = tab.conversation.search_messages
                tab_id = tab.tab_id

                if not messages:
                    # Track the tab but no autosave file
                    saved_tabs_info.append(
                        {
                            "tab_id": tab_id,
                            "name": tab.custom_name or tab.name,
                            "autosave_file": None,
                        }
                    )
                    continue

                session_data = {
                    "session_id": tab.conversation.session_id or "",
                    "session_title": tab.conversation.title or "",
                    "tab_id": tab_id,
                    "tab_name": tab.custom_name or tab.name,
                    "saved_at": datetime.now().isoformat(),
                    "message_count": len(messages),
                    "messages": [
                        {"role": role, "content": content}
                        for role, content, _widget in messages
                    ],
                }

                filename = f"autosave-{tab_id}-{ts}.json"
                filepath = AUTOSAVE_DIR / filename
                filepath.write_text(
                    json.dumps(session_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                saved_tabs_info.append(
                    {
                        "tab_id": tab_id,
                        "name": tab.custom_name or tab.name,
                        "autosave_file": filename,
                    }
                )

                # Rotate old auto-saves for this tab
                self._rotate_autosaves(tab_id)

            # Write workspace state (tab layout + references to autosave files)
            workspace_state = {
                "saved_at": datetime.now().isoformat(),
                "active_tab_index": self._active_tab_index,
                "tab_counter": self._tab_counter,
                "tabs": saved_tabs_info,
            }
            ws_path = AUTOSAVE_DIR / "workspace-state.json"
            ws_path.write_text(
                json.dumps(workspace_state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            self._last_autosave = time.time()
        except OSError:
            logger.debug("auto-save failed", exc_info=True)

    def _rotate_autosaves(self, tab_id: str) -> None:
        """Keep only the last MAX_AUTOSAVES_PER_TAB files per tab."""
        try:
            pattern = f"autosave-{tab_id}-*.json"
            files = sorted(AUTOSAVE_DIR.glob(pattern), key=lambda f: f.stat().st_mtime)
            while len(files) > MAX_AUTOSAVES_PER_TAB:
                oldest = files.pop(0)
                oldest.unlink(missing_ok=True)
        except OSError:
            logger.debug("failed to rotate autosaves", exc_info=True)

    def _check_autosave_recovery(self) -> None:
        """Check for workspace or auto-save files on startup and auto-restore."""
        try:
            if not AUTOSAVE_DIR.exists():
                return

            # First check for workspace state (multi-tab restore)
            ws_path = AUTOSAVE_DIR / "workspace-state.json"
            if ws_path.exists():
                ws_age = (time.time() - ws_path.stat().st_mtime) / 60
                if ws_age < 60:  # Less than 1 hour old
                    self._restore_workspace_state(ws_path)
                    return

            # Fall back to individual autosave notification
            autosaves = sorted(
                AUTOSAVE_DIR.glob("autosave-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if not autosaves:
                return
            latest = autosaves[0]
            age_minutes = (time.time() - latest.stat().st_mtime) / 60
            if age_minutes < 60:  # Only offer if less than 1 hour old
                self._add_system_message(
                    f"Auto-save found ({age_minutes:.0f} min ago). "
                    "Use /autosave restore to recover."
                )
        except OSError:
            logger.debug("failed to check autosave recovery", exc_info=True)

    # ── System Prompt (/system) ──────────────────────────────────────────

    def _update_system_indicator(self) -> None:
        """Update the status bar system prompt indicator."""
        try:
            indicator = self.query_one("#status-system", Static)
        except NoMatches:
            return

        if self._system_prompt:
            if self._system_preset_name:
                indicator.update(f"\U0001f3ad {self._system_preset_name}")
            else:
                # Show truncated custom prompt
                short = self._system_prompt[:20].replace("\n", " ")
                if len(self._system_prompt) > 20:
                    short += "\u2026"
                indicator.update(f"\U0001f3ad {short}")
        else:
            indicator.update("")
        self._update_breadcrumb()

    def _autosave_restore(self, file_index: int | None = None) -> None:
        """Show available auto-saves or restore one by number."""
        try:
            autosaves = sorted(
                AUTOSAVE_DIR.glob("autosave-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            logger.debug("failed to list autosaves", exc_info=True)
            autosaves = []

        if not autosaves:
            self._add_system_message("No auto-saves found")
            return

        # If a number was given, restore that file directly
        if file_index is not None:
            if file_index < 1 or file_index > len(autosaves[:10]):
                self._add_system_message(
                    f"Invalid auto-save number: {file_index}. "
                    f"Valid range: 1–{min(len(autosaves), 10)}"
                )
                return
            self._restore_autosave_file(autosaves[file_index - 1])
            return

        # No number — list available auto-saves with restore instructions
        lines = ["Available auto-saves:"]
        for i, f in enumerate(autosaves[:10], 1):
            try:
                age = (time.time() - f.stat().st_mtime) / 60
                size = f.stat().st_size / 1024
                data = json.loads(f.read_text(encoding="utf-8"))
                title = data.get("session_title", "")
                msg_count = data.get("message_count", "?")
                label = f" — {title}" if title else ""
                lines.append(
                    f"  {i}. {f.name} "
                    f"({age:.0f} min ago, {size:.1f} KB, "
                    f"{msg_count} msgs{label})"
                )
            except (OSError, json.JSONDecodeError):
                logger.debug("failed to read autosave metadata", exc_info=True)
                lines.append(f"  {i}. {f.name}")

        lines.append("")
        lines.append("Restore commands:")
        lines.append(
            "  /autosave restore N          Restore auto-save #N into a new tab"
        )
        lines.append(
            "  /autosave restore workspace  Restore all tabs from last session"
        )

        # Check for workspace state
        ws_path = AUTOSAVE_DIR / "workspace-state.json"
        if ws_path.exists():
            try:
                ws = json.loads(ws_path.read_text(encoding="utf-8"))
                tab_count = len(ws.get("tabs", []))
                ws_age = (time.time() - ws_path.stat().st_mtime) / 60
                lines.append(
                    f"\nWorkspace state: {tab_count} tab(s), saved {ws_age:.0f} min ago"
                )
            except (OSError, json.JSONDecodeError):
                pass

        lines.append(f"\nAuto-save files are in: {AUTOSAVE_DIR}")
        self._add_system_message("\n".join(lines))

    def _restore_autosave_file(self, filepath: Path) -> None:
        """Restore messages from a single auto-save file into a new tab."""
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._add_system_message(f"Failed to read auto-save: {exc}")
            return

        messages = data.get("messages", [])
        if not messages:
            self._add_system_message("Auto-save file contains no messages.")
            return

        tab_name = data.get("tab_name", "Restored")
        title = data.get("session_title", "")
        label = f" — {title}" if title else ""

        # If current tab already has messages, create a new tab
        if self._search_messages:
            self._create_new_tab(name=f"Restored: {tab_name}", show_welcome=False)
        else:
            # Reuse current empty tab — clear welcome screen
            self._clear_welcome()

        # Replay messages
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                self._add_user_message(content)
            elif role == "assistant":
                self._add_assistant_message(content)

        self._add_system_message(
            f"Restored {len(messages)} messages from {filepath.name}{label}"
        )

    def _restore_workspace_from_command(self) -> None:
        """Handle /autosave restore workspace command."""
        ws_path = AUTOSAVE_DIR / "workspace-state.json"
        if not ws_path.exists():
            self._add_system_message("No workspace state found.")
            return
        self._restore_workspace_state(ws_path)

    def _restore_workspace_state(self, ws_path: Path) -> None:
        """Restore full workspace (all tabs) from workspace-state.json."""
        try:
            ws = json.loads(ws_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._add_system_message(f"Failed to read workspace state: {exc}")
            return

        tabs_data = ws.get("tabs", [])
        if not tabs_data:
            self._add_system_message("Workspace state contains no tabs.")
            return

        saved_active = ws.get("active_tab_index", 0)
        restored_count = 0

        for tab_idx, tab_info in enumerate(tabs_data):
            autosave_file = tab_info.get("autosave_file")
            tab_name = tab_info.get("name", f"Tab {tab_idx + 1}")

            if not autosave_file:
                # Tab had no messages — create empty tab if not the first
                if tab_idx > 0:
                    self._create_new_tab(name=tab_name, show_welcome=False)
                restored_count += 1
                continue

            # Load the autosave data
            filepath = AUTOSAVE_DIR / autosave_file
            if not filepath.exists():
                if tab_idx > 0:
                    self._create_new_tab(name=tab_name, show_welcome=False)
                restored_count += 1
                continue

            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.debug(
                    "failed to read tab autosave during restore", exc_info=True
                )
                if tab_idx > 0:
                    self._create_new_tab(name=tab_name, show_welcome=False)
                restored_count += 1
                continue

            messages = data.get("messages", [])

            if tab_idx == 0:
                # First tab — use existing tab-0, just clear welcome
                self._clear_welcome()
            else:
                self._create_new_tab(name=tab_name, show_welcome=False)

            # Replay messages
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    self._add_user_message(content)
                elif role == "assistant":
                    self._add_assistant_message(content)

            restored_count += 1

        # Switch to the tab that was active when saved
        if saved_active < len(self._tabs) and saved_active != self._active_tab_index:
            self._switch_to_tab(saved_active)

        self._add_system_message(f"Workspace restored: {restored_count} tab(s)")

    # ── Crash-recovery draft (global, plain-text) ─────────────────

    def _save_crash_draft(self) -> None:
        """Save current input to global crash-recovery draft file."""
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            text = input_widget.text.strip()
            self._draft_store.save_crash(text)
        except OSError:
            logger.debug("failed to save crash draft", exc_info=True)

    def _clear_crash_draft(self) -> None:
        """Clear the global crash-recovery draft file."""
        self._draft_store.clear_crash()

    def _load_crash_draft(self) -> str | None:
        """Load crash-recovery draft if it exists and is non-empty."""
        return self._draft_store.load_crash()

    # ── Bookmarks ─────────────────────────────────────────────

    def _get_session_id(self) -> str | None:
        """Return the current session ID, or None."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        return getattr(sm, "session_id", None) if sm else None

    def _get_session_project_dir(self) -> str:
        """Return the active session's project directory, falling back to cwd.

        Looks up the ``project_path`` from the cached session list using the
        active session ID.  This means ``/commit``, ``/git``, and similar
        commands operate in the *session's* project -- not the directory the
        TUI was launched from.
        """
        import os

        sid = self._get_session_id()
        if sid:
            from pathlib import Path

            for s in getattr(self, "_session_list_data", []):
                if s.get("session_id") == sid:
                    pp = s.get("project_path")
                    if pp and Path(pp).is_dir():
                        return str(pp)
                    break
        return os.getcwd()

    def _load_bookmarks(self) -> dict[str, list[dict]]:
        """Load all bookmarks from the JSON file."""
        return self._bookmark_store.load_all()

    def _save_bookmark(self, session_id: str, bookmark: dict) -> None:
        """Append a bookmark for the given session."""
        self._bookmark_store.add(session_id, bookmark)

    def _load_session_bookmarks(self, session_id: str | None = None) -> list[dict]:
        """Load bookmarks for the current (or given) session."""
        sid = session_id or self._get_session_id()
        return self._bookmark_store.for_session(sid)

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
        return self._ref_store.load_all()

    def _save_refs(self) -> None:
        """Persist the current session's refs to disk."""
        sid = self._get_session_id()
        if not sid:
            return
        self._ref_store.save(sid, self._session_refs)

    def _load_session_refs(self, session_id: str | None = None) -> list[dict]:
        """Load refs for the current (or given) session."""
        sid = session_id or self._get_session_id()
        return self._ref_store.for_session(sid)

    def _load_message_pins(self) -> list[dict]:
        """Load pinned messages for the current session."""
        sid = self._get_session_id() or "default"
        return self._pin_store.load(sid)

    def _save_message_pins(self) -> None:
        """Persist message pins keyed by session ID."""
        sid = self._get_session_id() or "default"
        self._pin_store.save(sid, self._message_pins)

    # ── Session Notes ─────────────────────────────────────────────────

    def _load_notes(self) -> list[dict]:
        """Load notes for the current session."""
        sid = self._get_session_id()
        if not sid:
            return []
        return self._note_store.load(sid)

    def _save_notes(self) -> None:
        """Persist session notes keyed by session ID."""
        sid = self._get_session_id()
        if not sid:
            return
        self._note_store.save(sid, self._session_notes)

    def _add_message_pin(self, index: int, content: str, label: str = "") -> None:
        """Pin a message by its _search_messages index."""
        preview = content[:80].replace("\n", " ")
        if len(content) > 80:
            preview += "..."

        # Check if already pinned
        for pin in self._message_pins:
            if pin["index"] == index:
                self._add_system_message(f"Message {index + 1} is already pinned")
                return

        role = self._search_messages[index][0]
        self._message_pins.append(
            {
                "index": index,
                "role": role,
                "preview": preview,
                "content": content[:2000],
                "label": label,
                "pinned_at": datetime.now().isoformat(),
            }
        )
        self._save_message_pins()
        self._update_pinned_panel()

        # Apply visual indicator to the message widget
        widget = self._search_messages[index][2]
        if widget is not None:
            widget.add_class("pinned")

        pin_num = len(self._message_pins)
        role_label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(role, role)
        label_suffix = f" [{label}]" if label else ""
        self._add_system_message(
            f"\U0001f4cc Pinned #{pin_num} ({role_label} msg #{index + 1}){label_suffix}: {preview}"
        )

    def _apply_pin_classes(self) -> None:
        """Re-apply the 'pinned' CSS class to pinned messages after session restore."""
        if not self._message_pins:
            return
        total = len(self._search_messages)
        for pin in self._message_pins:
            idx = pin["index"]
            if idx < total:
                widget = self._search_messages[idx][2]
                if widget is not None:
                    widget.add_class("pinned")

    def _remove_all_pin_classes(self) -> None:
        """Remove 'pinned' CSS class from all currently pinned message widgets."""
        total = len(self._search_messages)
        for pin in self._message_pins:
            idx = pin["index"]
            if idx < total:
                widget = self._search_messages[idx][2]
                if widget is not None:
                    widget.remove_class("pinned")

    def _remove_pin(self, n: int) -> None:
        """Remove pin number *n* (1-based) and update visual indicator."""
        if not self._message_pins:
            self._add_system_message("No pins to remove.")
            return
        if 1 <= n <= len(self._message_pins):
            removed = self._message_pins.pop(n - 1)
            # Remove visual indicator
            idx = removed["index"]
            if idx < len(self._search_messages):
                widget = self._search_messages[idx][2]
                if widget is not None:
                    widget.remove_class("pinned")
            self._save_message_pins()
            self._update_pinned_panel()
            preview = removed["preview"][:40]
            self._add_system_message(f"Unpinned #{n}: {preview}...")
        else:
            total = len(self._message_pins)
            self._add_system_message(f"Pin #{n} not found (valid: 1-{total})")

    def _update_pinned_panel(self) -> None:
        """Refresh the pinned-messages panel at the top of the chat area."""
        try:
            panel = self.query_one("#pinned-panel", PinnedPanel)
        except NoMatches:
            return

        panel.remove_children()

        if not self._message_pins:
            panel.display = False
            return

        panel.display = True

        # Header line (click to collapse/expand)
        count = len(self._message_pins)
        if self._pinned_panel_collapsed:
            header_text = f"\U0001f4cc Pinned ({count}) \u25b6"
        else:
            header_text = f"\U0001f4cc Pinned ({count}) \u25bc"
        header = PinnedPanelHeader(header_text, id="pinned-panel-header")
        panel.mount(header)

        if self._pinned_panel_collapsed:
            return

        total = len(self._search_messages)
        for i, pin in enumerate(self._message_pins, 1):
            idx = pin["index"]
            if idx < total:
                role = self._search_messages[idx][0]
            else:
                role = pin.get("role", "?")
            role_label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                role, role
            )
            pin_label = pin.get("label", "")
            label_str = f" [{pin_label}]" if pin_label else ""
            preview = pin["preview"][:60]
            item = PinnedPanelItem(
                pin_number=i,
                msg_index=idx,
                content=f"  {i}. {role_label}{label_str}: {preview}",
                classes="pinned-panel-item",
            )
            panel.mount(item)

    def _scroll_to_pinned_message(self, msg_index: int) -> None:
        """Scroll the chat view to bring a pinned message into view."""
        if msg_index < len(self._search_messages):
            widget = self._search_messages[msg_index][2]
            if widget is not None:
                widget.scroll_visible(animate=True)
                # Briefly highlight the message
                widget.add_class("find-current")
                self.set_timer(2.0, lambda: widget.remove_class("find-current"))

    def _toggle_pinned_panel(self) -> None:
        """Toggle the pinned panel between collapsed and expanded."""
        self._pinned_panel_collapsed = not self._pinned_panel_collapsed
        self._update_pinned_panel()

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
            value = event.value
            if value.startswith(">"):
                # Search mode: show hint instead of filtering metadata
                tree = self.query_one("#session-tree", Tree)
                tree.clear()
                tree.show_root = False
                query_part = value[1:].strip()
                if query_part:
                    tree.root.add_leaf(
                        f"Press Enter to search transcripts for '{query_part}'"
                    )
                else:
                    tree.root.add_leaf("Type query after > to search inside sessions")
            else:
                self._filter_sessions(value)
        elif event.input.id == "find-input":
            self._find_execute_search(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the find-input or session-filter search mode."""
        if event.input.id == "session-filter":
            value = event.value
            if value.startswith(">"):
                query = value[1:].strip()
                if query:
                    self._active_search_query = query
                    self._last_search_query = query
                    self._sidebar_search_worker(query)
        elif event.input.id == "find-input":
            self._find_next()

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
            # Refresh smart prompt suggestions (skip on submission)
            if not isinstance(event, ChatInput.Submitted):
                self._refresh_suggestions()

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
        except NoMatches:
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
        """Handle special keys: find bar nav, Escape for cancel/focus/filter."""
        # -- Find bar navigation (when find-input is focused) --
        if self._find_visible:
            focused = self.focused
            if focused is not None and getattr(focused, "id", None) == "find-input":
                if event.key == "escape":
                    self._hide_find_bar()
                    event.prevent_default()
                    event.stop()
                    return
                if event.key == "shift+enter":
                    self._find_prev()
                    event.prevent_default()
                    event.stop()
                    return

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
                except NoMatches:
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
            except NoMatches:
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

    # -- Sidebar transcript search (> prefix / /search integration) ----------

    @work(thread=True)
    def _sidebar_search_worker(self, query: str) -> None:
        """Search transcripts across all sessions and populate the sidebar."""
        from .platform import amplifier_projects_dir

        # Show progress immediately
        self.call_from_thread(self._sidebar_search_show_progress, query)

        projects_dir = amplifier_projects_dir()
        if not projects_dir.exists():
            self.call_from_thread(self._display_search_results, [], query)
            return

        query_lower = query.lower()
        results: list[dict] = []

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue

            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Skip sub-sessions (agent delegations)
                if "_" in session_dir.name:
                    continue

                sid = session_dir.name
                transcript = session_dir / "transcript.jsonl"
                if not transcript.exists():
                    continue

                try:
                    mtime = transcript.stat().st_mtime
                except OSError:
                    continue

                # Read metadata
                meta_name = ""
                meta_desc = ""
                metadata_path = session_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                        meta_name = meta.get("name", "")
                        meta_desc = meta.get("description", "")
                    except (OSError, json.JSONDecodeError):
                        pass

                # Derive project name
                project_name = (
                    project_dir.name.rsplit("-", 1)[-1]
                    if "-" in project_dir.name
                    else project_dir.name
                )

                # Scan transcript for matches
                match_count = 0
                first_snippet = ""
                first_role = ""
                try:
                    with open(transcript, "r", encoding="utf-8") as fh:
                        for raw_line in fh:
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            try:
                                msg = json.loads(raw_line)
                            except json.JSONDecodeError:
                                continue
                            role = msg.get("role", "")
                            if role not in ("user", "assistant"):
                                continue
                            content = self._extract_transcript_text(
                                msg.get("content", "")
                            )
                            content_lower = content.lower()
                            start = 0
                            while True:
                                idx = content_lower.find(query_lower, start)
                                if idx == -1:
                                    break
                                match_count += 1
                                if match_count == 1:
                                    snip_start = max(0, idx - 40)
                                    snip_end = min(len(content), idx + len(query) + 40)
                                    snippet = content[snip_start:snip_end].replace(
                                        "\n", " "
                                    )
                                    if snip_start > 0:
                                        snippet = "..." + snippet
                                    if snip_end < len(content):
                                        snippet = snippet + "..."
                                    first_snippet = snippet
                                    first_role = role
                                start = idx + 1
                except OSError:
                    continue

                # Also check metadata fields
                for meta_field in (meta_name, meta_desc):
                    if meta_field and query_lower in meta_field.lower():
                        if not first_snippet:
                            first_snippet = meta_field.replace("\n", " ")[:100]
                            first_role = "metadata"
                            match_count = max(match_count, 1)
                        break

                if match_count > 0:
                    from datetime import datetime

                    results.append(
                        {
                            "session_id": sid,
                            "mtime": mtime,
                            "date_str": datetime.fromtimestamp(mtime).strftime(
                                "%m/%d %H:%M"
                            ),
                            "match_count": match_count,
                            "first_snippet": first_snippet,
                            "first_role": first_role,
                            "name": meta_name,
                            "description": meta_desc,
                            "project": project_name,
                        }
                    )

        # Sort by most recent first
        results.sort(key=lambda r: r["mtime"], reverse=True)

        # Store for /search open N
        self._last_search_results = results
        self._last_search_query = query

        self.call_from_thread(self._display_search_results, results, query)

    def _sidebar_search_show_progress(self, query: str) -> None:
        """Show a 'Searching...' indicator in the sidebar tree."""
        try:
            tree = self.query_one("#session-tree", Tree)
            tree.clear()
            tree.show_root = False
            tree.root.add_leaf(f"Searching for '{query}'...")
        except Exception:
            pass

    def _display_search_results(self, results: list[dict], query: str) -> None:
        """Populate the sidebar tree with cross-session search results."""
        try:
            tree = self.query_one("#session-tree", Tree)
        except Exception:
            return

        tree.clear()
        tree.show_root = False

        if not results:
            tree.root.add_leaf(f"No matches for '{query}'")
            return

        total_matches = sum(r["match_count"] for r in results)
        count_label = "match" if total_matches == 1 else "matches"
        sess_label = "session" if len(results) == 1 else "sessions"
        tree.root.add_leaf(
            f"{total_matches} {count_label} in {len(results)} {sess_label}"
        )

        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        # Group results by project
        current_project: str | None = None
        group_node = tree.root
        for r in results:
            project = r["project"]
            if project != current_project:
                current_project = project
                group_node = tree.root.add(project, expand=True)

            sid = r["session_id"]
            display = self._session_display_label(r, custom_names, session_titles)
            count = r["match_count"]
            count_str = f"({count} match{'es' if count != 1 else ''})"
            session_node = group_node.add(f"{display}  {count_str}", data=sid)
            # Show first snippet as a leaf
            if r["first_snippet"]:
                snippet = r["first_snippet"][:80]
                session_node.add_leaf(f"[{r['first_role']}] {snippet}")
            session_node.collapse()

        self._last_search_results = results
        self._active_search_query = query

    def _show_sidebar_search_results(self, results: list[dict], query: str) -> None:
        """Open sidebar and display search results (called from /search)."""
        # Open sidebar if not visible
        if not self._sidebar_visible:
            self.action_toggle_sidebar()

        # Set the filter input to >query
        try:
            self.query_one("#session-filter", Input).value = f">{query}"
        except Exception:
            pass

        self._display_search_results(results, query)

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#session-sidebar")
        self._sidebar_visible = not self._sidebar_visible
        sidebar.display = self._sidebar_visible
        if self._sidebar_visible:
            self._load_session_list()
            # Focus the filter input so user can start typing immediately
            self.query_one("#session-filter", Input).focus()
        else:
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

    def _ensure_rsearch_mgr(self) -> object:
        """Lazily create the :class:`ReverseSearchManager`.

        Deferred because ``self._history`` is not available during
        ``__init__``.
        """
        if self._rsearch_mgr is None:
            from .features.reverse_search import ReverseSearchManager

            self._rsearch_mgr = ReverseSearchManager(
                history=self._history,
                get_input=lambda: self.query_one("#chat-input", ChatInput),
                get_search_bar=lambda: self.query_one(
                    "#history-search-bar", HistorySearchBar
                ),
            )
        return self._rsearch_mgr

    def action_search_history(self) -> None:
        """Enter reverse-incremental search mode (Ctrl+R).

        Thin adapter — delegates to :class:`ReverseSearchManager`.
        """
        mgr = self._ensure_rsearch_mgr()
        mgr.start(add_message=self._add_system_message)  # type: ignore[union-attr]
        self._rsearch_active = mgr.active  # type: ignore[union-attr]

    # ── Reverse search helpers ────────────────────────────────────

    def _handle_rsearch_key(self, widget: ChatInput, event: object) -> bool:
        """Handle a key press while reverse search is active.

        Thin adapter — delegates to :meth:`ReverseSearchManager.handle_key`.
        """
        mgr = self._ensure_rsearch_mgr()
        result = mgr.handle_key(event)  # type: ignore[union-attr]
        self._rsearch_active = mgr.active  # type: ignore[union-attr]
        return result

    def _rsearch_cycle_next(self) -> None:
        """Thin adapter — delegates to :meth:`ReverseSearchManager.cycle_next`."""
        mgr = self._ensure_rsearch_mgr()
        mgr.cycle_next()  # type: ignore[union-attr]

    def _rsearch_cycle_prev(self) -> None:
        """Thin adapter — delegates to :meth:`ReverseSearchManager.cycle_prev`."""
        mgr = self._ensure_rsearch_mgr()
        mgr.cycle_prev()  # type: ignore[union-attr]

    def _do_rsearch(self) -> None:
        """Thin adapter — delegates to :meth:`ReverseSearchManager.do_search`."""
        mgr = self._ensure_rsearch_mgr()
        mgr.do_search()  # type: ignore[union-attr]

    def _rsearch_cancel(self) -> None:
        """Thin adapter — delegates to :meth:`ReverseSearchManager.cancel`."""
        mgr = self._ensure_rsearch_mgr()
        mgr.cancel()  # type: ignore[union-attr]
        self._rsearch_active = False

    def _rsearch_accept(self) -> None:
        """Thin adapter — delegates to :meth:`ReverseSearchManager.accept`."""
        mgr = self._ensure_rsearch_mgr()
        mgr.accept()  # type: ignore[union-attr]
        self._rsearch_active = False

    def _update_rsearch_display(self) -> None:
        """Thin adapter — delegates to :meth:`ReverseSearchManager.update_display`."""
        mgr = self._ensure_rsearch_mgr()
        mgr.update_display()  # type: ignore[union-attr]

    def _clear_rsearch_display(self) -> None:
        """Thin adapter — delegates to :meth:`ReverseSearchManager.clear_display`."""
        mgr = self._ensure_rsearch_mgr()
        mgr.clear_display()  # type: ignore[union-attr]

    def action_search_chat(self) -> None:
        """Toggle the find-in-chat search bar (Ctrl+F)."""
        if self._find_visible:
            self._hide_find_bar()
        else:
            self._show_find_bar()

    # -- Find-in-chat helpers ------------------------------------------------

    def _show_find_bar(self, query: str = "") -> None:
        """Open the find bar and optionally pre-fill a query."""
        try:
            find_bar = self.query_one("#find-bar", FindBar)
            find_bar.display = True
            self._find_visible = True
            inp = self.query_one("#find-input", Input)
            if query:
                inp.value = query
            inp.focus()
        except NoMatches:
            logger.debug("Find bar widgets not found", exc_info=True)

    def _hide_find_bar(self) -> None:
        """Close the find bar, clear highlights, return focus to chat input."""
        try:
            find_bar = self.query_one("#find-bar", FindBar)
            find_bar.display = False
            self._find_visible = False
            self._find_clear_highlights()
            self._find_matches = []
            self._find_index = -1
            self.query_one("#chat-input", ChatInput).focus()
        except NoMatches:
            logger.debug("Find bar or chat input widget not found", exc_info=True)

    def _find_execute_search(self, query: str) -> None:
        """Search _search_messages for *query*, highlight matching widgets."""
        self._find_clear_highlights()
        self._find_matches = []
        self._find_index = -1

        if not query:
            self._find_update_counter()
            return

        search_q = query if self._find_case_sensitive else query.lower()

        for i, (_role, text, widget) in enumerate(self._search_messages):
            hay = text if self._find_case_sensitive else text.lower()
            if search_q in hay:
                self._find_matches.append(i)
                if widget is not None:
                    widget.add_class("find-match")
                    self._find_highlighted.add(i)

        if self._find_matches:
            self._find_index = 0
            self._find_scroll_to_current()

        self._find_update_counter()

    def _find_next(self) -> None:
        """Navigate to the next match."""
        if not self._find_matches:
            return
        self._find_index = (self._find_index + 1) % len(self._find_matches)
        self._find_scroll_to_current()
        self._find_update_counter()

    def _find_prev(self) -> None:
        """Navigate to the previous match."""
        if not self._find_matches:
            return
        self._find_index = (self._find_index - 1) % len(self._find_matches)
        self._find_scroll_to_current()
        self._find_update_counter()

    def _find_scroll_to_current(self) -> None:
        """Scroll the current match into view and mark it as active."""
        if self._find_index < 0 or self._find_index >= len(self._find_matches):
            return

        # Remove previous .find-current from all highlighted widgets
        for idx in self._find_highlighted:
            if idx < len(self._search_messages):
                w = self._search_messages[idx][2]
                if w is not None:
                    w.remove_class("find-current")

        msg_idx = self._find_matches[self._find_index]
        widget = self._search_messages[msg_idx][2]
        if widget is not None:
            widget.add_class("find-current")
            try:
                widget.scroll_visible()
            except (AttributeError, TypeError):
                logger.debug("Failed to scroll widget into view", exc_info=True)

    def _find_update_counter(self) -> None:
        """Update the '3/17' counter label in the find bar."""
        try:
            label = self.query_one("#find-count", Static)
            if not self._find_matches:
                label.update("0/0")
            else:
                label.update(f"{self._find_index + 1}/{len(self._find_matches)}")
        except NoMatches:
            logger.debug("Find count label not found", exc_info=True)

    def _find_clear_highlights(self) -> None:
        """Remove .find-match and .find-current from all highlighted widgets."""
        for idx in list(self._find_highlighted):
            if idx < len(self._search_messages):
                w = self._search_messages[idx][2]
                if w is not None:
                    w.remove_class("find-match")
                    w.remove_class("find-current")
        self._find_highlighted.clear()

    def _find_toggle_case(self) -> None:
        """Toggle case sensitivity and re-run the search."""
        self._find_case_sensitive = not self._find_case_sensitive
        try:
            btn = self.query_one("#find-case-btn", Static)
            if self._find_case_sensitive:
                btn.add_class("find-case-active")
            else:
                btn.remove_class("find-case-active")
            inp = self.query_one("#find-input", Input)
            self._find_execute_search(inp.value)
        except NoMatches:
            logger.debug("Find case button or input not found", exc_info=True)

    def action_scroll_chat_top(self) -> None:
        """Scroll chat to the very top (Ctrl+Home)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_home(animate=False)
        except NoMatches:
            logger.debug("Chat view not found for scroll_home", exc_info=True)

    def action_scroll_chat_bottom(self) -> None:
        """Scroll chat to the very bottom (Ctrl+End)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_end(animate=False)
        except NoMatches:
            logger.debug("Chat view not found for scroll_end", exc_info=True)

    def action_scroll_chat_up(self) -> None:
        """Scroll chat up by a small amount (Ctrl+Up)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_up(animate=False)
        except NoMatches:
            logger.debug("Chat view not found for scroll_up", exc_info=True)

    def action_scroll_chat_down(self) -> None:
        """Scroll chat down by a small amount (Ctrl+Down)."""
        try:
            chat = self._active_chat_view()
            chat.scroll_down(animate=False)
        except NoMatches:
            logger.debug("Chat view not found for scroll_down", exc_info=True)

    async def action_quit(self) -> None:
        """Clean up the Amplifier session before quitting.

        Cleanup must run in a @work(thread=True) worker because the session
        was created in a worker thread with its own asyncio event loop.
        Running async cleanup on Textual's main loop fails silently.
        """
        # Save any in-progress draft before exiting
        self._save_draft()

        # Save workspace state (all tabs) so it can be restored on next launch
        self._do_autosave()

        if self.session_manager and getattr(self.session_manager, "session", None):
            self._update_status("Saving session...")
            try:
                worker = self._cleanup_session_worker()
                await worker.wait()
            except Exception:
                logger.debug("Session cleanup failed during quit", exc_info=True)
        self.exit()

    @work(thread=True)
    async def _cleanup_session_worker(self) -> None:
        """End session in a worker thread with a proper async event loop."""
        if self.session_manager is None:
            return
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
        if self.session_manager is None:
            return
        try:
            await self.session_manager.end_session()
        except (OSError, RuntimeError):
            logger.debug("Failed to end session cleanly", exc_info=True)
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
        self._session_notes = []
        self._search_messages = []
        self._session_start_time = time.monotonic()
        self._update_pinned_panel()
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
            except NoMatches:
                logger.debug("Chat view not found for auto-scroll", exc_info=True)

    def action_toggle_focus_mode(self) -> None:
        """Toggle focus mode: hide all chrome, show only chat + input."""
        self._set_focus_mode(not self._focus_mode)

    def _set_focus_mode(self, enabled: bool) -> None:
        """Toggle focus mode (hides chrome for distraction-free chat).

        Uses .focus-mode CSS class for status bar / breadcrumb / pinned panel.
        Sidebar uses inline display (consistent with action_toggle_sidebar).
        """
        if enabled == self._focus_mode:
            return

        self._focus_mode = enabled
        if enabled:
            self._sidebar_was_visible_before_focus = self._sidebar_visible
            self.add_class("focus-mode")
            try:
                self.query_one("#session-sidebar").display = False
            except NoMatches:
                pass
            self._add_system_message("Focus mode ON (F11 or /focus to exit)")
        else:
            self.remove_class("focus-mode")
            if self._sidebar_was_visible_before_focus:
                try:
                    self.query_one("#session-sidebar").display = True
                except NoMatches:
                    pass
                self._sidebar_visible = True
            self._add_system_message("Focus mode OFF")

        # Keep input focused
        try:
            self.query_one("#chat-input", ChatInput).focus()
        except NoMatches:
            logger.debug("Chat input not found for focus", exc_info=True)

    def action_toggle_split_focus(self) -> None:
        """Switch focus between chat input, chat view, and split panel (Ctrl+T)."""
        if not self.has_class("split-mode"):
            return
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
            split_panel = self.query_one("#split-panel", ScrollableContainer)
            chat_view = self._active_chat_view()
        except NoMatches:
            logger.debug("Split focus widgets not found", exc_info=True)
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
        """Return the first available editor, platform-aware."""
        from .platform import editor_candidates

        for candidate in editor_candidates():
            if candidate and shutil.which(candidate):
                return candidate
        return None

    def action_open_editor(self) -> None:
        """Open $EDITOR for composing a longer prompt (Ctrl+G)."""
        editor = self._resolve_editor()
        if not editor:
            self._add_system_message(no_editor_message())
            return

        inp = self.query_one("#chat-input", ChatInput)
        current_text = inp.text

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            prefix="amplifier-prompt-",
            delete=False,
        ) as f:
            f.write(
                "# Compose your prompt below. Lines starting with # are stripped.\n"
                "# Save and close to submit. Empty file cancels.\n"
                "\n"
            )
            if current_text:
                f.write(current_text)
                f.write("\n")
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
                raw = f.read()
            # Strip comment lines (template header and user comments)
            lines = [ln for ln in raw.split("\n") if not ln.startswith("#")]
            new_text = "\n".join(lines).strip()

            if not new_text or new_text == current_text.strip():
                self._add_system_message("Editor closed with no changes — cancelled.")
                return

            inp.clear()
            inp.insert(new_text)
            inp.focus()

            # Auto-send if preference is enabled
            if self._prefs.display.editor_auto_send:
                self._submit_message()
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("Editor launch failed", exc_info=True)
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
        except NoMatches:
            logger.debug("Stash indicator widget not found", exc_info=True)

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
            try:
                self._clipboard_store.add(text, source="copy response")
            except OSError:
                pass
            preview = self._copy_preview(text)
            self._add_system_message(
                f"Copied last assistant message ({len(text)} chars)\nPreview: {preview}"
            )
        else:
            self._add_system_message(
                "Failed to copy — no clipboard tool available (install xclip or xsel)"
            )

    # ── Input Handling ──────────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle Enter in the chat input."""
        # Dismiss suggestions on submit
        try:
            self.query_one("#suggestion-bar", SuggestionBar).dismiss()
        except NoMatches:
            logger.debug("Suggestion bar not found on submit", exc_info=True)
        self._submit_message()

    def _refresh_suggestions(self) -> None:
        """Compute and display smart prompt suggestions based on current input."""
        try:
            bar = self.query_one("#suggestion-bar", SuggestionBar)
        except NoMatches:
            logger.debug("Suggestion bar not found for refresh", exc_info=True)
            return

        if not self._prefs.display.show_suggestions:
            bar.dismiss()
            return

        try:
            input_w = self.query_one("#chat-input", ChatInput)
        except NoMatches:
            logger.debug("Chat input not found for suggestions", exc_info=True)
            bar.dismiss()
            return

        if not input_w._suggestions_enabled:
            bar.dismiss()
            return

        prefix = input_w.text.strip()

        # Only suggest after 2+ characters (avoid noise on every keystroke)
        if len(prefix) < 2:
            bar.dismiss()
            return

        suggestions = self._get_suggestions(prefix)
        if suggestions:
            bar.set_suggestions(suggestions)
        else:
            bar.dismiss()

    def _get_suggestions(self, prefix: str) -> list[str]:
        """Get suggestions based on current input prefix."""
        suggestions: list[str] = []
        prefix_lower = prefix.lower()

        # 1. Slash commands (if starts with /)
        if prefix.startswith("/"):
            for cmd in SLASH_COMMANDS:
                if cmd.startswith(prefix) and cmd != prefix:
                    suggestions.append(cmd)
            return suggestions[:10]

        # 2. History matches (most recent first)
        history = getattr(self, "_history", None)
        if history:
            for entry in reversed(history.entries):
                if entry.lower().startswith(prefix_lower) and entry != prefix:
                    if entry not in suggestions:
                        suggestions.append(entry)

        # 3. Template matches
        for template in PROMPT_TEMPLATES:
            if template.lower().startswith(prefix_lower) and template != prefix:
                if template not in suggestions:
                    suggestions.append(template)

        return suggestions[:10]

    def _submit_message(self) -> None:
        """Extract text from input and send it."""
        input_widget = self.query_one("#chat-input", ChatInput)
        text = input_widget.text.strip()
        if not text:
            return
        if self.is_processing:
            # Queue message for after current turn completes (mid-turn steering)
            input_widget.clear()
            self._queued_message = text
            self._add_system_message(
                f"Queued (will send after current response): {text[:80]}{'...' if len(text) > 80 else ''}"
            )
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

        # Expand @@snippet mentions (e.g. @@review) before sending
        expanded = self._expand_snippet_mentions(text)

        # Expand @file mentions (e.g. @./src/main.py) before sending
        expanded = self._expand_at_mentions(expanded)

        # Prepend attached file contents (if any) and clear them
        expanded = self._build_message_with_attachments(expanded)

        # Prepend mode context when an Amplifier mode is active
        if self._active_mode:
            expanded = f"/mode {self._active_mode}\n{expanded}"

        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(expanded)

    # ── Slash Commands ────────────────────────────────────────

    def _handle_slash_command(self, text: str, _alias_depth: int = 0) -> None:
        """Route a slash command to the appropriate handler."""
        if _alias_depth > 5:
            self._add_system_message("Alias recursion limit reached")
            return

        # /! shorthand for /run  (parsed before normal dispatch)
        stripped = text.strip()
        if stripped.startswith("/!"):
            self._cmd_run(stripped[2:].strip())
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
            "/sessions": lambda: self._cmd_sessions(args),
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
            "/ts": self._cmd_timestamps,
            "/keys": self._cmd_keys,
            "/stats": lambda: self._cmd_stats(args),
            "/tokens": self._cmd_tokens,
            "/context": lambda: self._cmd_context(args),
            "/showtokens": lambda: self._cmd_showtokens(text),
            "/contextwindow": lambda: self._cmd_contextwindow(text),
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
            "/drafts": lambda: self._cmd_drafts(text),
            "/sort": lambda: self._cmd_sort(text),
            "/edit": self.action_open_editor,
            "/editor": lambda: self._cmd_editor(args),
            "/wrap": lambda: self._cmd_wrap(text),
            "/fold": lambda: self._cmd_fold(text),
            "/unfold": lambda: self._cmd_unfold(text),
            "/alias": lambda: self._cmd_alias(args),
            "/history": lambda: self._cmd_history(args),
            "/grep": lambda: self._cmd_grep(text),
            "/find": lambda: self._cmd_find(text),
            "/redo": lambda: self._cmd_retry(args),
            "/retry": lambda: self._cmd_retry(args),
            "/undo": lambda: self._cmd_undo(args),
            "/snippet": lambda: self._cmd_snippet(args),
            "/snippets": lambda: self._cmd_snippet(""),
            "/snip": lambda: self._cmd_snippet(args),
            "/template": lambda: self._cmd_template(args),
            "/templates": lambda: self._cmd_template(""),
            "/title": lambda: self._cmd_title(args),
            "/diff": lambda: self._cmd_diff(args),
            "/git": lambda: self._cmd_git(args),
            "/ref": lambda: self._cmd_ref(text),
            "/refs": lambda: self._cmd_ref(text),
            "/vim": lambda: self._cmd_vim(args),
            "/watch": lambda: self._cmd_watch(args),
            "/split": lambda: self._cmd_split(args),
            "/stream": lambda: self._cmd_stream(args),
            "/tab": lambda: self._cmd_tab(args),
            "/tabs": lambda: self._cmd_tab(""),
            "/palette": self.action_command_palette,
            "/commands": self.action_command_palette,
            "/run": lambda: self._cmd_run(args),
            "/shell": lambda: self._cmd_shell(args),
            "/terminal": lambda: self._cmd_terminal(args),
            "/include": lambda: self._cmd_include(args),
            "/autosave": lambda: self._cmd_autosave(args),
            "/system": lambda: self._cmd_system(args),
            "/note": lambda: self._cmd_note(args),
            "/notes": lambda: self._show_notes(),
            "/fork": lambda: self._cmd_fork(args),
            "/branches": lambda: self._cmd_branches(args),
            "/branch": lambda: self._cmd_branch(args),
            "/name": lambda: self._cmd_name(args),
            "/attach": lambda: self._cmd_attach(args),
            "/cat": lambda: self._cmd_cat(args),
            "/multiline": lambda: self._cmd_multiline(args),
            "/ml": lambda: self._cmd_multiline(args),
            "/suggest": lambda: self._cmd_suggest(args),
            "/progress": lambda: self._cmd_progress(args),
            "/mode": lambda: self._cmd_mode(args),
            "/modes": lambda: self._cmd_mode(""),
            "/tag": lambda: self._cmd_tag(args),
            "/tags": lambda: self._cmd_tag("list-all"),
            "/clipboard": lambda: self._cmd_clipboard(args),
            "/clip": lambda: self._cmd_clipboard(args),
            "/agents": lambda: self._cmd_agents(args),
            "/todo": lambda: self._cmd_todo_panel(args),
            "/tools": lambda: self._cmd_tools(args),
            "/recipe": lambda: self._cmd_recipe(args),
            "/compare": lambda: self._cmd_compare(args),
            "/replay": lambda: self._cmd_replay(args),
            "/plugins": lambda: self._cmd_plugins(args),
            "/dashboard": lambda: self._cmd_dashboard(args),
            "/monitor": lambda: self._cmd_monitor(args),
            "/workspace": lambda: self._cmd_workspace(args),
            "/environment": self._cmd_environment,
            "/env": self._cmd_environment,
            "/gitstatus": lambda: self._cmd_git(""),
            "/gs": lambda: self._cmd_git(""),
            "/auto": lambda: self._cmd_auto(args),
            "/skills": lambda: self._cmd_skills(args),
            "/commit": lambda: self._cmd_commit(args),
        }

        handler = handlers.get(cmd)
        if handler:
            handler()
        elif self._plugin_loader.execute_command(cmd.lstrip("/"), self, args):
            pass  # Plugin command handled
        else:
            self._add_system_message(
                f"Unknown command: {cmd}\nType /help for available commands."
            )

    def _cmd_help(self) -> None:
        help_text = (
            "Amplifier TUI Commands\n"
            "\n"
            "  /!            Shorthand for /run (/! git diff)\n"
            "  /agents       Show agent delegation tree (/agents history, /agents clear, /agents tree)\n"
            "  /alias        List/create/remove custom shortcuts\n"
            "  /attach       Attach file(s) to next message (/attach *.py, clear, remove N)\n"
            "  /auto         Set approval mode (/auto suggest|edit|full)\n"
            "  /autosave     Auto-save status, toggle, force save, restore (/autosave on|off|now|restore)\n"
            "  /bookmark     Bookmark last response (/bm alias) | /bookmark N (toggle Nth from bottom)\n"
            "  /bookmark     list | jump N | remove N | clear | <label>\n"
            "  /bookmarks    List bookmarks | /bookmarks <N> to jump\n"
            "  /branch       Alias for /fork\n"
            "  /cat          Display file contents in chat (/cat src/main.py)\n"
            "  /clear        Clear chat\n"
            "  /clip         Alias for /clipboard\n"
            "  /clipboard    Clipboard ring (/clip N|search|clear)\n"
            "  /colors       View/set text colors (/colors <role> <#hex>, /colors reset, presets, use)\n"
            "  /commit       Smart commit with AI-generated message\n"
            "  /compact      Toggle compact view mode (/compact on, /compact off)\n"
            "  /compare      Model A/B testing (/compare <a> <b>, off, pick, status, history)\n"
            "  /context      Visual context window usage bar\n"
            "  /contextwindow Set context window size (/contextwindow 128k, auto)\n"
            "  /copy         Copy last response | /copy last | /copy N | /copy all | /copy code\n"
            "  /dashboard    Session heatmap dashboard (/dashboard refresh|export|heatmap|summary|clear)\n"
            "  /delete       Delete session (with confirmation)\n"
            "  /diff         Show git diff (/diff staged|all|<file>|<f1> <f2>|HEAD~N)\n"
            "  /diff last    Re-show the most recent inline file-edit diff\n"
            "  /diff msgs    Compare assistant messages (/diff msgs, /diff msgs N M)\n"
            "  /draft        Show/save/clear/load input draft (/draft save, /draft clear, /draft load)\n"
            "  /drafts       List all saved drafts across sessions (/drafts clear to clear current)\n"
            "  /edit         Open $EDITOR for longer prompts (same as Ctrl+G)\n"
            "  /editor       Alias for /edit | /editor submit toggles auto-submit\n"
            "  /environment  Full Amplifier install diagnostics (/env alias)\n"
            "  /export       Export chat (md default) | /export <fmt> [path] | /export last [N] | clipboard\n"
            "  /find         Interactive find-in-chat bar (Ctrl+F) with match navigation\n"
            "  /focus        Toggle focus mode (/focus on, /focus off)\n"
            "  /fold         Fold last long message (/fold all, /fold none, /fold <N>, /fold threshold)\n"
            "  /fork         Fork conversation into a new tab (/fork N from bottom)\n"
            "  /git          Quick git operations (/git status|log|diff|branch|stash|blame)\n"
            "  /gitstatus    Quick git status overview (alias: /gs)\n"
            "  /grep         Search with options (/grep <pattern>, /grep -c <pattern> for case-sensitive)\n"
            "  /help         Show this help\n"
            "  /history      Browse input history (/history <N>, /history search <query>, /history clear)\n"
            "  /include      Include file contents (/include src/main.py, /include *.py --send)\n"
            "  /include tree Project directory tree (respects .gitignore)\n"
            "  /include git  Git status + recent diff summary\n"
            "  /include recent Recently included files for quick re-include\n"
            "  /include preview <path> File preview (language, lines, size)\n"
            "                Also: @./path/to/file in your prompt auto-includes\n"
            "  /info         Show session details (ID, model, project, counts)\n"
            "  /keys         Keyboard shortcut overlay\n"
            "  /mode         Amplifier modes (/mode <name>, /mode off, /modes to list)\n"
            "  /model        Show/switch model | /model list | /model <name>\n"
            "  /monitor      Live session monitor (/monitor big|small|close)\n"
            "  /multiline    Toggle multiline mode (/multiline on, /multiline off, /ml)\n"
            "  /name         Name session (/name <text>, /name clear, /name to show)\n"
            "  /new          New session\n"
            "  /note         Add a session note (/note <text>, /note list, /note clear)\n"
            "  /notes        List all session notes (alias for /note list)\n"
            "  /notify       Toggle notifications (/notify on|off|sound|silent|flash|<secs>)\n"
            "  /palette      Command palette (Ctrl+P) – fuzzy search all commands\n"
            "  /pin          Pin message (/pin, /pin N, /pin list, /pin clear, /pin remove N)\n"
            "  /pin-session  Pin/unpin session (pinned appear at top of sidebar)\n"
            "  /pins         List all pinned messages (alias for /pin list)\n"
            "  /plugins      List loaded plugins (/plugins reload, /plugins help)\n"
            "  /prefs        Show preferences\n"
            "  /progress     Toggle detailed progress labels (/progress on, /progress off)\n"
            "  /quit         Quit\n"
            "  /recipe       Recipe pipeline view (/recipe status|history|clear)\n"
            "  /redo         Alias for /retry\n"
            "  /ref          Save a URL/reference (/ref <url> [label], /ref remove/clear/export)\n"
            "  /refs         List all saved references (same as /ref with no args)\n"
            "  /rename       Rename current tab (/rename <name>, /rename reset)\n"
            "  /replay       Session replay (/replay [id], pause, resume, skip, stop, speed, timeline)\n"
            "  /retry        Undo last exchange & re-send (/retry <text> to modify)\n"
            "  /run          Run shell command inline (/run ls -la, /run git status)\n"
            "  /scroll       Toggle auto-scroll on/off\n"
            "  /search       Search across all sessions | /search here <q> for current chat\n"
            "  /search open  Open result N from last search (/search open 3)\n"
            "  /sessions     Session manager (list, search, recent, open, delete, info)\n"
            "  /shell        Drop to interactive shell (type 'exit' to return)\n"
            "  /showtokens   Toggle token/context usage in status bar (/showtokens on|off)\n"
            "  /skills       Browse available skills (/skills, /skills <name>)\n"
            "  /snip         Alias for /snippet (/snip save, /snip use, /snip <name>)\n"
            "  /snippet      Prompt snippets (/snippet save|use|delete|search|cat|tag|export|import|<name>)\n"
            "  /sort         Sort sessions: date, name, project (/sort <mode>)\n"
            "  /sound        Toggle notification sound (/sound on|off|test)\n"
            "  /split        Toggle split view (/split [N|swap|off|pins|chat|file <path>])\n"
            "  /stats        Show session statistics | /stats tools | /stats tokens | /stats time\n"
            "  /stream       Toggle streaming display (/stream on, /stream off)\n"
            "  /suggest      Toggle smart prompt suggestions (/suggest on, /suggest off)\n"
            "  /system       Set/view system prompt (/system <text>, clear, presets, use <preset>, append)\n"
            "  /tab          Tab management (/tab new|switch|close|rename|list)\n"
            "  /tabs         List all open tabs\n"
            "  /tag          Session tags (/tag add|remove|list <tag>)\n"
            "  /tags         List all tags across all sessions with counts\n"
            "  /template     Prompt templates with {{variables}} (/template save|use|remove|clear|<name>)\n"
            "  /terminal     Toggle embedded terminal panel (/terminal big|small|close)\n"
            "  /theme        Switch color theme (/theme preview, /theme preview <name>, /theme revert)\n"
            "  /timestamps   Toggle message timestamps on/off (alias: /ts)\n"
            "  /title        View/set session title (/title <text> or /title clear)\n"
            "  /todo         Toggle live todo panel (auto-shows when agent uses todo tool)\n"
            "  /tokens       Detailed token / context usage breakdown\n"
            "  /tools        Live tool call log (/tools live|log|stats|clear)\n"
            "  /undo         Remove last exchange (/undo <N> for last N exchanges)\n"
            "  /unfold       Unfold last folded message (/unfold all to unfold all)\n"
            "  /unpin <N>    Remove a pin by its pin number\n"
            "  /vim          Toggle vim keybindings (/vim on, /vim off)\n"
            "  /watch        Watch files for changes (/watch <path>, stop, diff)\n"
            "  /workspace    Show or set project workspace (/workspace <path>)\n"
            "  /wrap         Toggle word wrap on/off (/wrap on, /wrap off)\n"
            "\n"
            "Key Bindings  (press F1 for full overlay)\n"
            "\n"
            "  Enter         Send message\n"
            "  Shift+Enter   Insert newline (multi-line input)\n"
            "  Ctrl+J        Insert newline (alt)\n"
            "  Up/Down       Browse prompt history\n"
            "  F1            Keyboard shortcuts overlay\n"
            "  F2            Rename current tab\n"
            "  F11           Toggle focus mode (hide chrome)\n"
            "  Ctrl+A        Toggle auto-scroll\n"
            "  Ctrl+F        Find in chat (interactive search bar)\n"
            "  Ctrl+R        Reverse search prompt history (Ctrl+S for forward)\n"
            "  Ctrl+G        Open $EDITOR for longer prompts\n"
            "  Ctrl+Y        Copy last response to clipboard (Ctrl+Shift+C also works)\n"
            "  Ctrl+M        Bookmark last response\n"
            "  Ctrl+S        Stash/restore prompt (stack of 5)\n"
            "  Ctrl+B        Toggle sidebar (vim normal: toggle bookmark)\n"
            "  Ctrl+N        New session\n"
            "  Ctrl+L        Clear chat\n"
            "  Escape        Cancel streaming generation\n"
            "  Ctrl+P        Command palette (fuzzy search all commands)\n"
            "  Ctrl+T        New conversation tab\n"
            "  Ctrl+W        Close current tab\n"
            "  Ctrl+PgUp/Dn  Switch between tabs\n"
            "  Alt+Left/Right Prev/next tab\n"
            "  Alt+1-9       Jump to tab 1-9\n"
            "  Alt+0         Jump to last tab\n"
            "  Ctrl+Home     Jump to top of chat\n"
            "  Ctrl+End      Jump to bottom of chat\n"
            "  Ctrl+Up/Down  Scroll chat up/down\n"
            "  Home/End      Top/bottom of chat (when input empty)\n"
            "  Ctrl+Q        Quit\n"
            "\n"
            "Vim Normal Mode (when /vim is on)\n"
            "\n"
            "  Ctrl+B        Toggle bookmark on last message\n"
            "  [             Jump to previous bookmark\n"
            "  ]             Jump to next bookmark"
        )
        self._add_system_message(help_text)

    @staticmethod
    def _is_binary(path: Path) -> bool:
        """Check if a file appears to be binary."""
        try:
            chunk = path.read_bytes()[:8192]
            return b"\x00" in chunk
        except OSError:
            logger.debug(
                "Failed to read file for binary check: %s", path, exc_info=True
            )
            return True

    def _read_file_for_include(self, path: Path) -> str | None:
        """Read a file and format it for inclusion in a prompt."""
        if not path.is_file():
            self._add_system_message(f"Not a file: {path}")
            return None

        if self._is_binary(path):
            self._add_system_message(f"Skipping binary file: {path.name}")
            return None

        size = path.stat().st_size
        if size > MAX_INCLUDE_SIZE:
            self._add_system_message(
                f"File too large: {path.name} ({size / 1024:.1f} KB). "
                f"Max: {MAX_INCLUDE_SIZE / 1024:.0f} KB"
            )
            return None

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("Failed to read file for include: %s", path, exc_info=True)
            self._add_system_message(f"Error reading {path.name}: {e}")
            return None

        lines = text.splitlines()
        lang = EXTENSION_TO_LANGUAGE.get(path.suffix.lower(), "")

        truncated = ""
        if len(lines) > MAX_INCLUDE_LINES:
            text = "\n".join(lines[:MAX_INCLUDE_LINES])
            truncated = f"\n... ({len(lines) - MAX_INCLUDE_LINES} more lines)"

        header = f"# {path.name} ({len(lines)} lines)"
        return f"{header}\n```{lang}\n{text}{truncated}\n```"

    def _include_into_input(self, content: str) -> None:
        """Insert content into the chat input, appending if there's existing text."""
        input_widget = self.query_one("#chat-input", ChatInput)
        current = input_widget.text.strip()
        input_widget.clear()
        if current:
            input_widget.insert(f"{current}\n\n{content}")
        else:
            input_widget.insert(content)

    def _include_and_send(self, content: str) -> None:
        """Set content into the input and immediately submit it."""
        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget.clear()
        input_widget.insert(content)
        self._submit_message()

    def _expand_at_mentions(self, text: str) -> str:
        """Expand @file references in input text.

        Only matches paths that start with ./, ../, ~/, or /
        to avoid matching @usernames.
        """

        def _replace_at_file(match: re.Match[str]) -> str:
            filepath = match.group(1)
            path = Path(filepath).expanduser()
            if not path.exists():
                path = Path.cwd() / filepath
            if path.exists() and path.is_file():
                content = self._read_file_for_include(path)
                if content:
                    return content
            return match.group(0)  # Keep original if file not found

        # Match @path/to/file.ext — platform-aware (includes C:\ on Windows)
        from .platform import AT_MENTION_RE

        return AT_MENTION_RE.sub(_replace_at_file, text)

    def _expand_snippet_mentions(self, text: str) -> str:
        """Expand @@name references to snippet content.

        Matches @@word-boundary identifiers (alphanumeric + hyphens/underscores)
        and replaces them with the saved snippet content.  Unknown @@names are
        left as-is so the user sees them in the output.
        """

        def _replace_snippet(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in self._snippets:
                return self._snippet_content(self._snippets[name])
            return match.group(0)  # keep original if not found

        return re.sub(r"@@([\w-]+)", _replace_snippet, text)

    # -- /attach and /cat helpers -----------------------------------------------

    def _attach_file(self, path: Path) -> None:
        """Attach a single file."""
        if self._is_binary(path):
            self._add_system_message(f"Skipping binary file: {path.name}")
            return

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("Failed to read file for attach: %s", path, exc_info=True)
            self._add_system_message(f"Error reading {path.name}: {e}")
            return

        ext = path.suffix.lower()
        lang = EXTENSION_TO_LANGUAGE.get(ext, "")
        size = len(content.encode("utf-8"))

        attachment = Attachment(
            path=path,
            name=path.name,
            content=content,
            language=lang,
            size=size,
        )
        self._attachments.append(attachment)

        total = sum(a.size for a in self._attachments)
        size_str = f"{size / 1024:.1f}KB"

        msg = f"Attached: {attachment.name} ({size_str})"
        if total > MAX_ATTACHMENT_SIZE:
            msg += f"\n  Total attachments: {total / 1024:.1f}KB (large — may use significant context)"

        self._add_system_message(msg)
        self._update_attachment_indicator()

    def _show_attachments(self) -> None:
        """Display currently attached files."""
        if not self._attachments:
            self._add_system_message(
                "No files attached.\n"
                "Usage: /attach <path>     Attach a file\n"
                "       /attach *.py       Attach by glob pattern\n"
                "       /attach clear      Remove all\n"
                "       /attach remove N   Remove by number"
            )
            return

        lines = ["Attached files:"]
        total = 0
        for i, att in enumerate(self._attachments, 1):
            total += att.size
            lines.append(f"  {i}. {att.name} ({att.size / 1024:.1f}KB)")
        lines.append(f"\nTotal: {total / 1024:.1f}KB")
        lines.append("These will be included with your next message.")
        self._add_system_message("\n".join(lines))

    def _update_attachment_indicator(self) -> None:
        """Show/hide attachment count near input."""
        try:
            indicator = self.query_one("#attachment-indicator", Static)
        except NoMatches:
            logger.debug("Attachment indicator not found", exc_info=True)
            return
        if self._attachments:
            count = len(self._attachments)
            total_kb = sum(a.size for a in self._attachments) / 1024
            names = ", ".join(a.name for a in self._attachments[:3])
            if count > 3:
                names += f" +{count - 3} more"
            indicator.update(f"Attached: {names} ({total_kb:.1f}KB)")
            indicator.display = True
        else:
            indicator.update("")
            indicator.display = False

    def _build_message_with_attachments(self, user_text: str) -> str:
        """Build the full message including attached files."""
        if not self._attachments:
            return user_text

        parts: list[str] = []
        for att in self._attachments:
            parts.append(f"File: {att.name}")
            parts.append(f"```{att.language}")
            parts.append(att.content)
            parts.append("```")
            parts.append("")

        parts.append(user_text)

        # Clear attachments after sending
        self._attachments.clear()
        self._update_attachment_indicator()

        return "\n".join(parts)

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

    def _edit_snippet_in_editor(self, name: str, content: str) -> None:
        """Edit a snippet in $EDITOR, reusing the Ctrl+G infrastructure."""
        editor = self._resolve_editor()
        if not editor:
            self._add_system_message(no_editor_message())
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
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("Snippet editor launch failed", exc_info=True)
            self._add_system_message(f"Could not open editor: {e}")
        finally:
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    @staticmethod
    def _extract_transcript_text(content: object) -> str:
        """Extract plain text from a transcript message content field.

        Assistant messages may store content as a list of typed blocks
        rather than a simple string.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return " ".join(parts)
        return ""

    def _resolve_session_id(self, partial: str) -> tuple[str | None, str]:
        """Resolve a partial session ID to a full one.

        Returns (session_id, error_message).  On success error_message is empty.
        """
        sessions = SessionManager.list_all_sessions(limit=500)

        # Exact match
        for s in sessions:
            if s["session_id"] == partial:
                return partial, ""

        # Prefix match
        matches = [s for s in sessions if s["session_id"].startswith(partial)]
        if len(matches) == 1:
            return matches[0]["session_id"], ""
        if len(matches) > 1:
            previews = [
                f"  {m['session_id'][:12]}...  {m['date_str']}" for m in matches[:5]
            ]
            return None, (
                f"Ambiguous ID '{partial}' matches {len(matches)} sessions:\n"
                + "\n".join(previews)
            )
        return None, f"No session found matching '{partial}'."

    def _session_label(
        self,
        info: dict,
        custom_names: dict[str, str],
        session_titles: dict[str, str],
    ) -> str:
        """Build a short display name for a session."""
        sid = info["session_id"]
        name = (
            custom_names.get(sid)
            or session_titles.get(sid)
            or info.get("name")
            or info.get("description")
            or sid[:12]
        )
        if len(name) > 40:
            name = name[:37] + "..."
        return name

    def _sessions_list(self) -> None:
        """List all saved sessions."""
        sessions = SessionManager.list_all_sessions(limit=200)
        if not sessions:
            self._add_system_message("No saved sessions found.")
            return

        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        lines = [f"Saved Sessions ({len(sessions)}):\n"]
        for s in sessions[:30]:
            label = self._session_label(s, custom_names, session_titles)
            project = s.get("project", "")
            sid_short = s["session_id"][:8]
            lines.append(f"  {s['date_str']}  [{sid_short}]  {label}")
            if project:
                lines.append(f"           project: {project}")

        if len(sessions) > 30:
            lines.append(f"\n... and {len(sessions) - 30} more")
        lines.append("\nUse /sessions open <id> to resume a session.")
        self._add_system_message("\n".join(lines))

    def _sessions_recent(self) -> None:
        """Show the 10 most recent sessions."""
        sessions = SessionManager.list_all_sessions(limit=10)
        if not sessions:
            self._add_system_message("No saved sessions found.")
            return

        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        lines = ["Recent Sessions:\n"]
        for i, s in enumerate(sessions, 1):
            label = self._session_label(s, custom_names, session_titles)
            sid_short = s["session_id"][:8]
            lines.append(f"  {i:2}. {s['date_str']}  [{sid_short}]  {label}")

        lines.append("\nUse /sessions open <id> to resume a session.")
        self._add_system_message("\n".join(lines))

    def _sessions_open(self, arg: str) -> None:
        """Open/resume a session by full or partial ID."""
        session_id, error = self._resolve_session_id(arg)
        if not session_id:
            self._add_system_message(error)
            return
        self._save_draft()
        self._resume_session_worker(session_id)

    def _sessions_delete(self, arg: str) -> None:
        """Delete a session by ID (delegates to /delete with confirmation)."""
        session_id, error = self._resolve_session_id(arg)
        if not session_id:
            self._add_system_message(error)
            return
        # Reuse the existing two-step delete flow
        self._cmd_delete(f"/delete {session_id}")

    def _sessions_info(self, arg: str) -> None:
        """Show detailed information about a session."""
        session_id, error = self._resolve_session_id(arg)
        if not session_id:
            self._add_system_message(error)
            return

        session_dir = self._find_session_dir(session_id)
        if not session_dir:
            self._add_system_message(f"Session directory not found for {arg}.")
            return

        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        # Read metadata
        meta: dict = {}
        metadata_path = session_dir / "metadata.json"
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.debug(
                    "Failed to read session metadata: %s", metadata_path, exc_info=True
                )

        # Count messages from transcript
        transcript_path = session_dir / "transcript.jsonl"
        msg_counts: Counter = Counter()
        first_user_msg = ""
        if transcript_path.exists():
            try:
                with open(transcript_path, "r", encoding="utf-8") as fh:
                    for raw_line in fh:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            msg = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue
                        role = msg.get("role", "unknown")
                        msg_counts[role] += 1
                        if role == "user" and not first_user_msg:
                            first_user_msg = self._extract_transcript_text(
                                msg.get("content", "")
                            )[:120]
            except OSError:
                pass

        # Build display
        mtime = session_dir.stat().st_mtime
        date_full = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

        display_name = (
            custom_names.get(session_id)
            or session_titles.get(session_id)
            or meta.get("name", "")
        )

        # Compute directory size
        total_bytes = sum(
            f.stat().st_size for f in session_dir.rglob("*") if f.is_file()
        )
        size_str = (
            f"{total_bytes / 1024:.1f} KB"
            if total_bytes < 1024 * 1024
            else f"{total_bytes / (1024 * 1024):.1f} MB"
        )

        lines = ["Session Info\n"]
        lines.append(f"  ID:          {session_id}")
        if display_name:
            lines.append(f"  Name:        {display_name}")
        if meta.get("description"):
            desc = meta["description"][:80]
            lines.append(f"  Description: {desc}")
        lines.append(f"  Last active: {date_full}")
        if meta.get("created"):
            lines.append(f"  Created:     {meta['created'][:19]}")
        if meta.get("model"):
            lines.append(f"  Model:       {meta['model']}")
        if meta.get("bundle"):
            lines.append(f"  Bundle:      {meta['bundle']}")
        lines.append(f"  Size:        {size_str}")
        total = sum(msg_counts.values())
        parts = ", ".join(f"{c} {r}" for r, c in msg_counts.most_common())
        lines.append(f"  Messages:    {total} ({parts})")
        if first_user_msg:
            preview = first_user_msg.replace("\n", " ")
            lines.append(f'\n  First message:\n    "{preview}"')
        lines.append(f"\n  /sessions open {session_id[:8]}   to resume")
        lines.append(f"  /sessions delete {session_id[:8]} to delete")
        self._add_system_message("\n".join(lines))

    def _cmd_prefs(self) -> None:
        from .preferences import PREFS_PATH

        c = self._prefs.colors
        e = self._prefs.environment
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
            "",
            "Environment\n",
            f"  workspace:            {e.workspace or '(not set)'}",
            "",
            f"Preferences file: {PREFS_PATH}",
            "Use /workspace <path> to set your project root.",
            "Use /environment for full install diagnostics.",
        ]
        self._add_system_message("\n".join(lines))

    def _cmd_workspace(self, args: str) -> None:
        """Show or set the workspace (project root) directory.

        /workspace          Show current workspace
        /workspace <path>   Set workspace to <path>
        """
        from .preferences import save_workspace

        arg = args.strip()
        if not arg:
            ws = self._prefs.environment.workspace
            if ws:
                self._add_system_message(
                    f"Workspace: {ws}\nUse /workspace <path> to change it."
                )
            else:
                self._add_system_message(
                    "No workspace configured.\n"
                    "Set your project root with: /workspace ~/dev/ANext"
                )
            return

        from pathlib import Path

        resolved = Path(arg).expanduser().resolve()
        if not resolved.is_dir():
            self._add_system_message(
                f"Directory not found: {resolved}\n"
                "The path must be an existing directory."
            )
            return

        save_workspace(str(resolved))
        self._prefs.environment.workspace = str(resolved)
        self._add_system_message(f"Workspace set to: {resolved}")

    def _cmd_environment(self) -> None:
        """Show full environment diagnostics and re-arm if now ready."""
        from .environment import check_environment, format_status

        status = check_environment(self._prefs.environment.workspace)
        self._add_system_message(format_status(status))

        # If the environment is now ready but we previously marked it
        # unavailable, re-arm so the next message will try to create a session.
        if status.ready and not self._amplifier_ready:
            self._amplifier_available = True
            self._amplifier_ready = True
            self._add_system_message(
                "Environment looks good now. Send a message to start a session."
            )

    def _cmd_auto(self, args: str) -> None:
        """Toggle approval automation level."""
        mode = args.strip().lower()
        valid_modes = ("suggest", "edit", "full")
        if not mode:
            current = getattr(self, "_auto_mode", "full")
            self._add_system_message(
                f"Approval mode: {current}\n"
                "  /auto suggest  - Confirm file writes and bash commands\n"
                "  /auto edit     - Auto-apply file edits, confirm bash\n"
                "  /auto full     - Auto-approve everything (default)"
            )
            return
        if mode not in valid_modes:
            self._add_system_message(f"Unknown mode: {mode}. Use: suggest, edit, full")
            return
        self._auto_mode = mode
        descriptions = {
            "suggest": "Will confirm file writes and bash commands",
            "edit": "Auto-applying file edits, confirming bash commands",
            "full": "Auto-approving all tool calls",
        }
        self._add_system_message(f"Approval mode set to: {mode}\n{descriptions[mode]}")

    def _cmd_skills(self, args: str) -> None:
        """Browse available skills."""
        from pathlib import Path
        import yaml as _yaml

        skill_dirs = []
        # Check workspace skills
        ws_skills = Path.cwd() / ".amplifier" / "skills"
        if ws_skills.is_dir():
            skill_dirs.append(("workspace", ws_skills))
        # Check user home skills
        home_skills = Path.home() / ".amplifier" / "skills"
        if home_skills.is_dir():
            skill_dirs.append(("user", home_skills))

        if not skill_dirs:
            self._add_system_message(
                "No skill directories found.\n"
                "Skills can be placed in:\n"
                "  .amplifier/skills/  (project)\n"
                "  ~/.amplifier/skills/ (user)"
            )
            return

        name = args.strip()
        if name and name != "load":
            # Show specific skill info
            for _source, sdir in skill_dirs:
                skill_file = sdir / f"{name}.md"
                if skill_file.exists():
                    try:
                        content = skill_file.read_text()
                        # Parse YAML frontmatter
                        if content.startswith("---"):
                            end = content.index("---", 3)
                            frontmatter = content[3:end].strip()
                            meta = _yaml.safe_load(frontmatter) or {}
                            desc = meta.get("description", "No description")
                            version = meta.get("version", "?")
                            self._add_system_message(
                                f"Skill: {name}\n"
                                f"  Version: {version}\n"
                                f"  Description: {desc}\n\n"
                                f"To load: /skills load {name}\n"
                                f"  (or ask the agent: 'load the {name} skill')"
                            )
                        else:
                            self._add_system_message(
                                f"Skill: {name}\n  (no metadata found)"
                            )
                    except Exception:
                        self._add_system_message(f"Error reading skill: {name}")
                    return
            self._add_system_message(f"Skill not found: {name}")
            return

        if args.strip().startswith("load "):
            # Send a message to the agent to load the skill
            skill_name = args.strip()[5:].strip()
            if skill_name and self._amplifier_ready:
                msg = f"Please load the skill: {skill_name}"
                self._add_user_message(msg)
                self._start_processing("Loading skill")
                self._send_message_worker(msg)
            return

        # List all skills
        lines = ["Available Skills\n"]
        for source, sdir in skill_dirs:
            found = sorted(sdir.glob("*.md"))
            if found:
                lines.append(f"  [{source}] {sdir}")
                for f in found:
                    skill_name_str = f.stem
                    # Try to read description from frontmatter
                    desc = ""
                    try:
                        text = f.read_text(errors="replace")[:500]
                        if text.startswith("---"):
                            end_idx = text.index("---", 3)
                            meta = _yaml.safe_load(text[3:end_idx]) or {}
                            desc = meta.get("description", "")
                    except Exception:
                        pass
                    suffix = f" - {desc}" if desc else ""
                    lines.append(f"    {skill_name_str}{suffix}")
                lines.append("")
        self._add_system_message("\n".join(lines))

    def _cmd_commit(self, args: str) -> None:
        """Smart commit: auto-stage, generate message, commit, and push.

        Runs in the active session's project directory (not the TUI launch dir).

        Usage:
            /commit          Stage all, generate message, commit, and push
            /commit nopush   Stage all, generate message, commit (skip push)
            /commit info     Show what would be committed (dry run)
        """
        import subprocess

        if not self._amplifier_ready:
            self._add_system_message("Amplifier not ready yet.")
            return

        cwd = self._get_session_project_dir()
        info_mode = "info" in args.lower()
        do_push = "nopush" not in args.lower() and not info_mode

        try:
            # Verify we're in a git repo
            check = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )
            if check.returncode != 0:
                self._add_system_message(f"Not a git repository: {cwd}")
                return

            # Get current branch
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )
            branch = branch_result.stdout.strip() or "(detached)"

            # Check for any changes (staged + unstaged + untracked)
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )
            if not status.stdout.strip():
                self._add_system_message("No changes to commit (working tree clean).")
                return

            # /commit info -- dry run: show what would be committed and stop
            if info_mode:
                from pathlib import Path

                project_label = Path(cwd).name
                # Categorise porcelain lines
                lines = status.stdout.strip().splitlines()
                staged = [ln for ln in lines if ln and ln[0] not in (" ", "?")]
                unstaged = [ln for ln in lines if len(ln) > 1 and ln[1] in ("M", "D")]
                untracked = [ln for ln in lines if ln.startswith("??")]
                parts = [
                    f"Project: **{project_label}** ({branch})",
                    f"Directory: `{cwd}`",
                    "",
                ]
                if staged:
                    parts.append(f"Already staged ({len(staged)}):")
                    parts.extend(f"  {ln}" for ln in staged)
                    parts.append("")
                if unstaged:
                    parts.append(f"Modified ({len(unstaged)}):")
                    parts.extend(f"  {ln}" for ln in unstaged)
                    parts.append("")
                if untracked:
                    parts.append(f"New files ({len(untracked)}):")
                    parts.extend(f"  {ln[3:]}" for ln in untracked)
                    parts.append("")
                total = len(staged) + len(unstaged) + len(untracked)
                parts.append(
                    f"/commit would stage **{total}** changes, "
                    f"generate a commit message, commit, and push."
                )
                parts.append("/commit nopush would do the same without pushing.")
                self._add_system_message("\n".join(parts))
                return

            # Auto-stage everything
            stage_result = subprocess.run(
                ["git", "add", "-A"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )
            if stage_result.returncode != 0:
                self._add_system_message(
                    f"Failed to stage changes: {stage_result.stderr.strip()}"
                )
                return

            # Get the diff summary and content for the LLM
            diff_summary = subprocess.run(
                ["git", "diff", "--staged", "--stat"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            ).stdout.strip()

            diff_content = subprocess.run(
                ["git", "diff", "--staged"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=cwd,
            ).stdout[:4000]

            from pathlib import Path

            project_label = Path(cwd).name

            # Show what we're doing
            self._add_system_message(
                f"Committing in **{project_label}** ({branch}):\n"
                f"```\n{diff_summary}\n```"
            )

            # Ask the agent to generate a commit message and execute
            push_instruction = (
                f"After committing, push to origin with: "
                f"`git -C {cwd} push origin {branch}`"
                if do_push
                else "Do NOT push after committing."
            )

            msg = (
                f"I'm committing changes in `{cwd}` on branch `{branch}`.\n\n"
                f"Staged changes:\n```\n{diff_summary}\n```\n\n"
                f"Diff (truncated):\n```\n{diff_content}\n```\n\n"
                f"Please:\n"
                f"1. Generate a concise git commit message using conventional commit "
                f"format (feat:, fix:, refactor:, docs:, etc).\n"
                f'2. Run the commit: `git -C {cwd} commit -m "<your message>"`\n'
                f"3. {push_instruction}\n\n"
                f"Use the Amplifier co-author trailer in the commit message."
            )
            self._add_user_message("/commit")
            self._start_processing("Generating commit")
            self._send_message_worker(msg)

        except subprocess.TimeoutExpired:
            self._add_system_message("Git command timed out.")
        except FileNotFoundError:
            self._add_system_message("Git not found in PATH.")
        except Exception as e:
            self._add_system_message(f"Error: {e}")

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

        # Append available models with descriptions
        lines.append("")
        lines.append("Available models:")
        catalog = {m[0]: m[2] for m in AVAILABLE_MODELS}
        available = self._get_available_models()
        for model, provider in available:
            marker = " \u2190" if model == current else "  "
            desc = catalog.get(model, "")
            desc_str = f"  {desc}" if desc else ""
            lines.append(f"  {provider:10s}  {model}{marker}{desc_str}")

        # Show aliases
        lines.append("")
        alias_names = sorted(MODEL_ALIASES)
        lines.append(f"Aliases: {', '.join(alias_names)}")
        lines.append("\nUsage: /model <name or alias>")

        self._add_system_message("\n".join(lines))

    # Well-known models derived from the module-level AVAILABLE_MODELS catalog.
    _KNOWN_MODELS: list[tuple[str, str]] = [
        (model_id, provider) for model_id, provider, _desc in AVAILABLE_MODELS
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
        catalog = {m[0]: m[2] for m in AVAILABLE_MODELS}

        lines = ["Available Models\n"]
        for name, provider in models:
            marker = "  (active)" if name == current else ""
            desc = catalog.get(name, "")
            lines.append(f"  {provider:10s}  {name}{marker}")
            if desc:
                lines.append(f"              {desc}")

        lines.append("")
        alias_names = sorted(MODEL_ALIASES)
        lines.append(f"Aliases: {', '.join(alias_names)}")
        lines.append("")
        lines.append("Switch: /model <name or alias>")
        has_session = bool(self.session_manager and self.session_manager.session)
        if has_session:
            lines.append("Takes effect immediately on the current session.")
        else:
            lines.append("Takes effect when the next session starts.")
        self._add_system_message("\n".join(lines))

    @staticmethod
    def _resolve_model_alias(name: str) -> str:
        """Resolve a model alias (case-insensitive) to its full model name."""
        return MODEL_ALIASES.get(name.lower(), name)

    def _cmd_model_set(self, name: str) -> None:
        """Switch the active model and save as preferred default."""
        # Resolve alias (case-insensitive)
        resolved = self._resolve_model_alias(name)
        was_alias = resolved != name

        sm = self.session_manager
        old_model = (
            (sm.model_name if sm else "") or self._prefs.preferred_model or "default"
        )

        # Persist preference for future sessions
        self._prefs.preferred_model = resolved
        save_preferred_model(resolved)

        # Try to switch the live session's provider immediately
        switched = sm.switch_model(resolved) if sm and sm.session else False

        self._update_token_display()
        self._update_breadcrumb()

        alias_note = f"  (alias: {name} \u2192 {resolved})" if was_alias else ""

        if switched:
            self._add_system_message(
                f"Model: {old_model} \u2192 {resolved}{alias_note}\n"
                "Next AI response will use this model."
            )
        else:
            self._add_system_message(
                f"Model: {old_model} \u2192 {resolved}{alias_note}\n"
                "Will take effect on the next session start."
            )

    def _update_multiline_status(self) -> None:
        """Update the status bar multiline mode indicator."""
        label = "[ML]" if self._prefs.display.multiline_default else ""
        try:
            self.query_one("#status-ml", Static).update(label)
        except NoMatches:
            logger.debug("status-ml widget not found", exc_info=True)

    def action_toggle_multiline(self) -> None:
        """Alt+M action: toggle multiline mode."""
        self._cmd_multiline("")

    # ── /suggest – smart prompt suggestions ──────────────────────────────────

    def _update_mode_display(self) -> None:
        """Update status bar indicator and input border for active mode."""
        # Update status bar mode indicator
        try:
            indicator = self.query_one("#status-mode", Static)
        except NoMatches:
            logger.debug("status-mode widget not found", exc_info=True)
            indicator = None

        if indicator is not None:
            if self._active_mode:
                mode = MODES[self._active_mode]
                indicator.update(mode["indicator"])
                indicator.styles.color = mode["accent"]
                indicator.styles.text_style = "bold"
            else:
                indicator.update("")

        # Update input border color to reflect mode
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
        except NoMatches:
            logger.debug("chat-input widget not found", exc_info=True)
            chat_input = None

        if chat_input is not None:
            if self._active_mode:
                mode = MODES[self._active_mode]
                chat_input.styles.border = ("solid", mode["accent"])
                chat_input.border_subtitle = mode["indicator"]
            else:
                # Reset to default (CSS will handle via :focus pseudo)
                chat_input.styles.border = ("solid", "$panel")
                chat_input.border_subtitle = ""

    # ── /split – side-by-side reference panel ────────────────────────────

    def _show_watch_diff(self, abs_path: str) -> None:
        """Show a unified diff for the last change to a watched file.

        Thin adapter — delegates to :meth:`FileWatcher._compute_diff`.
        """
        result = self._file_watcher.get_diff(abs_path)
        if result is not None:
            self._add_system_message(result)

    def _looks_like_commit_ref(self, text: str) -> bool:
        """Check if *text* looks like a git commit reference.

        Thin adapter — delegates to :func:`features.git_integration.looks_like_commit_ref`.
        """
        from .features.git_integration import looks_like_commit_ref

        return looks_like_commit_ref(text)

    def _colorize_diff(self, diff_text: str) -> str:
        """Apply Rich markup colors to diff output.

        Thin adapter — delegates to :func:`features.git_integration.colorize_diff`.
        """
        from .features.git_integration import colorize_diff

        return colorize_diff(diff_text)

    def _show_diff(self, diff_output: str, header: str = "") -> None:
        """Display colorized diff output, truncating if too large.

        Thin adapter — delegates to :func:`features.git_integration.show_diff`.
        """
        from .features.git_integration import show_diff

        self._add_system_message(show_diff(diff_output, header=header))

    # ------------------------------------------------------------------
    # /git command
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_preview(content: str, max_len: int = 100) -> str:
        """Return a short single-line preview of *content*."""
        preview = content[:max_len].replace("\n", " ")
        if len(content) > max_len:
            preview += "..."
        return preview

    def _refresh_timestamps(self) -> None:
        """Update all visible timestamp displays with current relative times."""
        if not self._prefs.display.show_timestamps:
            return
        for ts_widget in self.query(".msg-timestamp"):
            dt = getattr(ts_widget, "_created_at", None)
            if dt is None:
                continue
            content: str = getattr(ts_widget, "_meta_content", "")
            response_time: float | None = getattr(
                ts_widget, "_meta_response_time", None
            )
            parts: list[str] = [self._format_timestamp(dt)]
            if content:
                tokens = len(content) // 4
                if tokens > 0:
                    parts.append(f"~{tokens} tokens")
            if response_time is not None:
                parts.append(f"⏱ {response_time:.1f}s")
            ts_widget.update(" · ".join(parts))

    def _execute_undo(self, count: int, *, silent: bool = False) -> None:
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

        # Remove widgets from the DOM (message + adjacent meta / fold toggle)
        for _role, _content, widget in to_remove:
            if widget is None:
                continue

            # Remove adjacent meta and fold-toggle widgets after the message.
            # DOM order: [message] [meta?] [fold_toggle?]
            try:
                nxt = widget.next_sibling  # type: ignore[attr-defined]
                if nxt is not None and nxt.has_class("msg-timestamp"):
                    after_meta = nxt.next_sibling  # type: ignore[attr-defined]
                    nxt.remove()
                    nxt = after_meta
                if isinstance(nxt, FoldToggle):
                    nxt.remove()
            except (AttributeError, TypeError):
                logger.debug("failed to remove sibling widgets", exc_info=True)

            # Legacy: also check for old-style timestamp before the message
            try:
                prev_sib = widget.previous_sibling  # type: ignore[attr-defined]
                if prev_sib is not None and prev_sib.has_class("msg-timestamp"):
                    prev_sib.remove()
            except (AttributeError, TypeError):
                logger.debug("failed to remove legacy timestamp sibling", exc_info=True)

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

        if not silent:
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

    @staticmethod
    def _top_words(
        messages: list[tuple[str, str, object]], n: int = 10
    ) -> list[tuple[str, int]]:
        """Get top N most frequent meaningful words from messages."""
        stop_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "it",
            "this",
            "that",
            "and",
            "or",
            "but",
            "not",
            "no",
            "i",
            "you",
            "we",
            "they",
            "he",
            "she",
            "my",
            "your",
            "do",
            "does",
            "did",
            "have",
            "has",
            "had",
            "will",
            "would",
            "can",
            "could",
            "should",
            "if",
            "as",
            "so",
            "up",
            "out",
            "just",
            "also",
            "very",
            "all",
            "any",
            "some",
            "me",
            "its",
            "than",
            "then",
            "into",
            "about",
            "more",
            "when",
            "what",
            "how",
            "which",
            "there",
            "their",
            "them",
            "these",
            "those",
            "other",
            "each",
            "here",
            "where",
            "been",
            "being",
            "both",
            "same",
            "own",
            "such",
        }
        words: list[str] = []
        for role, content, _ in messages:
            if role.lower() in ("user", "assistant") and content:
                for word in content.lower().split():
                    word = word.strip(".,!?:;\"'()[]{}#`*_-/\\")
                    if len(word) > 2 and word not in stop_words and word.isalpha():
                        words.append(word)
        return Counter(words).most_common(n)

    @staticmethod
    def _format_count(n: int) -> str:
        """Format a count with k/M suffix: 1234 -> '1.2k'."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    def _preview_theme(self, name: str) -> None:
        """Temporarily apply a theme without persisting it."""
        if name not in THEMES:
            available = ", ".join(THEMES)
            self._add_system_message(f"Unknown theme: {name}\nAvailable: {available}")
            return

        # Apply colors temporarily (don't save to disk)
        for key, value in THEMES[name].items():
            if hasattr(self._prefs.colors, key):
                setattr(self._prefs.colors, key, value)

        self._previewing_theme = name

        # Switch Textual base theme
        textual_theme = TEXTUAL_THEMES.get(name)
        if textual_theme:
            self.theme = textual_theme.name

        self._apply_theme_to_all_widgets()
        desc = THEME_DESCRIPTIONS.get(name, "")
        saved = self._prefs.theme_name
        self._add_system_message(
            f"Previewing: {name} — {desc}\n"
            f"Use /theme {name} to keep, or /theme revert to restore {saved}"
        )

    def _revert_theme_preview(self) -> None:
        """Restore the saved theme after a preview."""
        saved = self._prefs.theme_name
        if not self._previewing_theme:
            self._add_system_message(f"No preview active. Current theme: {saved}")
            return

        old_preview = self._previewing_theme
        self._previewing_theme = None

        # Restore the persisted theme colors
        self._prefs.apply_theme(saved)

        textual_theme = TEXTUAL_THEMES.get(saved, TEXTUAL_THEMES["dark"])
        self.theme = textual_theme.name

        self._apply_theme_to_all_widgets()
        desc = THEME_DESCRIPTIONS.get(saved, "")
        self._add_system_message(
            f"Reverted from {old_preview} to: {saved} — {desc}"
            if desc
            else f"Reverted from {old_preview} to: {saved}"
        )

    def _apply_theme_to_all_widgets(self) -> None:
        """Re-style every visible chat widget with the current theme colors."""
        try:
            chat_view = self._active_chat_view()
        except NoMatches:
            logger.debug("chat view not found for theme application", exc_info=True)
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

            elif "note-message" in classes:
                self._style_note(widget)

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
        "note": "note_text",
        "timestamp": "timestamp",
    }

    @staticmethod
    def _html_escape(text: str) -> str:
        """Escape HTML special characters.

        Thin adapter — delegates to :func:`features.export.html_escape`.
        """
        from .features.export import html_escape

        return html_escape(text)

    @staticmethod
    def _md_to_html(text: str) -> str:
        """Very basic markdown to HTML conversion.

        Thin adapter — delegates to :func:`features.export.md_to_html`.
        """
        from .features.export import md_to_html

        return md_to_html(text)

    def _show_notes(self) -> None:
        """Show all session notes."""
        if not self._session_notes:
            self._add_system_message("No notes. Use /note <text> to add one.")
            return

        lines = [f"\U0001f4dd Session Notes ({len(self._session_notes)})"]
        lines.append("=" * 30)
        for i, note in enumerate(self._session_notes, 1):
            try:
                ts = datetime.fromisoformat(note["created_at"]).strftime("%H:%M:%S")
            except (ValueError, TypeError):
                logger.debug("failed to parse note timestamp", exc_info=True)
                ts = "?"
            lines.append(f"\n{i}. [{ts}] {note['text']}")

        self._add_system_message("\n".join(lines))

    def _add_note_message(self, text: str) -> None:
        """Add a visually distinct note widget to the chat."""
        timestamp = datetime.now().strftime("%H:%M")
        note_text = f"\U0001f4dd Note ({timestamp}): {text}"

        chat_view = self._active_chat_view()
        msg = NoteMessage(note_text)
        chat_view.mount(msg)
        self._style_note(msg)
        self._scroll_if_auto(msg)
        self._search_messages.append(("note", text, msg))

    def _style_note(self, widget: Static) -> None:
        """Apply sticky-note styling to a note message."""
        c = self._prefs.colors
        widget.styles.color = c.note_text
        widget.styles.border_left = ("thick", c.note_border)

    def _replay_notes(self) -> None:
        """Re-mount note widgets when restoring a session."""
        chat_view = self._active_chat_view()
        for note in self._session_notes:
            try:
                ts = datetime.fromisoformat(note["created_at"]).strftime("%H:%M")
            except (ValueError, TypeError):
                logger.debug("failed to parse note timestamp for replay", exc_info=True)
                ts = "?"
            note_text = f"\U0001f4dd Note ({ts}): {note['text']}"
            msg = NoteMessage(note_text)
            chat_view.mount(msg)
            self._style_note(msg)
            self._search_messages.append(("note", note["text"], msg))

    _SORT_MODES = ("date", "name", "project")

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
        self._draft_store.remove(session_id)

        # Refresh sidebar
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        # Reset UI to a fresh state
        self._reset_for_new_session()

        self._add_system_message(f"Session {short_id}... deleted.")

    def _remove_session_name(self, session_id: str) -> None:
        """Remove a custom session name from the JSON file."""
        self._session_name_store.remove_name(session_id)

    # ── Bookmark Commands ─────────────────────────────────────────────

    def action_bookmark_last(self) -> None:
        """Bookmark the last assistant message (Ctrl+M)."""
        self._cmd_bookmark("/bookmark")

    def _bookmark_last_message(self, label: str | None = None) -> None:
        """Bookmark the last assistant message with an optional label."""
        sid = self._get_session_id()
        if not sid:
            self._add_system_message("No active session — send a message first.")
            return

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

        # Already bookmarked?
        for bm in self._session_bookmarks:
            if bm["message_index"] == msg_idx:
                self._add_system_message(f"Already bookmarked: {bm['label']}")
                return

        preview = self._get_message_preview(target)

        bookmark = {
            "message_index": msg_idx,
            "label": label or f"Bookmark {len(self._session_bookmarks) + 1}",
            "timestamp": datetime.now().strftime("%H:%M"),
            "preview": preview,
        }

        self._save_bookmark(sid, bookmark)
        self._session_bookmarks.append(bookmark)
        target.add_class("bookmarked")
        self._bookmark_cursor = -1
        self._add_system_message(f"Bookmarked: {bookmark['label']}")

    def _bookmark_nth_message(self, n: int) -> None:
        """Toggle bookmark on the Nth assistant message from bottom."""
        sid = self._get_session_id()
        if not sid:
            self._add_system_message("No active session — send a message first.")
            return

        assistant_widgets = [
            w
            for w in self.query(".assistant-message")
            if isinstance(w, AssistantMessage)
        ]
        if not assistant_widgets:
            self._add_system_message("No assistant messages to bookmark.")
            return

        if n < 1 or n > len(assistant_widgets):
            self._add_system_message(
                f"Message {n} out of range (1-{len(assistant_widgets)})"
            )
            return

        target = assistant_widgets[-n]
        msg_idx = getattr(target, "msg_index", None)
        if msg_idx is None:
            self._add_system_message("Cannot bookmark this message.")
            return

        # Toggle: remove if already bookmarked
        for i, bm in enumerate(self._session_bookmarks):
            if bm["message_index"] == msg_idx:
                self._session_bookmarks.pop(i)
                self._save_session_bookmarks(sid)
                target.remove_class("bookmarked")
                self._bookmark_cursor = -1
                self._add_system_message(
                    f"Bookmark removed from message {n} from bottom"
                )
                return

        preview = self._get_message_preview(target)

        bookmark = {
            "message_index": msg_idx,
            "label": f"Bookmark {len(self._session_bookmarks) + 1}",
            "timestamp": datetime.now().strftime("%H:%M"),
            "preview": preview,
        }

        self._save_bookmark(sid, bookmark)
        self._session_bookmarks.append(bookmark)
        target.add_class("bookmarked")
        self._bookmark_cursor = -1
        self._add_system_message(f"Bookmarked message {n} from bottom")

    def _list_bookmarks(self) -> None:
        """Display all bookmarks for the current session."""
        if not self._session_bookmarks:
            self._add_system_message("No bookmarks in this session.")
            return

        lines = ["Bookmarks:"]
        for i, bm in enumerate(self._session_bookmarks, 1):
            lines.append(f"  {i}. [{bm['timestamp']}] {bm['label']}")
            if bm.get("preview"):
                prev = bm["preview"][:60]
                if len(bm["preview"]) > 60:
                    prev += "..."
                lines.append(f"     {prev}")
        lines.append("")
        lines.append("Jump: /bookmark jump <N>  Remove: /bookmark remove <N>")
        lines.append("Clear all: /bookmark clear")

        self._add_system_message("\n".join(lines))

    def _jump_to_bookmark(self, n: int) -> None:
        """Scroll to the Nth bookmark (1-based)."""
        if not self._session_bookmarks:
            self._add_system_message("No bookmarks in this session.")
            return
        if n < 1 or n > len(self._session_bookmarks):
            self._add_system_message(
                f"Bookmark {n} not found. Valid range: 1-{len(self._session_bookmarks)}"
            )
            return

        bm = self._session_bookmarks[n - 1]
        self._bookmark_cursor = n - 1
        self._scroll_to_bookmark_widget(bm, n)

    def _clear_bookmarks(self) -> None:
        """Remove all bookmarks from the current session."""
        sid = self._get_session_id()
        if not sid:
            self._add_system_message("No active session.")
            return
        if not self._session_bookmarks:
            self._add_system_message("No bookmarks to clear.")
            return

        count = len(self._session_bookmarks)
        for widget in self.query(".assistant-message.bookmarked"):
            widget.remove_class("bookmarked")

        self._session_bookmarks.clear()
        self._bookmark_cursor = -1
        self._save_session_bookmarks(sid)
        self._add_system_message(f"Cleared {count} bookmark(s).")

    def _remove_bookmark(self, n: int) -> None:
        """Remove bookmark N (1-based)."""
        if not self._session_bookmarks:
            self._add_system_message("No bookmarks to remove.")
            return
        if n < 1 or n > len(self._session_bookmarks):
            self._add_system_message(
                f"Bookmark {n} not found. Valid range: 1-{len(self._session_bookmarks)}"
            )
            return

        sid = self._get_session_id()
        if not sid:
            return

        bm = self._session_bookmarks.pop(n - 1)
        target_idx = bm["message_index"]
        for widget in self.query(".assistant-message"):
            if getattr(widget, "msg_index", None) == target_idx:
                widget.remove_class("bookmarked")
                break

        self._bookmark_cursor = -1
        self._save_session_bookmarks(sid)
        self._add_system_message(f"Removed bookmark {n}: {bm['label']}")

    def _save_session_bookmarks(self, session_id: str) -> None:
        """Overwrite all bookmarks for the given session (used by remove/clear)."""
        self._bookmark_store.save_for_session(session_id, self._session_bookmarks)

    def _toggle_bookmark_nearest(self) -> None:
        """Toggle bookmark on the last assistant message (Ctrl+B in vim normal)."""
        sid = self._get_session_id()
        if not sid:
            self._add_system_message("No active session.")
            return

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
            return

        # Toggle: remove if already bookmarked
        for i, bm in enumerate(self._session_bookmarks):
            if bm["message_index"] == msg_idx:
                self._session_bookmarks.pop(i)
                self._save_session_bookmarks(sid)
                target.remove_class("bookmarked")
                self._bookmark_cursor = -1
                self._add_system_message(f"Bookmark removed: {bm['label']}")
                return

        preview = self._get_message_preview(target)

        bookmark = {
            "message_index": msg_idx,
            "label": f"Bookmark {len(self._session_bookmarks) + 1}",
            "timestamp": datetime.now().strftime("%H:%M"),
            "preview": preview,
        }

        self._save_bookmark(sid, bookmark)
        self._session_bookmarks.append(bookmark)
        target.add_class("bookmarked")
        self._bookmark_cursor = -1
        self._add_system_message(f"Bookmarked: {bookmark['label']}")

    def _jump_prev_bookmark(self) -> None:
        """Jump to the previous bookmark ([ in vim normal mode)."""
        if not self._session_bookmarks:
            self._add_system_message("No bookmarks in this session.")
            return
        total = len(self._session_bookmarks)
        if self._bookmark_cursor <= 0:
            self._bookmark_cursor = total
        self._bookmark_cursor -= 1
        bm = self._session_bookmarks[self._bookmark_cursor]
        self._scroll_to_bookmark_widget(bm, self._bookmark_cursor + 1)

    def _jump_next_bookmark(self) -> None:
        """Jump to the next bookmark (] in vim normal mode)."""
        if not self._session_bookmarks:
            self._add_system_message("No bookmarks in this session.")
            return
        total = len(self._session_bookmarks)
        self._bookmark_cursor += 1
        if self._bookmark_cursor >= total:
            self._bookmark_cursor = 0
        bm = self._session_bookmarks[self._bookmark_cursor]
        self._scroll_to_bookmark_widget(bm, self._bookmark_cursor + 1)

    def _scroll_to_bookmark_widget(self, bm: dict, num: int) -> None:
        """Scroll to a bookmark's widget and announce it."""
        target_idx = bm["message_index"]
        total = len(self._session_bookmarks)
        for widget in self.query(".assistant-message"):
            if getattr(widget, "msg_index", None) == target_idx:
                widget.scroll_visible()
                self._add_system_message(f"Bookmark {num}/{total}: {bm['label']}")
                return
        self._add_system_message(
            f"Bookmark {num} widget not found (message may have been cleared)."
        )

    def _get_message_preview(self, widget: Static) -> str:
        """Get a short preview of a message widget's content."""
        for _role, text, w in self._search_messages:
            if w is widget:
                for line in text.split("\n"):
                    stripped = line.strip()
                    if stripped:
                        return stripped[:80]
                return text[:80] if text else "..."
        # Fallback to _last_assistant_text for the most recent message
        fallback = self._last_assistant_text or ""
        for line in fallback.split("\n"):
            stripped = line.strip()
            if stripped:
                return stripped[:80]
        return "..."

    # ── Message Display ─────────────────────────────────────────

    @staticmethod
    def _format_timestamp(dt: datetime) -> str:
        """Format a datetime for display.

        Uses relative time for recent messages (``"just now"``, ``"3m ago"``),
        ``"HH:MM"`` for older messages today, and ``"Feb 5 14:32"`` for
        previous days.
        """
        now = datetime.now(tz=dt.tzinfo)
        delta_secs = max(0, int((now - dt).total_seconds()))
        if delta_secs < 60:
            return "just now"
        if delta_secs < 3600:
            return f"{delta_secs // 60}m ago"
        today = now.date()
        if dt.date() == today:
            return dt.strftime("%H:%M")
        # Non-zero-padded day: "Feb 5 14:32"
        return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%H:%M')}"

    def _make_message_meta(
        self,
        content: str = "",
        dt: datetime | None = None,
        *,
        fallback_now: bool = True,
        response_time: float | None = None,
    ) -> "MessageMeta | None":
        """Create a dim metadata label below a message, or *None* if disabled.

        The label shows timestamp, approximate token count, and (for assistant
        messages) response time.  Example: ``"14:32 · ~450 tokens · ⏱ 3.2s"``

        Parameters
        ----------
        content:
            The message text, used to estimate token count.  Pass ``""`` to
            suppress the token portion (e.g. for system messages).
        dt:
            The datetime to display.  When *None* and *fallback_now* is True
            (the default for live messages), ``datetime.now()`` is used.
        fallback_now:
            If *False* and *dt* is None (e.g. a replayed transcript with no
            stored timestamp), skip the widget entirely rather than showing an
            incorrect "now" time.
        response_time:
            Elapsed seconds for the AI response (shown as ``"⏱ 3.2s"``).
        """
        if not self._prefs.display.show_timestamps:
            return None
        if dt is None:
            if not fallback_now:
                return None
            dt = datetime.now()
        parts: list[str] = [self._format_timestamp(dt)]
        # Rough token estimate (~4 chars per token)
        if content:
            tokens = len(content) // 4
            if tokens > 0:
                parts.append(f"~{tokens} tokens")
        if response_time is not None:
            parts.append(f"⏱ {response_time:.1f}s")
        widget = MessageMeta(" · ".join(parts), classes="msg-timestamp")
        widget._created_at = dt  # type: ignore[attr-defined]
        widget._meta_content = content  # type: ignore[attr-defined]
        widget._meta_response_time = response_time  # type: ignore[attr-defined]
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
        msg = UserMessage(text)
        chat_view.mount(msg)
        meta = self._make_message_meta(text, ts)
        if meta:
            chat_view.mount(meta)
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
        msg = AssistantMessage(text)
        msg.msg_index = self._assistant_msg_index  # type: ignore[attr-defined]
        self._assistant_msg_index += 1
        chat_view.mount(msg)
        # Peek at processing time for display (not consumed; _finish_processing handles that)
        response_time: float | None = None
        if self._processing_start_time is not None:
            response_time = time.monotonic() - self._processing_start_time
        meta = self._make_message_meta(text, ts, response_time=response_time)
        if meta:
            chat_view.mount(meta)
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
        msg = SystemMessage(text)
        chat_view.mount(msg)
        meta = self._make_message_meta(dt=ts)
        if meta:
            chat_view.mount(meta)
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
        self._search_messages.append(("thinking", text, collapsible))

    # -- Panel helper methods (called via call_from_thread) ------------------

    def _update_todo_panel(self, tool_input: dict) -> None:
        """Feed a todo tool call to the TodoPanel widget."""
        try:
            panel = self.query_one("#todo-panel", TodoPanel)
            panel.update_todos(tool_input)
        except Exception:
            pass  # Panel not mounted or query failed

    def _update_agent_tree_start(self, agent_name: str, agent_key: str) -> None:
        """Add a new agent to the AgentTreePanel when delegation starts."""
        try:
            panel = self.query_one("#agent-tree-panel", AgentTreePanel)
            panel.add_agent(name=agent_name, agent_id=agent_key)
        except Exception:
            pass  # Panel not mounted or query failed

    def _update_agent_tree_end(
        self, agent_key: str, status: str, summary: str = ""
    ) -> None:
        """Update an agent in the AgentTreePanel when delegation completes."""
        try:
            panel = self.query_one("#agent-tree-panel", AgentTreePanel)
            panel.update_agent(agent_id=agent_key, status=status, summary=summary)
        except Exception:
            pass  # Panel not mounted or query failed

    def _cmd_todo_panel(self, args: str = "") -> None:
        """Toggle the todo panel visibility."""
        try:
            panel = self.query_one("#todo-panel", TodoPanel)
            panel.visible = not panel.visible
            state = "shown" if panel.visible else "hidden"
            self._add_system_message(f"Todo panel {state}.")
        except Exception:
            self._add_system_message("Todo panel not available.")

    def _cmd_agent_tree_panel(self, args: str = "") -> None:
        """Toggle the agent tree panel visibility."""
        try:
            panel = self.query_one("#agent-tree-panel", AgentTreePanel)
            panel.visible = not panel.visible
            state = "shown" if panel.visible else "hidden"
            self._add_system_message(f"Agent tree panel {state}.")
        except Exception:
            self._add_system_message("Agent tree panel not available.")

    def _add_tool_use(
        self,
        tool_name: str,
        tool_input: dict | str | None = None,
        result: str = "",
    ) -> None:
        self._tool_call_count += 1
        self._tool_usage[tool_name] = self._tool_usage.get(tool_name, 0) + 1
        chat_view = self._active_chat_view()

        # --- Inline diff for file-edit tools ---
        if tool_name in ("edit_file", "write_file") and isinstance(tool_input, dict):
            rendered = self._render_file_edit_diff(tool_name, tool_input)
            if rendered is not None:
                title, diff_text = rendered
                inner = Static(diff_text, markup=True, classes="tool-detail tool-diff")
                collapsible = Collapsible(
                    inner,
                    title=title,
                    collapsed=True,
                )
                collapsible.add_class("tool-use")
                chat_view.mount(collapsible)
                self._style_tool(collapsible, inner)
                self._scroll_if_auto(collapsible)
                return

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
            r = result[:8000] + "\n... (truncated)" if len(result) > 8000 else result
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

    def _render_file_edit_diff(
        self, tool_name: str, tool_input: dict
    ) -> tuple[str, str] | None:
        """Build an inline diff for edit_file / write_file.

        Returns ``(title, rich_markup_text)`` or *None* if the input
        doesn't contain the expected keys.
        """
        from .features.diff_view import (
            diff_summary,
            format_edit_diff,
            format_new_file_diff,
            new_file_summary,
        )

        file_path = tool_input.get("file_path", "")
        if not file_path:
            return None

        if tool_name == "edit_file":
            old = tool_input.get("old_string")
            new = tool_input.get("new_string")
            if old is None or new is None:
                return None
            diff_text = format_edit_diff(file_path, old, new)
            title = f"\u25b6 {diff_summary(file_path, old, new)}"
        else:  # write_file
            content = tool_input.get("content")
            if content is None:
                return None
            diff_text = format_new_file_diff(file_path, content)
            title = f"\u25b6 {new_file_summary(file_path, content)}"

        # Store for /diff last
        self._last_file_edit_diff = (title, diff_text)  # type: ignore[attr-defined]
        return title, diff_text

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
        label = self._processing_label or "Thinking"
        elapsed_str = self._format_elapsed()

        # Build indicator text with optional elapsed timer
        indicator_text = f" {frame} {label}..."
        if elapsed_str:
            indicator_text += f"  [{elapsed_str}]"

        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            indicator.update(indicator_text)
        except NoMatches:
            logger.debug("processing-indicator widget not found", exc_info=True)

        # Keep status bar in sync with elapsed time
        if elapsed_str:
            status_label = self._status_activity_label
            self._update_status(f"{status_label}  [{elapsed_str}]")

    def _format_elapsed(self) -> str:
        """Format elapsed processing time for display.

        Returns an empty string for the first few seconds to avoid visual
        noise on fast responses.
        """
        if self._processing_start_time is None:
            return ""
        elapsed = time.monotonic() - self._processing_start_time
        if elapsed < 3:
            return ""
        if elapsed < 60:
            return f"{elapsed:.0f}s"
        minutes = int(elapsed) // 60
        seconds = int(elapsed) % 60
        return f"{minutes}m {seconds:02d}s"

    def _start_processing(self, label: str = "Thinking") -> None:
        self.is_processing = True
        self._got_stream_content = False
        self._processing_label = label
        self._status_activity_label = f"{label}..."
        self._processing_start_time = time.monotonic()
        self._tool_count_this_turn = 0
        inp = self.query_one("#chat-input", ChatInput)
        inp.placeholder = "Type to queue next message..."

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
        self._status_activity_label = "Ready"
        self._tool_count_this_turn = 0
        self._streaming_cancelled = False
        self._stream_accumulated_text = ""
        # Clean up any leftover streaming state
        self._stream_widget = None
        self._stream_container = None
        self._stream_block_type = None
        inp = self.query_one("#chat-input", ChatInput)
        inp.placeholder = "Message..."
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
        # Auto-save after every completed response
        self._do_autosave()
        # Mid-turn steering: send queued message if any
        if self._queued_message:
            queued = self._queued_message
            self._queued_message = None
            # Use set_timer to send after current processing cleanup completes
            self.set_timer(0.1, lambda: self._send_queued_message(queued))

    def _send_queued_message(self, message: str) -> None:
        """Send a previously queued mid-turn message."""
        if not self._amplifier_ready:
            return
        self._add_user_message(message)
        expanded = self._expand_snippet_mentions(message)
        expanded = self._expand_at_mentions(expanded)
        expanded = self._build_message_with_attachments(expanded)
        if self._active_mode:
            expanded = f"/mode {self._active_mode}\n{expanded}"
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(expanded)

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
        if nprefs.title_flash:
            self._flash_title_bar()

    @staticmethod
    def _send_terminal_notification(title: str, body: str = "") -> None:
        """Send a terminal notification via OSC escape sequences.

        Thin adapter — delegates to
        :func:`features.notifications.send_terminal_notification`.
        """
        from .features.notifications import send_terminal_notification

        send_terminal_notification(title, body)

    @staticmethod
    def _play_bell() -> None:
        """Write BEL character to the real terminal via *sys.__stdout__*.

        Thin adapter — delegates to :func:`features.notifications.play_bell`.
        """
        from .features.notifications import play_bell

        play_bell()

    def _flash_title_bar(self) -> None:
        """Briefly change the terminal title to signal response completion.

        Uses the platform module's OSC 2 helper, then restores after 3 s.
        """
        from .platform import set_terminal_title

        set_terminal_title("[\u2713 Ready] Amplifier TUI")
        self.set_timer(3.0, self._restore_title)

    def _restore_title(self) -> None:
        """Restore the normal terminal title after a title-bar flash."""
        from .platform import set_terminal_title

        set_terminal_title("Amplifier TUI")

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
        except NoMatches:
            logger.debug("processing-indicator not found for removal", exc_info=True)

    def _ensure_processing_indicator(self, label: str | None = None) -> None:
        """Ensure the processing indicator is visible with the given label.

        If the indicator widget exists, updates it in place.
        If it was removed (e.g. by streaming), re-mounts a fresh one.
        """
        if label is not None:
            self._processing_label = label
        display_label = self._processing_label or "Thinking"
        frame = self._SPINNER[self._spinner_frame % len(self._SPINNER)]
        elapsed_str = self._format_elapsed()
        text = f" {frame} {display_label}..."
        if elapsed_str:
            text += f"  [{elapsed_str}]"

        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            indicator.update(text)
        except NoMatches:
            logger.debug("processing-indicator not found, re-creating", exc_info=True)
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
        except NoMatches:
            logger.debug("status-scroll widget not found", exc_info=True)

    def _update_vim_status(self) -> None:
        """Update the status bar vim mode indicator."""
        label = "[vim]" if self._prefs.display.vim_mode else ""
        try:
            self.query_one("#status-vim", Static).update(label)
        except NoMatches:
            logger.debug("status-vim widget not found", exc_info=True)

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
        except NoMatches:
            logger.debug("chat view not found for smart scroll check", exc_info=True)

    # ── Status Bar ──────────────────────────────────────────────

    def _update_status(self, state: str = "Ready") -> None:
        try:
            if self._prefs.display.compact_mode:
                state = f"{state} [compact]"
            self.query_one("#status-state", Static).update(state)
        except NoMatches:
            logger.debug("status-state widget not found", exc_info=True)

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

        If the user has set a non-zero ``context_window_size`` preference it
        takes priority.  Otherwise uses the provider-reported value when
        available, falling back to ``MODEL_CONTEXT_WINDOWS`` keyed by model
        name substring.
        """
        # User-configured override (0 = auto-detect)
        override = self._prefs.display.context_window_size
        if override > 0:
            return override

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
            # Honour the show_token_usage preference
            if not self._prefs.display.show_token_usage:
                self.query_one("#status-model", Static).update("")
                self.query_one("#status-context", Static).update("")
                return

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

            # Color-code by context usage percentage (4-tier)
            widget.styles.color = _context_color(pct)

            # Update the context fuel gauge bar (8 chars wide, █/░)
            ctx_widget = self.query_one("#status-context", Static)
            if pct > 0:
                filled = int(pct * 8 / 100)
                bar = "\u2588" * filled + "\u2591" * (8 - filled)
                ctx_widget.update(f"{bar} {pct:.0f}%")
                ctx_widget.styles.color = _context_color(pct)
            else:
                ctx_widget.update("")
        except NoMatches:
            logger.debug("status bar widget not found for token display", exc_info=True)

    def _record_context_snapshot(self) -> None:
        """Record a context usage snapshot for the /context history sparkline."""
        try:
            window = self._get_context_window()
            if window <= 0:
                return
            sm = self.session_manager
            total = 0
            if sm:
                total = (getattr(sm, "total_input_tokens", 0) or 0) + (
                    getattr(sm, "total_output_tokens", 0) or 0
                )
            if total == 0 and self._search_messages:
                total = sum(
                    len(content) // 4 for _role, content, _w in self._search_messages
                )
            pct = min(100.0, total / window * 100) if total > 0 else 0.0
            ctx_history = getattr(self, "_context_history", None)
            if ctx_history is not None:
                ctx_history.record(pct)
        except (ValueError, AttributeError):
            logger.debug("Failed to record context snapshot", exc_info=True)

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
        except NoMatches:
            logger.debug("breadcrumb-bar widget not found", exc_info=True)
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

        # System prompt indicator in breadcrumb
        if self._system_prompt:
            if self._system_preset_name:
                parts.append(f"\U0001f3ad {self._system_preset_name}")
            else:
                parts.append("\U0001f3ad custom")

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
        except NoMatches:
            logger.debug("status-wordcount widget not found", exc_info=True)

    # ── Streaming Callbacks ─────────────────────────────────────

    def _setup_streaming_callbacks(self) -> None:
        """Wire streaming callbacks via SharedAppBase."""
        self._wire_streaming_callbacks()

    # --- Streaming callback overrides (called from BACKGROUND THREAD) ---
    # These implement the abstract _on_stream_* methods from SharedAppBase.
    # All UI updates are marshalled to the main thread via call_from_thread.

    def _on_stream_block_start(self, block_type: str) -> None:
        self.call_from_thread(self._begin_streaming_block, block_type)

    def _on_stream_block_delta(self, block_type: str, accumulated_text: str) -> None:
        self.call_from_thread(
            self._update_streaming_content, block_type, accumulated_text
        )

    def _on_stream_block_end(
        self, block_type: str, final_text: str, had_block_start: bool
    ) -> None:
        if had_block_start:
            # Streaming widget exists - finalize it with complete text
            self.call_from_thread(
                self._finalize_streaming_block, block_type, final_text
            )
        else:
            # No start event received - direct display (fallback)
            self.call_from_thread(self._remove_processing_indicator)
            if block_type in ("thinking", "reasoning"):
                self.call_from_thread(self._add_thinking_block, final_text)
            else:
                self.call_from_thread(self._add_assistant_message, final_text)

    def _on_stream_tool_start(self, name: str, tool_input: dict) -> None:
        # Feed todo tool calls to the TodoPanel
        if name == "todo" and isinstance(tool_input, dict):
            self.call_from_thread(self._update_todo_panel, tool_input)
        # Feed delegate tool calls to the AgentTreePanel
        if is_delegate_tool(name) and isinstance(tool_input, dict):
            agent_name = tool_input.get("agent", "unknown")
            agent_key = make_delegate_key(tool_input)
            self.call_from_thread(self._update_agent_tree_start, agent_name, agent_key)
        # Compute display label
        if self._prefs.display.progress_labels:
            label = _get_tool_label(name, tool_input)
            bare = label.rstrip(".")
            # Append raw tool name for extra detail
            bare = f"{bare} ({name})"
            # Show sequential counter when this isn't the first tool
            if self._tool_count_this_turn > 1:
                bare = f"{bare} [#{self._tool_count_this_turn}]"
        else:
            label = "Thinking..."
            bare = "Thinking"
        self._processing_label = bare
        self._status_activity_label = label
        self.call_from_thread(self._ensure_processing_indicator, bare)
        self.call_from_thread(self._update_status, label)

    def _on_stream_tool_end(self, name: str, tool_input: dict, result: str) -> None:
        # Update AgentTreePanel on delegate completion
        if is_delegate_tool(name) and isinstance(tool_input, dict):
            agent_key = make_delegate_key(tool_input)
            d_status = "failed" if result.startswith("Error") else "completed"
            summary = result[:100] if result else ""
            self.call_from_thread(
                self._update_agent_tree_end, agent_key, d_status, summary
            )
        self._processing_label = "Thinking"
        self._status_activity_label = "Thinking..."
        self.call_from_thread(self._add_tool_use, name, tool_input, result)
        self.call_from_thread(self._ensure_processing_indicator, "Thinking")
        self.call_from_thread(self._update_status, "Thinking...")

    def _on_stream_usage_update(self) -> None:
        self.call_from_thread(self._update_token_display)
        self.call_from_thread(self._record_context_snapshot)

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
                logger.debug(
                    "Rich Markdown rendering failed, falling back to plain text",
                    exc_info=True,
                )
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
                chat_view.mount(msg, before=old)
                # Peek at processing time for the meta label
                response_time: float | None = None
                if self._processing_start_time is not None:
                    response_time = time.monotonic() - self._processing_start_time
                meta = self._make_message_meta(text, response_time=response_time)
                if meta:
                    chat_view.mount(meta, before=old)
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
        if self.session_manager is None:
            self.call_from_thread(self._add_system_message, "No active session")
            return
        try:
            # Auto-create session on first message
            if not self.session_manager.session:
                self.call_from_thread(self._update_status, "Starting session...")
                model = self._prefs.preferred_model or ""
                try:
                    await self.session_manager.start_new_session(
                        model_override=model,
                    )
                except Exception as session_err:
                    # Session creation is where bundle loading, foundation import,
                    # and provider setup actually happen.  Show structured diagnostics
                    # instead of a raw traceback.
                    logger.debug("Session creation failed", exc_info=True)
                    from .environment import check_environment, format_status

                    env = check_environment(self._prefs.environment.workspace)
                    diag = format_status(env)
                    self.call_from_thread(
                        self._show_error,
                        f"Could not start session: {session_err}\n\n{diag}\n"
                        "Use /environment to re-check after fixing.",
                    )
                    return
                self.call_from_thread(self._update_session_display)
                self.call_from_thread(self._update_token_display)

            # Auto-title from first user message
            if not self._session_title:
                self._session_title = self._extract_title(message)
                self.call_from_thread(self._apply_session_title)

            if self._prefs.display.streaming_enabled:
                self._setup_streaming_callbacks()
            self.call_from_thread(self._update_status, "Thinking...")

            # Inject system prompt (if set) before the user message
            if self._system_prompt:
                message = f"[System instructions: {self._system_prompt}]\n\n{message}"

            response = await self.session_manager.send_message(message)

            if self._streaming_cancelled:
                return  # Already finalized in action_cancel_streaming

            # Fallback: if no hooks fired, show the full response
            if not self._got_stream_content and response:
                self.call_from_thread(self._add_assistant_message, response)

        except Exception as e:
            logger.debug("send message worker failed", exc_info=True)
            if self._streaming_cancelled:
                return  # Suppress errors from cancelled workers
            self.call_from_thread(self._show_error, str(e))
        finally:
            self.call_from_thread(self._finish_processing)

    @work(thread=True)
    async def _resume_session_worker(self, session_id: str) -> None:
        """Resume a session in a background thread."""
        if self.session_manager is None:
            self.call_from_thread(self._add_system_message, "No active session")
            return
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
            # Look up the original project path so the session CWD is correct
            working_dir = None
            for s in getattr(self, "_session_list_data", []):
                if s.get("session_id") == session_id:
                    pp = s.get("project_path")
                    if pp:
                        candidate = Path(pp)
                        if candidate.is_dir():
                            working_dir = candidate
                    break

            model = self._prefs.preferred_model or ""
            await self.session_manager.resume_session(
                session_id, model_override=model, working_dir=working_dir
            )

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
            logger.debug("resume session worker failed", exc_info=True)
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
                        ts_widget = self._make_message_meta(
                            dt=msg_ts, fallback_now=False
                        )
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
                        ts_widget = self._make_message_meta(
                            dt=msg_ts, fallback_now=False
                        )
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
        self._apply_pin_classes()
        self._update_pinned_panel()

        # Restore saved references for this session
        self._session_refs = self._load_session_refs()

        # Restore notes for this session
        self._session_notes = self._load_notes()
        self._replay_notes()

        chat_view.scroll_end(animate=False)

        # Auto-trigger find bar if opened from a search result
        if self._active_search_query:
            query = self._active_search_query
            self._active_search_query = ""
            self._show_find_bar(query)


# ── Entry Point ─────────────────────────────────────────────────────


def run_app(
    resume_session_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Run the Amplifier TUI application."""
    app = AmplifierTuiApp(
        resume_session_id=resume_session_id,
        initial_prompt=initial_prompt,
    )
    app.run()
