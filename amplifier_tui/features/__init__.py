"""Feature modules extracted from the monolithic app.

Stateless helpers are standalone functions; stateful features are helper
classes that own their own state and communicate with the app through
injected callbacks.

Modules
-------
git_integration
    Pure-function wrappers around ``git`` CLI commands.
export
    Pure-function converters (Markdown, text, JSON, HTML).
notifications
    Terminal bell / OSC notification helpers.
file_watch
    :class:`FileWatcher` — polls files for changes, reports diffs.
reverse_search
    :class:`ReverseSearchManager` — Ctrl+R reverse-i-search state machine.
"""

from .export import (
    export_html,
    export_json,
    export_markdown,
    export_text,
    get_export_metadata,
    html_escape,
    md_to_html,
)
from .file_watch import FileWatcher
from .diff_view import (
    diff_summary,
    format_edit_diff,
    format_new_file_diff,
    new_file_summary,
)
from .git_integration import (
    colorize_diff,
    looks_like_commit_ref,
    run_git,
    show_diff,
)
from .notifications import (
    play_bell,
    send_terminal_notification,
)
from .reverse_search import ReverseSearchManager
from .agent_tracker import AgentTracker, AgentNode, is_delegate_tool, make_delegate_key
from .context_profiler import (
    ContextBreakdown,
    ContextHistory,
    analyze_messages,
    analyze_messages_detail,
    estimate_tokens,
    format_profiler_bar,
    format_profiler_detail,
    format_profiler_history,
    format_top_consumers,
)
from .tool_log import ToolEntry, ToolLog, tool_color, summarize_tool_input
from .include_helpers import (
    file_preview,
    get_directory_tree,
    get_git_status_and_diff,
)
from .recipe_tracker import RecipeStep, RecipeRun, RecipeTracker
from .branch_manager import BranchManager, ConversationBranch

__all__ = [
    # diff_view
    "format_edit_diff",
    "format_new_file_diff",
    "diff_summary",
    "new_file_summary",
    # git
    "run_git",
    "looks_like_commit_ref",
    "colorize_diff",
    "show_diff",
    # export
    "html_escape",
    "md_to_html",
    "get_export_metadata",
    "export_markdown",
    "export_text",
    "export_json",
    "export_html",
    # notifications
    "send_terminal_notification",
    "play_bell",
    # stateful managers
    "FileWatcher",
    "ReverseSearchManager",
    "AgentTracker",
    "AgentNode",
    "is_delegate_tool",
    "make_delegate_key",
    # context profiler
    "ContextBreakdown",
    "ContextHistory",
    "analyze_messages",
    "analyze_messages_detail",
    "estimate_tokens",
    "format_profiler_bar",
    "format_profiler_detail",
    "format_profiler_history",
    "format_top_consumers",
    # tool log
    "ToolEntry",
    "ToolLog",
    "tool_color",
    "summarize_tool_input",
    # include helpers
    "get_directory_tree",
    "get_git_status_and_diff",
    "file_preview",
    # recipe tracker
    "RecipeStep",
    "RecipeRun",
    "RecipeTracker",
    # branch manager
    "BranchManager",
    "ConversationBranch",
]
