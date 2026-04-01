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
