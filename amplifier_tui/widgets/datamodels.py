"""Data models for Amplifier TUI widgets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from textual.widgets import Static

from amplifier_tui.core.conversation import ConversationState


@dataclass
class TabState:
    """UI-specific state for a TUI conversation tab.

    Backend/shared conversation state lives in the embedded
    ``conversation`` field (a :class:`ConversationState`).
    """

    name: str
    tab_id: str
    container_id: str  # ScrollableContainer widget ID for this tab
    conversation: ConversationState = field(default_factory=ConversationState)

    # UI-only fields
    last_assistant_widget: Static | None = None
    input_text: str = ""  # unsent input text (preserved across tab switches)
    custom_name: str = ""  # user-assigned tab name (empty = use auto `name`)


@dataclass
class Attachment:
    """A file attached to the next outgoing message."""

    path: Path
    name: str  # filename
    content: str  # file text content
    language: str  # detected language for syntax highlighting
    size: int  # byte length of content
