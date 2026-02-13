"""Tests for web slash commands and structured card events.

Tests the full path: client sends /command → server routes → structured event sent back.
Validates both routing correctness and event data shapes.
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


def send_command(ws, command: str) -> dict:
    """Send a slash command and return the first response event."""
    ws.send_json({"type": "message", "text": command})
    return ws.receive_json()


def collect_events(ws, command: str, count: int) -> list[dict]:
    """Send command and collect exactly `count` response events."""
    ws.send_json({"type": "message", "text": command})
    return [ws.receive_json() for _ in range(count)]


# ---------------------------------------------------------------------------
# Command routing — correct handler dispatched for each slash command
# ---------------------------------------------------------------------------


class TestCommandRouting:
    """Test that commands route to the correct handlers."""

    def test_help_routes(self, client):
        """/help should produce a system_message with help content."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/help")
            assert data["type"] == "system_message"
            assert len(data["text"]) > 50

    def test_clear_routes(self, client):
        """/clear should produce a clear event."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/clear")
            assert data["type"] == "clear"

    def test_unknown_command_error(self, client):
        """An unknown /command should produce a system_message about 'Unknown command'."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/definitely_not_a_real_command")
            assert data["type"] == "system_message"
            assert "unknown" in data["text"].lower()

    def test_sessions_command_routes(self, client):
        """/sessions should produce a system_message (sidebar-based listing)."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/sessions")
            assert data["type"] == "system_message"
            # The message tells users the sidebar has sessions
            assert "session" in data["text"].lower()

    def test_new_command_sends_clear_then_message(self, client):
        """/new sends exactly two events: clear, then system_message."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            events = collect_events(ws, "/new", count=2)
            assert events[0]["type"] == "clear"
            assert events[1]["type"] == "system_message"
            assert "new session" in events[1]["text"].lower()

    def test_command_case_insensitive(self, client):
        """/CLEAR and /Clear should both route to the clear handler."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            # The routing does cmd = parts[0].lower()
            data = send_command(ws, "/CLEAR")
            assert data["type"] == "clear"

    def test_connection_survives_unknown_command(self, client):
        """After an unknown command the WebSocket should remain usable."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            send_command(ws, "/bogus_xyz")
            # Connection still alive — ping should work
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


# ---------------------------------------------------------------------------
# /stats — structured stats_panel event
# ---------------------------------------------------------------------------


class TestStatsPanel:
    """/stats should return a stats_panel structured event with correct shape."""

    def test_stats_returns_stats_panel(self, client):
        """Fresh session should produce a stats_panel (all counters at zero)."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/stats")
            assert data["type"] == "stats_panel"

    def test_stats_has_required_fields(self, client):
        """stats_panel must carry duration, message counts, token counts, model, cost."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/stats")
            assert ev["type"] == "stats_panel"
            for key in (
                "duration",
                "messages",
                "user_messages",
                "assistant_messages",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "tool_calls",
                "model",
                "cost",
                "avg_response_time",
                "top_tools",
            ):
                assert key in ev, f"Missing key: {key}"

    def test_stats_numeric_types(self, client):
        """Integer counters must actually be ints, not strings."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/stats")
            assert ev["type"] == "stats_panel"
            assert isinstance(ev["messages"], int)
            assert isinstance(ev["user_messages"], int)
            assert isinstance(ev["assistant_messages"], int)
            assert isinstance(ev["input_tokens"], int)
            assert isinstance(ev["output_tokens"], int)
            assert isinstance(ev["total_tokens"], int)
            assert isinstance(ev["tool_calls"], int)

    def test_stats_top_tools_shape(self, client):
        """top_tools should be a list of {name, count} dicts."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/stats")
            assert ev["type"] == "stats_panel"
            assert isinstance(ev["top_tools"], list)
            # Fresh session: empty list is fine
            for tool in ev["top_tools"]:
                assert "name" in tool
                assert "count" in tool

    def test_stats_cost_is_dollar_string(self, client):
        """cost should be formatted as '$X.XXXX'."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/stats")
            assert ev["type"] == "stats_panel"
            assert ev["cost"].startswith("$")

    def test_stats_duration_is_string(self, client):
        """duration should be a human-readable string like '0s' or '1m 5s'."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/stats")
            assert ev["type"] == "stats_panel"
            assert isinstance(ev["duration"], str)
            assert "s" in ev["duration"]  # always contains seconds


# ---------------------------------------------------------------------------
# /tokens — structured token_usage event
# ---------------------------------------------------------------------------


