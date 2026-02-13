"""Widget classes extracted from the monolithic app module."""

from .bars import FindBar, HistorySearchBar, SuggestionBar
from .chat_input import ChatInput
from .commands import AmplifierCommandProvider
from .datamodels import Attachment, TabState
from .indicators import (
    ErrorMessage,
    FoldToggle,
    NoteMessage,
    ProcessingIndicator,
    SystemMessage,
)
from .messages import (
    AssistantMessage,
    MessageMeta,
    ThinkingBlock,
    ThinkingStatic,
    UserMessage,
)
from .panels import PinnedPanel, PinnedPanelHeader, PinnedPanelItem
from .todo_panel import TodoPanel
from .agent_tree_panel import AgentTreePanel
from .project_panel import ProjectPanel
from .screens import HistorySearchScreen, ShortcutOverlay
from .tabs import TabBar, TabButton

__all__ = [
    "AmplifierCommandProvider",
    "AssistantMessage",
    "Attachment",
    "ChatInput",
    "ErrorMessage",
    "FindBar",
    "FoldToggle",
    "HistorySearchBar",
    "HistorySearchScreen",
    "MessageMeta",
    "NoteMessage",
    "AgentTreePanel",
    "ProjectPanel",
    "PinnedPanel",
    "PinnedPanelHeader",
    "PinnedPanelItem",
    "ProcessingIndicator",
    "ShortcutOverlay",
    "SuggestionBar",
    "SystemMessage",
    "TabBar",
    "TabButton",
    "TabState",
    "ThinkingBlock",
    "ThinkingStatic",
    "TodoPanel",
    "UserMessage",
]
