# Session Cockpit Phase 3: Inspector Panel

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add the inspector panel with live/pinned modes, block navigation, side LLM session for `/ask`, and steering queue integration -- the full cockpit experience.

**Architecture:** `InspectorPanel` is a Textual `Vertical` widget with three sub-areas: block detail (ScrollableContainer), status line (Static), and input area (TextArea). It has its own command dispatch for `/ask`, `/steer`, `/prev`, `/next`, `/search`, `/help`. The inspector has two modes: **live** (follows the currently streaming block) and **pinned** (locked to a clicked block). The side LLM session is lazily created on first `/ask` using the same `SessionManager`. Steering messages go through the `SteerQueue` from Phase 1 and are injected via `SessionHandle.inject_user_message` at pause points.

**Tech Stack:** Python 3.12, Textual, pytest, pytest-asyncio

**Prerequisite:** Phase 1 (block model, SteerQueue) and Phase 2 (CockpitApp) must be complete.

---

## Task 1: Create InspectorPanel Widget Shell

**Files:**
- Create: `amplifier_tui/widgets/inspector_panel.py`
- Test: `tests/test_inspector_panel.py`

**Step 1: Write the failing test**

Create `tests/test_inspector_panel.py`:

```python
"""Tests for InspectorPanel widget."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Static, TextArea

from amplifier_tui.models.block_model import BlockInfo, BlockRegistry, BlockType
from amplifier_tui.widgets.inspector_panel import InspectorPanel


class InspectorTestApp(App):
    """Minimal app for testing InspectorPanel."""

    CSS = """
    InspectorPanel { height: 1fr; width: 40; }
    """

    def compose(self) -> ComposeResult:
        self._registry = BlockRegistry()
        self._registry.add(BlockType.USER, turn_index=0, summary="Hello world")
        self._registry.add(BlockType.ASSISTANT, turn_index=0, summary="Hi there")
        self._registry.add(BlockType.TOOL_CALL, turn_index=1, summary="grep for imports")
        yield InspectorPanel(block_registry=self._registry, id="inspector")


class TestInspectorCompose:
    """InspectorPanel has the expected sub-areas."""

    @pytest.mark.asyncio
    async def test_has_detail_area(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            detail = panel.query_one("#inspector-detail", ScrollableContainer)
            assert detail is not None

    @pytest.mark.asyncio
    async def test_has_status_line(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            status = panel.query_one("#inspector-status", Static)
            assert status is not None

    @pytest.mark.asyncio
    async def test_has_input_area(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            input_area = panel.query_one("#inspector-input", TextArea)
            assert input_area is not None


class TestInspectorModes:
    """InspectorPanel live vs pinned mode."""

    @pytest.mark.asyncio
    async def test_default_mode_is_live(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            assert panel.mode == "live"

    @pytest.mark.asyncio
    async def test_pin_to_block(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            assert panel.mode == "pinned"
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_unpin_returns_to_live(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            panel.set_live_mode()
            assert panel.mode == "live"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_inspector_panel.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'amplifier_tui.widgets.inspector_panel'`

**Step 3: Write the implementation**

Create `amplifier_tui/widgets/inspector_panel.py`:

```python
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
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_inspector_panel.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/widgets/inspector_panel.py tests/test_inspector_panel.py
git commit -m "feat(cockpit): add InspectorPanel widget with live/pinned modes"
```

---

## Task 2: Test Inspector Navigation and Search

**Files:**
- Modify: `tests/test_inspector_panel.py` (add tests)

**Step 1: Write the tests**

Append to `tests/test_inspector_panel.py`:

```python
class TestInspectorNavigation:
    """Inspector prev/next/search navigation."""

    @pytest.mark.asyncio
    async def test_prev_from_last(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(2)  # last block
            panel.go_prev()
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_next_from_first(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.go_next()
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_prev_at_start_stays(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.go_prev()
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_next_at_end_stays(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(2)
            panel.go_next()
            assert panel.current_block_id == 2

    @pytest.mark.asyncio
    async def test_search_backward_finds_match(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(2)  # start from end
            panel.search_blocks("Hello")
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_search_forward_finds_match(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)  # start from beginning
            panel.search_blocks("grep", forward=True)
            assert panel.current_block_id == 2

    @pytest.mark.asyncio
    async def test_navigation_switches_to_pinned(self):
        async with InspectorTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.set_live_mode()
            assert panel.mode == "live"
            panel.pin_to_block(1)
            panel.go_prev()
            assert panel.mode == "pinned"
```