class TestTokenUsage:
    """/tokens should return a token_usage structured event."""

    def test_tokens_returns_token_usage(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/tokens")
            assert ev["type"] == "token_usage"

    def test_tokens_has_required_fields(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/tokens")
            assert ev["type"] == "token_usage"
            for key in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "context_window",
                "usage_pct",
                "model",
                "cost",
            ):
                assert key in ev, f"Missing key: {key}"

    def test_tokens_numeric_types(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/tokens")
            assert ev["type"] == "token_usage"
            assert isinstance(ev["input_tokens"], int)
            assert isinstance(ev["output_tokens"], int)
            assert isinstance(ev["total_tokens"], int)
            assert isinstance(ev["context_window"], int)
            assert isinstance(ev["usage_pct"], (int, float))

    def test_tokens_usage_pct_in_range(self, client):
        """usage_pct should be between 0 and 100."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/tokens")
            assert ev["type"] == "token_usage"
            assert 0 <= ev["usage_pct"] <= 100


# ---------------------------------------------------------------------------
# /agents — structured agent_tree event
# ---------------------------------------------------------------------------


class TestAgentTree:
    """/agents should return an agent_tree structured event."""

    def test_agents_returns_agent_tree(self, client):
        """Fresh session with no delegations should still produce agent_tree."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/agents")
            assert ev["type"] == "agent_tree"

    def test_agents_has_required_fields(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/agents")
            assert ev["type"] == "agent_tree"
            for key in ("agents", "total", "running", "completed", "failed"):
                assert key in ev, f"Missing key: {key}"

    def test_agents_numeric_types(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/agents")
            assert ev["type"] == "agent_tree"
            assert isinstance(ev["agents"], list)
            assert isinstance(ev["total"], int)
            assert isinstance(ev["running"], int)
            assert isinstance(ev["completed"], int)
            assert isinstance(ev["failed"], int)

    def test_agents_fresh_session_is_empty(self, client):
        """A fresh session should have zero agents."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/agents")
            assert ev["type"] == "agent_tree"
            assert ev["agents"] == []
            assert ev["total"] == 0


# ---------------------------------------------------------------------------
# /git — structured git_status event
# ---------------------------------------------------------------------------


class TestGitStatus:
    """/git should return a git_status structured event (we are in a git repo)."""

    def test_git_returns_git_status(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/git")
            assert ev["type"] == "git_status"

    def test_git_has_required_fields(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/git")
            assert ev["type"] == "git_status"
            for key in (
                "branch",
                "staged",
                "modified",
                "untracked",
                "ahead",
                "behind",
                "clean",
                "last_commit",
            ):
                assert key in ev, f"Missing key: {key}"

    def test_git_field_types(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/git")
            assert ev["type"] == "git_status"
            assert isinstance(ev["branch"], str)
            assert isinstance(ev["staged"], int)
            assert isinstance(ev["modified"], int)
            assert isinstance(ev["untracked"], int)
            assert isinstance(ev["ahead"], int)
            assert isinstance(ev["behind"], int)
            assert isinstance(ev["clean"], bool)
            assert isinstance(ev["last_commit"], str)

    def test_git_branch_is_nonempty(self, client):
        """We know we are in a git repo, so branch must not be empty."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/git")
            assert ev["type"] == "git_status"
            assert len(ev["branch"]) > 0


# ---------------------------------------------------------------------------
# /dashboard — structured dashboard event
# ---------------------------------------------------------------------------


class TestDashboard:
    """/dashboard should return a dashboard structured event."""

    def test_dashboard_returns_event(self, client):
        """dashboard should produce either a dashboard event or system_message fallback."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/dashboard")
            # May be structured dashboard or system_message fallback
            assert ev["type"] in ("dashboard", "system_message")

    def test_dashboard_structured_shape(self, client):
        """If dashboard event is returned, validate its shape."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/dashboard")
            if ev["type"] == "dashboard":
                for key in (
                    "total_sessions",
                    "total_tokens",
                    "total_duration",
                    "avg_duration",
                    "streak_days",
                    "longest_streak",
                    "top_models",
                    "top_projects",
                ):
                    assert key in ev, f"Missing key: {key}"
                assert isinstance(ev["total_sessions"], int)
                assert isinstance(ev["total_tokens"], int)
                assert isinstance(ev["top_models"], list)
                assert isinstance(ev["top_projects"], list)


# ---------------------------------------------------------------------------
# /help — content quality checks
# ---------------------------------------------------------------------------


class TestHelpContent:
    """/help should return substantial, well-structured help text."""

    def test_help_mentions_key_commands(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/help")
            text = data["text"].lower()
            # Help should mention at least these key commands
            assert "/stats" in text
            assert "/clear" in text
            assert "/tokens" in text
            assert "/git" in text
            assert "/agents" in text

    def test_help_is_substantial(self, client):
        """Help text should be substantial, not a stub."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/help")
            assert len(data["text"]) > 500

    def test_help_has_categories(self, client):
        """Help text should be organized into categories."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/help")
            text = data["text"]
            # Source code shows these category headers
            assert "Session" in text
            assert "Information" in text
            assert "Git" in text

    def test_help_mentions_new_and_sessions(self, client):
        """Help should document session management commands."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            data = send_command(ws, "/help")
            text = data["text"].lower()
            assert "/new" in text
            assert "/sessions" in text


# ---------------------------------------------------------------------------
# Alias commands — verify aliases route the same as primaries
# ---------------------------------------------------------------------------


class TestCommandAliases:
    """Several commands have aliases that should route identically."""

    def test_gs_aliases_git(self, client):
        """/gs should produce the same git_status event as /git."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/gs")
            assert ev["type"] == "git_status"

    def test_gitstatus_aliases_git(self, client):
        """/gitstatus should produce the same git_status event as /git."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/gitstatus")
            assert ev["type"] == "git_status"

    def test_token_aliases_tokens(self, client):
        """/token (singular) should work the same as /tokens."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/token")
            assert ev["type"] == "token_usage"

    def test_session_aliases_sessions(self, client):
        """/session should work the same as /sessions."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/session")
            assert ev["type"] == "system_message"
            assert "session" in ev["text"].lower()

    def test_list_aliases_sessions(self, client):
        """/list should work the same as /sessions."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ev = send_command(ws, "/list")
            assert ev["type"] == "system_message"
