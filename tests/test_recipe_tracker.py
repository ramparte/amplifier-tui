"""Tests for the recipe pipeline tracker (F2.3)."""

from __future__ import annotations

from datetime import datetime, timedelta

from amplifier_tui.features.recipe_tracker import (
    RecipeRun,
    RecipeStep,
    RecipeTracker,
    _step_icon,
)
from amplifier_tui.commands.recipe_cmds import RecipeCommandsMixin


# ===========================================================================
# RecipeStep
# ===========================================================================


class TestRecipeStep:
    def test_defaults(self):
        step = RecipeStep(index=1, name="Explore codebase")
        assert step.index == 1
        assert step.name == "Explore codebase"
        assert step.status == "pending"
        assert step.start_time is None
        assert step.end_time is None
        assert step.result_preview == ""
        assert step.error_message == ""
        assert step.is_approval_gate is False

    def test_duration_str_no_start(self):
        step = RecipeStep(index=1, name="step")
        assert step.duration_str == ""

    def test_duration_str_seconds(self):
        now = datetime.now()
        step = RecipeStep(
            index=1,
            name="step",
            start_time=now - timedelta(seconds=42),
            end_time=now,
        )
        assert step.duration_str == "42s"

    def test_duration_str_minutes(self):
        now = datetime.now()
        step = RecipeStep(
            index=1,
            name="step",
            start_time=now - timedelta(minutes=4, seconds=22),
            end_time=now,
        )
        assert step.duration_str == "4m22s"

    def test_duration_str_running_no_end(self):
        """When end_time is None, uses datetime.now() -- result should be non-empty."""
        step = RecipeStep(
            index=1,
            name="step",
            start_time=datetime.now() - timedelta(seconds=5),
        )
        dur = step.duration_str
        assert dur != ""
        # Should be a number followed by 's'
        assert dur.endswith("s")

    def test_duration_str_zero_seconds(self):
        now = datetime.now()
        step = RecipeStep(index=1, name="step", start_time=now, end_time=now)
        assert step.duration_str == "0s"

    def test_duration_str_exact_minute(self):
        now = datetime.now()
        step = RecipeStep(
            index=1,
            name="step",
            start_time=now - timedelta(minutes=1),
            end_time=now,
        )
        assert step.duration_str == "1m00s"


# ===========================================================================
# RecipeRun
# ===========================================================================


class TestRecipeRun:
    def test_defaults(self):
        run = RecipeRun(recipe_name="code-review")
        assert run.recipe_name == "code-review"
        assert run.session_id == ""
        assert run.source_file == ""
        assert run.steps == []
        assert run.status == "running"
        assert run.end_time is None
        assert isinstance(run.start_time, datetime)

    def test_current_step_index_none_running(self):
        run = RecipeRun(
            recipe_name="test",
            steps=[
                RecipeStep(index=1, name="a", status="completed"),
                RecipeStep(index=2, name="b", status="pending"),
            ],
        )
        assert run.current_step_index == 0

    def test_current_step_index_with_running(self):
        run = RecipeRun(
            recipe_name="test",
            steps=[
                RecipeStep(index=1, name="a", status="completed"),
                RecipeStep(index=2, name="b", status="running"),
                RecipeStep(index=3, name="c", status="pending"),
            ],
        )
        assert run.current_step_index == 2

    def test_completed_count(self):
        run = RecipeRun(
            recipe_name="test",
            steps=[
                RecipeStep(index=1, name="a", status="completed"),
                RecipeStep(index=2, name="b", status="completed"),
                RecipeStep(index=3, name="c", status="running"),
                RecipeStep(index=4, name="d", status="pending"),
            ],
        )
        assert run.completed_count == 2

    def test_total_steps(self):
        run = RecipeRun(
            recipe_name="test",
            steps=[
                RecipeStep(index=1, name="a"),
                RecipeStep(index=2, name="b"),
                RecipeStep(index=3, name="c"),
            ],
        )
        assert run.total_steps == 3

    def test_total_steps_empty(self):
        run = RecipeRun(recipe_name="test")
        assert run.total_steps == 0
        assert run.completed_count == 0
        assert run.current_step_index == 0


# ===========================================================================
# _step_icon
# ===========================================================================


class TestStepIcon:
    def test_completed(self):
        assert _step_icon("completed") == "[green][x][/green]"

    def test_running(self):
        assert _step_icon("running") == "[yellow][>][/yellow]"

    def test_failed(self):
        assert _step_icon("failed") == "[red][!][/red]"

    def test_approval(self):
        assert _step_icon("approval") == "[cyan][?][/cyan]"

    def test_pending(self):
        assert _step_icon("pending") == "[ ]"

    def test_unknown_status(self):
        assert _step_icon("whatever") == "[ ]"


