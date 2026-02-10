"""Tests for amplifier_tui.session_manager -- TUI-012.

The SessionManager integrates with amplifier-core, so all tests mock
at the amplifier boundary.  No real sessions are created.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_tui.session_manager import SessionManager


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
        sm.total_input_tokens = 500
        sm.total_output_tokens = 200
        sm.model_name = "gpt-4"
        sm.context_window = 128000
        sm.reset_usage()
        assert sm.total_input_tokens == 0
        assert sm.total_output_tokens == 0
        assert sm.model_name == ""
        assert sm.context_window == 0


# -- Model info extraction ----------------------------------------------------


class TestExtractModelInfo:
    """_extract_model_info reads provider attributes."""

    def test_extracts_from_default_model(self):
        sm = SessionManager()
        sm.session = _make_session()
        sm._extract_model_info()
        assert sm.model_name == "claude-sonnet"
        assert sm.context_window == 200000

    def test_no_session_is_noop(self):
        sm = SessionManager()
        sm._extract_model_info()
        assert sm.model_name == ""

    def test_fallback_to_model_attr(self):
        """Provider with .model instead of .default_model."""
        prov = SimpleNamespace(model="gpt-4o")
        # No get_info method
        coord = MagicMock()
        coord.get.side_effect = lambda key: (
            {"default": prov} if key == "providers" else None
        )
        sm = SessionManager()
        sm.session = MagicMock(coordinator=coord)
        sm._extract_model_info()
        assert sm.model_name == "gpt-4o"

    def test_handles_exception_gracefully(self):
        """Broken provider doesn't crash."""
        coord = MagicMock()
        coord.get.side_effect = RuntimeError("boom")
        sm = SessionManager()
        sm.session = MagicMock(coordinator=coord)
        sm._extract_model_info()
        assert sm.model_name == ""


# -- switch_model -------------------------------------------------------------


class TestSwitchModel:
    """switch_model mutates the provider's model attribute."""

    def test_switch_success(self):
        sm = SessionManager()
        sm.session = _make_session()
        assert sm.switch_model("claude-opus") is True
        assert sm.model_name == "claude-opus"

    def test_switch_no_session(self):
        sm = SessionManager()
        assert sm.switch_model("gpt-4") is False

    def test_switch_no_providers(self):
        coord = MagicMock()
        coord.get.return_value = {}
        sm = SessionManager()
        sm.session = MagicMock(coordinator=coord)
        assert sm.switch_model("gpt-4") is False


# -- get_provider_models ------------------------------------------------------


class TestGetProviderModels:
    """get_provider_models returns (model, provider) pairs."""

    def test_returns_models(self):
        sm = SessionManager()
        sm.session = _make_session(_make_provider(model="claude-sonnet"))
        models = sm.get_provider_models()
        assert len(models) == 1
        assert models[0] == ("claude-sonnet", "default")

    def test_empty_when_no_session(self):
        sm = SessionManager()
        assert sm.get_provider_models() == []


# -- _apply_model_override (static) ------------------------------------------


class TestApplyModelOverride:
    """Static method patches config_data providers."""

    def test_patches_default_model(self):
        config = {
            "providers": [
                {"config": {"default_model": "old-model"}},
            ]
        }
        SessionManager._apply_model_override(config, "new-model")
        assert config["providers"][0]["config"]["default_model"] == "new-model"
        assert config["providers"][0]["config"]["priority"] == 0

    def test_fallback_patches_first_config(self):
        config = {
            "providers": [
                {"config": {"some_key": "val"}},
            ]
        }
        SessionManager._apply_model_override(config, "new-model")
        assert config["providers"][0]["config"]["default_model"] == "new-model"

    def test_no_providers_is_noop(self):
        config: dict = {"providers": []}
        SessionManager._apply_model_override(config, "new-model")
        assert config == {"providers": []}


# -- _load_transcript ---------------------------------------------------------


class TestLoadTranscript:
    """_load_transcript reads JSONL lines."""

    def test_loads_messages(self, tmp_path: Path):
        transcript = tmp_path / "transcript.jsonl"
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        transcript.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")
        sm = SessionManager()
        result = sm._load_transcript(transcript)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["content"] == "hi"

    def test_skips_blank_lines(self, tmp_path: Path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"role":"user","content":"a"}\n\n\n')
        sm = SessionManager()
        result = sm._load_transcript(transcript)
        assert len(result) == 1


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
            "amplifier_tui.session_manager.amplifier_projects_dir",
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
            "amplifier_tui.session_manager.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            results = SessionManager.list_all_sessions()

        assert len(results) == 1
        assert results[0]["session_id"] == "abc-123"

    def test_empty_when_no_projects(self, tmp_path: Path):
        with patch(
            "amplifier_tui.session_manager.amplifier_projects_dir",
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
            "amplifier_tui.session_manager.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            results = SessionManager.list_all_sessions(limit=3)

        assert len(results) == 3

    def test_reads_metadata(self, tmp_path: Path):
        project = tmp_path / "_home_user_project"
        sd = project / "sessions" / "abc-456"
        sd.mkdir(parents=True)
        (sd / "transcript.jsonl").write_text("{}\n")
        (sd / "metadata.json").write_text(
            json.dumps({"name": "My Session", "description": "Testing"})
        )

        with patch(
            "amplifier_tui.session_manager.amplifier_projects_dir",
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
            "amplifier_tui.session_manager.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            sm = SessionManager()
            result = sm.get_session_transcript_path("find-me-123")

        assert result == transcript

    def test_raises_for_missing_session(self, tmp_path: Path):
        with patch(
            "amplifier_tui.session_manager.amplifier_projects_dir",
            return_value=tmp_path,
        ):
            sm = SessionManager()
            with pytest.raises(ValueError, match="not found"):
                sm.get_session_transcript_path("nonexistent")


# -- send_message & end_session -----------------------------------------------


class TestSendMessage:
    """send_message delegates to session.execute."""

    @pytest.mark.asyncio
    async def test_send_returns_response(self):
        sm = SessionManager()
        mock_session = _make_session()
        sm.session = mock_session
        result = await sm.send_message("Hello")
        assert result == "Hello from assistant"
        mock_session.execute.assert_awaited_once_with("Hello")

    @pytest.mark.asyncio
    async def test_send_no_session_raises(self):
        sm = SessionManager()
        with pytest.raises(ValueError, match="No active session"):
            await sm.send_message("Hello")


class TestEndSession:
    """end_session emits SESSION_END and cleans up."""

    @pytest.mark.asyncio
    async def test_end_cleans_up(self):
        sm = SessionManager()
        mock_session = _make_session()
        sm.session = mock_session
        sm.session_id = "test-session"

        # Mock hooks
        hooks = AsyncMock()
        mock_session.coordinator.get.side_effect = lambda key: (
            hooks if key == "hooks" else None
        )

        with patch("amplifier_tui.session_manager.SessionManager._register_hooks"):
            await sm.end_session()

        assert sm.session is None

    @pytest.mark.asyncio
    async def test_end_no_session_is_noop(self):
        sm = SessionManager()
        await sm.end_session()  # Should not raise
        assert sm.session is None
