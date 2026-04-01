# Session Cockpit Phase 1: Foundation

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Build the block model, steering queue, ChatBlock widget, and extract shared methods into SharedAppBase -- the infrastructure all subsequent phases depend on.

**Architecture:** New `BlockInfo` dataclass and `BlockRegistry` provide pure-data block tracking. `SteerQueue` wraps a deque for steering message management. `ChatBlock` is a thin Textual `Vertical` wrapper that emits a `BlockSelected` message on click. `SharedAppBase` gets `block_index` passthrough in streaming callbacks so frontends can track which block is being streamed.

**Tech Stack:** Python 3.12, Textual, pytest, pytest-asyncio

---

## Task 1: Create the BlockInfo Dataclass and BlockType Enum

**Files:**
- Create: `amplifier_tui/models/__init__.py`
- Create: `amplifier_tui/models/block_model.py`
- Test: `tests/test_block_model.py`

**Step 1: Write the failing test**

Create `tests/test_block_model.py`:

```python
"""Tests for block model -- pure data, no Textual dependency."""

from __future__ import annotations

import pytest

from amplifier_tui.models.block_model import BlockInfo, BlockType


class TestBlockType:
    """BlockType enum covers all expected stream event types."""

    def test_enum_members(self):
        assert BlockType.USER.value == "user"
        assert BlockType.ASSISTANT.value == "assistant"
        assert BlockType.THINKING.value == "thinking"
        assert BlockType.TOOL_CALL.value == "tool_call"
        assert BlockType.TOOL_RESULT.value == "tool_result"
        assert BlockType.AGENT_DELEGATION.value == "agent_delegation"
        assert BlockType.SYSTEM.value == "system"

    def test_enum_count(self):
        assert len(BlockType) == 7


class TestBlockInfo:
    """BlockInfo dataclass construction and defaults."""

    def test_construction(self):
        block = BlockInfo(
            block_id=0,
            block_type=BlockType.ASSISTANT,
            turn_index=1,
        )
        assert block.block_id == 0
        assert block.block_type == BlockType.ASSISTANT
        assert block.turn_index == 1
        assert block.summary == ""
        assert block.content_ref is None

    def test_construction_with_all_fields(self):
        block = BlockInfo(
            block_id=5,
            block_type=BlockType.TOOL_CALL,
            turn_index=3,
            summary="grep for imports",
            content_ref="widget-id-123",
        )
        assert block.block_id == 5
        assert block.summary == "grep for imports"
        assert block.content_ref == "widget-id-123"

    def test_block_type_from_string(self):
        """BlockType can be constructed from stream event strings."""
        assert BlockType("user") == BlockType.USER
        assert BlockType("thinking") == BlockType.THINKING
        assert BlockType("tool_call") == BlockType.TOOL_CALL
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_block_model.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'amplifier_tui.models'`

**Step 3: Write minimal implementation**

Create `amplifier_tui/models/__init__.py`:

```python
"""Data models for the Session Cockpit."""

from .block_model import BlockInfo, BlockRegistry, BlockType, SteerQueue

__all__ = ["BlockInfo", "BlockRegistry", "BlockType", "SteerQueue"]
```

Create `amplifier_tui/models/block_model.py`:

