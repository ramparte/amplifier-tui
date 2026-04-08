"""Amplifier session management for the TUI.

Uses the same pattern as amplifier-app-cli: prepare the bundle ONCE at startup,
then create sessions directly from the PreparedBundle.  This avoids the
LocalBridge's per-session ``bundle.prepare()`` call which runs ``uv pip install
-e`` every time (~5-30 s depending on cache state).
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
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

    # --- Steering injection queue ---
    _pending_injects: deque[str] = field(default_factory=deque)

    def reset_usage(self) -> None:
        """Reset token usage counters for a new session."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.model_name = ""
        self.context_window = 0

    def inject_user_message(self, message: str) -> None:
        """Queue a steering message for injection at the next pause point."""
        self._pending_injects.append(message)

    def pop_pending_inject(self) -> str | None:
        """Pop the next pending injection, or None if empty."""
        if self._pending_injects:
            return self._pending_injects.popleft()
        return None

    @property
    def has_pending_inject(self) -> bool:
        """True if there are pending steering messages."""
        return len(self._pending_injects) > 0

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


# ---------------------------------------------------------------------------
# Path helpers (same as distro bridge uses)
# ---------------------------------------------------------------------------

_AMPLIFIER_HOME = Path("~/.amplifier").expanduser()
_PROJECTS_DIR = "projects"
_TRANSCRIPT_FILENAME = "transcript.jsonl"


