"""Model A/B testing manager (F3.2 - Model A/B Testing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ComparisonResult:
    """A single A/B comparison result."""

    prompt: str
    model_a: str
    model_b: str
    response_a: str = ""
    response_b: str = ""
    time_a_ms: float = 0
    time_b_ms: float = 0
    tokens_a: int = 0
    tokens_b: int = 0
    picked: str = ""  # "a", "b", or "" (no pick yet)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def picked_model(self) -> str:
        """Return the name of the picked model, or empty string."""
        if self.picked == "a":
            return self.model_a
        elif self.picked == "b":
            return self.model_b
        return ""


class CompareManager:
    """Manages Model A/B testing state and history."""

    def __init__(self) -> None:
        self._active: bool = False
        self._model_a: str = ""
        self._model_b: str = ""
        self._current: ComparisonResult | None = None
        self._history: list[ComparisonResult] = []

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def model_a(self) -> str:
        return self._model_a

    @property
    def model_b(self) -> str:
        return self._model_b

    @property
    def current(self) -> ComparisonResult | None:
        return self._current

    @property
    def history(self) -> list[ComparisonResult]:
        return list(self._history)

    def activate(self, model_a: str, model_b: str) -> None:
        """Enter A/B comparison mode.

        Raises:
            ValueError: If models are the same or empty.
        """
        if not model_a or not model_b:
            raise ValueError("Both model names are required")
        if model_a == model_b:
            raise ValueError("Models must be different for comparison")
        self._active = True
        self._model_a = model_a
        self._model_b = model_b

    def deactivate(self) -> None:
        """Exit A/B comparison mode."""
        if self._current:
            self._history.append(self._current)
            self._current = None
        self._active = False
        self._model_a = ""
        self._model_b = ""

    def start_comparison(self, prompt: str) -> ComparisonResult:
        """Start a new comparison with the given prompt.

        Raises:
            RuntimeError: If not in A/B mode.
        """
        if not self._active:
            raise RuntimeError("Not in A/B comparison mode")

        if self._current:
            self._history.append(self._current)

        self._current = ComparisonResult(
            prompt=prompt[:500],
            model_a=self._model_a,
            model_b=self._model_b,
        )
        return self._current

    def set_response_a(
        self, response: str, time_ms: float = 0, tokens: int = 0
    ) -> None:
        """Set response from model A."""
        if self._current:
            self._current.response_a = response
            self._current.time_a_ms = time_ms
            self._current.tokens_a = tokens

    def set_response_b(
        self, response: str, time_ms: float = 0, tokens: int = 0
    ) -> None:
        """Set response from model B."""
        if self._current:
            self._current.response_b = response
            self._current.time_b_ms = time_ms
            self._current.tokens_b = tokens

    def pick(self, choice: str) -> ComparisonResult | None:
        """Pick the preferred response.

        Args:
            choice: "a", "b", "left", or "right"

        Returns:
            The ComparisonResult with the pick recorded, or None if no
            current comparison.

        Raises:
            ValueError: If choice is invalid.
        """
        choice = choice.lower().strip()
        mapping = {"a": "a", "b": "b", "left": "a", "right": "b"}
        if choice not in mapping:
            raise ValueError(f"Invalid choice '{choice}'. Use: a, b, left, right")

        if not self._current:
            return None

        self._current.picked = mapping[choice]
        result = self._current
        self._history.append(self._current)
        self._current = None
        return result

    def format_status(self) -> str:
        """Format current A/B mode status."""
        if not self._active:
            return (
                "[dim]A/B comparison mode is not active.[/dim]\n\n"
                "Usage: /compare <model_a> <model_b>\n"
                "Example: /compare claude-sonnet gpt-4o"
            )

        lines = [
            "[bold]A/B Comparison Mode: ACTIVE[/bold]",
            "",
            f"  Model A (left):  [cyan]{self._model_a}[/cyan]",
            f"  Model B (right): [cyan]{self._model_b}[/cyan]",
            "",
        ]

        if self._current:
            lines.append("Current comparison: [yellow]awaiting pick[/yellow]")
            lines.append(f"  Prompt: {self._current.prompt[:80]}...")
        else:
            lines.append("Send a message to compare responses from both models.")

        lines.append("")
        lines.append(f"Comparisons so far: {len(self._history)}")
        lines.append("")
        lines.append(
            "Commands: /compare off | /compare pick left|right | /compare history"
        )

        return "\n".join(lines)

    def format_comparison(self, result: ComparisonResult | None = None) -> str:
        """Format a comparison result as Rich-markup side-by-side summary."""
        result = result or self._current
        if not result:
            return "[dim]No comparison to display.[/dim]"

        lines = [
            f"[bold]Comparison:[/bold] {result.prompt[:80]}",
            "",
        ]

        # Model A
        pick_a = " [green]\u2713 PICKED[/green]" if result.picked == "a" else ""
        lines.append(f"[cyan]Model A: {result.model_a}[/cyan]{pick_a}")
        if result.response_a:
            preview_a = result.response_a[:200].replace("\n", " ")
            time_a = f"{result.time_a_ms:.0f}ms" if result.time_a_ms else "N/A"
            tokens_a = f"{result.tokens_a}" if result.tokens_a else "N/A"
            lines.append(f"  Time: {time_a} | Tokens: {tokens_a}")
            lines.append(
                f"  {preview_a}{'...' if len(result.response_a) > 200 else ''}"
            )
        else:
            lines.append("  [dim]No response yet[/dim]")

        lines.append("")

        # Model B
        pick_b = " [green]\u2713 PICKED[/green]" if result.picked == "b" else ""
        lines.append(f"[cyan]Model B: {result.model_b}[/cyan]{pick_b}")
        if result.response_b:
            preview_b = result.response_b[:200].replace("\n", " ")
            time_b = f"{result.time_b_ms:.0f}ms" if result.time_b_ms else "N/A"
            tokens_b = f"{result.tokens_b}" if result.tokens_b else "N/A"
            lines.append(f"  Time: {time_b} | Tokens: {tokens_b}")
            lines.append(
                f"  {preview_b}{'...' if len(result.response_b) > 200 else ''}"
            )
        else:
            lines.append("  [dim]No response yet[/dim]")

        if not result.picked:
            lines.append("")
            lines.append("Use /compare pick left|right to choose.")

        return "\n".join(lines)

    def format_history(self) -> str:
        """Format comparison history."""
        if not self._history:
            if self._current:
                return self.format_comparison()
            return (
                "No comparisons yet. Enter A/B mode with /compare <model_a> <model_b>"
            )

        lines = [f"Comparison History ({len(self._history)} comparisons):"]
        lines.append("")

        for i, result in enumerate(self._history, 1):
            picked_str = ""
            if result.picked == "a":
                picked_str = f" \u2192 picked [green]{result.model_a}[/green]"
            elif result.picked == "b":
                picked_str = f" \u2192 picked [green]{result.model_b}[/green]"
            else:
                picked_str = " [dim](no pick)[/dim]"

            prompt_preview = result.prompt[:60]
            lines.append(f"  {i}. {result.model_a} vs {result.model_b}{picked_str}")
            lines.append(f"     [dim]{prompt_preview}[/dim]")

        # Score summary
        a_wins = sum(1 for r in self._history if r.picked == "a")
        b_wins = sum(1 for r in self._history if r.picked == "b")
        if a_wins or b_wins:
            lines.append("")
            # Get model names from last comparison
            last = self._history[-1]
            lines.append(f"Score: {last.model_a} {a_wins} - {b_wins} {last.model_b}")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all state."""
        self._active = False
        self._model_a = ""
        self._model_b = ""
        self._current = None
        self._history.clear()
