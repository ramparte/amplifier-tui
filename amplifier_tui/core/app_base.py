"""Shared application base class for TUI and Web frontends."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

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

        # -- Processing state (global, not per-conversation) --
        self.is_processing: bool = False
        self._amplifier_ready: bool = False
        self._amplifier_available: bool = False
        self._auto_mode: str = "full"
        self._queued_message: str | None = None
        self._got_stream_content: bool = False

        # -- Streaming state (reset per message send) --
        self._stream_accumulated_text: str = ""
        self._streaming_cancelled: bool = False
        self._tool_count_this_turn: int = 0

        # -- Active mode (per-conversation, but also on self for convenience) --
        self._active_mode: str | None = None

    # --- Abstract display methods (subclasses MUST implement) ---

    def _add_system_message(self, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _add_user_message(self, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _add_assistant_message(self, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _show_error(self, text: str) -> None:
        raise NotImplementedError

    def _update_status(self, text: str) -> None:
        raise NotImplementedError

    def _start_processing(self, label: str = "Thinking") -> None:
        raise NotImplementedError

    def _finish_processing(self) -> None:
        raise NotImplementedError

    # --- Abstract streaming display methods (called from BACKGROUND THREAD) ---
    # Subclasses must handle thread-safety (e.g., call_from_thread for TUI).

    def _on_stream_block_start(self, block_type: str) -> None:
        """A streaming content block has started (text or thinking)."""
        raise NotImplementedError

    def _on_stream_block_delta(self, block_type: str, accumulated_text: str) -> None:
        """Incremental streaming text update (throttled, provides full accumulated text)."""
        raise NotImplementedError

    def _on_stream_block_end(
        self, block_type: str, final_text: str, had_block_start: bool
    ) -> None:
        """A streaming content block has ended with final complete text.

        had_block_start indicates whether a block_start event was received
        before this end event (True = streaming widget exists, False = fallback).
        """
        raise NotImplementedError

    def _on_stream_tool_start(self, name: str, tool_input: dict) -> None:  # type: ignore[type-arg]
        """A tool call is starting."""
        raise NotImplementedError

    def _on_stream_tool_end(self, name: str, tool_input: dict, result: str) -> None:  # type: ignore[type-arg]
        """A tool call has completed."""
        raise NotImplementedError

    def _on_stream_usage_update(self) -> None:
        """Token usage statistics have been updated on session_manager."""
        raise NotImplementedError

    # --- Streaming callback wiring ---

    def _wire_streaming_callbacks(self) -> None:
        """Wire session_manager streaming callbacks with shared state tracking.

        Called before each message send.  Handles:
        - Accumulated text tracking
        - Tool count tracking
        - Tool log updates
        - Agent tracker updates
        - Recipe tracker updates
        - Delegates display to abstract ``_on_stream_*`` methods

        Closures run on background thread.  Abstract methods are called from
        that thread -- subclasses handle thread-safety.
        """
        if self.session_manager is None:
            return

        # Per-turn state (reset each message send)
        accumulated = {"text": ""}
        last_update = {"t": 0.0}
        block_started = {"v": False}

        def on_block_start(block_type: str, block_index: int) -> None:
            accumulated["text"] = ""
            last_update["t"] = 0.0
            block_started["v"] = True
            self._on_stream_block_start(block_type)

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
                self._on_stream_block_delta(block_type, snapshot)

        def on_block_end(block_type: str, text: str) -> None:
            self._got_stream_content = True
            had_start = block_started["v"]
            if had_start:
                # Streaming widget exists - finalize it with complete text
                block_started["v"] = False
                accumulated["text"] = ""
            self._on_stream_block_end(block_type, text, had_start)

        def on_tool_start(name: str, tool_input: dict) -> None:  # type: ignore[type-arg]
            # Shared state: increment tool counter
            self._tool_count_this_turn += 1

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

            self._on_stream_tool_start(name, tool_input)

        def on_tool_end(name: str, tool_input: dict, result: str) -> None:  # type: ignore[type-arg]
            # Live tool introspection log
            _tool_status = "failed" if result.startswith("Error") else "completed"
            tool_log = getattr(self, "_tool_log", None)
            if tool_log is not None:
                tool_log.on_tool_end(name, status=_tool_status)

            # Complete agent delegation tracking
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

            # Complete recipe tracking
            if name == "recipes" and isinstance(tool_input, dict):
                op = tool_input.get("operation", "")
                if op == "execute":
                    recipe_tracker = getattr(self, "_recipe_tracker", None)
                    if recipe_tracker is not None:
                        r_status = (
                            "failed" if result.startswith("Error") else "completed"
                        )
                        recipe_tracker.on_recipe_complete(status=r_status)

            self._on_stream_tool_end(name, tool_input, result)

        def on_usage() -> None:
            self._on_stream_usage_update()

        # Wire to session manager
        self.session_manager.on_content_block_start = on_block_start
        self.session_manager.on_content_block_delta = on_block_delta
        self.session_manager.on_content_block_end = on_block_end
        self.session_manager.on_tool_pre = on_tool_start
        self.session_manager.on_tool_post = on_tool_end
        self.session_manager.on_usage_update = on_usage
