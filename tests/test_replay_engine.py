"""Tests for the Session Replay engine (F3.3).

Tests cover the ReplayEngine, ReplayMessage dataclass, ReplayState enum,
and importability of the ReplayCommandsMixin — all in isolation (no app).
"""

from __future__ import annotations

import json

import pytest

from amplifier_tui.features.replay_engine import (
    ReplayEngine,
    ReplayMessage,
    ReplayState,
)
from amplifier_tui.commands.replay_cmds import ReplayCommandsMixin


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayMessage dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplayMessage:
    def test_defaults(self):
        msg = ReplayMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.timestamp is None
        assert msg.delay_ms == 0
        assert msg.tool_name == ""
        assert msg.index == 0

    def test_custom_fields(self):
        from datetime import datetime

        ts = datetime(2025, 1, 15, 10, 30, 0)
        msg = ReplayMessage(
            role="assistant",
            content="response",
            timestamp=ts,
            delay_ms=1500.0,
            tool_name="read_file",
            index=5,
        )
        assert msg.role == "assistant"
        assert msg.content == "response"
        assert msg.timestamp == ts
        assert msg.delay_ms == 1500.0
        assert msg.tool_name == "read_file"
        assert msg.index == 5


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayState enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplayState:
    def test_idle_value(self):
        assert ReplayState.IDLE.value == "idle"

    def test_playing_value(self):
        assert ReplayState.PLAYING.value == "playing"

    def test_paused_value(self):
        assert ReplayState.PAUSED.value == "paused"

    def test_finished_value(self):
        assert ReplayState.FINISHED.value == "finished"

    def test_all_states(self):
        assert len(ReplayState) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — Initial State
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplayEngineInit:
    def test_state_idle(self):
        engine = ReplayEngine()
        assert engine.state == ReplayState.IDLE

    def test_position_zero(self):
        engine = ReplayEngine()
        assert engine.position == 0

    def test_total_messages_zero(self):
        engine = ReplayEngine()
        assert engine.total_messages == 0

    def test_speed_default(self):
        engine = ReplayEngine()
        assert engine.speed == 1.0
        assert engine.speed_label == "1x"

    def test_session_id_empty(self):
        engine = ReplayEngine()
        assert engine.session_id == ""

    def test_is_playing_false(self):
        engine = ReplayEngine()
        assert engine.is_playing is False

    def test_is_paused_false(self):
        engine = ReplayEngine()
        assert engine.is_paused is False

    def test_is_finished_false(self):
        engine = ReplayEngine()
        assert engine.is_finished is False

    def test_messages_empty(self):
        engine = ReplayEngine()
        assert engine.messages == []

    def test_progress_pct_zero(self):
        engine = ReplayEngine()
        assert engine.progress_pct == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — load_transcript()
# ═══════════════════════════════════════════════════════════════════════════════


def _make_lines(*messages: dict) -> list[str]:
    """Helper to create JSONL lines from dicts."""
    return [json.dumps(m) for m in messages]


