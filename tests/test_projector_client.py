"""Tests for Projector data access client."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from amplifier_tui.core.features.projector_client import (
    PROJECT_STATUS_ICONS,
    ProjectorClient,
    ProjectorProject,
    ProjectorStrategy,
    ProjectorTask,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_project(
    base: Path,
    name: str,
    *,
    status: str = "active",
    description: str = "A test project",
    repos: list[str] | None = None,
    tasks: list[dict] | None = None,
    outcomes: list[dict] | None = None,
) -> Path:
    """Create a project directory with optional tasks and outcomes."""
    proj_dir = base / "projects" / name
    proj_dir.mkdir(parents=True, exist_ok=True)

    project_data = {
        "name": name,
        "description": description,
        "status": status,
        "repos": repos or [],
        "tags": ["test"],
    }
    (proj_dir / "project.yaml").write_text(yaml.dump(project_data))

    if tasks is not None:
        (proj_dir / "tasks.yaml").write_text(yaml.dump(tasks))

    if outcomes is not None:
        lines = [json.dumps(o) for o in outcomes]
        (proj_dir / "outcomes.jsonl").write_text("\n".join(lines) + "\n")

    return proj_dir


def _make_strategy(
    base: Path,
    name: str,
    *,
    active: bool = True,
    description: str = "A test strategy",
    scope: str = "global",
) -> Path:
    """Create a strategy YAML file."""
    strat_dir = base / "strategies"
    strat_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "name": name,
        "description": description,
        "active": active,
        "scope": scope,
    }
    path = strat_dir / f"{name}.yaml"
    path.write_text(yaml.dump(data))
    return path


# ---------------------------------------------------------------------------
# Dataclass construction
# ---------------------------------------------------------------------------


class TestProjectorProject:
    def test_defaults(self):
        p = ProjectorProject(name="x", description="d", status="active")
        assert p.repos == []
        assert p.task_count == 0
        assert p.recent_outcomes == []
        assert p.tags == []

    def test_mutable_isolation(self):
        a = ProjectorProject(name="a", description="", status="active")
        b = ProjectorProject(name="b", description="", status="active")
        a.repos.append("r1")
        assert b.repos == []


class TestProjectorStrategy:
    def test_defaults(self):
        s = ProjectorStrategy(name="s", description="d", active=True, scope="global")
        assert s.tags == []


class TestProjectorTask:
    def test_defaults(self):
        t = ProjectorTask(id="T-1", title="Do thing", status="pending")
        assert t.priority == "medium"
        assert t.project == ""


# ---------------------------------------------------------------------------
# Client: available
# ---------------------------------------------------------------------------


class TestClientAvailable:
    def test_not_available_missing_dir(self, tmp_path: Path):
        client = ProjectorClient(data_path=tmp_path / "nonexistent")
        assert client.available is False

    def test_available_when_dir_exists(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        data_dir.mkdir()
        client = ProjectorClient(data_path=data_dir)
        assert client.available is True


# ---------------------------------------------------------------------------
# Client: list_projects
# ---------------------------------------------------------------------------


class TestListProjects:
    def test_empty_no_projects_dir(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        data_dir.mkdir()
        client = ProjectorClient(data_path=data_dir)
        assert client.list_projects() == []

    def test_empty_projects_dir(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        (data_dir / "projects").mkdir(parents=True)
        client = ProjectorClient(data_path=data_dir)
        assert client.list_projects() == []

    def test_single_project(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "alpha", description="First project")
        client = ProjectorClient(data_path=data_dir)
        projects = client.list_projects()
        assert len(projects) == 1
        assert projects[0].name == "alpha"
        assert projects[0].description == "First project"
        assert projects[0].status == "active"

    def test_multiple_projects_sorted(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "beta")
        _make_project(data_dir, "alpha")
        client = ProjectorClient(data_path=data_dir)
        names = [p.name for p in client.list_projects()]
        assert names == ["alpha", "beta"]

    def test_task_count_excludes_completed(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        tasks = [
            {"id": "T-1", "title": "A", "status": "pending"},
            {"id": "T-2", "title": "B", "status": "completed"},
            {"id": "T-3", "title": "C", "status": "in_progress"},
        ]
        _make_project(data_dir, "proj", tasks=tasks)
        client = ProjectorClient(data_path=data_dir)
        proj = client.list_projects()[0]
        assert proj.task_count == 2  # pending + in_progress

    def test_outcomes_loaded(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        outcomes = [
            {"summary": "Did A", "timestamp": "2026-01-01T00:00:00Z"},
            {"summary": "Did B", "timestamp": "2026-01-02T00:00:00Z"},
            {"summary": "Did C", "timestamp": "2026-01-03T00:00:00Z"},
            {"summary": "Did D", "timestamp": "2026-01-04T00:00:00Z"},
        ]
        _make_project(data_dir, "proj", outcomes=outcomes)
        client = ProjectorClient(data_path=data_dir)
        proj = client.list_projects()[0]
        # Only last 3 outcomes loaded
        assert len(proj.recent_outcomes) == 3
        assert proj.recent_outcomes[0]["summary"] == "Did B"

    def test_malformed_yaml_skipped(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "good")
        # Create a malformed project
        bad_dir = data_dir / "projects" / "bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "project.yaml").write_text("{{invalid yaml: [")
        client = ProjectorClient(data_path=data_dir)
        projects = client.list_projects()
        assert len(projects) == 1
        assert projects[0].name == "good"

    def test_missing_project_yaml_skipped(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "good")
        # Create a dir without project.yaml
        (data_dir / "projects" / "empty").mkdir(parents=True)
        client = ProjectorClient(data_path=data_dir)
        projects = client.list_projects()
        assert len(projects) == 1

    def test_non_list_tasks_yaml(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        proj_dir = _make_project(data_dir, "proj")
        # Overwrite tasks with non-list YAML
        (proj_dir / "tasks.yaml").write_text(yaml.dump({"not": "a list"}))
        client = ProjectorClient(data_path=data_dir)
        proj = client.list_projects()[0]
        assert proj.task_count == 0


# ---------------------------------------------------------------------------
# Client: get_project
# ---------------------------------------------------------------------------


class TestGetProject:
    def test_found(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "target")
        client = ProjectorClient(data_path=data_dir)
        proj = client.get_project("target")
        assert proj is not None
        assert proj.name == "target"

    def test_not_found(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "other")
        client = ProjectorClient(data_path=data_dir)
        assert client.get_project("missing") is None


# ---------------------------------------------------------------------------
# Client: list_strategies
# ---------------------------------------------------------------------------


class TestListStrategies:
    def test_no_strategies_dir(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        data_dir.mkdir()
        client = ProjectorClient(data_path=data_dir)
        assert client.list_strategies() == []

    def test_active_only(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_strategy(data_dir, "active-one", active=True)
        _make_strategy(data_dir, "inactive-one", active=False)
        client = ProjectorClient(data_path=data_dir)
        strats = client.list_strategies(active_only=True)
        assert len(strats) == 1
        assert strats[0].name == "active-one"

    def test_all_strategies(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_strategy(data_dir, "a", active=True)
        _make_strategy(data_dir, "b", active=False)
        client = ProjectorClient(data_path=data_dir)
        strats = client.list_strategies(active_only=False)
        assert len(strats) == 2

    def test_malformed_yaml_skipped(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_strategy(data_dir, "good")
        (data_dir / "strategies" / "bad.yaml").write_text("{{not yaml")
        client = ProjectorClient(data_path=data_dir)
        strats = client.list_strategies()
        assert len(strats) == 1


# ---------------------------------------------------------------------------
# Client: get_tasks
# ---------------------------------------------------------------------------


class TestGetTasks:
    def test_missing_file(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        data_dir.mkdir()
        client = ProjectorClient(data_path=data_dir)
        assert client.get_tasks("nope") == []

    def test_valid_tasks(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        tasks = [
            {"id": "T-1", "title": "First", "status": "pending"},
            {
                "id": "T-2",
                "title": "Second",
                "status": "in_progress",
                "priority": "high",
            },
        ]
        _make_project(data_dir, "proj", tasks=tasks)
        client = ProjectorClient(data_path=data_dir)
        result = client.get_tasks("proj")
        assert len(result) == 2
        assert result[0].id == "T-1"
        assert result[0].status == "pending"
        assert result[0].priority == "medium"  # default
        assert result[1].priority == "high"
        assert result[1].project == "proj"

    def test_non_list_returns_empty(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        proj_dir = _make_project(data_dir, "proj")
        (proj_dir / "tasks.yaml").write_text(yaml.dump("just a string"))
        client = ProjectorClient(data_path=data_dir)
        assert client.get_tasks("proj") == []

    def test_corrupt_yaml_returns_empty(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        proj_dir = _make_project(data_dir, "proj")
        (proj_dir / "tasks.yaml").write_text("{{bad yaml")
        client = ProjectorClient(data_path=data_dir)
        assert client.get_tasks("proj") == []


# ---------------------------------------------------------------------------
# Client: detect_project
# ---------------------------------------------------------------------------


class TestDetectProject:
    def test_match_by_basename(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "myproj", repos=["my-repo"])
        # Create a working directory with matching basename
        work_dir = tmp_path / "workspace" / "my-repo"
        work_dir.mkdir(parents=True)
        client = ProjectorClient(data_path=data_dir)
        result = client.detect_project(work_dir)
        assert result is not None
        assert result.name == "myproj"

    def test_no_match(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "myproj", repos=["other-repo"])
        work_dir = tmp_path / "workspace" / "unrelated"
        work_dir.mkdir(parents=True)
        client = ProjectorClient(data_path=data_dir)
        assert client.detect_project(work_dir) is None

    def test_no_partial_basename_match(self, tmp_path: Path):
        """Ensure 'core' doesn't match 'bar-core' (old bug)."""
        data_dir = tmp_path / "projector"
        _make_project(data_dir, "myproj", repos=["bar-core"])
        work_dir = tmp_path / "workspace" / "core"
        work_dir.mkdir(parents=True)
        client = ProjectorClient(data_path=data_dir)
        # basename "core" != basename "bar-core"
        assert client.detect_project(work_dir) is None

    def test_match_by_resolved_path(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        work_dir = tmp_path / "workspace" / "my-repo"
        work_dir.mkdir(parents=True)
        _make_project(data_dir, "myproj", repos=[str(work_dir)])
        client = ProjectorClient(data_path=data_dir)
        result = client.detect_project(work_dir)
        assert result is not None
        assert result.name == "myproj"

    def test_empty_projects(self, tmp_path: Path):
        data_dir = tmp_path / "projector"
        data_dir.mkdir()
        client = ProjectorClient(data_path=data_dir)
        assert client.detect_project(tmp_path) is None


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------


class TestStatusIcons:
    def test_all_statuses_have_icons(self):
        for status in ("active", "paused", "completed", "idea"):
            assert status in PROJECT_STATUS_ICONS
