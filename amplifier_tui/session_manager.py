"""Amplifier session management for the TUI."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .log import logger

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
                    except OSError:
                        logger.debug(
                            "Failed to process .pth file %s", pth_file, exc_info=True
                        )
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
        self.on_content_block_start: Callable[[str, int], None] | None = None
        self.on_content_block_delta: Callable[[str, str], None] | None = None
        self.on_content_block_end: Callable[[str, str], None] | None = None
        self.on_tool_pre: Callable[[str, dict], None] | None = None
        self.on_tool_post: Callable[[str, dict, str], None] | None = None
        self.on_execution_start: Callable[[], None] | None = None
        self.on_execution_end: Callable[[], None] | None = None

        # Token usage tracking
        self.on_usage_update: Callable[[], None] | None = None
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.model_name: str = ""
        self.context_window: int = 0

    def reset_usage(self) -> None:
        """Reset token usage counters for a new session."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.model_name = ""
        self.context_window = 0

    def _extract_model_info(self) -> None:
        """Extract model name and context window from the session's provider."""
        if not self.session:
            return
        try:
            providers = self.session.coordinator.get("providers") or {}
            for _name, prov in providers.items():
                if hasattr(prov, "default_model"):
                    self.model_name = prov.default_model
                elif hasattr(prov, "model"):
                    self.model_name = prov.model
                if hasattr(prov, "get_info"):
                    info = prov.get_info()
                    if hasattr(info, "defaults") and isinstance(info.defaults, dict):
                        self.context_window = info.defaults.get("context_window", 0)
                break  # Use the first provider
        except Exception:
            logger.debug("Failed to extract model info", exc_info=True)

    def switch_model(self, model_name: str) -> bool:
        """Switch the active model on the current session's provider.

        Mutates the provider's ``default_model`` attribute so the next LLM
        call uses *model_name*.  Returns ``True`` on success.
        """
        if not self.session:
            return False
        try:
            providers = self.session.coordinator.get("providers") or {}
            for _name, prov in providers.items():
                if hasattr(prov, "default_model"):
                    prov.default_model = model_name
                    self.model_name = model_name
                    return True
                if hasattr(prov, "model"):
                    prov.model = model_name
                    self.model_name = model_name
                    return True
            return False
        except Exception:
            logger.debug("Failed to switch model to %s", model_name, exc_info=True)
            return False

    def get_provider_models(self) -> list[tuple[str, str]]:
        """Return ``(model_name, provider_module)`` pairs from the session.

        Falls back to an empty list when no session is active.
        """
        results: list[tuple[str, str]] = []
        if not self.session:
            return results
        try:
            providers = self.session.coordinator.get("providers") or {}
            for name, prov in providers.items():
                model = ""
                if hasattr(prov, "default_model"):
                    model = prov.default_model
                elif hasattr(prov, "model"):
                    model = prov.model
                if model:
                    results.append((model, name))
        except Exception:
            logger.debug("Failed to get provider models", exc_info=True)
        return results

    @staticmethod
    def _apply_model_override(config_data: dict, model_override: str) -> None:
        """Patch *config_data* providers to use *model_override*."""
        for provider in config_data.get("providers", []):
            cfg = provider.get("config", {})
            if "default_model" in cfg:
                cfg["default_model"] = model_override
                # Promote to highest priority so this provider is selected
                cfg["priority"] = 0
                return
        # Fallback: patch the first provider that has any config
        for provider in config_data.get("providers", []):
            cfg = provider.get("config")
            if isinstance(cfg, dict):
                cfg["default_model"] = model_override
                cfg["priority"] = 0
                return

    async def start_new_session(
        self,
        cwd: Path | None = None,
        model_override: str = "",
    ) -> None:
        """Start a new Amplifier session.

        Parameters
        ----------
        cwd:
            Working directory for the session.
        model_override:
            If non-empty, override the provider's default model before
            session creation.
        """
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

        if model_override:
            self._apply_model_override(config_data, model_override)

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

        # Register streaming hooks and extract model info
        self._register_hooks()
        self.reset_usage()
        self._extract_model_info()

    async def resume_session(
        self,
        session_id: str,
        model_override: str = "",
    ) -> None:
        """Resume an existing Amplifier session.

        Parameters
        ----------
        session_id:
            The session to resume.
        model_override:
            If non-empty, override the provider's default model.
        """
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

        if model_override:
            self._apply_model_override(config_data, model_override)

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

        # Register streaming hooks and extract model info
        self._register_hooks()
        self.reset_usage()
        self._extract_model_info()

    def _register_hooks(self) -> None:
        """Register hooks on the session for streaming UI updates."""
        if not self.session:
            return

        try:
            from amplifier_core.models import HookResult
        except ImportError:
            return

        hooks = self.session.coordinator.hooks

        async def on_block_start(event: str, data: dict) -> Any:
            block_type = data.get("block_type", "text")
            block_index = data.get("block_index", 0)
            if self.on_content_block_start:
                self.on_content_block_start(block_type, block_index)
            return HookResult(action="continue")

        async def on_block_delta(event: str, data: dict) -> Any:
            block_type = data.get("block_type", "text")
            delta = (
                data.get("delta", "") or data.get("text", "") or data.get("content", "")
            )
            if delta and self.on_content_block_delta:
                self.on_content_block_delta(block_type, delta)
            return HookResult(action="continue")

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
                    str(result)[:2000],  # Truncate long results (collapsed by default)
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

        async def on_llm_response(event: str, data: dict) -> Any:
            usage = data.get("usage", {})
            if usage:
                self.total_input_tokens += usage.get("input", 0)
                self.total_output_tokens += usage.get("output", 0)
            model = data.get("model", "")
            if model and not self.model_name:
                self.model_name = model
            if self.on_usage_update:
                self.on_usage_update()
            return HookResult(action="continue")

        hooks.register("content_block:start", on_block_start, name="tui-block-start")
        hooks.register("content_block:delta", on_block_delta, name="tui-block-delta")
        hooks.register("content_block:end", on_block_end, name="tui-content")
        hooks.register("tool:pre", on_tool_start, name="tui-tool-pre")
        hooks.register("tool:post", on_tool_end, name="tui-tool-post")
        hooks.register("execution:start", on_exec_start, name="tui-exec-start")
        hooks.register("execution:end", on_exec_end, name="tui-exec-end")
        hooks.register("llm:response", on_llm_response, name="tui-usage")

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
        """Get the path to a session's transcript file.

        Searches all project directories for the session.
        A session dir may exist in multiple projects (e.g. sub-sessions),
        so we verify transcript.jsonl actually exists before returning.
        """
        sessions_dir = Path.home() / ".amplifier" / "projects"

        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if sessions_subdir.exists():
                transcript = sessions_subdir / session_id / "transcript.jsonl"
                if transcript.exists():
                    return transcript

        raise ValueError(f"Session {session_id} not found")

    async def end_session(self) -> None:
        """End the current session cleanly (emit SESSION_END + cleanup).

        This mirrors what the CLI does in its finally block.
        Must be called before the app exits or the last turn won't persist.
        """
        if not self.session:
            return

        try:
            hooks = self.session.coordinator.get("hooks")
            if hooks:
                from amplifier_core.events import SESSION_END

                await hooks.emit(SESSION_END, {"session_id": self.session_id})
        except Exception:
            logger.debug("Failed to emit SESSION_END", exc_info=True)

        try:
            await self.session.cleanup()
        except Exception:
            logger.debug("Failed to clean up session", exc_info=True)

        self.session = None

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
            except (ValueError, IndexError):
                logger.debug(
                    "Failed to parse project path from %s", raw_name, exc_info=True
                )
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
                    except (OSError, json.JSONDecodeError):
                        logger.debug(
                            "Failed to read session metadata %s",
                            metadata_path,
                            exc_info=True,
                        )

                results.append(info)

        results.sort(key=lambda x: x["mtime"], reverse=True)
        return results[:limit]
