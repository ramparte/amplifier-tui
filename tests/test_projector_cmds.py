"""Tests for Projector subcommands in the unified /project mixin."""

from __future__ import annotations

from unittest.mock import MagicMock

from amplifier_tui.core.commands.project_cmds import ProjectCommandsMixin
from amplifier_tui.core.features.projector_client import (
    ProjectorClient,
    ProjectorProject,
    ProjectorStrategy,
    ProjectorTask,
)


# ---------------------------------------------------------------------------
# MockApp -- minimal stub satisfying self.* contracts for the mixin
# ---------------------------------------------------------------------------


class MockApp:
    """Stub for the app attributes that ProjectCommandsMixin expects."""

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._session_list_data: list[dict] = []

    def _add_system_message(self, text: str) -> None:
        self._messages.append(text)

    def query_one(self, selector: str):
        raise Exception("No DOM in tests")


class _TagStore:
    def load(self) -> dict:
        return {}


class _ProjectApp(ProjectCommandsMixin, MockApp):
    """Composite of mixin under test + MockApp."""

    def __init__(self) -> None:
        MockApp.__init__(self)
        self._tag_store = _TagStore()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_projects() -> list[ProjectorProject]:
    return [
        ProjectorProject(
            name="alpha",
            description="First project with a long description that gets truncated",
            status="active",
            repos=["repo-a"],
            task_count=3,
        ),
        ProjectorProject(
            name="beta",
            description="Second project",
            status="paused",
        ),
    ]


def _sample_strategies() -> list[ProjectorStrategy]:
    return [
        ProjectorStrategy(
            name="focus",
            description="Focus on core features for the quarter",
            active=True,
            scope="global",
        ),
    ]


def _sample_tasks() -> list[ProjectorTask]:
    return [
        ProjectorTask(id="T-1", title="Build thing", status="pending"),
        ProjectorTask(id="T-2", title="Fix bug", status="in_progress"),
    ]


# ---------------------------------------------------------------------------
# _ensure_projector lazy init
# ---------------------------------------------------------------------------


class TestEnsureProjector:
    def test_creates_client_on_first_call(self):
        app = _ProjectApp()
        assert app._projector_client is None
        client = app._ensure_projector()
        assert isinstance(client, ProjectorClient)
        assert app._projector_client is client

    def test_reuses_client(self):
        app = _ProjectApp()
        c1 = app._ensure_projector()
        c2 = app._ensure_projector()
        assert c1 is c2


# ---------------------------------------------------------------------------
# Unified command dispatch
# ---------------------------------------------------------------------------


class TestCommandDispatch:
    def _make_app(self) -> _ProjectApp:
        app = _ProjectApp()
        app._cmd_project_help = MagicMock()  # type: ignore[assignment]
        app._cmd_project_tasks = MagicMock()  # type: ignore[assignment]
        app._cmd_project_strategies = MagicMock()  # type: ignore[assignment]
        app._cmd_project_status = MagicMock()  # type: ignore[assignment]
        app._cmd_project_outcomes = MagicMock()  # type: ignore[assignment]
        app._cmd_project_panel = MagicMock()  # type: ignore[assignment]
        app._cmd_project_brief = MagicMock()  # type: ignore[assignment]
        app._cmd_project_focus = MagicMock()  # type: ignore[assignment]
        app._cmd_project_list_or_detail = MagicMock()  # type: ignore[assignment]
        return app

    def test_help_subcommand(self):
        app = self._make_app()
        app._cmd_project("help")
        app._cmd_project_help.assert_called_once_with("")  # type: ignore[union-attr]

    def test_tasks_subcommand_with_arg(self):
        app = self._make_app()
        app._cmd_project("tasks my-project")
        app._cmd_project_tasks.assert_called_once_with("my-project")  # type: ignore[union-attr]

    def test_strategies_subcommand(self):
        app = self._make_app()
        app._cmd_project("strategies")
        app._cmd_project_strategies.assert_called_once_with("")  # type: ignore[union-attr]

    def test_status_subcommand(self):
        app = self._make_app()
        app._cmd_project("status")
        app._cmd_project_status.assert_called_once_with("")  # type: ignore[union-attr]

    def test_outcomes_subcommand(self):
        app = self._make_app()
        app._cmd_project("outcomes alpha")
        app._cmd_project_outcomes.assert_called_once_with("alpha")  # type: ignore[union-attr]

    def test_panel_subcommand(self):
        app = self._make_app()
        app._cmd_project("panel")
        app._cmd_project_panel.assert_called_once_with("")  # type: ignore[union-attr]

    def test_brief_subcommand(self):
        app = self._make_app()
        app._cmd_project("brief my-proj")
        app._cmd_project_brief.assert_called_once_with("my-proj")  # type: ignore[union-attr]

    def test_focus_subcommand(self):
        app = self._make_app()
        app._cmd_project("focus")
        app._cmd_project_focus.assert_called_once_with("")  # type: ignore[union-attr]

    def test_no_args_lists_projects(self):
        app = self._make_app()
        app._cmd_project("")
        app._cmd_project_list_or_detail.assert_called_once_with("")  # type: ignore[union-attr]

    def test_unknown_name_goes_to_list_or_detail(self):
        app = self._make_app()
        app._cmd_project("some-project-name")
        app._cmd_project_list_or_detail.assert_called_once_with("some-project-name")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# /project tasks
