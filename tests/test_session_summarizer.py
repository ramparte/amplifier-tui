"""Tests for the LLM-powered session summarizer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from amplifier_tui.features.session_scanner import (
    MonitoredSession,
    SessionScanner,
    SessionState,
)
from amplifier_tui.features.session_summarizer import (
    SessionSummarizer,
    TranscriptExcerpt,
    _extract_assistant_text,
    build_summary_prompt,
    read_transcript_excerpt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_transcript(session_dir: Path, messages: list[dict]) -> Path:
    """Write transcript.jsonl."""
    path = session_dir / "transcript.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for msg in messages:
            fh.write(json.dumps(msg) + "\n")
    return path


def _write_events(session_dir: Path, events: list[dict]) -> Path:
    """Write events.jsonl."""
    path = session_dir / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return path


def _write_metadata(session_dir: Path, meta: dict) -> Path:
    """Write metadata.json."""
    path = session_dir / "metadata.json"
    path.write_text(json.dumps(meta))
    return path


def _make_session_dir(
    base: Path,
    project: str,
    session_id: str,
    transcript: list[dict] | None = None,
    events: list[dict] | None = None,
) -> Path:
    """Create a minimal session directory with transcript and events."""
    session_dir = base / project / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    _write_metadata(
        session_dir,
        {
            "session_id": session_id,
            "model": "claude-haiku-4-20250506",
            "working_dir": f"/home/user/dev/{project}",
        },
    )
    if events is None:
        events = [
            {"event": "session:start", "data": {}},
            {"event": "execution:end", "data": {}},
        ]
    _write_events(session_dir, events)
    if transcript is not None:
        _write_transcript(session_dir, transcript)
    return session_dir


def _make_monitored_session(
    session_id: str = "test-sess",
    state: SessionState = SessionState.IDLE,
    activity: str = "raw scanner text",
    session_dir: Path | None = None,
    mtime: float = 1000000.0,
) -> MonitoredSession:
    """Build a MonitoredSession for unit tests."""
    return MonitoredSession(
        session_id=session_id,
        short_id=session_id[:8],
        project="test-proj",
        project_path="/home/user/dev/test-proj",
        model="claude-haiku-4-20250506",
        state=state,
        turn_count=3,
        started_at=datetime(2026, 1, 5, 10, 0, 0),
        last_active=datetime.fromtimestamp(mtime),
        age_seconds=300.0,
        activity=activity,
        session_dir=session_dir,
    )


def _fake_summarize(prompt: str) -> str:
    """Fake LLM that returns a fixed status line."""
    return "Committed fix, tests passing"


def _echo_summarize(prompt: str) -> str:
    """Fake LLM that echoes back a marker so we can detect it was called."""
    return "LLM_SUMMARY_GENERATED"


def _failing_summarize(prompt: str) -> str:
    """Fake LLM that always raises."""
    raise RuntimeError("API down")


# ===========================================================================
# Transcript reading
# ===========================================================================


class TestExtractAssistantText:
    def test_string_content(self) -> None:
        msg = {"role": "assistant", "content": "Hello there."}
        assert _extract_assistant_text(msg) == "Hello there."

    def test_list_content_text_blocks(self) -> None:
        msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "First part."},
                {"type": "thinking", "thinking": "Internal thoughts..."},
                {"type": "text", "text": "Second part."},
            ],
        }
        result = _extract_assistant_text(msg)
        assert "First part." in result
        assert "Second part." in result
        assert "Internal thoughts" not in result

    def test_list_content_no_text(self) -> None:
        msg = {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Just thinking..."},
                {"type": "tool_use", "id": "t1", "name": "bash", "input": {}},
            ],
        }
        assert _extract_assistant_text(msg) == ""

    def test_empty_content(self) -> None:
        assert _extract_assistant_text({"content": ""}) == ""
        assert _extract_assistant_text({"content": []}) == ""
        assert _extract_assistant_text({}) == ""

    def test_non_dict_blocks_skipped(self) -> None:
        msg = {"content": ["not a dict", {"type": "text", "text": "ok"}]}
        assert _extract_assistant_text(msg) == "ok"


class TestReadTranscriptExcerpt:
    def test_reads_last_exchange(self, tmp_path: Path) -> None:
        sdir = tmp_path / "sess"
        sdir.mkdir()
        _write_transcript(
            sdir,
            [
                {"role": "user", "content": "Fix the auth bug"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I found and fixed the bug."},
                    ],
                },
                {"role": "user", "content": "Now add tests"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Tests added and passing."},
                    ],
                },
            ],
        )

        excerpt = read_transcript_excerpt(sdir)
        assert excerpt is not None
        assert excerpt.user_message == "Now add tests"
        assert excerpt.assistant_text == "Tests added and passing."

    def test_skips_tool_messages(self, tmp_path: Path) -> None:
        sdir = tmp_path / "sess"
        sdir.mkdir()
        _write_transcript(
            sdir,
            [
                {"role": "user", "content": "Run the build"},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Running build now."}],
                },
                {
                    "role": "tool",
                    "name": "bash",
                    "content": '{"stdout": "Build succeeded"}',
                },
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Build passed."}],
                },
            ],
        )

        excerpt = read_transcript_excerpt(sdir)
        assert excerpt is not None
        assert excerpt.user_message == "Run the build"
        assert excerpt.assistant_text == "Build passed."

    def test_missing_transcript(self, tmp_path: Path) -> None:
        sdir = tmp_path / "sess"
        sdir.mkdir()
        assert read_transcript_excerpt(sdir) is None

    def test_empty_transcript(self, tmp_path: Path) -> None:
        sdir = tmp_path / "sess"
        sdir.mkdir()
        (sdir / "transcript.jsonl").write_text("")
        assert read_transcript_excerpt(sdir) is None

    def test_only_user_message(self, tmp_path: Path) -> None:
        sdir = tmp_path / "sess"
        sdir.mkdir()
        _write_transcript(sdir, [{"role": "user", "content": "Hello"}])

        excerpt = read_transcript_excerpt(sdir)
        assert excerpt is not None
        assert excerpt.user_message == "Hello"
        assert excerpt.assistant_text == ""

    def test_truncates_long_content(self, tmp_path: Path) -> None:
        sdir = tmp_path / "sess"
        sdir.mkdir()
        _write_transcript(
            sdir,
            [
                {"role": "user", "content": "x" * 5000},
                {"role": "assistant", "content": "y" * 5000},
            ],
        )

        excerpt = read_transcript_excerpt(sdir)
        assert excerpt is not None
        assert len(excerpt.user_message) <= 2000
        assert len(excerpt.assistant_text) <= 2000


# ===========================================================================
# Prompt construction
# ===========================================================================


class TestBuildSummaryPrompt:
    def test_contains_user_and_assistant(self) -> None:
        excerpt = TranscriptExcerpt(
            user_message="Fix the bug",
            assistant_text="I found and fixed the null pointer.",
        )
        prompt = build_summary_prompt(excerpt, SessionState.DONE)
        assert "Fix the bug" in prompt
        assert "null pointer" in prompt
        assert "Session ended" in prompt

    def test_idle_state_label(self) -> None:
        excerpt = TranscriptExcerpt(user_message="x", assistant_text="y")
        prompt = build_summary_prompt(excerpt, SessionState.IDLE)
        assert "Waiting for user input" in prompt

    def test_empty_user_message(self) -> None:
        excerpt = TranscriptExcerpt(user_message="", assistant_text="Done.")
        prompt = build_summary_prompt(excerpt, SessionState.DONE)
        assert "Last user request" not in prompt
        assert "Done." in prompt

    def test_empty_assistant_text(self) -> None:
        excerpt = TranscriptExcerpt(user_message="Do stuff", assistant_text="")
        prompt = build_summary_prompt(excerpt, SessionState.IDLE)
        assert "Last assistant response" not in prompt
        assert "Do stuff" in prompt

    def test_includes_system_prompt(self) -> None:
        excerpt = TranscriptExcerpt(user_message="x", assistant_text="y")
        prompt = build_summary_prompt(excerpt, SessionState.DONE)
        assert "max 8 words" in prompt
        assert "Status line:" in prompt


# ===========================================================================
# SessionSummarizer.scan
# ===========================================================================


class TestSessionSummarizerScan:
    def test_passthrough_without_llm(self, tmp_path: Path) -> None:
        """With no summarize_fn, scan returns raw scanner output."""
        _make_session_dir(tmp_path, "proj", "sess-1")

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=None)

        sessions = summarizer.scan()
        assert len(sessions) == 1
        assert not summarizer.has_pending

    def test_queues_idle_session(self, tmp_path: Path) -> None:
        """IDLE sessions get queued for summarization."""
        _make_session_dir(
            tmp_path,
            "proj",
            "idle-1",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_echo_summarize)

        sessions = summarizer.scan()
        assert len(sessions) == 1
        # First scan returns raw text, queues for summarization.
        assert sessions[0].activity != "LLM_SUMMARY_GENERATED"
        assert summarizer.has_pending
        assert summarizer.pending_count == 1

    def test_queues_done_session(self, tmp_path: Path) -> None:
        """DONE sessions get queued for summarization."""
        _make_session_dir(
            tmp_path,
            "proj",
            "done-1",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
                {"event": "session:end", "data": {}},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_echo_summarize)

        summarizer.scan()
        assert summarizer.has_pending

    def test_does_not_queue_running_session(self, tmp_path: Path) -> None:
        """RUNNING sessions keep their real-time activity text."""
        _make_session_dir(
            tmp_path,
            "proj",
            "running-1",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "tool:pre", "data": {"tool_name": "grep"}},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_echo_summarize)

        sessions = summarizer.scan()
        assert not summarizer.has_pending
        assert "grep" in sessions[0].activity

    def test_does_not_double_queue(self, tmp_path: Path) -> None:
        """Same session should not be queued twice."""
        _make_session_dir(
            tmp_path,
            "proj",
            "idle-1",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_echo_summarize)

        summarizer.scan()
        summarizer.scan()  # second scan
        assert summarizer.pending_count == 1

    def test_cache_hit_replaces_activity(self, tmp_path: Path) -> None:
        """After processing, cached summary replaces raw activity."""
        _make_session_dir(
            tmp_path,
            "proj",
            "idle-1",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
            ],
            transcript=[
                {"role": "user", "content": "Fix the auth module"},
                {"role": "assistant", "content": "Fixed it."},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_fake_summarize)

        # First scan: queues.
        summarizer.scan()
        assert summarizer.has_pending

        # Process pending.
        processed = summarizer.process_pending()
        assert processed == 1
        assert not summarizer.has_pending

        # Second scan: cache hit.
        sessions2 = summarizer.scan()
        assert sessions2[0].activity == "Committed fix, tests passing"


# ===========================================================================
# SessionSummarizer.process_pending
# ===========================================================================


class TestProcessPending:
    def test_no_fn_clears_queue(self) -> None:
        scanner = SessionScanner(session_dir=Path("/nonexistent"))
        summarizer = SessionSummarizer(scanner, summarize_fn=None)
        # Manually stuff the queue.
        summarizer._pending.append(_make_monitored_session(session_dir=Path("/tmp")))
        assert summarizer.process_pending() == 0
        assert not summarizer.has_pending

    def test_respects_max_count(self, tmp_path: Path) -> None:
        """Only processes up to max_count at a time."""
        for i in range(5):
            _make_session_dir(
                tmp_path,
                "proj",
                f"sess-{i}",
                events=[
                    {"event": "session:start", "data": {}},
                    {"event": "execution:end", "data": {}},
                ],
                transcript=[
                    {"role": "user", "content": f"Task {i}"},
                    {"role": "assistant", "content": f"Done {i}."},
                ],
            )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_fake_summarize)

        summarizer.scan()
        assert summarizer.pending_count == 5

        processed = summarizer.process_pending(max_count=2)
        assert processed == 2
        assert summarizer.pending_count == 3

    def test_handles_llm_failure(self, tmp_path: Path) -> None:
        """Failed LLM calls don't crash; session is dropped from queue."""
        _make_session_dir(
            tmp_path,
            "proj",
            "fail-1",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
            ],
            transcript=[
                {"role": "user", "content": "test"},
                {"role": "assistant", "content": "response"},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_failing_summarize)

        summarizer.scan()
        processed = summarizer.process_pending()
        assert processed == 0
        assert not summarizer.has_pending  # dropped after failure

    def test_skips_session_without_dir(self) -> None:
        """Sessions without session_dir are skipped gracefully."""
        scanner = SessionScanner(session_dir=Path("/nonexistent"))
        summarizer = SessionSummarizer(scanner, summarize_fn=_fake_summarize)

        # Queue a session with no session_dir.
        summarizer._pending.append(_make_monitored_session(session_dir=None))
        processed = summarizer.process_pending()
        assert processed == 0

    def test_skips_session_without_transcript(self, tmp_path: Path) -> None:
        """Sessions with no transcript get skipped (no crash)."""
        _make_session_dir(
            tmp_path,
            "proj",
            "no-transcript",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
            ],
            transcript=None,  # no transcript
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_fake_summarize)

        summarizer.scan()
        processed = summarizer.process_pending()
        assert processed == 0


