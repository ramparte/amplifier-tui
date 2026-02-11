"""Web frontend for amplifier-tui."""


def main(port: int = 8765, resume_session_id: str | None = None) -> None:
    """Launch the web server."""
    import uvicorn

    from .server import create_app

    app = create_app(resume_session_id=resume_session_id)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
