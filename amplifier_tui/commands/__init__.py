"""Command handler mixins for AmplifierTuiApp."""

# Re-export shared (Textual-free) commands from core
from amplifier_tui.core.commands.agent_cmds import AgentCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.branch_cmds import BranchCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.compare_cmds import CompareCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.content_cmds import ContentCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.dashboard_cmds import DashboardCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.file_cmds import FileCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.git_cmds import GitCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.persistence_cmds import PersistenceCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.plugin_cmds import PluginCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.recipe_cmds import RecipeCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.replay_cmds import ReplayCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.shell_cmds import ShellCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.theme_cmds import ThemeCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.token_cmds import TokenCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.tool_cmds import ToolCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.project_cmds import ProjectCommandsMixin  # noqa: F401
from amplifier_tui.core.commands.watch_cmds import WatchCommandsMixin  # noqa: F401

# TUI-only commands (stay local)
from .session_cmds import SessionCommandsMixin  # noqa: F401
from .display_cmds import DisplayCommandsMixin  # noqa: F401
from .search_cmds import SearchCommandsMixin  # noqa: F401
from .export_cmds import ExportCommandsMixin  # noqa: F401
from .split_cmds import SplitCommandsMixin  # noqa: F401
from .terminal_cmds import TerminalCommandsMixin  # noqa: F401
from .monitor_cmds import MonitorCommandsMixin  # noqa: F401

__all__ = [
    "AgentCommandsMixin",
    "BranchCommandsMixin",
    "CompareCommandsMixin",
    "ContentCommandsMixin",
    "DashboardCommandsMixin",
    "DisplayCommandsMixin",
    "ExportCommandsMixin",
    "FileCommandsMixin",
    "GitCommandsMixin",
    "MonitorCommandsMixin",
    "PersistenceCommandsMixin",
    "PluginCommandsMixin",
    "ProjectCommandsMixin",
    "RecipeCommandsMixin",
    "ReplayCommandsMixin",
    "SearchCommandsMixin",
    "SessionCommandsMixin",
    "ShellCommandsMixin",
    "SplitCommandsMixin",
    "TerminalCommandsMixin",
    "ThemeCommandsMixin",
    "TokenCommandsMixin",
    "ToolCommandsMixin",
    "WatchCommandsMixin",
]
