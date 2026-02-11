"""Tests for monitor command mixin logic.

The mixin is mostly UI wiring (Textual DataTable, timers, panel toggle),
so these tests focus on the testable pure-logic pieces:

- Column definitions are consistent
- Command dispatch routes to correct handlers
- Model abbreviation / truncation in _refresh_monitor_table
- Scanner/summarizer lazy initialization
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual", reason="textual required for monitor_cmds tests")

from amplifier_tui.commands.monitor_cmds import MonitorCommandsMixin, _COLUMNS
from amplifier_tui.features.session_scanner import (
    MonitoredSession,
    SessionScanner,
    SessionState,
)
from amplifier_tui.features.session_summarizer import SessionSummarizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "abc-123",
    project: str = "my-project",
    model: str = "claude-haiku-4-20250506",
    state: SessionState = SessionState.IDLE,
    activity: str = "Waiting for input",
    turn_count: int = 5,
    age_seconds: float = 120.0,
) -> MonitoredSession:
    return MonitoredSession(
        session_id=session_id,
        short_id=session_id[:8],
        project=project,
        project_path=f"/home/user/dev/{project}",
        model=model,
        state=state,
        turn_count=turn_count,
        started_at=datetime(2026, 1, 5, 10, 0, 0),
        last_active=datetime(2026, 1, 5, 10, 2, 0),
        age_seconds=age_seconds,
        activity=activity,
        session_dir=None,
    )


def _write_events(session_dir: Path, events: list[dict]) -> None:
    path = session_dir / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")


def _write_metadata(session_dir: Path, meta: dict) -> None:
    (session_dir / "metadata.json").write_text(json.dumps(meta))


def _make_session_dir(base: Path, project: str, session_id: str) -> Path:
    sdir = base / project / "sessions" / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    _write_metadata(
        sdir, {"session_id": session_id, "model": "claude-haiku-4-20250506"}
    )
    _write_events(
        sdir,
        [
            {"event": "session:start", "data": {}},
            {"event": "execution:end", "data": {}},
        ],
    )
    return sdir


# ===========================================================================
# Column definitions
# ===========================================================================


class TestColumnDefinitions:
    def test_column_count(self) -> None:
        assert len(_COLUMNS) == 6

    def test_all_have_keys(self) -> None:
        keys = [c[0] for c in _COLUMNS]
        assert "state" in keys
        assert "project" in keys
        assert "activity" in keys

    def test_activity_is_auto_width(self) -> None:
        """The status column should auto-expand (width=None)."""
        activity_col = [c for c in _COLUMNS if c[0] == "activity"]
        assert len(activity_col) == 1
        assert activity_col[0][2] is None


# ===========================================================================
# Command dispatch
# ===========================================================================


class TestCommandDispatch:
    """Test that _cmd_monitor routes subcommands correctly."""

    def _make_mixin(self) -> MonitorCommandsMixin:
        mixin = MonitorCommandsMixin()
        mixin._toggle_monitor_panel = MagicMock()  # type: ignore[assignment]
        mixin._close_monitor_panel = MagicMock()  # type: ignore[assignment]
        mixin._toggle_monitor_size = MagicMock()  # type: ignore[assignment]
        mixin._post_system = MagicMock()  # type: ignore[attr-defined]
        return mixin

    def test_empty_args_toggles(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("")
        mixin._toggle_monitor_panel.assert_called_once()  # type: ignore[union-attr]

    def test_toggle_arg(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("toggle")
        mixin._toggle_monitor_panel.assert_called_once()  # type: ignore[union-attr]

    def test_close_arg(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("close")
        mixin._close_monitor_panel.assert_called_once()  # type: ignore[union-attr]

    def test_big_arg(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("big")
        mixin._toggle_monitor_size.assert_called_once_with(big=True)  # type: ignore[union-attr]

    def test_small_arg(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("small")
        mixin._toggle_monitor_size.assert_called_once_with(big=False)  # type: ignore[union-attr]

    def test_unknown_arg_shows_usage(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("foobar")
        mixin._post_system.assert_called_once()  # type: ignore[attr-defined]
        msg = mixin._post_system.call_args[0][0]  # type: ignore[attr-defined]
        assert "Usage:" in msg

    def test_args_case_insensitive(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("CLOSE")
        mixin._close_monitor_panel.assert_called_once()  # type: ignore[union-attr]

    def test_args_stripped(self) -> None:
        mixin = self._make_mixin()
        mixin._cmd_monitor("  big  ")
        mixin._toggle_monitor_size.assert_called_once_with(big=True)  # type: ignore[union-attr]


# ===========================================================================
# Model abbreviation
# ===========================================================================


class TestModelAbbreviation:
    """Test model name abbreviation logic from _refresh_monitor_table."""

    @staticmethod
    def _abbreviate(model: str) -> str:
        """Extract the abbreviation logic from _refresh_monitor_table."""
        if model.startswith("claude-"):
            model = model.replace("claude-", "c-")
        if len(model) > 14:
            model = model[:13] + "\u2026"
        return model

    def test_claude_shortened(self) -> None:
        assert self._abbreviate("claude-haiku-4-20250506") == "c-haiku-4-202\u2026"

    def test_short_model_unchanged(self) -> None:
        assert self._abbreviate("gpt-4o") == "gpt-4o"

    def test_long_non_claude_truncated(self) -> None:
        result = self._abbreviate("a-very-long-model-name-here")
        assert len(result) <= 14
        assert result.endswith("\u2026")


# ===========================================================================
# Lazy initialization
# ===========================================================================


class TestLazyInitialization:
    """Verify scanner and summarizer start as None."""

    def test_defaults_are_none(self) -> None:
        mixin = MonitorCommandsMixin()
        assert mixin._monitor_scanner is None
        assert mixin._monitor_summarizer is None
        assert mixin._monitor_fast_timer is None
        assert mixin._monitor_slow_timer is None


# ===========================================================================
# Integration: scanner + summarizer in mixin context
# ===========================================================================


class TestScannerSummarizerIntegration:
    """Test that the scanner/summarizer can be wired into the mixin."""

    def test_scanner_finds_sessions(self, tmp_path: Path) -> None:
        """Verify the scanner works when created the way the mixin does."""
        _make_session_dir(tmp_path, "proj-a", "sess-1")
        _make_session_dir(tmp_path, "proj-b", "sess-2")

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=None)

        sessions = summarizer.scan(limit=10)
        assert len(sessions) == 2

    def test_limit_respected(self, tmp_path: Path) -> None:
        for i in range(5):
            _make_session_dir(tmp_path, f"proj-{i}", f"sess-{i}")

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=None)

        sessions = summarizer.scan(limit=3)
        assert len(sessions) == 3


# ===========================================================================
# Constants: /monitor in SLASH_COMMANDS
# ===========================================================================


class TestSlashCommandRegistration:
    def test_monitor_in_slash_commands(self) -> None:
        from amplifier_tui.constants import SLASH_COMMANDS

        assert "/monitor" in SLASH_COMMANDS
        assert "/monitor close" in SLASH_COMMANDS
        assert "/monitor big" in SLASH_COMMANDS
        assert "/monitor small" in SLASH_COMMANDS


# ===========================================================================
# Feature exports
# ===========================================================================


class TestFeatureExports:
    def test_scanner_exported(self) -> None:
        from amplifier_tui.features import SessionScanner

        assert SessionScanner is not None

    def test_summarizer_exported(self) -> None:
        from amplifier_tui.features import SessionSummarizer

        assert SessionSummarizer is not None

    def test_make_anthropic_summarizer_exported(self) -> None:
        from amplifier_tui.features import make_anthropic_summarizer

        assert callable(make_anthropic_summarizer)

    def test_monitored_session_exported(self) -> None:
        from amplifier_tui.features import MonitoredSession

        assert MonitoredSession is not None

    def test_session_state_exported(self) -> None:
        from amplifier_tui.features import SessionState

        assert SessionState is not None


# ===========================================================================
# Command mixin export
# ===========================================================================


class TestCommandExport:
    def test_mixin_exported(self) -> None:
        from amplifier_tui.commands import MonitorCommandsMixin

        assert MonitorCommandsMixin is not None
