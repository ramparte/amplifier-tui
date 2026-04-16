"""Session Cockpit -- a focused single-session Amplifier TUI.

Designed for tmux panes. Single session, block-based rendering,
inspector panel (Phase 3), and steering support.

Features:
  - Single-session, no tabs, no session sidebar
  - Every stream event wrapped in a ChatBlock widget
  - Auto-resume via @amp_session_id tmux pane variable
  - BEL on turn completion for tmux monitor-activity
  - /shell command for quick tmux split
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widgets import Collapsible, Markdown, Static, TextArea
from textual import work

from .commands.cockpit_cmds import (
    CockpitCommandsMixin,
    _send_bel,
    _tmux_get_pane_var,
    _tmux_set_pane_var,
)
from .core.app_base import SharedAppBase
from .core.conversation import ConversationState
from .core.commands.content_cmds import ContentCommandsMixin
from .core.commands.file_cmds import FileCommandsMixin
from .core.commands.git_cmds import GitCommandsMixin
from .core.commands.persistence_cmds import PersistenceCommandsMixin
from .core.commands.shell_cmds import ShellCommandsMixin
from .core.commands.token_cmds import TokenCommandsMixin
from .core.session_manager import SessionManager
from .models.block_model import BlockInfo, BlockRegistry, BlockType, SteerQueue
from .widgets.chat_block import BlockSelected, ChatBlock
from .widgets.chat_input import ChatInput
from .widgets.inspector_panel import (
    InspectorPanel,
    InspectorSteerRequest,
    InspectorAskRequest,
)
from .widgets.indicators import (
    ErrorMessage,
    ProcessingIndicator,
    SystemMessage,
)
from .widgets.messages import AssistantMessage, UserMessage

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# File-based diagnostic logging
# ---------------------------------------------------------------------------
# Writes to /tmp/cockpit.log so real-terminal failures can be diagnosed
# even when the TUI is running (can't see stdout).

import tempfile

_cockpit_log = logging.getLogger("amplifier_tui.cockpit")
_cockpit_log.setLevel(logging.DEBUG)

_file_handler_added = False


def _ensure_file_logging() -> None:
    """Add file handler to cockpit logger on first call (lazy init)."""
    global _file_handler_added
    if _file_handler_added:
        return
    log_path = os.path.join(tempfile.gettempdir(), "cockpit.log")
    handler = logging.FileHandler(log_path, mode="a")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _cockpit_log.addHandler(handler)
    _file_handler_added = True


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_COCKPIT_CSS = """\
Screen {
    background: $background;
}

#cockpit-chat-view {
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

#cockpit-status-bar {
    dock: bottom;
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 1;
}

.chat-block {
    height: auto;
    margin: 0 0;
}

.chat-block:hover {
    background: $surface;
}

.chat-block.selected {
    background: $boost;
    border-left: thick $accent;
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

#cockpit-main {
    width: 1fr;
    height: 1fr;
}

#cockpit-chat-area {
    width: 1fr;
    height: 1fr;
}

#inspector-panel {
    width: 40;
    display: none;
}

