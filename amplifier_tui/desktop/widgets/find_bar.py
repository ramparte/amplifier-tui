"""In-chat search bar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class FindBar(QWidget):
    """Search bar for finding text in the chat display."""

    search_requested = Signal(str)  # search text
    search_next = Signal()
    search_prev = Signal()
    closed = Signal()

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search...")
        self._input.returnPressed.connect(
            lambda: self.search_requested.emit(self._input.text())
        )
        self._input.textChanged.connect(lambda t: self.search_requested.emit(t))
        layout.addWidget(self._input, 1)

        self._count_label = QLabel("")
        layout.addWidget(self._count_label)

        prev_btn = QPushButton("\u25b2")
        prev_btn.setFixedWidth(30)
        prev_btn.clicked.connect(self.search_prev.emit)
        layout.addWidget(prev_btn)

        next_btn = QPushButton("\u25bc")
        next_btn.setFixedWidth(30)
        next_btn.clicked.connect(self.search_next.emit)
        layout.addWidget(next_btn)

        close_btn = QPushButton("\u2715")
        close_btn.setFixedWidth(30)
        close_btn.clicked.connect(self._close)
        layout.addWidget(close_btn)

    def show_bar(self) -> None:
        self.setVisible(True)
        self._input.setFocus()
        self._input.selectAll()

    def _close(self) -> None:
        self.setVisible(False)
        self.closed.emit()

    def set_count(self, current: int, total: int) -> None:
        if total > 0:
            self._count_label.setText(f"{current}/{total}")
        else:
            self._count_label.setText("No results")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._close()
            return
        super().keyPressEvent(event)
