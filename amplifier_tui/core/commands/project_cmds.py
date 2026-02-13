"""Unified project commands (/project).

Combines session-based project intelligence (aggregation, LLM Q&A, search)
with Projector data (tasks, strategies, outcomes, people, notes) into a
single ``/project`` command surface.  ``/projector`` is an alias.
"""

from __future__ import annotations

import logging
import os

from amplifier_tui.core.features.project_aggregator import ProjectAggregator
from amplifier_tui.core.features.project_intelligence import (
    ProjectIntelligence,
    make_anthropic_ask_fn,
)
from amplifier_tui.core.features.project_search import ProjectSearch
from amplifier_tui.core.features.projector_client import ProjectorClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

_HELP_TEXT = """\
/project commands:

  /project                  List all projects with session counts
  /project <name>           Show details for a specific project
  /project help             Show this help

  Session intelligence (LLM-powered):
    /project ask <question> Ask about the current project
    /project attention      What needs attention?
    /project weekly         Weekly activity summary
    /project focus          What should I work on next?
    /project search <query> Search across session transcripts

  Projector data (when available):
    /project tasks [name]   Show tasks for a project
    /project strategies     List active strategies
    /project status         Show Projector context for current directory
    /project outcomes [name] Show recent session outcomes
    /project brief [name]   Full project briefing (sessions + Projector)

  Panel:
    /project panel          Toggle the project panel (also Ctrl+P)

Tip: /projector is an alias for /project.
"""


