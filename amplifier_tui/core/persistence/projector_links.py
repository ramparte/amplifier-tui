"""Session-to-Projector-project link store."""

from __future__ import annotations

from pathlib import Path

from ._base import JsonStore


class ProjectorLinkStore(JsonStore):
    """
    Maps session_id -> projector_project_name.

    Used when a user manually associates a session with a Projector project
    (e.g., /projector link <project>), overriding auto-detection.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def link(self, session_id: str, project_name: str) -> None:
        data = self.load_raw()
        if not isinstance(data, dict):
            data = {}
        data[session_id] = project_name
        self.save_raw(data, sort_keys=True)

    def unlink(self, session_id: str) -> None:
        data = self.load_raw()
        if not isinstance(data, dict):
            return
        data.pop(session_id, None)
        self.save_raw(data, sort_keys=True)

    def get_project(self, session_id: str) -> str | None:
        data = self.load_raw()
        if not isinstance(data, dict):
            return None
        return data.get(session_id)

    def sessions_for_project(self, project_name: str) -> list[str]:
        data = self.load_raw()
        if not isinstance(data, dict):
            return []
        return [sid for sid, pname in data.items() if pname == project_name]
