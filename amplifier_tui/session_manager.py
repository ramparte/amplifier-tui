"""Amplifier session management for the TUI."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

# Add the global Amplifier installation to sys.path if it exists
# This allows us to import from amplifier_core/foundation even though they're not in our venv
_amplifier_site_packages = Path.home() / ".local/share/uv/tools/amplifier/lib"
if _amplifier_site_packages.exists():
    # Find the python3.x directory
    for python_dir in _amplifier_site_packages.iterdir():
        if python_dir.name.startswith("python3"):
            site_packages = python_dir / "site-packages"
            if site_packages.exists() and str(site_packages) not in sys.path:
                sys.path.insert(0, str(site_packages))

                # Also process .pth files to find amplifier packages
                # (amplifier_foundation and others are installed via .pth files)
                for pth_file in site_packages.glob("*.pth"):
                    try:
                        with open(pth_file, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                # Skip comments and empty lines
                                if line and not line.startswith("#"):
                                    pth_path = Path(line)
                                    if (
                                        pth_path.exists()
                                        and str(pth_path) not in sys.path
                                    ):
                                        sys.path.insert(0, str(pth_path))
                    except Exception:
                        # Skip problematic .pth files
                        pass
                break

if TYPE_CHECKING:
    from amplifier_core import AmplifierSession


class SessionManager:
    """Manages Amplifier session lifecycle."""

    def __init__(self):
        self.session: AmplifierSession | None = None
        self.session_id: str | None = None
        self.prepared_bundle = None

        # Streaming callbacks - set by the app before execute()
        self.on_content_block_end: Callable[[str, str], None] | None = None
        self.on_tool_pre: Callable[[str, dict], None] | None = None
        self.on_tool_post: Callable[[str, dict, str], None] | None = None
        self.on_execution_start: Callable[[], None] | None = None
        self.on_execution_end: Callable[[], None] | None = None

    async def start_new_session(self, cwd: Path | None = None) -> None:
        """Start a new Amplifier session."""
        if cwd is None:
            cwd = Path.cwd()

        from amplifier_app_cli.session_runner import (
            create_initialized_session,
            SessionConfig,
        )
        from amplifier_app_cli.runtime.config import resolve_bundle_config
        from amplifier_app_cli.lib.settings import AppSettings
        from rich.console import Console

        self.session_id = str(uuid.uuid4())

        app_settings = AppSettings()
        bundle_name = app_settings.get_active_bundle()

        config_data, self.prepared_bundle = await resolve_bundle_config(
            bundle_name=bundle_name,
            app_settings=app_settings,
            console=None,
        )

        session_config = SessionConfig(
            config=config_data,
            search_paths=[cwd],
            verbose=False,
            session_id=self.session_id,
            bundle_name=bundle_name,
            prepared_bundle=self.prepared_bundle,
        )

        console = Console()
        initialized = await create_initialized_session(session_config, console)
        self.session = initialized.session

        # Register streaming hooks
        self._register_hooks()

    async def resume_session(self, session_id: str) -> None:
        """Resume an existing Amplifier session."""
        from amplifier_app_cli.session_runner import (
            create_initialized_session,
            SessionConfig,
        )
        from amplifier_app_cli.runtime.config import resolve_bundle_config
        from amplifier_app_cli.lib.settings import AppSettings
        from rich.console import Console

        app_settings = AppSettings()
        bundle_name = app_settings.get_active_bundle()

        config_data, self.prepared_bundle = await resolve_bundle_config(
            bundle_name=bundle_name,
            app_settings=app_settings,
            console=None,
        )

        # Load the transcript
        transcript_path = self.get_session_transcript_path(session_id)
        transcript = self._load_transcript(transcript_path)

        self.session_id = session_id

        session_config = SessionConfig(
            config=config_data,
            search_paths=[Path.cwd()],
            verbose=False,
            session_id=session_id,
            bundle_name=bundle_name,
            prepared_bundle=self.prepared_bundle,
            initial_transcript=transcript,
        )

        console = Console()
        initialized = await create_initialized_session(session_config, console)
        self.session = initialized.session

        # Register streaming hooks
        self._register_hooks()

    def _register_hooks(self) -> None:
        """Register hooks on the session for streaming UI updates."""
        if not self.session:
            return

        try:
            from amplifier_core.models import HookResult
        except ImportError:
            return

        hooks = self.session.coordinator.hooks

        async def on_block_end(event: str, data: dict) -> Any:
            block = data.get("block", {})
            block_type = block.get("type", "")
            if block_type == "text" and self.on_content_block_end:
                self.on_content_block_end("text", block.get("text", ""))
            elif block_type in ("thinking", "reasoning") and self.on_content_block_end:
                text = block.get("thinking", "") or block.get("text", "")
                self.on_content_block_end("thinking", text)
            return HookResult(action="continue")

        async def on_tool_start(event: str, data: dict) -> Any:
            if self.on_tool_pre:
                self.on_tool_pre(
                    data.get("tool_name", "unknown"), data.get("tool_input", {})
                )
            return HookResult(action="continue")

        async def on_tool_end(event: str, data: dict) -> Any:
            if self.on_tool_post:
                result = data.get("result", "")
                if isinstance(result, dict):
                    result = json.dumps(result, indent=2)
                self.on_tool_post(
                    data.get("tool_name", "unknown"),
                    data.get("tool_input", {}),
                    str(result)[:500],  # Truncate long results
                )
            return HookResult(action="continue")

        async def on_exec_start(event: str, data: dict) -> Any:
            if self.on_execution_start:
                self.on_execution_start()
            return HookResult(action="continue")

        async def on_exec_end(event: str, data: dict) -> Any:
            if self.on_execution_end:
                self.on_execution_end()
            return HookResult(action="continue")

        hooks.register("content_block:end", on_block_end, name="tui-content")
        hooks.register("tool:pre", on_tool_start, name="tui-tool-pre")
        hooks.register("tool:post", on_tool_end, name="tui-tool-post")
        hooks.register("execution:start", on_exec_start, name="tui-exec-start")
        hooks.register("execution:end", on_exec_end, name="tui-exec-end")

    def _load_transcript(self, transcript_path: Path) -> list[dict]:
        """Load messages from a transcript file."""
        messages = []
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))
        return messages

    def _find_most_recent_session(self) -> str:
        """Find the most recent session ID."""
        sessions = self.list_all_sessions()
        if not sessions:
            raise ValueError("No sessions found")
        return sessions[0]["session_id"]

    def get_session_transcript_path(self, session_id: str) -> Path:
        """Get the path to a session's transcript file."""
        sessions_dir = Path.home() / ".amplifier" / "projects"

        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if sessions_subdir.exists():
                session_dir = sessions_subdir / session_id
                if session_dir.exists():
                    return session_dir / "transcript.jsonl"

        raise ValueError(f"Session {session_id} not found")

    async def send_message(self, message: str) -> str:
        """Send a message to the current session."""
        if not self.session:
            raise ValueError("No active session")
        response = await self.session.execute(message)
        return response

    @staticmethod
    def list_all_sessions(limit: int = 50) -> list[dict]:
        """List all available sessions with metadata.

        Returns list of dicts with:
            session_id, project, project_path, mtime, date_str, name, description
        Sorted by mtime descending (most recent first).
        Only includes root sessions (skips sub-sessions with _ in ID).
        """
        sessions_dir = Path.home() / ".amplifier" / "projects"
        if not sessions_dir.exists():
            return []

        results = []
        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue

            # Reconstruct the original path from the directory name
            # e.g. -home-samschillace-dev-ANext-MyProject -> /home/samschillace/dev/ANext/MyProject
            raw_name = project_dir.name
            try:
                path_str = "/" + raw_name[1:].replace("-", "/")
                project_path = path_str
                project_label = Path(path_str).name
            except Exception:
                project_path = raw_name
                project_label = raw_name[:20]

            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Skip sub-sessions (they have _ in the session ID like uuid_agent-name)
                if "_" in session_dir.name:
                    continue
                transcript_path = session_dir / "transcript.jsonl"
                if not transcript_path.exists():
                    continue

                mtime = session_dir.stat().st_mtime
                info: dict[str, Any] = {
                    "session_id": session_dir.name,
                    "project": project_label,
                    "project_path": project_path,
                    "mtime": mtime,
                    "date_str": datetime.fromtimestamp(mtime).strftime("%m/%d %H:%M"),
                    "name": "",
                    "description": "",
                }

                # Read metadata for name and description
                metadata_path = session_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                            info["name"] = meta.get("name", "")
                            info["description"] = meta.get("description", "")
                    except Exception:
                        pass

                results.append(info)

        results.sort(key=lambda x: x["mtime"], reverse=True)
        return results[:limit]