class ProjectCommandsMixin:
    """/project command mixin -- unified project + Projector surface."""

    _project_intelligence: ProjectIntelligence | None = None
    _projector_client: ProjectorClient | None = None

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _ensure_projector(self) -> ProjectorClient:
        """Lazily initialise the Projector client."""
        if self._projector_client is None:
            self._projector_client = ProjectorClient()
        return self._projector_client

    def _ensure_project_intelligence(self) -> ProjectIntelligence:
        """Lazily create the ProjectIntelligence instance."""
        if self._project_intelligence is None:
            ask_fn = make_anthropic_ask_fn()
            projector = self._ensure_projector()
            self._project_intelligence = ProjectIntelligence(
                ask_fn=ask_fn,
                projector=projector if projector.available else None,
            )
        return self._project_intelligence

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    def _cmd_project(self, args: str) -> None:
        """Handle /project (and /projector alias) commands."""
        parts = args.strip().split(None, 1)
        sub = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        # Dispatch table
        handlers: dict[str, tuple] = {
            "help": (self._cmd_project_help, rest),
            "ask": (self._cmd_project_ask, rest),
            "search": (self._cmd_project_search, rest),
            "attention": (self._cmd_project_attention, rest),
            "weekly": (self._cmd_project_weekly, rest),
            "focus": (self._cmd_project_focus, rest),
            "tasks": (self._cmd_project_tasks, rest),
            "strategies": (self._cmd_project_strategies, rest),
            "status": (self._cmd_project_status, rest),
            "outcomes": (self._cmd_project_outcomes, rest),
            "brief": (self._cmd_project_brief, rest),
            "panel": (self._cmd_project_panel, rest),
        }

        if sub in handlers:
            fn, arg = handlers[sub]
            fn(arg)
            return

        # Default: list or show project
        self._cmd_project_list_or_detail(args.strip())

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _cmd_project_help(self, _args: str) -> None:
        self._add_system_message(_HELP_TEXT)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Session-based commands (existing)
    # ------------------------------------------------------------------

    def _cmd_project_list_or_detail(self, query: str) -> None:
        """List all projects or show detail for one."""
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
        project_name = self._get_current_project_name()

        self._add_system_message(f"Thinking about {project_name}...")  # type: ignore[attr-defined]

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

    def _cmd_project_focus(self, project_name: str) -> None:
        """Handle /project focus [project]."""
        sessions = self._session_list_data  # type: ignore[attr-defined]
        if not sessions:
            self._add_system_message("No sessions loaded.")  # type: ignore[attr-defined]
            return

        all_tags = self._tag_store.load()  # type: ignore[attr-defined]
        name = project_name or self._get_current_project_name()

        self._add_system_message(f"Thinking about what to focus on for {name}...")  # type: ignore[attr-defined]
        intel = self._ensure_project_intelligence()
        answer = intel.focus(sessions, all_tags, name)
        self._add_system_message(answer)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Projector data commands (absorbed from ProjectorCommandsMixin)
    # ------------------------------------------------------------------

    def _cmd_project_tasks(self, project_name: str) -> None:
        """Handle /project tasks [name]."""
        client = self._ensure_projector()

        if not client.available:
            self._add_system_message(  # type: ignore[attr-defined]
                "No Projector data found at ~/.amplifier/projector/"
            )
            return

        if not project_name:
            detected = self._projector_detect_current()
            if detected:
                project_name = detected.name
            else:
                self._add_system_message(  # type: ignore[attr-defined]
                    "No project specified and none detected from cwd.\n"
                    "Usage: /project tasks <name>"
                )
                return

        tasks = client.get_tasks(project_name)
        if not tasks:
            self._add_system_message(f"No tasks for {project_name}")  # type: ignore[attr-defined]
            return

        task_icons = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
            "blocked": "[!]",
        }
        lines = [f"Tasks: {project_name}\n"]
        for t in tasks:
            lines.append(f"  {task_icons.get(t.status, '[ ]')} {t.id}: {t.title}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _cmd_project_strategies(self, args: str) -> None:
        """Handle /project strategies [all]."""
        client = self._ensure_projector()

        if not client.available:
            self._add_system_message(  # type: ignore[attr-defined]
                "No Projector data found at ~/.amplifier/projector/"
            )
            return

        strategies = client.list_strategies(active_only="all" not in args)
        if not strategies:
            self._add_system_message("No strategies found.")  # type: ignore[attr-defined]
            return

        lines = ["Active Strategies\n"]
        for s in strategies:
            tag = "on" if s.active else "off"
            lines.append(f"  [{tag}] {s.name} - {s.description.strip()[:60]}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _cmd_project_status(self, _args: str) -> None:
        """Handle /project status -- Projector context for current directory."""
        client = self._ensure_projector()

        if not client.available:
            self._add_system_message(  # type: ignore[attr-defined]
                "No Projector data found at ~/.amplifier/projector/"
            )
            return

        detected = self._projector_detect_current()
        if not detected:
            self._add_system_message(  # type: ignore[attr-defined]
                "No Projector project detected for current directory.\n"
                "Use /project to see all projects."
            )
            return

        lines = [
            f"Project: {detected.name}",
            f"Status: {detected.status}",
            f"Repos: {', '.join(detected.repos) if detected.repos else 'none'}",
        ]
        if detected.people:
            lines.append(f"People: {', '.join(detected.people)}")
        if detected.task_count:
            lines.append(f"Active tasks: {detected.task_count}")
        if detected.recent_outcomes:
            lines.append("\nRecent outcomes:")
            for o in detected.recent_outcomes[-3:]:
                summary = o.get("summary", "no summary")[:80]
                lines.append(f"  - {summary}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _cmd_project_outcomes(self, project_name: str) -> None:
        """Handle /project outcomes [name]."""
        client = self._ensure_projector()

        if not client.available:
            self._add_system_message(  # type: ignore[attr-defined]
                "No Projector data found at ~/.amplifier/projector/"
            )
            return

        if not project_name:
            detected = self._projector_detect_current()
            project_name = detected.name if detected else ""

        if not project_name:
            self._add_system_message("Usage: /project outcomes <name>")  # type: ignore[attr-defined]
            return

        proj = client.get_project(project_name)
        if not proj:
            self._add_system_message(f"Project not found: {project_name}")  # type: ignore[attr-defined]
            return

        if not proj.recent_outcomes:
            self._add_system_message(f"No recorded outcomes for {project_name}")  # type: ignore[attr-defined]
            return

        lines = [f"Recent Outcomes: {project_name}\n"]
        for o in proj.recent_outcomes:
            ts = o.get("timestamp", "?")[:10]
            summary = o.get("summary", "no summary")
            lines.append(f"  [{ts}] {summary}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _cmd_project_brief(self, project_name: str) -> None:
        """Handle /project brief [name] -- rich briefing combining all sources."""
        client = self._ensure_projector()
        name = project_name or self._get_current_project_name()

        lines = [f"Project Brief: {name}\n"]

        # Projector data (if available)
        if client.available:
            proj = client.get_project(name)
            if proj:
                lines.append(f"Status: {proj.status}")
                if proj.description:
                    lines.append(f"Description: {proj.description.strip()}")
                if proj.people:
                    lines.append(f"People: {', '.join(proj.people)}")
                if proj.repos:
                    lines.append(f"Repos: {', '.join(proj.repos)}")
                if proj.relationships:
                    for rel_type, targets in proj.relationships.items():
                        if isinstance(targets, list):
                            lines.append(f"  {rel_type}: {', '.join(targets)}")
                        else:
                            lines.append(f"  {rel_type}: {targets}")
                if proj.notes:
                    lines.append(f"\nNotes: {proj.notes.strip()}")

                tasks = client.get_tasks(name)
                active = [t for t in tasks if t.status != "completed"]
                if active:
                    lines.append(f"\nActive tasks ({len(active)}):")
                    for t in active[:5]:
                        lines.append(f"  [{t.status}] {t.id}: {t.title}")
                    if len(active) > 5:
                        lines.append(f"  ... and {len(active) - 5} more")

                if proj.recent_outcomes:
                    lines.append("\nRecent outcomes:")
                    for o in proj.recent_outcomes:
                        ts = o.get("timestamp", "?")[:10]
                        summary = o.get("summary", "no summary")[:80]
                        lines.append(f"  [{ts}] {summary}")

        # Session data
        sessions = self._session_list_data  # type: ignore[attr-defined]
        if sessions:
            all_tags = self._tag_store.load()  # type: ignore[attr-defined]
            projects = ProjectAggregator.aggregate(sessions, all_tags)
            info = ProjectAggregator.get_project(projects, name)
            if info:
                lines.append(f"\nSessions: {info.session_count}")
                lines.append(f"Last active: {info.latest_date_str}")
                if info.top_tags:
                    lines.append(f"Common tags: {', '.join(info.top_tags[:8])}")
                recent = sorted(info.sessions, key=lambda s: s["mtime"], reverse=True)[
                    :3
                ]
                if recent:
                    lines.append("\nRecent sessions:")
                    for s in recent:
                        label = (
                            s.get("name") or s.get("description") or s["session_id"][:8]
                        )
                        if len(label) > 40:
                            label = label[:37] + "..."
                        lines.append(f"  {s['date_str']}  {label}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Panel toggle
    # ------------------------------------------------------------------

    def _cmd_project_panel(self, _args: str) -> None:
        """Toggle the project panel visibility."""
        self._ensure_projector()

        try:
            panel = self.query_one("#project-panel")  # type: ignore[attr-defined]
        except Exception:
            self._add_system_message("Project panel not available.")  # type: ignore[attr-defined]
            return

        panel.visible = not panel.visible
        if panel.visible:
            self._projector_refresh_panel()

    def _projector_refresh_panel(self) -> None:
        """Refresh the project panel with current data."""
        client = self._ensure_projector()

        if not client.available:
            return

        projects = client.list_projects()
        strategies = client.list_strategies(active_only=True)

        try:
            panel = self.query_one("#project-panel")  # type: ignore[attr-defined]
            panel.update_projects(projects, strategies)
        except Exception:
            logger.debug("Failed to refresh project panel", exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    def _projector_detect_current(self):
        """Detect Projector project from current session's working dir."""
        cwd = os.getcwd()

        # If we have an active session with a working dir, prefer that
        if hasattr(self, "_current_conversation_id"):
            conv_id = self._current_conversation_id  # type: ignore[attr-defined]
            if hasattr(self, "_session_manager"):
                handle = self._session_manager.get_handle(conv_id)  # type: ignore[attr-defined]
                if handle and hasattr(handle, "working_dir") and handle.working_dir:
                    cwd = handle.working_dir

        return self._ensure_projector().detect_project(cwd)