```python
"""Block model for Session Cockpit -- pure data, no Textual dependency.

BlockInfo tracks metadata for each block in the conversation stream.
BlockRegistry provides lookup, navigation, and search over blocks.
SteerQueue manages deferred steering messages for the main session.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BlockType(Enum):
    """Types of blocks in the conversation stream."""

    USER = "user"
    ASSISTANT = "assistant"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    AGENT_DELEGATION = "agent_delegation"
    SYSTEM = "system"


@dataclass
class BlockInfo:
    """Metadata for a single block in the conversation stream.

    Attributes:
        block_id: Sequential integer, assigned by BlockRegistry.
        block_type: What kind of block this is.
        turn_index: Conversational turn number (increments on each user message).
        summary: Short description (e.g., tool name, first line of text).
        content_ref: Reference to the widget or content (widget ID string).
    """

    block_id: int
    block_type: BlockType
    turn_index: int
    summary: str = ""
    content_ref: Any = None


class BlockRegistry:
    """Registry of BlockInfo objects with lookup and navigation.

    Blocks are stored in insertion order. IDs are sequential integers
    starting at 0.
    """

    def __init__(self) -> None:
        self._blocks: list[BlockInfo] = []

    def __len__(self) -> int:
        return len(self._blocks)

    def add(
        self,
        block_type: BlockType,
        turn_index: int,
        summary: str = "",
        content_ref: Any = None,
    ) -> BlockInfo:
        """Create and register a new block. Returns the new BlockInfo."""
        block = BlockInfo(
            block_id=len(self._blocks),
            block_type=block_type,
            turn_index=turn_index,
            summary=summary,
            content_ref=content_ref,
        )
        self._blocks.append(block)
        return block

    def get_by_id(self, block_id: int) -> BlockInfo | None:
        """Look up a block by its sequential ID."""
        if 0 <= block_id < len(self._blocks):
            return self._blocks[block_id]
        return None

    def get_by_turn(self, turn_index: int) -> list[BlockInfo]:
        """Return all blocks belonging to a specific turn."""
        return [b for b in self._blocks if b.turn_index == turn_index]

    def search(self, term: str, *, forward: bool = False, from_id: int | None = None) -> BlockInfo | None:
        """Search blocks by summary text. Returns first match or None.

        Args:
            term: Case-insensitive substring to search for.
            forward: If True, search forward from from_id. Default is backward.
            from_id: Starting block ID. None means start from end (backward) or start (forward).
        """
        term_lower = term.lower()
        if forward:
            start = (from_id + 1) if from_id is not None else 0
            for block in self._blocks[start:]:
                if term_lower in block.summary.lower():
                    return block
        else:
            start = (from_id - 1) if from_id is not None else len(self._blocks) - 1
            for i in range(start, -1, -1):
                if term_lower in self._blocks[i].summary.lower():
                    return self._blocks[i]
        return None

    def prev_block(self, current_id: int) -> BlockInfo | None:
        """Return the block before current_id, or None if at start."""
        if current_id > 0:
            return self._blocks[current_id - 1]
        return None

    def next_block(self, current_id: int) -> BlockInfo | None:
        """Return the block after current_id, or None if at end."""
        if current_id < len(self._blocks) - 1:
            return self._blocks[current_id + 1]
        return None

    @property
    def last(self) -> BlockInfo | None:
        """Return the most recently added block, or None if empty."""
        return self._blocks[-1] if self._blocks else None

    @property
    def all_blocks(self) -> list[BlockInfo]:
        """Return a copy of all blocks."""
        return list(self._blocks)


class SteerQueue:
    """Queue for steering messages to be injected into the main session.

    Messages are injected at natural pause points (between tool calls,
    before next LLM turn). When the session is idle, steer becomes the
    next regular user message.
    """

    def __init__(self) -> None:
        self._queue: deque[str] = deque()

    def enqueue(self, message: str) -> None:
        """Add a steering message to the queue."""
        self._queue.append(message)

    def dequeue(self) -> str | None:
        """Remove and return the next steering message, or None if empty."""
        if self._queue:
            return self._queue.popleft()
        return None

    @property
    def is_empty(self) -> bool:
        """True if no steering messages are queued."""
        return len(self._queue) == 0

    def __len__(self) -> int:
        return len(self._queue)

    def clear(self) -> None:
        """Discard all queued messages."""
        self._queue.clear()
```

