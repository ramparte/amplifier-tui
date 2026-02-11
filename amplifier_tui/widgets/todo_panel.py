"""Live todo panel that shows agent's task tracking state."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass
class TodoItem:
    """A single todo item."""

    content: str
    status: str  # pending, in_progress, completed
    active_form: str = ""


class TodoPanel(Widget):
    """Panel showing agent's live todo state."""

    DEFAULT_CSS = """
    TodoPanel {
        dock: right;
        width: 35;
        max-width: 40;
        border-left: solid $surface-lighten-2;
        background: $surface;
        display: none;
    }
    TodoPanel.visible {
        display: block;
    }
    TodoPanel .todo-title {
        text-style: bold;
        padding: 0 1;
        color: $text;
        background: $surface-lighten-1;
    }
    TodoPanel .todo-item {
        padding: 0 1;
        margin: 0;
    }
    TodoPanel .todo-completed {
        color: $text-muted;
        text-style: strike;
    }
    TodoPanel .todo-in-progress {
        color: $warning;
        text-style: bold;
    }
    TodoPanel .todo-pending {
        color: $text-disabled;
    }
    """

    visible: reactive[bool] = reactive(False)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._items: list[TodoItem] = []

    def compose(self) -> ComposeResult:
        yield Static("Tasks", classes="todo-title")
        yield VerticalScroll(id="todo-list")

    def watch_visible(self, value: bool) -> None:
        if value:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def update_todos(self, tool_input: dict) -> None:
        """Update from a todo tool call."""
        action = tool_input.get("action", "")
        if action in ("create", "update"):
            todos_data = tool_input.get("todos", [])
            self._items = []
            for item in todos_data:
                self._items.append(
                    TodoItem(
                        content=item.get("content", ""),
                        status=item.get("status", "pending"),
                        active_form=item.get("activeForm", ""),
                    )
                )
            self._render_items()
        elif action == "list":
            pass  # Don't update display on list queries

    def _render_items(self) -> None:
        """Re-render the todo list."""
        try:
            container = self.query_one("#todo-list", VerticalScroll)
        except Exception:
            return
        container.remove_children()

        if not self._items:
            container.mount(Static("  No tasks", classes="todo-item todo-pending"))
            return

        for item in self._items:
            if item.status == "completed":
                prefix = "[x]"
                css_class = "todo-completed"
            elif item.status == "in_progress":
                prefix = "[>]"
                css_class = "todo-in-progress"
            else:
                prefix = "[ ]"
                css_class = "todo-pending"

            # Truncate long content for the panel
            text = item.content
            if len(text) > 50:
                text = text[:47] + "..."

            container.mount(
                Static(f"  {prefix} {text}", classes=f"todo-item {css_class}")
            )

        # Auto-show when items arrive
        if self._items and not self.visible:
            self.visible = True

    @property
    def item_count(self) -> int:
        return len(self._items)

    @property
    def completed_count(self) -> int:
        return sum(1 for i in self._items if i.status == "completed")
