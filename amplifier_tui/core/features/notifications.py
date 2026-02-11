"""Notification helpers (mostly stateless).

Terminal notification and bell functions that don't require app state.
Delegates to the centralized platform module for cross-platform support.
"""

from __future__ import annotations

from ..platform_info import play_bell, send_notification

# Re-export with the original name for backward compatibility
send_terminal_notification = send_notification

__all__ = ["play_bell", "send_terminal_notification"]