**Step 4: Run test to verify it passes**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_block_model.py::TestBlockType -v
python -m pytest tests/test_block_model.py::TestBlockInfo -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/models/__init__.py amplifier_tui/models/block_model.py tests/test_block_model.py
git commit -m "feat(cockpit): add BlockInfo dataclass, BlockType enum, and block model module"
```

---

## Task 2: Test and Verify BlockRegistry

**Files:**
- Modify: `tests/test_block_model.py` (add tests)
- Already implemented: `amplifier_tui/models/block_model.py`

**Step 1: Write the failing tests**

Append to `tests/test_block_model.py`:

```python
from amplifier_tui.models.block_model import BlockRegistry


class TestBlockRegistry:
    """BlockRegistry: add, lookup, navigation, search."""

    def test_add_and_len(self):
        reg = BlockRegistry()
        assert len(reg) == 0
        block = reg.add(BlockType.USER, turn_index=0, summary="Hello")
        assert len(reg) == 1
        assert block.block_id == 0
        assert block.block_type == BlockType.USER
        assert block.summary == "Hello"

    def test_sequential_ids(self):
        reg = BlockRegistry()
        b0 = reg.add(BlockType.USER, turn_index=0)
        b1 = reg.add(BlockType.ASSISTANT, turn_index=0)
        b2 = reg.add(BlockType.TOOL_CALL, turn_index=1)
        assert b0.block_id == 0
        assert b1.block_id == 1
        assert b2.block_id == 2

    def test_get_by_id(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0, summary="first")
        reg.add(BlockType.ASSISTANT, turn_index=0, summary="second")
        assert reg.get_by_id(0).summary == "first"
        assert reg.get_by_id(1).summary == "second"
        assert reg.get_by_id(2) is None
        assert reg.get_by_id(-1) is None

    def test_get_by_turn(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0)
        reg.add(BlockType.ASSISTANT, turn_index=0)
        reg.add(BlockType.USER, turn_index=1)
        reg.add(BlockType.TOOL_CALL, turn_index=1)
        reg.add(BlockType.ASSISTANT, turn_index=1)
        assert len(reg.get_by_turn(0)) == 2
        assert len(reg.get_by_turn(1)) == 3
        assert len(reg.get_by_turn(99)) == 0

    def test_prev_next_navigation(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0)
        reg.add(BlockType.ASSISTANT, turn_index=0)
        reg.add(BlockType.USER, turn_index=1)
        # prev from start is None
        assert reg.prev_block(0) is None
        # prev from 1 is block 0
        assert reg.prev_block(1).block_id == 0
        # next from 1 is block 2
        assert reg.next_block(1).block_id == 2
        # next from end is None
        assert reg.next_block(2) is None

    def test_last_property(self):
        reg = BlockRegistry()
        assert reg.last is None
        reg.add(BlockType.USER, turn_index=0, summary="first")
        assert reg.last.summary == "first"
        reg.add(BlockType.ASSISTANT, turn_index=0, summary="second")
        assert reg.last.summary == "second"

    def test_search_backward(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0, summary="Hello world")
        reg.add(BlockType.ASSISTANT, turn_index=0, summary="Hi there")
        reg.add(BlockType.TOOL_CALL, turn_index=1, summary="grep for imports")
        reg.add(BlockType.ASSISTANT, turn_index=1, summary="Found imports")
        # Backward search from end
        result = reg.search("grep")
        assert result is not None
        assert result.block_id == 2
        # Case insensitive
        result = reg.search("GREP")
        assert result is not None
        assert result.block_id == 2

    def test_search_forward(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0, summary="Hello world")
        reg.add(BlockType.ASSISTANT, turn_index=0, summary="Hi there")
        reg.add(BlockType.TOOL_CALL, turn_index=1, summary="grep for imports")
        # Forward search from start
        result = reg.search("Hi", forward=True)
        assert result is not None
        assert result.block_id == 1

    def test_search_from_id(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0, summary="alpha test")
        reg.add(BlockType.ASSISTANT, turn_index=0, summary="beta test")
        reg.add(BlockType.USER, turn_index=1, summary="gamma test")
        # Backward from block 2 should find block 1
        result = reg.search("test", from_id=2)
        assert result is not None
        assert result.block_id == 1

    def test_search_no_match(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0, summary="Hello")
        assert reg.search("zzz_no_match") is None

    def test_all_blocks_returns_copy(self):
        reg = BlockRegistry()
        reg.add(BlockType.USER, turn_index=0)
        blocks = reg.all_blocks
        blocks.append(None)  # mutate the copy
        assert len(reg) == 1  # original unchanged
