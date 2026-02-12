"""Tests for WebApp streaming callbacks and display methods.

Unit tests that verify event shapes emitted by streaming callbacks and display
methods.  Uses a lightweight WebApp with a captured _send_event to avoid
needing a real WebSocket connection or LLM provider.

Protocol-level tests verify session lifecycle events through the real
WebSocket endpoint.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from amplifier_tui.web.web_app import WebApp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def events():
    """Collected events list -- shared between web_app and assertions."""
    return []


@pytest.fixture
def web_app(events):
    """WebApp with _send_event replaced by a list collector.

    This avoids needing a real WebSocket or event loop.
    The streaming callbacks and display methods all go through _send_event,
    so capturing that is sufficient to test event shapes.
    """
    mock_ws = MagicMock()
    app = WebApp(mock_ws)
    app._send_event = lambda ev: events.append(ev)
    return app


@pytest.fixture
def client():
    """Starlette TestClient for protocol-level tests."""
    from amplifier_tui.web.server import create_app

    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Streaming callback event shapes — stream blocks
# ---------------------------------------------------------------------------


class TestStreamBlockEvents:
    """Each streaming callback should emit exactly one event with correct shape."""

    def test_stream_block_start_text(self, web_app, events):
        web_app._on_stream_block_start("conv-1", "text")
        assert len(events) == 1
        assert events[0] == {"type": "stream_start", "block_type": "text"}

    def test_stream_block_start_thinking(self, web_app, events):
        web_app._on_stream_block_start("conv-1", "thinking")
        assert events[0] == {"type": "stream_start", "block_type": "thinking"}

    def test_stream_block_delta(self, web_app, events):
        web_app._on_stream_block_delta("conv-1", "text", "Hello world")
        assert len(events) == 1
        assert events[0] == {
            "type": "stream_delta",
            "block_type": "text",
            "text": "Hello world",
        }

    def test_stream_block_delta_sends_accumulated_text(self, web_app, events):
        """Delta sends the full accumulated text each time, not just the new chunk."""
        web_app._on_stream_block_delta("conv-1", "text", "Hello")
        web_app._on_stream_block_delta("conv-1", "text", "Hello world")
        assert events[0]["text"] == "Hello"
        assert events[1]["text"] == "Hello world"

    def test_stream_block_end(self, web_app, events):
        web_app._on_stream_block_end("conv-1", "text", "Final text", True)
        assert len(events) == 1
        assert events[0] == {
            "type": "stream_end",
            "block_type": "text",
            "text": "Final text",
        }

    def test_stream_block_end_without_prior_start(self, web_app, events):
        """End event shape is the same regardless of had_block_start."""
        web_app._on_stream_block_end("conv-1", "text", "Final", False)
        assert events[0] == {
            "type": "stream_end",
            "block_type": "text",
            "text": "Final",
        }


# ---------------------------------------------------------------------------
# Streaming callback event shapes — tool events
# ---------------------------------------------------------------------------


class TestStreamToolEvents:
    """Tool start/end streaming events should have correct shapes."""

    def test_tool_start(self, web_app, events):
        web_app._on_stream_tool_start("conv-1", "bash", {"command": "ls"})
        assert len(events) == 1
        assert events[0] == {
            "type": "tool_start",
            "tool_name": "bash",
            "tool_input": {"command": "ls"},
        }

    def test_tool_start_complex_input(self, web_app, events):
        tool_input = {
            "file_path": "/tmp/test.py",
            "old_string": "foo",
            "new_string": "bar",
        }
        web_app._on_stream_tool_start("conv-1", "edit_file", tool_input)
        assert events[0]["tool_name"] == "edit_file"
        assert events[0]["tool_input"] == tool_input

    def test_tool_start_empty_input(self, web_app, events):
        web_app._on_stream_tool_start("conv-1", "some_tool", {})
        assert events[0]["tool_input"] == {}

    def test_tool_end(self, web_app, events):
        web_app._on_stream_tool_end(
            "conv-1", "bash", {"command": "ls"}, "file1\nfile2"
        )
        assert len(events) == 1
        assert events[0] == {
            "type": "tool_end",
            "tool_name": "bash",
            "tool_input": {"command": "ls"},
            "result": "file1\nfile2",
        }

    def test_tool_end_with_error_result(self, web_app, events):
        web_app._on_stream_tool_end(
            "conv-1", "bash", {"command": "fail"}, "Error: command not found"
        )
        assert events[0]["type"] == "tool_end"
        assert events[0]["result"] == "Error: command not found"


# ---------------------------------------------------------------------------
# Streaming callback event shapes — usage update
# ---------------------------------------------------------------------------


class TestUsageUpdateEvent:
    """Usage update event should pull from session_manager."""

    def test_usage_update_with_session(self, web_app, events):
        # SessionManager properties delegate to _default_handle(), which is
        # None when no session is active.  Replace with a mock that has
        # plain attributes so the getter returns the values we set.
        mock_sm = MagicMock()
        mock_sm.total_input_tokens = 1500
        mock_sm.total_output_tokens = 500
        mock_sm.model_name = "claude-sonnet-4-20250514"
        web_app.session_manager = mock_sm

        web_app._on_stream_usage_update("conv-1")

        assert len(events) == 1
        assert events[0] == {
            "type": "usage_update",
            "input_tokens": 1500,
            "output_tokens": 500,
            "model": "claude-sonnet-4-20250514",
        }

    def test_usage_update_zero_tokens(self, web_app, events):
        # Without an active session, the SessionManager property getters
        # return defaults (0 / ""), which is the correct zero-state.
        web_app._on_stream_usage_update("conv-1")

        assert events[0]["input_tokens"] == 0
        assert events[0]["output_tokens"] == 0
        assert events[0]["model"] == ""

    def test_usage_update_no_session_manager(self, web_app, events):
        """When session_manager is None, no event is emitted."""
        web_app.session_manager = None
        web_app._on_stream_usage_update("conv-1")
        assert len(events) == 0


# ---------------------------------------------------------------------------
# Display method event shapes
# ---------------------------------------------------------------------------


class TestDisplayMethods:
    """Display methods should emit events with correct type and text fields."""

    def test_system_message(self, web_app, events):
        web_app._add_system_message("Hello from system")
        assert events[0] == {"type": "system_message", "text": "Hello from system"}

    def test_user_message(self, web_app, events):
        web_app._add_user_message("Hello from user")
        assert events[0] == {"type": "user_message", "text": "Hello from user"}

    def test_assistant_message(self, web_app, events):
        web_app._add_assistant_message("Hello from assistant")
        assert events[0] == {
            "type": "assistant_message",
            "text": "Hello from assistant",
        }

    def test_show_error(self, web_app, events):
        web_app._show_error("Something went wrong")
        assert events[0] == {"type": "error", "text": "Something went wrong"}

    def test_update_status(self, web_app, events):
        web_app._update_status("Processing...")
        assert events[0] == {"type": "status", "text": "Processing..."}

    def test_conversation_id_kwarg_does_not_leak(self, web_app, events):
        """Extra keyword args should not appear in the emitted event."""
        web_app._add_system_message("test", conversation_id="c1")
        assert events[0] == {"type": "system_message", "text": "test"}

    def test_empty_text_is_valid(self, web_app, events):
        """Empty string is valid — the method doesn't filter it out."""
        web_app._add_system_message("")
        assert events[0] == {"type": "system_message", "text": ""}

    def test_multiline_text_preserved(self, web_app, events):
        text = "Line 1\nLine 2\n\nLine 4"
        web_app._add_assistant_message(text)
        assert events[0]["text"] == text


