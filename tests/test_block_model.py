"""Tests for block model -- pure data, no Textual dependency."""

from __future__ import annotations

import pytest

from amplifier_tui.models.block_model import BlockInfo, BlockRegistry, BlockType, SteerQueue


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
