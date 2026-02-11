"""Framework-agnostic conversation state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import uuid


@dataclass
class ConversationState:
    """Backend state for a single conversation (framework-agnostic).

    Extracted from TabState. Contains all per-conversation state that
    both TUI and Web frontends need. UI-specific state stays in TabState.
    """

    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Amplifier session
    session: Any = None  # was TabState.sm_session
    session_id: str | None = None  # was TabState.sm_session_id
    title: str = ""  # was TabState.session_title

    # System prompt / mode
    system_prompt: str = ""
    system_preset_name: str = ""
    active_mode: str | None = None

    # Search index (list of (role, text) tuples - no widget refs)
    search_messages: list = field(default_factory=list)

    # Statistics
    total_words: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_call_count: int = 0
    user_words: int = 0
    assistant_words: int = 0
    response_times: list[float] = field(default_factory=list)
    tool_usage: dict[str, int] = field(default_factory=dict)
    assistant_msg_index: int = 0
    last_assistant_text: str = ""

    # Annotations
    bookmarks: list = field(default_factory=list)  # was session_bookmarks
    refs: list = field(default_factory=list)  # was session_refs
    pins: list = field(default_factory=list)  # was message_pins
    notes: list = field(default_factory=list)  # was session_notes

    # Metadata
    created_at: str = ""
