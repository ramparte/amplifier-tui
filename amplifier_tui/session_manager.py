"""Amplifier session management for the TUI.

Uses the distro Bridge as the single interface for session lifecycle.
No direct imports of amplifier-core or amplifier-foundation for session
creation -- everything goes through LocalBridge.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .log import logger
from .platform import (
    amplifier_projects_dir,
    reconstruct_project_path,
)

if TYPE_CHECKING:
    from amplifier_core import AmplifierSession


class SessionManager:
    """Manages Amplifier session lifecycle via the distro Bridge."""

    def __init__(self):
        self.session: AmplifierSession | None = None
        self.session_id: str | None = None

        # Bridge internals
        self._bridge: Any | None = None
        self._handle: Any | None = None

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
            for prov in providers.values():
                if hasattr(prov, "default_model"):
                    self.model_name = prov.default_model
                elif hasattr(prov, "model"):
                    self.model_name = prov.model
                if hasattr(prov, "get_info"):
                    info = prov.get_info()
                    if hasattr(info, "defaults") and isinstance(info.defaults, dict):
                        self.context_window = info.defaults.get("context_window", 0)
                break  # Use the first provider
        except Exception:  # noqa: BLE001
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
            for prov in providers.values():
                if hasattr(prov, "default_model"):
                    prov.default_model = model_name
                    self.model_name = model_name
                    return True
                if hasattr(prov, "model"):
                    prov.model = model_name
                    self.model_name = model_name
                    return True
            return False
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            logger.debug("Failed to get provider models", exc_info=True)
        return results

    # ------------------------------------------------------------------
    # Bridge helpers
    # ------------------------------------------------------------------

    def _get_bridge(self) -> Any:
        """Lazily create the LocalBridge singleton."""
        if self._bridge is None:
            from amplifier_distro.bridge import LocalBridge

            self._bridge = LocalBridge()
        return self._bridge

    def _on_stream(self, event: str, data: dict[str, Any]) -> None:
        """Dispatch bridge streaming events to the TUI callbacks."""
        if event == "content_block:start":
            if self.on_content_block_start:
                self.on_content_block_start(
                    data.get("block_type", "text"),
                    data.get("block_index", 0),
                )
        elif event == "content_block:delta":
            delta = (
                data.get("delta", "")
                or data.get("text", "")
                or data.get("content", "")
            )
            if delta and self.on_content_block_delta:
                self.on_content_block_delta(data.get("block_type", "text"), delta)
        elif event == "content_block:end":
            block = data.get("block", {})
            block_type = block.get("type", "")
            if block_type == "text" and self.on_content_block_end:
                self.on_content_block_end("text", block.get("text", ""))
            elif block_type in ("thinking", "reasoning") and self.on_content_block_end:
                text = block.get("thinking", "") or block.get("text", "")
                self.on_content_block_end("thinking", text)
        elif event == "tool:pre":
            if self.on_tool_pre:
                self.on_tool_pre(
                    data.get("tool_name", "unknown"), data.get("tool_input", {})
                )
        elif event == "tool:post":
            if self.on_tool_post:
                result = data.get("result", "")
                if isinstance(result, dict):
                    result = json.dumps(result, indent=2)
                self.on_tool_post(
                    data.get("tool_name", "unknown"),
                    data.get("tool_input", {}),
                    str(result)[:2000],
                )
        elif event == "execution:start":
            if self.on_execution_start:
                self.on_execution_start()
        elif event == "execution:end":
            if self.on_execution_end:
                self.on_execution_end()
        elif event == "llm:response":
            usage = data.get("usage", {})
            if usage:
                self.total_input_tokens += usage.get("input", 0)
                self.total_output_tokens += usage.get("output", 0)
            model = data.get("model", "")
            if model and not self.model_name:
                self.model_name = model
            if self.on_usage_update:
                self.on_usage_update()

    # ------------------------------------------------------------------
    # Session lifecycle (via Bridge)
    # ------------------------------------------------------------------

    async def start_new_session(
        self,
        cwd: Path | None = None,
        model_override: str = "",
    ) -> None:
        """Start a new Amplifier session via the distro Bridge.

        Parameters
        ----------
        cwd:
            Working directory for the session.
        model_override:
            If non-empty, override the provider's default model after
            session creation.
        """
        from amplifier_distro.bridge import BridgeConfig

        if cwd is None:
            cwd = Path.cwd()

        bridge = self._get_bridge()
        config = BridgeConfig(
            working_dir=cwd,
            run_preflight=False,
            on_stream=self._on_stream,
        )

        handle = await bridge.create_session(config)
        self._handle = handle
        self.session = handle._session
        self.session_id = handle.session_id

        if model_override:
            self.switch_model(model_override)

        self.reset_usage()
        self._extract_model_info()

    async def resume_session(
        self,
        session_id: str,
        model_override: str = "",
    ) -> None:
        """Resume an existing Amplifier session via the distro Bridge.

        Parameters
        ----------
        session_id:
            The session to resume.
        model_override:
            If non-empty, override the provider's default model.
        """
        from amplifier_distro.bridge import BridgeConfig

        bridge = self._get_bridge()
        config = BridgeConfig(
            working_dir=Path.cwd(),
            run_preflight=False,
            on_stream=self._on_stream,
        )

        handle = await bridge.resume_session(session_id, config)
        self._handle = handle
        self.session = handle._session
        self.session_id = handle.session_id

        if model_override:
            self.switch_model(model_override)

        self.reset_usage()
        self._extract_model_info()

    async def end_session(self) -> None:
        """End the current session cleanly via the Bridge.

        Emits SESSION_END, writes handoff, and cleans up resources.
        """
        if not self.session:
            return

        try:
            if self._handle:
                bridge = self._get_bridge()
                await bridge.end_session(self._handle)
            else:
                # Fallback: direct cleanup when no handle (e.g. tab-swapped session)
                try:
                    hooks = self.session.coordinator.get("hooks")
                    if hooks:
                        from amplifier_core.events import SESSION_END  # type: ignore[import-not-found]

                        await hooks.emit(
                            SESSION_END, {"session_id": self.session_id}
                        )
                except Exception:  # noqa: BLE001
                    logger.debug("Failed to emit SESSION_END", exc_info=True)
                try:
                    await self.session.cleanup()
                except Exception:  # noqa: BLE001
                    logger.debug("Failed to clean up session", exc_info=True)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to end session via bridge", exc_info=True)

        self.session = None
        self._handle = None

    async def send_message(self, message: str) -> str:
        """Send a message to the current session."""
        if not self.session:
            raise ValueError("No active session")
        response = await self.session.execute(message)
        return response

    # ------------------------------------------------------------------
    # Session discovery (local filesystem -- no bridge needed)
    # ------------------------------------------------------------------

    @staticmethod
    def list_all_sessions(limit: int = 50) -> list[dict]:
        """List all available sessions with metadata.

        Returns list of dicts with:
            session_id, project, project_path, mtime, date_str, name, description
        Sorted by mtime descending (most recent first).
        Only includes root sessions (skips sub-sessions with _ in ID).
        """
        sessions_dir = amplifier_projects_dir()
        if not sessions_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue

            # Reconstruct the original path from the directory name
            raw_name = project_dir.name
            try:
                project_path = reconstruct_project_path(raw_name)
                project_label = Path(project_path).name
            except (ValueError, IndexError):
                logger.debug(
                    "Failed to parse project path from %s", raw_name, exc_info=True
                )
                project_path = raw_name
                project_label = raw_name[:20]

            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Skip sub-sessions (they have _ in the session ID)
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
                    "date_str": datetime.fromtimestamp(mtime).strftime(
                        "%m/%d %H:%M"
                    ),
                    "name": "",
                    "description": "",
                }

                # Read metadata for name and description
                metadata_path = session_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path, encoding="utf-8") as f:
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

    def _find_most_recent_session(self) -> str:
        """Return the session_id of the most recently modified session.

        Raises ``ValueError`` when no sessions exist on disk.
        """
        sessions = self.list_all_sessions(limit=1)
        if not sessions:
            raise ValueError("No sessions found")
        return sessions[0]["session_id"]

    @staticmethod
    def get_session_transcript_path(session_id: str) -> Path | None:
        """Locate the ``transcript.jsonl`` file for *session_id*.

        Scans all project directories under ``~/.amplifier/projects/``.
        Supports prefix matching (e.g. first 8 chars of a UUID).
        """
        projects_dir = amplifier_projects_dir()
        if not projects_dir.exists():
            return None

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue
            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                if (
                    session_dir.name == session_id
                    or session_dir.name.startswith(session_id)
                ):
                    transcript = session_dir / "transcript.jsonl"
                    if transcript.exists():
                        return transcript
        return None
