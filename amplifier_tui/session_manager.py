# Re-export shim — real module lives in amplifier_tui.core.session_manager
from amplifier_tui.core.session_manager import SessionHandle, SessionManager

__all__ = ["SessionHandle", "SessionManager"]
