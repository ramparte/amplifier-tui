"""Tests for web server HTTP routes.

Uses Starlette's synchronous TestClient against the real FastAPI app.
No route mocking — every request hits the actual endpoint handlers.
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
# GET /  — main SPA page
# ---------------------------------------------------------------------------


class TestIndexRoute:
    """GET / — serves the single-page HTML app."""

    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_content_type_is_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_contains_app_div(self, client):
        resp = client.get("/")
        assert 'id="app"' in resp.text

    def test_contains_chat_input(self, client):
        resp = client.get("/")
        assert 'id="chat-input"' in resp.text

    def test_contains_messages_container(self, client):
        resp = client.get("/")
        assert 'id="messages"' in resp.text

    def test_loads_app_js(self, client):
        resp = client.get("/")
        assert "/static/app.js" in resp.text

    def test_loads_style_css(self, client):
        resp = client.get("/")
        assert "/static/style.css" in resp.text

    def test_contains_title(self, client):
        resp = client.get("/")
        assert "<title>Amplifier</title>" in resp.text


# ---------------------------------------------------------------------------
# GET /static/*  — JS, CSS, and other static assets
# ---------------------------------------------------------------------------


class TestStaticFiles:
    """GET /static/* — serves JS, CSS, and other static assets."""

    def test_app_js_returns_200(self, client):
        resp = client.get("/static/app.js")
        assert resp.status_code == 200

    def test_app_js_is_javascript(self, client):
        resp = client.get("/static/app.js")
        assert "javascript" in resp.headers["content-type"]

    def test_app_js_contains_handleEvent(self, client):
        """Verify app.js has the core event dispatch function."""
        resp = client.get("/static/app.js")
        assert "handleEvent" in resp.text

    def test_style_css_returns_200(self, client):
        resp = client.get("/static/style.css")
        assert resp.status_code == 200

    def test_style_css_is_css(self, client):
        resp = client.get("/static/style.css")
        assert "css" in resp.headers["content-type"]

    def test_nonexistent_static_returns_404(self, client):
        resp = client.get("/static/nonexistent.xyz")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /favicon.ico
# ---------------------------------------------------------------------------


class TestFavicon:
    """GET /favicon.ico — returns without a 500."""

    def test_returns_success(self, client):
        resp = client.get("/favicon.ico")
        # The route returns index.html as a fallback — any non-error is fine
        assert resp.status_code in (200, 204, 404)


# ---------------------------------------------------------------------------
# GET /api/sessions  — session list API
# ---------------------------------------------------------------------------


class TestSessionsAPI:
    """GET /api/sessions — returns session list."""

    def test_returns_200(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200

    def test_returns_json(self, client):
        resp = client.get("/api/sessions")
        assert "application/json" in resp.headers["content-type"]

    def test_response_has_sessions_key(self, client):
        resp = client.get("/api/sessions")
        data = resp.json()
        assert "sessions" in data

    def test_sessions_is_list(self, client):
        resp = client.get("/api/sessions")
        data = resp.json()
        assert isinstance(data["sessions"], list)

    def test_limit_param_accepted(self, client):
        """The limit query param should be accepted without error."""
        resp = client.get("/api/sessions?limit=5")
        assert resp.status_code == 200

    def test_session_shape_if_any(self, client):
        """If sessions exist, each should have id, title, date keys."""
        resp = client.get("/api/sessions")
        data = resp.json()
        for session in data["sessions"]:
            assert "id" in session
            assert "title" in session
            assert "date" in session
