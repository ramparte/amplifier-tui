"""Tests for the conversation branch manager (F3.1).

Tests cover the BranchManager and ConversationBranch dataclass in isolation,
plus importability checks for the BranchCommandsMixin.
"""

from __future__ import annotations

import pytest

from amplifier_tui.features.branch_manager import BranchManager, ConversationBranch
from amplifier_tui.commands.branch_cmds import BranchCommandsMixin


# ═══════════════════════════════════════════════════════════════════════
# ConversationBranch dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestConversationBranch:
    def test_defaults(self):
        b = ConversationBranch(name="test")
        assert b.name == "test"
        assert b.parent_branch == "main"
        assert b.fork_point == 0
        assert b.messages == []
        assert b.description == ""

    def test_message_count_empty(self):
        b = ConversationBranch(name="test")
        assert b.message_count == 0

    def test_message_count_with_messages(self):
        b = ConversationBranch(name="test", messages=[{"role": "user", "text": "hi"}])
        assert b.message_count == 1

    def test_created_at_set(self):
        b = ConversationBranch(name="test")
        assert b.created_at is not None


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — Initial State
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerInit:
    def test_main_branch_exists(self):
        mgr = BranchManager()
        assert mgr.get_branch("main") is not None

    def test_current_branch_is_main(self):
        mgr = BranchManager()
        assert mgr.current_branch == "main"

    def test_branch_names_includes_main(self):
        mgr = BranchManager()
        assert "main" in mgr.branch_names

    def test_branch_names_sorted(self):
        mgr = BranchManager()
        mgr.fork("beta", fork_point=5)
        mgr.fork("alpha", fork_point=3)
        assert mgr.branch_names == ["alpha", "beta", "main"]


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — fork()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerFork:
    def test_fork_creates_branch(self):
        mgr = BranchManager()
        branch = mgr.fork("feature", fork_point=5)
        assert branch.name == "feature"
        assert branch.parent_branch == "main"
        assert branch.fork_point == 5

    def test_fork_with_description(self):
        mgr = BranchManager()
        branch = mgr.fork("feature", fork_point=5, description="Try new approach")
        assert branch.description == "Try new approach"

    def test_fork_with_snapshot(self):
        mgr = BranchManager()
        msgs = [{"role": "user", "text": "hello"}]
        branch = mgr.fork("feature", fork_point=1, snapshot_messages=msgs)
        assert branch.messages == msgs
        # Snapshot is a copy
        msgs.append({"role": "assistant", "text": "world"})
        assert len(branch.messages) == 1

    def test_fork_records_parent(self):
        mgr = BranchManager()
        mgr.fork("child", fork_point=3)
        mgr.switch("child")
        mgr.fork("grandchild", fork_point=1)
        gc = mgr.get_branch("grandchild")
        assert gc is not None
        assert gc.parent_branch == "child"

    def test_fork_duplicate_name_raises(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        with pytest.raises(ValueError, match="already exists"):
            mgr.fork("feature", fork_point=2)

    def test_fork_main_name_raises(self):
        mgr = BranchManager()
        with pytest.raises(ValueError, match="Invalid branch name"):
            mgr.fork("main", fork_point=1)

    def test_fork_empty_name_raises(self):
        mgr = BranchManager()
        with pytest.raises(ValueError, match="Invalid branch name"):
            mgr.fork("", fork_point=1)

    def test_fork_does_not_switch_branch(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=5)
        assert mgr.current_branch == "main"


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — switch()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerSwitch:
    def test_switch_changes_current(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        result = mgr.switch("feature")
        assert mgr.current_branch == "feature"
        assert result.name == "feature"

    def test_switch_to_main(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.switch("feature")
        mgr.switch("main")
        assert mgr.current_branch == "main"

    def test_switch_nonexistent_raises(self):
        mgr = BranchManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.switch("nonexistent")


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — add_message()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerAddMessage:
    def test_add_to_non_main_branch(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.switch("feature")
        mgr.add_message({"role": "user", "text": "hello"})
        branch = mgr.get_branch("feature")
        assert branch is not None
        assert branch.message_count == 1

    def test_add_to_main_is_noop(self):
        mgr = BranchManager()
        mgr.add_message({"role": "user", "text": "hello"})
        branch = mgr.get_branch("main")
        assert branch is not None
        assert branch.message_count == 0

    def test_add_multiple_messages(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=0)
        mgr.switch("feature")
        mgr.add_message({"role": "user", "text": "one"})
        mgr.add_message({"role": "assistant", "text": "two"})
        mgr.add_message({"role": "user", "text": "three"})
        branch = mgr.get_branch("feature")
        assert branch is not None
        assert branch.message_count == 3


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — delete_branch()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerDelete:
    def test_delete_removes_branch(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.delete_branch("feature")
        assert mgr.get_branch("feature") is None

    def test_delete_main_raises(self):
        mgr = BranchManager()
        with pytest.raises(ValueError, match="Cannot delete main"):
            mgr.delete_branch("main")

    def test_delete_nonexistent_raises(self):
        mgr = BranchManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.delete_branch("nonexistent")

    def test_delete_current_switches_to_main(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.switch("feature")
        mgr.delete_branch("feature")
        assert mgr.current_branch == "main"

    def test_delete_non_current_keeps_current(self):
        mgr = BranchManager()
        mgr.fork("alpha", fork_point=1)
        mgr.fork("beta", fork_point=2)
        mgr.switch("alpha")
        mgr.delete_branch("beta")
        assert mgr.current_branch == "alpha"


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — merge_messages()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerMerge:
    def test_merge_returns_messages(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.switch("feature")
        mgr.add_message({"role": "user", "text": "hello"})
        mgr.add_message({"role": "assistant", "text": "world"})
        mgr.switch("main")
        messages = mgr.merge_messages("feature")
        assert len(messages) == 2

    def test_merge_returns_copy(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.switch("feature")
        mgr.add_message({"role": "user", "text": "hello"})
        mgr.switch("main")
        messages = mgr.merge_messages("feature")
        messages.append({"role": "user", "text": "extra"})
        assert mgr.get_branch("feature") is not None
        assert mgr.get_branch("feature").message_count == 1

    def test_merge_empty_branch(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        messages = mgr.merge_messages("feature")
        assert messages == []

    def test_merge_nonexistent_raises(self):
        mgr = BranchManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.merge_messages("nonexistent")


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — format_tree()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerFormatTree:
    def test_no_branches_shows_minimal(self):
        mgr = BranchManager()
        tree = mgr.format_tree()
        assert "main" in tree
        assert "no branches yet" in tree

    def test_single_branch(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=5, description="Try it")
        tree = mgr.format_tree()
        assert "main" in tree
        assert "feature" in tree
        assert "@msg 5" in tree

    def test_multiple_branches(self):
        mgr = BranchManager()
        mgr.fork("alpha", fork_point=3)
        mgr.fork("beta", fork_point=7)
        tree = mgr.format_tree()
        assert "alpha" in tree
        assert "beta" in tree

    def test_current_marker_on_main(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        tree = mgr.format_tree()
        assert "<-- current" in tree

    def test_current_marker_on_branch(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.switch("feature")
        tree = mgr.format_tree()
        assert "<-- current" in tree

    def test_nested_branches(self):
        mgr = BranchManager()
        mgr.fork("child", fork_point=5)
        mgr.switch("child")
        mgr.fork("grandchild", fork_point=2)
        tree = mgr.format_tree()
        assert "child" in tree
        assert "grandchild" in tree

    def test_message_count_in_tree(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.switch("feature")
        mgr.add_message({"role": "user", "text": "hi"})
        mgr.add_message({"role": "assistant", "text": "hello"})
        tree = mgr.format_tree()
        assert "(2 messages)" in tree

    def test_empty_branch_in_tree(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        tree = mgr.format_tree()
        assert "(empty)" in tree

    def test_description_in_tree(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1, description="new approach")
        tree = mgr.format_tree()
        assert "new approach" in tree


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — format_compare()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerFormatCompare:
    def test_compare_two_branches(self):
        mgr = BranchManager()
        mgr.fork("alpha", fork_point=3)
        mgr.fork("beta", fork_point=7)
        result = mgr.format_compare("alpha", "beta")
        assert "alpha" in result
        assert "beta" in result
        assert "Comparing branches" in result

    def test_compare_with_main(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=5)
        result = mgr.format_compare("main", "feature")
        assert "main" in result
        assert "feature" in result

    def test_compare_missing_first(self):
        mgr = BranchManager()
        result = mgr.format_compare("nonexistent", "main")
        assert "not found" in result

    def test_compare_missing_second(self):
        mgr = BranchManager()
        result = mgr.format_compare("main", "nonexistent")
        assert "not found" in result

    def test_compare_shows_details(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=5)
        result = mgr.format_compare("main", "feature")
        assert "Fork point" in result
        assert "Messages" in result
        assert "Parent" in result


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — clear()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerClear:
    def test_clear_resets_to_initial(self):
        mgr = BranchManager()
        mgr.fork("alpha", fork_point=1)
        mgr.fork("beta", fork_point=2)
        mgr.switch("alpha")
        mgr.clear()
        assert mgr.current_branch == "main"
        assert mgr.branch_names == ["main"]

    def test_clear_preserves_main(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        mgr.clear()
        assert mgr.get_branch("main") is not None


# ═══════════════════════════════════════════════════════════════════════
# BranchManager — get_branch()
# ═══════════════════════════════════════════════════════════════════════


class TestBranchManagerGetBranch:
    def test_get_existing(self):
        mgr = BranchManager()
        mgr.fork("feature", fork_point=1)
        branch = mgr.get_branch("feature")
        assert branch is not None
        assert branch.name == "feature"

    def test_get_nonexistent_returns_none(self):
        mgr = BranchManager()
        assert mgr.get_branch("nonexistent") is None

    def test_get_main(self):
        mgr = BranchManager()
        branch = mgr.get_branch("main")
        assert branch is not None
        assert branch.name == "main"


# ═══════════════════════════════════════════════════════════════════════
# Nested branching (fork from a fork)
# ═══════════════════════════════════════════════════════════════════════


class TestNestedBranching:
    def test_fork_from_fork(self):
        mgr = BranchManager()
        mgr.fork("level1", fork_point=5)
        mgr.switch("level1")
        mgr.add_message({"role": "user", "text": "in level1"})
        mgr.fork("level2", fork_point=1)
        mgr.switch("level2")
        mgr.add_message({"role": "user", "text": "in level2"})

        level2 = mgr.get_branch("level2")
        assert level2 is not None
        assert level2.parent_branch == "level1"
        assert level2.message_count == 1

    def test_three_level_nesting(self):
        mgr = BranchManager()
        mgr.fork("a", fork_point=1)
        mgr.switch("a")
        mgr.fork("b", fork_point=0)
        mgr.switch("b")
        mgr.fork("c", fork_point=0)

        c = mgr.get_branch("c")
        assert c is not None
        assert c.parent_branch == "b"
        b = mgr.get_branch("b")
        assert b is not None
        assert b.parent_branch == "a"

    def test_nested_tree_rendering(self):
        mgr = BranchManager()
        mgr.fork("parent", fork_point=5)
        mgr.switch("parent")
        mgr.fork("child", fork_point=2)
        tree = mgr.format_tree()
        # Both should appear in the tree
        assert "parent" in tree
        assert "child" in tree


# ═══════════════════════════════════════════════════════════════════════
# BranchCommandsMixin — importability and attribute checks
# ═══════════════════════════════════════════════════════════════════════


class TestBranchCommandsMixin:
    def test_mixin_is_importable(self):
        assert isinstance(BranchCommandsMixin, type)

    def test_has_cmd_fork(self):
        assert hasattr(BranchCommandsMixin, "_cmd_fork")

    def test_has_cmd_branches(self):
        assert hasattr(BranchCommandsMixin, "_cmd_branches")

    def test_has_cmd_branch(self):
        assert hasattr(BranchCommandsMixin, "_cmd_branch")
