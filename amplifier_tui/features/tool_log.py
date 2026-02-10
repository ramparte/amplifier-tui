"""Live tool introspection log (F4.1).

Tracks tool calls in a rolling buffer with timestamps, durations, and
color-coded formatting for the ``/tools`` family of commands.

This is a lightweight tracker: it captures tool name + key args, not full
payloads.  The hooks run on background threads so all methods are kept
simple and lock-free (CPython GIL is sufficient for the append/pop pattern).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ToolEntry:
    """A single tool call record."""

    tool_name: str
    summary: str  # key args, truncated
    timestamp: datetime
    duration_ms: float | None = None  # filled on completion
    status: str = "running"  # "running", "completed", "failed"


# Tool name -> Rich colour for display grouping.
TOOL_COLORS: dict[str, str] = {
    "read_file": "blue",
    "write_file": "blue",
    "edit_file": "blue",
    "glob": "blue",
    "grep": "yellow",
    "web_search": "yellow",
    "web_fetch": "yellow",
    "bash": "green",
    "delegate": "magenta",
    "task": "magenta",
    "LSP": "cyan",
    "python_check": "cyan",
    "todo": "dim",
    "recipes": "magenta",
    "load_skill": "dim",
}


def tool_color(name: str) -> str:
    """Return a Rich color token for *name*."""
    return TOOL_COLORS.get(name, "white")


# ---------------------------------------------------------------------------
# Summarisation helpers
# ---------------------------------------------------------------------------


def summarize_tool_input(tool_name: str, tool_input: dict | None) -> str:
    """Extract a short, human-readable summary of key args for display."""
    if not tool_input or not isinstance(tool_input, dict):
        return ""

    if tool_name == "read_file":
        fp = tool_input.get("file_path", "")
        parts = fp.rsplit("/", 1)
        short = parts[-1] if parts else fp
        offset = tool_input.get("offset")
        limit = tool_input.get("limit")
        if offset and limit:
            extra = f" (lines {offset}-{int(offset) + int(limit)})"
        elif offset:
            extra = f" (from line {offset})"
        else:
            extra = ""
        return f"{short}{extra}"

    if tool_name in ("write_file", "edit_file"):
        fp = tool_input.get("file_path", "")
        parts = fp.rsplit("/", 1)
        return parts[-1] if parts else fp

    if tool_name == "grep":
        pattern = tool_input.get("pattern", "")[:40]
        path = tool_input.get("path", "")
        return f'"{pattern}" in {path}' if path else f'"{pattern}"'

    if tool_name == "glob":
        return tool_input.get("pattern", "")[:50]

    if tool_name == "bash":
        return tool_input.get("command", "")[:60]

    if tool_name in ("delegate", "task"):
        agent = tool_input.get("agent", "")
        instr = tool_input.get("instruction", "")[:40]
        return f"{agent}: {instr}..." if instr else agent

    if tool_name == "web_search":
        return tool_input.get("query", "")[:50]

    if tool_name == "web_fetch":
        url = tool_input.get("url", "")
        return (url[:60] + "...") if len(url) > 60 else url

    if tool_name == "LSP":
        op = tool_input.get("operation", "")
        fp = tool_input.get("file_path", "")
        parts = fp.rsplit("/", 1)
        short = parts[-1] if parts else fp
        return f"{op} {short}"

    if tool_name == "todo":
        return tool_input.get("action", "")

    # Generic fallback: show first short string value.
    for v in tool_input.values():
        if isinstance(v, str) and v:
            return v[:50]
    return ""


# ---------------------------------------------------------------------------
# ToolLog – stateful tracker
# ---------------------------------------------------------------------------


class ToolLog:
    """Tracks tool calls for the live introspection panel.

    Maintains a rolling buffer of up to *MAX_ENTRIES* calls with per-turn
    counting and aggregate statistics.
    """

    MAX_ENTRIES = 200

    def __init__(self) -> None:
        self._entries: list[ToolEntry] = []
        self._turn_count: int = 0  # tools in current turn
        self._total_count: int = 0

    # -- hook entry points ---------------------------------------------------

    def on_tool_start(self, tool_name: str, tool_input: dict | None) -> None:
        """Record the start of a tool invocation."""
        summary = summarize_tool_input(tool_name, tool_input)
        entry = ToolEntry(
            tool_name=tool_name,
            summary=summary,
            timestamp=datetime.now(),
        )
        self._entries.append(entry)
        self._turn_count += 1
        self._total_count += 1
        # Prune oldest entries when over budget.
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES :]

    def on_tool_end(self, tool_name: str, *, status: str = "completed") -> None:
        """Mark the most recent *running* entry for *tool_name* as done."""
        # Walk backwards to find the latest running entry with a matching name.
        for entry in reversed(self._entries):
            if entry.tool_name == tool_name and entry.status == "running":
                entry.status = status
                elapsed = (datetime.now() - entry.timestamp).total_seconds() * 1000
                entry.duration_ms = elapsed
                return

    # -- turn management -----------------------------------------------------

    def reset_turn_count(self) -> None:
        self._turn_count = 0

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def entries(self) -> list[ToolEntry]:
        return list(self._entries)

    # -- formatting ----------------------------------------------------------

    def format_live_log(self, last_n: int = 25) -> str:
        """Format recent entries as Rich-markup for ``/tools`` or ``/tools live``."""
        if not self._entries:
            return "[dim]No tool calls yet[/dim]"

        lines: list[str] = []
        for entry in self._entries[-last_n:]:
            ts = entry.timestamp.strftime("%H:%M:%S")
            color = tool_color(entry.tool_name)
            name = entry.tool_name.ljust(12)
            summary = entry.summary[:60]

            if entry.status == "running":
                dur = "[yellow]running[/yellow]"
            elif entry.status == "failed":
                dur = "[red]failed[/red]"
            elif entry.duration_ms is not None:
                if entry.duration_ms < 1000:
                    dur = f"[dim]{entry.duration_ms:.0f}ms[/dim]"
                else:
                    dur = f"[dim]{entry.duration_ms / 1000:.1f}s[/dim]"
            else:
                dur = ""

            lines.append(f"[dim]{ts}[/dim] [{color}]{name}[/{color}] {summary}  {dur}")

        return "\n".join(lines)

    def format_full_log(self) -> str:
        """Format every entry for ``/tools log``."""
        if not self._entries:
            return "No tool calls in this session."

        lines: list[str] = [f"Tool Log ({len(self._entries)} calls):", ""]
        for entry in self._entries:
            color = tool_color(entry.tool_name)
            dur_str = ""
            if entry.duration_ms is not None:
                if entry.duration_ms < 1000:
                    dur_str = f" ({entry.duration_ms:.0f}ms)"
                else:
                    dur_str = f" ({entry.duration_ms / 1000:.1f}s)"
            icon = {
                "completed": "[green]\u2713[/green]",
                "failed": "[red]\u2717[/red]",
                "running": "[yellow]\u27f3[/yellow]",
            }.get(entry.status, " ")
            lines.append(
                f"  {icon} [{color}]{entry.tool_name}[/{color}]"
                f" {entry.summary}{dur_str}"
            )

        return "\n".join(lines)

    def format_stats(self) -> str:
        """Format aggregate statistics for ``/tools stats``."""
        if not self._entries:
            return "No tool calls in this session."

        counts: Counter[str] = Counter(e.tool_name for e in self._entries)
        total_time = sum(e.duration_ms or 0 for e in self._entries)

        lines: list[str] = [
            f"Tool Statistics ({self._total_count} total calls):",
            "",
        ]
        for name, count in counts.most_common(15):
            color = tool_color(name)
            bar = "\u2588" * min(count, 30)
            lines.append(f"  [{color}]{name.ljust(14)}[/{color}] {bar} {count}")
        lines.append("")
        if total_time > 0:
            lines.append(f"  Total tool time: {total_time / 1000:.1f}s")
        lines.append(f"  This turn: {self._turn_count} calls")

        return "\n".join(lines)

    # -- lifecycle -----------------------------------------------------------

    def clear(self) -> None:
        """Reset all state."""
        self._entries.clear()
        self._turn_count = 0
        self._total_count = 0
