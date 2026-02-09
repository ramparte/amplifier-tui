"""Session name and title persistence store."""

from __future__ import annotations

import json
from pathlib import Path

from ._base import JsonStore


class SessionNameStore(JsonStore):
    """Custom session names (``{session_id: name}``)."""

    def __init__(self, names_path: Path, titles_path: Path) -> None:
        super().__init__(names_path)
        self.titles_path = titles_path

    # -- names ----------------------------------------------------------------

    def load_names(self) -> dict[str, str]:
        """Load custom session names from disk."""
        return self.load_raw()  # type: ignore[return-value]

    def save_name(self, session_id: str, name: str) -> None:
        """Save a custom session name."""
        names = self.load_names()
        names[session_id] = name
        self.save_raw(names)

    def remove_name(self, session_id: str) -> None:
        """Remove a custom session name."""
        try:
            names = self.load_names()
            if session_id in names:
                del names[session_id]
                self.save_raw(names)
        except Exception:
            pass

    # -- titles ---------------------------------------------------------------

    def load_titles(self) -> dict[str, str]:
        """Load session titles from disk."""
        try:
            if self.titles_path.exists():
                return json.loads(self.titles_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save_title(self, session_id: str, title: str | None) -> None:
        """Save or clear a session title, keeping at most 200 entries."""
        try:
            titles = self.load_titles()
            if title:
                titles[session_id] = title
            elif session_id in titles:
                del titles[session_id]
            # Keep last 200 titles
            if len(titles) > 200:
                keys = list(titles.keys())
                for k in keys[:-200]:
                    del titles[k]
            self.titles_path.parent.mkdir(parents=True, exist_ok=True)
            self.titles_path.write_text(
                json.dumps(titles, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def title_for(self, session_id: str) -> str:
        """Load the title for a specific session (empty string if none)."""
        return self.load_titles().get(session_id, "")