```

**Step 2: Run tests to verify they pass**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_block_model.py::TestBlockRegistry -v
```

Expected: All PASS (implementation already written in Task 1)

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_block_model.py
git commit -m "test(cockpit): add comprehensive BlockRegistry tests"
```

---

## Task 3: Test and Verify SteerQueue

**Files:**
- Modify: `tests/test_block_model.py` (add tests)
- Already implemented: `amplifier_tui/models/block_model.py`

**Step 1: Write the tests**

Append to `tests/test_block_model.py`:

```python
from amplifier_tui.models.block_model import SteerQueue


class TestSteerQueue:
    """SteerQueue: FIFO queue for steering messages."""

    def test_empty_queue(self):
        q = SteerQueue()
        assert q.is_empty
        assert len(q) == 0
        assert q.dequeue() is None

    def test_enqueue_dequeue_fifo(self):
        q = SteerQueue()
        q.enqueue("first")
        q.enqueue("second")
        q.enqueue("third")
        assert len(q) == 3
        assert not q.is_empty
        assert q.dequeue() == "first"
        assert q.dequeue() == "second"
        assert q.dequeue() == "third"
        assert q.is_empty

    def test_clear(self):
        q = SteerQueue()
        q.enqueue("msg1")
        q.enqueue("msg2")
        q.clear()
        assert q.is_empty
        assert len(q) == 0

    def test_interleaved_operations(self):
        q = SteerQueue()
        q.enqueue("a")
        assert q.dequeue() == "a"
        q.enqueue("b")
        q.enqueue("c")
        assert q.dequeue() == "b"
        assert len(q) == 1
        assert q.dequeue() == "c"
        assert q.is_empty
```

**Step 2: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_block_model.py::TestSteerQueue -v
```

Expected: All PASS

**Step 3: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add tests/test_block_model.py
git commit -m "test(cockpit): add SteerQueue tests"
```

---

## Task 4: Add block_index Passthrough to SharedAppBase Streaming Callbacks

**Files:**
- Modify: `amplifier_tui/core/app_base.py` (lines 86-108, 156-179)

This task wires the `block_index` that's already available in `_wire_streaming_callbacks` closures through to the abstract methods, so frontends can use it.

**Step 1: Update abstract method signatures in app_base.py**

In `amplifier_tui/core/app_base.py`, change the three abstract streaming methods to include `block_index`:

Change line 86:
```python
    def _on_stream_block_start(self, conversation_id: str, block_type: str) -> None:
```
to:
```python
    def _on_stream_block_start(self, conversation_id: str, block_type: str, block_index: int = 0) -> None:
```

Change lines 90-92:
```python
    def _on_stream_block_delta(
        self, conversation_id: str, block_type: str, accumulated_text: str
    ) -> None:
```
to:
```python
    def _on_stream_block_delta(
        self, conversation_id: str, block_type: str, accumulated_text: str, block_index: int = 0
    ) -> None:
```

Change lines 96-102:
```python
    def _on_stream_block_end(
        self,
        conversation_id: str,
        block_type: str,
        final_text: str,
        had_block_start: bool,
    ) -> None:
```
to:
```python
    def _on_stream_block_end(
        self,
        conversation_id: str,
        block_type: str,
        final_text: str,
        had_block_start: bool,
        block_index: int = 0,
    ) -> None:
