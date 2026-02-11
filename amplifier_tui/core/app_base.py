"""Shared application base class for TUI and Web frontends."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
