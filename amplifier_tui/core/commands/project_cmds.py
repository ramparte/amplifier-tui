"""Project aggregation commands (/project).

Provides a view of sessions grouped by project with tag statistics.
"""

from __future__ import annotations

from amplifier_tui.core.features.project_aggregator import ProjectAggregator


class ProjectCommandsMixin:
    """/project command mixin."""

    def _cmd_project(self, args: str) -> None:
        """Handle /project commands.

        Usage:
            /project           -- list all projects with counts
            /project <name>    -- show details for a project
        """
        query = args.strip()

        # Load current data
        sessions = self._session_list_data  # type: ignore[attr-defined]
        if not sessions:
            self._add_system_message("No sessions loaded.")  # type: ignore[attr-defined]
            return

        all_tags = self._tag_store.load()  # type: ignore[attr-defined]
        projects = ProjectAggregator.aggregate(sessions, all_tags)

        if not query:
            # List all projects
            summary = ProjectAggregator.format_all_projects(projects)
            self._add_system_message(summary)  # type: ignore[attr-defined]
            return

        # Look up specific project
        info = ProjectAggregator.get_project(projects, query)
        if info is None:
            self._add_system_message(  # type: ignore[attr-defined]
                f"No project matching '{query}'.\nUse /project to list all projects."
            )
            return

        detail = ProjectAggregator.format_project_summary(info)

        # Also show recent sessions
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
