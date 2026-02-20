"""Desktop widgets package."""

from .chat_display import ChatDisplay
from .chat_input import ChatInput
from .find_bar import FindBar
from .panels import AgentTreePanel, ProjectPanel, TodoPanel
from .session_sidebar import SessionSidebar
from .status_bar import AmplifierStatusBar
from .tab_bar import DesktopTabState

__all__ = [
    "AgentTreePanel",
    "AmplifierStatusBar",
    "ChatDisplay",
    "ChatInput",
    "DesktopTabState",
    "FindBar",
    "ProjectPanel",
    "SessionSidebar",
    "TodoPanel",
]
