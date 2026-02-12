"""Amplifier session management for the TUI.
Uses the distro Bridge as the single interface for session lifecycle.
No direct imports of amplifier-core or amplifier-foundation for session
creation -- everything goes through LocalBridge.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .log import logger
from .platform_info import (
    amplifier_projects_dir,
    reconstruct_project_path,
)

if TYPE_CHECKING:
    from amplifier_core import AmplifierSession


@dataclass
class SessionHandle:
    """Isolated per-session state, owned by SessionManager, keyed by conversation_id.

    Each handle carries its own session object, streaming callbacks, and token
    counters.  The Bridge's ``on_stream`` is bound to ``self._on_stream`` at
    session creation, so streaming events dispatch to THIS handle's callbacks
    with zero cross-talk between concurrent sessions.
    """

    conversation_id: str = ""

    # --- Amplifier session ---
    session: AmplifierSession | None = None
    session_id: str | None = None
    _bridge_handle: Any = None  # bridge.SessionHandle returned by LocalBridge

    # --- Per-session streaming callbacks ---
    on_content_block_start: Callable[[str, int], None] | None = None
    on_content_block_delta: Callable[[str, str], None] | None = None
    on_content_block_end: Callable[[str, str], None] | None = None
    on_tool_pre: Callable[[str, dict], None] | None = None
    on_tool_post: Callable[[str, dict, str], None] | None = None
    on_execution_start: Callable[[], None] | None = None
    on_execution_end: Callable[[], None] | None = None
    on_usage_update: Callable[[], None] | None = None

    # --- Per-session token usage ---
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_name: str = ""
    context_window: int = 0

    def reset_usage(self) -> None:
        """Reset token usage counters for a new session."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.model_name = ""
        self.context_window = 0

    def _on_stream(self, event: str, data: dict[str, Any]) -> None:
        """Dispatch bridge streaming events to THIS handle's callbacks.

        Exact port of the old SessionManager._on_stream, but reading/writing
        this handle's callbacks and token counters instead of a shared singleton.
        Called from the background thread where session.execute() runs.
        """
        if event == "content_block:start":
            if self.on_content_block_start:
                self.on_content_block_start(
                    data.get("block_type", "text"),
                    data.get("block_index", 0),
                )
        elif event == "content_block:delta":
            delta = (
                data.get("delta", "") or data.get("text", "") or data.get("content", "")
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


class SessionManager:
    """Manages Amplifier session lifecycle via the distro Bridge.

    Sessions are stored as SessionHandle objects in a registry, keyed by
    conversation_id. Backward-compat properties delegate to the "default"
    handle for single-session callers.
    """

    def __init__(self) -> None:
        self._bridge: Any | None = None
        self._handles: dict[str, SessionHandle] = {}
        self._default_conversation_id: str | None = None

    # ------------------------------------------------------------------
    # Registry API
    # ------------------------------------------------------------------

    def _default_handle(self) -> SessionHandle | None:
        if self._default_conversation_id is None:
            return None
        return self._handles.get(self._default_conversation_id)

    def get_handle(self, conversation_id: str) -> SessionHandle | None:
        """Look up a session handle by conversation_id."""
        return self._handles.get(conversation_id)

    @property
    def active_handles(self) -> dict[str, SessionHandle]:
        """Read-only snapshot of all registered handles."""
        return dict(self._handles)

    def remove_handle(self, conversation_id: str) -> None:
        """Remove a handle without ending the session."""
        self._handles.pop(conversation_id, None)
        if self._default_conversation_id == conversation_id:
            self._default_conversation_id = None

    # ------------------------------------------------------------------
    # Backward-compat properties (delegate to default handle)
    # ------------------------------------------------------------------

    @property
    def session(self) -> AmplifierSession | None:
        h = self._default_handle()
        return h.session if h else None

    @session.setter
    def session(self, value: AmplifierSession | None) -> None:
        h = self._default_handle()
        if h:
            h.session = value

    @property
    def session_id(self) -> str | None:
        h = self._default_handle()
        return h.session_id if h else None

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        h = self._default_handle()
        if h:
            h.session_id = value

    @property
    def total_input_tokens(self) -> int:
        h = self._default_handle()
        return h.total_input_tokens if h else 0

    @total_input_tokens.setter
    def total_input_tokens(self, value: int) -> None:
        h = self._default_handle()
        if h:
            h.total_input_tokens = value

    @property
    def total_output_tokens(self) -> int:
        h = self._default_handle()
        return h.total_output_tokens if h else 0

    @total_output_tokens.setter
    def total_output_tokens(self, value: int) -> None:
        h = self._default_handle()
        if h:
            h.total_output_tokens = value

    @property
    def model_name(self) -> str:
        h = self._default_handle()
        return h.model_name if h else ""

    @model_name.setter
    def model_name(self, value: str) -> None:
        h = self._default_handle()
        if h:
            h.model_name = value

    @property
    def context_window(self) -> int:
        h = self._default_handle()
        return h.context_window if h else 0

    @context_window.setter
    def context_window(self, value: int) -> None:
        h = self._default_handle()
        if h:
            h.context_window = value

    def reset_usage(self) -> None:
        """Reset token usage counters on the default handle."""
        h = self._default_handle()
        if h:
            h.reset_usage()

    def switch_model(self, model_name: str) -> bool:
        """Switch model on the default handle (backward compat)."""
        h = self._default_handle()
        if h:
            return self._switch_model_on_handle(h, model_name)
        return False

    def get_provider_models(self) -> list[tuple[str, str]]:
        """Return (model_name, provider_module) pairs from default handle."""
        h = self._default_handle()
        if not h or not h.session:
            return []
        return self._get_provider_models_from_session(h.session)

    # ------------------------------------------------------------------
    # Model helpers (static, operate on handle or session)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_model_info_on_handle(handle: SessionHandle) -> None:
        """Extract model name and context window from the handle's session."""
        if not handle.session:
            return
        try:
            providers = handle.session.coordinator.get("providers") or {}
            for prov in providers.values():
                if hasattr(prov, "default_model"):
                    handle.model_name = prov.default_model
                elif hasattr(prov, "model"):
                    handle.model_name = prov.model
                if hasattr(prov, "get_info"):
                    info = prov.get_info()
                    if hasattr(info, "defaults") and isinstance(info.defaults, dict):
                        handle.context_window = info.defaults.get("context_window", 0)
                break  # Use the first provider
        except Exception:  # noqa: BLE001
            logger.debug("Failed to extract model info", exc_info=True)

    @staticmethod
    def _switch_model_on_handle(handle: SessionHandle, model_name: str) -> bool:
        """Switch the active model on a handle's session provider."""
        if not handle.session:
            return False
        try:
            providers = handle.session.coordinator.get("providers") or {}
            for prov in providers.values():
                if hasattr(prov, "default_model"):
                    prov.default_model = model_name
                    handle.model_name = model_name
                    return True
                if hasattr(prov, "model"):
                    prov.model = model_name
                    handle.model_name = model_name
                    return True
            return False
        except Exception:  # noqa: BLE001
            logger.debug("Failed to switch model to %s", model_name, exc_info=True)
            return False

    @staticmethod
    def _get_provider_models_from_session(
        session: AmplifierSession,
    ) -> list[tuple[str, str]]:
        """Return (model_name, provider_module) pairs from a session."""
        results: list[tuple[str, str]] = []
        try:
            providers = session.coordinator.get("providers") or {}
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

    # ------------------------------------------------------------------
    # Session lifecycle (via Bridge)
    # ------------------------------------------------------------------

    async def start_new_session(
        self,
        conversation_id: str | None = None,
        cwd: Path | None = None,
        model_override: str = "",
    ) -> SessionHandle:
        """Start a new Amplifier session, returning its SessionHandle.

        If conversation_id is None, an ID is auto-generated and this handle
        becomes the default (backward compat).
        """
        from amplifier_distro.bridge import BridgeConfig

        auto_generated = conversation_id is None
        if auto_generated:
            conversation_id = str(uuid.uuid4())

        if cwd is None:
            cwd = Path.cwd()

        handle = SessionHandle(conversation_id=conversation_id)

        bridge = self._get_bridge()
        config = BridgeConfig(
            working_dir=cwd,
            run_preflight=False,
            on_stream=handle._on_stream,  # per-handle binding
        )
        bridge_handle = await bridge.create_session(config)
        handle._bridge_handle = bridge_handle
        handle.session = bridge_handle._session
        handle.session_id = bridge_handle.session_id

        if model_override:
            self._switch_model_on_handle(handle, model_override)

        handle.reset_usage()
        self._extract_model_info_on_handle(handle)

        self._handles[conversation_id] = handle

        if auto_generated:
            self._default_conversation_id = conversation_id

        return handle

    async def resume_session(
        self,
        session_id: str,
        conversation_id: str | None = None,
        model_override: str = "",
        working_dir: Path | None = None,
    ) -> SessionHandle:
        """Resume an existing Amplifier session, returning its SessionHandle.

        If conversation_id is None, an ID is auto-generated and this handle
        becomes the default (backward compat).
        """
        from amplifier_distro.bridge import BridgeConfig

        auto_generated = conversation_id is None
        if auto_generated:
            conversation_id = str(uuid.uuid4())

        handle = SessionHandle(conversation_id=conversation_id)

        bridge = self._get_bridge()
        config = BridgeConfig(
            working_dir=working_dir or Path.cwd(),
            run_preflight=False,
            on_stream=handle._on_stream,  # per-handle binding
        )
        bridge_handle = await bridge.resume_session(session_id, config)
        handle._bridge_handle = bridge_handle
        handle.session = bridge_handle._session
        handle.session_id = bridge_handle.session_id

        if model_override:
            self._switch_model_on_handle(handle, model_override)

        handle.reset_usage()
        self._extract_model_info_on_handle(handle)

        self._handles[conversation_id] = handle

        if auto_generated:
            self._default_conversation_id = conversation_id

        return handle

    async def end_session(self, conversation_id: str | None = None) -> None:
        """End a session by conversation_id (or the default)."""
        cid = conversation_id or self._default_conversation_id
        if cid is None:
            return
        handle = self._handles.get(cid)
        if handle is None:
            return

        if not handle.session:
            self._handles.pop(cid, None)
            if self._default_conversation_id == cid:
                self._default_conversation_id = None
            return

        try:
            if handle._bridge_handle:
                bridge = self._get_bridge()
                await bridge.end_session(handle._bridge_handle)
            else:
                # Fallback: direct cleanup when no bridge handle
                try:
                    hooks = handle.session.coordinator.get("hooks")
                    if hooks:
                        from amplifier_core.events import SESSION_END  # type: ignore[import-not-found]

                        await hooks.emit(SESSION_END, {"session_id": handle.session_id})
                except Exception:  # noqa: BLE001
                    logger.debug("Failed to emit SESSION_END", exc_info=True)
                try:
                    await handle.session.cleanup()
                except Exception:  # noqa: BLE001
                    logger.debug("Failed to clean up session", exc_info=True)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to end session via bridge", exc_info=True)

        handle.session = None
        handle._bridge_handle = None
        self._handles.pop(cid, None)
        if self._default_conversation_id == cid:
            self._default_conversation_id = None

    async def send_message(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> str:
        """Send a message to a specific conversation's session."""
        cid = conversation_id or self._default_conversation_id
        if cid is None:
            raise ValueError("No conversation_id and no default session")
        handle = self._handles.get(cid)
        if handle is None or handle.session is None:
            raise ValueError(f"No active session for conversation {cid!r}")
        response = await handle.session.execute(message)
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

                # Use transcript mtime for accurate "last activity" sorting.
                mtime = transcript_path.stat().st_mtime
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
                if session_dir.name == session_id or session_dir.name.startswith(
                    session_id
                ):
                    transcript = session_dir / "transcript.jsonl"
                    if transcript.exists():
                        return transcript
        return None
