"""Agent delegation tree commands (/agents)."""

from __future__ import annotations


class AgentCommandsMixin:
    """Mixin providing the /agents command for viewing delegation trees."""

    def _cmd_agents(self, args: str = "") -> None:
        """Show agent delegation tree or manage delegation history."""
        sub = args.strip().lower()

        if sub == "clear":
            self._agent_tracker.clear()  # type: ignore[attr-defined]
            self._add_system_message("Agent delegation history cleared.")  # type: ignore[attr-defined]
            return

        # /agents, /agents history — both show the tree
        tracker = self._agent_tracker  # type: ignore[attr-defined]
        if not tracker.has_delegations:
            self._add_system_message("No agent delegations in this session.")  # type: ignore[attr-defined]
            return

        tree = tracker.format_tree()
        summary = tracker.format_summary()
        self._add_system_message(f"{tree}\n\n{summary}")  # type: ignore[attr-defined]
