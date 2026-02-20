"""Qt signal definitions for thread-safe backend-to-UI communication.

All signals are emitted from DesktopBackend (which may run on a background
thread) and received by DesktopApp slots on the main/GUI thread.  Qt's
signal-slot mechanism handles the cross-thread marshalling automatically.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class StreamSignals(QObject):
    """Central signal hub bridging DesktopBackend -> DesktopApp."""

    # --- Display messages (text, conversation_id) ---
    system_message = Signal(str, str)
    user_message = Signal(str, str)
    assistant_message = Signal(str, str)
    error_message = Signal(str, str)
    status_update = Signal(str, str)

    # --- Processing state ---
    processing_started = Signal(str, str)  # label, conversation_id
    processing_finished = Signal(str)  # conversation_id

    # --- Streaming content blocks ---
    block_start = Signal(str, str)  # conversation_id, block_type
    block_delta = Signal(str, str, str)  # conversation_id, block_type, accumulated_text
    block_end = Signal(
        str, str, str, bool
    )  # conversation_id, block_type, final_text, had_start

    # --- Tool execution ---
    tool_start = Signal(str, str, object)  # conversation_id, tool_name, tool_input
    tool_end = Signal(
        str, str, object, object
    )  # conversation_id, tool_name, tool_input, result

    # --- Usage / token stats ---
    usage_update = Signal(str)  # conversation_id

    # --- Session lifecycle ---
    session_list_ready = Signal(list)  # list[dict] for sidebar
    session_resumed = Signal(str, str, list)  # conversation_id, session_id, messages
    session_resume_failed = Signal(str, str)  # session_id, error_message
