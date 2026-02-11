"""Tests for the session scanner (monitor view data engine)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from amplifier_tui.features.session_scanner import (
    SessionScanner,
    SessionState,
    _detect_state,
    _extract_activity,
    _last_assistant_summary,
    _parse_last_events,
    _parse_timestamp,
    _project_label,
    _read_metadata,
    _tail_lines,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_events(session_dir: Path, events: list[dict]) -> Path:
    """Write a list of event dicts as events.jsonl."""
    path = session_dir / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return path


def _write_metadata(session_dir: Path, meta: dict) -> Path:
    """Write metadata.json for a session."""
    path = session_dir / "metadata.json"
    path.write_text(json.dumps(meta))
    return path


def _write_transcript(session_dir: Path, messages: list[dict]) -> Path:
    """Write transcript.jsonl for a session."""
    path = session_dir / "transcript.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for msg in messages:
            fh.write(json.dumps(msg) + "\n")
    return path


def _make_session(
    base: Path,
    project: str,
    session_id: str,
    events: list[dict] | None = None,
    meta: dict | None = None,
    transcript: list[dict] | None = None,
) -> Path:
    """Create a complete fake session directory on disk."""
    session_dir = base / project / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    if meta is None:
        meta = {
            "session_id": session_id,
            "created": "2026-01-05T10:00:00+00:00",
            "model": "claude-opus-4-6",
            "turn_count": 3,
            "working_dir": f"/home/user/dev/{project}",
        }
    _write_metadata(session_dir, meta)

    if events is None:
        events = [
            {"ts": "2026-01-05T10:00:00Z", "event": "session:start", "data": {}},
        ]
    _write_events(session_dir, events)

    if transcript is not None:
        _write_transcript(session_dir, transcript)

    return session_dir


# ===========================================================================
# _tail_lines
# ===========================================================================


class TestTailLines:
    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert _tail_lines(path) == []

    def test_small_file(self, tmp_path: Path) -> None:
        path = tmp_path / "small.jsonl"
        path.write_text("line1\nline2\nline3\n")
        lines = _tail_lines(path)
        assert lines == ["line1", "line2", "line3"]

    def test_large_file_tail(self, tmp_path: Path) -> None:
        """Only the tail portion is returned for large files."""
        path = tmp_path / "large.jsonl"
        # Write enough data to exceed the default tail bytes.
        big_line = "x" * 500 + "\n"
        with open(path, "w") as fh:
            for i in range(100):
                fh.write(f'{{"n": {i}, "pad": "{big_line}"}}\n')
        lines = _tail_lines(path, max_bytes=2048)
        # Should get some lines but not all 100.
        assert len(lines) > 0
        assert len(lines) < 100
        # Last line should be parseable JSON from the end of the file.
        last_valid = [line for line in lines if line.strip()]
        assert last_valid  # at least one non-empty line

    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nope.jsonl"
        assert _tail_lines(path) == []


# ===========================================================================
# _parse_last_events
# ===========================================================================


class TestParseLastEvents:
    def test_valid_lines(self) -> None:
        lines = [
            '{"event": "session:start"}',
            '{"event": "execution:start"}',
            '{"event": "tool:pre", "data": {"tool_name": "grep"}}',
        ]
        events = _parse_last_events(lines)
        assert len(events) == 3
        assert events[0]["event"] == "session:start"
        assert events[-1]["event"] == "tool:pre"

    def test_malformed_lines_skipped(self) -> None:
        lines = [
            '{"event": "ok"}',
            "not json at all",
            '{"event": "also_ok"}',
        ]
        events = _parse_last_events(lines)
        assert len(events) == 2
        assert events[0]["event"] == "ok"
        assert events[1]["event"] == "also_ok"

    def test_max_events_limit(self) -> None:
        lines = [f'{{"event": "e{i}"}}' for i in range(50)]
        events = _parse_last_events(lines, max_events=5)
        assert len(events) == 5
        # Should be the LAST 5 events (most recent).
        assert events[-1]["event"] == "e49"

    def test_empty_lines(self) -> None:
        assert _parse_last_events([]) == []
        assert _parse_last_events(["", "  ", "\n"]) == []


# ===========================================================================
# _detect_state
# ===========================================================================


class TestDetectState:
    def test_no_events_is_unknown(self) -> None:
        assert _detect_state([], stale=False) is SessionState.UNKNOWN

    def test_session_end_is_done(self) -> None:
        events = [{"event": "session:end"}]
        assert _detect_state(events, stale=False) is SessionState.DONE
        # Even if stale, session:end means DONE.
        assert _detect_state(events, stale=True) is SessionState.DONE

    def test_execution_end_is_idle(self) -> None:
        events = [{"event": "execution:end"}]
        assert _detect_state(events, stale=False) is SessionState.IDLE

    def test_execution_end_stale_is_stale(self) -> None:
        events = [{"event": "execution:end"}]
        assert _detect_state(events, stale=True) is SessionState.STALE

    def test_running_events(self) -> None:
        for event_name in (
            "execution:start",
            "tool:pre",
            "tool:post",
            "llm:request",
            "llm:response",
            "prompt:submit",
            "content_block:start",
        ):
            events = [{"event": event_name}]
            assert _detect_state(events, stale=False) is SessionState.RUNNING, (
                f"{event_name} should be RUNNING"
            )

    def test_running_events_stale(self) -> None:
        """Running events + stale flag -> STALE (process probably died)."""
        events = [{"event": "execution:start"}]
        assert _detect_state(events, stale=True) is SessionState.STALE


# ===========================================================================
# _extract_activity
# ===========================================================================


class TestExtractActivity:
    def test_empty_events(self) -> None:
        assert _extract_activity([], SessionState.UNKNOWN) == ""

    def test_tool_pre(self) -> None:
        events = [{"event": "tool:pre", "data": {"tool_name": "grep"}}]
        result = _extract_activity(events, SessionState.RUNNING)
        assert "grep" in result

    def test_tool_post(self) -> None:
        events = [{"event": "tool:post", "data": {"tool_name": "bash"}}]
        result = _extract_activity(events, SessionState.RUNNING)
        assert "bash" in result

    def test_llm_request_shows_thinking(self) -> None:
        events = [{"event": "llm:request", "data": {}}]
        result = _extract_activity(events, SessionState.RUNNING)
        assert "Thinking" in result

    def test_stale_shows_idle(self) -> None:
        events = [{"event": "execution:end", "data": {}}]
        result = _extract_activity(events, SessionState.STALE)
        assert "idle" in result.lower()

    def test_done_shows_assistant_summary(self) -> None:
        events = [
            {
                "event": "content_block:end",
                "data": {"block": {"type": "text", "text": "I fixed the bug."}},
            },
            {"event": "execution:end", "data": {}},
            {"event": "session:end", "data": {}},
        ]
        result = _extract_activity(events, SessionState.DONE)
        assert "fixed the bug" in result

    def test_idle_shows_last_response(self) -> None:
        events = [
            {
                "event": "content_block:end",
                "data": {"block": {"type": "text", "text": "Here are the results."}},
            },
            {"event": "execution:end", "data": {}},
        ]
        result = _extract_activity(events, SessionState.IDLE)
        assert "results" in result

    def test_prompt_submit(self) -> None:
        events = [
            {"event": "prompt:submit", "data": {"prompt": "Fix the auth module"}},
        ]
        result = _extract_activity(events, SessionState.RUNNING)
        assert "auth" in result


# ===========================================================================
# _last_assistant_summary
# ===========================================================================


class TestLastAssistantSummary:
    def test_finds_last_text_block(self) -> None:
        events = [
            {
                "event": "content_block:end",
                "data": {"block": {"type": "text", "text": "First response."}},
            },
            {
                "event": "content_block:end",
                "data": {"block": {"type": "text", "text": "Second response."}},
            },
        ]
        result = _last_assistant_summary(events)
        assert result == "Second response."

    def test_truncates_long_text(self) -> None:
        long_text = "a" * 200
        events = [
            {
                "event": "content_block:end",
                "data": {"block": {"type": "text", "text": long_text}},
            },
        ]
        result = _last_assistant_summary(events)
        assert len(result) <= 121  # 120 chars + ellipsis
        assert result.endswith("\u2026")

    def test_no_content_blocks(self) -> None:
        events = [{"event": "execution:end", "data": {}}]
        assert _last_assistant_summary(events) == ""

    def test_skips_empty_text(self) -> None:
        events = [
            {
                "event": "content_block:end",
                "data": {"block": {"type": "text", "text": ""}},
            },
        ]
        assert _last_assistant_summary(events) == ""

    def test_newlines_flattened(self) -> None:
        events = [
            {
                "event": "content_block:end",
                "data": {"block": {"type": "text", "text": "Line one.\nLine two."}},
            },
        ]
        result = _last_assistant_summary(events)
        assert "\n" not in result
        assert "Line one. Line two." == result


# ===========================================================================
# _read_metadata
# ===========================================================================


class TestReadMetadata:
    def test_reads_metadata_json(self, tmp_path: Path) -> None:
        meta = {"session_id": "abc", "model": "opus"}
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        result = _read_metadata(tmp_path)
        assert result["session_id"] == "abc"

    def test_falls_back_to_session_info(self, tmp_path: Path) -> None:
        meta = {"session_id": "xyz"}
        (tmp_path / "session-info.json").write_text(json.dumps(meta))
        result = _read_metadata(tmp_path)
        assert result["session_id"] == "xyz"

    def test_no_metadata(self, tmp_path: Path) -> None:
        assert _read_metadata(tmp_path) == {}

    def test_malformed_json(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text("not json{{{")
        assert _read_metadata(tmp_path) == {}


# ===========================================================================
# _parse_timestamp
# ===========================================================================


class TestParseTimestamp:
    def test_iso_with_z(self) -> None:
        dt = _parse_timestamp("2026-01-05T10:00:00Z")
        assert dt is not None
        assert dt.hour == 10

    def test_iso_with_offset(self) -> None:
        dt = _parse_timestamp("2026-01-05T10:00:00+00:00")
        assert dt is not None

    def test_empty_string(self) -> None:
        assert _parse_timestamp("") is None

    def test_bad_format(self) -> None:
        assert _parse_timestamp("not-a-date") is None


# ===========================================================================
# _project_label
# ===========================================================================


class TestProjectLabel:
    def test_from_working_dir(self) -> None:
        meta = {"working_dir": "/home/sam/dev/my-project"}
        label, path = _project_label(meta, "-home-sam-dev-my-project")
        assert label == "my-project"
        assert path == "/home/sam/dev/my-project"

    def test_from_dir_name_fallback(self) -> None:
        label, path = _project_label({}, "-home-sam-dev-cool-thing")
        assert label == "thing"  # last segment after decoding
        assert "/" in path  # decoded to path-like string


# ===========================================================================
# SessionScanner.scan
# ===========================================================================


class TestSessionScannerScan:
    def test_empty_dir(self, tmp_path: Path) -> None:
        scanner = SessionScanner(session_dir=tmp_path)
        assert scanner.scan() == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        scanner = SessionScanner(session_dir=tmp_path / "nope")
        assert scanner.scan() == []

    def test_finds_sessions(self, tmp_path: Path) -> None:
        _make_session(tmp_path, "proj-a", "aaaa-1111")
        _make_session(tmp_path, "proj-b", "bbbb-2222")

        scanner = SessionScanner(session_dir=tmp_path)
        sessions = scanner.scan()
        assert len(sessions) == 2

    def test_respects_limit(self, tmp_path: Path) -> None:
        for i in range(5):
            sdir = _make_session(tmp_path, "proj", f"sess-{i:04d}")
            # Stagger mtimes so ordering is deterministic.
            import os

            os.utime(sdir, (1000000 + i, 1000000 + i))

        scanner = SessionScanner(session_dir=tmp_path)
        sessions = scanner.scan(limit=3)
        assert len(sessions) == 3

    def test_skips_sub_sessions(self, tmp_path: Path) -> None:
        """Sub-sessions (with _ in name) should be excluded."""
        _make_session(tmp_path, "proj", "aaaa-1111")
        # Create a sub-session directory.
        sub_dir = tmp_path / "proj" / "sessions" / "aaaa-1111_foundation:explorer"
        sub_dir.mkdir(parents=True)
        _write_events(sub_dir, [{"event": "session:start"}])
        _write_metadata(sub_dir, {"session_id": "aaaa-1111_foundation:explorer"})

        scanner = SessionScanner(session_dir=tmp_path)
        sessions = scanner.scan()
        assert len(sessions) == 1
        assert sessions[0].session_id == "aaaa-1111"

    def test_sorted_by_recency(self, tmp_path: Path) -> None:
        """Most recently modified sessions come first."""
        import os

        s1 = _make_session(tmp_path, "proj", "old-session")
        os.utime(s1, (1000000, 1000000))  # old

        s2 = _make_session(tmp_path, "proj", "new-session")
        os.utime(s2, (9000000, 9000000))  # recent

        scanner = SessionScanner(session_dir=tmp_path)
        sessions = scanner.scan()
        assert sessions[0].session_id == "new-session"
        assert sessions[1].session_id == "old-session"

    def test_detects_running_state(self, tmp_path: Path) -> None:
        _make_session(
            tmp_path,
            "proj",
            "running-sess",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:start", "data": {}},
                {"event": "tool:pre", "data": {"tool_name": "bash"}},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        sessions = scanner.scan()
        assert len(sessions) == 1
        assert sessions[0].state is SessionState.RUNNING
        assert "bash" in sessions[0].activity

    def test_detects_idle_state(self, tmp_path: Path) -> None:
        _make_session(
            tmp_path,
            "proj",
            "idle-sess",
            events=[
                {"event": "session:start", "data": {}},
                {
                    "event": "content_block:end",
                    "data": {"block": {"type": "text", "text": "All done here."}},
                },
                {"event": "execution:end", "data": {}},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        sessions = scanner.scan()
        assert sessions[0].state is SessionState.IDLE
        assert "done here" in sessions[0].activity

    def test_detects_done_state(self, tmp_path: Path) -> None:
        _make_session(
            tmp_path,
            "proj",
            "done-sess",
            events=[
                {"event": "session:start", "data": {}},
                {
                    "event": "content_block:end",
                    "data": {
                        "block": {"type": "text", "text": "Committed the changes."}
                    },
                },
                {"event": "execution:end", "data": {}},
                {"event": "session:end", "data": {}},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path)
        sessions = scanner.scan()
        assert sessions[0].state is SessionState.DONE
        assert "Committed" in sessions[0].activity

    def test_stale_detection(self, tmp_path: Path) -> None:
        """Old sessions with no session:end are STALE."""
        import os

        sdir = _make_session(
            tmp_path,
            "proj",
            "stale-sess",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
            ],
        )
        # Set mtime to 2 hours ago.
        old_time = time.time() - 7200
        os.utime(sdir, (old_time, old_time))

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=3600)
        sessions = scanner.scan()
        assert sessions[0].state is SessionState.STALE

    def test_metadata_fields_populated(self, tmp_path: Path) -> None:
        _make_session(
            tmp_path,
            "proj",
            "meta-sess",
            meta={
                "session_id": "meta-sess",
                "created": "2026-01-05T10:00:00Z",
                "model": "claude-sonnet-4-20250514",
                "turn_count": 7,
                "working_dir": "/home/user/dev/my-project",
            },
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        sessions = scanner.scan()
        s = sessions[0]
        assert s.session_id == "meta-sess"
        assert s.short_id == "meta-ses"
        assert s.project == "my-project"
        assert s.model == "claude-sonnet-4-20250514"
        assert s.turn_count == 7
        assert s.started_at is not None

    def test_sessions_without_events_still_found(self, tmp_path: Path) -> None:
        """Sessions with only transcript.jsonl (no events) should appear."""
        session_dir = tmp_path / "proj" / "sessions" / "no-events"
        session_dir.mkdir(parents=True)
        _write_metadata(session_dir, {"session_id": "no-events", "model": "test"})
        _write_transcript(session_dir, [{"role": "user", "content": "hello"}])

        scanner = SessionScanner(session_dir=tmp_path)
        sessions = scanner.scan()
        assert len(sessions) == 1
        assert sessions[0].state is SessionState.UNKNOWN


# ===========================================================================
# Formatting helpers
# ===========================================================================


class TestFormatAge:
    def test_seconds(self) -> None:
        assert SessionScanner.format_age(45) == "45s"

    def test_minutes(self) -> None:
        assert SessionScanner.format_age(300) == "5m"

    def test_hours(self) -> None:
        result = SessionScanner.format_age(7200)
        assert "h" in result

    def test_days(self) -> None:
        result = SessionScanner.format_age(172800)
        assert "d" in result


class TestStateIcon:
    def test_all_states_have_icons(self) -> None:
        for state in SessionState:
            icon = SessionScanner.state_icon(state)
            assert isinstance(icon, str)
            assert len(icon) == 1


class TestStateColor:
    def test_all_states_have_colors(self) -> None:
        for state in SessionState:
            color = SessionScanner.state_color(state)
            assert isinstance(color, str)
            assert len(color) > 0