```

**Step 2: Update the closure wiring to pass block_index through**

In the same file, update the closures in `_wire_streaming_callbacks` (around lines 156-179):

Change the `on_block_start` closure (line 156):
```python
        def on_block_start(block_type: str, block_index: int) -> None:
            accumulated["text"] = ""
            last_update["t"] = 0.0
            block_started["v"] = True
            self._on_stream_block_start(conversation_id, block_type)
```
to:
```python
        def on_block_start(block_type: str, block_index: int) -> None:
            accumulated["text"] = ""
            last_update["t"] = 0.0
            block_started["v"] = True
            current_block_index["v"] = block_index
            self._on_stream_block_start(conversation_id, block_type, block_index)
```

Add a `current_block_index` tracking dict right after `block_started` (after line 154):
```python
        current_block_index = {"v": 0}
```

Change the `on_block_delta` closure to pass `block_index`:
```python
        def on_block_delta(block_type: str, delta: str) -> None:
            if conv.streaming_cancelled:
                return
            accumulated["text"] += delta
            conv.stream_accumulated_text = accumulated["text"]
            now = time.monotonic()
            if now - last_update["t"] >= 0.05:
                last_update["t"] = now
                snapshot = accumulated["text"]
                self._on_stream_block_delta(conversation_id, block_type, snapshot, current_block_index["v"])
```

Change the `on_block_end` closure to pass `block_index`:
```python
        def on_block_end(block_type: str, text: str) -> None:
            conv.got_stream_content = True
            had_start = block_started["v"]
            bi = current_block_index["v"]
            if had_start:
                block_started["v"] = False
                accumulated["text"] = ""
            self._on_stream_block_end(conversation_id, block_type, text, had_start, bi)
```

**Step 3: Run existing tests to verify nothing breaks**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_session_manager.py tests/test_app.py -v --timeout=30
```

Expected: All existing tests PASS (the new `block_index` parameter has a default value of 0)

**Step 4: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/core/app_base.py
git commit -m "feat(cockpit): add block_index passthrough to SharedAppBase streaming callbacks"
```

---

## Task 5: Update app.py Streaming Methods to Accept block_index

**Files:**
- Modify: `amplifier_tui/app.py` (lines 6565-6596)

The `AmplifierTuiApp` implementations of the streaming methods need to accept (and ignore) the new `block_index` parameter.

**Step 1: Update _on_stream_block_start (line 6565)**

Change:
```python
    def _on_stream_block_start(self, conversation_id: str, block_type: str) -> None:
```
to:
```python
    def _on_stream_block_start(self, conversation_id: str, block_type: str, block_index: int = 0) -> None:
```

**Step 2: Update _on_stream_block_delta (line 6568)**

Change:
```python
    def _on_stream_block_delta(
        self, conversation_id: str, block_type: str, accumulated_text: str
    ) -> None:
```
to:
```python
    def _on_stream_block_delta(
        self, conversation_id: str, block_type: str, accumulated_text: str, block_index: int = 0
    ) -> None:
```

**Step 3: Update _on_stream_block_end (line 6578)**

Change:
```python
    def _on_stream_block_end(
        self,
        conversation_id: str,
        block_type: str,
        final_text: str,
        had_block_start: bool,
    ) -> None:
```
to:
```python
    def _on_stream_block_end(
        self,
        conversation_id: str,
        block_type: str,
        final_text: str,
        had_block_start: bool,
        block_index: int = 0,
    ) -> None:
```

**Step 4: Check for web frontend implementations too**

Search for any other implementations of these methods:

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
grep -rn "def _on_stream_block_start\|def _on_stream_block_delta\|def _on_stream_block_end" amplifier_tui/ --include="*.py" | grep -v __pycache__
```

Update every file found (likely `amplifier_tui/web/` files) with the same `block_index: int = 0` parameter addition. The web frontend implementations will also need the parameter added to their signatures.

