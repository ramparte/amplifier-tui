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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from functools import partial

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
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
    save_autosave_enabled,
    save_colors,
    save_compact_mode,
    save_context_window_size,
    save_notification_enabled,
    save_notification_min_seconds,
    save_notification_sound,
    save_notification_title_flash,
    save_preferred_model,
    save_session_sort,
    save_show_timestamps,
    save_show_token_usage,
    save_fold_threshold,
    save_streaming_enabled,
    save_theme_name,
    save_multiline_default,
    save_show_suggestions,
    save_vim_mode,
    save_word_wrap,
)
from .theme import TEXTUAL_THEMES, make_custom_textual_theme

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

# /run shell execution settings
_DANGEROUS_PATTERNS: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf /*",
    "sudo rm",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "> /dev/sda",
)
_MAX_RUN_OUTPUT_LINES = 100
_RUN_TIMEOUT = 30

# Auto-save directory and defaults
AUTOSAVE_DIR = Path.home() / ".amplifier-tui" / "autosave"
MAX_AUTOSAVES_PER_TAB = 5

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
    "/ts",
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
    "/drafts",
    "/tokens",
    "/context",
    "/showtokens",
    "/contextwindow",
    "/sort",
    "/edit",
    "/editor",
    "/wrap",
    "/alias",
    "/info",
    "/fold",
    "/unfold",
    "/history",
    "/grep",
    "/find",
    "/redo",
    "/retry",
    "/undo",
    "/snippet",
    "/snippets",
    "/template",
    "/templates",
    "/title",
    "/diff",
    "/git",
    "/ref",
    "/refs",
    "/vim",
    "/watch",
    "/split",
    "/stream",
    "/tab",
    "/tabs",
    "/palette",
    "/commands",
    "/run",
    "/include",
    "/autosave",
    "/system",
    "/note",
    "/notes",
    "/fork",
    "/branch",
    "/name",
    "/attach",
    "/cat",
    "/multiline",
    "/ml",
    "/suggest",
)

# -- Prompt templates for smart suggestions ------------------------------------
PROMPT_TEMPLATES: tuple[str, ...] = (
    "Explain this code: ",
    "Fix the bug in ",
    "Refactor this to be more ",
    "Write tests for ",
    "Review this code for ",
    "What does this error mean: ",
    "Summarize the conversation so far",
    "Create a plan for ",
    "Debug why ",
    "How do I ",
    "What is the best way to ",
    "Compare the approaches for ",
    "Optimize the performance of ",
    "Add error handling to ",
    "Document the ",
)

# -- System prompt presets -----------------------------------------------------
SYSTEM_PRESETS: dict[str, str] = {
    "coder": (
        "You are an expert programmer. Write clean, efficient, well-documented"
        " code. Prefer simplicity over cleverness."
    ),
    "reviewer": (
        "You are a thorough code reviewer. Focus on bugs, security issues,"
        " performance problems, and best practices. Be specific and actionable."
    ),
    "teacher": (
        "You are a patient, knowledgeable teacher. Explain concepts clearly"
        " with examples. Build understanding step by step."
    ),
    "concise": (
        "Be extremely concise. Use bullet points and short sentences. No filler"
        " words or unnecessary elaboration."
    ),
    "creative": (
        "Think creatively and explore unconventional approaches. Challenge"
        " assumptions. Suggest novel solutions."
    ),
    "debug": (
        "You are a debugging expert. Think systematically about potential"
        " causes. Ask clarifying questions. Trace logic step by step."
    ),
    "architect": (
        "You are a software architect. Focus on system design, scalability,"
        " maintainability, and trade-offs between approaches."
    ),
    "writer": (
        "You are a skilled technical writer. Focus on clarity, structure, and"
        " accuracy. Write for the intended audience."
    ),
}

# -- Model aliases and catalog ------------------------------------------------

MODEL_ALIASES: dict[str, str] = {
    # Claude models
    "sonnet": "claude-sonnet-4-20250514",
    "haiku": "claude-haiku-35-20241022",
    "opus": "claude-3-opus-20240229",
    # GPT models
    "gpt4": "gpt-4o",
    "gpt4o": "gpt-4o",
    "gpt4-mini": "gpt-4o-mini",
    "o1": "o1",
    "o3": "o3-mini",
    # Shorthand
    "fast": "claude-haiku-35-20241022",
    "smart": "claude-sonnet-4-20250514",
    "best": "claude-3-opus-20240229",
}

AVAILABLE_MODELS: tuple[tuple[str, str, str], ...] = (
    # (model_id, provider, description)
    ("claude-sonnet-4-20250514", "Anthropic", "Claude Sonnet 4 (balanced)"),
    ("claude-haiku-35-20241022", "Anthropic", "Claude Haiku 3.5 (fast)"),
    ("claude-3-opus-20240229", "Anthropic", "Claude Opus (powerful)"),
    ("gpt-4o", "OpenAI", "GPT-4o (balanced)"),
    ("gpt-4o-mini", "OpenAI", "GPT-4o Mini (fast)"),
    ("o1", "OpenAI", "O1 (reasoning)"),
    ("o3-mini", "OpenAI", "O3 Mini (reasoning)"),
)

# -- /include constants -------------------------------------------------------

MAX_INCLUDE_LINES = 500
MAX_INCLUDE_SIZE = 100_000  # 100 KB

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".md": "markdown",
    ".txt": "",
    ".cfg": "ini",
    ".ini": "ini",
    ".env": "bash",
    ".dockerfile": "dockerfile",
    ".tf": "hcl",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
}

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
    session_notes: list = field(default_factory=list)
    created_at: str = ""
    # Custom system prompt for this tab
    system_prompt: str = ""
    system_preset_name: str = ""  # name of active preset (if any)
    # Unsent input text (preserved across tab switches)
    input_text: str = ""
    # User-assigned tab name (empty = use auto-generated `name`)
    custom_name: str = ""


@dataclass
class Attachment:
    """A file attached to the next outgoing message."""

    path: Path
    name: str  # filename
    content: str  # file text content
    language: str  # detected language for syntax highlighting
    size: int  # byte length of content


MAX_ATTACHMENT_SIZE = 50_000  # 50 KB warning threshold (total)


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
    "o3-mini": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    "gemini": 1_000_000,
}
DEFAULT_CONTEXT_WINDOW = 200_000


def _context_color(pct: float) -> str:
    """Return a color string for the given context-usage percentage.

    Four tiers:
      green   0-50%  – plenty of room
      yellow  50-75% – getting full
      orange  75-90% – almost full
      red     90%+   – near limit
    """
    if pct >= 90:
        return "#ff4444"
    if pct >= 75:
        return "#ff8800"
    if pct >= 50:
        return "#ffaa00"
    return "#44aa44"


def _context_color_name(pct: float) -> str:
    """Return a human-readable color *name* for context-usage percentage."""
    if pct >= 90:
        return "red"
    if pct >= 75:
        return "orange"
    if pct >= 50:
        return "yellow"
    return "green"


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


class MessageMeta(Static):
    """Subtle metadata line below messages (timestamp, tokens, response time)."""

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

        if self._multiline_mode:
            # Multiline mode: Enter = newline, Ctrl+J / Shift+Enter = send
            if event.key == "ctrl+j" or event.key == "shift+enter":
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
            # Normal mode: Enter = send, Shift+Enter / Ctrl+J = newline
            if event.key == "shift+enter":
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
                except Exception:
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


class SuggestionBar(Static):
    """Thin bar below input showing the current smart prompt suggestion."""

    def __init__(self) -> None:
        super().__init__("", id="suggestion-bar")
        self._suggestions: list[str] = []
        self._index: int = 0

    @property
    def has_suggestions(self) -> bool:
        return len(self._suggestions) > 0

    def set_suggestions(self, suggestions: list[str]) -> None:
        """Replace the suggestion list and reset the cycle index."""
        self._suggestions = suggestions
        self._index = 0
        self._render_bar()

    def accept_current(self) -> str | None:
        """Return the currently highlighted suggestion (Tab press)."""
        if not self._suggestions:
            return None
        return self._suggestions[self._index]

    def cycle_next(self) -> str | None:
        """Advance to the next suggestion and return it."""
        if not self._suggestions:
            return None
        self._index = (self._index + 1) % len(self._suggestions)
        self._render_bar()
        return self._suggestions[self._index]

    def dismiss(self) -> None:
        """Hide the suggestion bar."""
        self._suggestions = []
        self._index = 0
        self._render_bar()

    def _render_bar(self) -> None:
        if not self._suggestions:
            self.display = False
            return
        self.display = True
        current = self._suggestions[self._index]
        total = len(self._suggestions)
        if total == 1:
            self.update(f"[dim]Tab \u2192 {current}[/dim]")
        else:
            self.update(f"[dim]Tab \u2192 {current}  ({self._index + 1}/{total})[/dim]")


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


class NoteMessage(Static):
    """A user annotation/note displayed as a sticky-note in the chat."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message note-message")


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
            return f"▶ ··· {self._line_count} lines hidden (click to expand)"
        return f"▼ {self._line_count} lines (click to fold)"

    def on_click(self) -> None:
        folded = self._target.has_class("folded")
        if folded:
            self._target.remove_class("folded")
        else:
            self._target.add_class("folded")
        self.update(self._make_label(folded=not folded))


class PinnedPanelHeader(Static):
    """Header for the pinned panel. Click to collapse/expand."""

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "_toggle_pinned_panel"):
            app._toggle_pinned_panel()


class PinnedPanelItem(Static):
    """A single pinned message preview. Click to scroll to the original message."""

    def __init__(
        self, pin_number: int, msg_index: int, content: str, **kwargs: object
    ) -> None:
        super().__init__(content, **kwargs)
        self.pin_number = pin_number
        self.msg_index = msg_index

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "_scroll_to_pinned_message"):
            app._scroll_to_pinned_message(self.msg_index)


class PinnedPanel(Vertical):
    """Collapsible panel at top of chat showing pinned message previews."""

    pass


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
  Alt+M            Toggle multiline mode
                    (ML: Enter=newline, Shift+Enter=send)
  Escape           Cancel AI streaming
  Ctrl+C           Cancel AI response
  Ctrl+L           Clear chat
  Ctrl+A           Toggle auto-scroll

 SEARCH & EDIT ──────────────────────────
  Ctrl+F           Find in chat (interactive search bar)
  Ctrl+R           Reverse history search (Ctrl+S fwd)
  Ctrl+G           Open external editor
  Ctrl+Y           Copy last AI response (Ctrl+Shift+C also works)
  Ctrl+M           Bookmark last response
  Ctrl+S           Stash/restore draft

 VIM BOOKMARKS (normal mode) ─────────────
  Ctrl+B           Toggle bookmark on last message
  [                Jump to previous bookmark
  ]                Jump to next bookmark

 SESSIONS ───────────────────────────────
  Ctrl+N           New session
  Ctrl+T           New tab
  F2               Rename current tab
  Ctrl+W           Close tab (split: switch pane)
  Ctrl+PgUp/Dn    Switch tabs (split: switch pane)
  Alt+Left/Right   Prev/next tab (split: switch pane)
  Alt+1-9          Jump to tab 1-9
  Alt+0            Jump to last tab
  Ctrl+P           Command palette (fuzzy search)
  F1 / Ctrl+/      This help
  Ctrl+Q           Quit

 SPLIT VIEW ─────────────────────────────
  /split           Toggle tab split (2+ tabs)
  /split N         Split with tab N
  /split swap      Swap left/right panes
  /split off       Close split view
  Alt+Left/Right   Switch active pane
  Ctrl+W           Switch active pane

          Slash Commands
──────────────────────────────────────────
  Type /help for the full reference

 SESSION ────────────────────────────────
  /new             New session
  /sessions        Toggle session sidebar
  /rename          Rename tab (F2)
  /title           View/set session title
  /delete          Delete current session
  /pin-session     Pin/unpin in sidebar
  /sort            Sort sessions
  /split           Split view (tab split, pins, chat, file)
  /tab             Tab management
  /tabs            List open tabs
  /info            Session details
  /stats           Session statistics (tools, tokens, time)

 CHAT & HISTORY ─────────────────────────
  /clear           Clear chat display
  /copy            Copy response (last/N/all/code)
  /undo [N]        Undo last N exchange(s)
  /retry [text]    Undo last exchange & resend (or send new text)
  /redo [text]     Alias for /retry
  /fold            Fold last long message (all, none, <N>, threshold)
  /unfold          Unfold last folded message (all)
  /compact         Toggle compact mode
  /history         Browse/search/clear input history

 SEARCH ─────────────────────────────────
  /find            Interactive find-in-chat (Ctrl+F)
  /search          Search chat messages
  /grep            Search chat (regex)

 PINS & BOOKMARKS ──────────────────────
  /pin             Pin message (N, list, clear, remove N)
  /pins            List pinned messages
  /unpin N         Remove a pin
  /bookmark        Bookmark last response (list, N, jump N, remove N, clear)
  /bookmarks       List/jump to bookmarks
  /note            Add a session note (/note list, /note clear)
  /notes           List all notes (alias for /note list)
  /ref             Save URL/reference
  /refs             List saved references

 MODEL & DISPLAY ───────────────────────
  /model [name]    View/switch AI model
  /theme [name]    Switch color theme (/theme preview, /theme preview <name>, /theme revert)
  /colors          View/set text colors (/colors presets, /colors use <preset>)
  /wrap            Toggle word wrap
  /timestamps      Toggle timestamps (/ts)
  /focus           Toggle focus mode
  /stream          Toggle streaming display
  /scroll          Toggle auto-scroll

 EXPORT & DATA ─────────────────────────
  /export          Export chat (md/html/json/txt/clipboard)
  /diff            Show git diff (color-coded)
  /diff msgs       Compare last two assistant messages (or /diff msgs N M)
  /git             Quick git operations (status/log/diff/branch/stash/blame)
  /watch           Watch files for changes
  /run <cmd>       Run shell command inline (/! shorthand)
  /tokens          Token/context usage
  /context         Context window details
  /showtokens      Toggle token display
  /contextwindow   Set context window size

 FILES ─────────────────────────────────────
  /attach <path>   Attach file(s) to next message
  /attach          Show current attachments
  /attach clear    Remove all attachments
  /cat <path>      Display file contents in chat

 INPUT & SETTINGS ──────────────────────
  /edit            Open $EDITOR for input
  /editor          Alias for /edit
  /draft           Save/load input drafts
  /snippet         Prompt snippets
  /template        Prompt templates with {{variables}}
  /system          Set/view system prompt (presets, use, clear)
  /alias           Custom command shortcuts
  /vim             Toggle vim keybindings
  /suggest         Toggle smart prompt suggestions
  /prefs           Preferences
  /notify          Toggle notifications
  /sound           Toggle notification sound (on|off|test)
  /palette         Command palette (same as Ctrl+P)
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

    def update_tabs(
        self,
        tabs: list,
        active_index: int,
        split_left: int | None = None,
        split_right: int | None = None,
    ) -> None:
        """Rebuild the tab bar buttons."""
        self.remove_children()
        for i, tab in enumerate(tabs):
            label = tab.custom_name or tab.name
            # Mark split panes in tab bar
            if split_left is not None and i == split_left:
                label = f"\u25e7 {label}"
            elif split_right is not None and i == split_right:
                label = f"\u25e8 {label}"
            cls = "tab-btn tab-active" if i == active_index else "tab-btn tab-inactive"
            if i == split_left or i == split_right:
                cls += " tab-in-split"
            btn = TabButton(f" {label} ", tab_index=i, classes=cls)
            self.mount(btn)
        # Hide tab bar when there's only one tab
        if len(tabs) <= 1:
            self.add_class("single-tab")
        else:
            self.remove_class("single-tab")


class FindBar(Horizontal):
    """Inline search bar for finding text in chat (Ctrl+F)."""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Find in chat…", id="find-input")
        yield Static("Aa", id="find-case-btn", classes="find-btn")
        yield Static("▲", id="find-prev-btn", classes="find-btn")
        yield Static("▼", id="find-next-btn", classes="find-btn")
        yield Static("0/0", id="find-count")
        yield Static("✕", id="find-close-btn", classes="find-btn")

    def on_click(self, event) -> None:
        """Route clicks on the inline buttons."""
        target = event.widget
        if hasattr(target, "id"):
            if target.id == "find-close-btn":
                self.app._hide_find_bar()
            elif target.id == "find-prev-btn":
                self.app._find_prev()
            elif target.id == "find-next-btn":
                self.app._find_next()
            elif target.id == "find-case-btn":
                self.app._find_toggle_case()


# ── Main Application ────────────────────────────────────────────────


# ── Command Palette Provider ─────────────────────────────────────────────────

# (display_name, description, command_key)
# command_key: "/cmd" delegates to _handle_slash_command; "action:name" calls action_name
_PALETTE_COMMANDS: tuple[tuple[str, str, str], ...] = (
    # ── Slash commands ──────────────────────────────────────────────────────
    ("/help", "Show help reference", "/help"),
    ("/clear", "Clear chat display", "/clear"),
    ("/new", "Start a new session", "/new"),
    ("/sessions", "Toggle session sidebar", "/sessions"),
    ("/sessions list", "List all saved sessions", "/sessions list"),
    ("/sessions recent", "Show 10 most recent sessions", "/sessions recent"),
    ("/sessions search", "Search across all sessions", "/sessions search "),
    ("/sessions open", "Open/resume a session by ID", "/sessions open "),
    ("/sessions delete", "Delete a session by ID", "/sessions delete "),
    ("/sessions info", "Show session details", "/sessions info "),
    ("/prefs", "Open preferences", "/preferences"),
    ("/model", "Show or switch AI model", "/model"),
    ("/stats", "Session statistics (tools, tokens, time)", "/stats"),
    ("/tokens", "Detailed token and context usage breakdown", "/tokens"),
    ("/context", "Visual context window usage bar", "/context"),
    ("/showtokens", "Toggle token/context usage in status bar", "/showtokens"),
    ("/contextwindow", "Set context window size (e.g. 128k, auto)", "/contextwindow"),
    ("/info", "Session details (ID, model, project, counts)", "/info"),
    ("/copy", "Copy last response (last, N, all, code)", "/copy"),
    ("/bookmark", "Bookmark last AI response", "/bookmark"),
    ("/bookmark list", "List all bookmarks with preview", "/bookmark list"),
    ("/bookmark jump", "Jump to a bookmark by number", "/bookmark jump "),
    ("/bookmark remove", "Remove a specific bookmark", "/bookmark remove "),
    ("/bookmark clear", "Remove all bookmarks", "/bookmark clear"),
    ("/bookmarks", "List or jump to bookmarks", "/bookmarks"),
    ("/ref", "Save a URL or reference", "/ref"),
    ("/refs", "List saved references", "/refs"),
    ("/title", "View or set session title", "/title"),
    ("/rename", "Rename current tab (F2)", "/rename"),
    ("/rename reset", "Reset tab name to default", "/rename reset"),
    ("/pin", "Pin message (last, by number, or with label)", "/pin"),
    ("/pins", "List pinned messages", "/pins"),
    ("/unpin", "Remove a pin by number", "/unpin"),
    ("/pin-session", "Pin or unpin session in sidebar", "/pin-session"),
    ("/note", "Add a session note (not sent to AI)", "/note"),
    ("/note list", "List all session notes", "/note list"),
    ("/note clear", "Remove all session notes", "/note clear"),
    ("/notes", "List all session notes", "/notes"),
    ("/delete", "Delete session (with confirmation)", "/delete"),
    ("/export", "Export chat (md/html/json/txt/clipboard)", "/export"),
    ("/notify", "Toggle notifications (on, off, sound, silent, flash)", "/notify"),
    ("/sound", "Toggle notification sound (on, off, test)", "/sound"),
    ("/scroll", "Toggle auto-scroll on/off", "/scroll"),
    ("/timestamps", "Toggle message timestamps", "/timestamps"),
    ("/ts", "Toggle message timestamps (alias for /timestamps)", "/ts"),
    ("/wrap", "Toggle word wrap (on, off)", "/wrap"),
    ("/fold", "Fold or unfold long messages", "/fold"),
    ("/fold all", "Fold all long messages", "/fold all"),
    ("/fold none", "Unfold all messages", "/fold none"),
    ("/fold toggle", "Toggle fold on all long messages", "/fold toggle"),
    ("/fold threshold", "Show or set auto-fold line threshold", "/fold threshold"),
    ("/unfold", "Unfold the last folded message", "/unfold"),
    ("/unfold all", "Unfold all folded messages", "/unfold all"),
    ("/theme", "Switch color theme", "/theme"),
    ("/theme preview", "Preview all themes with swatches", "/theme preview"),
    ("/theme revert", "Restore saved theme after preview", "/theme revert"),
    ("/colors", "View or set text colors", "/colors"),
    (
        "/colors presets",
        "Show available color presets with swatches",
        "/colors presets",
    ),
    ("/colors use", "Apply a color preset", "/colors use "),
    ("/colors reset", "Reset all colors to defaults", "/colors reset"),
    ("/focus", "Toggle focus mode", "/focus"),
    ("/search", "Search across all past sessions", "/search"),
    ("/search here", "Search current chat only", "/search here "),
    ("/search open", "Open a result from last search", "/search open "),
    ("/grep", "Search chat with regex", "/grep"),
    ("/find", "Interactive find-in-chat (Ctrl+F)", "/find"),
    ("/diff", "Show git diff (staged, all, file)", "/diff"),
    ("/diff msgs", "Compare assistant messages (last two, or N M)", "/diff msgs"),
    ("/git", "Quick git info (status, log, diff, branch, stash, blame)", "/git"),
    ("/watch", "Watch files for changes", "/watch"),
    ("/sort", "Sort sessions (date, name, project)", "/sort"),
    ("/edit", "Open $EDITOR for input", "/edit"),
    ("/draft", "Save, load, or clear input draft", "/draft"),
    ("/drafts", "List all saved drafts across sessions", "/drafts"),
    ("/drafts clear", "Clear the current session draft", "/drafts clear"),
    ("/snippet", "Manage prompt snippets", "/snippet"),
    ("/snippets", "List all prompt snippets", "/snippets"),
    ("/template", "Manage prompt templates", "/template"),
    ("/templates", "List all prompt templates", "/templates"),
    ("/alias", "List, create, or remove command aliases", "/alias"),
    ("/compact", "Toggle compact view mode", "/compact"),
    ("/history", "Browse or search input history", "/history"),
    ("/undo", "Remove last exchange", "/undo"),
    ("/retry", "Undo last exchange & re-send (or send new text)", "/retry"),
    ("/redo", "Alias for /retry (undo + re-send)", "/redo"),
    ("/split", "Toggle split view (tab split, pins, chat, file)", "/split"),
    ("/split N", "Split current tab with tab N", "/split "),
    ("/split swap", "Swap left and right panes in split view", "/split swap"),
    ("/split off", "Close split view", "/split off"),
    ("/stream", "Toggle streaming display", "/stream"),
    (
        "/multiline",
        "Toggle multiline mode (Enter=newline, Shift+Enter=send)",
        "/multiline",
    ),
    ("/ml", "Toggle multiline mode (alias for /multiline)", "/ml"),
    ("/suggest", "Toggle smart prompt suggestions (on/off)", "/suggest"),
    ("/vim", "Toggle vim keybindings", "/vim"),
    ("/tab", "Tab management (new, switch, close, rename, list)", "/tab"),
    ("/tab new", "Open a new conversation tab", "/tab new"),
    ("/tab list", "List all open tabs", "/tab list"),
    ("/tab rename", "Rename current tab", "/tab rename"),
    ("/tabs", "List all open tabs", "/tabs"),
    ("/keys", "Keyboard shortcuts overlay", "/keys"),
    ("/quit", "Quit the application", "/quit"),
    ("/run", "Run a shell command inline (/! shorthand)", "/run"),
    ("/include", "Include file contents in prompt (@file syntax too)", "/include"),
    ("/autosave", "Auto-save status, toggle, force save, or restore", "/autosave"),
    ("/autosave on", "Enable periodic auto-save", "/autosave on"),
    ("/autosave off", "Disable periodic auto-save", "/autosave off"),
    ("/autosave now", "Force an immediate auto-save", "/autosave now"),
    ("/autosave restore", "List and restore from auto-saves", "/autosave restore"),
    ("/system", "Set or view custom system prompt", "/system"),
    ("/system presets", "Show available system prompt presets", "/system presets"),
    ("/system use coder", "Apply 'coder' system prompt preset", "/system use coder"),
    (
        "/system use reviewer",
        "Apply 'reviewer' system prompt preset",
        "/system use reviewer",
    ),
    (
        "/system use teacher",
        "Apply 'teacher' system prompt preset",
        "/system use teacher",
    ),
    (
        "/system use concise",
        "Apply 'concise' system prompt preset",
        "/system use concise",
    ),
    (
        "/system use creative",
        "Apply 'creative' system prompt preset",
        "/system use creative",
    ),
    ("/system use debug", "Apply 'debug' system prompt preset", "/system use debug"),
    (
        "/system use architect",
        "Apply 'architect' system prompt preset",
        "/system use architect",
    ),
    ("/system use writer", "Apply 'writer' system prompt preset", "/system use writer"),
    ("/system clear", "Remove custom system prompt", "/system clear"),
    ("/fork", "Fork conversation into a new tab", "/fork"),
    ("/fork N", "Fork from message N (from bottom) into a new tab", "/fork"),
    ("/branch", "Fork conversation into a new tab (alias for /fork)", "/branch"),
    ("/name", "Name current session (/name <text>, /name clear)", "/name"),
    ("/attach", "Attach file(s) to next message", "/attach "),
    ("/attach clear", "Remove all attachments", "/attach clear"),
    ("/attach remove", "Remove a specific attachment by number", "/attach remove "),
    ("/cat", "Display file contents in chat", "/cat "),
    # ── Keyboard-shortcut actions ───────────────────────────────────────────
    ("New Session  Ctrl+N", "Start a new conversation", "action:new_session"),
    ("New Tab  Ctrl+T", "Open a new conversation tab", "action:new_tab"),
    ("Close Tab  Ctrl+W", "Close the current tab", "action:close_tab"),
    ("Previous Tab  Ctrl+PgUp", "Switch to previous tab", "action:prev_tab"),
    ("Next Tab  Ctrl+PgDn", "Switch to next tab", "action:next_tab"),
    (
        "Toggle Sidebar  Ctrl+B",
        "Show or hide session sidebar",
        "action:toggle_sidebar",
    ),
    (
        "Open Editor  Ctrl+G",
        "Open external editor for input",
        "action:open_editor",
    ),
    (
        "Copy Response  Ctrl+Y / Ctrl+Shift+C",
        "Copy last AI response to clipboard",
        "action:copy_response",
    ),
    (
        "Stash Prompt  Ctrl+S",
        "Stash or restore draft prompt",
        "action:stash_prompt",
    ),
    (
        "Bookmark Last  Ctrl+M",
        "Bookmark the last AI response",
        "action:bookmark_last",
    ),
    (
        "Search History  Ctrl+R",
        "Reverse search prompt history",
        "action:search_history",
    ),
    (
        "Find in Chat  Ctrl+F",
        "Interactive find-in-chat search bar",
        "action:search_chat",
    ),
    (
        "Toggle Auto-scroll  Ctrl+A",
        "Toggle auto-scroll on/off",
        "action:toggle_auto_scroll",
    ),
    ("Clear Chat  Ctrl+L", "Clear the chat display", "action:clear_chat"),
    (
        "Focus Mode  F11",
        "Toggle focus mode (hide chrome)",
        "action:toggle_focus_mode",
    ),
    (
        "Keyboard Shortcuts  F1",
        "Show keyboard shortcuts overlay",
        "action:show_shortcuts",
    ),
    (
        "Scroll to Top  Ctrl+Home",
        "Jump to top of chat",
        "action:scroll_chat_top",
    ),
    (
        "Scroll to Bottom  Ctrl+End",
        "Jump to bottom of chat",
        "action:scroll_chat_bottom",
    ),
)


class AmplifierCommandProvider(Provider):
    """Provide all TUI slash commands and actions to the command palette."""

    async def search(self, query: str) -> Hits:
        """Yield commands that fuzzy-match *query*."""
        matcher = self.matcher(query)
        for name, description, command_key in _PALETTE_COMMANDS:
            score = matcher.match(f"{name} {description}")
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    partial(self._run_command, command_key),
                    help=description,
                )

    async def discover(self) -> Hits:
        """Show every command when the palette first opens (no query yet)."""
        for name, description, command_key in _PALETTE_COMMANDS:
            yield DiscoveryHit(
                name,
                partial(self._run_command, command_key),
                help=description,
            )

    def _run_command(self, key: str) -> None:
        """Execute a palette command by dispatching to the app."""
        app = self.app
        if key.startswith("action:"):
            action_name = key[7:]
            method = getattr(app, f"action_{action_name}", None)
            if method is not None:
                method()
        else:
            # Delegate to the existing slash-command router
            app._handle_slash_command(key)  # type: ignore[attr-defined]


class AmplifierChicApp(App):
    """Amplifier TUI - a clean TUI for Amplifier."""

    COMMANDS = {AmplifierCommandProvider}

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
    NOTES_FILE = Path.home() / ".amplifier" / "tui-notes.json"
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
        self.session_manager: object | None = None
        self.is_processing = False
        self._got_stream_content = False
        self._amplifier_available = True
        self._amplifier_ready = False
        self._session_list_data: list[dict] = []
        self._sidebar_visible = False
        self._spinner_frame = 0
        self._spinner_timer: object | None = None
        self._timestamp_timer: object | None = None
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
        self._crash_draft_timer: object | None = None

        # Draft auto-save change detection
        self._last_saved_draft: str = ""

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

        # Tab split view state (two tabs side by side)
        self._tab_split_mode: bool = False
        self._tab_split_left_index: int | None = None
        self._tab_split_right_index: int | None = None
        self._tab_split_active: str = "left"  # "left" or "right"

        # Auto-save state
        self._autosave_enabled: bool = self._prefs.autosave.enabled
        self._autosave_interval: int = self._prefs.autosave.interval
        self._last_autosave: float = 0.0
        self._autosave_timer: object | None = None

        # File attachments (cleared after sending)
        self._attachments: list[Attachment] = []

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
                yield FindBar(id="find-bar")
                yield PinnedPanel(id="pinned-panel")
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
                yield SuggestionBar()
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
                    yield Static("\u2195 ON", id="status-scroll")
                    yield Static("0 words", id="status-wordcount")
                    yield Static("", id="status-context")
                    yield Static("", id="status-model")

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

        # Check for auto-save recovery from a previous crash
        self._check_autosave_recovery()

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
            tab_bar.update_tabs(
                self._tabs,
                self._active_tab_index,
                split_left=self._tab_split_left_index if self._tab_split_mode else None,
                split_right=self._tab_split_right_index
                if self._tab_split_mode
                else None,
            )
        except Exception:
            pass
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
        tab.session_notes = self._session_notes
        tab.system_prompt = self._system_prompt
        tab.system_preset_name = self._system_preset_name
        # Preserve unsent input text across tab switches
        try:
            tab.input_text = self.query_one("#chat-input", ChatInput).text
        except Exception:
            pass

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
        self._session_notes = tab.session_notes
        self._system_prompt = tab.system_prompt
        self._system_preset_name = tab.system_preset_name

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

        # Restore unsent input text for this tab
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            if new_tab.input_text:
                input_widget.insert(new_tab.input_text)
            self._last_saved_draft = new_tab.input_text
        except Exception:
            pass

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
        except Exception:
            pass

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
        except Exception:
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

    def _load_drafts(self) -> dict:
        """Load all drafts from the JSON file.

        Returns a dict of ``{session_id: {text, timestamp, preview}}``
        (or plain strings for backward-compat with older files).
        """
        try:
            if self.DRAFTS_FILE.exists():
                return json.loads(self.DRAFTS_FILE.read_text())
        except Exception:
            pass
        return {}

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
            entry = drafts.get(session_id)
            draft_text = self._draft_text(entry) if entry else ""

            if draft_text:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.clear()
                input_widget.insert(draft_text)
                self._last_saved_draft = draft_text
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
            self._last_saved_draft = ""
        except Exception:
            pass

    def _auto_save_draft(self) -> None:
        """Periodic auto-save of input draft (called every 5s by timer).

        Only writes to disk when the input text has actually changed since
        the last save, and briefly flashes a 'Draft saved' notification.
        """
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            current = input_widget.text
            if current != self._last_saved_draft:
                self._last_saved_draft = current
                session_id = self._get_session_id()
                if session_id:
                    self._save_draft()
                    if current.strip():
                        self.notify("Draft saved", timeout=1.5, severity="information")
        except Exception:
            pass

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
        except Exception:
            pass

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
        """Perform an auto-save of the current session (timer + event hook).

        Silently fails — never interrupts the user.
        """
        if not self._autosave_enabled:
            return
        try:
            messages = self._search_messages
            if not messages:
                return  # Nothing to save

            tab = self._tabs[self._active_tab_index]
            tab_id = tab.tab_id

            session_data = {
                "session_id": self._get_session_id(),
                "session_title": self._session_title or "",
                "tab_id": tab_id,
                "tab_name": tab.name,
                "saved_at": datetime.now().isoformat(),
                "message_count": len(messages),
                "messages": [
                    {"role": role, "content": content}
                    for role, content, _widget in messages
                ],
            }

            ts = int(time.time())
            filename = f"autosave-{tab_id}-{ts}.json"
            filepath = AUTOSAVE_DIR / filename

            filepath.write_text(
                json.dumps(session_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._last_autosave = time.time()

            # Rotate old auto-saves for this tab
            self._rotate_autosaves(tab_id)
        except Exception:
            pass  # Silent failure — never interrupt the user

    def _rotate_autosaves(self, tab_id: str) -> None:
        """Keep only the last MAX_AUTOSAVES_PER_TAB files per tab."""
        try:
            pattern = f"autosave-{tab_id}-*.json"
            files = sorted(AUTOSAVE_DIR.glob(pattern), key=lambda f: f.stat().st_mtime)
            while len(files) > MAX_AUTOSAVES_PER_TAB:
                oldest = files.pop(0)
                oldest.unlink(missing_ok=True)
        except Exception:
            pass

    def _check_autosave_recovery(self) -> None:
        """Check for auto-save files on startup and notify the user."""
        try:
            if not AUTOSAVE_DIR.exists():
                return
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
        except Exception:
            pass

    # ── System Prompt (/system) ──────────────────────────────────────────

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

    def _update_system_indicator(self) -> None:
        """Update the status bar system prompt indicator."""
        try:
            indicator = self.query_one("#status-system", Static)
        except Exception:
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
            except Exception:
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
                    pass
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
                    pass
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

    def _autosave_restore(self) -> None:
        """Show available auto-saves for recovery."""
        try:
            autosaves = sorted(
                AUTOSAVE_DIR.glob("autosave-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            autosaves = []

        if not autosaves:
            self._add_system_message("No auto-saves found")
            return

        lines = ["Available auto-saves:"]
        for i, f in enumerate(autosaves[:10], 1):
            try:
                age = (time.time() - f.stat().st_mtime) / 60
                size = f.stat().st_size / 1024
                # Try to read session title from the file
                data = json.loads(f.read_text(encoding="utf-8"))
                title = data.get("session_title", "")
                msg_count = data.get("message_count", "?")
                label = f" — {title}" if title else ""
                lines.append(
                    f"  {i}. {f.name} "
                    f"({age:.0f} min ago, {size:.1f} KB, "
                    f"{msg_count} msgs{label})"
                )
            except Exception:
                lines.append(f"  {i}. {f.name}")

        lines.append("")
        lines.append("To restore the most recent auto-save:")
        lines.append(f"  /export json  (then compare with {autosaves[0]})")
        lines.append(f"\nAuto-save files are in: {AUTOSAVE_DIR}")

        self._add_system_message("\n".join(lines))

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

    # ── Session Notes ─────────────────────────────────────────────────

    def _load_notes(self) -> list[dict]:
        """Load notes for the current session."""
        try:
            if self.NOTES_FILE.exists():
                all_notes = json.loads(self.NOTES_FILE.read_text())
                sid = self._get_session_id() or "default"
                return all_notes.get(sid, [])
        except Exception:
            pass
        return []

    def _save_notes(self) -> None:
        """Persist session notes keyed by session ID."""
        try:
            all_notes: dict[str, list[dict]] = {}
            if self.NOTES_FILE.exists():
                all_notes = json.loads(self.NOTES_FILE.read_text())
            sid = self._get_session_id() or "default"
            if self._session_notes:
                all_notes[sid] = self._session_notes
            elif sid in all_notes:
                del all_notes[sid]
            # Keep last 50 sessions worth of notes
            if len(all_notes) > 50:
                keys = list(all_notes.keys())
                for k in keys[:-50]:
                    del all_notes[k]
            self.NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.NOTES_FILE.write_text(json.dumps(all_notes, indent=2))
        except Exception:
            pass

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
        except Exception:
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
        elif event.input.id == "find-input":
            self._find_execute_search(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the find-input to navigate to next match."""
        if event.input.id == "find-input":
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

        if key == "ctrl+s":
            self._rsearch_cycle_prev()
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
        if not self._rsearch_matches:
            self._update_rsearch_display()
            return
        # Wrap around from last match back to first
        self._rsearch_match_idx = (self._rsearch_match_idx + 1) % len(
            self._rsearch_matches
        )
        entry = self._history.get_entry(self._rsearch_matches[self._rsearch_match_idx])
        if entry is not None:
            input_widget = self.query_one("#chat-input", ChatInput)
            input_widget.clear()
            input_widget.insert(entry)
        self._update_rsearch_display()

    def _rsearch_cycle_prev(self) -> None:
        """Cycle to the previous (newer) match in the current result set."""
        if not self._rsearch_matches:
            self._update_rsearch_display()
            return
        # Wrap around from first match back to last
        self._rsearch_match_idx = (self._rsearch_match_idx - 1) % len(
            self._rsearch_matches
        )
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
        except Exception:
            pass

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
        except Exception:
            pass

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
            except Exception:
                pass

    def _find_update_counter(self) -> None:
        """Update the '3/17' counter label in the find bar."""
        try:
            label = self.query_one("#find-count", Static)
            if not self._find_matches:
                label.update("0/0")
            else:
                label.update(f"{self._find_index + 1}/{len(self._find_matches)}")
        except Exception:
            pass

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
        except Exception:
            pass

    def _cmd_find(self, text: str) -> None:
        """Handle the /find slash command — open find bar with optional query."""
        parts = text.strip().split(None, 1)
        query = parts[1] if len(parts) > 1 else ""
        self._show_find_bar(query)

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
        except Exception:
            pass
        self._submit_message()

    def _refresh_suggestions(self) -> None:
        """Compute and display smart prompt suggestions based on current input."""
        try:
            bar = self.query_one("#suggestion-bar", SuggestionBar)
        except Exception:
            return

        if not self._prefs.display.show_suggestions:
            bar.dismiss()
            return

        try:
            input_w = self.query_one("#chat-input", ChatInput)
        except Exception:
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
            "/context": self._cmd_context,
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
            "/editor": self.action_open_editor,
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
            "/include": lambda: self._cmd_include(args),
            "/autosave": lambda: self._cmd_autosave(args),
            "/system": lambda: self._cmd_system(args),
            "/note": lambda: self._cmd_note(args),
            "/notes": lambda: self._show_notes(),
            "/fork": lambda: self._cmd_fork(args),
            "/branch": lambda: self._cmd_fork(args),
            "/name": lambda: self._cmd_name(args),
            "/attach": lambda: self._cmd_attach(args),
            "/cat": lambda: self._cmd_cat(args),
            "/multiline": lambda: self._cmd_multiline(args),
            "/ml": lambda: self._cmd_multiline(args),
            "/suggest": lambda: self._cmd_suggest(args),
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
            "  /sessions     Session manager (list, search, recent, open, delete, info)\n"
            "  /prefs        Show preferences\n"
            "  /model        Show/switch model | /model list | /model <name>\n"
            "  /stats        Show session statistics | /stats tools | /stats tokens | /stats time\n"
            "  /tokens       Detailed token / context usage breakdown\n"
            "  /context      Visual context window usage bar\n"
            "  /showtokens   Toggle token/context usage in status bar (/showtokens on|off)\n"
            "  /contextwindow Set context window size (/contextwindow 128k, auto)\n"
            "  /info         Show session details (ID, model, project, counts)\n"
            "  /copy         Copy last response | /copy last | /copy N | /copy all | /copy code\n"
            "  /bookmark     Bookmark last response (/bm alias) | /bookmark N (toggle Nth from bottom)\n"
            "  /bookmark     list | jump N | remove N | clear | <label>\n"
            "  /bookmarks    List bookmarks | /bookmarks <N> to jump\n"
            "  /ref          Save a URL/reference (/ref <url> [label], /ref remove/clear/export)\n"
            "  /refs         List all saved references (same as /ref with no args)\n"
            "  /title        View/set session title (/title <text> or /title clear)\n"
            "  /rename       Rename current tab (/rename <name>, /rename reset)\n"
            "  /name         Name session (/name <text>, /name clear, /name to show)\n"
            "  /pin          Pin message (/pin, /pin N, /pin list, /pin clear, /pin remove N)\n"
            "  /pins         List all pinned messages (alias for /pin list)\n"
            "  /unpin <N>    Remove a pin by its pin number\n"
            "  /note         Add a session note (/note <text>, /note list, /note clear)\n"
            "  /notes        List all session notes (alias for /note list)\n"
            "  /pin-session  Pin/unpin session (pinned appear at top of sidebar)\n"
            "  /delete       Delete session (with confirmation)\n"
            "  /export       Export chat (md default) | /export <fmt> [path] | /export clipboard\n"
            "  /notify       Toggle notifications (/notify on|off|sound|silent|flash|<secs>)\n"
            "  /sound        Toggle notification sound (/sound on|off|test)\n"
            "  /scroll       Toggle auto-scroll on/off\n"
            "  /timestamps   Toggle message timestamps on/off (alias: /ts)\n"
            "  /wrap         Toggle word wrap on/off (/wrap on, /wrap off)\n"
            "  /fold         Fold last long message (/fold all, /fold none, /fold <N>, /fold threshold)\n"
            "  /unfold       Unfold last folded message (/unfold all to unfold all)\n"
            "  /theme        Switch color theme (/theme preview, /theme preview <name>, /theme revert)\n"
            "  /colors       View/set text colors (/colors <role> <#hex>, /colors reset, presets, use)\n"
            "  /focus        Toggle focus mode (/focus on, /focus off)\n"
            "  /find         Interactive find-in-chat bar (Ctrl+F) with match navigation\n"
            "  /search       Search across all sessions | /search here <q> for current chat\n"
            "  /search open  Open result N from last search (/search open 3)\n"
            "  /grep         Search with options (/grep <pattern>, /grep -c <pattern> for case-sensitive)\n"
            "  /diff         Show git diff (/diff staged|all|last|<file>|<f1> <f2>|HEAD~N)\n"
            "  /diff msgs    Compare assistant messages (/diff msgs, /diff msgs N M)\n"
            "  /git          Quick git operations (/git status|log|diff|branch|stash|blame)\n"
            "  /watch        Watch files for changes (/watch <path>, stop, diff)\n"
            "  /sort         Sort sessions: date, name, project (/sort <mode>)\n"
            "  /edit         Open $EDITOR for longer prompts (same as Ctrl+G)\n"
            "  /editor       Alias for /edit\n"
            "  /draft        Show/save/clear/load input draft (/draft save, /draft clear, /draft load)\n"
            "  /drafts       List all saved drafts across sessions (/drafts clear to clear current)\n"
            "  /snippet      Prompt snippets (/snippet save|use|remove|search|cat|tag|export|import|<name>)\n"
            "  /template     Prompt templates with {{variables}} (/template save|use|remove|clear|<name>)\n"
            "  /alias        List/create/remove custom shortcuts\n"
            "  /compact      Toggle compact view mode (/compact on, /compact off)\n"
            "  /history      Browse input history (/history <N>, /history search <query>, /history clear)\n"
            "  /undo         Remove last exchange (/undo <N> for last N exchanges)\n"
            "  /retry        Undo last exchange & re-send (/retry <text> to modify)\n"
            "  /redo         Alias for /retry\n"
            "  /split        Toggle split view (/split [N|swap|off|pins|chat|file <path>])\n"
            "  /stream       Toggle streaming display (/stream on, /stream off)\n"
            "  /multiline    Toggle multiline mode (/multiline on, /multiline off, /ml)\n"
            "  /suggest      Toggle smart prompt suggestions (/suggest on, /suggest off)\n"
            "  /vim          Toggle vim keybindings (/vim on, /vim off)\n"
            "  /tab          Tab management (/tab new|switch|close|rename|list)\n"
            "  /tabs         List all open tabs\n"
            "  /fork         Fork conversation into a new tab (/fork N from bottom)\n"
            "  /branch       Alias for /fork\n"
            "  /run          Run shell command inline (/run ls -la, /run git status)\n"
            "  /!            Shorthand for /run (/! git diff)\n"
            "  /include      Include file contents (/include src/main.py, /include *.py --send)\n"
            "                Also: @./path/to/file in your prompt auto-includes\n"
            "  /attach       Attach file(s) to next message (/attach *.py, clear, remove N)\n"
            "  /cat          Display file contents in chat (/cat src/main.py)\n"
            "  /autosave     Auto-save status, toggle, force save, restore (/autosave on|off|now|restore)\n"
            "  /system       Set/view system prompt (/system <text>, clear, presets, use <preset>, append)\n"
            "  /keys         Keyboard shortcut overlay\n"
            "  /palette      Command palette (Ctrl+P) – fuzzy search all commands\n"
            "  /quit         Quit\n"
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
        except Exception as e:
            self._add_system_message(f"Error running command: {e}")

    # -- /include helpers ------------------------------------------------------

    @staticmethod
    def _is_binary(path: Path) -> bool:
        """Check if a file appears to be binary."""
        try:
            chunk = path.read_bytes()[:8192]
            return b"\x00" in chunk
        except Exception:
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
        except Exception as e:
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

        # Match @path/to/file.ext — only paths starting with ./ ../ ~/ or /
        return re.sub(r"@((?:\.\.?/|~/|/)\S+)", _replace_at_file, text)

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

    def _attach_file(self, path: Path) -> None:
        """Attach a single file."""
        if self._is_binary(path):
            self._add_system_message(f"Skipping binary file: {path.name}")
            return

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
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
        except Exception:
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
        except Exception as e:
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
            draft = self._draft_text(drafts[session_id])
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

    def _cmd_drafts(self, text: str) -> None:
        """List all saved drafts across sessions, or clear current draft."""
        arg = (
            text.strip().split(None, 1)[1].strip().lower()
            if " " in text.strip()
            else ""
        )

        if arg == "clear":
            sid = self._get_session_id()
            if sid:
                self._clear_draft()
                self._clear_crash_draft()
                try:
                    input_widget = self.query_one("#chat-input", ChatInput)
                    input_widget.clear()
                except Exception:
                    pass
                self._add_system_message("Draft cleared")
            else:
                self._add_system_message("No active session")
            return

        # List all drafts
        drafts = self._load_drafts()
        if not drafts:
            self._add_system_message("No saved drafts")
            return

        lines = ["Saved Drafts:", ""]
        sorted_drafts = sorted(
            drafts.items(),
            key=lambda kv: (
                kv[1].get("timestamp", "") if isinstance(kv[1], dict) else ""
            ),
            reverse=True,
        )
        for sid, entry in sorted_drafts:
            if isinstance(entry, dict):
                ts = entry.get("timestamp", "unknown")[:16]
                preview = entry.get("preview", "")[:60]
                text_len = len(entry.get("text", ""))
            else:
                ts = "unknown"
                preview = str(entry)[:60].replace("\n", " ")
                text_len = len(str(entry))
            suffix = "..." if len(preview) >= 60 else ""
            lines.append(
                f"  {sid[:12]}... [{ts}] ({text_len} chars): {preview}{suffix}"
            )

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
                display_name = tab.custom_name or tab.name
                lines.append(f"{marker} {i + 1}. {display_name}{sid}")
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
            name = subargs[:30]
            self._rename_tab(name)
            self._add_system_message(f'Tab renamed to: "{name}"')
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

    def _cmd_fork(self, args: str) -> None:
        """Fork conversation at a specific point into a new tab."""
        args = args.strip()

        # Get current messages
        messages = self._search_messages
        if not messages:
            self._add_system_message("No messages to fork from.")
            return

        # Determine fork point (N is 1-based from bottom)
        if args and args.isdigit():
            n = int(args)
            if n < 1 or n > len(messages):
                self._add_system_message(
                    f"Invalid message number: {n}. Must be 1\u2013{len(messages)}."
                )
                return
            fork_idx = len(messages) - n
        else:
            # Fork from last message (include all)
            fork_idx = len(messages) - 1

        # Collect message data before switching tabs (role + text only)
        fork_data = [(role, txt) for role, txt, _ in messages[: fork_idx + 1]]
        total_messages = len(messages)

        # Save source tab info
        source_tab = self._tabs[self._active_tab_index]
        source_tab_name = source_tab.name
        source_system_prompt = self._system_prompt
        source_system_preset = self._system_preset_name

        # Create new tab without welcome message
        new_tab_name = f"Fork of {source_tab_name}"
        self._create_new_tab(name=new_tab_name, show_welcome=False)

        # Copy system prompt from source tab
        self._system_prompt = source_system_prompt
        self._system_preset_name = source_system_preset

        # Replay messages into the new tab
        for role, txt in fork_data:
            if role == "user":
                self._add_user_message(txt)
            elif role == "assistant":
                self._add_assistant_message(txt)
            # Skip system/thinking/note messages in fork

        # Add fork indicator
        fork_msg_count = len(fork_data)
        self._add_system_message(
            f"(forked from {source_tab_name} at msg {fork_msg_count}/{total_messages})\n"
            f"Continue the conversation from here.\n"
            f"Note: AI context starts fresh \u2014 the AI won't recall earlier messages\n"
            f"until you send a new message in this tab."
        )

        # Scroll to bottom
        try:
            chat = self._active_chat_view()
            chat.scroll_end(animate=False)
        except Exception:
            pass

    def _cmd_clear(self) -> None:
        self.action_clear_chat()
        # No system message needed - the chat is cleared

    def _cmd_new(self) -> None:
        self.action_new_session()
        # new session shows its own welcome message

    def _cmd_sessions(self, args: str) -> None:
        """Manage and search saved sessions."""
        args = args.strip()

        # No args: toggle sidebar (backward compatible)
        if not args:
            self.action_toggle_sidebar()
            state = "opened" if self._sidebar_visible else "closed"
            self._add_system_message(f"Session sidebar {state}.")
            return

        if args.lower() == "help":
            self._add_system_message(
                "Session Management\n\n"
                "  /sessions              Toggle session sidebar\n"
                "  /sessions list         List all saved sessions\n"
                "  /sessions recent       Show 10 most recent sessions\n"
                "  /sessions search <q>   Search across all sessions\n"
                "  /sessions open <id>    Open/resume a session by ID\n"
                "  /sessions delete <id>  Delete a session (with confirmation)\n"
                "  /sessions info <id>    Show session details\n"
                "\n"
                "Partial session IDs are supported (e.g. /sessions open 7de3)."
            )
            return

        parts = args.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "list":
            self._sessions_list()
        elif cmd == "recent":
            self._sessions_recent()
        elif cmd == "search":
            if not arg:
                self._add_system_message("Usage: /sessions search <query>")
                return
            self._sessions_search(arg)
        elif cmd == "open":
            if not arg:
                self._add_system_message("Usage: /sessions open <session-id>")
                return
            self._sessions_open(arg)
        elif cmd == "delete":
            if not arg:
                self._add_system_message("Usage: /sessions delete <session-id>")
                return
            self._sessions_delete(arg)
        elif cmd == "info":
            if not arg:
                self._add_system_message("Usage: /sessions info <session-id>")
                return
            self._sessions_info(arg)
        else:
            # Treat entire args as a search query
            self._sessions_search(args)

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
        from .session_manager import SessionManager

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
        from .session_manager import SessionManager

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
        from .session_manager import SessionManager

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

    def _sessions_search(self, query: str) -> None:
        """Search across all saved sessions for matching text."""
        projects_dir = Path.home() / ".amplifier" / "projects"
        if not projects_dir.exists():
            self._add_system_message("No saved sessions found.")
            return

        query_lower = query.lower()
        results: list[dict] = []
        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue

            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Skip sub-sessions
                if "_" in session_dir.name:
                    continue

                sid = session_dir.name
                transcript = session_dir / "transcript.jsonl"
                if not transcript.exists():
                    continue

                try:
                    mtime = session_dir.stat().st_mtime
                except OSError:
                    continue

                # Search metadata first (name, description)
                meta_match = ""
                metadata_path = session_dir / "metadata.json"
                meta_name = ""
                meta_desc = ""
                if metadata_path.exists():
                    try:
                        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                        meta_name = meta.get("name", "")
                        meta_desc = meta.get("description", "")
                        for field in (meta_name, meta_desc):
                            if query_lower in field.lower():
                                meta_match = field
                                break
                    except Exception:
                        pass

                # Search custom names / titles
                if not meta_match:
                    for field in (
                        custom_names.get(sid, ""),
                        session_titles.get(sid, ""),
                    ):
                        if field and query_lower in field.lower():
                            meta_match = field
                            break

                # Search filename
                if not meta_match and query_lower in sid.lower():
                    meta_match = f"(session ID: {sid})"

                # If metadata matched, record and skip transcript scan
                if meta_match:
                    results.append(
                        {
                            "session_id": sid,
                            "mtime": mtime,
                            "date_str": datetime.fromtimestamp(mtime).strftime(
                                "%m/%d %H:%M"
                            ),
                            "match_preview": meta_match.replace("\n", " ")[:100],
                            "match_role": "metadata",
                            "name": meta_name,
                            "description": meta_desc,
                        }
                    )
                    continue

                # Scan transcript lines for content match
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
                            text = self._extract_transcript_text(msg.get("content", ""))
                            if query_lower in text.lower():
                                preview = text.replace("\n", " ")[:120]
                                results.append(
                                    {
                                        "session_id": sid,
                                        "mtime": mtime,
                                        "date_str": datetime.fromtimestamp(
                                            mtime
                                        ).strftime("%m/%d %H:%M"),
                                        "match_preview": preview,
                                        "match_role": role,
                                        "name": meta_name,
                                        "description": meta_desc,
                                    }
                                )
                                break  # One match per session is enough
                except OSError:
                    continue

        if not results:
            self._add_system_message(f"No sessions matching '{query}'.")
            return

        # Sort by mtime descending (most recent first)
        results.sort(key=lambda r: r["mtime"], reverse=True)

        lines = [f"Found {len(results)} session(s) matching '{query}':\n"]
        for i, r in enumerate(results[:20], 1):
            sid_short = r["session_id"][:8]
            label = self._session_label(r, custom_names, session_titles)
            lines.append(f"  {i:2}. {r['date_str']}  [{sid_short}]  {label}")
            preview = r["match_preview"][:80]
            lines.append(f"      [{r['match_role']}] {preview}")

        if len(results) > 20:
            lines.append(f"\n... and {len(results) - 20} more")
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
            except Exception:
                pass

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

    # ── /multiline – toggle multiline input mode ─────────────────────────

    def _cmd_multiline(self, text: str) -> None:
        """Toggle multiline input mode.

        /multiline       Toggle multiline mode
        /multiline on    Enable multiline mode
        /multiline off   Disable multiline mode
        /ml              Alias for /multiline
        """
        text = text.strip().lower()

        if text in ("on", "true", "1"):
            ml = True
        elif text in ("off", "false", "0"):
            ml = False
        elif not text:
            ml = not self._prefs.display.multiline_default
        else:
            self._add_system_message("Usage: /multiline [on|off]")
            return

        self._prefs.display.multiline_default = ml
        save_multiline_default(ml)

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget._multiline_mode = ml

        if ml:
            self._add_system_message(
                "Multiline mode ON — Enter inserts newline, "
                "Shift+Enter sends (Ctrl+J also sends)"
            )
        else:
            self._add_system_message(
                "Multiline mode OFF — Enter sends, Shift+Enter inserts newline"
            )

        self._update_multiline_status()

    def _update_multiline_status(self) -> None:
        """Update the status bar multiline mode indicator."""
        label = "[ML]" if self._prefs.display.multiline_default else ""
        try:
            self.query_one("#status-ml", Static).update(label)
        except Exception:
            pass

    def action_toggle_multiline(self) -> None:
        """Alt+M action: toggle multiline mode."""
        self._cmd_multiline("")

    # ── /suggest – smart prompt suggestions ──────────────────────────────────

    def _cmd_suggest(self, text: str) -> None:
        """Toggle smart prompt suggestions on/off.

        /suggest       Toggle suggestions
        /suggest on    Enable suggestions
        /suggest off   Disable suggestions
        """
        text = text.strip().lower()

        if text in ("on", "true", "1"):
            enabled = True
        elif text in ("off", "false", "0"):
            enabled = False
        elif not text:
            enabled = not self._prefs.display.show_suggestions
        else:
            self._add_system_message("Usage: /suggest [on|off]")
            return

        self._prefs.display.show_suggestions = enabled
        save_show_suggestions(enabled)

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget._suggestions_enabled = enabled

        if enabled:
            self._add_system_message(
                "Smart suggestions ON — type 2+ chars to see suggestions, Tab to accept"
            )
        else:
            self._add_system_message("Smart suggestions OFF")
            # Dismiss any visible suggestions
            try:
                self.query_one("#suggestion-bar", SuggestionBar).dismiss()
            except Exception:
                pass

    # ── /split – side-by-side reference panel ────────────────────────────

    def _cmd_split(self, text: str) -> None:
        """Toggle or configure split view.

        /split          Toggle tab split (2+ tabs) or reference panel
        /split N        Split current tab with tab N
        /split off      Close any split view
        /split swap     Swap left and right panes (tab split)
        /split pins     Show pinned messages in right panel
        /split chat     Mirror of chat at independent scroll position
        /split file <p> Show file content in right panel
        """
        raw = text.strip() if text else ""
        lower = raw.lower()

        if lower == "off":
            if self._tab_split_mode:
                self._exit_tab_split()
            else:
                self._close_split()
            return

        if lower == "swap":
            if self._tab_split_mode:
                self._swap_tab_split()
            else:
                self._add_system_message("Swap requires tab split mode")
            return

        if lower == "pins":
            if self._tab_split_mode:
                self._exit_tab_split()
            self._open_split_pins()
            return

        if lower == "chat":
            if self._tab_split_mode:
                self._exit_tab_split()
            self._open_split_chat()
            return

        # /split file <path> – preserve original case for the path
        if lower.startswith("file ") or lower.startswith("file\t"):
            if self._tab_split_mode:
                self._exit_tab_split()
            path = raw[5:].strip()
            if not path:
                self._add_system_message("Usage: /split file <path>")
                return
            self._open_split_file(path)
            return

        # /split N – split with a specific tab number
        if lower and lower.isdigit():
            target_index = int(lower) - 1  # 1-based to 0-based
            if target_index < 0 or target_index >= len(self._tabs):
                self._add_system_message(
                    f"Tab {lower} not found (have {len(self._tabs)} tabs)"
                )
                return
            if target_index == self._active_tab_index:
                self._add_system_message("Cannot split a tab with itself")
                return
            if self.has_class("split-mode"):
                self._close_split()
            if self._tab_split_mode:
                self._exit_tab_split()
            self._enter_tab_split(self._active_tab_index, target_index)
            return

        if lower == "on" or not lower:
            # Toggle: if already in any split, exit
            if self._tab_split_mode:
                self._exit_tab_split()
                return
            if self.has_class("split-mode"):
                self._close_split()
                return
            # Enter tab split if 2+ tabs, otherwise fall back to pins
            if len(self._tabs) >= 2:
                next_idx = (self._active_tab_index + 1) % len(self._tabs)
                self._enter_tab_split(self._active_tab_index, next_idx)
            else:
                self._open_split_pins()
            return

        self._add_system_message(
            "Usage: /split [on|off|swap|N|pins|chat|file <path>]\n"
            "  /split          Toggle tab split (2+ tabs) or reference panel\n"
            "  /split N        Split current tab with tab N\n"
            "  /split swap     Swap left and right panes\n"
            "  /split off      Close split view\n"
            "  /split pins     Pinned messages in right panel\n"
            "  /split chat     Chat mirror (independent scroll)\n"
            "  /split file <p> File content in right panel\n"
            "  Alt+Left/Right  Switch active pane in split mode"
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
                role_label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                    role, role
                )
                pin_label = pin.get("label", "")
                label_str = f" [{pin_label}]" if pin_label else ""
                # Truncate very long content for display
                display = content[:500]
                if len(content) > 500:
                    display += "\n..."
                panel.mount(
                    Static(
                        f"[bold]#{i} ({role_label} msg {idx + 1}){label_str}:[/bold]\n{display}",
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
        """Close the reference split panel."""
        self.remove_class("split-mode")
        try:
            panel = self.query_one("#split-panel", ScrollableContainer)
            panel.remove_children()
        except Exception:
            pass
        self._add_system_message("Split view closed")

    # ── Tab split view (two live tabs side by side) ──────────────────────

    def _enter_tab_split(self, left_index: int, right_index: int) -> None:
        """Enter tab split mode showing two tabs side by side."""
        if self.is_processing:
            self._add_system_message("Cannot enter split view while processing.")
            return

        self._save_current_tab_state()

        self._tab_split_mode = True
        self._tab_split_left_index = left_index
        self._tab_split_right_index = right_index
        self._tab_split_active = "left"
        self._active_tab_index = left_index

        # Load left tab state
        self._load_tab_state(self._tabs[left_index])

        # Show both containers side by side
        left_tab = self._tabs[left_index]
        right_tab = self._tabs[right_index]

        try:
            left_container = self.query_one(
                f"#{left_tab.container_id}", ScrollableContainer
            )
            right_container = self.query_one(
                f"#{right_tab.container_id}", ScrollableContainer
            )

            # Ensure both are visible
            left_container.remove_class("tab-chat-hidden")
            right_container.remove_class("tab-chat-hidden")

            # Add split styling classes
            left_container.add_class("split-left-pane")
            right_container.add_class("split-right-pane")
            left_container.add_class("split-pane-active")

            # Ensure correct DOM order: left before right
            # (move right after left in case they aren't adjacent)
            right_container.move_after(left_container)
        except Exception:
            self._tab_split_mode = False
            self._tab_split_left_index = None
            self._tab_split_right_index = None
            self._add_system_message("Failed to set up split view")
            return

        self.add_class("tab-split-mode")

        left_name = self._tabs[left_index].name
        right_name = self._tabs[right_index].name
        self._update_tab_bar()
        self._add_system_message(
            f"Split view: [{left_name}] | [{right_name}]\n"
            "Alt+Left/Right or Ctrl+W to switch pane \u2022 /split off to close"
        )

    def _exit_tab_split(self) -> None:
        """Exit tab split mode, return to single-pane view."""
        if not self._tab_split_mode:
            return

        self._save_current_tab_state()

        left_index = self._tab_split_left_index
        right_index = self._tab_split_right_index
        active_index = self._active_tab_index

        # Determine which tab is NOT active (needs to be hidden)
        if left_index is not None and right_index is not None:
            other_index = right_index if active_index == left_index else left_index
        else:
            other_index = None

        # Clean up CSS classes from both containers
        for idx in (left_index, right_index):
            if idx is not None and idx < len(self._tabs):
                tab = self._tabs[idx]
                try:
                    container = self.query_one(
                        f"#{tab.container_id}", ScrollableContainer
                    )
                    container.remove_class(
                        "split-left-pane",
                        "split-right-pane",
                        "split-pane-active",
                    )
                except Exception:
                    pass

        # Hide the non-active tab's container
        if other_index is not None and other_index < len(self._tabs):
            other_tab = self._tabs[other_index]
            try:
                other_container = self.query_one(
                    f"#{other_tab.container_id}", ScrollableContainer
                )
                other_container.add_class("tab-chat-hidden")
            except Exception:
                pass

        self.remove_class("tab-split-mode")
        self._tab_split_mode = False
        self._tab_split_left_index = None
        self._tab_split_right_index = None
        self._tab_split_active = "left"

        self._update_tab_bar()
        self._add_system_message("Split view closed")

    def _swap_tab_split(self) -> None:
        """Swap left and right panes in tab split mode."""
        if not self._tab_split_mode:
            return

        left_index = self._tab_split_left_index
        right_index = self._tab_split_right_index

        if left_index is None or right_index is None:
            return

        # Swap indices
        self._tab_split_left_index = right_index
        self._tab_split_right_index = left_index

        # Update CSS classes on containers
        old_left_tab = self._tabs[left_index]
        old_right_tab = self._tabs[right_index]

        try:
            old_left_container = self.query_one(
                f"#{old_left_tab.container_id}", ScrollableContainer
            )
            old_right_container = self.query_one(
                f"#{old_right_tab.container_id}", ScrollableContainer
            )

            # Swap left/right CSS classes
            old_left_container.remove_class("split-left-pane")
            old_left_container.add_class("split-right-pane")

            old_right_container.remove_class("split-right-pane")
            old_right_container.add_class("split-left-pane")

            # Reorder in DOM so new-left appears before new-right
            old_right_container.move_before(old_left_container)
        except Exception:
            pass

        # Update active indicator
        self._update_split_active_indicator()

        left_name = self._tabs[self._tab_split_left_index].name
        right_name = self._tabs[self._tab_split_right_index].name
        self._update_tab_bar()
        self._add_system_message(f"Panes swapped: [{left_name}] | [{right_name}]")

    def _switch_split_pane(self) -> None:
        """Switch the active pane in tab split mode."""
        if not self._tab_split_mode:
            return

        self._save_current_tab_state()

        # Toggle active side
        if self._tab_split_active == "left":
            self._tab_split_active = "right"
            self._active_tab_index = self._tab_split_right_index or 0
        else:
            self._tab_split_active = "left"
            self._active_tab_index = self._tab_split_left_index or 0

        # Load the newly active tab's state
        self._load_tab_state(self._tabs[self._active_tab_index])

        # Update visual indicator
        self._update_split_active_indicator()

        # Update UI
        self._update_tab_bar()
        self._update_session_display()
        self._update_word_count_display()
        self._update_breadcrumb()
        self._update_pinned_panel()
        self.sub_title = self._session_title or ""

        # Restore input text for the new active pane's tab
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            active_tab = self._tabs[self._active_tab_index]
            input_widget.clear()
            if active_tab.input_text:
                input_widget.insert(active_tab.input_text)
            input_widget.focus()
        except Exception:
            pass

    def _update_split_active_indicator(self) -> None:
        """Update CSS classes to show which pane is active in tab split."""
        if not self._tab_split_mode:
            return

        for idx in (self._tab_split_left_index, self._tab_split_right_index):
            if idx is not None and idx < len(self._tabs):
                tab = self._tabs[idx]
                try:
                    container = self.query_one(
                        f"#{tab.container_id}", ScrollableContainer
                    )
                    if idx == self._active_tab_index:
                        container.add_class("split-pane-active")
                    else:
                        container.remove_class("split-pane-active")
                except Exception:
                    pass

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
        """Unified search command.

        Subcommands:
          /search <query>        Search across ALL past sessions
          /search here <query>   Search current chat only
          /search open <N>       Open Nth result from last cross-session search
        """
        parts = text.strip().split(None, 1)
        query = parts[1] if len(parts) > 1 else ""
        if not query:
            self._add_system_message(
                "Usage:\n"
                "  /search <query>        Search across all past sessions\n"
                "  /search here <query>   Search current chat only\n"
                "  /search open <N>       Open result from last search"
            )
            return

        # --- /search here <query> --- current chat only
        if query.startswith("here "):
            self._search_current_chat(query[5:].strip())
            return

        # --- /search open <N> --- open a result from the last cross-session search
        if query.startswith("open "):
            self._search_open_result(query[5:].strip())
            return

        # --- /search <query> --- cross-session search (threaded)
        self._add_system_message(f"Searching all sessions for '{query}'...")
        self._search_all_sessions_worker(query)

    def _search_current_chat(self, query: str) -> None:
        """Search only the current chat's in-memory messages."""
        if not query:
            self._add_system_message("Usage: /search here <query>")
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

    def _search_open_result(self, arg: str) -> None:
        """Open a session from the last cross-session search results."""
        if not self._last_search_results:
            self._add_system_message("No search results. Run /search <query> first.")
            return
        try:
            n = int(arg)
        except ValueError:
            self._add_system_message("Usage: /search open <number>")
            return
        if n < 1 or n > len(self._last_search_results):
            self._add_system_message(
                f"Invalid result number. Valid range: 1-{len(self._last_search_results)}"
            )
            return
        result = self._last_search_results[n - 1]
        sid = result["session_id"]
        self._sessions_open(sid)

    @work(thread=True)
    def _search_all_sessions_worker(self, query: str) -> None:
        """Search transcript content across all saved sessions in a background thread."""
        projects_dir = Path.home() / ".amplifier" / "projects"
        if not projects_dir.exists():
            self.call_from_thread(self._add_system_message, "No saved sessions found.")
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
                    mtime = session_dir.stat().st_mtime
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
                    except Exception:
                        pass

                # Derive project name from the encoded directory name
                project_name = (
                    project_dir.name.rsplit("-", 1)[-1]
                    if "-" in project_dir.name
                    else project_dir.name
                )

                # Scan transcript for ALL matches (not just first)
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
                            # Count occurrences in this message
                            start = 0
                            while True:
                                idx = content_lower.find(query_lower, start)
                                if idx == -1:
                                    break
                                match_count += 1
                                if match_count == 1:
                                    # Capture snippet around first match
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

        # Build output
        if not results:
            self.call_from_thread(
                self._add_system_message,
                f"No sessions found matching '{query}'.",
            )
            return

        total_matches = sum(r["match_count"] for r in results)
        lines = [
            f"Found {total_matches} match{'es' if total_matches != 1 else ''} "
            f"across {len(results)} session{'s' if len(results) != 1 else ''}:\n"
        ]

        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        for i, r in enumerate(results[:20], 1):
            sid_short = r["session_id"][:8]
            label = self._session_label(r, custom_names, session_titles)
            count = r["match_count"]
            count_str = f"{count} match{'es' if count != 1 else ''}"
            project = r["project"]
            lines.append(
                f"  {i:2}. [{r['date_str']}]  {project}/{sid_short}  ({count_str})"
            )
            lines.append(f"      {label}")
            snippet = r["first_snippet"][:80]
            lines.append(f"      [{r['first_role']}] {snippet}")

        if len(results) > 20:
            lines.append(f"\n  ... and {len(results) - 20} more sessions")

        lines.append("\nUse /search open <N> to open a result in a new tab.")
        lines.append("Use /search here <query> to search only the current chat.")

        self.call_from_thread(self._add_system_message, "\n".join(lines))

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
    # /git command
    # ------------------------------------------------------------------

    def _cmd_git(self, text: str) -> None:
        """Quick git operations (read-only)."""
        text = text.strip()

        if not text:
            self._git_overview()
            return

        parts = text.split(None, 1)
        subcmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "status": self._git_status,
            "st": self._git_status,
            "log": self._git_log,
            "diff": self._git_diff_summary,
            "branch": self._git_branches,
            "br": self._git_branches,
            "stash": self._git_stashes,
            "blame": self._git_blame,
        }

        handler = handlers.get(subcmd)
        if handler:
            handler(args)
        else:
            self._add_system_message(
                f"Unknown git subcommand: {subcmd}\n\n"
                "Available: status (st), log, diff, branch (br), stash, blame"
            )

    def _git_overview(self) -> None:
        """Quick git overview: branch, status summary, ahead/behind."""
        from rich.markup import escape

        ok, branch = self._run_git("branch", "--show-current")
        if not ok:
            self._add_system_message(f"Not a git repo or git error: {branch}")
            return
        branch = branch.strip() or "(detached HEAD)"

        # Status summary
        _, status_out = self._run_git("status", "--porcelain")
        lines = [ln for ln in status_out.splitlines() if ln.strip()]
        staged = sum(1 for ln in lines if ln[0] not in (" ", "?"))
        modified = sum(1 for ln in lines if len(ln) > 1 and ln[1] == "M")
        untracked = sum(1 for ln in lines if ln.startswith("??"))

        # Ahead/behind
        ahead, behind = 0, 0
        ab_ok, ab_out = self._run_git(
            "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
        )
        if ab_ok and ab_out.strip():
            ab_parts = ab_out.strip().split()
            if len(ab_parts) == 2:
                ahead, behind = int(ab_parts[0]), int(ab_parts[1])

        # Last commit
        _, last_commit = self._run_git("log", "-1", "--format=%h %s (%cr)")

        parts = [f"[bold]Branch:[/bold] {escape(branch)}"]
        if staged:
            parts.append(f"  [green]Staged:[/green] {staged}")
        if modified:
            parts.append(f"  [yellow]Modified:[/yellow] {modified}")
        if untracked:
            parts.append(f"  [dim]Untracked:[/dim] {untracked}")
        if ahead:
            parts.append(f"  [cyan]↑ {ahead} ahead[/cyan]")
        if behind:
            parts.append(f"  [red]↓ {behind} behind[/red]")
        if not (staged or modified or untracked):
            parts.append("  [green]Clean working tree[/green]")
        if last_commit.strip():
            parts.append(f"\n[dim]Last:[/dim] {escape(last_commit.strip())}")

        self._add_system_message("\n".join(parts))

    def _git_status(self, args: str) -> None:
        """Detailed git status."""
        ok, out = self._run_git("status", "--short", "--branch")
        if not ok:
            self._add_system_message(f"git status error: {out}")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_log(self, args: str) -> None:
        """Recent commits."""
        n = "10"
        if args.strip().isdigit():
            n = args.strip()
        ok, out = self._run_git(
            "log",
            f"-{n}",
            "--format=%h %s (%cr) <%an>",
        )
        if not ok:
            self._add_system_message(f"git log error: {out}")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_diff_summary(self, args: str) -> None:
        """Diff summary or specific file diff."""
        if args.strip():
            ok, out = self._run_git("diff", args.strip())
        else:
            ok, out = self._run_git("diff", "--stat")
        if not ok:
            self._add_system_message(f"git diff error: {out}")
            return
        if not out.strip():
            self._add_system_message("No changes (working tree clean)")
            return
        # Truncate if too long
        lines = out.splitlines()
        if len(lines) > 50:
            out = "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} more lines)"
        # Use colorized display for actual diffs, plain for --stat
        if args.strip():
            self._show_diff(out)
        else:
            self._add_system_message(f"```\n{out}\n```")

    def _git_branches(self, args: str) -> None:
        """List branches."""
        ok, out = self._run_git("branch", "-vv")
        if not ok:
            self._add_system_message(f"git branch error: {out}")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_stashes(self, args: str) -> None:
        """List stashes."""
        ok, out = self._run_git("stash", "list")
        if not ok:
            self._add_system_message(f"git stash error: {out}")
            return
        if not out.strip():
            self._add_system_message("No stashes")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_blame(self, args: str) -> None:
        """Quick blame view."""
        if not args.strip():
            self._add_system_message("Usage: /git blame <file>")
            return
        ok, out = self._run_git("blame", "--date=short", args.strip())
        if not ok:
            self._add_system_message(f"git blame error: {out}")
            return
        lines = out.splitlines()
        if len(lines) > 50:
            out = "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} more lines)"
        self._add_system_message(f"```\n{out}\n```")

    # ------------------------------------------------------------------
    # /diff command
    # ------------------------------------------------------------------

    def _cmd_diff(self, text: str) -> None:
        """Show git diff with color-coded output, or compare messages.

        /diff              Unstaged changes (or file summary when clean)
        /diff staged       Staged changes
        /diff all          All unstaged (+ staged fallback)
        /diff last         Changes in last commit
        /diff <file>       Diff for one file (tries staged too)
        /diff <f1> <f2>    Compare two files
        /diff HEAD~N       Changes since N commits ago
        /diff <commit>     Changes since a commit
        /diff msgs         Diff last two assistant messages
        /diff msgs N M     Diff message N vs M (from bottom, 1-based)
        /diff msgs last    Same as /diff msgs
        """
        text = text.strip()

        # --- /diff msgs ... -> message comparison ---
        if text == "msgs" or text.startswith("msgs "):
            self._cmd_diff_msgs(text[4:].strip())
            return

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

    # ------------------------------------------------------------------
    # /diff msgs  – compare two chat messages
    # ------------------------------------------------------------------

    def _cmd_diff_msgs(self, text: str) -> None:
        """Compare two chat messages side-by-side (unified diff).

        /diff msgs          Last two assistant messages
        /diff msgs last     Same as above
        /diff msgs N M      Message N vs M (from bottom, 1-based)
        """
        from rich.markup import escape

        # Collect non-system messages for indexing
        messages = [
            (role, content)
            for role, content, _ in self._search_messages
            if role in ("user", "assistant")
        ]

        if len(messages) < 2:
            self._add_system_message("Need at least 2 messages to diff")
            return

        # Parse arguments
        if not text or text == "last":
            # Diff last two assistant messages
            assistant_msgs = [(r, c) for r, c in messages if r == "assistant"]
            if len(assistant_msgs) < 2:
                self._add_system_message("Need at least 2 assistant messages to diff")
                return
            msg_a = assistant_msgs[-2][1]
            msg_b = assistant_msgs[-1][1]
            label_a = "Previous response"
            label_b = "Latest response"
        else:
            parts = text.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                n, m = int(parts[0]), int(parts[1])
                total = len(messages)
                if n < 1 or n > total or m < 1 or m > total:
                    self._add_system_message(
                        f"Message numbers must be 1\u2013{total} (from bottom)"
                    )
                    return
                if n == m:
                    self._add_system_message("Messages are identical (same index)")
                    return
                msg_a = messages[-n][1]
                msg_b = messages[-m][1]
                role_a = messages[-n][0]
                role_b = messages[-m][0]
                label_a = f"Message #{n} from bottom ({role_a})"
                label_b = f"Message #{m} from bottom ({role_b})"
            else:
                self._add_system_message("Usage: /diff msgs [N M | last]")
                return

        # Generate unified diff
        lines_a = msg_a.splitlines(keepends=True)
        lines_b = msg_b.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=label_a,
                tofile=label_b,
                n=3,
            )
        )

        if not diff:
            self._add_system_message("Messages are identical")
            return

        # Count changes
        additions = sum(
            1 for ln in diff if ln.startswith("+") and not ln.startswith("+++")
        )
        deletions = sum(
            1 for ln in diff if ln.startswith("-") and not ln.startswith("---")
        )

        # Format with Rich markup colors
        formatted: list[str] = []
        for line in diff:
            line = line.rstrip("\n")
            escaped = escape(line)
            if line.startswith("+++") or line.startswith("---"):
                formatted.append(f"[bold]{escaped}[/bold]")
            elif line.startswith("+"):
                formatted.append(f"[green]{escaped}[/green]")
            elif line.startswith("-"):
                formatted.append(f"[red]{escaped}[/red]")
            elif line.startswith("@@"):
                formatted.append(f"[cyan]{escaped}[/cyan]")
            else:
                formatted.append(escaped)

        # Truncate very long diffs
        max_lines = 200
        truncated = len(formatted) > max_lines
        if truncated:
            remaining = len(formatted) - max_lines
            formatted = formatted[:max_lines]
            formatted.append(f"\n... and {remaining} more lines (diff truncated)")

        summary = f"\n\n{additions} addition(s), {deletions} deletion(s)"
        result = "\n".join(formatted) + summary

        self._add_system_message(f"Message diff:\n{result}")

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

    @staticmethod
    def _copy_preview(content: str, max_len: int = 100) -> str:
        """Return a short single-line preview of *content*."""
        preview = content[:max_len].replace("\n", " ")
        if len(content) > max_len:
            preview += "..."
        return preview

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

    def _cmd_timestamps(self) -> None:
        """Toggle message timestamps on/off."""
        self._prefs.display.show_timestamps = not self._prefs.display.show_timestamps
        save_show_timestamps(self._prefs.display.show_timestamps)
        state = "on" if self._prefs.display.show_timestamps else "off"
        # Show/hide existing timestamp widgets
        for ts_widget in self.query(".msg-timestamp"):
            ts_widget.display = self._prefs.display.show_timestamps
        # Manage periodic refresh timer for relative timestamps
        if self._prefs.display.show_timestamps:
            self._refresh_timestamps()
            if self._timestamp_timer is None:
                self._timestamp_timer = self.set_interval(
                    30.0, self._refresh_timestamps
                )
        else:
            if self._timestamp_timer is not None:
                self._timestamp_timer.stop()
                self._timestamp_timer = None
        self._add_system_message(f"Timestamps {state}")

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
        """Fold/unfold long messages, toggle Nth, or set fold threshold."""
        parts = text.strip().split(None, 2)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "all":
            self._fold_all_messages()
            return
        if arg in ("none", "off"):
            self._unfold_all_messages()
            return
        if arg == "toggle":
            self._toggle_fold_all()
            return
        if arg == "threshold":
            # /fold threshold [N] — set or show the auto-fold threshold
            val = parts[2].strip() if len(parts) > 2 else ""
            if val.isdigit():
                threshold = max(5, int(val))
                self._fold_threshold = threshold
                self._prefs.display.fold_threshold = threshold
                save_fold_threshold(threshold)
                self._add_system_message(
                    f"Fold threshold set to {threshold} lines (saved)"
                )
            elif val == "off" or val == "0":
                self._fold_threshold = 0
                self._prefs.display.fold_threshold = 0
                save_fold_threshold(0)
                self._add_system_message("Auto-fold disabled (saved)")
            else:
                self._add_system_message(
                    f"Fold threshold: {self._fold_threshold} lines\n"
                    "Usage: /fold threshold <n>  (min 5, 0 = disabled)"
                )
            return
        if arg.isdigit():
            # /fold N — toggle fold on Nth message from bottom
            self._toggle_fold_nth(int(arg))
            return
        if not arg:
            self._fold_last_message()
            return

        self._add_system_message(
            "Usage: /fold [all|none|toggle|threshold|<N>]\n"
            "  /fold            Fold the last long message\n"
            "  /fold all        Fold all long messages\n"
            "  /fold none       Unfold all messages\n"
            "  /fold toggle     Toggle fold on all long messages\n"
            "  /fold <N>        Toggle fold on Nth message from bottom\n"
            "  /fold threshold  Show or set auto-fold threshold\n"
            "  /fold threshold <n>  Set threshold (min 5, 0 = disabled)"
        )

    def _cmd_unfold(self, text: str) -> None:
        """Unfold/expand folded messages."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "all":
            self._unfold_all_messages()
            return
        if not arg:
            self._unfold_last_message()
            return

        self._add_system_message(
            "Usage: /unfold [all]\n"
            "  /unfold      Unfold the last folded message\n"
            "  /unfold all  Unfold all folded messages"
        )

    def _fold_last_message(self) -> None:
        """Fold the last unfolded foldable message (bottom-up)."""
        toggles = list(self.query(FoldToggle))
        for toggle in reversed(toggles):
            if not toggle._target.has_class("folded"):
                toggle._target.add_class("folded")
                toggle.update(toggle._make_label(folded=True))
                self._add_system_message("Folded last long message")
                return
        self._add_system_message("No unfoldable messages found")

    def _unfold_last_message(self) -> None:
        """Unfold the last folded message (bottom-up)."""
        toggles = list(self.query(FoldToggle))
        for toggle in reversed(toggles):
            if toggle._target.has_class("folded"):
                toggle._target.remove_class("folded")
                toggle.update(toggle._make_label(folded=False))
                self._add_system_message("Unfolded last folded message")
                return
        self._add_system_message("No folded messages found")

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

    def _toggle_fold_nearest(self) -> None:
        """Toggle fold on the last foldable message (vim 'z' key)."""
        toggles = list(self.query(FoldToggle))
        if not toggles:
            return
        toggle = toggles[-1]
        folded = toggle._target.has_class("folded")
        if folded:
            toggle._target.remove_class("folded")
        else:
            toggle._target.add_class("folded")
        toggle.update(toggle._make_label(folded=not folded))

    def _toggle_fold_nth(self, n: int) -> None:
        """Toggle fold on the Nth foldable message from the bottom (1-based)."""
        toggles = list(self.query(FoldToggle))
        if not toggles:
            self._add_system_message("No foldable messages")
            return
        if n < 1 or n > len(toggles):
            self._add_system_message(
                f"Message #{n} not found ({len(toggles)} foldable message"
                f"{'s' if len(toggles) != 1 else ''} available)"
            )
            return
        toggle = toggles[-n]
        folded = toggle._target.has_class("folded")
        if folded:
            toggle._target.remove_class("folded")
        else:
            toggle._target.add_class("folded")
        toggle.update(toggle._make_label(folded=not folded))
        state = "unfolded" if folded else "folded"
        self._add_system_message(f"Message #{n} from bottom {state}")

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
            except Exception:
                pass

            # Legacy: also check for old-style timestamp before the message
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

    def _cmd_keys(self) -> None:
        """Show the keyboard shortcut overlay."""
        self.action_show_shortcuts()

    def _cmd_stats(self, text: str = "") -> None:
        """Show session statistics, or a subcommand view.

        Subcommands:
            /stats          Full overview
            /stats tools    Detailed tool usage breakdown
            /stats tokens   Detailed token breakdown with cost estimate
            /stats time     Detailed timing metrics
        """
        sub = text.strip().lower()

        if sub == "tools":
            self._cmd_stats_tools()
            return
        if sub == "tokens":
            self._cmd_stats_tokens()
            return
        if sub == "time":
            self._cmd_stats_time()
            return
        if sub:
            self._add_system_message(
                f"Unknown subcommand: /stats {sub}\n"
                "Usage: /stats | /stats tools | /stats tokens | /stats time"
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

        # --- Character counts & code blocks from _search_messages ---
        user_chars = 0
        asst_chars = 0
        code_blocks = 0
        system_count = 0
        for role, content, _widget in self._search_messages:
            r = role.lower()
            if r == "user":
                user_chars += len(content or "")
            elif r == "assistant":
                asst_chars += len(content or "")
                if content:
                    code_blocks += content.count("```") // 2
            elif r == "system":
                system_count += 1
        total_chars = user_chars + asst_chars

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
            f"    System:        {system_count}",
            f"    Tool calls:    {self._tool_call_count}",
            "",
            f"  Characters:      {total_chars:,}",
            f"    You:           {user_chars:,}",
            f"    AI:            {asst_chars:,}",
            f"  Est. tokens:     ~{fmt(est_tokens)}",
        ]

        if code_blocks:
            lines.append(f"  Code blocks:     {code_blocks}")

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
                # Cost estimate summary (Claude Sonnet pricing)
                cost_in = inp_tok * 3.0 / 1_000_000
                cost_out = out_tok * 15.0 / 1_000_000
                cost_total = cost_in + cost_out
                lines.append(f"  Est. cost:       ${cost_total:.4f}")

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

        # --- Top words ---
        top = self._top_words(self._search_messages)
        if top:
            lines.append("")
            lines.append("  Top words:")
            for word, cnt in top:
                lines.append(f"    {word:<18s} {cnt}")

        lines.append("")
        lines.append("Tip: /stats tools | /stats tokens | /stats time")

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

    def _cmd_stats_time(self) -> None:
        """Show detailed timing metrics."""
        elapsed = time.monotonic() - self._session_start_time

        # Format duration nicely
        if elapsed < 60:
            duration = f"{elapsed:.0f}s"
        elif elapsed < 3600:
            m, s = divmod(int(elapsed), 60)
            duration = f"{m}m {s}s"
        else:
            h, rem = divmod(int(elapsed), 3600)
            m, s = divmod(rem, 60)
            duration = f"{h}h {m}m {s}s"

        lines: list[str] = [
            "Timing Metrics",
            "\u2500" * 40,
            f"  Session duration:  {duration}",
        ]

        total_msgs = self._user_message_count + self._assistant_message_count
        if total_msgs > 0:
            avg_interval = elapsed / total_msgs
            if avg_interval < 60:
                interval_str = f"{avg_interval:.1f}s"
            else:
                interval_str = f"{avg_interval / 60:.1f}m"
            lines.append(f"  Avg msg interval: {interval_str}")

        if self._response_times:
            times = self._response_times
            avg_t = sum(times) / len(times)
            min_t = min(times)
            max_t = max(times)
            total_wait = sum(times)
            median_t = sorted(times)[len(times) // 2]

            lines += [
                "",
                f"  Responses:         {len(times)} requests",
                f"  Total wait:        {total_wait:.1f}s",
                "",
                "  Response Time Distribution",
                "  " + "\u2500" * 28,
                f"    Min:             {min_t:.1f}s",
                f"    Median:          {median_t:.1f}s",
                f"    Avg:             {avg_t:.1f}s",
                f"    Max:             {max_t:.1f}s",
            ]

            # Standard deviation
            if len(times) > 1:
                mean = avg_t
                variance = sum((t - mean) ** 2 for t in times) / (len(times) - 1)
                std_dev = variance**0.5
                lines.append(f"    Std dev:         {std_dev:.1f}s")

            # Histogram buckets
            if len(times) >= 3:
                buckets = [
                    ("< 2s", 0, 2),
                    ("2-5s", 2, 5),
                    ("5-10s", 5, 10),
                    ("10-30s", 10, 30),
                    ("> 30s", 30, float("inf")),
                ]
                lines.append("")
                lines.append("  Response Histogram")
                lines.append("  " + "\u2500" * 28)
                for label, lo, hi in buckets:
                    n = sum(1 for t in times if lo <= t < hi)
                    if n > 0:
                        bar_w = 12
                        filled = max(1, int(n / len(times) * bar_w))
                        bar = "\u2588" * filled + "\u2591" * (bar_w - filled)
                        lines.append(f"    {label:<8s} {n:3d}  {bar}")

            # Time trend (first half vs second half)
            if len(times) >= 4:
                mid = len(times) // 2
                first_avg = sum(times[:mid]) / mid
                second_avg = sum(times[mid:]) / (len(times) - mid)
                if second_avg < first_avg * 0.9:
                    trend = "\u2193 getting faster"
                elif second_avg > first_avg * 1.1:
                    trend = "\u2191 getting slower"
                else:
                    trend = "\u2192 stable"
                lines += [
                    "",
                    f"  Trend:             {trend}",
                    f"    First half avg:  {first_avg:.1f}s",
                    f"    Second half avg: {second_avg:.1f}s",
                ]
        else:
            lines += [
                "",
                "  (no response times recorded yet)",
            ]

        self._add_system_message("\n".join(lines))

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

        # Rough cost estimate (~$3/1M input, ~$15/1M output for Claude 3.5)
        input_cost = (est_user + est_sys) / 1_000_000 * 3.0
        output_cost = est_asst / 1_000_000 * 15.0
        if api_total > 0:
            input_cost = input_tok / 1_000_000 * 3.0
            output_cost = output_tok / 1_000_000 * 15.0
        total_cost = input_cost + output_cost

        lines += [
            "",
            "Breakdown (~4 chars/token):",
            f"  User:        ~{fmt(est_user)} tokens  ({user_msg_count} messages)",
            f"  Assistant:   ~{fmt(est_asst)} tokens  ({asst_msg_count} messages)",
            f"  System:      ~{fmt(est_sys)} tokens  ({sys_msg_count} messages)",
            "",
            f"Messages: {msg_count} total",
            f"  Est. cost:   ~${total_cost:.4f}"
            f" (in ~${input_cost:.4f} + out ~${output_cost:.4f})",
            "",
            "Note: Token counts are estimates (~4 chars/token).",
            "Cost assumes Claude 3.5 Sonnet pricing ($3/1M in, $15/1M out).",
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

        color_label = _context_color_name(pct)

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

    def _cmd_showtokens(self, text: str) -> None:
        """Toggle the status-bar token/context usage display on or off."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg in ("on", "true", "1"):
            enabled = True
        elif arg in ("off", "false", "0"):
            enabled = False
        elif not arg:
            enabled = not self._prefs.display.show_token_usage
        else:
            self._add_system_message("Usage: /showtokens [on|off]")
            return

        self._prefs.display.show_token_usage = enabled
        save_show_token_usage(enabled)
        self._update_token_display()

        state = "ON" if enabled else "OFF"
        self._add_system_message(f"Token usage display: {state}")

    def _cmd_contextwindow(self, text: str) -> None:
        """Set the context window size override (0 = auto-detect)."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if not arg:
            current = self._prefs.display.context_window_size
            effective = self._get_context_window()
            if current > 0:
                self._add_system_message(
                    f"Context window: {current:,} tokens (user override)\n"
                    f"Use /contextwindow auto to auto-detect from model.\n"
                    f"Use /contextwindow <number> to set a custom size."
                )
            else:
                self._add_system_message(
                    f"Context window: {effective:,} tokens (auto-detected)\n"
                    f"Use /contextwindow <number> to override (e.g. 128000).\n"
                    f"Use /contextwindow auto to reset to auto-detect."
                )
            return

        if arg in ("auto", "0", "reset"):
            size = 0
        else:
            try:
                # Accept shorthand like "128k" or "200K"
                if arg.endswith("k"):
                    size = int(float(arg[:-1]) * 1_000)
                elif arg.endswith("m"):
                    size = int(float(arg[:-1]) * 1_000_000)
                else:
                    size = int(arg)
            except ValueError:
                self._add_system_message(
                    "Usage: /contextwindow <size|auto>\n"
                    "Examples: /contextwindow 128000, /contextwindow 128k, "
                    "/contextwindow auto"
                )
                return

        self._prefs.display.context_window_size = size
        save_context_window_size(size)
        self._update_token_display()

        if size > 0:
            self._add_system_message(
                f"Context window set to {size:,} tokens (user override)"
            )
        else:
            effective = self._get_context_window()
            self._add_system_message(
                f"Context window: auto-detect ({effective:,} tokens)"
            )

    def _cmd_theme(self, text: str) -> None:
        """Switch color theme or show current/available themes.

        Sub-commands:
          /theme              — list available themes
          /theme <name>       — apply and persist a theme
          /theme preview      — show color swatches for all themes
          /theme preview <n>  — temporarily preview a theme (live)
          /theme revert       — restore the saved theme after a preview
        """
        parts = text.strip().split(None, 1)

        if len(parts) < 2:
            # No argument: list themes with descriptions and active marker
            current = self._prefs.theme_name
            previewing = self._previewing_theme
            lines = ["Available themes:"]
            for name, desc in THEME_DESCRIPTIONS.items():
                if previewing and name == previewing:
                    marker = " >"
                elif name == current:
                    marker = " *"
                else:
                    marker = "  "
                lines.append(f"{marker} {name}: {desc}")
            lines.append("")
            lines.append(
                "Use: /theme <name>  |  /theme preview <name>  |  /theme revert"
            )
            if previewing:
                lines.append(f"  (previewing {previewing}, saved: {current})")
            self._add_system_message("\n".join(lines))
            return

        arg = parts[1].strip().lower()

        # /theme preview  OR  /theme preview <name>
        if arg == "preview":
            self._cmd_theme_preview()
            return
        if arg.startswith("preview "):
            preview_name = arg[8:].strip()
            self._preview_theme(preview_name)
            return

        # /theme revert — restore the saved theme after a preview
        if arg == "revert":
            self._revert_theme_preview()
            return

        # /theme <name> — apply and persist
        if not self._prefs.apply_theme(arg):
            available = ", ".join(THEMES)
            self._add_system_message(f"Unknown theme: {arg}\nAvailable: {available}")
            return

        self._prefs.theme_name = arg
        self._previewing_theme = None  # clear any active preview
        save_colors(self._prefs.colors)
        save_theme_name(arg)

        # Switch the Textual base theme (background, surface, panel, etc.)
        textual_theme = TEXTUAL_THEMES.get(arg)
        if textual_theme:
            self.theme = textual_theme.name

        self._apply_theme_to_all_widgets()
        desc = THEME_DESCRIPTIONS.get(arg, "")
        self._add_system_message(f"Theme: {arg} — {desc}" if desc else f"Theme: {arg}")

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

    def _cmd_theme_preview(self) -> None:
        """Show all themes with color swatches."""
        current = self._prefs.theme_name
        lines = ["Theme Preview:\n"]
        for name, colors in THEMES.items():
            active = " (active)" if name == current else ""
            desc = THEME_DESCRIPTIONS.get(name, "")
            # Build swatches for the key color roles
            user_sw = f"[{colors['user_text']}]\u2588\u2588\u2588\u2588[/]"
            asst_sw = f"[{colors['assistant_text']}]\u2588\u2588\u2588\u2588[/]"
            sys_sw = f"[{colors['system_text']}]\u2588\u2588\u2588\u2588[/]"
            border_sw = f"[{colors['user_border']}]\u2588\u2588[/]"
            think_sw = f"[{colors['thinking_border']}]\u2588\u2588[/]"
            lines.append(
                f"  {name:<16}{active:>9}  "
                f"{user_sw} {asst_sw} {sys_sw} {border_sw} {think_sw}"
                f"  {desc}"
            )
        lines.append("")
        lines.append("  Swatches: user  assistant  system  border  thinking")
        lines.append("  Apply: /theme <name>  |  Try: /theme preview <name>")
        self._add_system_message("\n".join(lines))

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
                f"  note        {c.note_text:<10} {_swatch(c.note_text)}",
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
                f"  note_text           {c.note_text:<10} {_swatch(c.note_text)}",
                f"  note_border         {c.note_border:<10} {_swatch(c.note_border)}",
                f"  timestamp           {c.timestamp:<10} {_swatch(c.timestamp)}",
                f"  status_bar          {c.status_bar:<10} {_swatch(c.status_bar)}",
                "",
                "Change:  /colors <role> <color>  e.g. /colors user white",
                "         /colors <key> <color>   e.g. /colors user_border #ff8800",
                "Reset:   /colors reset",
                "Presets: /colors presets          Show available color presets",
                "         /colors use <preset>     Apply a preset",
                "Roles:   user, assistant, system, error, tool, thinking, note, timestamp",
                "Colors:  white, gray, cyan, red, green, blue, yellow, magenta, orange, dim, #RRGGBB",
            ]
            self._add_system_message("\n".join(lines))
            return

        if arg == "reset":
            self._prefs.colors = ColorPreferences()
            save_colors(self._prefs.colors)
            self._apply_theme_to_all_widgets()
            self._add_system_message("Colors reset to defaults.")
            return

        if arg == "presets":
            self._cmd_colors_presets()
            return

        # /colors use <preset>
        if arg.startswith("use "):
            preset_name = arg[4:].strip()
            self._cmd_colors_use_preset(preset_name)
            return

        # Parse: key value
        tokens = arg.split(None, 1)
        if len(tokens) != 2:
            self._add_system_message(
                "Usage: /colors <role> <color>  e.g. /colors user white\n"
                "       /colors <key> <color>   e.g. /colors user_border #ff8800\n"
                "       /colors reset           Restore defaults\n"
                "       /colors presets          Show available color presets\n"
                "       /colors use <preset>     Apply a preset\n"
                "Roles: user, assistant, system, error, tool, thinking, note, timestamp\n"
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

    def _cmd_colors_presets(self) -> None:
        """Show available color presets with sample swatches."""

        def _swatch(hex_color: str) -> str:
            return f"[{hex_color}]\u2588\u2588[/]"

        lines = ["Color Presets:", ""]
        for name, theme_colors in THEMES.items():
            desc = THEME_DESCRIPTIONS.get(name, "")
            user_sw = _swatch(theme_colors.get("user_text", "#ffffff"))
            asst_sw = _swatch(theme_colors.get("assistant_text", "#999999"))
            sys_sw = _swatch(theme_colors.get("system_text", "#88bbcc"))
            note_sw = _swatch(theme_colors.get("note_text", "#e0d080"))
            err_sw = _swatch(theme_colors.get("error_text", "#cc0000"))
            active = " \u2190 active" if name == self._prefs.theme_name else ""
            lines.append(
                f"  {name:<16} "
                f"{user_sw} {asst_sw} {sys_sw} {note_sw} {err_sw}"
                f"  {desc}{active}"
            )
        lines.append("")
        lines.append("  Swatches: user  assistant  system  note  error")
        lines.append("  Apply: /colors use <preset>")
        self._add_system_message("\n".join(lines))

    def _cmd_colors_use_preset(self, preset_name: str) -> None:
        """Apply a color preset (theme colors) by name."""
        if not preset_name:
            self._add_system_message(
                "Usage: /colors use <preset>\nSee available presets: /colors presets"
            )
            return

        if preset_name not in THEMES:
            available = ", ".join(sorted(THEMES.keys()))
            self._add_system_message(
                f"Unknown preset '{preset_name}'.\n"
                f"Available: {available}\n"
                f"Preview: /colors presets"
            )
            return

        self._prefs.apply_theme(preset_name)
        save_colors(self._prefs.colors)
        self._apply_theme_to_all_widgets()
        self._add_system_message(
            f"Applied color preset '{preset_name}'. "
            f"Customize further with /colors <role> <color>."
        )

    # ------------------------------------------------------------------
    # Export formatters
    # ------------------------------------------------------------------

    def _get_export_metadata(self) -> dict[str, str]:
        """Gather metadata for export headers."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        session_id = (getattr(sm, "session_id", None) or "") if sm else ""
        model = (getattr(sm, "model_name", None) or "unknown") if sm else "unknown"
        total_words = getattr(self, "_user_words", 0) + getattr(
            self, "_assistant_words", 0
        )
        est_tokens = int(total_words * 1.3)
        return {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "session_id": session_id,
            "session_title": self._session_title or "",
            "model": model,
            "message_count": str(len(self._search_messages)),
            "token_estimate": f"~{est_tokens:,}",
        }

    def _export_markdown(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as markdown."""
        meta = self._get_export_metadata()
        lines = [
            "# Amplifier Chat Export",
            "",
        ]
        lines.append(f"- **Date**: {meta['date']}")
        if meta["session_id"]:
            lines.append(f"- **Session**: {meta['session_id'][:12]}")
        if meta["session_title"]:
            lines.append(f"- **Title**: {meta['session_title']}")
        lines.append(f"- **Model**: {meta['model']}")
        lines.append(f"- **Messages**: {meta['message_count']}")
        lines.append(f"- **Tokens**: {meta['token_estimate']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for role, content, _widget in messages:
            if role == "user":
                lines.append("## User")
            elif role == "assistant":
                lines.append("## Assistant")
            elif role == "thinking":
                lines.append("<details><summary>Thinking</summary>")
                lines.append("")
                lines.append(content)
                lines.append("")
                lines.append("</details>")
                lines.append("")
                lines.append("---")
                lines.append("")
                continue
            elif role == "system":
                lines.append(f"> **System**: {content}")
                lines.append("")
                lines.append("---")
                lines.append("")
                continue
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
        meta = self._get_export_metadata()
        lines: list[str] = [
            f"Amplifier Chat - {meta['date']}",
            "=" * 40,
            f"Session: {meta['session_id'][:12] if meta['session_id'] else 'n/a'}",
            f"Model: {meta['model']}",
            f"Messages: {meta['message_count']}",
            f"Tokens: {meta['token_estimate']}",
            "=" * 40,
            "",
        ]
        for role, content, _widget in messages:
            label = {
                "user": "You",
                "assistant": "AI",
                "system": "System",
                "thinking": "Thinking",
            }.get(role, role)
            lines.append(f"[{label}]")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    def _export_json(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as JSON."""
        meta = self._get_export_metadata()
        data = {
            "session_id": meta["session_id"],
            "session_title": meta["session_title"],
            "model": meta["model"],
            "exported_at": datetime.now().isoformat(),
            "message_count": len(messages),
            "token_estimate": meta["token_estimate"],
            "messages": [
                {"role": role, "content": content}
                for role, content, _widget in messages
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def _html_escape(text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    @staticmethod
    def _md_to_html(text: str) -> str:
        """Very basic markdown to HTML conversion."""
        # Code blocks (fenced)
        text = re.sub(
            r"```(\w+)?\n(.*?)\n```",
            lambda m: (
                f'<pre><code class="language-{m.group(1) or ""}">'
                f"{m.group(2)}</code></pre>"
            ),
            text,
            flags=re.DOTALL,
        )
        # Inline code
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        # Italic
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        # Line breaks (outside <pre> blocks)
        parts = re.split(r"(<pre>.*?</pre>)", text, flags=re.DOTALL)
        for i, part in enumerate(parts):
            if not part.startswith("<pre>"):
                parts[i] = part.replace("\n", "<br>\n")
        return "".join(parts)

    def _export_html(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as styled HTML with dark theme."""
        meta = self._get_export_metadata()
        title_text = (
            self._html_escape(meta["session_title"])
            if meta["session_title"]
            else "Chat Export"
        )
        html = [
            "<!DOCTYPE html>",
            "<html lang='en'><head>",
            "<meta charset='utf-8'>",
            f"<title>Amplifier - {title_text} - {meta['date']}</title>",
            "<style>",
            "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"
            " max-width: 800px; margin: 0 auto; padding: 20px; background: #1e1e2e; color: #cdd6f4; }",
            ".metadata { color: #6c7086; font-size: 0.85em; border-bottom: 1px solid #313244;"
            " padding-bottom: 1rem; margin-bottom: 2rem; }",
            ".metadata span { margin-right: 1.5em; }",
            ".message { margin: 16px 0; padding: 12px 16px; border-radius: 8px; }",
            ".user { background: #313244; border-left: 3px solid #89b4fa; }",
            ".assistant { background: #1e1e2e; border-left: 3px solid #a6e3a1; }",
            ".system { background: #181825; border-left: 3px solid #f9e2af; font-style: italic; }",
            ".thinking { background: #181825; border-left: 3px solid #9399b2; }",
            ".role { font-weight: bold; margin-bottom: 8px; color: #89b4fa; }",
            ".assistant .role { color: #a6e3a1; }",
            ".system .role { color: #f9e2af; }",
            ".thinking .role { color: #9399b2; }",
            "pre { background: #11111b; padding: 12px; border-radius: 4px; overflow-x: auto; }",
            "code { font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace; font-size: 0.9em; }",
            "p code { background: #313244; padding: 2px 5px; border-radius: 3px; }",
            "details { margin: 8px 0; }",
            "summary { cursor: pointer; color: #9399b2; font-weight: bold; }",
            ".meta { color: #6c7086; font-size: 0.85em; margin-top: 12px; }",
            "h1 { color: #cba6f7; border-bottom: 1px solid #313244; padding-bottom: 8px; }",
            "a { color: #89b4fa; }",
            "</style>",
            "</head><body>",
            "<h1>Amplifier Chat Export</h1>",
        ]
        sid_short = meta["session_id"][:12] if meta["session_id"] else "n/a"
        meta_parts = [
            f"<span><strong>Date:</strong> {meta['date']}</span>",
            f"<span><strong>Session:</strong> {self._html_escape(sid_short)}</span>",
            f"<span><strong>Model:</strong> {self._html_escape(meta['model'])}</span>",
            f"<span><strong>Messages:</strong> {meta['message_count']}</span>",
            f"<span><strong>Tokens:</strong> {self._html_escape(meta['token_estimate'])}</span>",
        ]
        if meta["session_title"]:
            meta_parts.insert(
                1,
                f"<span><strong>Title:</strong> {self._html_escape(meta['session_title'])}</span>",
            )
        html.append(f"<div class='metadata'>{''.join(meta_parts)}</div>")

        for role, content, _widget in messages:
            escaped = self._html_escape(content)
            rendered = self._md_to_html(escaped)

            if role == "thinking":
                html.append(
                    f"<details class='message thinking'>"
                    f"<summary class='role'>Thinking</summary>"
                    f"<div>{rendered}</div></details>"
                )
            else:
                role_label = {
                    "user": "User",
                    "assistant": "Assistant",
                    "system": "System",
                }.get(role, role.title())
                html.append(
                    f"<div class='message {self._html_escape(role)}'>"
                    f"<div class='role'>{role_label}</div>"
                    f"<div>{rendered}</div></div>"
                )

        html.append(
            "<p class='meta' style='text-align:center; margin-top:32px;'>"
            "Exported from Amplifier TUI</p>"
        )
        html.append("</body></html>")
        return "\n".join(html)

    # ------------------------------------------------------------------
    # /export command
    # ------------------------------------------------------------------

    def _cmd_export(self, text: str) -> None:
        """Export the current chat to markdown, HTML, plain text, or JSON.

        Usage:
            /export                  Export to markdown (default)
            /export md [path]        Markdown
            /export html [path]      Styled HTML (dark theme)
            /export json [path]      Structured JSON
            /export txt [path]       Plain text
            /export clipboard        Copy markdown to clipboard
            /export <fmt> --clipboard Copy <fmt> to clipboard
            /export help             Show this help
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # /export help — show usage
        if arg.lower() in ("help", "?"):
            self._add_system_message(
                "Export conversation:\n"
                "  /export                    Markdown (default)\n"
                "  /export md [path]          Markdown\n"
                "  /export html [path]        Styled HTML (dark theme)\n"
                "  /export json [path]        Structured JSON\n"
                "  /export txt [path]         Plain text\n"
                "  /export clipboard          Copy markdown to clipboard\n"
                "  /export <fmt> --clipboard  Copy to clipboard\n\n"
                "Default path: ./amplifier-chat-{timestamp}.{ext}"
            )
            return

        if not self._search_messages:
            self._add_system_message("No messages to export")
            return

        # Check for --clipboard flag
        to_clipboard = "--clipboard" in arg or "--clip" in arg
        arg = arg.replace("--clipboard", "").replace("--clip", "").strip()

        # Parse format and optional path
        tokens = arg.split(None, 1)
        first = tokens[0].lower() if tokens else ""
        rest = tokens[1].strip() if len(tokens) > 1 else ""

        fmt = "md"
        custom_path = ""

        format_map = {
            "md": "md",
            "markdown": "md",
            "html": "html",
            "json": "json",
            "txt": "txt",
            "text": "txt",
        }

        if first == "clipboard":
            # /export clipboard — shorthand for markdown to clipboard
            to_clipboard = True
            fmt = "md"
        elif first in format_map:
            fmt = format_map[first]
            custom_path = rest
        elif first:
            # Treat entire arg as a filename; infer format from extension
            custom_path = arg
            if arg.endswith(".html"):
                fmt = "html"
            elif arg.endswith(".json"):
                fmt = "json"
            elif arg.endswith(".txt"):
                fmt = "txt"
            else:
                fmt = "md"

        # Generate content
        messages = self._search_messages
        if fmt == "json":
            content = self._export_json(messages)
        elif fmt == "html":
            content = self._export_html(messages)
        elif fmt == "txt":
            content = self._export_text(messages)
        else:
            content = self._export_markdown(messages)

        msg_count = len(messages)

        # Clipboard mode
        if to_clipboard:
            if _copy_to_clipboard(content):
                size_str = (
                    f"{len(content):,} bytes"
                    if len(content) < 1024
                    else f"{len(content) / 1024:.1f} KB"
                )
                self._add_system_message(
                    f"Copied {msg_count} messages as {fmt.upper()}"
                    f" to clipboard ({size_str})"
                )
            else:
                self._add_system_message(
                    "Failed to copy \u2014 no clipboard tool available"
                    " (install xclip or xsel)"
                )
            return

        # Determine output path (default: cwd with amplifier-chat-* naming)
        if custom_path:
            out_path = Path(custom_path).expanduser()
        else:
            ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            out_path = Path.cwd() / f"amplifier-chat-{ts}.{fmt}"

        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
        out_path = out_path.resolve()

        # Ensure extension matches format
        ext_map = {"md": ".md", "html": ".html", "json": ".json", "txt": ".txt"}
        expected_ext = ext_map.get(fmt, f".{fmt}")
        if not out_path.suffix == expected_ext and not custom_path:
            out_path = out_path.with_suffix(expected_ext)

        # Write file
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            size = out_path.stat().st_size
            size_str = f"{size:,} bytes" if size < 1024 else f"{size / 1024:.1f} KB"
            self._add_system_message(
                f"Exported {msg_count} messages to {out_path}\n"
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
        """Rename the current tab.

        Usage:
            /rename              Show current tab name
            /rename <name>       Set tab name (max 30 chars)
            /rename reset|default|auto   Reset to auto-generated name
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        tab = self._tabs[self._active_tab_index]

        if not arg:
            current = tab.custom_name or tab.name
            self._add_system_message(
                f'Current tab: "{current}"\n'
                "Usage: /rename <name> to rename, /rename reset to restore default"
            )
            return

        if arg.lower() in ("reset", "default", "auto"):
            tab.custom_name = ""
            self._update_tab_bar()
            self._add_system_message(f'Tab name reset to default: "{tab.name}"')
            return

        name = arg[:30]
        self._rename_tab(name)
        self._add_system_message(f'Tab renamed to: "{name}"')

    def _cmd_name(self, text: str) -> None:
        """Name the current session (friendly label for search/sidebar/tabs).

        Usage:
            /name              Show current name
            /name <text>       Set session name
            /name clear        Remove the name
        """
        sid = self._get_session_id()
        if not sid:
            self._add_system_message("No active session to name.")
            return

        text = text.strip()

        # No argument: show current name
        if not text:
            custom_names = self._load_session_names()
            current = custom_names.get(sid)
            if current:
                self._add_system_message(f'Session name: "{current}"')
            else:
                self._add_system_message(
                    "Session is unnamed.\nUsage: /name <text> to set a name."
                )
            return

        # Clear the name
        if text.lower() == "clear":
            self._remove_session_name(sid)
            # Reset tab name back to default
            tab = self._tabs[self._active_tab_index]
            tab.name = f"Tab {self._active_tab_index + 1}"
            self._update_tab_bar()
            self._update_breadcrumb()
            if self._session_list_data:
                self._populate_session_list(self._session_list_data)
            self._add_system_message("Session name cleared.")
            return

        # Set the name
        try:
            self._save_session_name(sid, text)
        except Exception as e:
            self._add_system_message(f"Failed to save name: {e}")
            return

        # Update tab bar label so the name is visible immediately
        tab = self._tabs[self._active_tab_index]
        tab.name = text
        self._update_tab_bar()
        self._update_breadcrumb()

        # Refresh sidebar if loaded
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        self._add_system_message(f'Session named: "{text}"')

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

        /pin              – pin last assistant message
        /pin <N>          – pin message number N (1-based)
        /pin list         – list all pinned messages
        /pin clear        – clear all pins
        /pin remove <N>   – remove pin number N
        /pin <label>      – pin last assistant message with a label
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg.lower() == "clear":
            self._remove_all_pin_classes()
            self._message_pins = []
            self._save_message_pins()
            self._add_system_message("All message pins cleared.")
            self._update_pinned_panel()
            return

        if arg.lower() == "list":
            self._cmd_pins(text)
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

        # /pin remove N
        sub_parts = arg.split(None, 1)
        if sub_parts[0].lower() == "remove":
            if len(sub_parts) > 1 and sub_parts[1].strip().isdigit():
                self._remove_pin(int(sub_parts[1].strip()))
                return
            self._add_system_message("Usage: /pin remove <pin-number>")
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

        # Treat remaining text as a label for the last assistant message
        for i in range(len(self._search_messages) - 1, -1, -1):
            role, content, _widget = self._search_messages[i]
            if role == "assistant":
                self._add_message_pin(i, content, label=arg)
                return
        self._add_system_message("No assistant message to pin.")

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
                role = pin.get("role", "?")
            role_label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                role, role
            )
            pin_label = pin.get("label", "")
            label_str = f" [{pin_label}]" if pin_label else ""
            lines.append(
                f"  #{i} [{role_label} msg {idx + 1}]{label_str}: {pin['preview']}"
            )
        lines.append("")
        lines.append(
            "Use /pin remove <N> or /unpin <N> to remove, /pin clear to clear all"
        )
        self._add_system_message("\n".join(lines))

    def _cmd_unpin(self, text: str) -> None:
        """Remove a message pin by its pin number."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg or not arg.isdigit():
            self._add_system_message("Usage: /unpin <pin-number>")
            return

        self._remove_pin(int(arg))

    # ── Session Notes Commands ─────────────────────────────────────────

    def _cmd_note(self, args: str) -> None:
        """Add or manage session notes.

        /note <text>    – add a note
        /note list      – show all notes
        /note clear     – remove all notes
        /notes          – alias for /note list
        """
        text = args.strip()

        if not text:
            self._add_system_message(
                "Usage:\n"
                "  /note <text>    Add a note\n"
                "  /note list      Show all notes\n"
                "  /note clear     Remove all notes\n"
                "  /notes          Alias for /note list"
            )
            return

        if text.lower() == "list":
            self._show_notes()
            return

        if text.lower() == "clear":
            self._session_notes.clear()
            self._save_notes()
            self._add_system_message("All notes cleared.")
            return

        # Add a note
        note = {
            "text": text,
            "created_at": datetime.now().isoformat(),
            "position": len(self._search_messages),
        }
        self._session_notes.append(note)
        self._save_notes()

        # Display the note in chat with special styling
        self._add_note_message(text)

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
            except Exception:
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
            except Exception:
                ts = "?"
            note_text = f"\U0001f4dd Note ({ts}): {note['text']}"
            msg = NoteMessage(note_text)
            chat_view.mount(msg)
            self._style_note(msg)
            self._search_messages.append(("note", note["text"], msg))

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
        """Bookmark command with subcommands.

        /bookmark          — bookmark last assistant message
        /bookmark list     — list all bookmarks
        /bookmark N        — toggle bookmark on Nth message from bottom
        /bookmark jump N   — scroll to bookmark N
        /bookmark clear    — remove all bookmarks
        /bookmark remove N — remove bookmark N
        /bookmark <label>  — bookmark last message with a label
        """
        parts = text.strip().split(None, 1)
        args = parts[1].strip() if len(parts) > 1 else ""

        if not args:
            self._bookmark_last_message()
            return

        arg_parts = args.split(None, 1)
        subcmd = arg_parts[0].lower()

        if subcmd == "list":
            self._list_bookmarks()
        elif subcmd == "clear":
            self._clear_bookmarks()
        elif subcmd == "jump" and len(arg_parts) > 1 and arg_parts[1].strip().isdigit():
            self._jump_to_bookmark(int(arg_parts[1].strip()))
        elif (
            subcmd == "remove" and len(arg_parts) > 1 and arg_parts[1].strip().isdigit()
        ):
            self._remove_bookmark(int(arg_parts[1].strip()))
        elif subcmd.isdigit():
            self._bookmark_nth_message(int(subcmd))
        else:
            # Treat remaining text as a label for the last message
            self._bookmark_last_message(label=args)

    def _cmd_bookmarks(self, text: str) -> None:
        """List bookmarks or jump to a specific bookmark by number."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg.isdigit():
            self._jump_to_bookmark(int(arg))
            return

        self._list_bookmarks()

    # ── Bookmark helpers ──────────────────────────────────────────

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
        all_bm = self._load_bookmarks()
        all_bm[session_id] = list(self._session_bookmarks)
        self.BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.BOOKMARKS_FILE.write_text(json.dumps(all_bm, indent=2))

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
        label = self._processing_label or "Thinking"
        elapsed_str = self._format_elapsed()

        # Build indicator text with optional elapsed timer
        indicator_text = f" {frame} {label}..."
        if elapsed_str:
            indicator_text += f"  [{elapsed_str}]"

        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            indicator.update(indicator_text)
        except Exception:
            pass

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
        self._status_activity_label = "Ready"
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
        # Auto-save after every completed response
        self._do_autosave()

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

    def _flash_title_bar(self) -> None:
        """Briefly change the terminal title to signal response completion.

        Uses OSC 2 (Set Window Title) to show "[✓ Ready] Amplifier TUI",
        then schedules a restore after 3 seconds.  Writes to ``sys.__stdout__``
        to bypass Textual's stdout capture.
        """
        out = sys.__stdout__
        if out is None:
            return
        try:
            out.write("\033]2;[\u2713 Ready] Amplifier TUI\a")
            out.flush()
        except Exception:
            pass
        self.set_timer(3.0, self._restore_title)

    def _restore_title(self) -> None:
        """Restore the normal terminal title after a title-bar flash."""
        out = sys.__stdout__
        if out is None:
            return
        try:
            out.write("\033]2;Amplifier TUI\a")
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
        elapsed_str = self._format_elapsed()
        text = f" {frame} {display_label}..."
        if elapsed_str:
            text += f"  [{elapsed_str}]"

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
            self._status_activity_label = label
            self.call_from_thread(self._ensure_processing_indicator, bare)
            self.call_from_thread(self._update_status, label)

        def on_tool_end(name: str, tool_input: dict, result: str) -> None:
            self._processing_label = "Thinking"
            self._status_activity_label = "Thinking..."
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