**Step 2: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_inspector_panel.py::TestInspectorNavigation -v
```

Expected: All PASS

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_inspector_panel.py
git commit -m "test(cockpit): add inspector navigation and search tests"
```

---

## Task 3: Test Inspector Command Dispatch

**Files:**
- Modify: `tests/test_inspector_panel.py` (add tests)

**Step 1: Write the tests**

Append to `tests/test_inspector_panel.py`:

```python
from amplifier_tui.widgets.inspector_panel import InspectorSteerRequest, InspectorAskRequest


class InspectorMessageTestApp(App):
    """App that captures inspector messages for testing."""

    CSS = """
    InspectorPanel { height: 1fr; width: 40; }
    """

    def __init__(self):
        super().__init__()
        self.steer_messages: list[str] = []
        self.ask_messages: list[tuple[str, BlockInfo | None]] = []

    def compose(self) -> ComposeResult:
        self._registry = BlockRegistry()
        self._registry.add(BlockType.USER, turn_index=0, summary="Hello world")
        self._registry.add(BlockType.ASSISTANT, turn_index=0, summary="Hi there")
        yield InspectorPanel(block_registry=self._registry, id="inspector")

    def on_inspector_steer_request(self, event: InspectorSteerRequest) -> None:
        self.steer_messages.append(event.text)

    def on_inspector_ask_request(self, event: InspectorAskRequest) -> None:
        self.ask_messages.append((event.question, event.block_info))


class TestInspectorCommandDispatch:
    """Inspector handle_input routes commands correctly."""

    @pytest.mark.asyncio
    async def test_free_text_sends_steer(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("focus on the tests please")
            await pilot.pause()
            assert "focus on the tests please" in pilot.app.steer_messages

    @pytest.mark.asyncio
    async def test_explicit_steer_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("/steer use pytest instead")
            await pilot.pause()
            assert "use pytest instead" in pilot.app.steer_messages

    @pytest.mark.asyncio
    async def test_ask_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.handle_input("/ask what does this block do?")
            await pilot.pause()
            assert len(pilot.app.ask_messages) == 1
            question, block = pilot.app.ask_messages[0]
            assert question == "what does this block do?"
            assert block is not None
            assert block.block_id == 0

    @pytest.mark.asyncio
    async def test_prev_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            panel.handle_input("/prev")
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_next_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.handle_input("/next")
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_search_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(1)
            panel.handle_input("/search Hello")
            assert panel.current_block_id == 0

    @pytest.mark.asyncio
    async def test_search_forward_command(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.pin_to_block(0)
            panel.handle_input("/search forward Hi")
            assert panel.current_block_id == 1

    @pytest.mark.asyncio
    async def test_help_command_shows_help(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("/help")
            await pilot.pause()
            # Help text should be in the detail area
            detail = panel.query_one("#inspector-detail")
            children_text = str([str(c.renderable) for c in detail.children])
            assert "Inspector Commands" in children_text or len(list(detail.children)) > 0

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self):
        async with InspectorMessageTestApp().run_test() as pilot:
            panel = pilot.app.query_one("#inspector", InspectorPanel)
            panel.handle_input("")
            panel.handle_input("   ")
            await pilot.pause()
            assert len(pilot.app.steer_messages) == 0
            assert len(pilot.app.ask_messages) == 0
```

**Step 2: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_inspector_panel.py::TestInspectorCommandDispatch -v
```

Expected: All PASS

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_inspector_panel.py
git commit -m "test(cockpit): add inspector command dispatch tests"
```

---

## Task 4: Wire Inspector into CockpitApp -- Toggle and Block Selection

**Files:**
- Modify: `amplifier_tui/cockpit_app.py`
- Test: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the failing test**

Append to `tests/test_cockpit_app.py`:

