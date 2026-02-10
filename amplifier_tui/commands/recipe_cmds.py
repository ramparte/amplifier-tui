"""Recipe pipeline commands (/recipe)."""

from __future__ import annotations


class RecipeCommandsMixin:
    """Mixin providing the /recipe command for recipe pipeline visualization."""

    def _cmd_recipe(self, args: str = "") -> None:
        """Show recipe pipeline status, history, or manage tracking.

        Subcommands:
            /recipe          Current pipeline view (same as /recipe status)
            /recipe status   Step-by-step pipeline with timing
            /recipe history  Past recipe runs in this session
            /recipe clear    Clear recipe tracking
        """
        sub = args.strip().lower()

        if not sub or sub == "status":
            self._add_system_message(self._recipe_tracker.format_pipeline())  # type: ignore[attr-defined]
            return

        if sub == "history":
            self._add_system_message(self._recipe_tracker.format_history())  # type: ignore[attr-defined]
            return

        if sub == "clear":
            self._recipe_tracker.clear()  # type: ignore[attr-defined]
            self._add_system_message("Recipe tracking cleared.")  # type: ignore[attr-defined]
            return

        self._add_system_message(  # type: ignore[attr-defined]
            "Usage: /recipe [status|history|clear]\n"
            "  /recipe          Show current pipeline (default)\n"
            "  /recipe status   Same as /recipe\n"
            "  /recipe history  Past recipe runs\n"
            "  /recipe clear    Clear tracking"
        )
