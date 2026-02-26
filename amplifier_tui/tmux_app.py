"""Tmux-mode TUI: a stripped-down single-session Amplifier interface.

Designed for use inside tmux panes.  No tab bar, no session sidebar,
no split view — just a chat input, a scrollable message area, and a
status bar.

Features beyond the base TUI:
  - Auto-detects tmux via $TMUX env var
  - Sends BEL (\\a) on turn completion so ``monitor-activity`` triggers
  - Stores/reads ``@amp_session_id`` tmux pane variable for auto-resume
  - Tmux-specific slash commands: /move-to, /shell, /amp help
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widgets import Collapsible, Markdown, Static
from textual import work

from .core.app_base import SharedAppBase
from .core.constants import (
    DEFAULT_CONTEXT_WINDOW,
    EXTENSION_TO_LANGUAGE,
    MAX_INCLUDE_LINES,
    MAX_INCLUDE_SIZE,
    MODEL_CONTEXT_WINDOWS,
)
from .core.conversation import ConversationState
from .core.history import PromptHistory
from .core.session_manager import SessionManager
from .core.log import logger
from .core.commands.content_cmds import ContentCommandsMixin
from .core.commands.file_cmds import FileCommandsMixin
from .core.commands.git_cmds import GitCommandsMixin
from .core.commands.shell_cmds import ShellCommandsMixin
from .core.commands.token_cmds import TokenCommandsMixin
from .commands.tmux_cmds import TmuxCommandsMixin
from .widgets.chat_input import ChatInput
from .widgets.messages import AssistantMessage, UserMessage
from .widgets.indicators import (
    ErrorMessage,
    ProcessingIndicator,
    SystemMessage,
)

if TYPE_CHECKING:
    from textual.timer import Timer

# ---------------------------------------------------------------------------
# Tmux helpers
# ---------------------------------------------------------------------------


def _tmux_get_pane_var(name: str) -> str | None:
    """Read a tmux pane user variable.  Returns None outside tmux."""
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
    """Write a tmux pane user variable.  No-op outside tmux."""
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
# TmuxApp
# ---------------------------------------------------------------------------

_TMUX_CSS = """\
Screen {
    background: $background;
}

#tmux-chat-view {
    width: 1fr;
    height: 1fr;
    overflow-y: auto;
    padding: 0 1;
}

#chat-input {
    dock: bottom;
    min-height: 1;
    max-height: 8;
    margin: 0 0;
    border-top: solid $accent;
}

#tmux-status-bar {
    dock: bottom;
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 1;
}

.user-message {
    margin: 1 0 0 0;
    padding: 0 1;
    border-left: thick $warning;
    text-style: bold;
}

.assistant-message {
    margin: 1 0 0 0;
    padding: 0 1;
    border-left: thick $accent;
}

.system-message {
    margin: 1 0 0 0;
    padding: 0 1;
    color: $text-muted;
    border-left: thick $secondary;
}

.error-message {
    margin: 1 0 0 0;
    padding: 0 1;
    color: $error;
    border-left: thick $error;
}

.processing-indicator {
    margin: 0 0;
    padding: 0 1;
    color: $text-muted;
}

.thinking-block {
    margin: 0 0;
    padding: 0 1;
    color: $text-disabled;
}

.thinking-text {
    color: $text-disabled;
}

.tool-call {
    margin: 0 0;
    padding: 0 1;
    color: $text-disabled;
}