# ---------------------------------------------------------------------------
# Processing start/end events
# ---------------------------------------------------------------------------


class TestProcessingEvents:
    """Processing start/end should emit events and update conversation state."""

    def test_start_processing_default_label(self, web_app, events):
        web_app._start_processing()
        assert events[0] == {"type": "processing_start", "label": "Thinking"}
        assert web_app._conversation.is_processing is True

    def test_start_processing_custom_label(self, web_app, events):
        web_app._start_processing("Searching")
        assert events[0] == {"type": "processing_start", "label": "Searching"}

    def test_finish_processing(self, web_app, events):
        web_app._conversation.is_processing = True
        web_app._finish_processing()
        assert events[0] == {"type": "processing_end"}
        assert web_app._conversation.is_processing is False

    def test_processing_round_trip(self, web_app, events):
        """Start then finish produces two events in order."""
        web_app._start_processing("Working")
        web_app._finish_processing()
        assert len(events) == 2
        assert events[0]["type"] == "processing_start"
        assert events[1]["type"] == "processing_end"
        assert web_app._conversation.is_processing is False


# ---------------------------------------------------------------------------
# Full streaming sequences (realistic event ordering)
# ---------------------------------------------------------------------------


class TestStreamingSequence:
    """Test realistic sequences of streaming events."""

    def test_text_block_lifecycle(self, web_app, events):
        """Complete text block: start -> deltas -> end."""
        cid = "conv-1"
        web_app._on_stream_block_start(cid, "text")
        web_app._on_stream_block_delta(cid, "text", "Hello")
        web_app._on_stream_block_delta(cid, "text", "Hello world")
        web_app._on_stream_block_end(cid, "text", "Hello world", True)

        types = [e["type"] for e in events]
        assert types == ["stream_start", "stream_delta", "stream_delta", "stream_end"]

    def test_tool_use_lifecycle(self, web_app, events):
        """Tool use: tool_start -> tool_end."""
        cid = "conv-1"
        web_app._on_stream_tool_start(cid, "bash", {"command": "echo hi"})
        web_app._on_stream_tool_end(cid, "bash", {"command": "echo hi"}, "hi\n")

        types = [e["type"] for e in events]
        assert types == ["tool_start", "tool_end"]

    def test_text_then_tool_then_text(self, web_app, events):
        """Realistic flow: text block, tool use, follow-up text."""
        cid = "conv-1"
        # First text block
        web_app._on_stream_block_start(cid, "text")
        web_app._on_stream_block_delta(cid, "text", "Let me check...")
        web_app._on_stream_block_end(cid, "text", "Let me check...", True)
        # Tool use
        web_app._on_stream_tool_start(cid, "bash", {"command": "ls"})
        web_app._on_stream_tool_end(cid, "bash", {"command": "ls"}, "file.py")
        # Follow-up text
        web_app._on_stream_block_start(cid, "text")
        web_app._on_stream_block_delta(cid, "text", "Found file.py")
        web_app._on_stream_block_end(cid, "text", "Found file.py", True)

        types = [e["type"] for e in events]
        assert types == [
            "stream_start",
            "stream_delta",
            "stream_end",
            "tool_start",
            "tool_end",
            "stream_start",
            "stream_delta",
            "stream_end",
        ]

    def test_thinking_then_text(self, web_app, events):
        """Thinking block followed by text block preserves block_type."""
        cid = "conv-1"
        web_app._on_stream_block_start(cid, "thinking")
        web_app._on_stream_block_delta(cid, "thinking", "Let me reason...")
        web_app._on_stream_block_end(cid, "thinking", "Let me reason...", True)
        web_app._on_stream_block_start(cid, "text")
        web_app._on_stream_block_delta(cid, "text", "The answer is 42")
        web_app._on_stream_block_end(cid, "text", "The answer is 42", True)

        # Thinking events carry block_type "thinking"
        assert events[0]["block_type"] == "thinking"
        assert events[1]["block_type"] == "thinking"
        assert events[2]["block_type"] == "thinking"
        # Text events carry block_type "text"
        assert events[3]["block_type"] == "text"
        assert events[4]["block_type"] == "text"
        assert events[5]["block_type"] == "text"

    def test_full_turn_with_processing(self, web_app, events):
        """Full assistant turn: processing_start -> stream -> processing_end."""
        cid = "conv-1"
        web_app._start_processing()
        web_app._on_stream_block_start(cid, "text")
        web_app._on_stream_block_delta(cid, "text", "Response")
        web_app._on_stream_block_end(cid, "text", "Response", True)
        web_app._finish_processing()

        types = [e["type"] for e in events]
        assert types == [
            "processing_start",
            "stream_start",
            "stream_delta",
            "stream_end",
            "processing_end",
        ]


