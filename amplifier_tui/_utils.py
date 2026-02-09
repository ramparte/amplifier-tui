"""Shared utility functions used by app.py and command mixins."""

from __future__ import annotations

from pathlib import Path

from .constants import TOOL_LABELS, _MAX_LABEL_LEN
from .log import logger
from .platform import copy_to_clipboard as _copy_to_clipboard  # noqa: F401 - re-exported


def _context_color(pct: float) -> str:
    """Return a color string for the given context-usage percentage.

    Four tiers:
      green   0-50%  – plenty of room
      yellow  50-75% – getting full
      orange  75-90% – almost full
      red     90%+   – near limit
    """
    if pct >= 90:
        return "#ff4444"
    if pct >= 75:
        return "#ff8800"
    if pct >= 50:
        return "#ffaa00"
    return "#44aa44"


def _context_color_name(pct: float) -> str:
    """Return a human-readable color *name* for context-usage percentage."""
    if pct >= 90:
        return "red"
    if pct >= 75:
        return "orange"
    if pct >= 50:
        return "yellow"
    return "green"


def _get_tool_label(name: str, tool_input: dict | str | None) -> str:
    """Map a tool name (+ optional input) to a short, human-friendly label."""
    base = TOOL_LABELS.get(name, f"Running {name}")
    inp = tool_input if isinstance(tool_input, dict) else {}

    # Add file/path context for file-related tools
    if name in ("read_file", "write_file", "edit_file"):
        path = inp.get("file_path", "")
        if path:
            short = Path(path).name
            base = f"{base.rsplit('.', 1)[0].rstrip('.')} {short}"

    elif name == "grep":
        pattern = inp.get("pattern", "")
        if pattern:
            if len(pattern) > 20:
                pattern = pattern[:17] + "..."
            base = f"Searching: {pattern}"

    elif name == "delegate":
        agent = inp.get("agent", "")
        if agent:
            short = agent.split(":")[-1] if ":" in agent else agent
            base = f"Delegating to {short}"

    elif name == "bash":
        cmd = inp.get("command", "")
        if cmd:
            first_line = cmd.split("\n", 1)[0]
            if len(first_line) > 25:
                first_line = first_line[:22] + "\u2026"
            base = f"Running: {first_line}"

    elif name == "web_fetch":
        url = inp.get("url", "")
        if url:
            try:
                from urllib.parse import urlparse

                host = urlparse(url).netloc
                if host:
                    base = f"Fetching {host}"
            except ValueError:
                logger.debug("Failed to parse URL %s", url, exc_info=True)

    elif name == "web_search":
        query = inp.get("query", "")
        if query:
            if len(query) > 20:
                query = query[:17] + "\u2026"
            base = f"Searching: {query}"

    elif name == "glob":
        pattern = inp.get("pattern", "")
        if pattern:
            if len(pattern) > 20:
                pattern = pattern[:17] + "\u2026"
            base = f"Finding: {pattern}"

    elif name == "LSP":
        op = inp.get("operation", "")
        if op:
            base = f"Analyzing: {op}"

    elif name == "python_check":
        paths = inp.get("paths")
        if paths and isinstance(paths, list) and paths[0]:
            short = Path(paths[0]).name
            base = f"Checking {short}"

    elif name == "load_skill":
        skill = inp.get("skill_name", "") or inp.get("search", "")
        if skill:
            base = f"Loading skill: {skill}"

    elif name == "todo":
        action = inp.get("action", "")
        if action:
            base = f"Planning: {action}"

    elif name == "recipes":
        op = inp.get("operation", "")
        if op:
            base = f"Recipe: {op}"

    # Truncate to keep status bar tidy, then add ellipsis
    if len(base) > _MAX_LABEL_LEN:
        base = base[: _MAX_LABEL_LEN - 1] + "\u2026"
    return f"{base}..."


# _copy_to_clipboard is imported from .platform (see top of file)
