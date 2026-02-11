"""Agent tree panel showing live delegation hierarchy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass
class AgentNode:
    """An agent in the delegation tree."""

    name: str
    status: str = "running"  # running, completed, failed
    started_at: datetime | None = None
    summary: str = ""
    children: list[AgentNode] = field(default_factory=list)


class AgentTreePanel(Widget):
    """Panel showing live agent delegation hierarchy."""

    DEFAULT_CSS = """
    AgentTreePanel {
        dock: right;
        width: 35;
        max-width: 40;
        border-left: solid $surface-lighten-2;
        background: $surface;
        display: none;
    }
    AgentTreePanel.visible {
        display: block;
    }
    AgentTreePanel .tree-title {
        text-style: bold;
        padding: 0 1;
        color: $text;
        background: $surface-lighten-1;
    }
    AgentTreePanel .agent-node {
        padding: 0 1;
    }
    AgentTreePanel .agent-running {
        color: $warning;
    }
    AgentTreePanel .agent-completed {
        color: $success;
    }
    AgentTreePanel .agent-failed {
        color: $error;
    }
    """

    visible: reactive[bool] = reactive(False)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._root_agents: list[AgentNode] = []
        self._agent_map: dict[str, AgentNode] = {}

    def compose(self) -> ComposeResult:
        yield Static("Agents", classes="tree-title")
        yield VerticalScroll(id="agent-tree-list")

    def watch_visible(self, value: bool) -> None:
        if value:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def add_agent(self, name: str, agent_id: str = "", parent_id: str = "") -> None:
        """Add a new agent node to the tree."""
        node = AgentNode(name=name, started_at=datetime.now())
        key = agent_id or name
        self._agent_map[key] = node

        if parent_id and parent_id in self._agent_map:
            self._agent_map[parent_id].children.append(node)
        else:
            self._root_agents.append(node)

        self._render_tree()

        # Auto-show when agents are delegated
        if not self.visible:
            self.visible = True

    def update_agent(self, agent_id: str, status: str, summary: str = "") -> None:
        """Update an existing agent's status."""
        key = agent_id
        if key in self._agent_map:
            self._agent_map[key].status = status
            if summary:
                self._agent_map[key].summary = summary[:100]
            self._render_tree()

    def clear(self) -> None:
        """Clear all agents (on new session/turn)."""
        self._root_agents.clear()
        self._agent_map.clear()
        self._render_tree()

    def _render_tree(self) -> None:
        """Re-render the agent tree."""
        try:
            container = self.query_one("#agent-tree-list", VerticalScroll)
        except Exception:
            return
        container.remove_children()

        if not self._root_agents:
            container.mount(Static("  No agents active", classes="agent-node"))
            return

        for node in self._root_agents:
            self._render_node(container, node, depth=0)

    def _render_node(
        self, container: VerticalScroll, node: AgentNode, depth: int
    ) -> None:
        """Render a single node and its children."""
        indent = "  " + "  " * depth

        status_indicators = {
            "running": ">",
            "completed": "x",
            "failed": "!",
        }
        indicator = status_indicators.get(node.status, "?")
        css_class = f"agent-{node.status}"

        # Truncate name for display
        max_len = 30 - depth * 2
        display_name = node.name
        if len(display_name) > max_len:
            display_name = display_name[: max_len - 3] + "..."

        line = f"{indent}[{indicator}] {display_name}"
        container.mount(Static(line, classes=f"agent-node {css_class}"))

        # Show summary for completed agents
        if node.summary:
            summary_line = f"{indent}    {node.summary[:40]}..."
            container.mount(Static(summary_line, classes="agent-node agent-completed"))

        for child in node.children:
            self._render_node(container, child, depth + 1)

    @property
    def active_count(self) -> int:
        return sum(1 for n in self._agent_map.values() if n.status == "running")
