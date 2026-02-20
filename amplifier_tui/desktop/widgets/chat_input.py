"""Chat input widget with slash command completion and key bindings."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QStringListModel
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QCompleter, QTextEdit

# Known slash commands (subset - populated from SharedAppBase at runtime)
DEFAULT_COMMANDS = [
    "/help",
    "/new",
    "/model",
    "/quit",
    "/system",
    "/mode",
    "/copy",
    "/undo",
    "/redo",
    "/retry",
    "/include",
    "/attach",
    "/cat",
    "/run",
    "/shell",
    "/alias",
    "/snippet",
    "/template",
    "/draft",
    "/note",
    "/bookmark",
    "/ref",
    "/tag",
    "/pin",
    "/clipboard",
    "/agents",
    "/recipe",
    "/tools",
    "/plugins",
    "/git",
    "/diff",
    "/stats",
    "/tokens",
    "/context",
    "/dashboard",
    "/history",
    "/info",
    "/compact",
    "/wrap",
    "/fold",
    "/find",
    "/export",
    "/split",
    "/tabs",
    "/close",
    "/rename",
    "/zoom",
    "/scroll",
    "/grep",
]


class ChatInput(QTextEdit):
    """Multi-line input with slash completion and key bindings."""

    submitted = Signal(str)  # emitted when user presses Enter to send

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setPlaceholderText("Type a message or /command...")
        self.setMaximumHeight(200)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(False)

        # Dynamic height
        self.document().contentsChanged.connect(self._adjust_height)
        self._min_height = 36
        self._max_height = 200
        self.setFixedHeight(self._min_height)

        # Command history
        self._history: list[str] = []
        self._history_index: int = -1
        self._history_draft: str = ""

        # Slash command completer
        self._completer = QCompleter(DEFAULT_COMMANDS, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.activated.connect(self._insert_completion)
        popup = self._completer.popup()
        if popup:
            popup.setStyleSheet(
                """
                QAbstractItemView {
                    background-color: #16213e;
                    color: #e0e0e0;
                    border: 1px solid #444;
                    selection-background-color: #0f3460;
                    font-family: "Cascadia Code", monospace;
                    font-size: 13px;
                }
            """
            )

    def set_commands(self, commands: list[str]) -> None:
        """Update the slash command list."""
        self._completer.setModel(QStringListModel(commands, self._completer))

    def set_history(self, history: list[str]) -> None:
        """Set the prompt history."""
        self._history = list(history)
        self._history_index = -1

    def _adjust_height(self) -> None:
        doc_height = self.document().size().height()
        margins = self.contentsMargins()
        new_height = min(
            int(doc_height + margins.top() + margins.bottom() + 10),
            self._max_height,
        )
        new_height = max(new_height, self._min_height)
        self.setFixedHeight(new_height)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # Handle completer popup
        popup = self._completer.popup()
        if popup and popup.isVisible():
            if event.key() in (
                Qt.Key.Key_Enter,
                Qt.Key.Key_Return,
                Qt.Key.Key_Tab,
            ):
                # Let completer handle it
                index = popup.currentIndex()
                if index.isValid():
                    completion_model = self._completer.completionModel()
                    if completion_model:
                        self._completer.activated.emit(completion_model.data(index))
                    popup.hide()
                    return
                popup.hide()
            elif event.key() == Qt.Key.Key_Escape:
                popup.hide()
                return

        # Ctrl+Enter or Cmd+Enter: always submit
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._submit()
                return
            # Shift+Enter: always newline
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            # Plain Enter: submit if single-line, newline if multiline content
            text = self.toPlainText()
            if "\n" not in text:
                self._submit()
                return
            else:
                super().keyPressEvent(event)
                return

        # Up arrow: history navigation when input is empty or cursor at start
        if event.key() == Qt.Key.Key_Up and self.toPlainText().strip() == "":
            self._history_prev()
            return

        # Down arrow: history navigation when browsing history
        if event.key() == Qt.Key.Key_Down and self._history_index >= 0:
            self._history_next()
            return

        # Escape: clear input
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            self._history_index = -1
            return

        # Default handling
        super().keyPressEvent(event)

        # Update completer after text changes
        self._update_completer()

    def _update_completer(self) -> None:
        """Show slash command completion when typing /."""
        text = self.toPlainText()
        if text.startswith("/") and "\n" not in text:
            self._completer.setCompletionPrefix(text)
            if self._completer.completionCount() > 0:
                popup = self._completer.popup()
                if popup:
                    cr = self.cursorRect()
                    cr.setWidth(
                        popup.sizeHintForColumn(0)
                        + popup.verticalScrollBar().sizeHint().width()
                        + 20
                    )
                    self._completer.complete(cr)
            else:
                popup = self._completer.popup()
                if popup:
                    popup.hide()
        else:
            popup = self._completer.popup()
            if popup:
                popup.hide()

    def _insert_completion(self, completion: str) -> None:
        """Insert the selected completion, replacing the current text."""
        self.clear()
        self.setPlainText(completion + " ")
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def _submit(self) -> None:
        text = self.toPlainText().strip()
        if text:
            # Add to history
            if not self._history or self._history[-1] != text:
                self._history.append(text)
            self._history_index = -1
            self.clear()
            self.submitted.emit(text)

    def _history_prev(self) -> None:
        if not self._history:
            return
        if self._history_index == -1:
            self._history_draft = self.toPlainText()
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self.setPlainText(self._history[self._history_index])
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def _history_next(self) -> None:
        if self._history_index < 0:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.setPlainText(self._history[self._history_index])
        else:
            self._history_index = -1
            self.setPlainText(self._history_draft)
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)
