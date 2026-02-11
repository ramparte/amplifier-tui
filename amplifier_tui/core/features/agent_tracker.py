"""Agent delegation tree tracker.

Tracks when the AI spawns sub-agents via the ``delegate`` or ``task`` tool,
building a tree of parent → child relationships with timing and status info.

This is a best-effort tracker: if tool_use_id matching fails, operations
are silently skipped rather than raising errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AgentNode:
    """A single agent delegation in the tree."""

    agent_name: str
    instruction: str  # first 200 chars
    status: str  # "running", "completed", "failed"
    start_time: float  # monotonic timestamp
    end_time: float | None = None
    result_preview: str = ""  # first 200 chars of result
    children: list[AgentNode] = field(default_factory=list)
    tool_use_id: str = ""  # to correlate start ↔ end


_STATUS_ICONS: dict[str, tuple[str, str]] = {
    "running": ("⟳", "yellow"),
    "completed": ("✓", "green"),
    "failed": ("✗", "red"),
}

_DELEGATE_TOOL_NAMES = frozenset({"delegate", "task"})


def is_delegate_tool(tool_name: str) -> bool:
    """Return True if *tool_name* is a delegation tool."""
    return tool_name in _DELEGATE_TOOL_NAMES


def make_delegate_key(tool_input: dict | str | None) -> str:
    """Derive a stable matching key from delegate tool_input.

    Since the live hook callbacks don't expose ``tool_use_id``, we build a
    synthetic key from the agent name + instruction prefix so that
    ``on_delegate_start`` and ``on_delegate_complete`` can be correlated.
    """
    if not isinstance(tool_input, dict):
        return ""
    agent = tool_input.get("agent", "")
    instruction = tool_input.get("instruction", "")[:100]
    return f"{agent}:{instruction}"


class AgentTracker:
    """Track agent delegations and render a tree view.

    The tracker is entirely in-memory; nothing is persisted.  It hooks into
    the existing ``on_tool_pre`` / ``on_tool_post`` callbacks by checking
    whether the tool name is ``delegate`` or ``task``.
    """

    def __init__(self) -> None:
        self._roots: list[AgentNode] = []
        self._active: dict[str, AgentNode] = {}  # tool_use_id → running node
        self._completed_count: int = 0
        self._failed_count: int = 0

    # -- Public mutation API --------------------------------------------------

    def on_delegate_start(
        self,
        tool_use_id: str,
        agent: str,
        instruction: str,
    ) -> None:
        """Record a new delegation.  Called when a delegate tool_use fires."""
        node = AgentNode(
            agent_name=agent or "unknown",
            instruction=(instruction[:200] + "…")
            if len(instruction) > 200
            else instruction,
            status="running",
            start_time=time.monotonic(),
            tool_use_id=tool_use_id,
        )
        self._roots.append(node)
        if tool_use_id:
            self._active[tool_use_id] = node

    def on_delegate_complete(
        self,
        tool_use_id: str,
        result: str = "",
        status: str = "completed",
    ) -> None:
        """Mark a delegation as finished.  Best-effort: skips if ID unknown."""
        node = self._active.pop(tool_use_id, None)
        if node is None:
            return
        node.status = status
        node.end_time = time.monotonic()
        node.result_preview = (result[:200] + "…") if len(result) > 200 else result
        if status == "completed":
            self._completed_count += 1
        else:
            self._failed_count += 1

    def clear(self) -> None:
        """Reset all tracking state."""
        self._roots.clear()
        self._active.clear()
        self._completed_count = 0
        self._failed_count = 0

    # -- Read-only queries ----------------------------------------------------

    @property
    def total(self) -> int:
        return len(self._roots)

    @property
    def running_count(self) -> int:
        return len(self._active)

    @property
    def completed_count(self) -> int:
        return self._completed_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    @property
    def has_delegations(self) -> bool:
        return bool(self._roots)

    # -- Rendering ------------------------------------------------------------

    def format_tree(self) -> str:
        """Return a Rich-markup formatted tree of all delegations."""
        if not self._roots:
            return "No agent delegations in this session."
        lines: list[str] = ["Agent Delegations:"]
        for node in self._roots:
            lines.append(self._format_node(node, indent=1))
            for child in node.children:
                lines.append(self._format_node(child, indent=2))
        return "\n".join(lines)

    def format_summary(self) -> str:
        """One-line summary of delegation activity."""
        if not self._roots:
            return "No agent delegations."
        parts: list[str] = [f"{self.total} agent(s)"]
        if self._completed_count:
            parts.append(f"{self._completed_count} completed")
        if self._failed_count:
            parts.append(f"{self._failed_count} failed")
        if self.running_count:
            parts.append(f"{self.running_count} running")

        total_time = self._total_elapsed()
        if total_time > 0:
            parts.append(f"{total_time:.1f}s total")

        return "Summary: " + ", ".join(parts)

    # -- Internals ------------------------------------------------------------

    @staticmethod
    def _format_node(node: AgentNode, indent: int = 1) -> str:
        icon, color = _STATUS_ICONS.get(node.status, ("?", "dim"))
        prefix = "  " * indent

        # Truncate instruction for display
        instr = node.instruction
        if len(instr) > 60:
            instr = instr[:57] + "..."
        instr_display = f'"{instr}"'

        # Timing
        if node.end_time is not None:
            elapsed = node.end_time - node.start_time
            timing = f"{elapsed:.1f}s"
        else:
            elapsed = time.monotonic() - node.start_time
            timing = f"{elapsed:.0f}s running"

        return f"{prefix}[{color}]{icon}[/{color}] {node.agent_name}  {instr_display}  [{timing}]"

    def _total_elapsed(self) -> float:
        """Sum of elapsed times for all completed nodes."""
        total = 0.0
        for node in self._roots:
            if node.end_time is not None:
                total += node.end_time - node.start_time
            for child in node.children:
                if child.end_time is not None:
                    total += child.end_time - child.start_time
        return total