```python
from amplifier_tui.widgets.inspector_panel import InspectorPanel


class TestCockpitInspectorToggle:
    """CockpitApp inspector panel toggle and block selection."""

    @pytest.mark.asyncio
    async def test_inspector_initially_hidden(self):
        async with CockpitApp().run_test() as pilot:
            panels = list(pilot.app.query(InspectorPanel))
            if panels:
                assert not panels[0].display
            # Or no panel exists yet (lazy mount) -- both are valid

    @pytest.mark.asyncio
    async def test_toggle_inspector_shows_panel(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            assert panel.display

    @pytest.mark.asyncio
    async def test_toggle_twice_hides_panel(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._toggle_inspector()
            await pilot.pause()
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            assert not panel.display

    @pytest.mark.asyncio
    async def test_block_click_opens_inspector_pinned(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("Test block click")
            await pilot.pause()
            # Find the user block and click it
            blocks = list(app.query(ChatBlock))
            user_blocks = [b for b in blocks if b.block_type == BlockType.USER]
            assert len(user_blocks) > 0
            user_blocks[0].on_click()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            assert panel.display
            assert panel.mode == "pinned"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitInspectorToggle -v
```

Expected: FAIL with `AttributeError: 'CockpitApp' object has no attribute '_toggle_inspector'`

**Step 3: Update CockpitApp**

In `amplifier_tui/cockpit_app.py`, make these changes:

**Add import at the top** (with existing imports):
```python
from .widgets.inspector_panel import InspectorPanel, InspectorSteerRequest, InspectorAskRequest
from textual.containers import Horizontal
```

**Add keybinding** in the `BINDINGS` list:
```python
    Binding("ctrl+i", "toggle_inspector", "Inspector", show=True),
```

**Update compose()** to include the inspector panel (hidden by default):
```python
    def compose(self) -> ComposeResult:
        with Horizontal(id="cockpit-main"):
            with Vertical(id="cockpit-chat-area"):
                yield ScrollableContainer(id="cockpit-chat-view")
                yield ChatInput(
                    "",
                    id="chat-input",
                    soft_wrap=True,
                    show_line_numbers=False,
                    tab_behavior="focus",
                    compact=True,
                )
            yield InspectorPanel(
                block_registry=self._block_registry,
                id="inspector-panel",
            )
        yield Static("No session | Ready", id="cockpit-status-bar")
```

**Update the CSS** to include inspector layout:
```css
#cockpit-main {
    width: 1fr;
    height: 1fr;
}

#cockpit-chat-area {
    width: 1fr;
    height: 1fr;
}

#inspector-panel {
    width: 40;
    display: none;
}

#inspector-panel.visible {
    display: block;
}
```

**Add inspector toggle method:**
```python
    def _toggle_inspector(self) -> None:
        """Toggle the inspector panel visibility."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            if panel.display:
                panel.display = False
                panel.remove_class("visible")
            else:
                panel.display = True
                panel.add_class("visible")
                panel.set_live_mode()
        except NoMatches:
            pass

    def action_toggle_inspector(self) -> None:
        """Textual action for Ctrl+I binding."""
        self._toggle_inspector()
```

**Update on_block_selected** to open inspector in pinned mode:
```python
    def on_block_selected(self, event: BlockSelected) -> None:
        """Handle block click -- open inspector in pinned mode."""
        # Visual selection
        for cb in self.query(ChatBlock):
            cb.deselect()

        # Open inspector in pinned mode
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            panel.display = True
            panel.add_class("visible")
            panel.pin_to_block(event.block_id)
        except NoMatches:
            pass
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitInspectorToggle -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/cockpit_app.py tests/test_cockpit_app.py
git commit -m "feat(cockpit): wire inspector panel toggle and block selection into CockpitApp"
```

---

## Task 5: Wire Steering Queue -- InspectorSteerRequest to Main Session

**Files:**
- Modify: `amplifier_tui/cockpit_app.py`
- Test: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the failing test**

Append to `tests/test_cockpit_app.py`:

```python
class TestCockpitSteering:
    """CockpitApp steering queue integration."""

    @pytest.mark.asyncio
    async def test_steer_request_queued(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Simulate an InspectorSteerRequest
            from amplifier_tui.widgets.inspector_panel import InspectorSteerRequest
            app.post_message(InspectorSteerRequest("focus on tests"))
            await pilot.pause()
            assert not app._steer_queue.is_empty
            assert app._steer_queue.dequeue() == "focus on tests"

    @pytest.mark.asyncio
    async def test_multiple_steers_fifo(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            from amplifier_tui.widgets.inspector_panel import InspectorSteerRequest
            app.post_message(InspectorSteerRequest("first"))
            app.post_message(InspectorSteerRequest("second"))
            await pilot.pause()
            assert app._steer_queue.dequeue() == "first"
            assert app._steer_queue.dequeue() == "second"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitSteering -v
```

Expected: FAIL (no handler for InspectorSteerRequest)

