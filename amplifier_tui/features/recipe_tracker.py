"""Recipe pipeline execution tracker (F2.3).

Tracks recipe execution state for the ``/recipe`` family of commands,
providing a step-by-step pipeline view with timing, status icons, and
error highlighting.

This follows the same pattern as :mod:`agent_tracker` and :mod:`tool_log`:
a lightweight in-memory tracker that hooks into the existing
``on_tool_pre`` / ``on_tool_post`` callbacks by checking whether the
tool name is ``recipes``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RecipeStep:
    """A single step in a recipe pipeline."""

    index: int  # 1-based step number
    name: str  # step name/description
    status: str = "pending"  # "pending", "running", "completed", "failed", "approval"
    start_time: datetime | None = None
    end_time: datetime | None = None
    result_preview: str = ""
    error_message: str = ""
    is_approval_gate: bool = False

    @property
    def duration_str(self) -> str:
        """Format duration as human-readable string."""
        if not self.start_time:
            return ""
        end = self.end_time or datetime.now()
        seconds = (end - self.start_time).total_seconds()
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m{secs:02d}s"


@dataclass
class RecipeRun:
    """A complete recipe execution."""

    recipe_name: str
    session_id: str = ""
    source_file: str = ""
    steps: list[RecipeStep] = field(default_factory=list)
    status: str = "running"  # "running", "completed", "failed", "cancelled"
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None

    @property
    def current_step_index(self) -> int:
        """Return the 1-based index of the currently running step, or 0."""
        for step in self.steps:
            if step.status == "running":
                return step.index
        return 0

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "completed")

    @property
    def total_steps(self) -> int:
        return len(self.steps)


class RecipeTracker:
    """Tracks recipe pipeline execution for visualization.

    The tracker is entirely in-memory; nothing is persisted.  It hooks into
    the existing ``on_tool_pre`` / ``on_tool_post`` callbacks by checking
    whether the tool name is ``recipes``.
    """

    def __init__(self) -> None:
        self._current: RecipeRun | None = None
        self._history: list[RecipeRun] = []

    # -- Public mutation API --------------------------------------------------

    @property
    def current(self) -> RecipeRun | None:
        return self._current

    @property
    def history(self) -> list[RecipeRun]:
        return list(self._history)

    def on_recipe_start(
        self,
        recipe_name: str,
        steps: list[str],
        session_id: str = "",
        source_file: str = "",
    ) -> None:
        """Called when a recipe begins execution."""
        recipe_steps = []
        for i, name in enumerate(steps, 1):
            is_approval = "approval" in name.lower() or "gate" in name.lower()
            recipe_steps.append(
                RecipeStep(
                    index=i,
                    name=name,
                    is_approval_gate=is_approval,
                )
            )
        self._current = RecipeRun(
            recipe_name=recipe_name,
            session_id=session_id,
            source_file=source_file,
            steps=recipe_steps,
        )

    def on_step_start(self, step_index: int) -> None:
        """Called when a step begins.  *step_index* is 1-based."""
        if not self._current:
            return
        for step in self._current.steps:
            if step.index == step_index:
                step.status = "running"
                step.start_time = datetime.now()
                break

    def on_step_complete(self, step_index: int, result_preview: str = "") -> None:
        """Called when a step completes."""
        if not self._current:
            return
        for step in self._current.steps:
            if step.index == step_index:
                step.status = "completed"
                step.end_time = datetime.now()
                step.result_preview = result_preview[:200]
                break

    def on_step_failed(self, step_index: int, error: str = "") -> None:
        """Called when a step fails."""
        if not self._current:
            return
        for step in self._current.steps:
            if step.index == step_index:
                step.status = "failed"
                step.end_time = datetime.now()
                step.error_message = error[:200]
                break

    def on_recipe_complete(self, status: str = "completed") -> None:
        """Called when the recipe finishes."""
        if not self._current:
            return
        self._current.status = status
        self._current.end_time = datetime.now()
        self._history.append(self._current)
        self._current = None

    def clear(self) -> None:
        """Reset all tracking state."""
        self._current = None
        self._history.clear()

    # -- Rendering ------------------------------------------------------------

    def format_pipeline(self, run: RecipeRun | None = None) -> str:
        """Format a recipe run as a Rich-markup pipeline view."""
        run = run or self._current
        if not run:
            return (
                "[dim]No recipe currently running.[/dim]\n"
                "Use /recipe history to see past runs."
            )

        lines: list[str] = []
        # Header
        current = run.current_step_index
        total = run.total_steps
        if current > 0:
            lines.append(
                f"[bold]Recipe: {run.recipe_name}[/bold] (step {current}/{total})"
            )
        else:
            lines.append(f"[bold]Recipe: {run.recipe_name}[/bold] ({run.status})")

        if run.source_file:
            lines.append(f"[dim]Source: {run.source_file}[/dim]")
        lines.append("")

        # Steps
        for step in run.steps:
            icon = _step_icon(step.status)
            name = step.name
            duration = step.duration_str

            if step.status == "completed":
                lines.append(
                    f"  {icon} {step.index}. {name:<30s} [dim]{duration}[/dim]"
                )
            elif step.status == "running":
                lines.append(
                    f"  {icon} {step.index}. {name:<30s} [yellow]{duration}  RUNNING[/yellow]"
                )
            elif step.status == "failed":
                lines.append(f"  {icon} {step.index}. {name:<30s} [red]FAILED[/red]")
                if step.error_message:
                    lines.append(f"       [red]{step.error_message[:80]}[/red]")
            elif step.is_approval_gate:
                lines.append(
                    f"  {icon} {step.index}. [yellow]APPROVAL:[/yellow] {name:<22s} [dim]waiting[/dim]"
                )
            else:
                lines.append(f"  {icon} {step.index}. {name:<30s} [dim]pending[/dim]")

        return "\n".join(lines)

    def format_history(self) -> str:
        """Format past recipe runs."""
        if not self._history:
            if self._current:
                return self.format_pipeline()
            return "No recipe runs in this session."

        lines: list[str] = ["Recipe History:", ""]
        for i, run in enumerate(self._history, 1):
            status_icon = {
                "completed": "[green]\u2713[/green]",
                "failed": "[red]\u2717[/red]",
                "cancelled": "[yellow]\u2298[/yellow]",
            }.get(run.status, " ")
            duration = ""
            if run.end_time and run.start_time:
                secs = (run.end_time - run.start_time).total_seconds()
                if secs < 60:
                    duration = f"{secs:.0f}s"
                else:
                    mins = int(secs // 60)
                    duration = f"{mins}m{int(secs % 60):02d}s"
            lines.append(
                f"  {status_icon} {i}. {run.recipe_name}"
                f" ({run.completed_count}/{run.total_steps} steps) {duration}"
            )

        if self._current:
            lines.append("")
            lines.append("[bold]Currently running:[/bold]")
            lines.append(self.format_pipeline())

        return "\n".join(lines)


def _step_icon(status: str) -> str:
    """Return Rich-markup icon for a step status."""
    return {
        "completed": "[green][x][/green]",
        "running": "[yellow][>][/yellow]",
        "failed": "[red][!][/red]",
        "approval": "[cyan][?][/cyan]",
        "pending": "[ ]",
    }.get(status, "[ ]")
