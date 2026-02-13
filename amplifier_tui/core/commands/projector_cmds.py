"""Projector slash command mixin."""

from __future__ import annotations

import logging

from amplifier_tui.core.features.projector_client import (
    PROJECT_STATUS_ICONS,
    ProjectorClient,
)

logger = logging.getLogger(__name__)


class ProjectorCommandsMixin:
    """
    Adds /projector commands to the TUI.

    Slash commands:
        /projector           - Toggle project panel, refresh data
        /projector projects  - List all projects with status
        /projector tasks     - Show tasks for current/named project
        /projector strategies - List active strategies
        /projector status    - Show current project context (detected from cwd)
        /projector outcomes <name> - Show recent session outcomes for a project
    """

    _projector_client: ProjectorClient | None = None

    def _ensure_projector(self) -> ProjectorClient:
        """Lazily initialize the Projector client."""
        if self._projector_client is None:
            self._projector_client = ProjectorClient()
        return self._projector_client

    def _cmd_projector(self, args: str) -> None:
        """Handle /projector commands."""
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if not subcmd:
            # Toggle panel and refresh
            self._projector_toggle_panel()
            return

        handlers = {
            "projects": self._projector_list_projects,
            "tasks": self._projector_show_tasks,
            "strategies": self._projector_list_strategies,
            "status": self._projector_show_status,
            "outcomes": self._projector_show_outcomes,
        }

        handler = handlers.get(subcmd)
        if handler:
            handler(rest)
        else:
            self._add_system_message(  # type: ignore[attr-defined]
                f"Unknown projector command: {subcmd}\n"
                "Available: projects, tasks, strategies, status, outcomes"
            )

    def _projector_toggle_panel(self) -> None:
        """Toggle the project panel visibility and refresh its data."""
        self._ensure_projector()

        try:
            panel = self.query_one("#project-panel")  # type: ignore[attr-defined]
        except Exception:
            self._add_system_message("Project panel not available")  # type: ignore[attr-defined]
            return

        panel.visible = not panel.visible
        if panel.visible:
            self._projector_refresh_panel()

    def _projector_refresh_panel(self) -> None:
        """Refresh the project panel with current data."""
        client = self._ensure_projector()

        if not client.available:
            self._add_system_message(  # type: ignore[attr-defined]
                "Projector data not found at ~/.amplifier/projector/\n"
                "Install: amplifier bundle add "
                "git+https://github.com/ramparte/amplifier-bundle-projector@main"
            )
            return

        projects = client.list_projects()
        strategies = client.list_strategies(active_only=True)

        try:
            panel = self.query_one("#project-panel")  # type: ignore[attr-defined]
            panel.update_projects(projects, strategies)
        except Exception:
            logger.debug("Failed to refresh project panel", exc_info=True)

    def _projector_list_projects(self, args: str) -> None:
        """List all Projector projects."""
        projects = self._ensure_projector().list_projects()
        if not projects:
            self._add_system_message("No Projector projects found.")  # type: ignore[attr-defined]
            return

        lines = ["**Projector Projects**\n"]
        for p in projects:
            icon = PROJECT_STATUS_ICONS.get(p.status, " ")
            tasks = f" ({p.task_count} tasks)" if p.task_count else ""
            lines.append(f"  [{icon}] **{p.name}**{tasks} - {p.description[:60]}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _projector_show_tasks(self, project_name: str) -> None:
        """Show tasks for a project (auto-detects if no name given)."""
        client = self._ensure_projector()

        if not project_name:
            detected = self._projector_detect_current()
            if detected:
                project_name = detected.name
            else:
                self._add_system_message(  # type: ignore[attr-defined]
                    "No project specified and none detected from cwd. "
                    "Usage: /projector tasks <name>"
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
        lines = [f"**Tasks: {project_name}**\n"]
        for t in tasks:
            lines.append(f"  {task_icons.get(t.status, '[ ]')} {t.id}: {t.title}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _projector_list_strategies(self, args: str) -> None:
        """List active strategies."""
        strategies = self._ensure_projector().list_strategies(
            active_only="all" not in args
        )
        if not strategies:
            self._add_system_message("No strategies found.")  # type: ignore[attr-defined]
            return

        lines = ["**Active Strategies**\n"]
        for s in strategies:
            tag = "on" if s.active else "off"
            lines.append(f"  [{tag}] **{s.name}** - {s.description[:60]}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _projector_show_status(self, args: str) -> None:
        """Show Projector context for current working directory."""
        self._ensure_projector()

        detected = self._projector_detect_current()
        if not detected:
            self._add_system_message(  # type: ignore[attr-defined]
                "No Projector project detected for current directory.\n"
                "Use /projector projects to see all projects."
            )
            return

        lines = [
            f"**Project: {detected.name}**",
            f"Status: {detected.status}",
            f"Repos: {', '.join(detected.repos) if detected.repos else 'none'}",
        ]
        if detected.task_count:
            lines.append(f"Active tasks: {detected.task_count}")
        if detected.recent_outcomes:
            lines.append("\n**Recent outcomes:**")
            for o in detected.recent_outcomes[-3:]:
                summary = o.get("summary", "no summary")[:80]
                lines.append(f"  - {summary}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _projector_show_outcomes(self, project_name: str) -> None:
        """Show recent session outcomes for a project."""
        client = self._ensure_projector()

        if not project_name:
            detected = self._projector_detect_current()
            project_name = detected.name if detected else ""

        if not project_name:
            self._add_system_message("Usage: /projector outcomes <name>")  # type: ignore[attr-defined]
            return

        proj = client.get_project(project_name)
        if not proj:
            self._add_system_message(f"Project not found: {project_name}")  # type: ignore[attr-defined]
            return

        if not proj.recent_outcomes:
            self._add_system_message(f"No recorded outcomes for {project_name}")  # type: ignore[attr-defined]
            return

        lines = [f"**Recent Outcomes: {project_name}**\n"]
        for o in proj.recent_outcomes:
            ts = o.get("timestamp", "?")[:10]
            summary = o.get("summary", "no summary")
            lines.append(f"  [{ts}] {summary}")

        self._add_system_message("\n".join(lines))  # type: ignore[attr-defined]

    def _projector_detect_current(self):
        """Detect Projector project from current session's working dir."""
        import os

        cwd = os.getcwd()

        # If we have an active session with a working dir, prefer that
        if hasattr(self, "_current_conversation_id"):
            conv_id = self._current_conversation_id  # type: ignore[attr-defined]
            if hasattr(self, "_session_manager"):
                handle = self._session_manager.get_handle(conv_id)  # type: ignore[attr-defined]
                if handle and hasattr(handle, "working_dir") and handle.working_dir:
                    cwd = handle.working_dir

        return self._ensure_projector().detect_project(cwd)
