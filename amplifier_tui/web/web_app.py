"""WebApp: web frontend inheriting SharedAppBase + all 16 command mixins."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from amplifier_tui.core.app_base import SharedAppBase
from amplifier_tui.core.commands import (
    AgentCommandsMixin,
    BranchCommandsMixin,
    CompareCommandsMixin,
    ContentCommandsMixin,
    DashboardCommandsMixin,
    FileCommandsMixin,
    GitCommandsMixin,
    PersistenceCommandsMixin,
    PluginCommandsMixin,
    RecipeCommandsMixin,
    ReplayCommandsMixin,
    ShellCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    ToolCommandsMixin,
    WatchCommandsMixin,
)
from amplifier_tui.core.session_manager import SessionManager

logger = logging.getLogger(__name__)


class WebApp(
    SharedAppBase,
    GitCommandsMixin,
    TokenCommandsMixin,
    AgentCommandsMixin,
    RecipeCommandsMixin,
    BranchCommandsMixin,
    CompareCommandsMixin,
    ContentCommandsMixin,
    DashboardCommandsMixin,
    FileCommandsMixin,
    PersistenceCommandsMixin,
    PluginCommandsMixin,
    ReplayCommandsMixin,
    ShellCommandsMixin,
    ThemeCommandsMixin,
    ToolCommandsMixin,
    WatchCommandsMixin,
):
    """Web frontend app inheriting shared backend + all command mixins."""

    def __init__(self, websocket: Any) -> None:
        super().__init__()
        self._ws = websocket
        self._loop: asyncio.AbstractEventLoop | None = None
        self.session_manager = SessionManager()

        # Features used by command mixins and _wire_streaming_callbacks
        from amplifier_tui.core.features.agent_tracker import AgentTracker
        from amplifier_tui.core.features.recipe_tracker import RecipeTracker
        from amplifier_tui.core.features.tool_log import ToolLog

        self._agent_tracker = AgentTracker()
        self._tool_log = ToolLog()
        self._recipe_tracker = RecipeTracker()

    # ------------------------------------------------------------------
    # Thread-safe WebSocket send
    # ------------------------------------------------------------------

    def _send_event(self, event: dict[str, Any]) -> None:
        """Thread-safe WebSocket send.  Can be called from background threads."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._ws_send_json(event), self._loop)

    async def _ws_send_json(self, event: dict[str, Any]) -> None:
        """Actually send JSON over WebSocket (must run on event loop)."""
        try:
            await self._ws.send_json(event)
        except Exception:
            logger.debug("WebSocket send failed", exc_info=True)

    # ------------------------------------------------------------------
    # Abstract display methods (SharedAppBase)
    # ------------------------------------------------------------------

    def _add_system_message(self, text: str, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
        self._send_event({"type": "system_message", "text": text})

    def _add_user_message(self, text: str, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
        self._send_event({"type": "user_message", "text": text})

    def _add_assistant_message(self, text: str, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
        self._send_event({"type": "assistant_message", "text": text})

    def _show_error(self, text: str) -> None:
        self._send_event({"type": "error", "text": text})

    def _update_status(self, text: str) -> None:
        self._send_event({"type": "status", "text": text})

    def _start_processing(self, label: str = "Thinking") -> None:
        self.is_processing = True
        self._send_event({"type": "processing_start", "label": label})

    def _finish_processing(self) -> None:
        self.is_processing = False
        self._send_event({"type": "processing_end"})

    # ------------------------------------------------------------------
    # Abstract streaming methods (called from BACKGROUND THREAD)
    # ------------------------------------------------------------------

    def _on_stream_block_start(self, block_type: str) -> None:
        self._send_event({"type": "stream_start", "block_type": block_type})

    def _on_stream_block_delta(self, block_type: str, accumulated_text: str) -> None:
        self._send_event({
            "type": "stream_delta",
            "block_type": block_type,
            "text": accumulated_text,
        })

    def _on_stream_block_end(
        self, block_type: str, final_text: str, had_block_start: bool
    ) -> None:
        self._send_event({
            "type": "stream_end",
            "block_type": block_type,
            "text": final_text,
        })

    def _on_stream_tool_start(self, name: str, tool_input: dict) -> None:  # type: ignore[type-arg]
        self._send_event({
            "type": "tool_start",
            "tool_name": name,
            "tool_input": tool_input,
        })

    def _on_stream_tool_end(self, name: str, tool_input: dict, result: str) -> None:  # type: ignore[type-arg]
        self._send_event({
            "type": "tool_end",
            "tool_name": name,
            "tool_input": tool_input,
            "result": result,
        })

    def _on_stream_usage_update(self) -> None:
        sm = self.session_manager
        if sm:
            self._send_event({
                "type": "usage_update",
                "input_tokens": sm.total_input_tokens,
                "output_tokens": sm.total_output_tokens,
                "model": sm.model_name or "",
            })

    # ------------------------------------------------------------------
    # Command routing
    # ------------------------------------------------------------------

    def _route_command(self, text: str) -> bool:
        """Route slash commands.  Returns True if handled."""
        if not text.startswith("/"):
            return False

        parts = text.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Primary command map -- maps /cmd to the mixin handler
        handlers: dict[str, Any] = {
            "/help": lambda: self._add_system_message(
                "Available commands: /git, /diff, /tokens, /agents, /recipe, "
                "/tools, /compare, /branch, /branches, /replay, /dashboard, "
                "/watch, /plugins, /shell, /theme, /stats, /info, /context, "
                "/system, /mode, /attach, /cat, /history, /ref, /alias, "
                "/snippet, /template, /draft, /drafts, /note, /bookmark, "
                "/bookmarks, /tag, /pin, /pins, /new, /clear, /help"
            ),
            # Git
            "/git": lambda: self._cmd_git(args),
            "/diff": lambda: self._cmd_diff(args),
            "/gitstatus": lambda: self._cmd_git(""),
            "/gs": lambda: self._cmd_git(""),
            # Tokens / info
            "/tokens": lambda: self._cmd_tokens(),
            "/token": lambda: self._cmd_tokens(),
            "/stats": lambda: self._cmd_stats(args),
            "/info": lambda: self._cmd_info(),
            "/context": lambda: self._cmd_context(args),
            "/keys": lambda: self._cmd_keys(),
            # Agents / recipes / tools
            "/agents": lambda: self._cmd_agents(args),
            "/recipe": lambda: self._cmd_recipe(args),
            "/tools": lambda: self._cmd_tools(args),
            # Branching
            "/compare": lambda: self._cmd_compare(args),
            "/branch": lambda: self._cmd_branch(args),
            "/branches": lambda: self._cmd_branches(args),
            "/fork": lambda: self._cmd_fork(args),
            # Replay / dashboard / watch
            "/replay": lambda: self._cmd_replay(args),
            "/dashboard": lambda: self._cmd_dashboard(args),
            "/watch": lambda: self._cmd_watch(args),
            # Plugins / shell / theme
            "/plugins": lambda: self._cmd_plugins(args),
            "/shell": lambda: self._cmd_shell(args),
            "/theme": lambda: self._cmd_theme(args),
            # Content
            "/system": lambda: self._cmd_system(args),
            "/mode": lambda: self._cmd_mode(args),
            "/attach": lambda: self._cmd_attach(args),
            "/cat": lambda: self._cmd_cat(args),
            "/history": lambda: self._cmd_history(args),
            "/copy": lambda: self._cmd_copy(args),
            "/redo": lambda: self._cmd_redo(args),
            "/retry": lambda: self._cmd_retry(args),
            "/undo": lambda: self._cmd_undo(args),
            # Persistence
            "/ref": lambda: self._cmd_ref(args),
            "/alias": lambda: self._cmd_alias(args),
            "/snippet": lambda: self._cmd_snippet(args),
            "/template": lambda: self._cmd_template(args),
            "/draft": lambda: self._cmd_draft(args),
            "/drafts": lambda: self._cmd_drafts(args),
            "/note": lambda: self._cmd_note(args),
            "/bookmark": lambda: self._cmd_bookmark(args),
            "/bookmarks": lambda: self._cmd_bookmarks(args),
            "/tag": lambda: self._cmd_tag(args),
            "/pin": lambda: self._cmd_pin_msg(args),
            "/pins": lambda: self._cmd_pins(args),
            "/unpin": lambda: self._cmd_unpin(args),
            "/clipboard": lambda: self._cmd_clipboard(args),
            # Session management
            "/new": lambda: self._handle_new_session(),
            "/clear": lambda: self._send_event({"type": "clear"}),
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                handler()
            except Exception as exc:
                self._show_error(f"Command error: {exc}")
            return True

        self._add_system_message(
            f"Unknown command: {cmd}\nType /help for available commands."
        )
        return True

    def _handle_new_session(self) -> None:
        """Start a new session.  Actual creation deferred to handle_message."""
        if self.session_manager:
            # Reset for fresh session
            self.session_manager.session = None
            self.session_manager.reset_usage()
        self._amplifier_ready = False
        self._send_event({"type": "clear"})
        self._add_system_message("Starting new session... Send a message to begin.")

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def handle_message(self, text: str) -> None:
        """Handle a user message (chat or command)."""
        text = text.strip()
        if not text:
            return

        if text.startswith("/"):
            self._route_command(text)
            return

        # Chat message
        self._add_user_message(text)
        self._start_processing()
        self._wire_streaming_callbacks()
        self._tool_count_this_turn = 0
        self._got_stream_content = False

        try:
            if not self.session_manager.session:
                await self.session_manager.start_new_session()
                self._amplifier_ready = True
                self._send_event({
                    "type": "session_started",
                    "session_id": self.session_manager.session_id or "",
                    "model": self.session_manager.model_name or "",
                })

            response = await self.session_manager.send_message(text)

            # If streaming didn't produce content, show the final response
            if not self._got_stream_content and response:
                self._add_assistant_message(response)
        except Exception as exc:
            self._show_error(f"Error: {exc}")
            logger.exception("Message handling error")
        finally:
            self._finish_processing()

    async def initialize(self) -> None:
        """Initialize the app (called once when WebSocket connects)."""
        self._loop = asyncio.get_event_loop()
        self._send_event({"type": "connected", "status": "ready"})

    async def shutdown(self) -> None:
        """Clean up when WebSocket disconnects."""
        if self.session_manager and self.session_manager.session:
            try:
                await self.session_manager.end_session()
            except Exception:
                logger.debug("Error ending session on disconnect", exc_info=True)
