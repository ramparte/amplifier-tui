"""Main Amplifier TUI application."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Collapsible, Input, OptionList, Static
from textual.widgets.option_list import Option
from textual import work

from .theme import CHIC_THEME


# ── Widget Classes ──────────────────────────────────────────────────


class ChatMessage(Static):
    """A chat message with role-based styling."""

    def __init__(self, content: str, role: str = "assistant", **kwargs: object) -> None:
        classes = f"chat-message {role}-message"
        super().__init__(content, classes=classes, **kwargs)


class ThinkingBlock(Static):
    """A dimmed thinking/reasoning block."""

    pass


class ProcessingIndicator(Static):
    """Animated indicator shown during processing."""

    pass


class ErrorMessage(Static):
    """An inline error message."""

    pass


# ── Main Application ────────────────────────────────────────────────


class AmplifierChicApp(App):
    """Amplifier TUI - a clean TUI for Amplifier."""

    CSS_PATH = "styles.tcss"
    TITLE = "Amplifier TUI"

    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "Sessions", show=True),
        Binding("ctrl+n", "new_session", "New", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
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

    # ── Layout ──────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            with Vertical(id="session-sidebar"):
                yield Static(" Sessions", id="sidebar-title")
                yield OptionList(id="session-list")
            with Vertical(id="chat-area"):
                yield ScrollableContainer(id="chat-view")
                yield Input(
                    placeholder="Type a message... (Enter to send)",
                    id="chat-input",
                )
                with Horizontal(id="status-bar"):
                    yield Static("No session", id="status-session")
                    yield Static("Ready", id="status-state")
                    yield Static("", id="status-model")

    async def on_mount(self) -> None:
        self.register_theme(CHIC_THEME)
        self.theme = "chic"

        # Show UI immediately, defer Amplifier import to background
        self._show_welcome()
        self.query_one("#chat-input", Input).focus()

        # Start the spinner timer
        self._spinner_frame = 0
        self._spinner_timer = self.set_interval(0.3, self._animate_spinner)

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

    def _load_session_list(self) -> None:
        """Show loading state then populate in background."""
        if not self._amplifier_available:
            return
        option_list = self.query_one("#session-list", OptionList)
        option_list.clear_options()
        option_list.add_option(Option("  Loading sessions...", disabled=True))
        self._load_sessions_worker()

    @work(thread=True)
    def _load_sessions_worker(self) -> None:
        """Load session list in background thread."""
        from .session_manager import SessionManager

        sessions = SessionManager.list_all_sessions(limit=50)
        self.call_from_thread(self._populate_session_list, sessions)

    def _populate_session_list(self, sessions: list[dict]) -> None:
        """Populate sidebar with sessions grouped by project folder."""
        self._session_list_data = []
        option_list = self.query_one("#session-list", OptionList)
        option_list.clear_options()

        if not sessions:
            option_list.add_option(Option("  No sessions found", disabled=True))
            return

        # Group by project, maintaining recency order
        current_group = None
        for s in sessions:
            project = s["project"]
            if project != current_group:
                current_group = project
                option_list.add_option(Option(f"-- {project} --", disabled=True))

            date = s["date_str"]
            name = s.get("name", "")
            desc = s.get("description", "")

            if name:
                label = name[:26] if len(name) > 26 else name
            elif desc:
                label = desc[:26] if len(desc) > 26 else desc
            else:
                label = s["session_id"][:8]

            display = f"  {date}  {label}"
            option_list.add_option(Option(display))
            self._session_list_data.append(s)

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#session-sidebar")
        self._sidebar_visible = not self._sidebar_visible
        if self._sidebar_visible:
            sidebar.add_class("visible")
            self._load_session_list()
        else:
            sidebar.remove_class("visible")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_list = self.query_one("#session-list", OptionList)
        selected = option_list.get_option_at_index(event.option_index)
        if selected.disabled:
            return

        # Count non-disabled options before this index to map to data list
        data_idx = 0
        for i in range(event.option_index):
            opt = option_list.get_option_at_index(i)
            if not opt.disabled:
                data_idx += 1

        if 0 <= data_idx < len(self._session_list_data):
            session_id = self._session_list_data[data_idx]["session_id"]
            self.action_toggle_sidebar()  # Close sidebar
            self._resume_session_worker(session_id)

    # ── Actions ─────────────────────────────────────────────────

    def action_new_session(self) -> None:
        """Start a fresh session."""
        if self.is_processing:
            return
        # Reset session manager state
        if self.session_manager:
            self.session_manager.session = None
            self.session_manager.session_id = None
        # Clear chat
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        for child in list(chat_view.children):
            child.remove()
        self._show_welcome("New session will start when you send a message.")
        self._update_session_display()
        self._update_status("Ready")
        self.query_one("#chat-input", Input).focus()

    def action_clear_chat(self) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        for child in list(chat_view.children):
            child.remove()

    # ── Input Handling ──────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            return
        if self.is_processing:
            return
        if not self._amplifier_available:
            return
        if not self._amplifier_ready:
            self._update_status("Still loading Amplifier...")
            return

        message = event.value.strip()
        event.input.value = ""

        self._clear_welcome()
        self._add_user_message(message)
        # Show appropriate label based on session state
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(message)

    # ── Message Display ─────────────────────────────────────────

    def _add_user_message(self, text: str) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        msg = ChatMessage(text, role="user")
        chat_view.mount(msg)
        msg.scroll_visible()

    def _add_assistant_message(self, text: str) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        msg = ChatMessage(text, role="assistant")
        chat_view.mount(msg)
        msg.scroll_visible()

    def _add_thinking_block(self, text: str) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        # Show abbreviated preview, full text on expand
        preview = text.split("\n")[0][:80]
        if len(text) > 80:
            preview += "..."
        full_text = text[:600] + "..." if len(text) > 600 else text
        collapsible = Collapsible(
            Static(full_text, classes="thinking-block"),
            title=f"Thinking: {preview}",
            collapsed=True,
        )
        chat_view.mount(collapsible)

    def _add_tool_use(
        self,
        tool_name: str,
        tool_input: dict | str | None = None,
        result: str = "",
    ) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)

        detail_parts: list[str] = []
        if tool_input:
            input_str = (
                json.dumps(tool_input, indent=2)
                if isinstance(tool_input, dict)
                else str(tool_input)
            )
            if len(input_str) > 300:
                input_str = input_str[:300] + "..."
            detail_parts.append(f"Input:\n{input_str}")
        if result:
            r = result[:400] + "..." if len(result) > 400 else result
            detail_parts.append(f"Result:\n{r}")

        detail = "\n\n".join(detail_parts) if detail_parts else "(no details)"

        collapsible = Collapsible(
            Static(detail, classes="tool-detail"),
            title=f"Tool: {tool_name}",
            collapsed=True,
        )
        collapsible.add_class("tool-use")
        chat_view.mount(collapsible)
        collapsible.scroll_visible()

    def _show_error(self, error_text: str) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        msg = ErrorMessage(f"Error: {error_text}", classes="error-message")
        chat_view.mount(msg)
        msg.scroll_visible()

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
        inp = self.query_one("#chat-input", Input)
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
        indicator.scroll_visible()
        self._update_status(f"{label}...")

    def _finish_processing(self) -> None:
        self.is_processing = False
        self._processing_label = None
        inp = self.query_one("#chat-input", Input)
        inp.disabled = False
        inp.remove_class("disabled")
        inp.focus()
        self._remove_processing_indicator()
        self._update_status("Ready")

    def _remove_processing_indicator(self) -> None:
        try:
            self.query_one("#processing-indicator").remove()
        except Exception:
            pass

    # ── Status Bar ──────────────────────────────────────────────

    def _update_status(self, state: str = "Ready") -> None:
        try:
            self.query_one("#status-state", Static).update(state)
        except Exception:
            pass

    def _update_session_display(self) -> None:
        if self.session_manager and getattr(self.session_manager, "session_id", None):
            sid = self.session_manager.session_id[:8]
            self.query_one("#status-session", Static).update(f"Session: {sid}")
        else:
            self.query_one("#status-session", Static).update("No session")

    # ── Streaming Callbacks ─────────────────────────────────────

    def _setup_streaming_callbacks(self) -> None:
        """Wire session manager hooks to UI updates via call_from_thread."""

        def on_content(block_type: str, text: str) -> None:
            self._got_stream_content = True
            if block_type == "thinking":
                self.call_from_thread(self._remove_processing_indicator)
                self.call_from_thread(self._add_thinking_block, text)
            else:
                self.call_from_thread(self._remove_processing_indicator)
                self.call_from_thread(self._add_assistant_message, text)

        def on_tool_start(name: str, tool_input: dict) -> None:
            self.call_from_thread(self._remove_processing_indicator)
            self.call_from_thread(self._update_status, f"Running: {name}")

        def on_tool_end(name: str, tool_input: dict, result: str) -> None:
            self.call_from_thread(self._add_tool_use, name, tool_input, result)
            self.call_from_thread(self._update_status, "Thinking...")

        self.session_manager.on_content_block_end = on_content
        self.session_manager.on_tool_pre = on_tool_start
        self.session_manager.on_tool_post = on_tool_end

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
            self.call_from_thread(self._update_status, "Ready")

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

        tool_results: dict[str, str] = {}

        for msg in load_transcript(transcript_path):
            blocks = parse_message_blocks(msg)
            for block in blocks:
                if block.kind == "user":
                    chat_view.mount(ChatMessage(block.content, role="user"))

                elif block.kind == "text":
                    chat_view.mount(ChatMessage(block.content, role="assistant"))

                elif block.kind == "thinking":
                    preview = block.content[:200]
                    if len(block.content) > 200:
                        preview += "..."
                    chat_view.mount(ThinkingBlock(preview, classes="thinking-block"))

                elif block.kind == "tool_use":
                    result = tool_results.get(block.tool_id, "")
                    input_str = (
                        json.dumps(block.tool_input, indent=2)
                        if isinstance(block.tool_input, dict)
                        else str(block.tool_input)
                    )
                    if len(input_str) > 300:
                        input_str = input_str[:300] + "..."
                    detail = f"Input:\n{input_str}"
                    if result:
                        detail += f"\n\nResult:\n{result}"
                    collapsible = Collapsible(
                        Static(detail, classes="tool-detail"),
                        title=f"Tool: {block.tool_name}",
                        collapsed=True,
                    )
                    collapsible.add_class("tool-use")
                    chat_view.mount(collapsible)

                elif block.kind == "tool_result":
                    tool_results[block.tool_id] = block.content

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