# ---------------------------------------------------------------------------
# Session lifecycle via WebSocket protocol
# ---------------------------------------------------------------------------


class TestSessionLifecycleViaProtocol:
    """Test session lifecycle events through the WebSocket protocol."""

    def test_switch_session_invalid_id(self, client):
        """Switching to a nonexistent session produces an error, not a crash."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "switch_session", "id": "nonexistent-id-12345"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "session" in data["text"].lower() or "failed" in data["text"].lower()

    def test_switch_session_empty_id_ignored(self, client):
        """Empty session ID is silently ignored (server.py checks `if session_id:`)."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "switch_session", "id": ""})
            # Empty ID is skipped — connection should still work
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_connection_survives_switch_error(self, client):
        """After a failed switch, the connection remains usable."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "switch_session", "id": "bad-id"})
            ws.receive_json()  # error event

            # ping still works
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

            # commands still work
            ws.send_json({"type": "message", "text": "/help"})
            data = ws.receive_json()
            assert data["type"] == "system_message"

    def test_new_then_commands_still_work(self, client):
        """/new resets state but commands keep functioning."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "message", "text": "/new"})
            ws.receive_json()  # clear
            ws.receive_json()  # system_message

            ws.send_json({"type": "message", "text": "/stats"})
            data = ws.receive_json()
            assert data["type"] == "stats_panel"


# ---------------------------------------------------------------------------
# Event protocol contracts
# ---------------------------------------------------------------------------


class TestEventContracts:
    """All events must satisfy basic protocol contracts."""

    def test_all_command_events_have_type_field(self, client):
        """Every event over the WebSocket must have a 'type' string field."""
        with client.websocket_connect("/ws") as ws:
            ev = ws.receive_json()  # connected
            assert "type" in ev
            assert isinstance(ev["type"], str)

            commands = ["/help", "/clear", "/stats", "/tokens", "/agents", "/git"]
            for cmd in commands:
                ws.send_json({"type": "message", "text": cmd})
                data = ws.receive_json()
                assert "type" in data, f"Event from {cmd} missing 'type': {data}"
                assert isinstance(data["type"], str)

    def test_rapid_commands_dont_crash(self, client):
        """Sending many commands rapidly should not cause errors."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            commands = ["/help", "/clear", "/stats", "/tokens", "/agents", "/git"]
            # Fire all commands before reading any responses
            for cmd in commands:
                ws.send_json({"type": "message", "text": cmd})
            # Each command produces exactly one event
            events = [ws.receive_json() for _ in range(len(commands))]
            assert len(events) == len(commands)
            for ev in events:
                assert "type" in ev
