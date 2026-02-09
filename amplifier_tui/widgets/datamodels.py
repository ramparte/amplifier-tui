"""Data models for Amplifier TUI widgets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textual.widgets import Static


@dataclass
class TabState:
    """State for a single conversation tab."""

    name: str
    tab_id: str
    container_id: str  # ScrollableContainer widget ID for this tab
    # Session state (saved/restored when switching tabs)
    sm_session: Any = None
    sm_session_id: str | None = None
    session_title: str = ""
    # Search index
    search_messages: list = field(default_factory=list)
    # Statistics
    total_words: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_call_count: int = 0
    user_words: int = 0
    assistant_words: int = 0
    response_times: list = field(default_factory=list)
    tool_usage: dict = field(default_factory=dict)
    assistant_msg_index: int = 0
    last_assistant_widget: Static | None = None
    last_assistant_text: str = ""
    # Per-session data
    session_bookmarks: list = field(default_factory=list)
    session_refs: list = field(default_factory=list)
    message_pins: list = field(default_factory=list)
    session_notes: list = field(default_factory=list)
    created_at: str = ""
    # Custom system prompt for this tab
    system_prompt: str = ""
    system_preset_name: str = ""  # name of active preset (if any)
    # Amplifier mode for this tab (planning, research, review, debug)
    active_mode: str | None = None
    # Unsent input text (preserved across tab switches)
    input_text: str = ""
    # User-assigned tab name (empty = use auto-generated `name`)
    custom_name: str = ""


@dataclass
class Attachment:
    """A file attached to the next outgoing message."""

    path: Path
    name: str  # filename
    content: str  # file text content
    language: str  # detected language for syntax highlighting
    size: int  # byte length of content