class TestLoadTranscript:
    def test_parses_valid_jsonl(self):
        lines = _make_lines(
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        )
        engine = ReplayEngine()
        count = engine.load_transcript(lines)
        assert count == 2
        assert engine.total_messages == 2

    def test_handles_malformed_json(self):
        lines = [
            '{"role": "user", "content": "hello"}',
            "this is not json",
            '{"role": "assistant", "content": "hi"}',
        ]
        engine = ReplayEngine()
        count = engine.load_transcript(lines)
        assert count == 2  # skips malformed line

    def test_skips_empty_lines(self):
        lines = [
            '{"role": "user", "content": "hello"}',
            "",
            "   ",
            '{"role": "assistant", "content": "hi"}',
        ]
        engine = ReplayEngine()
        count = engine.load_transcript(lines)
        assert count == 2

    def test_skips_entries_without_role(self):
        lines = _make_lines(
            {"content": "no role here"},
            {"role": "user", "content": "hello"},
        )
        engine = ReplayEngine()
        count = engine.load_transcript(lines)
        assert count == 1

    def test_skips_entries_without_content(self):
        lines = _make_lines(
            {"role": "user"},
            {"role": "user", "content": "hello"},
        )
        engine = ReplayEngine()
        count = engine.load_transcript(lines)
        assert count == 1

    def test_includes_tool_name_entries(self):
        """Entries with tool_name should be included even without content."""
        lines = _make_lines(
            {"role": "assistant", "tool_name": "read_file"},
        )
        engine = ReplayEngine()
        count = engine.load_transcript(lines)
        assert count == 1
        assert engine.messages[0].tool_name == "read_file"

    def test_calculates_delays_from_timestamps(self):
        lines = _make_lines(
            {
                "role": "user",
                "content": "hello",
                "timestamp": "2025-01-15T10:00:00",
            },
            {
                "role": "assistant",
                "content": "hi",
                "timestamp": "2025-01-15T10:00:05",
            },
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        msgs = engine.messages
        assert msgs[0].delay_ms == 0  # first message has no delay
        assert msgs[1].delay_ms == 5000  # 5 seconds = 5000ms

    def test_caps_delays_at_30000ms(self):
        lines = _make_lines(
            {
                "role": "user",
                "content": "hello",
                "timestamp": "2025-01-15T10:00:00",
            },
            {
                "role": "assistant",
                "content": "hi",
                "timestamp": "2025-01-15T10:05:00",
            },
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        msgs = engine.messages
        assert msgs[1].delay_ms == 30000  # capped at 30s

    def test_handles_utc_z_timestamp(self):
        lines = _make_lines(
            {
                "role": "user",
                "content": "hello",
                "timestamp": "2025-01-15T10:00:00Z",
            },
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        assert engine.messages[0].timestamp is not None

    def test_handles_invalid_timestamp(self):
        lines = _make_lines(
            {
                "role": "user",
                "content": "hello",
                "timestamp": "not-a-date",
            },
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        assert engine.messages[0].timestamp is None

    def test_stores_session_id(self):
        lines = _make_lines({"role": "user", "content": "hello"})
        engine = ReplayEngine()
        engine.load_transcript(lines, session_id="test-123")
        assert engine.session_id == "test-123"

    def test_stores_source_path(self):
        lines = _make_lines({"role": "user", "content": "hello"})
        engine = ReplayEngine()
        engine.load_transcript(lines, source_path="/tmp/transcript.jsonl")
        assert engine._source_path == "/tmp/transcript.jsonl"

    def test_resets_on_reload(self):
        lines = _make_lines({"role": "user", "content": "hello"})
        engine = ReplayEngine()
        engine.load_transcript(lines)
        assert engine.total_messages == 1
        # Reload with different data
        lines2 = _make_lines(
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "user", "content": "c"},
        )
        count = engine.load_transcript(lines2)
        assert count == 3
        assert engine.total_messages == 3
        assert engine.position == 0

    def test_non_string_content_converted(self):
        """Content that isn't a string gets str() applied."""
        lines = _make_lines(
            {"role": "user", "content": ["list", "content"]},
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        assert engine.messages[0].content == "['list', 'content']"

    def test_message_indices_sequential(self):
        lines = _make_lines(
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        for i, msg in enumerate(engine.messages):
            assert msg.index == i

    def test_no_delay_for_first_message(self):
        lines = _make_lines(
            {
                "role": "user",
                "content": "hello",
                "timestamp": "2025-01-15T10:00:00",
            },
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        assert engine.messages[0].delay_ms == 0

    def test_negative_delay_clamped_to_zero(self):
        """If timestamps go backward, delay should be 0 not negative."""
        lines = _make_lines(
            {
                "role": "user",
                "content": "hello",
                "timestamp": "2025-01-15T10:00:10",
            },
            {
                "role": "assistant",
                "content": "hi",
                "timestamp": "2025-01-15T10:00:05",
            },
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        assert engine.messages[1].delay_ms == 0


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — play()
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlay:
    def test_starts_playback(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "hi"}))
        engine.play()
        assert engine.state == ReplayState.PLAYING
        assert engine.is_playing is True

    def test_raises_when_no_transcript(self):
        engine = ReplayEngine()
        with pytest.raises(RuntimeError, match="No transcript loaded"):
            engine.play()

    def test_restarts_from_finished(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "hi"}))
        engine.play()
        engine.next_message()  # finishes (only 1 message)
        assert engine.is_finished
        engine.play()  # restart
        assert engine.is_playing
        assert engine.position == 0


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — pause() / resume()
# ═══════════════════════════════════════════════════════════════════════════════


class TestPauseResume:
    def test_pause_changes_state(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
            )
        )
        engine.play()
        engine.pause()
        assert engine.state == ReplayState.PAUSED
        assert engine.is_paused is True

    def test_pause_noop_when_not_playing(self):
        engine = ReplayEngine()
        engine.pause()
        assert engine.state == ReplayState.IDLE

    def test_resume_changes_state(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
            )
        )
        engine.play()
        engine.pause()
        engine.resume()
        assert engine.state == ReplayState.PLAYING
        assert engine.is_playing is True

    def test_resume_noop_when_not_paused(self):
        engine = ReplayEngine()
        engine.resume()
        assert engine.state == ReplayState.IDLE


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — stop()
# ═══════════════════════════════════════════════════════════════════════════════


class TestStop:
    def test_stop_resets_to_idle(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
            )
        )
        engine.play()
        engine.next_message()
        engine.stop()
        assert engine.state == ReplayState.IDLE

    def test_stop_resets_position(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
            )
        )
        engine.play()
        engine.next_message()
        assert engine.position == 1
        engine.stop()
        assert engine.position == 0


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — next_message()
# ═══════════════════════════════════════════════════════════════════════════════


