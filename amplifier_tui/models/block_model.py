"""Block model for Session Cockpit -- pure data, no Textual dependency.

BlockInfo tracks metadata for each block in the conversation stream.
BlockRegistry provides lookup, navigation, and search over blocks.
SteerQueue manages deferred steering messages for the main session.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum


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
        content: Full text content of the block.
    """

    block_id: int
    block_type: BlockType
    turn_index: int
    summary: str = ""
    content: str = ""


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
        content: str = "",
    ) -> BlockInfo:
        """Create and register a new block. Returns the new BlockInfo."""
        block = BlockInfo(
            block_id=len(self._blocks),
            block_type=block_type,
            turn_index=turn_index,
            summary=summary,
            content=content,
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

    def search(
        self, term: str, *, forward: bool = False, from_id: int | None = None
    ) -> BlockInfo | None:
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

    def clear(self) -> None:
        """Remove all blocks, resetting the registry to empty."""
        self._blocks = []

    @property
    def all_blocks(self) -> list[BlockInfo]:
        """Return a copy of all blocks."""
        return list(self._blocks)


class SteerQueue:
    """Queue for steering messages to be injected into the main session.

    Messages are injected at natural pause points (between tool calls,
    before next LLM turn). When the session is idle, steer becomes the
    next regular user message.

    Backpressure: the queue is capped at MAX_SIZE. When full, the oldest
    message is dropped to make room for the new one.
    """

    MAX_SIZE: int = 10

    def __init__(self) -> None:
        self._queue: deque[str] = deque()

    def enqueue(self, message: str) -> None:
        """Add a steering message to the queue.

        If the queue is already at MAX_SIZE, the oldest message is dropped
        before the new one is appended.
        """
        if len(self._queue) >= self.MAX_SIZE:
            self._queue.popleft()
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

    @property
    def is_full(self) -> bool:
        """True if the queue has reached MAX_SIZE."""
        return len(self._queue) >= self.MAX_SIZE

    def __len__(self) -> int:
        return len(self._queue)

    def clear(self) -> None:
        """Discard all queued messages."""
        self._queue.clear()
