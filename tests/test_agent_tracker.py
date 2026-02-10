"""Tests for the agent delegation tracker (F2.1)."""

from __future__ import annotations

import time

from amplifier_tui.features.agent_tracker import (
    AgentNode,
    AgentTracker,
    is_delegate_tool,
    make_delegate_key,
)
from amplifier_tui.commands.agent_cmds import AgentCommandsMixin


# ===========================================================================
# is_delegate_tool
# ===========================================================================


class TestIsDelegateTool:
    def test_delegate(self):
        assert is_delegate_tool("delegate") is True

    def test_task(self):
        assert is_delegate_tool("task") is True

    def test_other_tool(self):
        assert is_delegate_tool("bash") is False

    def test_empty(self):
        assert is_delegate_tool("") is False


# ===========================================================================
# make_delegate_key
# ===========================================================================


class TestMakeDelegateKey:
    def test_normal_input(self):
        key = make_delegate_key(
            {"agent": "foundation:explorer", "instruction": "Search"}
        )
        assert key == "foundation:explorer:Search"

    def test_missing_agent(self):
        key = make_delegate_key({"instruction": "Search"})
        assert key == ":Search"

    def test_missing_instruction(self):
        key = make_delegate_key({"agent": "self"})
        assert key == "self:"

    def test_non_dict_input(self):
        assert make_delegate_key("string") == ""
        assert make_delegate_key(None) == ""

    def test_long_instruction_truncated(self):
        long = "x" * 200
        key = make_delegate_key({"agent": "a", "instruction": long})
        # Key uses first 100 chars of instruction
        assert key == f"a:{long[:100]}"


# ===========================================================================
# AgentNode dataclass
# ===========================================================================


class TestAgentNode:
    def test_defaults(self):
        node = AgentNode(
            agent_name="test",
            instruction="do stuff",
            status="running",
            start_time=1.0,
        )
        assert node.end_time is None
        assert node.result_preview == ""
        assert node.children == []
        assert node.tool_use_id == ""


# ===========================================================================
# AgentTracker — start / complete lifecycle
# ===========================================================================


class TestAgentTrackerStart:
    def test_creates_node(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "foundation:explorer", "Survey modules")
        assert tracker.total == 1
        assert tracker.running_count == 1
        assert tracker.has_delegations is True

    def test_node_has_running_status(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "self", "Build feature")
        assert tracker._roots[0].status == "running"
        assert tracker._roots[0].agent_name == "self"

    def test_long_instruction_truncated(self):
        tracker = AgentTracker()
        long_instr = "a" * 300
        tracker.on_delegate_start("k1", "agent", long_instr)
        node = tracker._roots[0]
        assert len(node.instruction) == 201  # 200 + "…"
        assert node.instruction.endswith("…")

    def test_empty_agent_becomes_unknown(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "", "do stuff")
        assert tracker._roots[0].agent_name == "unknown"


class TestAgentTrackerComplete:
    def test_marks_completed(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "agent", "work")
        tracker.on_delegate_complete("k1", result="done", status="completed")
        assert tracker.completed_count == 1
        assert tracker.running_count == 0
        node = tracker._roots[0]
        assert node.status == "completed"
        assert node.end_time is not None
        assert node.result_preview == "done"

    def test_marks_failed(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "agent", "work")
        tracker.on_delegate_complete("k1", result="Error: boom", status="failed")
        assert tracker.failed_count == 1
        assert tracker.completed_count == 0
        assert tracker._roots[0].status == "failed"

    def test_unknown_id_skipped(self):
        tracker = AgentTracker()
        tracker.on_delegate_complete("nonexistent", result="x")
        assert tracker.total == 0
        assert tracker.completed_count == 0

    def test_long_result_truncated(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "agent", "work")
        tracker.on_delegate_complete("k1", result="r" * 300)
        node = tracker._roots[0]
        assert len(node.result_preview) == 201  # 200 + "…"

    def test_elapsed_time_positive(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "agent", "work")
        time.sleep(0.01)
        tracker.on_delegate_complete("k1", result="ok")
        node = tracker._roots[0]
        assert node.end_time is not None
        assert node.end_time > node.start_time


