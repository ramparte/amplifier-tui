"""FastAPI server for the Amplifier web frontend."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from amplifier_tui.core.session_manager import SessionManager

from .web_app import WebApp

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


def create_app(resume_session_id: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Amplifier Web")

    # Serve static files (app.js, style.css)
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Serve the single-page app."""
        html = (_TEMPLATES / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(content=html)

    @app.get("/favicon.ico")
    async def favicon() -> FileResponse:
        """Serve a minimal favicon to avoid 404s."""
        # Return the index as a fallback; browsers won't complain
        return FileResponse(_TEMPLATES / "index.html", media_type="text/html")

    @app.get("/api/sessions")
    async def list_sessions(limit: int = 50) -> dict:
        """List available sessions, normalized for the web frontend."""
        from amplifier_tui.core.persistence.tags import TagStore
        from amplifier_tui.core.persistence.pinned_sessions import PinnedSessionStore

        raw = SessionManager.list_all_sessions(limit=limit)
        amp_home = Path.home() / ".amplifier"
        tag_store = TagStore(amp_home / "tui-session-tags.json")
        pinned_store = PinnedSessionStore(amp_home / "tui-pinned-sessions.json")
        all_tags = tag_store.load()
        pinned_ids = pinned_store.load()

        sessions = []
        for s in raw:
            sid = s.get("session_id", "")
            sessions.append(
                {
                    "id": sid,
                    "title": s.get("name") or s.get("description") or sid[:12],
                    "date": s.get("date_str", ""),
                    "active": False,
                    "project": s.get("project", ""),
                    "project_path": s.get("project_path", ""),
                    "tags": all_tags.get(sid, []),
                    "pinned": sid in pinned_ids,
                }
            )
        return {"sessions": sessions}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """Bidirectional WebSocket for chat."""
        await ws.accept()
        web_app = WebApp(ws)

        try:
            await web_app.initialize()

            # If resuming a session, do it now
            if resume_session_id:
                try:
                    sid = resume_session_id
                    if sid == "__most_recent__":
                        sid = web_app.session_manager._find_most_recent_session()
                    await web_app.session_manager.resume_session(sid)
                    web_app._amplifier_ready = True
                    web_app._send_event(
                        {
                            "type": "session_resumed",
                            "session_id": web_app.session_manager.session_id or "",
                            "model": web_app.session_manager.model_name or "",
                        }
                    )
                    web_app._add_system_message(
                        f"Resumed session {web_app.session_manager.session_id}"
                    )
                except Exception as exc:
                    web_app._show_error(f"Failed to resume session: {exc}")

            # Message loop
            while True:
                data = await ws.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "message":
                    text = data.get("text", "")
                    await web_app.handle_message(text)
                elif msg_type == "switch_session":
                    session_id = data.get("id", "")
                    if session_id:
                        await web_app.switch_to_session(session_id)
                elif msg_type == "ping":
                    await ws.send_json({"type": "pong"})
                else:
                    logger.debug("Unknown WebSocket message type: %s", msg_type)

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception:
            logger.exception("WebSocket error")
        finally:
            await web_app.shutdown()

    return app
