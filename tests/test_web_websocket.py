"""Tests for web server WebSocket protocol.

Uses Starlette's synchronous TestClient against the real FastAPI app.
Tests the WebSocket message protocol: connect, ping/pong, command dispatch.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from amplifier_tui.web.server import create_app

    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# WS /ws — connection lifecycle
# ---------------------------------------------------------------------------


class TestWebSocketConnect:
    """WS /ws — connection lifecycle."""

    def test_connect_sends_connected_event(self, client):
        """First message after WS connect should be {type: connected, status: ready}."""
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["status"] == "ready"

    def test_connect_then_close(self, client):
        """Should be able to connect and cleanly close."""
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()  # consume connected event
            assert data["type"] == "connected"
            # exiting the context manager closes the WS cleanly


# ---------------------------------------------------------------------------
# WS ping/pong keepalive protocol
# ---------------------------------------------------------------------------


class TestPingPong:
    """WS ping/pong keepalive protocol."""

    def test_ping_returns_pong(self, client):
        """Server should reply with {type: pong} to a {type: ping}."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # consume connected event
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_multiple_pings(self, client):
        """Multiple pings in sequence should each get a pong."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # consume connected event
            for _ in range(3):
                ws.send_json({"type": "ping"})
                data = ws.receive_json()
                assert data["type"] == "pong"


# ---------------------------------------------------------------------------
# WS message type dispatch — slash commands
# ---------------------------------------------------------------------------


class TestMessageDispatch:
    """WS message type dispatch for slash commands."""

    def test_slash_help_returns_system_message(self, client):
        """/help should return a system_message with help content."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # consume connected
            ws.send_json({"type": "message", "text": "/help"})
            data = ws.receive_json()
            assert data["type"] == "system_message"
            assert len(data["text"]) > 100  # help text should be substantial

    def test_slash_clear_returns_clear_event(self, client):
        """/clear should return a clear event."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # consume connected
            ws.send_json({"type": "message", "text": "/clear"})
            data = ws.receive_json()
            assert data["type"] == "clear"

    def test_unknown_command_returns_system_message(self, client):
        """/nonexistent should return a system_message about unknown command."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # consume connected
            ws.send_json({"type": "message", "text": "/nonexistent_cmd_xyz"})
            data = ws.receive_json()
            assert data["type"] == "system_message"
            assert "unknown" in data["text"].lower()

    def test_unknown_ws_type_is_ignored(self, client):
        """Unknown message types should be silently ignored (no crash)."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # consume connected
            ws.send_json({"type": "totally_bogus_type"})
            # Should not crash — send a ping to verify connection still alive
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"
