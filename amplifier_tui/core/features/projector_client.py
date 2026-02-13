"""Projector data access for TUI."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Shared constants for consistent display across commands and widgets
PROJECT_STATUS_ICONS: dict[str, str] = {
    "active": "*",
    "paused": "~",
    "completed": "+",
    "idea": "?",
}


@dataclass
class ProjectorProject:
    """A Projector project."""

    name: str
    description: str
    status: str  # active, paused, completed, idea
    repos: list[str] = field(default_factory=list)
    relationships: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    task_count: int = 0
    recent_outcomes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProjectorStrategy:
    """A Projector strategy."""

    name: str
    description: str
    active: bool
    scope: str  # global or project-specific
    tags: list[str] = field(default_factory=list)


@dataclass
class ProjectorTask:
    """A task within a project."""

    id: str
    title: str
    status: str  # pending, in_progress, completed, blocked
    priority: str = "medium"
    project: str = ""


class ProjectorClient:
    """
    Reads Projector data from ~/.amplifier/projector/.

    This is a read-only client for the TUI to display Projector state.
    Mutations go through the Projector tool (in-session) or distro API.
    """

    def __init__(self, data_path: Path | None = None):
        self._data_path = data_path or Path.home() / ".amplifier" / "projector"

    @property
    def available(self) -> bool:
        """Check if Projector data exists."""
        return self._data_path.exists()

    def list_projects(self) -> list[ProjectorProject]:
        """List all projects with task counts and recent outcomes."""
        projects_dir = self._data_path / "projects"
        if not projects_dir.exists():
            return []

        results = []
        for proj_dir in sorted(projects_dir.iterdir()):
            proj_file = proj_dir / "project.yaml"
            if not proj_file.exists():
                continue
            try:
                data = yaml.safe_load(proj_file.read_text())
                proj = ProjectorProject(
                    name=data.get("name", proj_dir.name),
                    description=data.get("description", ""),
                    status=data.get("status", "active"),
                    repos=data.get("repos", []),
                    relationships=data.get("relationships", []),
                    tags=data.get("tags", []),
                )
                # Count tasks
                tasks_file = proj_dir / "tasks.yaml"
                if tasks_file.exists():
                    tasks = yaml.safe_load(tasks_file.read_text())
                    if isinstance(tasks, list):
                        proj.task_count = len(
                            [t for t in tasks if t.get("status") != "completed"]
                        )

                # Last 3 outcomes
                outcomes_file = proj_dir / "outcomes.jsonl"
                if outcomes_file.exists():
                    lines = outcomes_file.read_text().strip().splitlines()
                    for line in lines[-3:]:
                        try:
                            proj.recent_outcomes.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

                results.append(proj)
            except Exception:
                logger.debug("Failed to load project from %s", proj_dir, exc_info=True)
                continue

        return results

    def get_project(self, name: str) -> ProjectorProject | None:
        """Get a single project by name."""
        for p in self.list_projects():
            if p.name == name:
                return p
        return None

    def list_strategies(self, active_only: bool = True) -> list[ProjectorStrategy]:
        """List strategies."""
        strat_dir = self._data_path / "strategies"
        if not strat_dir.exists():
            return []

        results = []
        for f in sorted(strat_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text())
                strat = ProjectorStrategy(
                    name=data.get("name", f.stem),
                    description=data.get("description", ""),
                    active=data.get("active", True),
                    scope=data.get("scope", "global"),
                    tags=data.get("tags", []),
                )
                if active_only and not strat.active:
                    continue
                results.append(strat)
            except Exception:
                logger.debug("Failed to load strategy from %s", f, exc_info=True)
                continue

        return results

    def get_tasks(self, project_name: str) -> list[ProjectorTask]:
        """Get tasks for a project."""
        tasks_file = self._data_path / "projects" / project_name / "tasks.yaml"
        if not tasks_file.exists():
            return []

        try:
            data = yaml.safe_load(tasks_file.read_text())
            if not isinstance(data, list):
                return []
            return [
                ProjectorTask(
                    id=t.get("id", ""),
                    title=t.get("title", ""),
                    status=t.get("status", "pending"),
                    priority=t.get("priority", "medium"),
                    project=project_name,
                )
                for t in data
            ]
        except Exception:
            logger.debug("Failed to load tasks for %s", project_name, exc_info=True)
            return []

    def detect_project(self, working_dir: str | Path) -> ProjectorProject | None:
        """
        Detect which Projector project matches a working directory.

        Checks if any project's repos list contains a path that matches
        the working directory (by resolved path or basename).
        """
        working_dir = Path(working_dir).resolve()
        dir_name = working_dir.name

        for proj in self.list_projects():
            for repo in proj.repos:
                repo_path = Path(repo).expanduser()
                # Compare by resolved absolute path if repo looks like a path
                if "/" in repo:
                    try:
                        if working_dir == repo_path.resolve():
                            return proj
                    except OSError:
                        pass
                # Fall back to basename comparison
                if repo_path.name == dir_name:
                    return proj
        return None
