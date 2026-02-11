"""Textual-free command handler mixins (moved to core/)."""

from .agent_cmds import AgentCommandsMixin
from .branch_cmds import BranchCommandsMixin
from .compare_cmds import CompareCommandsMixin
from .content_cmds import ContentCommandsMixin
from .dashboard_cmds import DashboardCommandsMixin
from .file_cmds import FileCommandsMixin
from .git_cmds import GitCommandsMixin
from .persistence_cmds import PersistenceCommandsMixin
from .plugin_cmds import PluginCommandsMixin
from .recipe_cmds import RecipeCommandsMixin
from .replay_cmds import ReplayCommandsMixin
from .shell_cmds import ShellCommandsMixin
from .theme_cmds import ThemeCommandsMixin
from .token_cmds import TokenCommandsMixin
from .tool_cmds import ToolCommandsMixin
from .watch_cmds import WatchCommandsMixin

__all__ = [
    "AgentCommandsMixin",
    "BranchCommandsMixin",
    "CompareCommandsMixin",
    "ContentCommandsMixin",
    "DashboardCommandsMixin",
    "FileCommandsMixin",
    "GitCommandsMixin",
    "PersistenceCommandsMixin",
    "PluginCommandsMixin",
    "RecipeCommandsMixin",
    "ReplayCommandsMixin",
    "ShellCommandsMixin",
    "ThemeCommandsMixin",
    "TokenCommandsMixin",
    "ToolCommandsMixin",
    "WatchCommandsMixin",
]
