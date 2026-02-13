"""Projector project panel widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from amplifier_tui.core.features.projector_client import PROJECT_STATUS_ICONS


class ProjectItem(Static):
    """A single project in the panel."""

    DEFAULT_CSS = """
    ProjectItem {
        padding: 0 1;
        height: auto;
    }
    ProjectItem:hover {
        background: $surface-lighten-1;
    }
    """

    def __init__(self, name: str, status: str, task_count: int, **kwargs):
        self._project_name = name
        self._status = status
        self._task_count = task_count
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        icon = PROJECT_STATUS_ICONS.get(self._status, " ")
        tasks = f" [{self._task_count} tasks]" if self._task_count > 0 else ""
        yield Static(f"[{icon}] {self._project_name}{tasks}")


class ProjectPanel(Widget):
    """Right-docked panel showing Projector projects and strategies."""

    DEFAULT_CSS = """
    ProjectPanel {
        dock: right;
        width: 40;
        display: none;
        border-left: solid $surface-lighten-2;
        background: $surface;
    }
    ProjectPanel.visible {
        display: block;
    }
    ProjectPanel .panel-title {
        text-style: bold;
        padding: 0 1;
        color: $text;
        background: $surface-lighten-1;
    }
    ProjectPanel .section-header {
        text-style: bold;
        padding: 1 1 0 1;
        color: $text-muted;
    }
    ProjectPanel .strategy-item {
        padding: 0 1 0 2;
        color: $text-muted;
    }
    """

    visible: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("Projector", classes="panel-title")
        yield VerticalScroll(id="project-panel-content")

    def watch_visible(self, value: bool) -> None:
        if value:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def update_projects(self, projects: list, strategies: list) -> None:
        """
        Refresh the panel content.

        Args:
            projects: list of ProjectorProject dataclass instances
            strategies: list of ProjectorStrategy dataclass instances
        """
        try:
            container = self.query_one("#project-panel-content", VerticalScroll)
        except NoMatches:
            return

        container.remove_children()

        # Projects section
        container.mount(Static("Projects", classes="section-header"))
        if not projects:
            container.mount(Static("  No projects found", classes="strategy-item"))
        for proj in projects:
            container.mount(
                ProjectItem(
                    name=proj.name,
                    status=proj.status,
                    task_count=proj.task_count,
                )
            )

        # Strategies section
        container.mount(Static("Strategies", classes="section-header"))
        if not strategies:
            container.mount(Static("  No strategies found", classes="strategy-item"))
        for strat in strategies:
            tag = "on" if strat.active else "off"
            container.mount(
                Static(
                    f"  [{tag}] {strat.name}",
                    classes="strategy-item",
                )
            )
