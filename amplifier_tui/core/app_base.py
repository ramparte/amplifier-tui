"""Shared application base class for TUI and Web frontends."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .conversation import ConversationState
from .features.agent_tracker import is_delegate_tool, make_delegate_key
from .session_manager import SessionManager

if TYPE_CHECKING:
    pass


class SharedAppBase:
    """Base class providing shared state and command infrastructure.

    Both TUI and Web inherit from this. Command mixins are mixed in
    alongside this class. Subclasses implement the abstract display methods.
    """

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        # Cooperative MRO: propagate to next base (e.g. Textual App)
        super().__init__(**kwargs)

        # -- Session engine --
        self.session_manager: SessionManager | None = None

        # -- App-level state (NOT per-conversation) --
        self._amplifier_ready: bool = False
        self._amplifier_available: bool = False
        self._auto_mode: str = "full"

        # -- Active mode (per-conversation, but also on self for convenience) --
        self._active_mode: str | None = None

    # --- Multi-conversation helpers ---

    def _all_conversations(self) -> list:
        """Return all active ConversationState objects.
        TUI returns: [tab.conversation for tab in self._tabs]
        Web returns: [self._conversation]
        """
        raise NotImplementedError

    @property
    def is_any_processing(self) -> bool:
        """True if ANY conversation is currently processing."""
        return any(c.is_processing for c in self._all_conversations())

    # --- Abstract display methods (subclasses MUST implement) ---

    def _add_system_message(
        self, text: str, *, conversation_id: str = "", **kwargs
    ) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _add_user_message(
        self, text: str, *, conversation_id: str = "", **kwargs
    ) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _add_assistant_message(
        self, text: str, *, conversation_id: str = "", **kwargs
    ) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _show_error(self, text: str, *, conversation_id: str = "") -> None:
        raise NotImplementedError

    def _update_status(self, text: str, *, conversation_id: str = "") -> None:
        raise NotImplementedError

    def _start_processing(
        self, label: str = "Thinking", *, conversation_id: str = ""
    ) -> None:
        raise NotImplementedError

    def _finish_processing(self, *, conversation_id: str = "") -> None:
        raise NotImplementedError

    # --- Abstract streaming display methods (called from BACKGROUND THREAD) ---
    # Subclasses must handle thread-safety (e.g., call_from_thread for TUI).

    def _on_stream_block_start(self, conversation_id: str, block_type: str) -> None:
        """A streaming content block has started (text or thinking)."""
        raise NotImplementedError

    def _on_stream_block_delta(
        self, conversation_id: str, block_type: str, accumulated_text: str
    ) -> None:
        """Incremental streaming text update (throttled, provides full accumulated text)."""
        raise NotImplementedError

    def _on_stream_block_end(
        self,
        conversation_id: str,
        block_type: str,
        final_text: str,
        had_block_start: bool,
    ) -> None:
        """A streaming content block has ended with final complete text.

        had_block_start indicates whether a block_start event was received
        before this end event (True = streaming widget exists, False = fallback).
        """
        raise NotImplementedError

    def _on_stream_tool_start(
        self, conversation_id: str, name: str, tool_input: dict
    ) -> None:  # type: ignore[type-arg]
        """A tool call is starting."""
        raise NotImplementedError

    def _on_stream_tool_end(
        self, conversation_id: str, name: str, tool_input: dict, result: str
    ) -> None:  # type: ignore[type-arg]
        """A tool call has completed."""
        raise NotImplementedError

    def _on_stream_usage_update(self, conversation_id: str) -> None:
        """Token usage statistics have been updated on session_manager."""
        raise NotImplementedError

    # --- Streaming callback wiring ---

    def _wire_streaming_callbacks(
        self,
        conversation_id: str,
        conversation: ConversationState,
    ) -> None:
        """Wire streaming callbacks to a specific SessionHandle and ConversationState.

        Called before each message send. Creates closures that capture both the
        conversation_id and the ConversationState, so streaming events from
        concurrent sessions route to the correct conversation's state.

        Closures run on background thread. Abstract methods are called from
        that thread -- subclasses handle thread-safety.
        """
        if self.session_manager is None:
            return

        handle = self.session_manager.get_handle(conversation_id)
        if handle is None:
            return

        conv = conversation  # alias for closures

        # Per-turn state (reset each message send)
        accumulated = {"text": ""}
        last_update = {"t": 0.0}
        block_started = {"v": False}

        def on_block_start(block_type: str, block_index: int) -> None:
            accumulated["text"] = ""
            last_update["t"] = 0.0
            block_started["v"] = True
            self._on_stream_block_start(conversation_id, block_type)

        def on_block_delta(block_type: str, delta: str) -> None:
            if conv.streaming_cancelled:
                return
            accumulated["text"] += delta
            conv.stream_accumulated_text = accumulated["text"]
            now = time.monotonic()
            if now - last_update["t"] >= 0.05:
                last_update["t"] = now
                snapshot = accumulated["text"]
                self._on_stream_block_delta(conversation_id, block_type, snapshot)

        def on_block_end(block_type: str, text: str) -> None:
            conv.got_stream_content = True
            had_start = block_started["v"]
            if had_start:
                block_started["v"] = False
                accumulated["text"] = ""
            self._on_stream_block_end(conversation_id, block_type, text, had_start)

        def on_tool_start(name: str, tool_input: dict) -> None:
            conv.tool_count_this_turn += 1

            # Live tool introspection log
            tool_log = getattr(self, "_tool_log", None)
            if tool_log is not None:
                tool_log.on_tool_start(name, tool_input)

            # Track agent delegations
            if is_delegate_tool(name) and isinstance(tool_input, dict):
                key = make_delegate_key(tool_input)
                if key:
                    agent_tracker = getattr(self, "_agent_tracker", None)
                    if agent_tracker is not None:
                        agent_tracker.on_delegate_start(
                            tool_use_id=key,
                            agent=tool_input.get("agent", ""),
                            instruction=tool_input.get("instruction", ""),
                        )

            # Track recipe executions
            if name == "recipes" and isinstance(tool_input, dict):
                op = tool_input.get("operation", "")
                if op == "execute":
                    recipe_tracker = getattr(self, "_recipe_tracker", None)
                    if recipe_tracker is not None:
                        recipe_path = tool_input.get("recipe_path", "")
                        recipe_name = (
                            recipe_path.rsplit("/", 1)[-1].replace(".yaml", "")
                            if recipe_path
                            else "unknown"
                        )
                        recipe_tracker.on_recipe_start(
                            recipe_name, [], source_file=recipe_path
                        )

            self._on_stream_tool_start(conversation_id, name, tool_input)

        def on_tool_end(name: str, tool_input: dict, result: str) -> None:
            _tool_status = "failed" if result.startswith("Error") else "completed"
            tool_log = getattr(self, "_tool_log", None)
            if tool_log is not None:
                tool_log.on_tool_end(name, status=_tool_status)

            if is_delegate_tool(name) and isinstance(tool_input, dict):
                key = make_delegate_key(tool_input)
                if key:
                    agent_tracker = getattr(self, "_agent_tracker", None)
                    if agent_tracker is not None:
                        status = "failed" if result.startswith("Error") else "completed"
                        agent_tracker.on_delegate_complete(
                            tool_use_id=key,
                            result=result,
                            status=status,
                        )

            if name == "recipes" and isinstance(tool_input, dict):
                op = tool_input.get("operation", "")
                if op == "execute":
                    recipe_tracker = getattr(self, "_recipe_tracker", None)
                    if recipe_tracker is not None:
                        r_status = (
                            "failed" if result.startswith("Error") else "completed"
                        )
                        recipe_tracker.on_recipe_complete(status=r_status)

            self._on_stream_tool_end(conversation_id, name, tool_input, result)

        def on_usage() -> None:
            self._on_stream_usage_update(conversation_id)

        # Wire to the SessionHandle (not session_manager)
        handle.on_content_block_start = on_block_start
        handle.on_content_block_delta = on_block_delta
        handle.on_content_block_end = on_block_end
        handle.on_tool_pre = on_tool_start
        handle.on_tool_post = on_tool_end
        handle.on_usage_update = on_usage
