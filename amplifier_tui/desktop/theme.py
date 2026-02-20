"""QSS dark theme and theme switching for Amplifier desktop."""

from __future__ import annotations

DARK_THEME = """
QMainWindow {
    background-color: #1a1a2e;
}
QTextBrowser {
    background-color: #16213e;
    color: #e0e0e0;
    border: none;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 14px;
    padding: 12px;
}
QTextEdit {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #333;
    border-radius: 4px;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 14px;
    padding: 8px;
}
QTabWidget::pane {
    border: none;
    background-color: #16213e;
}
QTabBar::tab {
    background-color: #16213e;
    color: #888;
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #e0e0e0;
    border-bottom: 2px solid #e94560;
}
QTabBar::tab:hover {
    color: #ccc;
}
QDockWidget {
    background-color: #16213e;
    color: #e0e0e0;
    font-size: 13px;
}
QDockWidget::title {
    background-color: #1a1a2e;
    padding: 6px;
    text-align: left;
}
QSplitter::handle {
    background-color: #333;
}
QSplitter::handle:horizontal { width: 2px; }
QSplitter::handle:vertical { height: 2px; }
QScrollBar:vertical {
    background-color: #1a1a2e;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background-color: #444;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background-color: #1a1a2e;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background-color: #444;
    border-radius: 4px;
    min-width: 20px;
}
QTreeWidget {
    background-color: #16213e;
    color: #e0e0e0;
    border: none;
    font-size: 13px;
}
QTreeWidget::item:selected {
    background-color: #0f3460;
}
QTreeWidget::item:hover {
    background-color: #1a2850;
}
QLineEdit {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 13px;
}
QLabel {
    color: #aaa;
    font-size: 12px;
}
QStatusBar {
    background-color: #1a1a2e;
    color: #888;
    font-size: 12px;
}
QMenuBar {
    background-color: #1a1a2e;
    color: #e0e0e0;
}
QMenuBar::item:selected {
    background-color: #0f3460;
}
QMenu {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #333;
}
QMenu::item:selected {
    background-color: #0f3460;
}
QCompleter QAbstractItemView {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #444;
    selection-background-color: #0f3460;
}
"""

# ---------------------------------------------------------------------------
# Inline styles for chat messages (QTextBrowser compatible)
#
# QTextBrowser only supports a small subset of CSS 2.1 and silently ignores
# class selectors on divs.  We use inline ``style=`` attributes instead.
# The left-border accent is faked via a two-column table: a narrow colored
# cell on the left and the message content on the right.
# ---------------------------------------------------------------------------


def _border_wrap(border_color: str, inner_style: str, content: str) -> str:
    """Wrap *content* in a table that simulates a left-border accent.

    QTextBrowser doesn't reliably support ``border-left`` on divs so we use a
    1-row, 2-column table: the first cell is a thin colored strip and the
    second cell holds the actual message.
    """
    return (
        '<table cellspacing="0" cellpadding="0" '
        'style="margin:8px 0; border-collapse:collapse; width:100%;">'
        "<tr>"
        f'<td style="width:3px; background-color:{border_color}; padding:0;"></td>'
        f'<td style="{inner_style}">{content}</td>'
        "</tr></table>"
    )


def inline_user(content: str) -> str:
    """Return *content* wrapped in user-message inline styling."""
    return _border_wrap(
        "#4a9eff",
        "background-color:#1a3a5c; color:#e0e0e0; padding:12px;",
        content,
    )


def inline_assistant(content: str) -> str:
    """Return *content* wrapped in assistant-message inline styling."""
    return _border_wrap(
        "#50fa7b",
        "background-color:#1e1e2e; color:#e0e0e0; padding:12px;",
        content,
    )


def inline_system(content: str) -> str:
    """Return *content* wrapped in system-message inline styling."""
    return _border_wrap(
        "#666666",
        "background-color:#1a1a2e; color:#888888; padding:8px 12px; font-style:italic;",
        content,
    )


def inline_error(content: str) -> str:
    """Return *content* wrapped in error-message inline styling."""
    return _border_wrap(
        "#ff5555",
        "background-color:#3a1a1a; color:#ff8888; padding:12px;",
        content,
    )


def inline_tool(content: str) -> str:
    """Return *content* wrapped in tool-message inline styling."""
    return _border_wrap(
        "#8be9fd",
        "background-color:#1a2a1a; color:#aaaaaa; padding:8px 12px; font-family:monospace;",
        content,
    )


def inline_thinking(content: str) -> str:
    """Return *content* wrapped in thinking-block inline styling."""
    return _border_wrap(
        "#bd93f9",
        "background-color:#1a1a2e; color:#888888; padding:8px 12px; font-style:italic;",
        content,
    )


def inline_streaming(content: str, block_type: str = "text") -> str:
    """Inline style for in-progress streaming blocks."""
    if block_type == "thinking":
        return inline_thinking(content)
    return inline_assistant(content)


# ---------------------------------------------------------------------------
# Message CSS for elements that QTextBrowser *does* handle well via <style>
# (element selectors: pre, code, table, a …).  Class selectors (.foo) are
# omitted here — they were never applied reliably.
# ---------------------------------------------------------------------------
_BASE_MESSAGE_CSS = """
pre {
    background-color: #0d1117;
    border-radius: 6px;
    padding: 12px;
    overflow-x: auto;
    font-family: "Cascadia Code", monospace;
    font-size: 13px;
}
code {
    background-color: #0d1117;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: "Cascadia Code", monospace;
    font-size: 13px;
}
table { border-collapse: collapse; margin: 8px 0; }
td, th { border: 1px solid #444; padding: 6px 10px; }
th { background-color: #1a1a2e; }
a { color: #5dade2; }
"""

# Generate syntax-highlighting CSS from pygments if available (monokai theme).
# This is appended to the base CSS so code blocks get coloured when pygments is
# installed; otherwise the CSS is simply empty and code renders unstyled.
_PYGMENTS_CSS = ""
try:
    from pygments.formatters import HtmlFormatter

    _PYGMENTS_CSS = "\n" + HtmlFormatter(style="monokai").get_style_defs(".codehilite")
except Exception:  # ImportError or any pygments issue
    pass

MESSAGE_CSS: str = _BASE_MESSAGE_CSS + _PYGMENTS_CSS


def apply_theme(app: object, theme_name: str = "dark") -> None:
    """Apply a QSS theme to the application."""
    if theme_name == "dark":
        from PySide6.QtWidgets import QApplication

        if isinstance(app, QApplication):
            app.setStyleSheet(DARK_THEME)
