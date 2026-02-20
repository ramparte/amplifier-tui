"""Dockable side panels: Todo, Agent Tree, Project."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AmplifierDockPanel(QDockWidget):
    """Base for right-side dock panels."""

    def __init__(self, title: str, parent: object = None) -> None:
        super().__init__(title, parent)  # type: ignore[arg-type]
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.setMinimumWidth(250)
        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self.setWidget(self._content)


class TodoPanel(AmplifierDockPanel):
    """Displays todo items from the todo tool."""

    def __init__(self, parent: object = None) -> None:
        super().__init__("Todo", parent)
        self._items: list[dict] = []
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Status", "Task"])
        self._tree.setColumnWidth(0, 60)
        self._layout.addWidget(self._tree)

    def update_todos(self, items: list[dict]) -> None:
        self._items = items
        self._tree.clear()
        for item in items:
            status = item.get("status", "pending")
            content = item.get("content", "")
            active = item.get("activeForm", "")

            icon = {
                "completed": "\u2713",
                "in_progress": "\u2192",
                "pending": "\u2610",
            }.get(status, "?")
            display = active if status == "in_progress" and active else content

            tree_item = QTreeWidgetItem([icon, display])
            if status == "completed":
                from PySide6.QtGui import QColor

                tree_item.setForeground(1, QColor("#666"))
            self._tree.addTopLevelItem(tree_item)


class AgentTreePanel(AmplifierDockPanel):
    """Displays agent delegation tree."""

    def __init__(self, parent: object = None) -> None:
        super().__init__("Agents", parent)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Agent", "Status"])
        self._tree.setColumnWidth(0, 180)
        self._layout.addWidget(self._tree)
        self._agent_items: dict[str, QTreeWidgetItem] = {}

    def add_agent(
        self,
        name: str,
        parent_name: str | None = None,
        status: str = "running",
    ) -> None:
        icon = {"running": "\u23f3", "completed": "\u2713", "failed": "\u2717"}.get(
            status, "?"
        )
        item = QTreeWidgetItem([name, icon])

        if parent_name and parent_name in self._agent_items:
            self._agent_items[parent_name].addChild(item)
        else:
            self._tree.addTopLevelItem(item)

        # Use a unique key to avoid clobbering duplicate agent names
        key = name
        counter = 2
        while key in self._agent_items:
            key = f"{name}#{counter}"
            counter += 1
        self._agent_items[key] = item
        self._tree.expandAll()

    def update_agent_status(self, name: str, status: str) -> None:
        if name in self._agent_items:
            icon = {"running": "\u23f3", "completed": "\u2713", "failed": "\u2717"}.get(
                status, "?"
            )
            self._agent_items[name].setText(1, icon)

    def clear_agents(self) -> None:
        self._tree.clear()
        self._agent_items.clear()


class ProjectPanel(AmplifierDockPanel):
    """Shows Projector projects and tasks."""

    def __init__(self, parent: object = None) -> None:
        super().__init__("Projects", parent)
        self._info_label = QLabel("No project loaded")
        self._info_label.setWordWrap(True)
        self._layout.addWidget(self._info_label)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Task", "Status"])
        self._layout.addWidget(self._tree)

    def set_project(self, name: str, tasks: list[dict] | None = None) -> None:
        self._info_label.setText(f"Project: {name}")
        self._tree.clear()
        if tasks:
            for task in tasks:
                item = QTreeWidgetItem(
                    [task.get("content", ""), task.get("status", "")]
                )
                self._tree.addTopLevelItem(item)