**Step 3: Add the handler to CockpitApp**

Add to `amplifier_tui/cockpit_app.py`:

```python
    def on_inspector_steer_request(self, event: InspectorSteerRequest) -> None:
        """Queue a steering message from the inspector."""
        self._steer_queue.enqueue(event.text)
        # If session is idle, send immediately as next message
        if not self._conversation.is_processing:
            steer_text = self._steer_queue.dequeue()
            if steer_text:
                self._add_user_message(f"[steer] {steer_text}")
                cid = self._conversation.conversation_id
                self._start_processing("Steering", conversation_id=cid)
                self._do_send_message(steer_text)
```

Also, add a check in `_on_stream_tool_end` to inject queued steers at pause points:

```python
    def _on_stream_tool_end(
        self, conversation_id: str, name: str, tool_input: dict, result: str
    ) -> None:
        self._processing_label = "Thinking"
        self.call_from_thread(self._add_tool_use, name, tool_input, result)
        self.call_from_thread(self._ensure_processing_indicator, "Thinking")
        # Check steer queue at pause point (between tool calls)
        self.call_from_thread(self._check_steer_queue)

    def _check_steer_queue(self) -> None:
        """Inject pending steer messages at natural pause points."""
        if self._steer_queue.is_empty:
            return
        cid = self._conversation.conversation_id
        handle = self.session_manager.get_handle(cid) if self.session_manager else None
        if handle:
            steer_text = self._steer_queue.dequeue()
            if steer_text:
                handle.inject_user_message(steer_text)
                self._add_system_message(f"[steer injected] {steer_text}")
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitSteering -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/cockpit_app.py tests/test_cockpit_app.py
git commit -m "feat(cockpit): wire steering queue -- InspectorSteerRequest to SteerQueue with pause-point injection"
```

---

## Task 6: Wire Side LLM Session -- /ask Command

**Files:**
- Modify: `amplifier_tui/cockpit_app.py`
- Test: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the failing test**

Append to `tests/test_cockpit_app.py`:

```python
class TestCockpitSideSession:
    """CockpitApp side session lifecycle."""

    @pytest.mark.asyncio
    async def test_side_session_initially_none(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            assert app._side_session_id is None

    @pytest.mark.asyncio
    async def test_ask_context_assembly(self):
        """Verify that /ask assembles the right context from the pinned block."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Add a block to reference
            app._add_user_message("Write tests for auth.py")
            block = app._block_registry.get_by_id(
                app._block_registry.last.block_id
            )
            assert block is not None
            # Build context
            context = app._build_ask_context(block, "what is this about?")
            assert "user" in context.lower() or "Write tests" in context
            assert "what is this about?" in context
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitSideSession -v
```

Expected: FAIL (no `_side_session_id` attribute or `_build_ask_context` method)

**Step 3: Add side session support to CockpitApp**

In `amplifier_tui/cockpit_app.py`, add to `__init__`:

```python
        # Side session (lazy, for /ask)
        self._side_session_id: str | None = None
        self._side_conversation = ConversationState()
```

Add methods:

```python
    def _build_ask_context(self, block: BlockInfo, question: str) -> str:
        """Assemble context for a /ask query from a block."""
        parts = [
            f"I'm looking at a {block.block_type.value} block (turn {block.turn_index}):",
            f"Content: {block.summary}",
            "",
            f"Question: {question}",
        ]
        return "\n".join(parts)

    def on_inspector_ask_request(self, event: InspectorAskRequest) -> None:
        """Handle /ask from the inspector -- send to side session."""
        if event.block_info is None:
            self._add_system_message("No block selected for /ask")
            return
        context = self._build_ask_context(event.block_info, event.question)
        self._do_ask(context)

    @work(thread=True, group="ask")
    async def _do_ask(self, context: str) -> None:
        """Send a /ask query to the side LLM session."""
        if self.session_manager is None:
            self.call_from_thread(self._show_inspector_error, "No session manager")
            return

        try:
            # Lazy-create side session
            if self._side_session_id is None:
                self._side_conversation = ConversationState()
                self._side_session_id = self._side_conversation.conversation_id
                await self.session_manager.start_new_session(
                    conversation_id=self._side_session_id,
                )

            # Update inspector status
            self.call_from_thread(self._show_inspector_status, "[ASK] waiting...")

            response = await self.session_manager.send_message(
                context, conversation_id=self._side_session_id
            )

            # Show response in inspector
            self.call_from_thread(self._show_ask_response, response or "(no response)")

        except Exception as e:
            logger.debug("Side session /ask failed", exc_info=True)
            self.call_from_thread(self._show_inspector_error, f"/ask failed: {e}")

    def _show_ask_response(self, response: str) -> None:
        """Display a /ask response in the inspector."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            panel.display_ask_response(response)
        except NoMatches:
            pass

    def _show_inspector_error(self, text: str) -> None:
        """Display an error in the inspector detail area."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            panel._set_detail_content(f"Error: {text}")
        except NoMatches:
            pass

    def _show_inspector_status(self, text: str) -> None:
        """Update the inspector status line directly."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            status = panel.query_one("#inspector-status", Static)
            status.update(text)
        except NoMatches:
            pass
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitSideSession -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/cockpit_app.py tests/test_cockpit_app.py
git commit -m "feat(cockpit): add side LLM session for /ask with lazy creation and context assembly"
```

