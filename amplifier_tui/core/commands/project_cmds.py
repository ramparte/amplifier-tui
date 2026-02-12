"""Project aggregation and intelligence commands (/project).

Provides a view of sessions grouped by project with tag statistics,
plus LLM-powered project Q&A and cross-session search.
"""

from __future__ import annotations

from amplifier_tui.core.features.project_aggregator import ProjectAggregator
from amplifier_tui.core.features.project_intelligence import (
    ProjectIntelligence,
    make_anthropic_ask_fn,
)
from amplifier_tui.core.features.project_search import ProjectSearch


class ProjectCommandsMixin:
    """/project command mixin."""

    _project_intelligence: ProjectIntelligence | None = None

    def _ensure_project_intelligence(self) -> ProjectIntelligence:
        """Lazily create the ProjectIntelligence instance."""
        if self._project_intelligence is None:
            ask_fn = make_anthropic_ask_fn()
            self._project_intelligence = ProjectIntelligence(ask_fn=ask_fn)
        return self._project_intelligence

    def _cmd_project(self, args: str) -> None:
        """Handle /project commands.

        Usage:
            /project                 -- list all projects with counts
            /project <name>          -- show details for a project
            /project ask <question>  -- ask about the current/specified project
            /project search <query>  -- search across session transcripts
            /project attention       -- what needs attention?
            /project weekly          -- weekly summary
        """
        parts = args.strip().split(None, 1)
        sub = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub == "ask":
            self._cmd_project_ask(rest)
            return
        if sub == "search":
            self._cmd_project_search(rest)
            return
        if sub == "attention":
            self._cmd_project_attention(rest)
            return
        if sub == "weekly":
            self._cmd_project_weekly(rest)
            return

        # Original behavior: list or show project
        query = args.strip()
        sessions = self._session_list_data  # type: ignore[attr-defined]
        if not sessions:
            self._add_system_message("No sessions loaded.")  # type: ignore[attr-defined]
            return

        all_tags = self._tag_store.load()  # type: ignore[attr-defined]
        projects = ProjectAggregator.aggregate(sessions, all_tags)

        if not query:
            summary = ProjectAggregator.format_all_projects(projects)
            self._add_system_message(summary)  # type: ignore[attr-defined]
            return

        info = ProjectAggregator.get_project(projects, query)
        if info is None:
            self._add_system_message(  # type: ignore[attr-defined]
                f"No project matching '{query}'.\nUse /project to list all projects."
            )
            return

        detail = ProjectAggregator.format_project_summary(info)
        recent = sorted(info.sessions, key=lambda s: s["mtime"], reverse=True)[:5]
        if recent:
            detail += "\n  Recent sessions:"
            for s in recent:
                sid = s["session_id"][:8]
                tags = all_tags.get(s["session_id"], [])
                tag_str = " ".join(f"#{t}" for t in tags[:2]) if tags else ""
                label = s.get("name") or s.get("description") or sid
                if len(label) > 30:
                    label = label[:27] + "..."
                detail += f"\n    {s['date_str']}  {label}  {tag_str}"

        self._add_system_message(detail)  # type: ignore[attr-defined]

    def _cmd_project_ask(self, question: str) -> None:
        """Handle /project ask <question>."""
        if not question:
            self._add_system_message(  # type: ignore[attr-defined]
                "Usage: /project ask <question>\n"
                "Examples:\n"
                "  /project ask what's the status of the auth work?\n"
                "  /project ask what did I do this week?\n"
                "  /project ask what patterns are emerging?"
            )
            return

        sessions = self._session_list_data  # type: ignore[attr-defined]
        if not sessions:
            self._add_system_message("No sessions loaded.")  # type: ignore[attr-defined]
            return

        all_tags = self._tag_store.load()  # type: ignore[attr-defined]

        # Determine project from current session or most recent
        project_name = self._get_current_project_name()

        self._add_system_message(  # type: ignore[attr-defined]
            f"Thinking about {project_name}..."
        )

        intel = self._ensure_project_intelligence()
        answer = intel.ask(sessions, all_tags, project_name, question)
        self._add_system_message(answer)  # type: ignore[attr-defined]

    def _cmd_project_search(self, query: str) -> None:
        """Handle /project search <query>."""
        if not query:
            self._add_system_message(  # type: ignore[attr-defined]
                "Usage: /project search <query>\nExample: /project search filter bug"
            )
            return

        sessions = self._session_list_data  # type: ignore[attr-defined]
        if not sessions:
            self._add_system_message("No sessions loaded.")  # type: ignore[attr-defined]
            return

        results = ProjectSearch.search(sessions, query, limit=15)
        formatted = ProjectSearch.format_results(results, query)
        self._add_system_message(formatted)  # type: ignore[attr-defined]

    def _cmd_project_attention(self, project_name: str) -> None:
        """Handle /project attention [project]."""
        sessions = self._session_list_data  # type: ignore[attr-defined]
        if not sessions:
            self._add_system_message("No sessions loaded.")  # type: ignore[attr-defined]
            return

        all_tags = self._tag_store.load()  # type: ignore[attr-defined]
        name = project_name or self._get_current_project_name()

        self._add_system_message(f"Analyzing {name}...")  # type: ignore[attr-defined]
        intel = self._ensure_project_intelligence()
        answer = intel.what_needs_attention(sessions, all_tags, name)
        self._add_system_message(answer)  # type: ignore[attr-defined]

    def _cmd_project_weekly(self, project_name: str) -> None:
        """Handle /project weekly [project]."""
        sessions = self._session_list_data  # type: ignore[attr-defined]
        if not sessions:
            self._add_system_message("No sessions loaded.")  # type: ignore[attr-defined]
            return

        all_tags = self._tag_store.load()  # type: ignore[attr-defined]
        name = project_name or self._get_current_project_name()

        self._add_system_message(f"Generating weekly summary for {name}...")  # type: ignore[attr-defined]
        intel = self._ensure_project_intelligence()
        answer = intel.weekly_summary(sessions, all_tags, name)
        self._add_system_message(answer)  # type: ignore[attr-defined]

    def _get_current_project_name(self) -> str:
        """Get the current project name from session or most common."""
        # Try current session's project
        if hasattr(self, "session_manager") and self.session_manager:  # type: ignore[attr-defined]
            sm = self.session_manager  # type: ignore[attr-defined]
            if hasattr(sm, "project") and sm.project:
                return sm.project
        # Fall back to most recent session's project
        sessions = self._session_list_data  # type: ignore[attr-defined]
        if sessions:
            return sessions[0]["project"]
        return "unknown"
