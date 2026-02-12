"""Tests for amplifier_tui.session_manager -- TUI-side session management.

The SessionManager integrates with amplifier-core via the distro Bridge,
so all tests mock at the bridge boundary.  No real sessions are created.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_tui.session_manager import SessionHandle, SessionManager

# The actual module where amplifier_projects_dir is looked up at runtime.
_CORE_MODULE = "amplifier_tui.core.session_manager"

# -- Helpers ------------------------------------------------------------------


def _make_provider(*, model: str = "claude-sonnet", context_window: int = 200000):
    """Create a minimal mock provider."""
    info = SimpleNamespace(defaults={"context_window": context_window})
    prov = SimpleNamespace(default_model=model, get_info=lambda: info)
    return prov


def _make_session(provider=None):
    """Create a minimal mock AmplifierSession."""
    prov = provider or _make_provider()
    coordinator = MagicMock()
    coordinator.get.side_effect = lambda key: (
        {"default": prov} if key == "providers" else None
    )
    session = MagicMock()
    session.coordinator = coordinator
    session.execute = AsyncMock(return_value="Hello from assistant")
    session.cleanup = AsyncMock()
    return session


def _setup_default_handle(sm, session=None):
    """Create a default handle on the SessionManager for backward-compat tests."""
    handle = SessionHandle(conversation_id="test-conv")
    if session:
        handle.session = session
    sm._handles["test-conv"] = handle
    sm._default_conversation_id = "test-conv"
    return handle


# -- Init & reset -------------------------------------------------------------


class TestSessionManagerInit:
    """SessionManager initialises with clean state."""

    def test_initial_state(self):
        sm = SessionManager()
        assert sm.session is None
        assert sm.session_id is None
        assert sm.total_input_tokens == 0
        assert sm.total_output_tokens == 0
        assert sm.model_name == ""
        assert sm.context_window == 0

    def test_reset_usage(self):
        sm = SessionManager()
        handle = _setup_default_handle(sm)
        handle.total_input_tokens = 500
        handle.total_output_tokens = 300
        handle.model_name = "gpt-4"
        handle.context_window = 128000
        sm.reset_usage()
        assert sm.total_input_tokens == 0
        assert sm.total_output_tokens == 0
        assert sm.model_name == ""
        assert sm.context_window == 0


# -- Model info extraction ----------------------------------------------------


class TestExtractModelInfo:
    """_extract_model_info_on_handle reads provider attributes."""

    def test_extracts_from_default_model(self):
        handle = SessionHandle(conversation_id="test")
        handle.session = _make_session()
        SessionManager._extract_model_info_on_handle(handle)
        assert handle.model_name == "claude-sonnet"
        assert handle.context_window == 200000

    def test_no_session_is_noop(self):
        handle = SessionHandle(conversation_id="test")
        SessionManager._extract_model_info_on_handle(handle)
        assert handle.model_name == ""

    def test_fallback_to_model_attr(self):
        """Provider with .model instead of .default_model."""
        prov = SimpleNamespace(model="gpt-4o")
        # No get_info method
        coord = MagicMock()
        coord.get.side_effect = lambda key: (
            {"default": prov} if key == "providers" else None
        )
        handle = SessionHandle(conversation_id="test")
        handle.session = MagicMock(coordinator=coord)
        SessionManager._extract_model_info_on_handle(handle)
        assert handle.model_name == "gpt-4o"

    def test_handles_exception_gracefully(self):
        """Broken provider doesn't crash."""
        coord = MagicMock()
        coord.get.side_effect = RuntimeError("boom")
        handle = SessionHandle(conversation_id="test")
        handle.session = MagicMock(coordinator=coord)
        SessionManager._extract_model_info_on_handle(handle)
        assert handle.model_name == ""


# -- switch_model -------------------------------------------------------------


class TestSwitchModel:
    """switch_model mutates the provider's model attribute."""

    def test_switch_success(self):
        sm = SessionManager()
        _setup_default_handle(sm, session=_make_session())
        assert sm.switch_model("claude-opus") is True
        assert sm.model_name == "claude-opus"

    def test_switch_no_session(self):
        sm = SessionManager()
        assert sm.switch_model("gpt-4") is False

    def test_switch_no_providers(self):
        coord = MagicMock()
        coord.get.return_value = {}
        sm = SessionManager()
        _setup_default_handle(sm, session=MagicMock(coordinator=coord))
        assert sm.switch_model("gpt-4") is False


# -- get_provider_models ------------------------------------------------------