**Step 5: Run full test suite**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/ -v --timeout=30
```

Expected: All tests PASS

**Step 6: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/app.py amplifier_tui/web/
git commit -m "feat(cockpit): update all frontend streaming methods to accept block_index"
```

---

## Task 6: Create the ChatBlock Widget

**Files:**
- Create: `amplifier_tui/widgets/chat_block.py`
- Test: `tests/test_chat_block.py`

**Step 1: Write the failing test**

Create `tests/test_chat_block.py`:

```python
"""Tests for ChatBlock widget -- Textual Pilot tests."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer

from amplifier_tui.models.block_model import BlockType
from amplifier_tui.widgets.chat_block import BlockSelected, ChatBlock


class ChatBlockTestApp(App):
    """Minimal test app for ChatBlock widget tests."""

    CSS = """
    ChatBlock { height: auto; }
    ChatBlock.selected { background: $accent; }
    ChatBlock:hover { background: $surface; }
    """

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="chat-view"):
            yield ChatBlock(
                block_id=0,
                block_type=BlockType.USER,
                turn_index=0,
                id="block-0",
            )
            yield ChatBlock(
                block_id=1,
                block_type=BlockType.ASSISTANT,
                turn_index=0,
                id="block-1",
            )
            yield ChatBlock(
                block_id=2,
                block_type=BlockType.TOOL_CALL,
                turn_index=1,
                id="block-2",
            )


class TestChatBlockConstruction:
    """ChatBlock widget construction and properties."""

    @pytest.mark.asyncio
    async def test_block_properties(self):
        async with ChatBlockTestApp().run_test() as pilot:
            app = pilot.app
            block = app.query_one("#block-0", ChatBlock)
            assert block.block_id == 0
            assert block.block_type == BlockType.USER
            assert block.turn_index == 0

    @pytest.mark.asyncio
    async def test_block_has_css_class_for_type(self):
        async with ChatBlockTestApp().run_test() as pilot:
            app = pilot.app
            block0 = app.query_one("#block-0", ChatBlock)
            assert block0.has_class("block-user")
            block1 = app.query_one("#block-1", ChatBlock)
            assert block1.has_class("block-assistant")
            block2 = app.query_one("#block-2", ChatBlock)
            assert block2.has_class("block-tool-call")

    @pytest.mark.asyncio
    async def test_three_blocks_rendered(self):
        async with ChatBlockTestApp().run_test() as pilot:
            app = pilot.app
            blocks = app.query(ChatBlock)
            assert len(blocks) == 3


class TestChatBlockMessages:
    """ChatBlock emits BlockSelected message on click."""

    @pytest.mark.asyncio
    async def test_click_emits_block_selected(self):
        messages_received = []

        class ClickTestApp(ChatBlockTestApp):
            def on_block_selected(self, event: BlockSelected) -> None:
                messages_received.append(event.block_id)

        async with ClickTestApp().run_test() as pilot:
            block = pilot.app.query_one("#block-1", ChatBlock)
            await pilot.click(block)
            assert 1 in messages_received
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_chat_block.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'amplifier_tui.widgets.chat_block'`

**Step 3: Write the implementation**

Create `amplifier_tui/widgets/chat_block.py`:

