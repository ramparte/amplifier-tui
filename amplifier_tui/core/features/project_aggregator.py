"""Project-level aggregation of sessions and tags.

Provides a unified view of sessions grouped by project, enriched with
tag data and basic statistics.  Entirely stateless -- aggregation runs
on demand from the data already loaded by the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProjectInfo:
    """Aggregated information about a project."""

    name: str
    project_path: str
    session_count: int = 0
    sessions: list[dict] = field(default_factory=list)
    tags: dict[str, int] = field(default_factory=dict)  # {tag: count}
    latest_mtime: float = 0.0
    latest_date_str: str = ""

    @property
    def top_tags(self) -> list[str]:
        """Return tags sorted by frequency (most common first)."""
        return [t for t, _ in sorted(self.tags.items(), key=lambda x: -x[1])]


class ProjectAggregator:
    """Aggregate sessions and tags into project-level views.

    Usage::

        agg = ProjectAggregator()
        projects = agg.aggregate(sessions, all_tags)
        info = agg.get_project(projects, "amplifier-tui")
    """

    @staticmethod
    def aggregate(
        sessions: list[dict],
        all_tags: dict[str, list[str]],
    ) -> dict[str, ProjectInfo]:
        """Group sessions by project and compute per-project stats.

        Parameters
        ----------
        sessions:
            List of session dicts from ``SessionManager.list_all_sessions()``.
            Each dict has keys: session_id, project, project_path, mtime,
            date_str, name, description.
        all_tags:
            Tag data from ``TagStore.load()``.
            ``{session_id: [tag1, tag2, ...]}``.

        Returns
        -------
        dict mapping project name to ``ProjectInfo``.
        """
        projects: dict[str, ProjectInfo] = {}

        for s in sessions:
            project_name = s["project"]
            if project_name not in projects:
                projects[project_name] = ProjectInfo(
                    name=project_name,
                    project_path=s.get("project_path", project_name),
                )

            info = projects[project_name]
            info.session_count += 1
            info.sessions.append(s)

            # Track latest activity
            if s["mtime"] > info.latest_mtime:
                info.latest_mtime = s["mtime"]
                info.latest_date_str = s["date_str"]

            # Accumulate tags
            sid = s["session_id"]
            for tag in all_tags.get(sid, []):
                info.tags[tag] = info.tags.get(tag, 0) + 1

        return projects

    @staticmethod
    def get_project(
        projects: dict[str, ProjectInfo],
        name: str,
    ) -> ProjectInfo | None:
        """Find a project by name (case-insensitive partial match)."""
        # Exact match first
        if name in projects:
            return projects[name]
        # Case-insensitive exact match
        lower = name.lower()
        for pname, info in projects.items():
            if pname.lower() == lower:
                return info
        # Partial match
        for pname, info in projects.items():
            if lower in pname.lower():
                return info
        return None

    @staticmethod
    def format_project_summary(info: ProjectInfo) -> str:
        """Format a project summary for display."""
        lines = [
            f"Project: {info.name}",
            f"  Path: {info.project_path}",
            f"  Sessions: {info.session_count}",
            f"  Last active: {info.latest_date_str}",
        ]
        if info.tags:
            top = info.top_tags[:5]
            tag_str = "  ".join(f"#{t}({info.tags[t]})" for t in top)
            lines.append(f"  Top tags: {tag_str}")
        return "\n".join(lines)

    @staticmethod
    def format_all_projects(projects: dict[str, ProjectInfo]) -> str:
        """Format a summary of all projects for display."""
        if not projects:
            return "No projects found."

        # Sort by latest activity
        sorted_projects = sorted(
            projects.values(),
            key=lambda p: p.latest_mtime,
            reverse=True,
        )

        lines = [f"Projects ({len(sorted_projects)}):"]
        for p in sorted_projects:
            tags_str = ""
            if p.top_tags:
                tags_str = "  " + " ".join(f"#{t}" for t in p.top_tags[:3])
            lines.append(
                f"  {p.name} ({p.session_count} sessions, "
                f"last: {p.latest_date_str}){tags_str}"
            )
        return "\n".join(lines)
