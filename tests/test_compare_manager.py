"""Tests for the Model A/B testing manager (F3.2).

Tests cover the CompareManager and ComparisonResult dataclass in isolation,
plus importability checks for the CompareCommandsMixin.
"""

from __future__ import annotations

import pytest

from amplifier_tui.features.compare_manager import CompareManager, ComparisonResult
from amplifier_tui.commands.compare_cmds import CompareCommandsMixin


# ═══════════════════════════════════════════════════════════════════════════
# ComparisonResult dataclass
# ═══════════════════════════════════════════════════════════════════════════


class TestComparisonResult:
    def test_defaults(self):
        r = ComparisonResult(prompt="hello", model_a="sonnet", model_b="gpt-4o")
        assert r.prompt == "hello"
        assert r.model_a == "sonnet"
        assert r.model_b == "gpt-4o"
        assert r.response_a == ""
        assert r.response_b == ""
        assert r.time_a_ms == 0
        assert r.time_b_ms == 0
        assert r.tokens_a == 0
        assert r.tokens_b == 0
        assert r.picked == ""

    def test_created_at_set(self):
        r = ComparisonResult(prompt="test", model_a="a", model_b="b")
        assert r.created_at is not None

    def test_picked_model_a(self):
        r = ComparisonResult(
            prompt="test", model_a="sonnet", model_b="gpt-4o", picked="a"
        )
        assert r.picked_model == "sonnet"

    def test_picked_model_b(self):
        r = ComparisonResult(
            prompt="test", model_a="sonnet", model_b="gpt-4o", picked="b"
        )
        assert r.picked_model == "gpt-4o"

    def test_picked_model_empty(self):
        r = ComparisonResult(prompt="test", model_a="sonnet", model_b="gpt-4o")
        assert r.picked_model == ""


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — Initial State
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerInit:
    def test_not_active(self):
        mgr = CompareManager()
        assert mgr.is_active is False

    def test_no_models(self):
        mgr = CompareManager()
        assert mgr.model_a == ""
        assert mgr.model_b == ""

    def test_no_current(self):
        mgr = CompareManager()
        assert mgr.current is None

    def test_empty_history(self):
        mgr = CompareManager()
        assert mgr.history == []


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — activate()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerActivate:
    def test_activate_sets_models(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        assert mgr.is_active is True
        assert mgr.model_a == "sonnet"
        assert mgr.model_b == "gpt-4o"

    def test_activate_raises_for_same_models(self):
        mgr = CompareManager()
        with pytest.raises(ValueError, match="different"):
            mgr.activate("sonnet", "sonnet")

    def test_activate_raises_for_empty_model_a(self):
        mgr = CompareManager()
        with pytest.raises(ValueError, match="required"):
            mgr.activate("", "gpt-4o")

    def test_activate_raises_for_empty_model_b(self):
        mgr = CompareManager()
        with pytest.raises(ValueError, match="required"):
            mgr.activate("sonnet", "")

    def test_activate_raises_for_both_empty(self):
        mgr = CompareManager()
        with pytest.raises(ValueError, match="required"):
            mgr.activate("", "")


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — deactivate()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerDeactivate:
    def test_deactivate_clears_mode(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.deactivate()
        assert mgr.is_active is False
        assert mgr.model_a == ""
        assert mgr.model_b == ""

    def test_deactivate_moves_current_to_history(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test prompt")
        mgr.deactivate()
        assert mgr.current is None
        assert len(mgr.history) == 1
        assert mgr.history[0].prompt == "test prompt"

    def test_deactivate_without_current(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.deactivate()
        assert mgr.history == []


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — start_comparison()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerStartComparison:
    def test_creates_comparison(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        result = mgr.start_comparison("explain this code")
        assert result.prompt == "explain this code"
        assert result.model_a == "sonnet"
        assert result.model_b == "gpt-4o"
        assert mgr.current is result

    def test_raises_when_not_active(self):
        mgr = CompareManager()
        with pytest.raises(RuntimeError, match="Not in A/B"):
            mgr.start_comparison("test")

    def test_archives_previous_current(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        first = mgr.start_comparison("first prompt")
        second = mgr.start_comparison("second prompt")
        assert mgr.current is second
        assert len(mgr.history) == 1
        assert mgr.history[0] is first

    def test_prompt_truncated_to_500(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        long_prompt = "x" * 1000
        result = mgr.start_comparison(long_prompt)
        assert len(result.prompt) == 500


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — set_response_a / set_response_b
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerSetResponses:
    def test_set_response_a(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        mgr.set_response_a("answer from A", time_ms=150.0, tokens=42)
        assert mgr.current is not None
        assert mgr.current.response_a == "answer from A"
        assert mgr.current.time_a_ms == 150.0
        assert mgr.current.tokens_a == 42

    def test_set_response_b(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        mgr.set_response_b("answer from B", time_ms=200.0, tokens=55)
        assert mgr.current is not None
        assert mgr.current.response_b == "answer from B"
        assert mgr.current.time_b_ms == 200.0
        assert mgr.current.tokens_b == 55

    def test_set_response_no_current(self):
        """Setting response when no current is a no-op (no error)."""
        mgr = CompareManager()
        mgr.set_response_a("test")  # Should not raise
        mgr.set_response_b("test")  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — pick()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerPick:
    def test_pick_a(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        result = mgr.pick("a")
        assert result is not None
        assert result.picked == "a"
        assert result.picked_model == "sonnet"
        assert mgr.current is None
        assert len(mgr.history) == 1

    def test_pick_b(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        result = mgr.pick("b")
        assert result is not None
        assert result.picked == "b"
        assert result.picked_model == "gpt-4o"

    def test_pick_left_alias(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        result = mgr.pick("left")
        assert result is not None
        assert result.picked == "a"

    def test_pick_right_alias(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        result = mgr.pick("right")
        assert result is not None
        assert result.picked == "b"

    def test_pick_invalid_choice(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        with pytest.raises(ValueError, match="Invalid choice"):
            mgr.pick("middle")

    def test_pick_no_current(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        result = mgr.pick("a")
        assert result is None

    def test_pick_archives_to_history(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("prompt 1")
        mgr.pick("a")
        mgr.start_comparison("prompt 2")
        mgr.pick("b")
        assert len(mgr.history) == 2
        assert mgr.history[0].picked == "a"
        assert mgr.history[1].picked == "b"


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — format_status()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerFormatStatus:
    def test_inactive_status(self):
        mgr = CompareManager()
        status = mgr.format_status()
        assert "not active" in status
        assert "/compare" in status

    def test_active_status(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        status = mgr.format_status()
        assert "ACTIVE" in status
        assert "sonnet" in status
        assert "gpt-4o" in status

    def test_active_with_current(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test prompt")
        status = mgr.format_status()
        assert "awaiting pick" in status

    def test_shows_history_count(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("p1")
        mgr.pick("a")
        status = mgr.format_status()
        assert "1" in status


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — format_comparison()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerFormatComparison:
    def test_no_current(self):
        mgr = CompareManager()
        output = mgr.format_comparison()
        assert "No comparison" in output

    def test_with_responses(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        mgr.set_response_a("Response from A", time_ms=100, tokens=20)
        mgr.set_response_b("Response from B", time_ms=200, tokens=30)
        output = mgr.format_comparison()
        assert "sonnet" in output
        assert "gpt-4o" in output
        assert "Response from A" in output
        assert "Response from B" in output
        assert "100ms" in output
        assert "200ms" in output

    def test_with_pick(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        mgr.set_response_a("A says hi")
        result = mgr.pick("a")
        output = mgr.format_comparison(result)
        assert "PICKED" in output

    def test_explicit_result_parameter(self):
        result = ComparisonResult(
            prompt="custom",
            model_a="m1",
            model_b="m2",
            response_a="resp-a",
            response_b="resp-b",
        )
        mgr = CompareManager()
        output = mgr.format_comparison(result)
        assert "m1" in output
        assert "m2" in output
        assert "pick" in output.lower()

    def test_no_response_yet(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        output = mgr.format_comparison()
        assert "No response yet" in output


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — format_history()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerFormatHistory:
    def test_empty_history(self):
        mgr = CompareManager()
        output = mgr.format_history()
        assert "No comparisons yet" in output

    def test_with_current_no_history(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        output = mgr.format_history()
        # Should display current comparison
        assert "sonnet" in output

    def test_with_entries(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("prompt one")
        mgr.pick("a")
        mgr.start_comparison("prompt two")
        mgr.pick("b")
        output = mgr.format_history()
        assert "2 comparisons" in output
        assert "prompt one" in output
        assert "prompt two" in output

    def test_score_summary(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("p1")
        mgr.pick("a")
        mgr.start_comparison("p2")
        mgr.pick("a")
        mgr.start_comparison("p3")
        mgr.pick("b")
        output = mgr.format_history()
        assert "Score:" in output
        assert "2" in output  # sonnet wins
        assert "1" in output  # gpt-4o wins

    def test_no_pick_shown(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("no pick prompt")
        # Deactivate moves current to history without a pick
        mgr.deactivate()
        output = mgr.format_history()
        assert "no pick" in output


# ═══════════════════════════════════════════════════════════════════════════
# CompareManager — clear()
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareManagerClear:
    def test_clear_resets_everything(self):
        mgr = CompareManager()
        mgr.activate("sonnet", "gpt-4o")
        mgr.start_comparison("test")
        mgr.pick("a")
        mgr.start_comparison("test2")
        mgr.clear()
        assert mgr.is_active is False
        assert mgr.model_a == ""
        assert mgr.model_b == ""
        assert mgr.current is None
        assert mgr.history == []

    def test_clear_when_empty(self):
        mgr = CompareManager()
        mgr.clear()  # Should not raise
        assert mgr.is_active is False


# ═══════════════════════════════════════════════════════════════════════════
# Full Workflow
# ═══════════════════════════════════════════════════════════════════════════


class TestFullWorkflow:
    def test_activate_compare_pick_deactivate(self):
        mgr = CompareManager()

        # Activate
        mgr.activate("claude-sonnet", "gpt-4o")
        assert mgr.is_active is True

        # Start comparison
        result = mgr.start_comparison("What is Python?")
        assert result.prompt == "What is Python?"

        # Set responses
        mgr.set_response_a("Python is a language", time_ms=120, tokens=5)
        mgr.set_response_b("Python is a snake", time_ms=80, tokens=4)

        # Pick
        picked = mgr.pick("left")
        assert picked is not None
        assert picked.picked_model == "claude-sonnet"
        assert picked.response_a == "Python is a language"
        assert picked.response_b == "Python is a snake"

        # History should have one entry
        assert len(mgr.history) == 1

        # Start another comparison
        mgr.start_comparison("What is Rust?")
        mgr.set_response_a("Rust is a systems language", time_ms=100, tokens=6)
        mgr.set_response_b("Rust is oxidation", time_ms=90, tokens=3)
        picked2 = mgr.pick("right")
        assert picked2 is not None
        assert picked2.picked_model == "gpt-4o"

        # History should have two entries
        assert len(mgr.history) == 2

        # Check history output
        history_output = mgr.format_history()
        assert "2 comparisons" in history_output
        assert "Score:" in history_output

        # Deactivate
        mgr.deactivate()
        assert mgr.is_active is False

    def test_multiple_comparisons_without_picks(self):
        mgr = CompareManager()
        mgr.activate("m1", "m2")

        mgr.start_comparison("p1")
        mgr.start_comparison("p2")  # archives p1
        mgr.start_comparison("p3")  # archives p2

        # Two in history (p1, p2), one current (p3)
        assert len(mgr.history) == 2
        assert mgr.current is not None
        assert mgr.current.prompt == "p3"

        mgr.deactivate()
        # p3 now in history too
        assert len(mgr.history) == 3


# ═══════════════════════════════════════════════════════════════════════════
# CompareCommandsMixin — Importability
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareCommandsMixin:
    def test_mixin_is_importable(self):
        assert isinstance(CompareCommandsMixin, type)

    def test_has_cmd_compare(self):
        assert hasattr(CompareCommandsMixin, "_cmd_compare")

    def test_cmd_compare_is_callable(self):
        assert callable(getattr(CompareCommandsMixin, "_cmd_compare"))