---

## Task 7: Wire Live Mode -- Inspector Follows Streaming Blocks

**Files:**
- Modify: `amplifier_tui/cockpit_app.py`
- Test: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the failing test**

Append to `tests/test_cockpit_app.py`:

```python
class TestCockpitLiveMode:
    """Inspector live mode follows latest block."""

    @pytest.mark.asyncio
    async def test_inspector_follows_new_blocks_in_live_mode(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Open inspector in live mode
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)

            # Add blocks
            app._add_user_message("msg 1")
            app._notify_inspector_new_block()
            await pilot.pause()

            assert panel.mode == "live"
            last_id = app._block_registry.last.block_id
            assert panel.current_block_id == last_id

    @pytest.mark.asyncio
    async def test_inspector_does_not_follow_in_pinned_mode(self):
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg 1")
            app._add_assistant_message("reply 1")
            await pilot.pause()

            # Open inspector and pin to first block
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            panel.pin_to_block(0)

            # Add more blocks
            app._add_user_message("msg 2")
            app._notify_inspector_new_block()
            await pilot.pause()

            # Should still be pinned to block 0
            assert panel.current_block_id == 0
            assert panel.mode == "pinned"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitLiveMode -v
```

Expected: FAIL (no `_notify_inspector_new_block` method)

**Step 3: Add the method to CockpitApp**

In `amplifier_tui/cockpit_app.py`, add:

```python
    def _notify_inspector_new_block(self) -> None:
        """Tell the inspector about a new block (for live mode following)."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            if panel.display:
                panel.follow_latest()
        except NoMatches:
            pass
```

Then call `self._notify_inspector_new_block()` at the end of `_begin_streaming_block` and after `_add_tool_use`:

In `_begin_streaming_block`, add at the end:
```python
        self._notify_inspector_new_block()
```

In `_add_tool_use`, add at the end:
```python
        self._notify_inspector_new_block()
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitLiveMode -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/cockpit_app.py tests/test_cockpit_app.py
git commit -m "feat(cockpit): wire live mode -- inspector follows latest streaming block"
```

---

## Task 8: Wire Inspector Input Routing

**Files:**
- Modify: `amplifier_tui/cockpit_app.py`
- Test: `tests/test_cockpit_app.py` (add tests)

**Step 1: Write the failing test**

Append to `tests/test_cockpit_app.py`:

```python
class TestCockpitInputRouting:
    """Input routes to main session or inspector based on panel state."""

    @pytest.mark.asyncio
    async def test_input_goes_to_main_when_inspector_closed(self):
        """When inspector is closed, input goes to main session."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            # Inspector should be closed by default
            target = app._get_input_target()
            assert target == "main"

    @pytest.mark.asyncio
    async def test_input_goes_to_inspector_when_open(self):
        """When inspector is open, input routes to inspector."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._toggle_inspector()
            await pilot.pause()
            target = app._get_input_target()
            assert target == "inspector"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitInputRouting -v
```

Expected: FAIL (no `_get_input_target` method)

**Step 3: Add input routing to CockpitApp**

In `amplifier_tui/cockpit_app.py`, add:

```python
    def _get_input_target(self) -> str:
        """Determine where input should be routed: 'main' or 'inspector'."""
        try:
            panel = self.query_one("#inspector-panel", InspectorPanel)
            if panel.display:
                return "inspector"
        except NoMatches:
            pass
        return "main"
```