# ===========================================================================
# Cache management
# ===========================================================================


class TestCacheManagement:
    def test_invalidate_forces_regeneration(self, tmp_path: Path) -> None:
        _make_session_dir(
            tmp_path,
            "proj",
            "sess-1",
            events=[
                {"event": "session:start", "data": {}},
                {"event": "execution:end", "data": {}},
            ],
            transcript=[
                {"role": "user", "content": "x"},
                {"role": "assistant", "content": "y"},
            ],
        )

        scanner = SessionScanner(session_dir=tmp_path, stale_threshold=999999)
        summarizer = SessionSummarizer(scanner, summarize_fn=_fake_summarize)

        # Build cache.
        summarizer.scan()
        summarizer.process_pending()

        # Verify cached.
        sessions = summarizer.scan()
        assert sessions[0].activity == "Committed fix, tests passing"
        assert not summarizer.has_pending  # cache hit, not re-queued

        # Invalidate.
        summarizer.invalidate("sess-1")

        # Next scan should re-queue.
        summarizer.scan()
        assert summarizer.has_pending

    def test_clear_cache(self, tmp_path: Path) -> None:
        scanner = SessionScanner(session_dir=tmp_path)
        summarizer = SessionSummarizer(scanner, summarize_fn=_fake_summarize)

        # Manually populate cache.
        from amplifier_tui.features.session_summarizer import _CachedSummary

        summarizer._cache["x"] = _CachedSummary(summary="test", mtime=1.0)
        summarizer._pending.append(_make_monitored_session(session_dir=tmp_path))

        summarizer.clear_cache()
        assert len(summarizer._cache) == 0
        assert not summarizer.has_pending


# ===========================================================================
# _clean_summary
# ===========================================================================


class TestCleanSummary:
    def test_strips_quotes(self) -> None:
        assert SessionSummarizer._clean_summary('"Fixed bug"') == "Fixed bug"

    def test_strips_markdown(self) -> None:
        assert SessionSummarizer._clean_summary("**Done**") == "Done"

    def test_takes_first_line(self) -> None:
        raw = "Fixed the bug\nHere's a longer explanation..."
        result = SessionSummarizer._clean_summary(raw)
        assert result == "Fixed the bug"

    def test_truncates_long_line(self) -> None:
        raw = "a" * 100
        result = SessionSummarizer._clean_summary(raw)
        assert len(result) <= 61  # 60 + ellipsis char
        assert result.endswith("\u2026")

    def test_strips_whitespace(self) -> None:
        assert SessionSummarizer._clean_summary("  hello  \n") == "hello"

    def test_strips_backticks(self) -> None:
        assert SessionSummarizer._clean_summary("`status line`") == "status line"