# ===========================================================================
# RecipeTracker lifecycle
# ===========================================================================


class TestRecipeTrackerLifecycle:
    def test_initial_state(self):
        tracker = RecipeTracker()
        assert tracker.current is None
        assert tracker.history == []

    def test_on_recipe_start(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start(
            "code-review",
            ["Explore", "Analyze", "Report"],
            session_id="sess-1",
            source_file="recipes/code-review.yaml",
        )
        run = tracker.current
        assert run is not None
        assert run.recipe_name == "code-review"
        assert run.session_id == "sess-1"
        assert run.source_file == "recipes/code-review.yaml"
        assert run.total_steps == 3
        assert run.steps[0].name == "Explore"
        assert run.steps[0].index == 1
        assert run.steps[1].index == 2
        assert run.steps[2].index == 3

    def test_on_step_start(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Step A", "Step B"])
        tracker.on_step_start(1)

        step = tracker.current.steps[0]  # type: ignore[union-attr]
        assert step.status == "running"
        assert step.start_time is not None

    def test_on_step_start_no_current(self):
        """on_step_start silently no-ops when no recipe is running."""
        tracker = RecipeTracker()
        tracker.on_step_start(1)  # Should not raise

    def test_on_step_complete(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Step A", "Step B"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1, result_preview="All good")

        step = tracker.current.steps[0]  # type: ignore[union-attr]
        assert step.status == "completed"
        assert step.end_time is not None
        assert step.result_preview == "All good"

    def test_on_step_complete_no_current(self):
        """on_step_complete silently no-ops when no recipe is running."""
        tracker = RecipeTracker()
        tracker.on_step_complete(1)  # Should not raise

    def test_on_step_complete_truncates_preview(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Step A"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1, result_preview="x" * 300)

        step = tracker.current.steps[0]  # type: ignore[union-attr]
        assert len(step.result_preview) == 200

    def test_on_step_failed(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Step A"])
        tracker.on_step_start(1)
        tracker.on_step_failed(1, error="Connection refused")

        step = tracker.current.steps[0]  # type: ignore[union-attr]
        assert step.status == "failed"
        assert step.end_time is not None
        assert step.error_message == "Connection refused"

    def test_on_step_failed_no_current(self):
        """on_step_failed silently no-ops when no recipe is running."""
        tracker = RecipeTracker()
        tracker.on_step_failed(1)  # Should not raise

    def test_on_step_failed_truncates_error(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Step A"])
        tracker.on_step_start(1)
        tracker.on_step_failed(1, error="e" * 300)

        step = tracker.current.steps[0]  # type: ignore[union-attr]
        assert len(step.error_message) == 200

    def test_on_recipe_complete(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Step A"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1)
        tracker.on_recipe_complete()

        assert tracker.current is None
        assert len(tracker.history) == 1
        assert tracker.history[0].recipe_name == "test"
        assert tracker.history[0].status == "completed"
        assert tracker.history[0].end_time is not None

    def test_on_recipe_complete_failed(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Step A"])
        tracker.on_step_start(1)
        tracker.on_step_failed(1, error="boom")
        tracker.on_recipe_complete(status="failed")

        assert tracker.current is None
        assert tracker.history[0].status == "failed"

    def test_on_recipe_complete_no_current(self):
        """on_recipe_complete silently no-ops when no recipe is running."""
        tracker = RecipeTracker()
        tracker.on_recipe_complete()  # Should not raise
        assert tracker.history == []

    def test_multiple_recipe_runs(self):
        tracker = RecipeTracker()

        tracker.on_recipe_start("first", ["A", "B"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1)
        tracker.on_step_start(2)
        tracker.on_step_complete(2)
        tracker.on_recipe_complete()

        tracker.on_recipe_start("second", ["X"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1)
        tracker.on_recipe_complete()

        assert tracker.current is None
        assert len(tracker.history) == 2
        assert tracker.history[0].recipe_name == "first"
        assert tracker.history[1].recipe_name == "second"

    def test_clear(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["A"])
        tracker.on_recipe_complete()
        tracker.on_recipe_start("running", ["B"])

        tracker.clear()
        assert tracker.current is None
        assert tracker.history == []


# ===========================================================================
# Approval gate detection
# ===========================================================================


class TestApprovalGateDetection:
    def test_approval_in_name(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["review-approval", "normal step"])
        assert tracker.current.steps[0].is_approval_gate is True  # type: ignore[union-attr]
        assert tracker.current.steps[1].is_approval_gate is False  # type: ignore[union-attr]

    def test_gate_in_name(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["quality-gate", "deploy"])
        assert tracker.current.steps[0].is_approval_gate is True  # type: ignore[union-attr]
        assert tracker.current.steps[1].is_approval_gate is False  # type: ignore[union-attr]

    def test_case_insensitive(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["APPROVAL step", "Gate Check"])
        assert tracker.current.steps[0].is_approval_gate is True  # type: ignore[union-attr]
        assert tracker.current.steps[1].is_approval_gate is True  # type: ignore[union-attr]


# ===========================================================================
# format_pipeline
# ===========================================================================


class TestFormatPipeline:
    def test_no_current_recipe(self):
        tracker = RecipeTracker()
        output = tracker.format_pipeline()
        assert "No recipe currently running" in output
        assert "/recipe history" in output

    def test_running_recipe_header(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("code-review", ["Explore", "Analyze", "Report"])
        tracker.on_step_start(1)
        output = tracker.format_pipeline()
        assert "code-review" in output
        assert "step 1/3" in output

    def test_source_file_shown(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["A"], source_file="@recipes:code-review.yaml")
        output = tracker.format_pipeline()
        assert "@recipes:code-review.yaml" in output

    def test_completed_step_shows_duration(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Explore"])
        now = datetime.now()
        step = tracker.current.steps[0]  # type: ignore[union-attr]
        step.status = "completed"
        step.start_time = now - timedelta(minutes=4, seconds=22)
        step.end_time = now

        output = tracker.format_pipeline()
        assert "[x]" in output
        assert "4m22s" in output

    def test_running_step_shows_running(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Explore"])
        tracker.on_step_start(1)
        output = tracker.format_pipeline()
        assert "[>]" in output
        assert "RUNNING" in output

    def test_failed_step_shows_error(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Explore"])
        tracker.on_step_start(1)
        tracker.on_step_failed(1, error="Connection timeout")
        output = tracker.format_pipeline()
        assert "[!]" in output
        assert "FAILED" in output
        assert "Connection timeout" in output

    def test_pending_step_shown(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["Explore", "Report"])
        output = tracker.format_pipeline()
        assert "[ ]" in output
        assert "pending" in output

    def test_approval_gate_shown(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["review-gate"])
        output = tracker.format_pipeline()
        assert "APPROVAL:" in output
        assert "waiting" in output

    def test_completed_recipe_shows_status(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["A"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1)
        # Manually set all steps done, no running step
        run = tracker.current  # type: ignore[union-attr]
        output = tracker.format_pipeline(run)
        # No running step -> shows (completed/running status)
        assert "test" in output

    def test_explicit_run_argument(self):
        tracker = RecipeTracker()
        tracker.on_recipe_start("test", ["A", "B"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1)
        tracker.on_recipe_complete()

        # Format a historical run
        run = tracker.history[0]
        output = tracker.format_pipeline(run)
        assert "test" in output
        assert "completed" in output


# ===========================================================================
# format_history
# ===========================================================================


class TestFormatHistory:
    def test_empty_history_no_current(self):
        tracker = RecipeTracker()
        output = tracker.format_history()
        assert "No recipe runs in this session" in output

    def test_empty_history_with_current(self):
        """When no history but a recipe is running, show the pipeline."""
        tracker = RecipeTracker()
        tracker.on_recipe_start("active", ["Step 1"])
        output = tracker.format_history()
        assert "active" in output

    def test_history_with_completed_runs(self):
        tracker = RecipeTracker()

        tracker.on_recipe_start("first", ["A", "B"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1)
        tracker.on_step_start(2)
        tracker.on_step_complete(2)
        tracker.on_recipe_complete()

        tracker.on_recipe_start("second", ["X"])
        tracker.on_step_start(1)
        tracker.on_step_failed(1, error="oops")
        tracker.on_recipe_complete(status="failed")

        output = tracker.format_history()
        assert "Recipe History" in output
        assert "first" in output
        assert "second" in output
        assert "2/2 steps" in output
        assert "0/1 steps" in output

    def test_history_with_current_running(self):
        tracker = RecipeTracker()

        tracker.on_recipe_start("old", ["A"])
        tracker.on_step_start(1)
        tracker.on_step_complete(1)
        tracker.on_recipe_complete()

        tracker.on_recipe_start("active", ["B"])
        tracker.on_step_start(1)

        output = tracker.format_history()
        assert "Recipe History" in output
        assert "old" in output
        assert "Currently running" in output
        assert "active" in output


# ===========================================================================
# RecipeCommandsMixin
# ===========================================================================


class TestRecipeCommandsMixin:
    def test_mixin_exists(self):
        """RecipeCommandsMixin can be imported and has _cmd_recipe."""
        assert hasattr(RecipeCommandsMixin, "_cmd_recipe")

    def test_mixin_method_signature(self):
        """_cmd_recipe accepts an args parameter."""
        import inspect

        sig = inspect.signature(RecipeCommandsMixin._cmd_recipe)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "args" in params