class TestGetProviderModels:
    """get_provider_models returns (model, provider) pairs."""

    def test_returns_models(self):
        sm = SessionManager()
        _setup_default_handle(
            sm, session=_make_session(_make_provider(model="claude-sonnet"))
        )
        models = sm.get_provider_models()
        assert len(models) == 1
        assert models[0] == ("claude-sonnet", "default")

    def test_empty_when_no_session(self):
        sm = SessionManager()
        assert sm.get_provider_models() == []


# -- list_all_sessions --------------------------------------------------------


class TestListAllSessions:
    """list_all_sessions scans the projects directory."""

    def test_lists_sessions(self, tmp_path: Path):
        # Create a fake project structure
        project = tmp_path / "_home_user_project"
        session_dir = project / "sessions" / "abc-123-def"
        session_dir.mkdir(parents=True)
        (session_dir / "transcript.jsonl").write_text('{"role":"user"}\n')

        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            results = SessionManager.list_all_sessions()

        assert len(results) == 1
        assert results[0]["session_id"] == "abc-123-def"

    def test_skips_sub_sessions(self, tmp_path: Path):
        project = tmp_path / "_home_user_project"
        # Root session
        root = project / "sessions" / "abc-123"
        root.mkdir(parents=True)
        (root / "transcript.jsonl").write_text("{}\n")
        # Sub-session (has _ in name)
        sub = project / "sessions" / "abc-123_agent-name"
        sub.mkdir(parents=True)
        (sub / "transcript.jsonl").write_text("{}\n")

        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            results = SessionManager.list_all_sessions()

        assert len(results) == 1
        assert results[0]["session_id"] == "abc-123"

    def test_empty_when_no_projects(self, tmp_path: Path):
        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path / "nonexistent",
        ):
            assert SessionManager.list_all_sessions() == []

    def test_respects_limit(self, tmp_path: Path):
        project = tmp_path / "_home_user_project"
        for i in range(5):
            sd = project / "sessions" / f"session-{i:03d}"
            sd.mkdir(parents=True)
            (sd / "transcript.jsonl").write_text("{}\n")

        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            results = SessionManager.list_all_sessions(limit=2)
        assert len(results) == 2

    def test_reads_metadata(self, tmp_path: Path):
        project = tmp_path / "_home_user_project"
        sd = project / "sessions" / "abc-456"
        sd.mkdir(parents=True)
        (sd / "transcript.jsonl").write_text("{}\n")
        (sd / "metadata.json").write_text(
            json.dumps({"name": "My Session", "description": "Testing"})
        )

        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            results = SessionManager.list_all_sessions()

        assert results[0]["name"] == "My Session"
        assert results[0]["description"] == "Testing"


# -- get_session_transcript_path ----------------------------------------------


class TestGetSessionTranscriptPath:
    """get_session_transcript_path finds transcripts across projects."""

    def test_finds_transcript(self, tmp_path: Path):
        project = tmp_path / "_home_user_project"
        sd = project / "sessions" / "find-me-123"
        sd.mkdir(parents=True)
        transcript = sd / "transcript.jsonl"
        transcript.write_text("{}\n")

        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            result = SessionManager.get_session_transcript_path("find-me-123")

        assert result == transcript

    def test_returns_none_for_missing_session(self, tmp_path: Path):
        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            result = SessionManager.get_session_transcript_path("nonexistent")
            assert result is None

    def test_prefix_matching(self, tmp_path: Path):
        project = tmp_path / "_home_user_project"
        sd = project / "sessions" / "abcdef-1234-5678"
        sd.mkdir(parents=True)
        transcript = sd / "transcript.jsonl"
        transcript.write_text("{}\n")

        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            result = SessionManager.get_session_transcript_path("abcdef")

        assert result == transcript


# -- _find_most_recent_session ------------------------------------------------


class TestFindMostRecentSession:
    """_find_most_recent_session returns the newest session ID."""

    def test_returns_most_recent(self, tmp_path: Path):
        project = tmp_path / "_home_user_project"
        # Create two sessions; modify one more recently
        for sid in ("older-111", "newer-222"):
            sd = project / "sessions" / sid
            sd.mkdir(parents=True)
            (sd / "transcript.jsonl").write_text("{}\n")

        import time

        time.sleep(0.05)
        # Touch the newer one to make it most recent
        (project / "sessions" / "newer-222" / "transcript.jsonl").write_text("{}\n")

        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            sm = SessionManager()
            result = sm._find_most_recent_session()

        assert result == "newer-222"

    def test_raises_when_empty(self, tmp_path: Path):
        with patch(
            f"{_CORE_MODULE}.amplifier_projects_dir",
            return_value=tmp_path / "nonexistent",
        ):
            sm = SessionManager()
            with pytest.raises(ValueError, match="No sessions found"):
                sm._find_most_recent_session()


# -- _on_stream callback dispatch ---------------------------------------------