# ---------------------------------------------------------------------------


class TestShowTasks:
    def test_no_name_no_detection(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.detect_project.return_value = None
        app._projector_client = mock_client
        app._projector_detect_current = MagicMock(return_value=None)  # type: ignore[assignment]
        app._cmd_project_tasks("")
        assert any("Usage:" in m for m in app._messages)

    def test_no_tasks(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.get_tasks.return_value = []
        app._projector_client = mock_client
        app._cmd_project_tasks("proj")
        assert any("No tasks for proj" in m for m in app._messages)

    def test_with_tasks(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.get_tasks.return_value = _sample_tasks()
        app._projector_client = mock_client
        app._cmd_project_tasks("proj")
        msg = app._messages[0]
        assert "T-1" in msg
        assert "T-2" in msg
        assert "[ ]" in msg  # pending
        assert "[>]" in msg  # in_progress


# ---------------------------------------------------------------------------
# /project strategies
# ---------------------------------------------------------------------------


class TestListStrategies:
    def test_no_strategies(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.list_strategies.return_value = []
        app._projector_client = mock_client
        app._cmd_project_strategies("")
        assert any("No strategies" in m for m in app._messages)

    def test_with_strategies(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.list_strategies.return_value = _sample_strategies()
        app._projector_client = mock_client
        app._cmd_project_strategies("")
        msg = app._messages[0]
        assert "focus" in msg
        assert "[on]" in msg

    def test_all_flag(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.list_strategies.return_value = _sample_strategies()
        app._projector_client = mock_client
        app._cmd_project_strategies("all")
        mock_client.list_strategies.assert_called_once_with(active_only=False)


# ---------------------------------------------------------------------------
# /project status
# ---------------------------------------------------------------------------


class TestShowStatus:
    def test_no_detection(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        app._projector_client = mock_client
        app._projector_detect_current = MagicMock(return_value=None)  # type: ignore[assignment]
        app._cmd_project_status("")
        assert any("No Projector project detected" in m for m in app._messages)

    def test_detected_project(self):
        proj = ProjectorProject(
            name="my-proj",
            description="desc",
            status="active",
            repos=["repo-1", "repo-2"],
            people=["alice", "bob"],
            task_count=5,
            recent_outcomes=[{"summary": "Did something"}],
        )
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        app._projector_client = mock_client
        app._projector_detect_current = MagicMock(return_value=proj)  # type: ignore[assignment]
        app._cmd_project_status("")
        msg = app._messages[0]
        assert "my-proj" in msg
        assert "active" in msg
        assert "repo-1" in msg
        assert "Active tasks: 5" in msg
        assert "Did something" in msg
        assert "alice" in msg


# ---------------------------------------------------------------------------
# /project outcomes
# ---------------------------------------------------------------------------


class TestShowOutcomes:
    def test_no_name_no_detection(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        app._projector_client = mock_client
        app._projector_detect_current = MagicMock(return_value=None)  # type: ignore[assignment]
        app._cmd_project_outcomes("")
        assert any("Usage:" in m for m in app._messages)

    def test_project_not_found(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.get_project.return_value = None
        app._projector_client = mock_client
        app._cmd_project_outcomes("missing")
        assert any("not found" in m for m in app._messages)

    def test_no_outcomes(self):
        proj = ProjectorProject(
            name="proj", description="d", status="active", recent_outcomes=[]
        )
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.get_project.return_value = proj
        app._projector_client = mock_client
        app._cmd_project_outcomes("proj")
        assert any("No recorded outcomes" in m for m in app._messages)

    def test_with_outcomes(self):
        proj = ProjectorProject(
            name="proj",
            description="d",
            status="active",
            recent_outcomes=[
                {"summary": "Built auth", "timestamp": "2026-01-15T10:00:00Z"},
                {"summary": "Fixed bug", "timestamp": "2026-01-16T10:00:00Z"},
            ],
        )
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = True
        mock_client.get_project.return_value = proj
        app._projector_client = mock_client
        app._cmd_project_outcomes("proj")
        msg = app._messages[0]
        assert "Built auth" in msg
        assert "Fixed bug" in msg
        assert "2026-01-15" in msg


# ---------------------------------------------------------------------------
# /project help
# ---------------------------------------------------------------------------


class TestHelp:
    def test_help_output(self):
        app = _ProjectApp()
        app._cmd_project("help")
        assert len(app._messages) == 1
        msg = app._messages[0]
        assert "/project help" in msg
        assert "/project tasks" in msg
        assert "/project strategies" in msg
        assert "/project focus" in msg
        assert "/project brief" in msg
        assert "/projector" in msg  # alias mention


# ---------------------------------------------------------------------------
# /project not-available (graceful degradation)
# ---------------------------------------------------------------------------


class TestProjectorNotAvailable:
    def test_tasks_without_projector(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = False
        app._projector_client = mock_client
        app._cmd_project_tasks("proj")
        assert any("No Projector data" in m for m in app._messages)

    def test_strategies_without_projector(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = False
        app._projector_client = mock_client
        app._cmd_project_strategies("")
        assert any("No Projector data" in m for m in app._messages)

    def test_status_without_projector(self):
        app = _ProjectApp()
        mock_client = MagicMock(spec=ProjectorClient)
        mock_client.available = False
        app._projector_client = mock_client
        app._cmd_project_status("")
        assert any("No Projector data" in m for m in app._messages)


# ---------------------------------------------------------------------------
# _resolve_project_from_text (smart project detection from question text)
# ---------------------------------------------------------------------------


def _sessions_with_projects() -> list[dict]:
    """Create sessions spanning multiple projects for resolution tests."""
    import time

    now = time.time()
    return [
        {
            "session_id": "aaa",
            "project": "kepler",
            "project_path": "/home/user/dev/kepler",
            "mtime": now - 100,
            "date_str": "02/12",
        },
        {
            "session_id": "bbb",
            "project": "amplifier-tui",
            "project_path": "/home/user/dev/amplifier-tui",
            "mtime": now - 200,
            "date_str": "02/11",
        },
        {
            "session_id": "ccc",
            "project": "amplifier-core",
            "project_path": "/home/user/dev/amplifier-core",
            "mtime": now - 300,
            "date_str": "02/10",
        },
    ]


class TestResolveProjectFromText:
    def test_finds_project_in_question(self):
        app = _ProjectApp()
        app._session_list_data = _sessions_with_projects()
        result = app._resolve_project_from_text("what's up with kepler?")
        assert result == "kepler"

    def test_finds_project_case_insensitive(self):
        app = _ProjectApp()
        app._session_list_data = _sessions_with_projects()
        result = app._resolve_project_from_text("Tell me about KEPLER")
        assert result == "kepler"

    def test_finds_hyphenated_project(self):
        app = _ProjectApp()
        app._session_list_data = _sessions_with_projects()
        result = app._resolve_project_from_text("what happened in amplifier-tui?")
        assert result == "amplifier-tui"

    def test_returns_none_when_no_match(self):
        app = _ProjectApp()
        app._session_list_data = _sessions_with_projects()
        result = app._resolve_project_from_text("how is the weather today?")
        assert result is None

    def test_returns_none_with_no_sessions(self):
        app = _ProjectApp()
        app._session_list_data = []
        result = app._resolve_project_from_text("what about kepler?")
        assert result is None

    def test_strips_punctuation(self):
        app = _ProjectApp()
        app._session_list_data = _sessions_with_projects()
        # kepler followed by question mark, comma, period
        assert app._resolve_project_from_text("kepler?") == "kepler"
        assert app._resolve_project_from_text("kepler,") == "kepler"
        assert app._resolve_project_from_text("(kepler)") == "kepler"

    def test_first_match_wins(self):
        app = _ProjectApp()
        app._session_list_data = _sessions_with_projects()
        # "kepler" appears before "amplifier-core" in the text
        result = app._resolve_project_from_text("compare kepler and amplifier-core")
        assert result == "kepler"
