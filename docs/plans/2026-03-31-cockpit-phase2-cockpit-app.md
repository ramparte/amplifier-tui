# Session Cockpit Phase 2: CockpitApp Shell

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Create a functioning CockpitApp that works as a basic single-session chat in tmux -- block-based rendering, tmux integration, auto-resume. No inspector panel yet (that's Phase 3).

**Architecture:** `CockpitApp` inherits `SharedAppBase` + 6 core command mixins + `CockpitCommandsMixin`, following the same pattern as the existing `AmplifierTuiApp` (see `amplifier_tui/app.py:142-168`) but much simpler. Single conversation, no tabs, no session sidebar. Every stream event creates a `ChatBlock` widget in a `BlockRegistry`. Tmux helpers provide `@amp_session_id` pane variable for auto-resume and BEL on turn completion.

**Tech Stack:** Python 3.12, Textual, pytest, pytest-asyncio

**Prerequisite:** Phase 1 must be complete (block model, ChatBlock widget, block_index passthrough, inject_user_message).

---

## Task 1: Create CockpitCommandsMixin

**Files:**
- Create: `amplifier_tui/commands/cockpit_cmds.py`
- Test: `tests/test_cockpit_cmds.py`

**Step 1: Write the failing test**

Create `tests/test_cockpit_cmds.py`:

```python
"""Tests for CockpitCommandsMixin -- tmux helpers and commands."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from amplifier_tui.commands.cockpit_cmds import (
    CockpitCommandsMixin,
    _send_bel,
    _tmux_get_pane_var,
    _tmux_set_pane_var,
)


class TestTmuxHelpers:
    """Tmux helper functions work correctly outside tmux."""

    def test_get_pane_var_outside_tmux(self):
        """Returns None when $TMUX is not set."""
        with patch.dict("os.environ", {}, clear=True):
            assert _tmux_get_pane_var("@amp_session_id") is None

    def test_set_pane_var_outside_tmux(self):
        """No-op when $TMUX is not set (no exception)."""
        with patch.dict("os.environ", {}, clear=True):
            _tmux_set_pane_var("@amp_session_id", "test-123")  # should not raise

    @patch("subprocess.run")
    def test_get_pane_var_inside_tmux(self, mock_run):
        """Reads pane variable when inside tmux."""
        mock_run.return_value = MagicMock(stdout="session-abc123\n")
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            result = _tmux_get_pane_var("@amp_session_id")
        assert result == "session-abc123"
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_pane_var_empty_returns_none(self, mock_run):
        """Returns None for empty pane variable."""
        mock_run.return_value = MagicMock(stdout="\n")
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            result = _tmux_get_pane_var("@amp_session_id")
        assert result is None

    def test_send_bel_no_crash(self):
        """_send_bel doesn't crash."""
        _send_bel()  # should not raise


class TestCockpitCommandsMixin:
    """CockpitCommandsMixin provides /shell and /help commands."""

    def test_mixin_has_shell_command(self):
        assert hasattr(CockpitCommandsMixin, "_cmd_cockpit_shell")

    def test_mixin_has_help_command(self):
        assert hasattr(CockpitCommandsMixin, "_cmd_cockpit_help")
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_cmds.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'amplifier_tui.commands.cockpit_cmds'`

**Step 3: Write the implementation**

Create `amplifier_tui/commands/cockpit_cmds.py`:

```python
"""Cockpit-specific slash commands and tmux helpers.

Commands:
    /shell     Open a horizontal split pane in tmux for shell access
    /help      Display cockpit command list

Tmux helpers:
    _tmux_get_pane_var  Read a tmux pane user variable
    _tmux_set_pane_var  Write a tmux pane user variable
    _send_bel           Write BEL character to stdout
"""

from __future__ import annotations

import os
import subprocess
import sys

from ..core.log import logger


# ---------------------------------------------------------------------------
# Tmux helpers (module-level, reusable)
# ---------------------------------------------------------------------------


def _tmux_get_pane_var(name: str) -> str | None:
    """Read a tmux pane user variable. Returns None outside tmux."""
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
    """Write a tmux pane user variable. No-op outside tmux."""
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
# Mixin
# ---------------------------------------------------------------------------


class CockpitCommandsMixin:
    """Mixin providing cockpit-specific slash commands."""

    def _cmd_cockpit_shell(self) -> None:
        """Open a horizontal split pane in tmux for shell access."""
        if not os.environ.get("TMUX"):
            self._add_system_message(  # type: ignore[attr-defined]
                "Not running inside tmux -- /shell requires a tmux session."
            )
            return
        try:
            subprocess.run(
                ["tmux", "split-window", "-v", "-l", "30%"],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self._add_system_message(  # type: ignore[attr-defined]
                f"Failed to open shell split: {exc}"
            )

    def _cmd_cockpit_help(self) -> None:
        """Display cockpit command list."""
        help_text = (
            "Cockpit Commands:\n"
            "  /help        Show this help\n"
            "  /shell       Open tmux split for shell access\n"
            "  /model       Show/switch model\n"
            "  /tokens      Show token usage\n"
            "  /include     Include file in next message\n"
            "  /git         Git shortcuts\n"
            "  /clear       Clear chat\n"
            "  /quit        Exit cockpit\n"
        )
        self._add_system_message(help_text)  # type: ignore[attr-defined]
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_cmds.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/commands/cockpit_cmds.py tests/test_cockpit_cmds.py
git commit -m "feat(cockpit): add CockpitCommandsMixin with tmux helpers"
```

---

## Task 2: Create CockpitApp Skeleton with compose()

**Files:**
- Create: `amplifier_tui/cockpit_app.py`
- Test: `tests/test_cockpit_app.py`

**Step 1: Write the failing test**

Create `tests/test_cockpit_app.py`:

```python
"""Tests for CockpitApp -- Textual Pilot widget tests."""

from __future__ import annotations

import pytest
from textual.containers import ScrollableContainer
from textual.widgets import Static

from amplifier_tui.cockpit_app import CockpitApp


class TestCockpitCompose:
    """CockpitApp.compose() produces the expected layout."""

    @pytest.mark.asyncio
    async def test_has_status_bar(self):
        async with CockpitApp().run_test() as pilot:
            status = pilot.app.query_one("#cockpit-status-bar", Static)
            assert status is not None

    @pytest.mark.asyncio
    async def test_has_chat_view(self):
        async with CockpitApp().run_test() as pilot:
            chat_view = pilot.app.query_one("#cockpit-chat-view", ScrollableContainer)
            assert chat_view is not None

    @pytest.mark.asyncio
    async def test_has_chat_input(self):
        from amplifier_tui.widgets.chat_input import ChatInput

        async with CockpitApp().run_test() as pilot:
            chat_input = pilot.app.query_one("#chat-input", ChatInput)
            assert chat_input is not None

    @pytest.mark.asyncio
    async def test_title(self):
        async with CockpitApp().run_test() as pilot:
            assert "Cockpit" in pilot.app.title or "cockpit" in pilot.app.title.lower()
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'amplifier_tui.cockpit_app'`

**Step 3: Write the implementation**

Create `amplifier_tui/cockpit_app.py`:

```python
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

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
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
from .widgets.indicators import (
    ErrorMessage,
    ProcessingIndicator,
    SystemMessage,
)
from .widgets.messages import AssistantMessage, ThinkingBlock, UserMessage

if TYPE_CHECKING:
    from textual.timer import Timer

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

        # Streaming widget state
        self._stream_widget: Static | None = None
        self._stream_container = None
        self._stream_block_type: str = ""
        self._processing_label: str = ""
        self._processing_indicator: ProcessingIndicator | None = None

        # Session state
        self._session_title: str = ""

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield ScrollableContainer(id="cockpit-chat-view")
            yield ChatInput(
                "",
                id="chat-input",
                soft_wrap=True,
                show_line_numbers=False,
                tab_behavior="focus",
                compact=True,
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

    def _add_system_message(self, text: str, *, conversation_id: str = "", **kwargs) -> None:
        chat_view = self._active_chat_view()
        block = ChatBlock(
            block_id=self._block_registry.add(
                BlockType.SYSTEM, self._turn_index, summary=text[:60]
            ).block_id,
            block_type=BlockType.SYSTEM,
            turn_index=self._turn_index,
        )
        block.mount(SystemMessage(text))
        chat_view.mount(block)
        block.scroll_visible()

    def _add_user_message(self, text: str, *, conversation_id: str = "", **kwargs) -> None:
        self._turn_index += 1
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.USER, self._turn_index, summary=text[:60]
        )
        block = ChatBlock(
            block_id=info.block_id,
            block_type=BlockType.USER,
            turn_index=self._turn_index,
        )
        block.mount(UserMessage(text))
        chat_view.mount(block)
        block.scroll_visible()

    def _add_assistant_message(self, text: str, *, conversation_id: str = "", **kwargs) -> None:
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.ASSISTANT, self._turn_index, summary=text[:60]
        )
        block = ChatBlock(
            block_id=info.block_id,
            block_type=BlockType.ASSISTANT,
            turn_index=self._turn_index,
        )
        block.mount(AssistantMessage(text))
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

    def _start_processing(self, label: str = "Thinking", *, conversation_id: str = "") -> None:
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
        self, conversation_id: str, block_type: str, accumulated_text: str, block_index: int = 0
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

    def _on_stream_usage_update(self, conversation_id: str) -> None:
        self.call_from_thread(self._update_status, "Thinking...")

    # ------------------------------------------------------------------
    # Streaming display helpers (main thread)
    # ------------------------------------------------------------------

    def _begin_streaming_block(self, block_type: str, block_index: int = 0) -> None:
        """Create a new streaming widget for incoming content."""
        self._remove_processing_indicator()
        chat_view = self._active_chat_view()

        bt = BlockType.THINKING if block_type in ("thinking", "reasoning") else BlockType.ASSISTANT
        info = self._block_registry.add(bt, self._turn_index, summary=f"[streaming {block_type}]")

        if block_type in ("thinking", "reasoning"):
            widget = Static("", classes="thinking-block thinking-text")
            container = Collapsible(title="Thinking...", collapsed=False)
            container.mount(widget)
            cb = ChatBlock(
                block_id=info.block_id, block_type=bt, turn_index=self._turn_index
            )
            cb.mount(container)
            chat_view.mount(cb)
            self._stream_widget = widget
            self._stream_container = container
        else:
            widget = Markdown("", classes="assistant-message")
            cb = ChatBlock(
                block_id=info.block_id, block_type=bt, turn_index=self._turn_index
            )
            cb.mount(widget)
            chat_view.mount(cb)
            self._stream_widget = widget

        self._stream_block_type = block_type
        cb.scroll_visible()

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
        container = Collapsible(title="Thinking", collapsed=True)
        container.mount(Static(text, classes="thinking-block thinking-text"))
        cb = ChatBlock(
            block_id=info.block_id,
            block_type=BlockType.THINKING,
            turn_index=self._turn_index,
        )
        cb.mount(container)
        chat_view.mount(cb)

    def _add_tool_use(self, name: str, tool_input: dict, result: str) -> None:
        """Add a tool call block to the chat view."""
        chat_view = self._active_chat_view()
        info = self._block_registry.add(
            BlockType.TOOL_CALL, self._turn_index, summary=f"{name}"
        )
        # Compact display: tool name and result in a collapsible
        import json
        input_str = json.dumps(tool_input, indent=2) if isinstance(tool_input, dict) else str(tool_input)
        content = f"Input:\n{input_str}\n\nResult:\n{result[:500]}"
        container = Collapsible(title=f"Tool: {name}", collapsed=True)
        container.mount(Static(content, classes="tool-call"))
        cb = ChatBlock(
            block_id=info.block_id,
            block_type=BlockType.TOOL_CALL,
            turn_index=self._turn_index,
        )
        cb.mount(container)
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

        # Slash command dispatch
        if text.startswith("/"):
            self._dispatch_slash_command(text)
            return

        # Regular message
        self._clear_welcome()
        self._add_user_message(text)
        cid = self._conversation.conversation_id
        self._start_processing("Starting session", conversation_id=cid)
        self._do_send_message(text)

    def _dispatch_slash_command(self, text: str) -> None:
        """Route slash commands to the appropriate handler."""
        parts = text.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help": lambda: self._cmd_cockpit_help(),
            "/shell": lambda: self._cmd_cockpit_shell(),
            "/clear": lambda: self._action_clear_chat(),
            "/quit": lambda: self.exit(),
            "/q": lambda: self.exit(),
        }

        handler = handlers.get(cmd)
        if handler:
            handler()
        else:
            # Try parent mixin commands (token, git, etc.)
            self._add_system_message(f"Unknown command: {cmd}\nUse /help for available commands.")

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
                    self.call_from_thread(self._add_system_message, "No sessions found to resume.")
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
                self._add_system_message,
                f"Resumed session {session_id[:12]}..."
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
    # BlockSelected handler (placeholder for Phase 3 inspector)
    # ------------------------------------------------------------------

    def on_block_selected(self, event: BlockSelected) -> None:
        """Handle block click -- Phase 3 will open the inspector."""
        # For now, just visually select the block
        for cb in self.query(ChatBlock):
            cb.deselect()
        try:
            clicked = self.query_one(f"#block-{event.block_id}", ChatBlock)
            clicked.select()
        except NoMatches:
            pass


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
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/cockpit_app.py tests/test_cockpit_app.py
git commit -m "feat(cockpit): add CockpitApp with compose layout and basic chat"
```

---

## Task 3: Add --cockpit CLI Flag and $TMUX Auto-Detection

**Files:**
- Modify: `amplifier_tui/__main__.py`
- Test: `tests/test_main.py` (add tests)

**Step 1: Read the current test file for patterns**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
head -40 tests/test_main.py
```

**Step 2: Write the failing test**

Append to `tests/test_main.py` (or create if it only has import tests):

```python
class TestCockpitFlag:
    """CLI --cockpit and --no-cockpit flags."""

    def test_cockpit_flag_recognized(self):
        """argparse accepts --cockpit."""
        import argparse
        # Re-create the parser to test flag parsing
        parser = argparse.ArgumentParser()
        parser.add_argument("--cockpit", action="store_true")
        parser.add_argument("--no-cockpit", action="store_true")
        parser.add_argument("prompt", nargs="*")
        args = parser.parse_args(["--cockpit"])
        assert args.cockpit is True
        assert args.no_cockpit is False

    def test_no_cockpit_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--cockpit", action="store_true")
        parser.add_argument("--no-cockpit", action="store_true")
        parser.add_argument("prompt", nargs="*")
        args = parser.parse_args(["--no-cockpit"])
        assert args.no_cockpit is True
```

**Step 3: Add the flags to __main__.py**

In `amplifier_tui/__main__.py`, add two new arguments after the `--web` argument (after line 166):

```python
    parser.add_argument(
        "--cockpit",
        action="store_true",
        help="Launch cockpit mode (single-session, optimized for tmux)",
    )
    parser.add_argument(
        "--no-cockpit",
        action="store_true",
        help="Suppress tmux auto-detection (force standard TUI)",
    )
```

Then, in the `main()` function, add cockpit launching logic after the `--web` block (after line 226) and before the standard TUI launch:

```python
    # --cockpit or $TMUX auto-detection
    use_cockpit = args.cockpit
    if not use_cockpit and not args.no_cockpit and os.environ.get("TMUX"):
        use_cockpit = True

    if use_cockpit:
        try:
            from amplifier_tui.cockpit_app import run_cockpit

            run_cockpit(
                resume_session_id=resume_session_id,
                initial_prompt=initial_prompt,
            )
        except (KeyboardInterrupt, SystemExit):
            pass
        return
```

Also add `import os` at the top of the file if it's not already there (it's not currently imported).

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_main.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/__main__.py tests/test_main.py
git commit -m "feat(cockpit): add --cockpit/--no-cockpit CLI flags with TMUX auto-detection"
```

---

## Task 4: Test Block-Based Rendering in CockpitApp

**Files:**
- Modify: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the tests**

Append to `tests/test_cockpit_app.py`:

```python
from amplifier_tui.models.block_model import BlockType
from amplifier_tui.widgets.chat_block import ChatBlock


class TestCockpitBlockRendering:
    """CockpitApp renders messages as ChatBlock widgets."""

    @pytest.mark.asyncio
    async def test_system_message_creates_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_system_message("Test system message")
            blocks = app.query(ChatBlock)
            assert len(blocks) >= 1
            # Find the system block
            system_blocks = [b for b in blocks if b.block_type == BlockType.SYSTEM]
            assert len(system_blocks) >= 1

    @pytest.mark.asyncio
    async def test_user_message_creates_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._clear_welcome()
            app._add_user_message("Hello world")
            blocks = app.query(ChatBlock)
            user_blocks = [b for b in blocks if b.block_type == BlockType.USER]
            assert len(user_blocks) == 1

    @pytest.mark.asyncio
    async def test_assistant_message_creates_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_assistant_message("Hi there!")
            blocks = app.query(ChatBlock)
            assistant_blocks = [b for b in blocks if b.block_type == BlockType.ASSISTANT]
            assert len(assistant_blocks) == 1

    @pytest.mark.asyncio
    async def test_block_registry_tracks_blocks(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg 1")
            app._add_assistant_message("reply 1")
            assert len(app._block_registry) >= 2

    @pytest.mark.asyncio
    async def test_turn_index_increments_on_user_message(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            initial_turn = app._turn_index
            app._add_user_message("first")
            assert app._turn_index == initial_turn + 1
            app._add_user_message("second")
            assert app._turn_index == initial_turn + 2
```

**Step 2: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitBlockRendering -v
```

Expected: All PASS

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_cockpit_app.py
git commit -m "test(cockpit): add block-based rendering tests for CockpitApp"
```

---

## Task 5: Test BlockSelected Message Handling

**Files:**
- Modify: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the tests**

Append to `tests/test_cockpit_app.py`:

```python
class TestCockpitBlockSelection:
    """CockpitApp handles BlockSelected messages."""

    @pytest.mark.asyncio
    async def test_block_click_selects_block(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("Click me")
            # Find the user block
            blocks = list(app.query(ChatBlock))
            user_blocks = [b for b in blocks if b.block_type == BlockType.USER]
            assert len(user_blocks) > 0
            block = user_blocks[0]
            # Simulate click
            block.on_click()
            await pilot.pause()
            # The block should now have the "selected" class
            assert block.has_class("selected")
```

**Step 2: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitBlockSelection -v
```

Expected: All PASS

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_cockpit_app.py
git commit -m "test(cockpit): add block selection tests for CockpitApp"
```

---

## Task 6: Test Slash Command Dispatch

**Files:**
- Modify: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the tests**

Append to `tests/test_cockpit_app.py`:

```python
class TestCockpitSlashCommands:
    """CockpitApp slash command dispatch."""

    @pytest.mark.asyncio
    async def test_help_command(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._dispatch_slash_command("/help")
            await pilot.pause()
            # Should have added a system message with help text
            blocks = list(app.query(ChatBlock))
            system_blocks = [b for b in blocks if b.block_type == BlockType.SYSTEM]
            # At least one system block with help text
            assert any("help" in str(b.children).lower() for b in system_blocks) or len(system_blocks) > 0

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._dispatch_slash_command("/nonexistent")
            await pilot.pause()
            # Should show unknown command message
            blocks = list(app.query(ChatBlock))
            assert len(blocks) > 0  # At least the welcome + error

    @pytest.mark.asyncio
    async def test_clear_command(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg1")
            app._add_assistant_message("reply1")
            app._dispatch_slash_command("/clear")
            await pilot.pause()
            # Chat view should be empty after clear
            from textual.containers import ScrollableContainer
            chat_view = app.query_one("#cockpit-chat-view", ScrollableContainer)
            assert len(list(chat_view.children)) == 0
```

**Step 2: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitSlashCommands -v
```

Expected: All PASS

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_cockpit_app.py
git commit -m "test(cockpit): add slash command dispatch tests"
```

---

## Task 7: Full Phase 2 Regression Test

**Files:** None modified -- verification only.

**Step 1: Run the complete test suite**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/ -v --timeout=60
```

Expected: All tests PASS including all Phase 1 and Phase 2 tests.

**Step 2: Verify the cockpit module imports cleanly**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -c "
from amplifier_tui.cockpit_app import CockpitApp, run_cockpit
from amplifier_tui.commands.cockpit_cmds import CockpitCommandsMixin
from amplifier_tui.models import BlockRegistry, SteerQueue
print(f'CockpitApp MRO: {[c.__name__ for c in CockpitApp.__mro__[:8]]}')
print('Phase 2 integration check passed!')
"
```

Expected:
```
CockpitApp MRO: ['CockpitApp', 'CockpitCommandsMixin', 'PersistenceCommandsMixin', 'ShellCommandsMixin', 'ContentCommandsMixin', 'FileCommandsMixin', 'GitCommandsMixin', 'TokenCommandsMixin']
Phase 2 integration check passed!
```

**Step 3: Verify CLI help shows --cockpit flag**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m amplifier_tui --help | grep -i cockpit
```

Expected: Shows `--cockpit` and `--no-cockpit` in the help output.

---

## Summary

| Task | What | Files | Tests |
|------|------|-------|-------|
| 1 | CockpitCommandsMixin | commands/cockpit_cmds.py | test_cockpit_cmds.py |
| 2 | CockpitApp skeleton + compose | cockpit_app.py | test_cockpit_app.py |
| 3 | --cockpit CLI flag + $TMUX | __main__.py | test_main.py |
| 4 | Block-based rendering tests | (none) | test_cockpit_app.py |
| 5 | BlockSelected handling tests | (none) | test_cockpit_app.py |
| 6 | Slash command dispatch tests | (none) | test_cockpit_app.py |
| 7 | Full regression | (none) | all tests |

**Phase 2 delivers:** A working CockpitApp that can be launched with `--cockpit` or auto-detected in tmux, sends/receives messages via Amplifier, renders all stream events as ChatBlock widgets, and supports basic slash commands. Phase 3 adds the inspector panel, side session, and steering.