class TestNextMessage:
    def test_advances_position(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        msg = engine.next_message()
        assert msg is not None
        assert msg.role == "user"
        assert msg.content == "a"
        assert engine.position == 1

    def test_returns_none_when_finished(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        engine.play()
        engine.next_message()  # consumes the only message
        assert engine.is_finished
        msg = engine.next_message()
        assert msg is None

    def test_returns_none_when_not_playing(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        # Not playing — still IDLE
        msg = engine.next_message()
        assert msg is None

    def test_returns_none_when_paused(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
            )
        )
        engine.play()
        engine.pause()
        msg = engine.next_message()
        assert msg is None

    def test_sets_finished_on_last_message(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        engine.next_message()  # msg 0
        engine.next_message()  # msg 1 — last
        assert engine.state == ReplayState.FINISHED


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — skip()
# ═══════════════════════════════════════════════════════════════════════════════


class TestSkip:
    def test_skip_works_when_paused(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        engine.pause()
        msg = engine.skip()
        assert msg is not None
        assert msg.content == "a"
        assert engine.position == 1

    def test_skip_works_when_playing(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        msg = engine.skip()
        assert msg is not None
        assert msg.content == "a"

    def test_skip_returns_none_when_idle(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        msg = engine.skip()
        assert msg is None

    def test_skip_returns_none_when_finished(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        engine.play()
        engine.next_message()
        assert engine.is_finished
        msg = engine.skip()
        assert msg is None

    def test_skip_sets_finished_on_last(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        engine.play()
        engine.pause()
        engine.skip()
        assert engine.is_finished


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — set_speed()
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetSpeed:
    def test_valid_options(self):
        engine = ReplayEngine()
        for label, expected in ReplayEngine.SPEED_OPTIONS.items():
            engine.set_speed(label)
            assert engine.speed == expected
            assert engine.speed_label == label

    def test_case_insensitive(self):
        engine = ReplayEngine()
        engine.set_speed("INSTANT")
        assert engine.speed == 0.0
        assert engine.speed_label == "instant"

    def test_strips_whitespace(self):
        engine = ReplayEngine()
        engine.set_speed("  2x  ")
        assert engine.speed == 2.0

    def test_raises_for_invalid(self):
        engine = ReplayEngine()
        with pytest.raises(ValueError, match="Invalid speed '3x'"):
            engine.set_speed("3x")


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — get_adjusted_delay()
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetAdjustedDelay:
    def test_1x_speed(self):
        engine = ReplayEngine()
        msg = ReplayMessage(role="user", content="x", delay_ms=2000)
        assert engine.get_adjusted_delay(msg) == 2000

    def test_2x_speed(self):
        engine = ReplayEngine()
        engine.set_speed("2x")
        msg = ReplayMessage(role="user", content="x", delay_ms=2000)
        assert engine.get_adjusted_delay(msg) == 1000

    def test_half_speed(self):
        engine = ReplayEngine()
        engine.set_speed("0.5x")
        msg = ReplayMessage(role="user", content="x", delay_ms=2000)
        assert engine.get_adjusted_delay(msg) == 4000

    def test_5x_speed(self):
        engine = ReplayEngine()
        engine.set_speed("5x")
        msg = ReplayMessage(role="user", content="x", delay_ms=5000)
        assert engine.get_adjusted_delay(msg) == 1000

    def test_instant_returns_zero(self):
        engine = ReplayEngine()
        engine.set_speed("instant")
        msg = ReplayMessage(role="user", content="x", delay_ms=5000)
        assert engine.get_adjusted_delay(msg) == 0

    def test_zero_delay_unchanged(self):
        engine = ReplayEngine()
        engine.set_speed("2x")
        msg = ReplayMessage(role="user", content="x", delay_ms=0)
        assert engine.get_adjusted_delay(msg) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — progress_pct
# ═══════════════════════════════════════════════════════════════════════════════


class TestProgressPct:
    def test_zero_when_empty(self):
        engine = ReplayEngine()
        assert engine.progress_pct == 0.0

    def test_zero_at_start(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        assert engine.progress_pct == 0.0

    def test_fifty_at_midpoint(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        engine.next_message()
        assert engine.progress_pct == 50.0

    def test_hundred_at_end(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        engine.next_message()
        engine.next_message()
        assert engine.progress_pct == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — format_status()
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatStatus:
    def test_idle_no_messages(self):
        engine = ReplayEngine()
        status = engine.format_status()
        assert "No replay active" in status
        assert "/replay" in status

    def test_playing_state(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        status = engine.format_status()
        assert "playing" in status
        assert "0/2" in status

    def test_paused_state(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.play()
        engine.pause()
        status = engine.format_status()
        assert "paused" in status

    def test_finished_state(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        engine.play()
        engine.next_message()
        status = engine.format_status()
        assert "finished" in status

    def test_shows_session_id(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines({"role": "user", "content": "a"}),
            session_id="my-session-id",
        )
        status = engine.format_status()
        assert "my-session-id" in status

    def test_shows_speed(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        engine.set_speed("5x")
        status = engine.format_status()
        assert "5x" in status

    def test_shows_progress_bar(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        status = engine.format_status()
        # Progress bar contains block characters
        assert "\u2588" in status or "\u2591" in status

    def test_shows_last_message_preview(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines({"role": "user", "content": "unique_test_content"})
        )
        engine.play()
        engine.next_message()
        status = engine.format_status()
        assert "unique_test_content" in status

    def test_long_session_id_truncated(self):
        engine = ReplayEngine()
        long_id = "a" * 50
        engine.load_transcript(
            _make_lines({"role": "user", "content": "a"}),
            session_id=long_id,
        )
        status = engine.format_status()
        assert "..." in status


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — format_timeline()
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatTimeline:
    def test_empty_messages(self):
        engine = ReplayEngine()
        timeline = engine.format_timeline()
        assert "No messages loaded" in timeline

    def test_shows_messages(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "hello world"},
                {"role": "assistant", "content": "hi there"},
            )
        )
        timeline = engine.format_timeline()
        assert "hello world" in timeline
        assert "hi there" in timeline

    def test_shows_position_marker(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        timeline = engine.format_timeline()
        assert "\u2192" in timeline  # arrow marker

    def test_shows_timestamps(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {
                    "role": "user",
                    "content": "a",
                    "timestamp": "2025-01-15T10:30:00",
                },
            )
        )
        timeline = engine.format_timeline()
        assert "10:30:00" in timeline

    def test_shows_unknown_time(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        timeline = engine.format_timeline()
        assert "??:??:??" in timeline


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — clear()
# ═══════════════════════════════════════════════════════════════════════════════


class TestClear:
    def test_resets_state(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines({"role": "user", "content": "a"}),
            session_id="test",
        )
        engine.play()
        engine.set_speed("5x")
        engine.next_message()

        engine.clear()

        assert engine.state == ReplayState.IDLE
        assert engine.total_messages == 0
        assert engine.position == 0
        assert engine.speed == 1.0
        assert engine.speed_label == "1x"
        assert engine.session_id == ""

    def test_messages_empty_after_clear(self):
        engine = ReplayEngine()
        engine.load_transcript(
            _make_lines(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            )
        )
        engine.clear()
        assert engine.messages == []


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — messages property
# ═══════════════════════════════════════════════════════════════════════════════


class TestMessagesProperty:
    def test_returns_copy(self):
        engine = ReplayEngine()
        engine.load_transcript(_make_lines({"role": "user", "content": "a"}))
        msgs = engine.messages
        msgs.append(ReplayMessage(role="fake", content="injected"))
        # Original should be unaffected
        assert engine.total_messages == 1


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayEngine — Full Playback Workflow
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullPlaybackWorkflow:
    def test_load_play_consume_finish(self):
        lines = _make_lines(
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        )
        engine = ReplayEngine()

        # Load
        count = engine.load_transcript(lines, session_id="workflow-test")
        assert count == 3
        assert engine.state == ReplayState.IDLE

        # Play
        engine.play()
        assert engine.state == ReplayState.PLAYING

        # Consume messages
        msg1 = engine.next_message()
        assert msg1 is not None
        assert msg1.content == "first"
        assert engine.position == 1

        msg2 = engine.next_message()
        assert msg2 is not None
        assert msg2.content == "second"
        assert engine.position == 2

        msg3 = engine.next_message()
        assert msg3 is not None
        assert msg3.content == "third"
        assert engine.position == 3

        # Finished
        assert engine.state == ReplayState.FINISHED
        assert engine.is_finished is True
        assert engine.progress_pct == 100.0

        # No more messages
        msg4 = engine.next_message()
        assert msg4 is None

    def test_pause_skip_resume_workflow(self):
        lines = _make_lines(
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        engine.play()

        # Play first message
        engine.next_message()
        assert engine.position == 1

        # Pause
        engine.pause()
        assert engine.is_paused

        # next_message returns None while paused
        assert engine.next_message() is None

        # Skip works while paused
        msg = engine.skip()
        assert msg is not None
        assert msg.content == "b"
        assert engine.position == 2

        # Resume
        engine.resume()
        assert engine.is_playing

        # Continue consuming
        msg = engine.next_message()
        assert msg is not None
        assert msg.content == "c"

    def test_stop_and_restart(self):
        lines = _make_lines(
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)

        engine.play()
        engine.next_message()
        engine.stop()

        assert engine.state == ReplayState.IDLE
        assert engine.position == 0

        # Can restart
        engine.play()
        msg = engine.next_message()
        assert msg is not None
        assert msg.content == "a"

    def test_speed_affects_delays(self):
        lines = _make_lines(
            {
                "role": "user",
                "content": "a",
                "timestamp": "2025-01-15T10:00:00",
            },
            {
                "role": "assistant",
                "content": "b",
                "timestamp": "2025-01-15T10:00:10",
            },
        )
        engine = ReplayEngine()
        engine.load_transcript(lines)
        engine.set_speed("2x")

        msgs = engine.messages
        delay = engine.get_adjusted_delay(msgs[1])
        assert delay == 5000  # 10000ms / 2x = 5000ms


# ═══════════════════════════════════════════════════════════════════════════════
# ReplayCommandsMixin — importability
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplayCommandsMixin:
    def test_mixin_exists(self):
        assert ReplayCommandsMixin is not None

    def test_has_cmd_replay(self):
        assert hasattr(ReplayCommandsMixin, "_cmd_replay")

    def test_cmd_replay_is_callable(self):
        assert callable(getattr(ReplayCommandsMixin, "_cmd_replay"))