```python
"""ChatBlock widget -- thin wrapper for conversation stream blocks.

Each block in the cockpit conversation stream is wrapped in a ChatBlock.
It provides block metadata, click-to-select behavior, and visual state
(hover, selected) without changing the inner widget rendering.
"""

from __future__ import annotations

from textual.containers import Vertical
from textual.message import Message

from amplifier_tui.models.block_model import BlockType


class BlockSelected(Message):
    """Posted when a ChatBlock is clicked.

    Attributes:
        block_id: The sequential block ID that was selected.
        block_type: The type of block that was selected.
    """

    bubble = True

    def __init__(self, block_id: int, block_type: BlockType) -> None:
        super().__init__()
        self.block_id = block_id
        self.block_type = block_type


class ChatBlock(Vertical):
    """Wrapper widget for a single block in the conversation stream.

    Wraps existing widgets (UserMessage, AssistantMessage, Collapsible, etc.)
    and adds block metadata + click-to-select behavior.

    Args:
        block_id: Sequential integer assigned by BlockRegistry.
        block_type: What kind of block this is.
        turn_index: Conversational turn number.
    """

    def __init__(
        self,
        block_id: int,
        block_type: BlockType,
        turn_index: int,
        *children,
        **kwargs,
    ) -> None:
        # Build CSS class from block type: e.g. "tool_call" -> "block-tool-call"
        type_class = f"block-{block_type.value.replace('_', '-')}"
        classes = kwargs.pop("classes", "")
        if classes:
            classes = f"{classes} chat-block {type_class}"
        else:
            classes = f"chat-block {type_class}"

        super().__init__(*children, classes=classes, **kwargs)

        self._block_id = block_id
        self._block_type = block_type
        self._turn_index = turn_index

    @property
    def block_id(self) -> int:
        return self._block_id

    @property
    def block_type(self) -> BlockType:
        return self._block_type

    @property
    def turn_index(self) -> int:
        return self._turn_index

    def on_click(self) -> None:
        """Post a BlockSelected message when this block is clicked."""
        self.post_message(BlockSelected(self._block_id, self._block_type))

    def select(self) -> None:
        """Mark this block as selected (visual state)."""
        self.add_class("selected")

    def deselect(self) -> None:
        """Remove selected visual state."""
        self.remove_class("selected")
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_chat_block.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/widgets/chat_block.py tests/test_chat_block.py
git commit -m "feat(cockpit): add ChatBlock widget with BlockSelected message"
```

---

## Task 7: Export ChatBlock from widgets __init__.py

**Files:**
- Modify: `amplifier_tui/widgets/__init__.py`

**Step 1: Add the import**

Add to `amplifier_tui/widgets/__init__.py`, after the existing imports:

```python
from .chat_block import BlockSelected, ChatBlock
```

And add `"BlockSelected"` and `"ChatBlock"` to the `__all__` list (alphabetical order).

**Step 2: Run import smoke test**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -c "from amplifier_tui.widgets import ChatBlock, BlockSelected; print('OK')"
```

Expected: `OK`

**Step 3: Run full test suite**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/ -v --timeout=30
```

Expected: All PASS

**Step 4: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/widgets/__init__.py
git commit -m "feat(cockpit): export ChatBlock and BlockSelected from widgets package"
```

---

## Task 8: Add inject_user_message to SessionHandle

**Files:**
- Modify: `amplifier_tui/core/session_manager.py` (add method to `SessionHandle` class)
- Test: `tests/test_session_manager.py` (add tests)

**Step 1: Write the failing test**

Append to `tests/test_session_manager.py`:

```python
class TestSessionHandleInject:
    """SessionHandle.inject_user_message for steering support."""

    def test_inject_queues_message(self):
        """inject_user_message stores the message for later retrieval."""
        handle = SessionHandle(conversation_id="test-inject")
        handle.inject_user_message("steer: focus on tests")
        assert handle.has_pending_inject
        assert handle.pop_pending_inject() == "steer: focus on tests"
        assert not handle.has_pending_inject

    def test_inject_multiple_fifo(self):
        """Multiple injections are FIFO."""
        handle = SessionHandle(conversation_id="test-inject-2")
        handle.inject_user_message("first")
        handle.inject_user_message("second")
        assert handle.pop_pending_inject() == "first"
        assert handle.pop_pending_inject() == "second"
        assert handle.pop_pending_inject() is None

    def test_pop_empty_returns_none(self):
        handle = SessionHandle(conversation_id="test-inject-3")
        assert handle.pop_pending_inject() is None
        assert not handle.has_pending_inject
```

**Step 2: Run test to verify it fails**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_session_manager.py::TestSessionHandleInject -v
```

