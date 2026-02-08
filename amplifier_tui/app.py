"""Main Amplifier TUI application."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Collapsible, Markdown, Static, TextArea, Tree
from textual import work

from .preferences import load_preferences
from .theme import CHIC_THEME


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
    """TextArea where Enter submits, Ctrl+J inserts a newline."""

    class Submitted(TextArea.Changed):
        """Fired when the user presses Enter."""

    async def _on_key(self, event) -> None:
        if event.key == "enter":
            # Submit the message
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(text_area=self))
        elif event.key == "ctrl+j":
            # Insert a newline (Ctrl+J = linefeed)
            event.prevent_default()
            event.stop()
            self.insert("\n")
        else:
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


# ── Main Application ────────────────────────────────────────────────


class AmplifierChicApp(App):
    """Amplifier TUI - a clean TUI for Amplifier."""

    CSS_PATH = "styles.tcss"
    TITLE = "Amplifier TUI"

    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "Sessions", show=True),
        Binding("ctrl+g", "open_editor", "Editor", show=True),
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
        self._prefs = load_preferences()

        # Streaming display state
        self._stream_widget: Static | None = None
        self._stream_container: Collapsible | None = None
        self._stream_block_type: str | None = None

    # ── Layout ──────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            with Vertical(id="session-sidebar"):
                yield Static(" Sessions", id="sidebar-title")
                yield Tree("Sessions", id="session-tree")
            with Vertical(id="chat-area"):
                yield ScrollableContainer(id="chat-view")
                yield ChatInput(
                    "",
                    id="chat-input",
                    soft_wrap=True,
                    show_line_numbers=False,
                    tab_behavior="focus",
                    compact=True,
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
        self.query_one("#chat-input", ChatInput).focus()

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

    def _populate_session_list(self, sessions: list[dict]) -> None:
        """Populate sidebar tree with sessions grouped by project folder.

        Each project folder is an expandable node. Sessions show as single-line
        summaries (date + name/description). Session ID is stored as node data
        for selection handling without cluttering the display.
        """
        self._session_list_data = []
        tree = self.query_one("#session-tree", Tree)
        tree.clear()
        tree.show_root = False

        if not sessions:
            tree.root.add_leaf("No sessions found")
            return

        # Group by project, maintaining recency order
        current_group: str | None = None
        group_node = tree.root
        for s in sessions:
            project = s["project"]
            if project != current_group:
                current_group = project
                # Shorten long paths: show last 2 components
                parts = project.split("/")
                short = "/".join(parts[-2:]) if len(parts) > 2 else project
                group_node = tree.root.add(short, expand=True)

            date = s["date_str"]
            name = s.get("name", "")
            desc = s.get("description", "")

            if name:
                label = name[:28] if len(name) > 28 else name
            elif desc:
                label = desc[:28] if len(desc) > 28 else desc
            else:
                label = s["session_id"][:8]

            # Session is an expandable node: summary on collapse, ID on expand
            display = f"{date}  {label}"
            session_node = group_node.add(display, data=s["session_id"])
            session_node.add_leaf(f"id: {s['session_id'][:12]}...")
            session_node.collapse()
            self._session_list_data.append(s)

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#session-sidebar")
        self._sidebar_visible = not self._sidebar_visible
        if self._sidebar_visible:
            sidebar.add_class("visible")
            self._load_session_list()
        else:
            sidebar.remove_class("visible")

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
        # Don't close sidebar - let user close it manually with Ctrl+B
        self._resume_session_worker(session_id)

    # ── Actions ─────────────────────────────────────────────────

    async def action_quit(self) -> None:
        """Clean up the Amplifier session before quitting.

        Cleanup must run in a @work(thread=True) worker because the session
        was created in a worker thread with its own asyncio event loop.
        Running async cleanup on Textual's main loop fails silently.
        """
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
        self.query_one("#chat-input", ChatInput).focus()

    def action_clear_chat(self) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        for child in list(chat_view.children):
            child.remove()

    def action_open_editor(self) -> None:
        """Open $EDITOR for composing a longer prompt (Ctrl+G)."""
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"

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

            if new_text:
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

        self._clear_welcome()
        self._add_user_message(text)
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(text)

    # ── Slash Commands ────────────────────────────────────────

    def _handle_slash_command(self, text: str) -> None:
        """Route a slash command to the appropriate handler."""
        parts = text.strip().split(None, 1)
        cmd = parts[0].lower()
        # arg = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help": self._cmd_help,
            "/clear": self._cmd_clear,
            "/new": self._cmd_new,
            "/sessions": self._cmd_sessions,
            "/preferences": self._cmd_prefs,
            "/prefs": self._cmd_prefs,
            "/model": self._cmd_model,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
            "/compact": self._cmd_compact,
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
            "  /model        Show model info\n"
            "  /compact      Clear chat, keep session\n"
            "  /quit         Quit\n"
            "\n"
            "Key Bindings\n"
            "\n"
            "  Enter         Send message\n"
            "  Ctrl+J        Insert newline\n"
            "  Ctrl+G        Open $EDITOR for longer prompts\n"
            "  Ctrl+B        Toggle sidebar\n"
            "  Ctrl+N        New session\n"
            "  Ctrl+L        Clear chat\n"
            "  Ctrl+Q        Quit"
        )
        self._add_system_message(help_text)

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

    def _cmd_model(self) -> None:
        if not self.session_manager:
            self._add_system_message("No session manager available.")
            return

        sm = self.session_manager
        lines = ["Model Info\n"]

        if sm.model_name:
            lines.append(f"  Model:    {sm.model_name}")
        else:
            lines.append("  Model:    (not set)")

        total_in = getattr(sm, "total_input_tokens", 0)
        total_out = getattr(sm, "total_output_tokens", 0)
        ctx = getattr(sm, "context_window", 0)

        if total_in or total_out:
            lines.append(f"  Input:    {self._format_token_count(total_in)} tokens")
            lines.append(f"  Output:   {self._format_token_count(total_out)} tokens")
            lines.append(
                f"  Total:    {self._format_token_count(total_in + total_out)} tokens"
            )
        else:
            lines.append("  Tokens:   (no usage yet)")

        if ctx > 0:
            pct = int((total_in + total_out) / ctx * 100) if ctx else 0
            lines.append(
                f"  Context:  {self._format_token_count(ctx)} window ({pct}% used)"
            )

        sid = getattr(sm, "session_id", None)
        if sid:
            lines.append(f"  Session:  {sid[:12]}...")

        self._add_system_message("\n".join(lines))

    def _cmd_quit(self) -> None:
        # Use call_later so the current handler finishes before quit runs
        self.call_later(self.action_quit)

    def _cmd_compact(self) -> None:
        """Clear chat visually but keep the session alive."""
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        for child in list(chat_view.children):
            child.remove()
        self._add_system_message("Chat cleared. Session continues.")

    # ── Message Display ─────────────────────────────────────────

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

    def _style_system(self, widget: Static) -> None:
        """Apply preference colors to a system message."""
        c = self._prefs.colors
        widget.styles.color = c.system_text
        widget.styles.border_left = ("thick", c.system_border)

    def _add_user_message(self, text: str) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        msg = UserMessage(text)
        chat_view.mount(msg)
        self._style_user(msg)
        msg.scroll_visible()

    def _add_assistant_message(self, text: str) -> None:
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        msg = AssistantMessage(text)
        chat_view.mount(msg)
        self._style_assistant(msg)
        msg.scroll_visible()

    def _add_system_message(self, text: str) -> None:
        """Display a system message (slash command output)."""
        chat_view = self.query_one("#chat-view", ScrollableContainer)
        msg = SystemMessage(text)
        chat_view.mount(msg)
        self._style_system(msg)
        msg.scroll_visible()

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

        inner = Static(detail, classes="tool-detail")
        collapsible = Collapsible(
            inner,
            title=f"\u25b6 {tool_name}",
            collapsed=True,
        )
        collapsible.add_class("tool-use")
        chat_view.mount(collapsible)
        self._style_tool(collapsible, inner)
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
        indicator.scroll_visible()
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

    def _update_token_display(self) -> None:
        """Update the status bar with current token usage and model info."""
        if not self.session_manager:
            return
        try:
            sm = self.session_manager
            parts: list[str] = []

            if sm.model_name:
                name = sm.model_name
                if name.startswith("claude-"):
                    name = name[7:]
                parts.append(name)

            total = sm.total_input_tokens + sm.total_output_tokens
            if total > 0 and sm.context_window > 0:
                used = self._format_token_count(total)
                cap = self._format_token_count(sm.context_window)
                pct = int(total / sm.context_window * 100)
                parts.append(f"{used}/{cap} ({pct}%)")
            elif total > 0:
                parts.append(f"{self._format_token_count(total)} tokens")

            self.query_one("#status-model", Static).update(
                " | ".join(parts) if parts else ""
            )
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
            self.call_from_thread(self._remove_processing_indicator)
            self.call_from_thread(self._update_status, f"Running: {name}")

        def on_tool_end(name: str, tool_input: dict, result: str) -> None:
            self.call_from_thread(self._add_tool_use, name, tool_input, result)
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
            widget.scroll_visible()
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
        self._stream_widget.scroll_visible()

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
            old = self._stream_widget
            if old:
                msg = AssistantMessage(text)
                chat_view.mount(msg, before=old)
                self._style_assistant(msg)
                old.remove()
                msg.scroll_visible()
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
                    widget = UserMessage(block.content)
                    chat_view.mount(widget)
                    self._style_user(widget)

                elif block.kind == "text":
                    widget = AssistantMessage(block.content)
                    chat_view.mount(widget)
                    self._style_assistant(widget)

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
                    inner = Static(detail, classes="tool-detail")
                    collapsible = Collapsible(
                        inner,
                        title=f"\u25b6 {block.tool_name}",
                        collapsed=True,
                    )
                    collapsible.add_class("tool-use")
                    chat_view.mount(collapsible)
                    self._style_tool(collapsible, inner)

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
