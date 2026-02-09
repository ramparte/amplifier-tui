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

__all__ = [
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
]
