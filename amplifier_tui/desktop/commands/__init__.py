"""Desktop-specific command overrides (Phase 2+)."""

from .display_cmds import DesktopDisplayCommandsMixin
from .export_cmds import DesktopExportCommandsMixin
from .search_cmds import DesktopSearchCommandsMixin
from .session_cmds import DesktopSessionCommandsMixin

__all__ = [
    "DesktopDisplayCommandsMixin",
    "DesktopExportCommandsMixin",
    "DesktopSearchCommandsMixin",
    "DesktopSessionCommandsMixin",
]
