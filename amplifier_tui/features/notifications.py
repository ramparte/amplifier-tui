"""Notification helpers (mostly stateless).

Terminal notification and bell functions that don't require app state.
"""

from __future__ import annotations

import sys

from ..log import logger


def send_terminal_notification(title: str, body: str = "") -> None:
    """Send a terminal notification via OSC escape sequences.

    Uses multiple methods for broad terminal compatibility:
    - OSC 9: iTerm2, WezTerm, kitty
    - OSC 777: rxvt-unicode
    - BEL: universal fallback (triggers terminal bell / visual bell)

    Writes to sys.__stdout__ to bypass Textual's stdout capture.
    """
    out = sys.__stdout__
    if out is None:
        return
    try:
        out.write(f"\033]9;{title}: {body}\a")
        out.write(f"\033]777;notify;{title};{body}\a")
        out.write("\a")
        out.flush()
    except OSError:
        logger.debug("Terminal notification write failed", exc_info=True)


def play_bell() -> None:
    """Write BEL character to the real terminal via *sys.__stdout__*.

    Textual captures ``sys.stdout``, so we use the original fd directly.
    """
    out = sys.__stdout__
    if out is None:
        return
    try:
        out.write("\a")
        out.flush()
    except OSError:
        logger.debug("Terminal bell write failed", exc_info=True)