Expected: FAIL with `AttributeError: 'SessionHandle' object has no attribute 'inject_user_message'`

**Step 3: Write the implementation**

In `amplifier_tui/core/session_manager.py`, add to the `SessionHandle` dataclass (after line 52, after the `on_usage_update` field):

```python
    # --- Steering injection queue ---
    _pending_injects: list[str] = field(default_factory=list)
```

Note: since `SessionHandle` is a `@dataclass`, we need to add the `field` import. Check that `from dataclasses import dataclass, field` is already at the top (it should be from the existing `field` import -- verify it's `dataclass, field` not just `dataclass`). If not, add `field` to the import.

Then add these methods to the `SessionHandle` class (after `reset_usage`, around line 65):

```python
    def inject_user_message(self, message: str) -> None:
        """Queue a steering message for injection at the next pause point."""
        self._pending_injects.append(message)

    def pop_pending_inject(self) -> str | None:
        """Pop the next pending injection, or None if empty."""
        if self._pending_injects:
            return self._pending_injects.pop(0)
        return None

    @property
    def has_pending_inject(self) -> bool:
        """True if there are pending steering messages."""
        return len(self._pending_injects) > 0
```

**Step 4: Run tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_session_manager.py::TestSessionHandleInject -v
```

Expected: All PASS

**Step 5: Run full session manager tests**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/test_session_manager.py -v
```

Expected: All existing tests still PASS

**Step 6: Commit**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git add amplifier_tui/core/session_manager.py tests/test_session_manager.py
git commit -m "feat(cockpit): add inject_user_message to SessionHandle for steering support"
```

---

## Task 9: Full Regression Test

**Files:** None modified -- verification only.

**Step 1: Run the complete test suite**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -m pytest tests/ -v --timeout=60
```

Expected: All tests PASS, including the new `test_block_model.py` and `test_chat_block.py`.

**Step 2: Verify imports work end-to-end**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
python -c "
from amplifier_tui.models import BlockInfo, BlockRegistry, BlockType, SteerQueue
from amplifier_tui.widgets import ChatBlock, BlockSelected
from amplifier_tui.core.session_manager import SessionHandle

# Verify block model
reg = BlockRegistry()
b = reg.add(BlockType.USER, turn_index=0, summary='test')
assert b.block_id == 0

# Verify steer queue
q = SteerQueue()
q.enqueue('hello')
assert q.dequeue() == 'hello'

# Verify inject
h = SessionHandle(conversation_id='test')
h.inject_user_message('steer')
assert h.pop_pending_inject() == 'steer'

print('All Phase 1 integration checks passed!')
"
```

Expected: `All Phase 1 integration checks passed!`

**Step 3: Commit (tag phase completion)**

```bash
cd /home/samschillace/dev/ANext/amplifier-tui
git log --oneline -10
```

Verify the Phase 1 commits are all present. No additional commit needed unless something was missed.

---

## Summary

| Task | What | Files | Tests |
|------|------|-------|-------|
| 1 | BlockInfo + BlockType + model module | models/block_model.py, models/__init__.py | test_block_model.py |
| 2 | BlockRegistry tests | (already implemented) | test_block_model.py |
| 3 | SteerQueue tests | (already implemented) | test_block_model.py |
| 4 | block_index passthrough in SharedAppBase | core/app_base.py | existing tests |
| 5 | Update app.py + web streaming signatures | app.py, web/ | existing tests |
| 6 | ChatBlock widget | widgets/chat_block.py | test_chat_block.py |
| 7 | Export ChatBlock from widgets | widgets/__init__.py | import check |
| 8 | inject_user_message on SessionHandle | core/session_manager.py | test_session_manager.py |
| 9 | Full regression | (none) | all tests |

**Phase 1 delivers:** Pure-data block model with full test coverage, ChatBlock widget with click-to-select, block_index flowing through streaming callbacks, and steering injection support on SessionHandle. Phase 2 builds on all of this.
