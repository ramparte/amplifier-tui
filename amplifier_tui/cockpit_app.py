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

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widgets import Collapsible, Markdown, Static
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
from .core.log import logger
from .core.session_manager import SessionManager
from .models.block_model import BlockRegistry, BlockType, SteerQueue
from .widgets.chat_block import BlockSelected, ChatBlock
from .widgets.chat_input import ChatInput
from .widgets.inspector_panel import InspectorPanel, InspectorSteerRequest, InspectorAskRequest
from .widgets.indicators import (
    ErrorMessage,
    ProcessingIndicator,
    SystemMessage,
)
from .widgets.messages import AssistantMessage, UserMessage

if TYPE_CHECKING:
    pass

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
        Binding("ctrl+i", "toggle_inspector", "Inspector", show=True),
    ]

    def __init__(
        self,
        resume_session_id: str | None = None,
        initial_prompt: str | None = None,
        **kwargs,
    ) -> None:
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

        # Check for auto-resume via tmux pane variable
        if not self.resume_session_id:
            pane_session = _tmux_get_pane_var("@amp_session_id")
            if pane_session:
                self.resume_session_id = pane_session

        # Heavy init in background
        self._init_amplifier()

    @work(thread=True, group="init")
    def _init_amplifier(self) -> None:
        """Import Amplifier in background so UI appears instantly."""
        self.call_from_thread(self._update_status, "Loading Amplifier...")

        try:
            self.session_manager = SessionManager()
        except Exception:
            logger.debug("Failed to initialize session manager", exc_info=True)
            self._amplifier_available = False
            self.call_from_thread(
                self._add_system_message,
                "Amplifier session manager failed to initialise.\n"
                "Use --doctor for diagnostics.",
            )
            self.call_from_thread(self._update_status, "Not connected")
            return

        self._amplifier_ready = True

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
            BlockType.SYSTEM, self._turn_index, summary=text[:60]
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
            BlockType.USER, self._turn_index, summary=text[:60]
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
            BlockType.ASSISTANT, self._turn_index, summary=text[:60]
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
            bt, self._turn_index, summary=f"[streaming {block_type}]"
        )
        
        # Track current streaming block for live mode
        self._current_streaming_block_id = info.block_id

        if block_type in ("thinking", "reasoning"):
            widget = Static("", classes="thinking-block thinking-text")
            container = Collapsible(widget, title="Thinking...", collapsed=False)
            cb = ChatBlock(
                info.block_id, bt, self._turn_index, container,
                id=f"block-{info.block_id}",
            )
            chat_view.mount(cb)
            self._stream_widget = widget
            self._stream_container = container
        else:
            widget = Markdown("", classes="assistant-message")
            cb = ChatBlock(
                info.block_id, bt, self._turn_index, widget,
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
        if isinstance(self._stream_widget, Markdown):
            self._stream_widget.update(final_text)
        else:
            self._stream_widget.update(final_text)

        # Update the block summary in the registry
        if self._block_registry.last:
            self._block_registry.last.summary = final_text[:60]

        self._stream_widget = None
        self._stream_container = None
        self._stream_block_type = ""

    def _add_thinking_block(self, text: str) -> None:
        """Add a completed thinking block (fallback, no streaming widget)."""
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.THINKING, self._turn_index, summary=text[:60]
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
        info = self._block_registry.add(
            BlockType.TOOL_CALL, self._turn_index, summary=f"{name}"
        )
        # Compact display: tool name and result in a collapsible
        import json

        input_str = (
            json.dumps(tool_input, indent=2)
            if isinstance(tool_input, dict)
            else str(tool_input)
        )
        content = f"Input:\n{input_str}\n\nResult:\n{result[:500]}"
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

        target = self._get_input_target()

        if target == "inspector":
            # Route to inspector command dispatch
            try:
                panel = self.query_one("#inspector-panel", InspectorPanel)
                panel.handle_input(text)
            except NoMatches:
                pass
            return

        # Main session: slash command or regular message
        if text.startswith("/"):
            self._dispatch_slash_command(text)
            return

        self._clear_welcome()
        self._add_user_message(text)
        cid = self._conversation.conversation_id
        self._start_processing("Starting session", conversation_id=cid)
        self._do_send_message(text)

    def _dispatch_slash_command(self, text: str) -> None:
        """Route slash commands to the appropriate handler."""
        parts = text.split(None, 1)
        cmd = parts[0].lower()

        handlers = {
            "/help": lambda: self._cmd_cockpit_help(),
            "/shell": lambda: self._cmd_cockpit_shell(),
            "/clear": lambda: self.action_clear_chat(),
            "/quit": lambda: self.exit(),
            "/q": lambda: self.exit(),
        }

        handler = handlers.get(cmd)
        if handler:
            handler()
        else:
            # Try parent mixin commands (token, git, etc.)
            self._add_system_message(
                f"Unknown command: {cmd}\nUse /help for available commands."
            )

    @work(thread=True, group="send-message")
    async def _do_send_message(self, message: str) -> None:
        """Send a message to Amplifier in a background thread."""
        cid = self._conversation.conversation_id
        conv = self._conversation

        if self.session_manager is None:
            self.call_from_thread(self._add_system_message, "No active session")
            return

        try:
            # Auto-create session on first message
            handle = self.session_manager.get_handle(cid)
            if not handle or not handle.session:
                self.call_from_thread(self._update_status, "Starting session...")
                try:
                    await self.session_manager.start_new_session(
                        conversation_id=cid,
                    )
                except Exception as session_err:
                    logger.debug("Session creation failed", exc_info=True)
                    self.call_from_thread(
                        self._show_error,
                        f"Could not start session: {session_err}",
                    )
                    return

            self._wire_streaming_callbacks(cid, conv)
            self.call_from_thread(self._update_status, "Thinking...")

            response = await self.session_manager.send_message(
                message, conversation_id=cid
            )

            if conv.streaming_cancelled:
                return

            # Fallback: if no streaming hooks fired, show the full response
            if not conv.got_stream_content and response:
                self.call_from_thread(self._add_assistant_message, response)

        except Exception as e:
            logger.debug("send message worker failed", exc_info=True)
            if conv.streaming_cancelled:
                return
            self.call_from_thread(self._show_error, str(e))
        finally:
            self.call_from_thread(self._finish_processing, conversation_id=cid)

    @work(thread=True, group="resume")
    async def _resume_session(self, session_id: str) -> None:
        """Resume a session in a background thread."""
        cid = self._conversation.conversation_id
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

            await self.session_manager.resume_session(
                session_id=session_id,
                conversation_id=cid,
            )
            self.call_from_thread(self._update_status, "Ready")
            self.call_from_thread(self._clear_welcome)
            self.call_from_thread(
                self._add_system_message, f"Resumed session {session_id[:12]}..."
            )
        except Exception as e:
            logger.debug("Resume failed", exc_info=True)
            self.call_from_thread(self._show_error, f"Resume failed: {e}")
            self.call_from_thread(self._update_status, "Ready")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def on_chat_input_submitted(self, event) -> None:
        """Handle Enter in the chat input."""
        text = event.value
        event.input.clear()
        self._handle_input(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_clear_chat(self) -> None:
        """Clear the chat view."""
        try:
            chat_view = self._active_chat_view()
            for child in list(chat_view.children):
                child.remove()
        except NoMatches:
            pass

    def action_cancel_streaming(self) -> None:
        """Cancel current streaming."""
        self._conversation.streaming_cancelled = True

    # ------------------------------------------------------------------
    # Inspector toggle methods
    # ------------------------------------------------------------------

    def _toggle_inspector(self) -> None:
        """Toggle the inspector panel visibility."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            if panel.display:
                panel.display = False
                panel.remove_class("visible")
            else:
                panel.display = True
                panel.add_class("visible")
                panel.set_live_mode()
        except NoMatches:
            pass

    def action_toggle_inspector(self) -> None:
        """Textual action for Ctrl+I binding."""
        self._toggle_inspector()

    # ------------------------------------------------------------------
    # BlockSelected handler
    # ------------------------------------------------------------------

    def on_block_selected(self, event: BlockSelected) -> None:
        """Handle block click -- open inspector in pinned mode."""
        # Visual selection
        for cb in self.query(ChatBlock):
            cb.deselect()

        # Open inspector in pinned mode
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            panel.display = True
            panel.add_class("visible")
            panel.pin_to_block(event.block_id)
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
        if handle:
            steer_text = self._steer_queue.dequeue()
            if steer_text:
                handle.inject_user_message(steer_text)
                self._add_system_message(f"[steer injected] {steer_text}")

    # ------------------------------------------------------------------
    # Side session methods for /ask command
    # ------------------------------------------------------------------

    def _build_ask_context(self, block: BlockInfo, question: str) -> str:
        """Build context for the side session from a pinned block."""
        context_parts = []
        
        # Block metadata
        context_parts.append(f"Block {block.block_id} ({block.block_type.name} from turn {block.turn_index})")
        if block.summary:
            context_parts.append(f"Summary: {block.summary}")
        
        # Get actual block content from chat view if available
        try:
            chat_view = self._active_chat_view()
            block_widget = chat_view.query_one(f"#block-{block.block_id}")
            # Try to extract text content from the block widget
            context_parts.append("Content:")
            context_parts.append(str(block_widget))  # Fallback to widget string representation
        except Exception:
            context_parts.append("Content: <unavailable>")
        
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
        """Send ask context to side session (async worker)."""
        if not self.session_manager:
            return
            
        # Lazy create side session
        if not self._side_session_id:
            self._side_session_id = await self.session_manager.create_session(
                initial_prompt="You are an assistant for analyzing conversation blocks. "
                             "Answer questions about the provided context."
            )
        
        handle = self.session_manager.get_handle(self._side_session_id)
        if not handle:
            return
            
        # Send context as user message
        handle.inject_user_message(context)
        
        # Start processing (simplified, no streaming to main chat)
        self.call_from_thread(self._update_status, "Side session thinking...")
        
        # Wait for response (this is a simplified implementation)
        # In a full implementation, you'd stream the response to the inspector
        # For now, just update status
        import asyncio
        await asyncio.sleep(1)  # Simulate processing
        self.call_from_thread(self._update_status, "Side session complete")

    def _notify_inspector_live_mode(self) -> None:
        """Notify inspector panel to follow latest block if in live mode."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            if panel.display:
                panel.follow_latest()
        except NoMatches:
            pass

    def _get_input_target(self) -> str:
        """Determine where input should be routed: 'main' or 'inspector'."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            if panel.display:
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
    app = CockpitApp(
        resume_session_id=resume_session_id,
        initial_prompt=initial_prompt,
    )
    app.run()