#inspector-panel.visible {
    display: block;
}
"""


# ---------------------------------------------------------------------------
# CockpitApp
# ---------------------------------------------------------------------------


class CockpitApp(
    CockpitCommandsMixin,
    PersistenceCommandsMixin,
    ShellCommandsMixin,
    ContentCommandsMixin,
    FileCommandsMixin,
    GitCommandsMixin,
    TokenCommandsMixin,
    SharedAppBase,
    App,
):
    """Single-session Amplifier TUI optimised for tmux panes."""

    CSS = _COCKPIT_CSS
    TITLE = "Amplifier Cockpit"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
        Binding("ctrl+y", "copy_response", "Copy", show=False),
        Binding("escape", "cancel_streaming", "Cancel", show=False),
        # NOTE: ctrl+i = Tab in most terminals; f2 is reliable in tmux.
        Binding("f2", "toggle_inspector", "Inspector", show=True),
    ]

    def __init__(
        self,
        resume_session_id: str | None = None,
        initial_prompt: str | None = None,
        **kwargs,
    ) -> None:
        _ensure_file_logging()
        super().__init__(**kwargs)

        self.resume_session_id = resume_session_id
        self.initial_prompt = initial_prompt

        # Single conversation
        self._conversation = ConversationState()

        # Block tracking
        self._block_registry = BlockRegistry()
        self._steer_queue = SteerQueue()
        self._turn_index: int = 0

        # Side session (lazy, for /ask)
        self._side_session_id: str | None = None
        self._side_conversation = ConversationState()

        # Streaming widget state
        self._stream_widget: Static | None = None
        self._stream_container = None
        self._stream_block_type: str = ""
        self._processing_label: str = ""
        self._processing_indicator: ProcessingIndicator | None = None
        self._current_streaming_block_id: int | None = None

        # Session state
        self._session_title: str = ""

        _cockpit_log.info(
            "CockpitApp.__init__ resume=%s initial_prompt=%s",
            resume_session_id,
            bool(initial_prompt),
        )

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="cockpit-main"):
            with Vertical(id="cockpit-chat-area"):
                yield ScrollableContainer(id="cockpit-chat-view")
                yield ChatInput(
                    "",
                    id="chat-input",
                    soft_wrap=True,
                    show_line_numbers=False,
                    tab_behavior="focus",
                    compact=True,
                )
            yield InspectorPanel(
                block_registry=self._block_registry,
                id="inspector-panel",
            )
        yield Static("No session | Ready", id="cockpit-status-bar")

    # ------------------------------------------------------------------
    # Mount
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        self._show_welcome()
        self.query_one("#chat-input", ChatInput).focus()
        # NOTE: inspector panel starts hidden via CSS (#inspector-panel { display: none })
        # Do NOT set panel.display = False here — that would fight the CSS cascade.

        # Check for auto-resume via tmux pane variable
        if not self.resume_session_id:
            pane_session = _tmux_get_pane_var("@amp_session_id")
            if pane_session:
                self.resume_session_id = pane_session
                _cockpit_log.info(
                    "on_mount: auto-resume session from tmux pane: %s", pane_session
                )

        _cockpit_log.info("on_mount: starting _init_amplifier worker")
        # Heavy init in background
        self._init_amplifier()

    async def on_unmount(self) -> None:
        """Clean up sessions and resources on app exit."""
        if self.session_manager:
            cid = self._conversation.conversation_id
            try:
                await self.session_manager.end_session(cid)
            except Exception:
                _cockpit_log.debug(
                    "Failed to end main session on unmount", exc_info=True
                )
            # Clean up side session
            if self._side_session_id:
                try:
                    await self.session_manager.end_session(self._side_session_id)
                except Exception:
                    _cockpit_log.debug(
                        "Failed to end side session on unmount", exc_info=True
                    )

    @work(thread=True, group="init")
    def _init_amplifier(self) -> None:
        """Import Amplifier in background so UI appears instantly."""
        _cockpit_log.info("_init_amplifier: start")
        self.call_from_thread(self._update_status, "Loading Amplifier...")

        try:
            self.session_manager = SessionManager()
            _cockpit_log.info("_init_amplifier: SessionManager created OK")
        except Exception:
            _cockpit_log.exception("_init_amplifier: SessionManager creation FAILED")
            self._amplifier_available = False
            self.call_from_thread(
                self._add_system_message,
                "Amplifier session manager failed to initialise.\n"
                "Use --doctor for diagnostics.",
            )
            self.call_from_thread(self._update_status, "Not connected")
            return

        # Proactive readiness check -- catches the common "clean machine" case
        # where libraries or bundles aren't set up yet, BEFORE the user sends a
        # message and gets a raw exception.
        from .environment import check_environment, format_status

        env_status = check_environment("")  # Cockpit doesn't have workspace preferences
        _cockpit_log.info("_init_amplifier: env_status.ready=%s", env_status.ready)
        if not env_status.ready:
            self._amplifier_available = False
            diag = format_status(env_status)
            _cockpit_log.warning("_init_amplifier: environment not ready:\n%s", diag)
            self.call_from_thread(
                self._add_system_message,
                diag
                + "\n\nFix the issues above, then restart or use --doctor to re-check.",
            )
            self.call_from_thread(self._update_status, "Setup needed")
            return

        # Pre-prepare the bundle ONCE at startup.  This is the expensive
        # operation (triggers ``uv pip install -e``).  Doing it here means
        # subsequent start_new_session / resume_session calls are fast (~1s
        # instead of ~5-10s).  Same pattern as amplifier-app-cli.
        import asyncio as _asyncio

        self.call_from_thread(self._update_status, "Preparing bundle...")
        try:
            _asyncio.run(self.session_manager.prepare_bundle())
            _cockpit_log.info("_init_amplifier: bundle prepared OK")
        except Exception:
            _cockpit_log.warning(
                "_init_amplifier: bundle prepare failed", exc_info=True
            )
            # Non-fatal: first session creation will retry prepare_bundle()

        # Verify providers are available.  The most common failure mode is
        # provider injection silently failing, which produces the cryptic
        # "No providers available" error only after the user sends a message.
        # Surface it here so the user sees it immediately on startup.
        has_providers = self.session_manager.has_providers()
        if not has_providers:
            _cockpit_log.warning("_init_amplifier: NO providers in mount plan")
            self.call_from_thread(
                self._add_system_message,
                "Warning: No LLM providers available.\n"
                "Check that your bundle is configured correctly, or run:\n"
                "  amplifier provider install\n"
                "See /tmp/cockpit.log for details.",
            )
            self.call_from_thread(self._update_status, "No providers")

        self._amplifier_ready = True
        _cockpit_log.info(
            "_init_amplifier: ready=True, resume_session_id=%s", self.resume_session_id
        )

        if self.resume_session_id:
            self._resume_session(self.resume_session_id)
        elif self.initial_prompt:
            prompt = self.initial_prompt
            self.initial_prompt = None
            cid = self._conversation.conversation_id
            self.call_from_thread(self._clear_welcome)
            self.call_from_thread(self._add_user_message, prompt)
            self.call_from_thread(
                self._start_processing, "Starting session", conversation_id=cid
            )
            self._do_send_message(prompt)
        else:
            self.call_from_thread(self._update_status, "Ready")

    # ------------------------------------------------------------------
    # Multi-conversation interface (single conversation only)
    # ------------------------------------------------------------------

    def _all_conversations(self) -> list:
        return [self._conversation]

    def _active_chat_view(self) -> ScrollableContainer:
        return self.query_one("#cockpit-chat-view", ScrollableContainer)

    # ------------------------------------------------------------------
    # Abstract display methods
    # ------------------------------------------------------------------

    def _add_system_message(
        self, text: str, *, conversation_id: str = "", **kwargs
    ) -> None:
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.SYSTEM, self._turn_index, summary=text[:60], content=text
        )
        block = ChatBlock(
            info.block_id,
            BlockType.SYSTEM,
            self._turn_index,
            SystemMessage(text),
            id=f"block-{info.block_id}",
        )
        chat_view.mount(block)
        block.scroll_visible()

    def _add_user_message(
        self, text: str, *, conversation_id: str = "", **kwargs
    ) -> None:
        self._turn_index += 1
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.USER, self._turn_index, summary=text[:60], content=text
        )
        block = ChatBlock(
            info.block_id,
            BlockType.USER,
            self._turn_index,
            UserMessage(text),
            id=f"block-{info.block_id}",
        )
        chat_view.mount(block)
        block.scroll_visible()

        # Notify inspector if in live mode
        self._notify_inspector_live_mode()

    def _add_assistant_message(
        self, text: str, *, conversation_id: str = "", **kwargs
    ) -> None:
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.ASSISTANT, self._turn_index, summary=text[:60], content=text
        )
        block = ChatBlock(
            info.block_id,
            BlockType.ASSISTANT,
            self._turn_index,
            AssistantMessage(text),
            id=f"block-{info.block_id}",
        )
        chat_view.mount(block)
        block.scroll_visible()

    def _show_error(self, text: str, *, conversation_id: str = "") -> None:
        chat_view = self._active_chat_view()
        chat_view.mount(ErrorMessage(text, classes="error-message"))

    def _display_transcript(self, transcript_path: object) -> None:
        """Render a session transcript in the chat view on resume."""
        from pathlib import Path as _Path

        from .transcript_loader import load_transcript, parse_message_blocks

        path = _Path(str(transcript_path))
        if not path.exists():
            return

        chat_view = self._active_chat_view()
        # Clear existing content (welcome screen, etc.)
        for child in list(chat_view.children):
            child.remove()

        for msg in load_transcript(path):
            for block in parse_message_blocks(msg):
                if block.kind == "user":
                    self._add_user_message(block.content)
                elif block.kind == "text":
                    self._add_assistant_message(block.content)

    def _update_status(self, text: str, *, conversation_id: str = "") -> None:
        try:
            status_bar = self.query_one("#cockpit-status-bar", Static)
            session_id = ""
            if self.session_manager:
                sid = self.session_manager.session_id
                if sid:
                    session_id = sid[:12]
            model = ""
            if self.session_manager:
                model = self.session_manager.model_name or ""
            parts = [p for p in [session_id, model, text] if p]
            status_bar.update(" | ".join(parts))
        except NoMatches:
            pass

    def _start_processing(
        self, label: str = "Thinking", *, conversation_id: str = ""
    ) -> None:
        self._conversation.is_processing = True
        self._processing_label = label
        self._ensure_processing_indicator(label)

    def _finish_processing(self, *, conversation_id: str = "") -> None:
        self._conversation.is_processing = False
        self._conversation.tool_count_this_turn = 0
        self._conversation.got_stream_content = False
        self._conversation.streaming_cancelled = False
        self._remove_processing_indicator()
        self._update_status("Ready")
        if os.environ.get("TMUX"):
            _send_bel()

        # Store session ID in tmux pane variable
        if self.session_manager and self.session_manager.session_id:
            _tmux_set_pane_var("@amp_session_id", self.session_manager.session_id)

    # ------------------------------------------------------------------
    # Streaming display methods (called from BACKGROUND THREAD)
    # ------------------------------------------------------------------

    def _on_stream_block_start(
        self, conversation_id: str, block_type: str, block_index: int = 0
    ) -> None:
        self.call_from_thread(self._begin_streaming_block, block_type, block_index)

    def _on_stream_block_delta(
        self,
        conversation_id: str,
        block_type: str,
        accumulated_text: str,
        block_index: int = 0,
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
        block_index: int = 0,
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

    def _on_stream_tool_end(
        self, conversation_id: str, name: str, tool_input: dict, result: str
    ) -> None:
        self._processing_label = "Thinking"
        self.call_from_thread(self._add_tool_use, name, tool_input, result)
        self.call_from_thread(self._ensure_processing_indicator, "Thinking")
        # Check steer queue at pause point (between tool calls)
        self.call_from_thread(self._check_steer_queue)

    def _on_stream_usage_update(self, conversation_id: str) -> None:
        self.call_from_thread(self._update_status, "Thinking...")

    # ------------------------------------------------------------------
    # Streaming display helpers (main thread)
    # ------------------------------------------------------------------

    def _begin_streaming_block(self, block_type: str, block_index: int = 0) -> None:
        """Create a new streaming widget for incoming content."""
        self._remove_processing_indicator()
        chat_view = self._active_chat_view()

        bt = (
            BlockType.THINKING
            if block_type in ("thinking", "reasoning")
            else BlockType.ASSISTANT
        )
        info = self._block_registry.add(
            bt, self._turn_index, summary=f"[streaming {block_type}]", content=""
        )

        # Track current streaming block for live mode
        self._current_streaming_block_id = info.block_id

        if block_type in ("thinking", "reasoning"):
            widget = Static("", classes="thinking-block thinking-text")
            container = Collapsible(widget, title="Thinking...", collapsed=False)
            cb = ChatBlock(
                info.block_id,
                bt,
                self._turn_index,
                container,
                id=f"block-{info.block_id}",
            )
            chat_view.mount(cb)
            self._stream_widget = widget
            self._stream_container = container
        else:
            widget = Markdown("", classes="assistant-message")
            cb = ChatBlock(
                info.block_id,
                bt,
                self._turn_index,
                widget,
                id=f"block-{info.block_id}",
            )
            chat_view.mount(cb)
            self._stream_widget = widget

        self._stream_block_type = block_type
        cb.scroll_visible()

        # Notify inspector if in live mode
        self._notify_inspector_live_mode()

    def _update_streaming_content(self, block_type: str, accumulated_text: str) -> None:
        """Update the active streaming widget with accumulated text."""
        if self._stream_widget is None:
            return
        if isinstance(self._stream_widget, Markdown):
            self._stream_widget.update(accumulated_text)
        else:
            self._stream_widget.update(accumulated_text)

    def _finalize_streaming_block(self, block_type: str, final_text: str) -> None:
        """Replace the streaming widget with final content."""
        if self._stream_widget is None:
            return
        self._stream_widget.update(final_text)
        # Update the block content and summary in the registry
        if self._current_streaming_block_id is not None:
            block = self._block_registry.get_by_id(self._current_streaming_block_id)
            if block:
                block.content = final_text
                block.summary = final_text[:60]
        self._stream_widget = None
        self._stream_container = None
        self._stream_block_type = ""
        self._current_streaming_block_id = None

    def _add_thinking_block(self, text: str) -> None:
        """Add a completed thinking block (fallback, no streaming widget)."""
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.THINKING, self._turn_index, summary=text[:60], content=text
        )
        container = Collapsible(
            Static(text, classes="thinking-block thinking-text"),
            title="Thinking",
            collapsed=True,
        )
        cb = ChatBlock(info.block_id, BlockType.THINKING, self._turn_index, container)
        chat_view.mount(cb)

    def _add_tool_use(self, name: str, tool_input: dict, result: str) -> None:
        """Add a tool call block to the chat view."""
        chat_view = self._active_chat_view()
        # Compact display: tool name and result in a collapsible
        import json

        input_str = (
            json.dumps(tool_input, indent=2)
            if isinstance(tool_input, dict)
            else str(tool_input)
        )
        content = f"Input:\n{input_str}\n\nResult:\n{result}"
        info = self._block_registry.add(
            BlockType.TOOL_CALL, self._turn_index, summary=f"{name}", content=content
        )
        container = Collapsible(
            Static(content, classes="tool-call"),
            title=f"Tool: {name}",
            collapsed=True,
        )
        cb = ChatBlock(info.block_id, BlockType.TOOL_CALL, self._turn_index, container)
        chat_view.mount(cb)

    # ------------------------------------------------------------------
    # Processing indicator
    # ------------------------------------------------------------------

    def _ensure_processing_indicator(self, label: str = "Thinking") -> None:
        if self._processing_indicator is not None:
            self._processing_indicator.update(f"  {label}...")
            return
        indicator = ProcessingIndicator(f"  {label}...", classes="processing-indicator")
        self._processing_indicator = indicator
        try:
            chat_view = self._active_chat_view()
            chat_view.mount(indicator)
            indicator.scroll_visible()
        except NoMatches:
            self._processing_indicator = None

    def _remove_processing_indicator(self) -> None:
        if self._processing_indicator is not None:
            self._processing_indicator.remove()
            self._processing_indicator = None

    # ------------------------------------------------------------------
    # Welcome screen
    # ------------------------------------------------------------------

    def _show_welcome(self, text: str = "") -> None:
        if not text:
            text = (
                "Amplifier Cockpit\n\n"
                "Single-session mode. Type a message to start.\n"
                "Use /help for available commands."
            )
        try:
            chat_view = self._active_chat_view()
            chat_view.mount(Static(text, classes="welcome-screen", id="welcome"))
        except NoMatches:
            pass

    def _clear_welcome(self) -> None:
        try:
            welcome = self.query_one("#welcome")
            welcome.remove()
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    def _handle_input(self, text: str) -> None:
        """Process input from the chat input widget."""
        text = text.strip()
        if not text:
            return

        _cockpit_log.info(
            "_handle_input: text=%r ready=%s sm=%s",
            text[:40],
            self._amplifier_ready,
            self.session_manager is not None,
        )

        target = self._get_input_target()

        if target == "inspector":
            # Route to inspector command dispatch
            try:
                panel = self.query_one("#inspector-panel", InspectorPanel)
                panel.handle_input(text)
            except NoMatches:
                pass
            return

        # Bare exit/quit (without slash prefix) -- just exit the app.
        if text.strip().lower() in ("exit", "quit"):
            self.exit()
            return

        # Main session: slash command or regular message
        if text.startswith("/"):
            if self._dispatch_slash_command(text):
                return  # Cockpit-local command handled

        # Gate: don't send messages until Amplifier has finished initialising.
        # This prevents race conditions where the user types before the init
        # worker has created the SessionManager and set _amplifier_ready.
        if not self._amplifier_ready:
            _cockpit_log.warning("_handle_input: not ready yet, dropping message")
            self._add_system_message(
                "Amplifier is still loading… please wait a moment and try again."
            )
            return

        self._clear_welcome()
        self._add_user_message(text)
        cid = self._conversation.conversation_id
        has_session = bool(
            self.session_manager and self.session_manager.get_handle(cid)
        )
        label = "Thinking" if has_session else "Starting session"
        self._start_processing(label, conversation_id=cid)
        self._do_send_message(text)

    def _dispatch_slash_command(self, text: str) -> bool:
        """Route slash commands to the appropriate handler.

        Returns ``True`` if the command was handled locally (cockpit UI
        commands like ``/help``, ``/shell``, ``/clear``).  Returns ``False``
        for unrecognised commands so that the caller can pass them through
        to the Amplifier session (e.g. ``/status``, ``/skills``, ``/mode``).
        """
        parts = text.split(None, 1)
        cmd = parts[0].lower()

        handlers = {
            "/help": lambda: self._cmd_cockpit_help(),
            "/shell": lambda: self._cmd_cockpit_shell(),
            "/clear": lambda: self._cmd_clear_with_context(),
            "/status": lambda: self._cmd_status(),
            "/new": lambda: self._cmd_new_session(),
            "/quit": lambda: self.exit(),
            "/q": lambda: self.exit(),
            "/exit": lambda: self.exit(),
        }

        handler = handlers.get(cmd)
        if handler:
            handler()
            return True

        # Unrecognised -- let the caller send it to the Amplifier session.
        return False

    @work(thread=True, group="send-message")
    def _do_send_message(self, message: str) -> None:
        """Send a message to Amplifier in a background thread.

        Like ``_resume_session``, this MUST be a sync function.  Textual's
        ``@work(thread=True)`` runs async functions via ``asyncio.run()``
        inside the thread, creating an isolated event-loop whose
        ``call_from_thread`` posts are silently dropped by the Textual main
        loop (observed in Textual 8.0).  Keeping this sync and using
        ``asyncio.run()`` explicitly preserves reliable ``call_from_thread``
        delivery for status updates, error messages, and the response
        fallback path.
        """
        import asyncio as _asyncio

        cid = self._conversation.conversation_id
        conv = self._conversation

        _cockpit_log.info(
            "_do_send_message: start msg=%r cid=%s sm=%s",
            message[:40],
            cid,
            self.session_manager is not None,
        )

        if self.session_manager is None:
            _cockpit_log.error(
                "_do_send_message: session_manager is None -- init not complete?"
            )
            self.call_from_thread(self._add_system_message, "No active session")
            return

        try:
            # Auto-create session on first message
            handle = self.session_manager.get_handle(cid)
            _cockpit_log.info(
                "_do_send_message: existing handle=%s", handle is not None
            )
            if not handle or not handle.session:
                self.call_from_thread(self._update_status, "Starting session...")
                _cockpit_log.info(
                    "_do_send_message: calling start_new_session cwd=%s", None
                )
                try:
                    _asyncio.run(
                        self.session_manager.start_new_session(
                            conversation_id=cid,
                        )
                    )
                    _cockpit_log.info("_do_send_message: start_new_session OK")
                except Exception as session_err:
                    _cockpit_log.exception(
                        "_do_send_message: start_new_session FAILED: %s", session_err
                    )
                    self.call_from_thread(
                        self._show_error,
                        f"Could not start session: {session_err}",
                    )
                    return

            self._wire_streaming_callbacks(cid, conv)
            self.call_from_thread(self._update_status, "Thinking...")

            _cockpit_log.info("_do_send_message: calling send_message")
            response = _asyncio.run(
                self.session_manager.send_message(message, conversation_id=cid)
            )
            _cockpit_log.info(
                "_do_send_message: send_message returned len=%d response=%r",
                len(response or ""),
                (response or "")[:200],
            )

            if conv.streaming_cancelled:
                return

            # Fallback: if no streaming hooks fired, show the full response
            if not conv.got_stream_content and response:
                self.call_from_thread(self._add_assistant_message, response)

        except Exception as e:
            _cockpit_log.exception("_do_send_message: EXCEPTION: %s", e)
            if conv.streaming_cancelled:
                return
            self.call_from_thread(self._show_error, str(e))
        finally:
            from textual.worker import get_current_worker

            worker = get_current_worker()
            if worker and not worker.is_cancelled:
                self.call_from_thread(self._finish_processing, conversation_id=cid)

    @work(thread=True, group="resume")
    def _resume_session(self, session_id: str) -> None:
        """Resume a session in a background thread.

        This MUST be a sync function (not async) even though it calls async
        bridge code.  Textual's ``@work(thread=True)`` runs async functions
        via ``asyncio.run()`` inside the thread, which creates an isolated
        event-loop.  ``call_from_thread`` posts from that nested loop are
        silently dropped by the Textual main loop (observed in Textual 8.0).
        By keeping this sync and using ``asyncio.run()`` explicitly for just
        the bridge call, all ``call_from_thread`` calls happen at the plain-
        thread level where Textual reliably processes them.
        """
        import asyncio as _asyncio

        cid = self._conversation.conversation_id
        _cockpit_log.info("_resume_session: session_id=%s cid=%s", session_id, cid)
        self.call_from_thread(self._update_status, "Resuming session...")

        if self.session_manager is None:
            self.call_from_thread(self._add_system_message, "No session manager")
            return

        try:
            if session_id == "__most_recent__":
                sessions = SessionManager.list_all_sessions(limit=1)
                if not sessions:
                    self.call_from_thread(
                        self._add_system_message, "No sessions found to resume."
                    )
                    self.call_from_thread(self._update_status, "Ready")
                    return
                session_id = sessions[0]["session_id"]

            self.call_from_thread(self._update_status, "Loading bundle...")

            # Display the transcript history in the chat view BEFORE resuming
            # so the user sees prior conversation immediately.
            from pathlib import Path as _Path

            transcript_path = SessionManager.get_session_transcript_path(
                session_id, cwd=_Path.cwd()
            )
            if transcript_path and transcript_path.exists():
                self.call_from_thread(self._display_transcript, transcript_path)

            # Run the async bridge call in an explicit event loop.
            # This keeps call_from_thread at the sync-thread level.
            _asyncio.run(
                self.session_manager.resume_session(
                    session_id=session_id,
                    conversation_id=cid,
                )
            )
            _cockpit_log.info("_resume_session: resumed OK session_id=%s", session_id)
            self.call_from_thread(self._update_status, "Ready")
            self.call_from_thread(self._clear_welcome)
            self.call_from_thread(
                self._add_system_message, f"Resumed session {session_id[:12]}..."
            )
        except Exception as e:
            _cockpit_log.exception("_resume_session: FAILED: %s", e)
            # Resume failed -- clear any partial handle so next message creates fresh session
            try:
                self.session_manager.remove_handle(cid)
            except Exception:
                pass
            self.call_from_thread(self._show_error, f"Resume failed: {e}")
            self.call_from_thread(self._update_status, "Ready")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def on_chat_input_submitted(self, event) -> None:
        """Handle Enter in the chat input."""
        # ChatInput.Submitted inherits from TextArea.Changed -- text is on the widget
        text = event.text_area.text.strip()
        _cockpit_log.info("on_chat_input_submitted: text=%r", text[:60])
        event.text_area.clear()
        if text:
            self._handle_input(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_clear_chat(self) -> None:
        """Clear the chat view (DOM only, does not clear session context).

        NOTE: ``_turn_index`` is NOT reset to zero.  Textual keeps a global
        registry of widget IDs and even after ``child.remove()`` the old IDs
        remain reserved until the next compose cycle.  Reusing them causes
        ``DuplicateIds``.  Instead we keep the counter monotonically
        increasing so new ChatBlock IDs (``block-{turn}``) stay unique.
        """
        try:
            chat_view = self._active_chat_view()
            for child in list(chat_view.children):
                child.remove()
        except NoMatches:
            pass
        self._block_registry.clear()

    def _cmd_clear_with_context(self) -> None:
        """Clear the chat view AND the session's context memory."""
        self.action_clear_chat()
        # Schedule the async context clear (context module methods are async)
        self.run_worker(self._async_clear_context(), exclusive=False)
        self._add_system_message("Chat and session context cleared.")

    async def _async_clear_context(self) -> None:
        """Actually clear the session's context memory (async)."""
        cid = self._conversation.conversation_id
        if self.session_manager:
            handle = self.session_manager.get_handle(cid)
            if handle and handle.session:
                try:
                    ctx = handle.session.coordinator.get("context")
                    if ctx and hasattr(ctx, "clear"):
                        await ctx.clear()
                        _cockpit_log.info("/clear: session context cleared")
                except Exception:  # noqa: BLE001
                    _cockpit_log.debug("Could not clear session context", exc_info=True)

    def _get_active_session(self) -> object | None:
        """Return the active AmplifierSession, or None."""
        cid = self._conversation.conversation_id
        if self.session_manager:
            handle = self.session_manager.get_handle(cid)
            if handle and handle.session:
                return handle.session
        return None

    def _cmd_status(self) -> None:
        """Show session status information."""
        lines = ["Session Status:"]
        cid = self._conversation.conversation_id
        if self.session_manager:
            handle = self.session_manager.get_handle(cid)
            if handle:
                lines.append(f"  Session ID: {handle.session_id or 'none'}")
                if handle.model_name:
                    lines.append(f"  Model: {handle.model_name}")
                lines.append(f"  Messages: {self._turn_index}")
                lines.append(f"  Blocks: {len(self._block_registry)}")
                # Show provider list
                try:
                    providers = self.session_manager.get_provider_models()
                    if providers:
                        prov_list = ", ".join(
                            f"{model} ({name})" for model, name in providers
                        )
                        lines.append(f"  Providers: {prov_list}")
                except Exception:  # noqa: BLE001
                    pass
            else:
                lines.append("  No active session")
        else:
            lines.append("  Amplifier not initialized")
        self._add_system_message("\n".join(lines))

    def _cmd_new_session(self) -> None:
        """End the current session and start a fresh one."""
        import asyncio as _asyncio

        cid = self._conversation.conversation_id
        if self.session_manager:
            handle = self.session_manager.get_handle(cid)
            if handle and handle.session:
                try:
                    _asyncio.run(self.session_manager.end_session(cid))
                except Exception:  # noqa: BLE001
                    _cockpit_log.debug("Error ending session", exc_info=True)

        # Clear DOM and create fresh conversation state
        self.action_clear_chat()
        self._conversation = ConversationState()
        self._add_system_message("New session started. Send a message to begin.")

    def action_cancel_streaming(self) -> None:
        """Cancel current streaming."""
        self._conversation.streaming_cancelled = True

    # ------------------------------------------------------------------
    # Inspector toggle methods
    # ------------------------------------------------------------------

    def _inspector_is_visible(self) -> bool:
        """Return True if the inspector panel is currently shown."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            return panel.has_class("visible")
        except NoMatches:
            return False

    def _toggle_inspector(self) -> None:
        """Toggle the inspector panel visibility.

        Uses ONLY the CSS class 'visible' to drive show/hide so it doesn't
        conflict with the CSS cascade (#inspector-panel { display: none }).
        Setting panel.display directly would override the stylesheet and cause
        both states to fight each other.
        """
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            currently_visible = panel.has_class("visible")
            _cockpit_log.info(
                "_toggle_inspector: currently_visible=%s", currently_visible
            )

            if currently_visible:
                # Hide: remove CSS class, return focus to chat input
                panel.remove_class("visible")
                try:
                    self.query_one("#chat-input", ChatInput).focus()
                except NoMatches:
                    pass
            else:
                # Show: add CSS class, set live mode, move focus into inspector
                panel.add_class("visible")
                panel.set_live_mode()
                try:
                    panel.query_one("#inspector-input", TextArea).focus()
                except NoMatches:
                    pass

            _cockpit_log.info(
                "_toggle_inspector: done, now_visible=%s", not currently_visible
            )
        except NoMatches:
            _cockpit_log.warning("_toggle_inspector: InspectorPanel not found")

    def action_toggle_inspector(self) -> None:
        """Textual action for F2 binding."""
        self._toggle_inspector()

    # ------------------------------------------------------------------
    # BlockSelected handler
    # ------------------------------------------------------------------

    def on_block_selected(self, event: BlockSelected) -> None:
        """Handle block click -- open inspector in pinned mode."""
        # Visual selection
        for cb in self.query(ChatBlock):
            cb.deselect()

        # Select the clicked block
        for cb in self.query(ChatBlock):
            if cb.block_id == event.block_id:
                cb.select()
                break

        # Open inspector in pinned mode (CSS class only, no direct display set)
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            panel.add_class("visible")
            panel.pin_to_block(event.block_id)
            _cockpit_log.info(
                "on_block_selected: pinned block %d, inspector now visible",
                event.block_id,
            )
        except NoMatches:
            pass

    def on_inspector_steer_request(self, event: InspectorSteerRequest) -> None:
        """Queue a steering message from the inspector."""
        self._steer_queue.enqueue(event.text)

    def _check_steer_queue(self) -> None:
        """Inject pending steer messages at natural pause points."""
        if self._steer_queue.is_empty:
            return
        cid = self._conversation.conversation_id
        handle = self.session_manager.get_handle(cid) if self.session_manager else None
        if not handle:
            return
        steer_text = self._steer_queue.dequeue()
        if not steer_text:
            return
        if not self._conversation.is_processing:
            # Session is idle: send as a regular user message
            self._add_user_message(steer_text)
            self._start_processing("Steering", conversation_id=cid)
            self._do_send_message(steer_text)
        else:
            # Session is mid-execution: queue for injection at next tool pause
            handle.inject_user_message(steer_text)
            self._add_system_message(f"[steer queued] {steer_text}")

    # ------------------------------------------------------------------
    # Side session methods for /ask command
    # ------------------------------------------------------------------

    def _build_ask_context(self, block: BlockInfo, question: str) -> str:
        """Build context for the side session from a pinned block."""
        context_parts = []
        context_parts.append(
            f"Block {block.block_id} ({block.block_type.name} from turn {block.turn_index})"
        )
        if block.content:
            context_parts.append(f"Content:\n{block.content}")
        elif block.summary:
            context_parts.append(f"Summary: {block.summary}")
        context_parts.append(f"\nUser question: {question}")
        return "\n".join(context_parts)

    def on_inspector_ask_request(self, event: InspectorAskRequest) -> None:
        """Handle /ask command from inspector - start side session."""
        if not event.block_info:
            # Show error in inspector
            return

        context = self._build_ask_context(event.block_info, event.question)
        self._do_ask(context)

    @work(exclusive=True)
    async def _do_ask(self, context: str) -> None:
        """Send ask context to side session and display response."""
        if not self.session_manager:
            return

        # Lazy create side session
        if not self._side_session_id:
            try:
                handle = await self.session_manager.start_new_session()
                self._side_session_id = handle.conversation_id
            except Exception as e:
                self.call_from_thread(
                    self._add_system_message, f"Failed to create side session: {e}"
                )
                return

        self.call_from_thread(self._update_status, "Side session thinking...")

        try:
            response = await self.session_manager.send_message(
                context, conversation_id=self._side_session_id
            )
            if response:
                self.call_from_thread(self._show_ask_response, response)
        except Exception as e:
            self.call_from_thread(self._add_system_message, f"Side session error: {e}")
        finally:
            self.call_from_thread(self._update_status, "Ready")

    def _show_ask_response(self, response: str) -> None:
        """Display /ask response in the inspector panel."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            panel.display_ask_response(response)
        except NoMatches:
            pass

    def _notify_inspector_live_mode(self) -> None:
        """Notify inspector panel to follow latest block if in live mode."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            # Use CSS class to check visibility, not panel.display
            if panel.has_class("visible"):
                panel.follow_latest()
        except NoMatches:
            pass

    def _get_input_target(self) -> str:
        """Determine where input should be routed: 'main' or 'inspector'.

        Uses CSS class to check visibility rather than panel.display to stay
        consistent with the CSS-only toggle approach.
        """
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            if panel.has_class("visible"):
                return "inspector"
        except NoMatches:
            pass
        return "main"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_cockpit(
    resume_session_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Run the Cockpit application."""
    _cockpit_log.info(
        "run_cockpit: resume=%s initial_prompt=%s",
        resume_session_id,
        bool(initial_prompt),
    )
    app = CockpitApp(
        resume_session_id=resume_session_id,
        initial_prompt=initial_prompt,
    )
    app.run()
