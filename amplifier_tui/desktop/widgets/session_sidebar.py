"""Collapsible session browser sidebar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SessionSidebar(QWidget):
    """Session browser with filter and grouping."""

    session_selected = Signal(str)  # session_id

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("Filter sessions...")
        self._filter_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._filter_input)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Session", "Date"])
        self._tree.setColumnWidth(0, 180)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree)

        self._sessions: list[dict] = []

    def set_sessions(self, sessions: list[dict]) -> None:
        """Populate with session list.

        Each dict has: session_id, title, date, project.
        """
        self._sessions = sessions
        self._rebuild_tree()

    def _rebuild_tree(self, filter_text: str = "") -> None:
        self._tree.clear()
        ft = filter_text.lower()

        # Group by category (simplified: all go to "Recent" for now)
        groups: dict[str, list[dict]] = {}
        for s in self._sessions:
            title = s.get("title", s.get("session_id", "")[:8])
            if (
                ft
                and ft not in title.lower()
                and ft not in s.get("project", "").lower()
            ):
                continue
            groups.setdefault("Recent", []).append(s)

        for group_name, items in groups.items():
            if not items:
                continue
            group_item = QTreeWidgetItem([group_name, ""])
            group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for s in items:
                title = s.get("title", s.get("session_id", "")[:8])
                date = s.get("date", "")
                child = QTreeWidgetItem([title, date])
                child.setData(0, Qt.ItemDataRole.UserRole, s.get("session_id", ""))
                group_item.addChild(child)
            self._tree.addTopLevelItem(group_item)
            group_item.setExpanded(True)

    def _on_filter_changed(self, text: str) -> None:
        self._rebuild_tree(text)

    def _on_item_double_clicked(
        self,
        item: QTreeWidgetItem,
        column: int,  # noqa: ARG002
    ) -> None:
        session_id = item.data(0, Qt.ItemDataRole.UserRole)
        if session_id:
            self.session_selected.emit(session_id)
