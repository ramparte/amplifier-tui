"""Model A/B testing commands (F3.2 - Model A/B Testing)."""

from __future__ import annotations


class CompareCommandsMixin:
    """Mixin providing /compare command for Model A/B testing."""

    def _cmd_compare(self, args: str = "") -> None:
        """Handle /compare subcommands.

        Subcommands:
            /compare <model_a> <model_b>  Enter A/B mode
            /compare off                  Exit A/B mode
            /compare status               Show current state
            /compare pick left|right      Choose preferred response
            /compare show                 Show current comparison
            /compare history              Past comparisons
            /compare clear                Clear history
        """
        text = args.strip() if args else ""

        if not text:
            # Show status
            self._add_system_message(self._compare_manager.format_status())  # type: ignore[attr-defined]
            return

        if text == "off":
            self._compare_manager.deactivate()  # type: ignore[attr-defined]
            self._add_system_message("A/B comparison mode deactivated.")  # type: ignore[attr-defined]
            return

        if text == "status":
            self._add_system_message(self._compare_manager.format_status())  # type: ignore[attr-defined]
            return

        if text == "history":
            self._add_system_message(self._compare_manager.format_history())  # type: ignore[attr-defined]
            return

        if text == "clear":
            self._compare_manager.clear()  # type: ignore[attr-defined]
            self._add_system_message("Comparison history cleared.")  # type: ignore[attr-defined]
            return

        if text.startswith("pick "):
            choice = text[5:].strip()
            try:
                result = self._compare_manager.pick(choice)  # type: ignore[attr-defined]
                if result:
                    self._add_system_message(  # type: ignore[attr-defined]
                        f"Picked [green]{result.picked_model}[/green] response.\n\n"
                        + self._compare_manager.format_comparison(result)  # type: ignore[attr-defined]
                    )
                else:
                    self._add_system_message(  # type: ignore[attr-defined]
                        "No active comparison to pick from. Send a message first."
                    )
            except ValueError as e:
                self._add_system_message(f"[red]Error:[/red] {e}")  # type: ignore[attr-defined]
            return

        if text == "show":
            self._add_system_message(self._compare_manager.format_comparison())  # type: ignore[attr-defined]
            return

        # Try to parse as "model_a model_b"
        parts = text.split(None, 1)
        if len(parts) == 2:
            model_a, model_b = parts
            try:
                self._compare_manager.activate(model_a, model_b)  # type: ignore[attr-defined]
                self._add_system_message(  # type: ignore[attr-defined]
                    f"[bold]A/B Comparison Mode: ACTIVE[/bold]\n\n"
                    f"  Model A (left):  [cyan]{model_a}[/cyan]\n"
                    f"  Model B (right): [cyan]{model_b}[/cyan]\n\n"
                    f"Send a message to compare responses.\n"
                    f"Use /compare off to exit."
                )
            except ValueError as e:
                self._add_system_message(f"[red]Error:[/red] {e}")  # type: ignore[attr-defined]
            return

        self._add_system_message(  # type: ignore[attr-defined]
            "Usage:\n"
            "  /compare <model_a> <model_b>  Enter A/B mode\n"
            "  /compare off                  Exit A/B mode\n"
            "  /compare status               Show current state\n"
            "  /compare pick left|right      Choose preferred response\n"
            "  /compare show                 Show current comparison\n"
            "  /compare history              Past comparisons\n"
            "  /compare clear                Clear history"
        )