.welcome-screen {
    margin: 2 2;
    color: $text-muted;
    text-align: center;
}
"""


class TmuxApp(
    TmuxCommandsMixin,
    ShellCommandsMixin,
    ContentCommandsMixin,
    FileCommandsMixin,
    GitCommandsMixin,
    TokenCommandsMixin,
    SharedAppBase,
    App,
):
    """Single-session Amplifier TUI optimised for tmux panes."""

    CSS = _TMUX_CSS
    TITLE = "Amplifier (tmux)"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
        Binding("ctrl+y", "copy_response", "Copy", show=False),
        Binding("escape", "cancel_streaming", "Cancel", show=False),
    ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        resume_session_id: str | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.resume_session_id = resume_session_id
        self.initial_prompt = initial_prompt

        # Single conversation (no tabs)
        self._conversation = ConversationState()

        # App-level state expected by mixins / SharedAppBase
        self._amplifier_available: bool = True
        self._amplifier_ready: bool = False
        self._auto_scroll: bool = True

        # Statistics (expected by TokenCommandsMixin._cmd_stats)
        self._session_start_time: float = time.monotonic()
        self._session_title: str = ""
        self._total_words: int = 0
        self._user_message_count: int = 0
        self._assistant_message_count: int = 0
        self._tool_call_count: int = 0
        self._user_words: int = 0
        self._assistant_words: int = 0
        self._response_times: list[float] = []
        self._tool_usage: dict[str, int] = {}
        self._last_assistant_text: str = ""
        self._assistant_msg_index: int = 0

        # Search index (role, text) — no widget refs for simplicity
        self._search_messages: list[tuple[str, str, Static | None]] = []

        # System prompt
        self._system_prompt: str = ""
        self._system_preset_name: str = ""

        # Streaming display state
        self._stream_widget: Static | Markdown | None = None
        self._stream_block_type: str = ""

        # Spinner
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None
        self._processing_label: str = "Thinking"

        # Preferences (load for mixins that check self._prefs)
        try:
            from .preferences import load_preferences

            self._prefs = load_preferences()
        except Exception:
            self._prefs = None  # type: ignore[assignment]

        # Aliases (for /alias expansion)
        self._aliases: dict[str, str] = {}

        # Prompt history (expected by FileCommandsMixin._cmd_run)
        self._history = PromptHistory()

        # Attributes expected by non-routed mixin commands
        # (prevents AttributeError if accidentally invoked)
        self._clipboard_store: list[str] = []
        self._attachments: list[str] = []
        self._pending_undo: tuple[str, str] | None = None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield ScrollableContainer(id="tmux-chat-view")
            yield ChatInput(
                "",
                id="chat-input",
                soft_wrap=True,
                show_line_numbers=False,
                tab_behavior="focus",
                compact=True,
            )
            yield Static("No session | Ready", id="tmux-status-bar")

    # ------------------------------------------------------------------
    # Mount
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        self._show_welcome()
        self.query_one("#chat-input", ChatInput).focus()

        # Spinner timer
        self._spinner_timer = self.set_interval(0.3, self._animate_spinner)

        # Check for auto-resume via tmux pane variable
        if not self.resume_session_id:
            pane_session = _tmux_get_pane_var("@amp_session_id")
            if pane_session:
                self.resume_session_id = pane_session

        # Heavy init in background (@work decorator returns Worker, not coroutine)
        self._init_amplifier_worker()  # type: ignore[reportUnusedCoroutine]

    # ------------------------------------------------------------------
    # Abstract implementations: SharedAppBase
    # ------------------------------------------------------------------

    def _all_conversations(self) -> list[ConversationState]:
        return [self._conversation]

    def _active_chat_view(self) -> ScrollableContainer:
        return self.query_one("#tmux-chat-view", ScrollableContainer)

    # --- Display methods (called from main thread) ---

    def _add_system_message(
        self, text: str, *, conversation_id: str = "", **kwargs: object
    ) -> None:
        chat_view = self._active_chat_view()
        msg = SystemMessage(text)
        chat_view.mount(msg)
        self._scroll_if_auto(msg)
        self._search_messages.append(("system", text, msg))

    def _add_user_message(
        self, text: str, *, conversation_id: str = "", **kwargs: object
    ) -> None:
        chat_view = self._active_chat_view()
        msg = UserMessage(text)
        chat_view.mount(msg)
        self._scroll_if_auto(msg)
        self._search_messages.append(("user", text, msg))
        words = len(text.split())
        self._total_words += words
        self._user_message_count += 1
        self._user_words += words

    def _add_assistant_message(
        self, text: str, *, conversation_id: str = "", **kwargs: object
    ) -> None:
        chat_view = self._active_chat_view()
        msg = AssistantMessage(text)
        chat_view.mount(msg)
        self._scroll_if_auto(msg)
        self._last_assistant_text = text
        self._search_messages.append(("assistant", text, msg))
        words = len(text.split())
        self._total_words += words
        self._assistant_message_count += 1
        self._assistant_words += words
        self._assistant_msg_index += 1

    def _show_error(self, text: str, *, conversation_id: str = "") -> None:
        chat_view = self._active_chat_view()
        msg = ErrorMessage(f"Error: {text}", classes="error-message")
        chat_view.mount(msg)
        self._scroll_if_auto(msg)

    def _update_status(self, text: str = "Ready", *, conversation_id: str = "") -> None:
        sid = ""
        if self.session_manager and self.session_manager.session_id:
            sid = self.session_manager.session_id[:8]
        model = ""
        if self.session_manager and self.session_manager.model_name:
            model = self.session_manager.model_name
        parts = []
        if sid:
            parts.append(sid)
        if model:
            parts.append(model)
        parts.append(text)
        try:
            self.query_one("#tmux-status-bar", Static).update(" | ".join(parts))
        except NoMatches:
            pass

    def _start_processing(
        self, label: str = "Thinking", *, conversation_id: str = ""
    ) -> None:
        conv = self._conversation
        conv.is_processing = True
        conv.got_stream_content = False
        conv.processing_start_time = time.monotonic()
        conv.tool_count_this_turn = 0
        self._processing_label = label

        chat_view = self._active_chat_view()
        indicator = ProcessingIndicator(
            f" \u280b {label}...",
            classes="processing-indicator",
            id="processing-indicator",
        )
        chat_view.mount(indicator)
        self._scroll_if_auto(indicator)
        self._update_status(f"{label}...")

        try:
            inp = self.query_one("#chat-input", ChatInput)
            inp.placeholder = "Type to queue next message..."
        except NoMatches:
            pass

    def _finish_processing(self, *, conversation_id: str = "") -> None:
        conv = self._conversation
        if not conv.is_processing:
            return
        conv.is_processing = False
        conv.tool_count_this_turn = 0
        conv.streaming_cancelled = False
        conv.stream_accumulated_text = ""
        self._stream_widget = None
        self._stream_block_type = ""

        # Record response time
        if conv.processing_start_time is not None:
            elapsed = time.monotonic() - conv.processing_start_time
            conv.processing_start_time = None
            self._response_times.append(elapsed)

        self._remove_processing_indicator()
        self._update_status("Ready")

        try:
            inp = self.query_one("#chat-input", ChatInput)
            inp.placeholder = "Message..."
            inp.focus()
        except NoMatches:
            pass

        # BEL character for tmux monitor-activity
        _send_bel()

        # Mid-turn steering: send queued message
        if conv.queued_message:
            queued = conv.queued_message
            conv.queued_message = None
            self.set_timer(0.1, lambda: self._send_queued(queued))

    # --- Streaming display methods (called from BACKGROUND thread) ---

    def _on_stream_block_start(self, conversation_id: str, block_type: str) -> None:
        self.call_from_thread(self._begin_streaming_block, block_type)

    def _on_stream_block_delta(
        self, conversation_id: str, block_type: str, accumulated_text: str
    ) -> None:
        self.call_from_thread(
            self._update_streaming_content, block_type, accumulated_text
        )

    def _on_stream_block_end(
        self,
        conversation_id: str,
        block_type: str,
        final_text: str,
        had_block_start: bool,
    ) -> None:
        if had_block_start:
            self.call_from_thread(
                self._finalize_streaming_block, block_type, final_text
            )
        else:
            self.call_from_thread(self._remove_processing_indicator)
            if block_type in ("thinking", "reasoning"):
                self.call_from_thread(self._add_thinking_block, final_text)
            else:
                self.call_from_thread(self._add_assistant_message, final_text)

    def _on_stream_tool_start(
        self, conversation_id: str, name: str, tool_input: dict
    ) -> None:
        label = f"Running {name}"
        self._processing_label = label
        self.call_from_thread(self._ensure_processing_indicator, label)
        self.call_from_thread(self._update_status, f"{label}...")

    def _on_stream_tool_end(
        self, conversation_id: str, name: str, tool_input: dict, result: str
    ) -> None:
        self._processing_label = "Thinking"
        self.call_from_thread(self._add_tool_use, name, tool_input, result)
        self.call_from_thread(self._ensure_processing_indicator, "Thinking")
        self.call_from_thread(self._update_status, "Thinking...")

    def _on_stream_usage_update(self, conversation_id: str) -> None:
        self.call_from_thread(self._update_status, "Thinking...")

    # ------------------------------------------------------------------
    # Streaming display helpers (main thread)
    # ------------------------------------------------------------------

    def _begin_streaming_block(self, block_type: str) -> None:
        self._remove_processing_indicator()
        chat_view = self._active_chat_view()
        if block_type in ("thinking", "reasoning"):
            widget = Static("", classes="thinking-text")
            self._stream_block_type = "thinking"
        else:
            widget = Static("", classes="assistant-message")
            self._stream_block_type = "text"
        chat_view.mount(widget)
        self._stream_widget = widget
        self._scroll_if_auto(widget)

    def _update_streaming_content(self, block_type: str, accumulated_text: str) -> None:
        if self._stream_widget is not None:
            self._stream_widget.update(accumulated_text)
            self._scroll_if_auto(self._stream_widget)

    def _finalize_streaming_block(self, block_type: str, final_text: str) -> None:
        if self._stream_widget is None:
            return
        old_widget = self._stream_widget
        self._stream_widget = None

        if block_type in ("thinking", "reasoning"):
            # Replace streaming static with collapsed thinking block
            old_widget.remove()
            self._add_thinking_block(final_text)
        else:
            # Replace streaming static with proper Markdown AssistantMessage
            old_widget.remove()
            self._add_assistant_message(final_text)

    def _add_thinking_block(self, text: str) -> None:
        chat_view = self._active_chat_view()
        preview = text.split("\n")[0][:55]
        if len(text) > 55:
            preview += "..."
        full = text[:800] + "..." if len(text) > 800 else text
        inner = Static(full, classes="thinking-text")
        collapsible = Collapsible(
            inner,
            title=f"\u25b6 Thinking: {preview}",
            collapsed=True,
            classes="thinking-block",
        )
        chat_view.mount(collapsible)

    def _add_tool_use(self, name: str, tool_input: dict, result: str) -> None:
        chat_view = self._active_chat_view()
        summary = result[:120].replace("\n", " ") if result else ""
        inner = Static(summary, classes="tool-call")
        collapsible = Collapsible(
            inner,
            title=f"\u25b6 {name}",
            collapsed=True,
            classes="tool-call",
        )
        chat_view.mount(collapsible)
        self._tool_call_count += 1
        self._tool_usage[name] = self._tool_usage.get(name, 0) + 1

    # ------------------------------------------------------------------
    # Processing indicator helpers
    # ------------------------------------------------------------------

    _SPINNER = [
        "\u280b",
        "\u2819",
        "\u2839",
        "\u2838",
        "\u283c",
        "\u2834",
        "\u2826",
        "\u2827",
        "\u2807",
        "\u280f",
    ]

    def _animate_spinner(self) -> None:
        conv = self._conversation
        if not conv.is_processing:
            return
        self._spinner_frame = (self._spinner_frame + 1) % len(self._SPINNER)
        frame = self._SPINNER[self._spinner_frame]
        label = self._processing_label
        elapsed_str = self._format_elapsed()
        indicator_text = f" {frame} {label}..."
        if elapsed_str:
            indicator_text += f"  [{elapsed_str}]"
        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            indicator.update(indicator_text)
        except NoMatches:
            pass

    def _format_elapsed(self) -> str:
        start = self._conversation.processing_start_time
        if start is None:
            return ""
        elapsed = time.monotonic() - start
        if elapsed < 3:
            return ""
        if elapsed < 60:
            return f"{elapsed:.0f}s"
        minutes = int(elapsed) // 60
        seconds = int(elapsed) % 60
        return f"{minutes}m {seconds:02d}s"

    def _remove_processing_indicator(self) -> None:
        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            indicator.remove()
        except NoMatches:
            pass

    def _ensure_processing_indicator(self, label: str) -> None:
        try:
            indicator = self.query_one("#processing-indicator", ProcessingIndicator)
            frame = self._SPINNER[self._spinner_frame]
            indicator.update(f" {frame} {label}...")
        except NoMatches:
            chat_view = self._active_chat_view()
            frame = self._SPINNER[self._spinner_frame]
            indicator = ProcessingIndicator(
                f" {frame} {label}...",
                classes="processing-indicator",
                id="processing-indicator",
            )
            chat_view.mount(indicator)

    # ------------------------------------------------------------------
    # Scroll helper
    # ------------------------------------------------------------------

    def _scroll_if_auto(self, widget: Static | Markdown) -> None:
        if self._auto_scroll:
            try:
                chat_view = self._active_chat_view()
                chat_view.scroll_end(animate=False)
            except NoMatches:
                pass

    # ------------------------------------------------------------------
    # Welcome screen
    # ------------------------------------------------------------------

    def _show_welcome(self, subtitle: str = "") -> None:
        chat_view = self._active_chat_view()
        for w in self.query(".welcome-screen"):
            w.remove()
        lines = [
            "Amplifier TUI (tmux mode)",
            "",
            "Type a message to start a new session.",
            "/help for commands.  /quit to exit.",
        ]
        if subtitle:
            lines.append(f"\n{subtitle}")
        chat_view.mount(Static("\n".join(lines), classes="welcome-screen"))

    def _clear_welcome(self) -> None:
        for w in self.query(".welcome-screen"):
            w.remove()

    # ------------------------------------------------------------------
    # Properties expected by core command mixins
    # ------------------------------------------------------------------

    @property
    def is_processing(self) -> bool:
        """Whether the app is currently processing a request."""
        return self._conversation.is_processing

    # ------------------------------------------------------------------
    # Update helpers expected by core command mixins
    # ------------------------------------------------------------------

    def _update_system_indicator(self) -> None:
        """No-op — tmux mode has no system-prompt indicator widget."""

    def _update_token_display(self) -> None:
        """Refresh token info in the status bar."""
        self._update_status(
            "Ready" if not self._conversation.is_processing else "Thinking..."
        )

    def _update_session_display(self) -> None:
        """Refresh session info in the status bar."""
        self._update_status("Ready")

    def _update_word_count_display(self) -> None:
        """No-op — no word count widget in tmux mode."""

    @staticmethod
    def _format_token_count(count: int) -> str:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 10_000:
            val = count / 1_000
            return f"{val:.0f}k" if val >= 100 else f"{val:.1f}k"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}k"
        return str(count)

    @staticmethod
    def _format_count(count: int) -> str:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}k"
        return str(count)

    @staticmethod
    def _count_words(text: str) -> int:
        return len(text.split())

    @staticmethod
    def _extract_title(message: str, max_len: int = 50) -> str:
        text = re.sub(r"```.*?```", "", message, flags=re.DOTALL)
        text = re.sub(r"`[^`]+`", "", text)
        text = re.sub(r"[#*_~>\[\]()]", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = text.strip()
        if not text:
            return "Untitled"
        first_line = text.split("\n")[0].strip()
        if len(first_line) > max_len:
            first_line = first_line[:max_len].rsplit(" ", 1)[0] + "..."
        return first_line

    # ------------------------------------------------------------------
    # Methods expected by core command mixins
    # ------------------------------------------------------------------

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

    def _get_context_window(self) -> int:
        """Get context window size for the current model."""
        # User-configured override (0 = auto-detect)
        if self._prefs and self._prefs.display.context_window_size > 0:
            return self._prefs.display.context_window_size

        sm = self.session_manager
        if sm and sm.context_window > 0:
            return sm.context_window

        # Build a model string from whatever is available.
        model = ""
        if sm and sm.model_name:
            model = sm.model_name
        elif self._prefs and self._prefs.preferred_model:
            model = self._prefs.preferred_model

        if model:
            model_lower = model.lower()
            for key, size in MODEL_CONTEXT_WINDOWS.items():
                if key in model_lower:
                    return size

        return DEFAULT_CONTEXT_WINDOW

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

    def _update_mode_display(self) -> None:
        """No-op — tmux mode has no dedicated mode indicator widget."""

    def _execute_undo(self) -> None:
        """No-op — undo not supported in tmux mode."""
        self._add_system_message("Undo is not supported in tmux mode.")

    def action_show_shortcuts(self) -> None:
        """No-op — tmux mode has no shortcuts overlay."""
        self._add_system_message(
            "Shortcuts: Ctrl+Q=Quit  Ctrl+L=Clear  Ctrl+Y=Copy  Esc=Cancel"
        )

    def action_open_editor(self) -> None:
        """No-op — external editor not supported in tmux mode."""
        self._add_system_message("External editor is not supported in tmux mode.")

    # ------------------------------------------------------------------
    # Amplifier init (background worker)
    # ------------------------------------------------------------------

    @work(thread=True)
    async def _init_amplifier_worker(self) -> None:
        self.call_from_thread(self._update_status, "Loading Amplifier...")
        try:
            self.session_manager = SessionManager()
        except Exception:
            logger.debug("Failed to init session manager", exc_info=True)
            self._amplifier_available = False
            self.call_from_thread(
                self._show_welcome,
                "Amplifier session manager failed to initialise.\n"
                "Use /environment for diagnostics.",
            )
            self.call_from_thread(self._update_status, "Not connected")
            return

        # Proactive readiness check
        try:
            from .environment import check_environment, format_status

            ws = self._prefs.environment.workspace if self._prefs else None
            env_status = check_environment(ws or "")
            if not env_status.ready:
                self._amplifier_available = False
                diag = format_status(env_status)
                self.call_from_thread(
                    self._show_welcome,
                    diag + "\n\nFix the issues above, then restart.",
                )
                self.call_from_thread(self._update_status, "Setup needed")
                return
        except Exception:
            logger.debug("Environment check failed", exc_info=True)

        self._amplifier_ready = True

        if self.resume_session_id:
            await self._resume_session_worker(self.resume_session_id)
        elif self.initial_prompt:
            prompt = self.initial_prompt
            self.initial_prompt = None
            cid = self._conversation.conversation_id
            self.call_from_thread(self._clear_welcome)
            self.call_from_thread(self._add_user_message, prompt)
            self.call_from_thread(
                self._start_processing, "Starting session", conversation_id=cid
            )
            await self._send_message_worker(prompt)
        else:
            self.call_from_thread(self._update_status, "Ready")

    # ------------------------------------------------------------------
    # Send message (background worker)
    # ------------------------------------------------------------------

    @work(thread=True, group="send-message")
    async def _send_message_worker(self, message: str) -> None:
        conv = self._conversation
        cid = conv.conversation_id
        if self.session_manager is None:
            self.call_from_thread(self._add_system_message, "No active session")
            return
        try:
            handle = self.session_manager.get_handle(cid)
            if not handle or not handle.session:
                self.call_from_thread(self._update_status, "Starting session...")
                model = self._prefs.preferred_model if self._prefs else ""
                ws = self._prefs.environment.workspace if self._prefs else None
                session_cwd = Path(ws) if ws and Path(ws).is_dir() else None
                try:
                    await self.session_manager.start_new_session(
                        conversation_id=cid,
                        model_override=model or "",
                        cwd=session_cwd,
                    )
                except Exception as session_err:
                    logger.debug("Session creation failed", exc_info=True)
                    self.call_from_thread(
                        self._show_error,
                        f"Could not start session: {session_err}",
                    )
                    return
                # Store session ID in tmux pane variable for auto-resume
                new_handle = self.session_manager.get_handle(cid)
                if new_handle and new_handle.session_id:
                    _tmux_set_pane_var("@amp_session_id", new_handle.session_id)
                self.call_from_thread(self._update_session_display)

            # Auto-title from first message
            if not self._session_title:
                self._session_title = self._extract_title(message)

            self._wire_streaming_callbacks(cid, conv)
            self.call_from_thread(self._update_status, "Thinking...")

            # Inject system prompt if set
            actual_message = message
            if self._system_prompt:
                actual_message = (
                    f"[System instructions: {self._system_prompt}]\n\n{message}"
                )

            response = await self.session_manager.send_message(
                actual_message, conversation_id=cid
            )

            if conv.streaming_cancelled:
                return

            if not conv.got_stream_content and response:
                self.call_from_thread(self._add_assistant_message, response)

        except Exception as e:
            logger.debug("send message worker failed", exc_info=True)
            if conv.streaming_cancelled:
                return
            self.call_from_thread(self._show_error, str(e))
        finally:
            self.call_from_thread(self._finish_processing, conversation_id=cid)

    # ------------------------------------------------------------------
    # Resume session (background worker)
    # ------------------------------------------------------------------

    @work(thread=True, group="send-message")
    async def _resume_session_worker(self, session_id: str) -> None:
        conv = self._conversation
        cid = conv.conversation_id
        if self.session_manager is None:
            self.call_from_thread(self._add_system_message, "No active session")
            return
        self.call_from_thread(self._clear_welcome)
        self.call_from_thread(self._update_status, "Loading session...")

        try:
            if session_id == "__most_recent__":
                session_id = self.session_manager._find_most_recent_session()

            model = self._prefs.preferred_model if self._prefs else ""
            await self.session_manager.resume_session(
                session_id,
                conversation_id=cid,
                model_override=model or "",
            )

            self._wire_streaming_callbacks(cid, conv)

            # Store session ID in tmux pane variable
            _tmux_set_pane_var("@amp_session_id", session_id)

            self.call_from_thread(self._update_session_display)
            self.call_from_thread(self._update_status, "Ready (resumed)")
            self.call_from_thread(
                self._add_system_message,
                f"Resumed session {session_id[:12]}...",
            )

            # Handle initial prompt after resume
            if self.initial_prompt:
                prompt = self.initial_prompt
                self.initial_prompt = None
                self.call_from_thread(self._add_user_message, prompt)
                self.call_from_thread(
                    self._start_processing, "Thinking", conversation_id=cid
                )
                self._wire_streaming_callbacks(cid, conv)
                response = await self.session_manager.send_message(
                    prompt, conversation_id=cid
                )
                if not conv.got_stream_content and response:
                    self.call_from_thread(self._add_assistant_message, response)
                self.call_from_thread(self._finish_processing, conversation_id=cid)

        except Exception as e:
            logger.debug("resume session worker failed", exc_info=True)
            self.call_from_thread(self._show_error, f"Failed to resume: {e}")
            self.call_from_thread(self._update_status, "Error")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        await self._submit_message()

    async def _submit_message(self) -> None:
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
        except NoMatches:
            return
        text = input_widget.text.strip()
        if not text:
            return
        conv = self._conversation
        if conv.is_processing:
            input_widget.clear()
            conv.queued_message = text
            self._add_system_message(
                f"Queued (will send after current response): {text[:80]}"
            )
            return

        if self._auto_scroll is False:
            self._auto_scroll = True

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
        self._clear_welcome()
        self._add_user_message(text)

        # Prepend mode context
        expanded = text
        if self._active_mode:
            expanded = f"/mode {self._active_mode}\n{expanded}"

        handle = (
            self.session_manager.get_handle(conv.conversation_id)
            if self.session_manager
            else None
        )
        has_session = handle and handle.session
        self._start_processing("Starting session" if not has_session else "Thinking")
        await self._send_message_worker(expanded)

    async def _send_queued(self, message: str) -> None:
        if not self._amplifier_ready:
            return
        self._add_user_message(message)
        self._start_processing("Thinking")
        await self._send_message_worker(message)

    # ------------------------------------------------------------------
    # Slash command routing
    # ------------------------------------------------------------------

    def _handle_slash_command(self, text: str, _alias_depth: int = 0) -> None:
        if _alias_depth > 5:
            self._add_system_message("Alias recursion limit reached")
            return

        stripped = text.strip()
        if stripped.startswith("/!"):
            self._cmd_run(stripped[2:].strip())
            return

        parts = text.strip().split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers: dict[str, object] = {
            # -- Built-in --
            "/help": self._cmd_help,
            "/clear": self._cmd_clear,
            "/new": self._cmd_new,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
            "/info": self._cmd_info,
            "/model": lambda: self._cmd_model(text),
            "/stream": lambda: self._cmd_stream(args),
            "/resume": lambda: self._cmd_resume(args),
            "/sessions": lambda: self._cmd_sessions_list(args),
            "/environment": self._cmd_environment,
            "/env": self._cmd_environment,
            # -- From core command mixins --
            "/run": lambda: self._cmd_run(args),
            "/shell": lambda: self._cmd_tmux_shell(),
            "/system": lambda: self._cmd_system(args),
            "/copy": lambda: self._cmd_copy_last(),
            "/tokens": lambda: self._cmd_tokens_display(),
            "/stats": lambda: self._cmd_stats(args),
            "/git": lambda: self._cmd_git(args),
            "/diff": lambda: self._cmd_diff(args),
            "/include": lambda: self._cmd_include(args),
            "/cat": lambda: self._cmd_cat(args),
            # -- Tmux-specific --
            "/move-to": lambda: self._cmd_tmux_move_to(args),
            "/amp": lambda: self._cmd_amp(args),
        }

        handler = handlers.get(cmd)
        if handler:
            handler()  # type: ignore[operator]
        else:
            self._add_system_message(
                f"Unknown command: {cmd}\nType /help for available commands."
            )

    # ------------------------------------------------------------------
    # Built-in command handlers
    # ------------------------------------------------------------------

    def _cmd_help(self) -> None:
        self._add_system_message(
            "Amplifier TUI (tmux mode) Commands\n"
            "\n"
            "  /help          Show this help\n"
            "  /clear         Clear chat\n"
            "  /new           Start a new session\n"
            "  /resume [id]   Resume a session (most recent if no id)\n"
            "  /sessions      List available sessions\n"
            "  /model [name]  Show or switch model\n"
            "  /system [text] Set/view/clear system prompt\n"
            "  /tokens        Show token usage\n"
            "  /stats         Show session statistics\n"
            "  /copy          Copy last response to clipboard\n"
            "  /run <cmd>     Run shell command inline\n"
            "  /! <cmd>       Shorthand for /run\n"
            "  /git [sub]     Git commands (status, log, diff, branch)\n"
            "  /diff [args]   Show git diff\n"
            "  /include <f>   Include file in next message\n"
            "  /cat <file>    Display file contents\n"
            "  /stream [on|off]  Toggle streaming\n"
            "  /environment   Amplifier environment diagnostics\n"
            "  /info          Show session info\n"
            "  /quit          Exit\n"
            "\n"
            "Tmux-specific:\n"
            "  /shell         Open a tmux split pane\n"
            "  /move-to <p>   Move window to amp-<project> session\n"
            "  /amp help      Show amp CLI help\n"
        )

    def _cmd_clear(self) -> None:
        chat_view = self._active_chat_view()
        for child in list(chat_view.children):
            child.remove()
        self._search_messages.clear()

    def _cmd_new(self) -> None:
        if self.session_manager:
            cid = self._conversation.conversation_id
            handle = self.session_manager.get_handle(cid)
            if handle:
                self.session_manager.remove_handle(cid)
        self._conversation = ConversationState()
        self._session_title = ""
        self._cmd_clear()
        self._show_welcome()
        self._update_status("Ready")

    def _cmd_quit(self) -> None:
        self.exit()

    def _cmd_info(self) -> None:
        lines = ["Session Info\n"]
        if self.session_manager and self.session_manager.session_id:
            lines.append(f"  Session ID: {self.session_manager.session_id}")
        if self.session_manager and self.session_manager.model_name:
            lines.append(f"  Model:      {self.session_manager.model_name}")
        lines.append(
            f"  Messages:   {self._user_message_count} user, "
            f"{self._assistant_message_count} assistant"
        )
        lines.append(f"  Title:      {self._session_title or '(none)'}")
        if os.environ.get("TMUX"):
            lines.append("  Tmux:       yes")
        self._add_system_message("\n".join(lines))

    def _cmd_model(self, text: str) -> None:
        parts = text.strip().split(None, 1)
        if len(parts) < 2:
            model = (
                self.session_manager.model_name if self.session_manager else ""
            ) or "unknown"
            self._add_system_message(f"Current model: {model}\nUsage: /model <name>")
            return
        new_model = parts[1].strip()
        if self.session_manager and self.session_manager.switch_model(new_model):
            self._add_system_message(f"Switched to model: {new_model}")
            self._update_status("Ready")
        else:
            self._add_system_message(f"Failed to switch to model: {new_model}")

    def _cmd_stream(self, args: str) -> None:
        if not self._prefs:
            self._add_system_message("Preferences not loaded")
            return
        arg = args.strip().lower()
        if arg == "off":
            self._prefs.display.streaming_enabled = False
            self._add_system_message("Streaming: OFF")
        elif arg == "on":
            self._prefs.display.streaming_enabled = True
            self._add_system_message("Streaming: ON")
        else:
            state = "ON" if self._prefs.display.streaming_enabled else "OFF"
            self._add_system_message(f"Streaming: {state}\nUsage: /stream on|off")

    async def _cmd_resume(self, args: str) -> None:
        sid = args.strip()
        if not sid:
            sid = "__most_recent__"
        if not self._amplifier_ready:
            self._add_system_message("Amplifier not ready yet.")
            return
        await self._resume_session_worker(sid)

    def _cmd_sessions_list(self, args: str) -> None:
        if not self.session_manager:
            self._add_system_message("No session manager available.")
            return
        sessions = SessionManager.list_all_sessions(limit=20)
        if not sessions:
            self._add_system_message("No sessions found.")
            return
        lines = ["Recent sessions:\n"]
        for s in sessions[:20]:
            sid = s.get("session_id", "???")[:12]
            proj = s.get("project", "")
            date = s.get("date_str", "")
            name = s.get("name", "")
            display = name or proj or "unnamed"
            lines.append(f"  {sid}  {date:10s}  {display}")
        lines.append("\nUse /resume <id> to resume a session.")
        self._add_system_message("\n".join(lines))

    def _cmd_environment(self) -> None:
        try:
            from .environment import check_environment, format_status

            ws = self._prefs.environment.workspace if self._prefs else None
            env_status = check_environment(ws or "")
            self._add_system_message(format_status(env_status))
        except Exception as exc:
            self._add_system_message(f"Environment check failed: {exc}")

    def _cmd_copy_last(self) -> None:
        if not self._last_assistant_text:
            self._add_system_message("No assistant response to copy.")
            return
        try:
            from .core._utils import _copy_to_clipboard

            _copy_to_clipboard(self._last_assistant_text)
            self._add_system_message("Copied last response to clipboard.")
        except Exception as exc:
            self._add_system_message(f"Copy failed: {exc}")

    def _cmd_tokens_display(self) -> None:
        if not self.session_manager:
            self._add_system_message("No active session.")
            return
        inp = self.session_manager.total_input_tokens
        out = self.session_manager.total_output_tokens
        model = self.session_manager.model_name or "unknown"
        self._add_system_message(
            f"Token usage:\n"
            f"  Model:   {model}\n"
            f"  Input:   {self._format_token_count(inp)}\n"
            f"  Output:  {self._format_token_count(out)}\n"
            f"  Total:   {self._format_token_count(inp + out)}"
        )

    def _cmd_amp(self, args: str) -> None:
        sub = args.strip().lower()
        if sub == "help":
            self._cmd_tmux_amp_help()
        else:
            self._add_system_message("Usage: /amp help")

    # ------------------------------------------------------------------
    # Actions (keyboard bindings)
    # ------------------------------------------------------------------

    def action_clear_chat(self) -> None:
        self._cmd_clear()

    def action_copy_response(self) -> None:
        self._cmd_copy_last()

    def action_cancel_streaming(self) -> None:
        conv = self._conversation
        if not conv.is_processing:
            return
        conv.streaming_cancelled = True
        if self._stream_widget and conv.stream_accumulated_text:
            self._finalize_streaming_block(
                self._stream_block_type or "text",
                conv.stream_accumulated_text,
            )
        self.workers.cancel_group(self, "send-message")
        self._add_system_message("Generation cancelled.")
        self._finish_processing()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_tmux_app(
    resume_session_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Run the tmux-mode Amplifier TUI."""
    app = TmuxApp(
        resume_session_id=resume_session_id,
        initial_prompt=initial_prompt,
    )
    app.run()