class TestOnStream:
    """SessionHandle._on_stream dispatches bridge events to TUI callbacks."""

    def test_content_block_start(self):
        handle = SessionHandle(conversation_id="test")
        calls = []
        handle.on_content_block_start = lambda bt, bi: calls.append(("start", bt, bi))
        handle._on_stream(
            "content_block:start", {"block_type": "text", "block_index": 0}
        )
        assert calls == [("start", "text", 0)]

    def test_content_block_delta(self):
        handle = SessionHandle(conversation_id="test")
        calls = []
        handle.on_content_block_delta = lambda bt, d: calls.append(("delta", bt, d))
        handle._on_stream(
            "content_block:delta", {"block_type": "text", "delta": "hello"}
        )
        assert calls == [("delta", "text", "hello")]

    def test_content_block_end_text(self):
        handle = SessionHandle(conversation_id="test")
        calls = []
        handle.on_content_block_end = lambda bt, t: calls.append(("end", bt, t))
        handle._on_stream(
            "content_block:end",
            {"block": {"type": "text", "text": "full text"}},
        )
        assert calls == [("end", "text", "full text")]

    def test_tool_pre(self):
        handle = SessionHandle(conversation_id="test")
        calls = []
        handle.on_tool_pre = lambda name, inp: calls.append(("pre", name, inp))
        handle._on_stream(
            "tool:pre", {"tool_name": "bash", "tool_input": {"cmd": "ls"}}
        )
        assert calls == [("pre", "bash", {"cmd": "ls"})]

    def test_tool_post(self):
        handle = SessionHandle(conversation_id="test")
        calls = []
        handle.on_tool_post = lambda name, inp, res: calls.append(("post", name, res))
        handle._on_stream(
            "tool:post",
            {"tool_name": "bash", "tool_input": {}, "result": "output"},
        )
        assert calls == [("post", "bash", "output")]

    def test_llm_response_tracks_usage(self):
        handle = SessionHandle(conversation_id="test")
        handle._on_stream(
            "llm:response",
            {"usage": {"input": 100, "output": 50}, "model": "claude-sonnet"},
        )
        assert handle.total_input_tokens == 100
        assert handle.total_output_tokens == 50
        assert handle.model_name == "claude-sonnet"

    def test_llm_response_accumulates(self):
        handle = SessionHandle(conversation_id="test")
        handle._on_stream("llm:response", {"usage": {"input": 100, "output": 50}})
        handle._on_stream("llm:response", {"usage": {"input": 200, "output": 100}})
        assert handle.total_input_tokens == 300
        assert handle.total_output_tokens == 150

    def test_unknown_event_ignored(self):
        handle = SessionHandle(conversation_id="test")
        handle._on_stream("unknown:event", {})  # Should not raise


# -- send_message & end_session -----------------------------------------------


class TestSendMessage:
    """send_message delegates to session.execute."""

    @pytest.mark.asyncio
    async def test_send_returns_response(self):
        sm = SessionManager()
        mock_session = _make_session()
        _setup_default_handle(sm, session=mock_session)
        result = await sm.send_message("Hello")
        assert result == "Hello from assistant"
        mock_session.execute.assert_awaited_once_with("Hello")

    @pytest.mark.asyncio
    async def test_send_no_session_raises(self):
        sm = SessionManager()
        with pytest.raises(ValueError):
            await sm.send_message("Hello")


class TestEndSession:
    """end_session cleans up via bridge or fallback."""

    @pytest.mark.asyncio
    async def test_end_via_bridge(self):
        sm = SessionManager()
        mock_session = _make_session()
        handle = _setup_default_handle(sm, session=mock_session)
        handle.session_id = "test-session"

        # Mock the bridge and bridge_handle
        mock_bridge = AsyncMock()
        sm._bridge = mock_bridge
        mock_bridge_handle = MagicMock()
        handle._bridge_handle = mock_bridge_handle

        await sm.end_session()

        mock_bridge.end_session.assert_awaited_once_with(mock_bridge_handle)
        assert sm.session is None
        assert sm._default_handle() is None

    @pytest.mark.asyncio
    async def test_end_fallback_without_handle(self):
        sm = SessionManager()
        mock_session = _make_session()
        handle = _setup_default_handle(sm, session=mock_session)
        handle.session_id = "test-session"
        handle._bridge_handle = None  # No bridge handle

        # Mock hooks for fallback path
        hooks = AsyncMock()
        mock_session.coordinator.get.side_effect = lambda key: (
            hooks if key == "hooks" else None
        )

        await sm.end_session()

        assert sm.session is None

    @pytest.mark.asyncio
    async def test_end_no_session_is_noop(self):
        sm = SessionManager()
        await sm.end_session()  # Should not raise
        assert sm.session is None