# ===========================================================================
# Multiple delegations
# ===========================================================================


class TestAgentTrackerMultiple:
    def test_multiple_roots(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "agent-a", "task 1")
        tracker.on_delegate_start("k2", "agent-b", "task 2")
        assert tracker.total == 2
        assert tracker.running_count == 2

    def test_mixed_statuses(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "a", "t1")
        tracker.on_delegate_start("k2", "b", "t2")
        tracker.on_delegate_start("k3", "c", "t3")
        tracker.on_delegate_complete("k1", "ok")
        tracker.on_delegate_complete("k3", "Error", status="failed")
        assert tracker.total == 3
        assert tracker.completed_count == 1
        assert tracker.failed_count == 1
        assert tracker.running_count == 1


# ===========================================================================
# Clear
# ===========================================================================


class TestAgentTrackerClear:
    def test_clears_everything(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "agent", "work")
        tracker.on_delegate_complete("k1", "done")
        tracker.on_delegate_start("k2", "agent", "more")
        tracker.clear()
        assert tracker.total == 0
        assert tracker.running_count == 0
        assert tracker.completed_count == 0
        assert tracker.failed_count == 0
        assert tracker.has_delegations is False


# ===========================================================================
# format_tree
# ===========================================================================


class TestFormatTree:
    def test_empty_tree(self):
        tracker = AgentTracker()
        result = tracker.format_tree()
        assert "No agent delegations" in result

    def test_single_completed(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "foundation:explorer", "Survey code")
        tracker.on_delegate_complete("k1", "Found 3 files")
        tree = tracker.format_tree()
        assert "Agent Delegations:" in tree
        assert "foundation:explorer" in tree
        assert "Survey code" in tree
        assert "✓" in tree

    def test_running_shows_yellow(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "self", "Build feature")
        tree = tracker.format_tree()
        assert "⟳" in tree
        assert "self" in tree

    def test_failed_shows_red(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "agent", "work")
        tracker.on_delegate_complete("k1", "Error", status="failed")
        tree = tracker.format_tree()
        assert "✗" in tree

    def test_children_indented(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "parent", "do stuff")
        # Manually add a child to test rendering
        child = AgentNode(
            agent_name="child-agent",
            instruction="sub task",
            status="completed",
            start_time=time.monotonic(),
            end_time=time.monotonic() + 1.0,
        )
        tracker._roots[0].children.append(child)
        tree = tracker.format_tree()
        assert "child-agent" in tree
        # Child should be more indented than parent
        lines = tree.split("\n")
        parent_line = [line for line in lines if "parent" in line][0]
        child_line = [line for line in lines if "child-agent" in line][0]
        assert len(child_line) - len(child_line.lstrip()) > len(parent_line) - len(
            parent_line.lstrip()
        )


# ===========================================================================
# format_summary
# ===========================================================================


class TestFormatSummary:
    def test_empty(self):
        tracker = AgentTracker()
        assert "No agent delegations" in tracker.format_summary()

    def test_counts_correct(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "a", "t1")
        tracker.on_delegate_start("k2", "b", "t2")
        tracker.on_delegate_complete("k1", "ok")
        summary = tracker.format_summary()
        assert "2 agent(s)" in summary
        assert "1 completed" in summary
        assert "1 running" in summary

    def test_includes_time(self):
        tracker = AgentTracker()
        tracker.on_delegate_start("k1", "a", "t1")
        time.sleep(0.01)
        tracker.on_delegate_complete("k1", "ok")
        summary = tracker.format_summary()
        assert "total" in summary


# ===========================================================================
# Command mixin
# ===========================================================================


class TestAgentCommandsMixin:
    def test_has_cmd_agents(self):
        assert hasattr(AgentCommandsMixin, "_cmd_agents")

    def test_mixin_is_a_class(self):
        assert isinstance(AgentCommandsMixin, type)