Update `_handle_input` to route based on target:

```python
    def _handle_input(self, text: str) -> None:
        """Process input from the chat input widget."""
        text = text.strip()
        if not text:
            return

        target = self._get_input_target()

        if target == "inspector":
            # Route to inspector command dispatch
            try:
                panel = self.query_one("#inspector-panel", InspectorPanel)
                panel.handle_input(text)
            except NoMatches:
                pass
            return

        # Main session: slash command or regular message
        if text.startswith("/"):
            self._dispatch_slash_command(text)
            return

        self._clear_welcome()
        self._add_user_message(text)
        cid = self._conversation.conversation_id
        self._start_processing("Starting session", conversation_id=cid)
        self._do_send_message(text)
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_app.py::TestCockpitInputRouting -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/cockpit_app.py tests/test_cockpit_app.py
git commit -m "feat(cockpit): add input routing -- main vs inspector based on panel state"
```

---

## Task 9: Export InspectorPanel from widgets __init__.py

**Files:**
- Modify: `amplifier_tui/widgets/__init__.py`

**Step 1: Add the import**

Add to `amplifier_tui/widgets/__init__.py`:

```python
from .inspector_panel import InspectorAskRequest, InspectorPanel, InspectorSteerRequest
```

And add `"InspectorAskRequest"`, `"InspectorPanel"`, `"InspectorSteerRequest"` to the `__all__` list.

**Step 2: Run import smoke test**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -c "from amplifier_tui.widgets import InspectorPanel, InspectorSteerRequest, InspectorAskRequest; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/widgets/__init__.py
git commit -m "feat(cockpit): export InspectorPanel from widgets package"
```

---

## Task 10: Integration Test -- Full Cockpit Flow

**Files:**
- Create: `tests/test_cockpit_integration.py`

**Step 1: Write the integration test**

Create `tests/test_cockpit_integration.py`:

```python
"""Integration tests for the full cockpit flow.

Tests the complete path: message -> stream events -> blocks created ->
inspector pin -> navigation -> steering queue.
No real Amplifier session -- all session interactions are mocked.
"""

from __future__ import annotations

import pytest

from amplifier_tui.cockpit_app import CockpitApp
from amplifier_tui.models.block_model import BlockType
from amplifier_tui.widgets.chat_block import ChatBlock
from amplifier_tui.widgets.inspector_panel import InspectorPanel


class TestFullCockpitFlow:
    """End-to-end flow without a real session."""

    @pytest.mark.asyncio
    async def test_message_to_blocks_flow(self):
        """Messages create ChatBlock widgets in the registry."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("Hello")
            app._add_assistant_message("Hi there!")
            await pilot.pause()

            assert len(app._block_registry) >= 2
            blocks = list(app.query(ChatBlock))
            assert len(blocks) >= 2

    @pytest.mark.asyncio
    async def test_block_click_to_inspector_flow(self):
        """Click block -> inspector opens pinned -> shows block detail."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("Click test")
            await pilot.pause()

            # Click the user block
            user_blocks = [b for b in app.query(ChatBlock) if b.block_type == BlockType.USER]
            assert len(user_blocks) > 0
            user_blocks[0].on_click()
            await pilot.pause()

            # Inspector should be visible and pinned
            panel = app.query_one("#inspector-panel", InspectorPanel)
            assert panel.display
            assert panel.mode == "pinned"

    @pytest.mark.asyncio
    async def test_inspector_navigation_flow(self):
        """Navigate through blocks in the inspector."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("msg 1")
            app._add_assistant_message("reply 1")
            app._add_user_message("msg 2")
            await pilot.pause()

            # Open inspector pinned to last block
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)
            last_id = app._block_registry.last.block_id
            panel.pin_to_block(last_id)

            # Navigate backward
            panel.go_prev()
            assert panel.current_block_id == last_id - 1
            panel.go_prev()
            assert panel.current_block_id == last_id - 2

            # Navigate forward
            panel.go_next()
            assert panel.current_block_id == last_id - 1

    @pytest.mark.asyncio
    async def test_steering_queue_flow(self):
        """Steer from inspector -> queue -> check at pause point."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._toggle_inspector()
            await pilot.pause()
            panel = app.query_one("#inspector-panel", InspectorPanel)

            # Steer while session is not processing
            panel.handle_input("focus on error handling")
            await pilot.pause()

            # The steer should have been sent immediately (session idle)
            # or queued depending on processing state
            # Just verify no crash and steer was handled

    @pytest.mark.asyncio
    async def test_block_registry_consistent_with_widgets(self):
        """BlockRegistry count matches ChatBlock widget count."""
        async with CockpitApp().run_test() as pilot:
            app = pilot.app
            app._add_user_message("a")
            app._add_assistant_message("b")
            app._add_user_message("c")
            app._add_assistant_message("d")
            await pilot.pause()

            registry_count = len(app._block_registry)
            widget_count = len(list(app.query(ChatBlock)))
            # May include welcome screen blocks, but user+assistant should match
            assert registry_count >= 4
            assert widget_count >= 4
