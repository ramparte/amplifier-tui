"""Chat display widget with markdown rendering and streaming support."""

from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPushButton, QTextBrowser

from amplifier_tui.desktop.theme import (
    inline_assistant,
    inline_error,
    inline_system,
    inline_thinking,
    inline_tool,
    inline_user,
)


class ChatDisplay(QTextBrowser):
    """Rich text chat display with markdown rendering."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.verticalScrollBar().setSingleStep(20)

        # Streaming state
        self._streaming_block_id: str | None = None
        self._streaming_block_start: int | None = None
        self._streaming_block_end: int | None = None
        self._auto_scroll = True

        # Track scroll position for auto-scroll behavior
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # --- Jump-to-bottom floating button ---
        self._jump_btn = QPushButton("\u2193 Jump to bottom", self)
        self._jump_btn.setFixedHeight(28)
        self._jump_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._jump_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: rgba(15, 52, 96, 200);"
            "  color: #e0e0e0;"
            "  border: 1px solid #444;"
            "  border-radius: 14px;"
            "  padding: 4px 16px;"
            "  font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "  background-color: rgba(15, 52, 96, 240);"
            "}"
        )
        self._jump_btn.clicked.connect(self._force_scroll_to_bottom)
        self._jump_btn.hide()

    # ----------------------------------------------------------------
    # Scroll helpers
    # ----------------------------------------------------------------

    def _should_auto_scroll(self) -> bool:
        sb = self.verticalScrollBar()
        return sb.value() >= sb.maximum() - 50

    def _on_scroll(self) -> None:
        self._auto_scroll = self._should_auto_scroll()
        self._jump_btn.setVisible(not self._auto_scroll)

    def _scroll_to_bottom(self) -> None:
        if self._auto_scroll:
            sb = self.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _force_scroll_to_bottom(self) -> None:
        """Scroll to bottom unconditionally (jump-to-bottom button click)."""
        self._auto_scroll = True
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._jump_btn.hide()

    def _reposition_jump_btn(self) -> None:
        """Place the jump button at the bottom-right of the viewport."""
        margin = 12
        btn = self._jump_btn
        vp = self.viewport()
        x = vp.width() - btn.sizeHint().width() - margin
        y = vp.height() - btn.height() - margin
        btn.move(max(0, x), max(0, y))

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._reposition_jump_btn()

    def showEvent(self, event: object) -> None:  # noqa: N802
        super().showEvent(event)  # type: ignore[arg-type]
        self._reposition_jump_btn()

    # ----------------------------------------------------------------
    # Message display methods
    # ----------------------------------------------------------------

    def add_user_message(self, text: str) -> None:
        rendered = render_markdown(text)
        self.append(inline_user(f"<b>You</b><br>{rendered}"))
        self._scroll_to_bottom()

    def add_assistant_message(self, text: str) -> None:
        rendered = render_markdown(text)
        self.append(inline_assistant(rendered))
        self._scroll_to_bottom()

    def add_system_message(self, text: str) -> None:
        rendered = render_markdown(text)
        self.append(inline_system(rendered))
        self._scroll_to_bottom()

    def add_error_message(self, text: str) -> None:
        escaped = html.escape(text)
        self.append(inline_error(f"<b>Error</b><br>{escaped}"))
        self._scroll_to_bottom()

    def add_tool_message(self, name: str, detail: str = "") -> None:
        escaped_name = html.escape(name)
        escaped_detail = html.escape(detail)[:200] if detail else ""
        content = f"<b>Tool:</b> {escaped_name}"
        if escaped_detail:
            content += f"<br><small>{escaped_detail}</small>"
        self.append(inline_tool(content))
        self._scroll_to_bottom()

    def add_thinking_message(self, text: str) -> None:
        """Render thinking content -- dimmed, italic, smaller with [Thinking] prefix."""
        escaped = html.escape(text).replace("\n", "<br>")
        self.append(
            inline_thinking(
                f'<span style="color:#888;font-size:11px;">[Thinking]</span> {escaped}'
            )
        )
        self._scroll_to_bottom()

    def add_tool_start_message(self, tool_name: str, tool_id: str = "") -> None:
        """Render tool invocation start with wrench icon and monospace name."""
        escaped_name = html.escape(tool_name)
        id_part = ""
        if tool_id:
            escaped_id = html.escape(tool_id)[:60]
            id_part = f' <span style="color:#777;">({escaped_id})</span>'
        self.append(
            inline_tool(
                f"\U0001f527 <code>{escaped_name}</code>{id_part} <i>running...</i>"
            )
        )
        self._scroll_to_bottom()

    def add_tool_end_message(self, tool_name: str, result_preview: str = "") -> None:
        """Render tool completion with wrench icon and result preview."""
        escaped_name = html.escape(tool_name)
        preview = html.escape(result_preview)[:200] if result_preview else "done"
        self.append(
            inline_tool(
                f"\U0001f527 <code>{escaped_name}</code> "
                f'<span style="color:#4a9;">\u2713</span>'
                f"<br><small>{preview}</small>"
            )
        )
        self._scroll_to_bottom()

    # ----------------------------------------------------------------
    # Streaming support
    # ----------------------------------------------------------------

    def start_streaming_block(self, block_type: str) -> None:
        """Begin a new streaming block.  Track by block number (paragraph)."""
        self._streaming_block_id = block_type
        label = "<i>Thinking...</i>" if block_type == "thinking" else "..."
        if block_type == "thinking":
            self.append(inline_thinking(label))
        else:
            self.append(inline_assistant(label))
        self._streaming_block_start = self.document().blockCount() - 1
        self._streaming_block_end = self.document().blockCount() - 1
        self._scroll_to_bottom()

    def _select_streaming_block(self) -> QTextCursor | None:
        """Return a cursor selecting the current streaming block range, or None."""
        if self._streaming_block_start is None:
            return None
        doc = self.document()
        start_block = doc.findBlockByNumber(self._streaming_block_start)
        if not start_block.isValid():
            return None
        cursor = QTextCursor(start_block)
        # Select from start to end of the streaming range only (not EOF)
        end_num = self._streaming_block_end or self._streaming_block_start
        end_block = doc.findBlockByNumber(end_num)
        if end_block.isValid():
            end_cursor = QTextCursor(end_block)
            end_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cursor.setPosition(end_cursor.position(), QTextCursor.MoveMode.KeepAnchor)
        else:
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
            )
        return cursor

    def update_streaming_block(self, text: str, block_type: str = "text") -> None:
        """Update the current streaming block with new accumulated text.

        During streaming, render as escaped plain text for performance.
        Full markdown render happens on block_end.
        """
        if self._streaming_block_start is None:
            self.start_streaming_block(block_type)

        escaped = html.escape(text).replace("\n", "<br>")
        if block_type == "thinking":
            styled = inline_thinking(escaped)
        else:
            styled = inline_assistant(escaped)

        cursor = self._select_streaming_block()
        if cursor is not None:
            cursor.removeSelectedText()
            cursor.insertHtml(styled)
            # Update end marker after content insertion
            self._streaming_block_end = self.document().blockCount() - 1

        self._scroll_to_bottom()

    def end_streaming_block(self, final_text: str, block_type: str = "text") -> None:
        """Finalize the streaming block with full markdown render."""
        # Remove the transient streaming content
        cursor = self._select_streaming_block()
        if cursor is not None:
            cursor.removeSelectedText()

        # Append the final, fully-rendered version
        if block_type == "thinking":
            self.add_thinking_message(final_text)
        else:
            rendered = render_markdown(final_text)
            self.append(inline_assistant(rendered))

        self._streaming_block_id = None
        self._streaming_block_start = None
        self._streaming_block_end = None
        self._scroll_to_bottom()

    def clear_chat(self) -> None:
        self.clear()


def render_markdown(text: str) -> str:
    """Convert markdown text to HTML.

    Uses the markdown library if available, falls back to basic conversion.
    Adds syntax highlighting via pygments when available.
    """
    try:
        import markdown
        from markdown.extensions.fenced_code import FencedCodeExtension

        extensions: list = [
            "tables",
        ]

        # Use CodeHilite + pygments for syntax highlighting if available
        try:
            import pygments  # noqa: F401
            from markdown.extensions.codehilite import CodeHiliteExtension

            extensions.append(
                CodeHiliteExtension(
                    pygments_style="monokai",
                    noclasses=False,
                    linenums=False,
                )
            )
            extensions.append(FencedCodeExtension())
        except ImportError:
            # pygments not installed -- plain fenced code blocks
            extensions.append(FencedCodeExtension())

        md = markdown.Markdown(extensions=extensions)
        return md.convert(text)
    except ImportError:
        # Fallback: basic HTML escaping with minimal formatting
        escaped = html.escape(text)
        escaped = escaped.replace("\n", "<br>")
        # Bold
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        # Inline code
        escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
        return escaped
