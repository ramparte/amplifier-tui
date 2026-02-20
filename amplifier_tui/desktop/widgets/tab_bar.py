"""Tab bar and tab state for desktop conversations."""

from __future__ import annotations

from dataclasses import dataclass, field

from amplifier_tui.core.conversation import ConversationState


@dataclass
class DesktopTabState:
    """Per-tab state for the desktop frontend."""

    name: str
    tab_id: str
    conversation: ConversationState = field(default_factory=ConversationState)
    input_text: str = ""
    custom_name: str = ""
    scroll_position: int = 0
