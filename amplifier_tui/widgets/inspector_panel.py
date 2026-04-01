"""Inspector panel widget for the Session Cockpit.

Three sub-areas:
1. Block detail area -- full content of current/pinned block
2. Status line -- displays mode and position
3. Input area -- TextArea for steering/ask commands

Modes:
- LIVE: follows the currently streaming block
- PINNED: locked to a specific block (from click or /prev /next)
- ASK: showing side session response
"""

from __future__ import annotations

from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.widgets import Static, TextArea

from amplifier_tui.models.block_model import BlockInfo, BlockRegistry, BlockType


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class InspectorSteerRequest(Message):
    """Inspector requests a steering message be sent to the main session."""

    bubble = True

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class InspectorAskRequest(Message):
    """Inspector requests a /ask query sent to the side session."""

    bubble = True

    def __init__(self, question: str, block_info: BlockInfo | None) -> None:
        super().__init__()
        self.question = question
        self.block_info = block_info


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

_INSPECTOR_CSS = """\
InspectorPanel {
    height: 1fr;
    border-left: solid $accent;
    background: $surface;
}

#inspector-detail {
    height: 1fr;
    overflow-y: auto;
    padding: 0 1;
}

#inspector-status {
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 1;
}

#inspector-input {
    min-height: 1;
    max-height: 3;
    border-top: solid $secondary;
}
"""


class InspectorPanel(Vertical):
    """Inspector panel for block detail, steering, and side session queries.

    Args:
        block_registry: Reference to the CockpitApp's BlockRegistry.
    """

    DEFAULT_CSS = _INSPECTOR_CSS

    def __init__(
        self,
        block_registry: BlockRegistry,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._registry = block_registry
        self._mode: str = "live"  # "live", "pinned", "ask"
        self._current_block_id: int | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        """Current mode: 'live', 'pinned', or 'ask'."""
        return self._mode

    @property
    def current_block_id(self) -> int | None:
        """Currently displayed block ID."""
        return self._current_block_id

    @property
    def current_block(self) -> BlockInfo | None:
        """Currently displayed BlockInfo, or None."""
        if self._current_block_id is not None:
            return self._registry.get_by_id(self._current_block_id)
        return None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self):
        yield ScrollableContainer(id="inspector-detail")
        yield Static("[LIVE] No block selected", id="inspector-status")
        yield TextArea("", id="inspector-input")

    def on_mount(self) -> None:
        self._update_status_line()

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    def pin_to_block(self, block_id: int) -> None:
        """Pin the inspector to a specific block."""
        self._mode = "pinned"
        self._current_block_id = block_id
        self._display_block(block_id)
        self._update_status_line()

    def set_live_mode(self) -> None:
        """Return to live mode (follow latest block)."""
        self._mode = "live"
        last = self._registry.last
        if last:
            self._current_block_id = last.block_id
            self._display_block(last.block_id)
        self._update_status_line()

    def follow_latest(self) -> None:
        """In live mode, update to show the latest block."""
        if self._mode != "live":
            return
        last = self._registry.last
        if last and last.block_id != self._current_block_id:
            self._current_block_id = last.block_id
            self._display_block(last.block_id)
            self._update_status_line()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def go_prev(self) -> None:
        """Navigate to the previous block."""
        if self._current_block_id is None:
            return
        prev = self._registry.prev_block(self._current_block_id)
        if prev:
            self._mode = "pinned"
            self._current_block_id = prev.block_id
            self._display_block(prev.block_id)
            self._update_status_line()

    def go_next(self) -> None:
        """Navigate to the next block."""
        if self._current_block_id is None:
            return
        nxt = self._registry.next_block(self._current_block_id)
        if nxt:
            self._mode = "pinned"
            self._current_block_id = nxt.block_id
            self._display_block(nxt.block_id)
            self._update_status_line()

    def search_blocks(self, term: str, *, forward: bool = False) -> None:
        """Search blocks by summary and navigate to the result."""
        result = self._registry.search(
            term, forward=forward, from_id=self._current_block_id
        )
        if result:
            self._mode = "pinned"
            self._current_block_id = result.block_id
            self._display_block(result.block_id)
            self._update_status_line()
        else:
            self._set_detail_content(f"No match for: {term}")

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _display_block(self, block_id: int) -> None:
        """Render a block's content in the detail area."""
        block = self._registry.get_by_id(block_id)
        if block is None:
            self._set_detail_content("[STALE] Block not found")
            return
        content = (
            f"Block {block.block_id} | {block.block_type.value} | Turn {block.turn_index}\n"
            f"{'=' * 40}\n"
            f"{block.summary}"
        )
        self._set_detail_content(content)

    def _set_detail_content(self, text: str) -> None:
        """Replace the detail area content."""
        try:
            detail = self.query_one("#inspector-detail", ScrollableContainer)
            for child in list(detail.children):
                child.remove()
            detail.mount(Static(text))
        except Exception:
            pass

    def display_ask_response(self, response: str) -> None:
        """Show a /ask response in the detail area."""
        self._mode = "ask"
        self._set_detail_content(response)
        self._update_status_line()

    def _update_status_line(self) -> None:
        """Update the status line based on current mode and position."""
        try:
            status = self.query_one("#inspector-status", Static)
        except Exception:
            return

        total = len(self._registry)
        pos = (self._current_block_id + 1) if self._current_block_id is not None else 0
        block = self.current_block

        if self._mode == "live":
            block_desc = block.block_type.value if block else "..."
            status.update(f"[LIVE] {block_desc} (block {pos}/{total})")
        elif self._mode == "pinned":
            block_desc = f"{block.block_type.value}: {block.summary[:30]}" if block else "..."
            status.update(f"[PINNED] {block_desc} (block {pos}/{total})")
        elif self._mode == "ask":
            status.update("[ASK] response shown")
        else:
            status.update(f"[{self._mode.upper()}]")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def handle_input(self, text: str) -> None:
        """Process input from the inspector input area.

        Routing:
        - /ask question  -> InspectorAskRequest (side session)
        - /steer text    -> InspectorSteerRequest (main session)
        - /prev          -> navigate to previous block
        - /next          -> navigate to next block
        - /search term   -> search backward
        - /search forward term -> search forward
        - /help          -> show inspector commands
        - Free text      -> InspectorSteerRequest (default action)
        """
        text = text.strip()
        if not text:
            return

        if text.startswith("/ask "):
            question = text[5:].strip()
            if question:
                self.post_message(
                    InspectorAskRequest(question, self.current_block)
                )
        elif text.startswith("/steer "):
            steer_text = text[7:].strip()
            if steer_text:
                self.post_message(InspectorSteerRequest(steer_text))
        elif text == "/prev":
            self.go_prev()
        elif text == "/next":
            self.go_next()
        elif text.startswith("/search forward "):
            term = text[16:].strip()
            if term:
                self.search_blocks(term, forward=True)
        elif text.startswith("/search "):
            term = text[8:].strip()
            if term:
                self.search_blocks(term)
        elif text == "/help":
            self._show_help()
        else:
            # Default: steer
            self.post_message(InspectorSteerRequest(text))

    def _show_help(self) -> None:
        """Show inspector command help in the detail area."""
        help_text = (
            "Inspector Commands:\n"
            "  (free text)          Steer main session (default)\n"
            "  /steer text          Same as free text (explicit)\n"
            "  /ask question        Ask side LLM about current block\n"
            "  /prev                Previous block\n"
            "  /next                Next block\n"
            "  /search term         Search backward\n"
            "  /search forward term Search forward\n"
            "  /help                Show this help"
        )
        self._set_detail_content(help_text)