def _encode_cwd(cwd: Path) -> str:
    """Encode a working directory into a safe project-folder name."""
    try:
        from amplifier_distro.bridge import _encode_cwd as _distro_encode

        return _distro_encode(cwd)
    except ImportError:
        # Fallback: replicate the standard encoding
        return str(cwd).replace("/", "_").lstrip("_")


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Manages Amplifier session lifecycle via the CLI pattern.

    Prepares the bundle ONCE, then creates sessions directly from the
    PreparedBundle -- no per-session ``bundle.prepare()`` cost.
    """

    def __init__(self) -> None:
        self._prepared: Any | None = None  # PreparedBundle, cached
        self._bridge: Any | None = None  # LocalBridge, for helpers only
        self._handles: dict[str, SessionHandle] = {}
        self._default_conversation_id: str | None = None

    # ------------------------------------------------------------------
    # Bundle preparation (ONE-TIME, like the CLI)
    # ------------------------------------------------------------------

    async def prepare_bundle(self) -> None:
        """Load and prepare the bundle once.

        This is the expensive operation (triggers ``uv pip install``).
        Call during app startup, not per-session.

        Also injects providers into the mount plan (API keys, default models)
        since user bundles typically omit the ``providers:`` section and rely
        on the app layer to supply it.
        """
        if self._prepared is not None:
            return  # Already prepared

        from amplifier_foundation import load_bundle

        # Resolve bundle ref the same way the bridge does
        bridge = self._get_bridge()
        bundle_ref = bridge._resolve_distro_bundle(None)
        logger.info("Preparing bundle: %s", bundle_ref)

        bundle = await load_bundle(bundle_ref)
        self._prepared = await bundle.prepare()

        # Inject providers into the mount plan (same as bridge does).
        # This adds the default Anthropic/OpenAI provider from distro.yaml
        # when the user's bundle doesn't carry its own providers section.
        try:
            bridge._inject_providers(self._prepared.mount_plan, None)
        except Exception:  # noqa: BLE001
            logger.warning("Provider injection failed", exc_info=True)

        has_providers = bool(self._prepared.mount_plan.get("providers"))
        logger.info("Bundle prepared successfully (has_providers=%s)", has_providers)

    def has_providers(self) -> bool:
        """Check whether the prepared mount plan includes any providers."""
        if self._prepared is None:
            return False
        providers = self._prepared.mount_plan.get("providers")
        if isinstance(providers, list):
            return len(providers) > 0
        if isinstance(providers, dict):
            return len(providers) > 0
        return False

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
    # Bridge helpers (kept for _resolve_distro_bundle and end_session)
    # ------------------------------------------------------------------

    def _get_bridge(self) -> Any:
        """Lazily create the LocalBridge singleton."""
        if self._bridge is None:
            from amplifier_distro.bridge import LocalBridge

            self._bridge = LocalBridge()
        return self._bridge

    # ------------------------------------------------------------------
    # Session lifecycle (CLI pattern: prepared bundle -> direct create)
    # ------------------------------------------------------------------

    def _register_streaming_hooks(self, session: Any, handle: SessionHandle) -> None:
        """Register streaming hooks on the session (same as bridge does)."""
        try:
            from amplifier_distro.bridge_protocols import BridgeStreamingHook
            from amplifier_core.events import ALL_EVENTS  # type: ignore[import-not-found]

            streaming = BridgeStreamingHook(on_event=handle._on_stream)
            for event in list(ALL_EVENTS):
                session.coordinator.hooks.register(
                    event=event,
                    handler=streaming,
                    priority=100,
                    name=f"tui-streaming:{event}",
                )
        except (ImportError, AttributeError):
            logger.debug(
                "Could not register streaming hooks"
                " (amplifier-core events not available)"
            )

    async def start_new_session(
        self,
        conversation_id: str | None = None,
        cwd: Path | None = None,
        model_override: str = "",
    ) -> SessionHandle:
        """Start a new Amplifier session using the pre-prepared bundle.

        If conversation_id is None, an ID is auto-generated and this handle
        becomes the default (backward compat).
        """
        from amplifier_distro.bridge_protocols import (
            BridgeApprovalSystem,
            BridgeDisplaySystem,
        )

        # Ensure bundle is prepared (no-op if already done)
        if self._prepared is None:
            await self.prepare_bundle()

        auto_generated = conversation_id is None
        if auto_generated:
            conversation_id = str(uuid.uuid4())

        if cwd is None:
            cwd = Path.cwd()

        handle = SessionHandle(conversation_id=conversation_id)

        # Create session directly from PreparedBundle (like the CLI does)
        display = BridgeDisplaySystem()
        approval = BridgeApprovalSystem(auto_approve=True)

        session = await self._prepared.create_session(
            approval_system=approval,
            display_system=display,
            session_cwd=cwd,
        )

        # Register streaming hooks
        self._register_streaming_hooks(session, handle)

        handle.session = session
        handle.session_id = session.coordinator.session_id

        if model_override:
            self._switch_model_on_handle(handle, model_override)

        handle.reset_usage()
        self._extract_model_info_on_handle(handle)

        self._handles[conversation_id] = handle

        if auto_generated:
            self._default_conversation_id = conversation_id

        logger.info(
            "Session created: id=%s conversation=%s",
            handle.session_id,
            conversation_id,
        )
        return handle

    async def resume_session(
        self,
        session_id: str,
        conversation_id: str | None = None,
        model_override: str = "",
        working_dir: Path | None = None,
    ) -> SessionHandle:
        """Resume an existing Amplifier session using the pre-prepared bundle.

        Finds the session directory, creates a session with the original ID,
        and injects the previous transcript.  If conversation_id is None, an
        ID is auto-generated and this handle becomes the default.
        """
        from amplifier_distro.bridge_protocols import (
            BridgeApprovalSystem,
            BridgeDisplaySystem,
        )

        # Ensure bundle is prepared (no-op if already done)
        if self._prepared is None:
            await self.prepare_bundle()

        auto_generated = conversation_id is None
        if auto_generated:
            conversation_id = str(uuid.uuid4())

        handle = SessionHandle(conversation_id=conversation_id)

        # 1. Find the session directory (same logic as bridge)
        session_dir, effective_cwd = self._find_session_dir(
            session_id, working_dir or Path.cwd()
        )

        # 2. Create session with resume flag
        display = BridgeDisplaySystem()
        approval = BridgeApprovalSystem(auto_approve=True)

        session = await self._prepared.create_session(
            session_id=session_id,
            is_resumed=True,
            approval_system=approval,
            display_system=display,
            session_cwd=effective_cwd,
        )

        # 3. Register streaming hooks
        self._register_streaming_hooks(session, handle)

        # 4. Load and inject previous transcript
        self._inject_transcript(session, session_dir)

        handle.session = session
        handle.session_id = session.coordinator.session_id

        if model_override:
            self._switch_model_on_handle(handle, model_override)

        handle.reset_usage()
        self._extract_model_info_on_handle(handle)

        self._handles[conversation_id] = handle

        if auto_generated:
            self._default_conversation_id = conversation_id

        logger.info(
            "Session resumed: id=%s conversation=%s dir=%s",
            handle.session_id,
            conversation_id,
            session_dir,
        )
        return handle

    def _find_session_dir(
        self, session_id: str, fallback_cwd: Path
    ) -> tuple[Path, Path]:
        """Locate a session directory by ID (or prefix).

        Search order:
        1. The project directory matching ``fallback_cwd`` (current CWD).
        2. All other project directories.

        When multiple matches exist, prefer:
        - Matches from the current project directory
        - Longer directory names (full UUID over short-name alias)

        Returns (session_dir, effective_working_dir).
        """
        projects_path = _AMPLIFIER_HOME / _PROJECTS_DIR
        if not projects_path.exists():
            raise FileNotFoundError(f"No projects directory found at {projects_path}")

        # Determine which project dir corresponds to the current CWD so we
        # can prefer it when the same session ID appears in multiple projects.
        cwd_project_name = _encode_cwd(fallback_cwd)

        matches: list[tuple[Path, Path]] = []  # (session_dir, project_dir)
        for project_dir in projects_path.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            search_dir = sessions_subdir if sessions_subdir.is_dir() else project_dir
            for candidate in search_dir.iterdir():
                if not candidate.is_dir():
                    continue
                if candidate.name == session_id or candidate.name.startswith(
                    session_id
                ):
                    matches.append((candidate, project_dir))

        if not matches:
            raise FileNotFoundError(f"Session not found: {session_id}")

        if len(matches) > 1:
            # Prefer the current project's match over other projects.
            local = [m for m in matches if m[1].name == cwd_project_name]
            if local:
                matches = local

        if len(matches) > 1:
            # Among remaining matches, prefer the longest directory name
            # (full UUID over short-name alias).
            matches.sort(key=lambda m: len(m[0].name), reverse=True)
            if matches[0][0].name != matches[1][0].name:
                matches = [matches[0]]
            else:
                ids = [f"{m[0].name} (in {m[1].name})" for m in matches]
                raise ValueError(
                    f"Ambiguous session prefix '{session_id}' matches: {ids}"
                )

        session_dir, project_dir = matches[0]

        # Try to recover the original working directory from the project dir name
        try:
            effective_cwd = Path(reconstruct_project_path(project_dir.name))
            if not effective_cwd.is_dir():
                effective_cwd = fallback_cwd
        except (ValueError, IndexError):
            effective_cwd = fallback_cwd

        return session_dir, effective_cwd

    @staticmethod
    def _inject_transcript(session: Any, session_dir: Path) -> None:
        """Load transcript.jsonl and inject messages into session context."""
        transcript_file = session_dir / _TRANSCRIPT_FILENAME
        if not transcript_file.exists():
            logger.debug("No transcript found at %s", transcript_file)
            return

        try:
            messages: list[dict[str, str]] = []
            for line in transcript_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                role = entry.get("role", "user")
                content = entry.get("content", "")
                if content:
                    messages.append({"role": role, "content": content})

            if messages:
                try:
                    session.coordinator.context.add_messages(messages)
                    logger.info(
                        "Injected %d messages from previous transcript",
                        len(messages),
                    )
                except (AttributeError, TypeError):
                    logger.debug(
                        "Could not inject transcript messages"
                        " (context API not available)"
                    )
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            logger.warning(
                "Failed to load transcript from %s",
                transcript_file,
                exc_info=True,
            )

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
                # Direct cleanup when no bridge handle (our normal path now)
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
        # Drain pending steering injects
        while handle.has_pending_inject:
            inject = handle.pop_pending_inject()
            if inject:
                response = await handle.session.execute(inject)
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
    def get_session_transcript_path(
        session_id: str, cwd: Path | None = None
    ) -> Path | None:
        """Locate the ``transcript.jsonl`` file for *session_id*.

        Scans project directories under ``~/.amplifier/projects/``.
        If *cwd* is provided, the matching project is searched first
        to avoid cross-project collisions.  Supports prefix matching.
        """
        projects_dir = amplifier_projects_dir()
        if not projects_dir.exists():
            return None

        # Build ordered list: current project first, then the rest.
        project_dirs = sorted(projects_dir.iterdir())
        if cwd is not None:
            cwd_project = _encode_cwd(cwd)
            project_dirs = sorted(
                project_dirs,
                key=lambda d: (0 if d.name == cwd_project else 1, d.name),
            )

        best: Path | None = None
        best_len = 0  # prefer longest dir name (full UUID > alias)
        for project_dir in project_dirs:
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
                    if transcript.exists() and len(session_dir.name) > best_len:
                        best = transcript
                        best_len = len(session_dir.name)
                        # If we found a match in the CWD project, stop
                        # searching other projects.
                        if cwd is not None and project_dir.name == cwd_project:
                            return best
        return best
        return None