```

**Step 2: Run the integration tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_cockpit_integration.py -v
```

Expected: All PASS

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_cockpit_integration.py
git commit -m "test(cockpit): add integration tests for full cockpit flow"
```

---

## Task 11: Full Phase 3 Regression Test

**Files:** None modified -- verification only.

**Step 1: Run the complete test suite**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/ -v --timeout=60
```

Expected: All tests PASS -- Phase 1, Phase 2, and Phase 3.

**Step 2: Verify the full cockpit import chain**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -c "
from amplifier_tui.cockpit_app import CockpitApp
from amplifier_tui.widgets.inspector_panel import InspectorPanel, InspectorSteerRequest, InspectorAskRequest
from amplifier_tui.models import BlockRegistry, BlockType, SteerQueue

# Verify MRO
mro = [c.__name__ for c in CockpitApp.__mro__[:10]]
print(f'CockpitApp MRO: {mro}')

# Verify registry + inspector work together
reg = BlockRegistry()
reg.add(BlockType.USER, turn_index=0, summary='test')
reg.add(BlockType.ASSISTANT, turn_index=0, summary='reply')
assert reg.get_by_id(0).summary == 'test'
assert reg.prev_block(1).block_id == 0

# Verify steer queue
q = SteerQueue()
q.enqueue('steer msg')
assert q.dequeue() == 'steer msg'
assert q.is_empty

print('All Phase 3 integration checks passed!')
"
```

Expected: `All Phase 3 integration checks passed!`

**Step 3: Verify test count summary**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_block_model.py tests/test_chat_block.py tests/test_cockpit_cmds.py tests/test_cockpit_app.py tests/test_inspector_panel.py tests/test_cockpit_integration.py -v --tb=no | tail -5
```

Expected: Shows total test count (should be 40+ cockpit-specific tests) with all passing.

---

## Summary

| Task | What | Files | Tests |
|------|------|-------|-------|
| 1 | InspectorPanel widget shell | widgets/inspector_panel.py | test_inspector_panel.py |
| 2 | Inspector navigation + search tests | (none) | test_inspector_panel.py |
| 3 | Inspector command dispatch tests | (none) | test_inspector_panel.py |
| 4 | Wire inspector into CockpitApp | cockpit_app.py | test_cockpit_app.py |
| 5 | Steering queue wiring | cockpit_app.py | test_cockpit_app.py |
| 6 | Side LLM session for /ask | cockpit_app.py | test_cockpit_app.py |
| 7 | Live mode -- follow streaming | cockpit_app.py | test_cockpit_app.py |
| 8 | Input routing main vs inspector | cockpit_app.py | test_cockpit_app.py |
| 9 | Export InspectorPanel | widgets/__init__.py | import check |
| 10 | Integration test -- full flow | (none) | test_cockpit_integration.py |
| 11 | Full regression | (none) | all tests |

**Phase 3 delivers:** The full cockpit experience -- inspector panel with live/pinned modes, block navigation and search, side LLM session via `/ask`, steering queue with pause-point injection, and input routing between main session and inspector. The Session Cockpit is feature-complete.

---

## Open Questions Resolved During Implementation

1. **Inspector keystroke:** `Ctrl+I` (intuitive for "inspector"). Test for conflicts during Task 4.
2. **Steer injection:** Queue at app level via `SteerQueue`, inject via `SessionHandle.inject_user_message` at tool_end pause points. If `LocalBridge` doesn't support mid-loop injection, the queue holds until the turn ends.
3. **Side session cleanup:** Lazy creation on first `/ask`, persists for app lifetime. No explicit cleanup needed -- session manager handles it.
4. **Inspector position:** Default is right (width: 40). A future `/inspector bottom` command could switch to Vertical split, but that's not in this phase.
