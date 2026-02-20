"""DesktopApp: PySide6 native frontend for Amplifier.

Architecture (composition pattern to avoid MRO conflicts):
  - DesktopBackend(SharedAppBase, ...16 mixins...) -- no Qt inheritance
  - DesktopApp(QMainWindow) -- the Qt window, holds all widgets
  - StreamSignals bridges the two via Qt's thread-safe signal-slot mechanism
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from amplifier_tui.core.app_base import SharedAppBase
from amplifier_tui.desktop.commands import (
    DesktopDisplayCommandsMixin,
    DesktopExportCommandsMixin,
    DesktopSearchCommandsMixin,
    DesktopSessionCommandsMixin,
)
from amplifier_tui.core.commands import (
    AgentCommandsMixin,
    BranchCommandsMixin,
    CompareCommandsMixin,
    ContentCommandsMixin,
    DashboardCommandsMixin,
    FileCommandsMixin,
    GitCommandsMixin,
    PersistenceCommandsMixin,
    PluginCommandsMixin,
    RecipeCommandsMixin,
    ReplayCommandsMixin,
    ShellCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    ToolCommandsMixin,
    WatchCommandsMixin,
)
from amplifier_tui.core.conversation import ConversationState
from amplifier_tui.core.history import PromptHistory
from amplifier_tui.core.persistence import (
    AliasStore,
    BookmarkStore,
    ClipboardStore,
    DraftStore,
    MessagePinStore,
    NoteStore,
    PinnedSessionStore,
    RefStore,
    SessionNameStore,
    SnippetStore,
    TagStore,
    TemplateStore,
)
from amplifier_tui.core.preferences import load_preferences
from amplifier_tui.core.session_manager import SessionManager

from .signals import StreamSignals
from .theme import MESSAGE_CSS
from .widgets import (
    AgentTreePanel,
    AmplifierStatusBar,
    ChatDisplay,
    ChatInput,
    DesktopTabState,
    FindBar,
    ProjectPanel,
    SessionSidebar,
    TodoPanel,
)

logger = logging.getLogger(__name__)

# Shared Amplifier home directory for persistence stores
_amp_home = Path.home() / ".amplifier"
_amp_home.mkdir(parents=True, exist_ok=True)

# Autosave directory for desktop frontend session recovery
_AUTOSAVE_DIR = Path.home() / ".amplifier" / "desktop-autosave"


# ------------------------------------------------------------------
# Minimal FileWatcher stub (desktop doesn't do filesystem polling yet)
# ------------------------------------------------------------------
class _DesktopFileWatcher:
    """Minimal FileWatcher stub for desktop."""

    def __init__(self) -> None:
        self.watched_files: dict[str, Any] = {}

    def add(self, path: str, interval: float | None = None) -> None:  # noqa: ARG002
        pass

    def remove(self, path: str) -> None:  # noqa: ARG002
        pass

    def check(self) -> None:
        pass


# ==================================================================
# DesktopBackend -- SharedAppBase + all command mixins, NO Qt
# Desktop-specific mixins listed first so they override core equivalents.
# ==================================================================
class DesktopBackend(
    DesktopDisplayCommandsMixin,
    DesktopExportCommandsMixin,
    DesktopSearchCommandsMixin,
    DesktopSessionCommandsMixin,
    SharedAppBase,
    AgentCommandsMixin,
    BranchCommandsMixin,
    CompareCommandsMixin,
    ContentCommandsMixin,
    DashboardCommandsMixin,
    FileCommandsMixin,
    GitCommandsMixin,
    PersistenceCommandsMixin,
    PluginCommandsMixin,
    RecipeCommandsMixin,
    ReplayCommandsMixin,
    ShellCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    ToolCommandsMixin,
    WatchCommandsMixin,
):
    """Backend: shared app logic + command mixins, bridged to Qt via signals."""

    def __init__(self, signals: StreamSignals) -> None:
        super().__init__()
        self._signals = signals
        self.session_manager = SessionManager()
        self._conversation = ConversationState()

        # Set by DesktopApp after construction (back-reference for command mixins)
        self._desktop_app: Any = None

        # ==============================================================
        # Category 1: Data Attributes (mirrored from WebApp)
        # ==============================================================

        # Session statistics counters
        self._user_message_count: int = 0
        self._assistant_message_count: int = 0
        self._tool_call_count: int = 0
        self._user_words: int = 0
        self._assistant_words: int = 0
        self._session_start_time: float = time.monotonic()
        self._response_times: list[float] = []
        self._tool_usage: dict[str, int] = {}
        self._top_words: dict[str, int] = {}

        # Custom system prompt
        self._system_prompt: str = ""
        self._system_preset_name: str = ""

        # Command aliases, snippets, templates
        self._aliases: dict[str, str] = {}
        self._snippets: dict[str, dict[str, str]] = {}
        self._snippet_content: str = ""
        self._snippet_category: str = ""
        self._templates: dict[str, str] = {}

        # Attachments
        self._attachments: list[Any] = []

        # Pinned messages and sessions
        self._message_pins: list[dict[str, Any]] = []
        self._pinned_sessions: set[str] = set()

        # Session notes and refs
        self._session_notes: list[dict[str, Any]] = []
        self._session_refs: list[dict[str, Any]] = []

        # Draft state
        self._draft_text: str = ""
        self._copy_preview: str = ""

        # Undo
        self._pending_undo: int | None = None

        # Watch files
        self._watched_files: dict[str, Any] = {}

        # Autosave
        self._autosave_enabled: bool = False
        self._autosave_interval: int = 300
        self._last_autosave: float = 0.0
        self._autosave_timer: Any = None

        # Theme preview
        self._previewing_theme: str | None = None

        # Session list data
        self._session_list_data: list[dict[str, Any]] = []

        # Search messages (list of tuples: role, text, widget_or_none)
        self._search_messages: list[Any] = []

        # ==============================================================
        # Category 2: Persistence Stores
        # ==============================================================
        self._alias_store = AliasStore(_amp_home / "tui-aliases.json")
        self._bookmark_store = BookmarkStore(_amp_home / "tui-bookmarks.json")
        self._draft_store = DraftStore(
            _amp_home / "tui-drafts.json", _amp_home / "tui-draft.txt"
        )
        self._note_store = NoteStore(_amp_home / "tui-notes.json")
        self._pin_store = MessagePinStore(_amp_home / "tui-pins.json")
        self._pinned_session_store = PinnedSessionStore(
            _amp_home / "tui-pinned-sessions.json"
        )
        self._ref_store = RefStore(_amp_home / "tui-refs.json")
        self._session_name_store = SessionNameStore(
            _amp_home / "tui-session-names.json",
            _amp_home / "tui-session-titles.json",
        )
        self._snippet_store = SnippetStore(_amp_home / "tui-snippets.json")
        self._template_store = TemplateStore(_amp_home / "tui-templates.json")
        self._tag_store = TagStore(_amp_home / "tui-session-tags.json")
        self._clipboard_store = ClipboardStore(_amp_home / "tui-clipboard-ring.json")

        # ==============================================================
        # Category 3: Feature Objects
        # ==============================================================
        from amplifier_tui.core.features.agent_tracker import AgentTracker
        from amplifier_tui.core.features.branch_manager import BranchManager
        from amplifier_tui.core.features.compare_manager import CompareManager
        from amplifier_tui.core.features.context_profiler import ContextHistory
        from amplifier_tui.core.features.dashboard_stats import DashboardStats
        from amplifier_tui.core.features.plugin_loader import PluginLoader
        from amplifier_tui.core.features.recipe_tracker import RecipeTracker
        from amplifier_tui.core.features.replay_engine import ReplayEngine
        from amplifier_tui.core.features.tool_log import ToolLog

        self._agent_tracker = AgentTracker()
        self._tool_log = ToolLog()
        self._recipe_tracker = RecipeTracker()
        self._branch_manager = BranchManager()
        self._compare_manager = CompareManager()
        self._replay_engine = ReplayEngine()
        self._plugin_loader = PluginLoader()
        self._plugin_loader.load_all()
        self._dashboard_stats = DashboardStats()
        self._context_history = ContextHistory()

        # Preferences and prompt history
        self._prefs = load_preferences()
        self._history = PromptHistory()

        # File watcher stub
        self._file_watcher = _DesktopFileWatcher()
        self._watched_files = self._file_watcher.watched_files

    # ==================================================================
    # Abstract display methods (SharedAppBase) -- emit Qt signals
    # ==================================================================

    def _conversation_for_cid(self, cid: str) -> "ConversationState":
        """Find the ConversationState matching *cid*, or fall back to self._conversation."""
        app = self._desktop_app
        if app:
            for tab in app._tabs:
                if tab.tab_id == cid:
                    return tab.conversation
        return self._conversation

    def _all_conversations(self) -> list:
        """Return all conversations across all tabs."""
        app = self._desktop_app
        if app and app._tabs:
            return [tab.conversation for tab in app._tabs]
        return [self._conversation]

    def _add_system_message(
        self, text: str, *, conversation_id: str = "", **kwargs: Any
    ) -> None:
        cid = conversation_id or self._conversation.conversation_id
        self._signals.system_message.emit(text, cid)

    def _add_user_message(
        self, text: str, *, conversation_id: str = "", **kwargs: Any
    ) -> None:
        cid = conversation_id or self._conversation.conversation_id
        self._signals.user_message.emit(text, cid)

    def _add_assistant_message(
        self, text: str, *, conversation_id: str = "", **kwargs: Any
    ) -> None:
        cid = conversation_id or self._conversation.conversation_id
        self._signals.assistant_message.emit(text, cid)

    def _show_error(self, text: str, *, conversation_id: str = "") -> None:
        cid = conversation_id or self._conversation.conversation_id
        self._signals.error_message.emit(text, cid)

    def _update_status(self, text: str, *, conversation_id: str = "") -> None:
        cid = conversation_id or self._conversation.conversation_id
        self._signals.status_update.emit(text, cid)

    def _start_processing(
        self, label: str = "Thinking", *, conversation_id: str = ""
    ) -> None:
        cid = conversation_id or self._conversation.conversation_id
        conv = self._conversation_for_cid(cid)
        conv.is_processing = True
        self._signals.processing_started.emit(label, cid)

    def _finish_processing(self, *, conversation_id: str = "") -> None:
        cid = conversation_id or self._conversation.conversation_id
        conv = self._conversation_for_cid(cid)
        conv.is_processing = False
        self._signals.processing_finished.emit(cid)

    # ==================================================================
    # Abstract streaming methods (called from BACKGROUND THREAD)
    # Qt signals handle thread-safety automatically.
    # ==================================================================

    def _on_stream_block_start(self, conversation_id: str, block_type: str) -> None:
        self._signals.block_start.emit(conversation_id, block_type)

    def _on_stream_block_delta(
        self, conversation_id: str, block_type: str, accumulated_text: str
    ) -> None:
        self._signals.block_delta.emit(conversation_id, block_type, accumulated_text)

    def _on_stream_block_end(
        self,
        conversation_id: str,
        block_type: str,
        final_text: str,
        had_block_start: bool,
    ) -> None:
        self._signals.block_end.emit(
            conversation_id, block_type, final_text, had_block_start
        )

    def _on_stream_tool_start(
        self,
        conversation_id: str,
        name: str,
        tool_input: dict,  # type: ignore[type-arg]
    ) -> None:
        self._signals.tool_start.emit(conversation_id, name, tool_input)

    def _on_stream_tool_end(
        self,
        conversation_id: str,
        name: str,
        tool_input: dict,
        result: str,  # type: ignore[type-arg]
    ) -> None:
        self._signals.tool_end.emit(conversation_id, name, tool_input, result)

    def _on_stream_usage_update(self, conversation_id: str) -> None:
        self._signals.usage_update.emit(conversation_id)

    # ==================================================================
    # Message handling
    # ==================================================================

    def _handle_submitted_text(self, text: str) -> None:
        """Handle user input: route commands or send message."""
        text = text.strip()
        if not text:
            return
        if text.startswith("/"):
            self._handle_slash_command(text)
            return
        cid = self._conversation.conversation_id
        self._add_user_message(text, conversation_id=cid)
        self._start_processing(conversation_id=cid)
        # Send on background thread (session APIs are async)
        thread = threading.Thread(
            target=self._send_message_worker,
            args=(text,),
            daemon=True,
        )
        thread.start()

    def _send_message_worker(self, text: str) -> None:
        """Background thread: create session if needed, wire callbacks, send.

        SessionManager methods are async, so we spin up a fresh event loop
        for the background thread.
        """
        cid = self._conversation.conversation_id
        conv = self._conversation_for_cid(cid)
        try:
            conv.tool_count_this_turn = 0
            conv.got_stream_content = False

            try:
                if not self.session_manager.get_handle(cid):
                    asyncio.run(
                        self.session_manager.start_new_session(
                            conversation_id=cid,
                            cwd=Path(os.getcwd()),
                        )
                    )
                    self._amplifier_ready = True

                self._wire_streaming_callbacks(cid, conv)
                response = asyncio.run(
                    self.session_manager.send_message(text, conversation_id=cid)
                )

                if not conv.got_stream_content and response:
                    self._add_assistant_message(response, conversation_id=cid)
            except Exception as e:
                self._show_error(str(e), conversation_id=cid)
        finally:
            self._finish_processing(conversation_id=cid)

    def _handle_slash_command(self, text: str) -> None:
        """Route slash commands to the appropriate mixin handler."""
        parts = text.split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handler_name = f"_cmd_{command.lstrip('/')}"
        handler = getattr(self, handler_name, None)
        if handler:
            try:
                handler(args)
            except Exception as e:
                self._show_error(f"Command error: {e}")
        else:
            # Try plugin commands
            if self._plugin_loader.execute_command(command.lstrip("/"), self, args):
                return
            self._show_error(
                f"Unknown command: {command}\nType /help for available commands."
            )

    # ==================================================================
    # Utility methods (mirrored from WebApp)
    # ==================================================================

    def _get_session_id(self) -> str | None:
        sm = self.session_manager if hasattr(self, "session_manager") else None
        return getattr(sm, "session_id", None) if sm else None

    @staticmethod
    def _format_count(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    @staticmethod
    def _format_token_count(count: int) -> str:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 10_000:
            val = count / 1_000
            return f"{val:.0f}k" if val >= 100 else f"{val:.1f}k"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}k"
        return str(count)

    def _get_context_window(self) -> int:
        override = self._prefs.display.context_window_size
        if override > 0:
            return override
        sm = self.session_manager
        if sm and sm.context_window > 0:
            return sm.context_window
        return 200_000  # default

    def _is_binary(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
            return b"\x00" in chunk
        except Exception:
            return False

    def _read_file_for_include(self, path: str) -> str | None:
        p = Path(path).expanduser()
        if not p.exists():
            self._show_error(f"File not found: {path}")
            return None
        if self._is_binary(str(p)):
            self._show_error(f"Binary file, cannot include: {path}")
            return None
        try:
            return p.read_text(errors="replace")
        except Exception as e:
            self._show_error(f"Error reading {path}: {e}")
            return None

    # ==================================================================
    # Persistence delegate methods (mirrored from WebApp)
    # ==================================================================

    def _load_bookmarks(self) -> dict[str, list[dict[str, Any]]]:
        return self._bookmark_store.load_all()

    def _save_aliases(self) -> None:
        self._alias_store.save(self._aliases)

    def _save_snippets(self) -> None:
        self._snippet_store.save(self._snippets)

    def _save_templates(self) -> None:
        self._template_store.save(self._templates)

    def _save_notes(self) -> None:
        sid = self._get_session_id()
        if sid:
            self._note_store.save(sid, self._session_notes)

    def _save_refs(self) -> None:
        sid = self._get_session_id()
        if sid:
            self._ref_store.save(sid, self._session_refs)

    def _save_message_pins(self) -> None:
        sid = self._get_session_id()
        if sid:
            self._pin_store.save(sid, self._message_pins)

    def _save_pinned_sessions(self) -> None:
        self._pinned_session_store.save(self._pinned_sessions)

    def _save_crash_draft(self) -> None:
        pass  # Not critical for desktop Phase 1

    def _load_crash_draft(self) -> str | None:
        return None

    def _clear_crash_draft(self) -> None:
        pass

    def _save_draft(self, name: str = "") -> None:
        drafts = self._draft_store.load()
        drafts[name or "_current"] = self._draft_text
        self._draft_store.save_all(drafts)

    def _load_drafts(self) -> dict[str, str]:
        return self._draft_store.load()

    def _clear_draft(self, name: str = "") -> None:
        self._draft_store.remove(name or "_current")

    def _load_session_names(self) -> dict[str, str]:
        return self._session_name_store.load_names()

    def _list_bookmarks(self) -> list[dict[str, Any]]:
        sid = self._get_session_id()
        if not sid:
            return []
        all_bm = self._load_bookmarks()
        return all_bm.get(sid, [])

    def _bookmark_last_message(self, label: str = "") -> None:  # noqa: ARG002
        self._add_system_message("Bookmarking is not yet available in the desktop app.")

    def _bookmark_nth_message(self, n: int, label: str = "") -> None:  # noqa: ARG002
        self._add_system_message("Bookmarking is not yet available in the desktop app.")

    def _remove_bookmark(self, index: int) -> None:  # noqa: ARG002
        self._add_system_message(
            "Bookmark removal is not yet available in the desktop app."
        )

    def _clear_bookmarks(self) -> None:
        sid = self._get_session_id()
        if sid:
            self._bookmark_store.save_for_session(sid, [])
        self._add_system_message("Bookmarks cleared")

    def _add_message_pin(self, text: str, label: str = "") -> None:
        self._message_pins.append({"text": text, "label": label})
        self._save_message_pins()

    def _remove_pin(self, index: int) -> None:
        if 0 <= index < len(self._message_pins):
            self._message_pins.pop(index)
            self._save_message_pins()

    def _add_note_message(self, text: str) -> None:
        from datetime import datetime

        self._session_notes.append(
            {"text": text, "timestamp": datetime.now().isoformat()}
        )
        self._save_notes()
        self._add_system_message(f"Note saved: {text[:50]}...")

    def _show_notes(self) -> None:
        if not self._session_notes:
            self._add_system_message("No notes for this session")
            return
        lines = ["**Session Notes:**"]
        for i, n in enumerate(self._session_notes, 1):
            lines.append(f"{i}. {n['text']}")
        self._add_system_message("\n".join(lines))

    def _migrate_snippets(self) -> None:
        pass  # No migration needed

    def _execute_undo(self) -> None:
        self._add_system_message("Undo not yet supported in desktop interface")

    def _show_watch_diff(self, path: str, old: str, new: str) -> None:
        import difflib

        diff = difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=path,
            tofile=path,
            lineterm="",
        )
        self._add_system_message(f"```diff\n{chr(10).join(diff)}\n```")

    # ==================================================================
    # Textual-specific stubs (no-ops for desktop)
    # ==================================================================

    def _cmd_suspend(self, args: str = "") -> None:  # noqa: ARG002
        """Not applicable in desktop mode."""
        self._add_system_message(
            "The /suspend command is not available in the desktop app."
            " Minimize the window instead."
        )

    def _cmd_compact(self, args: str = "") -> None:  # noqa: ARG002
        """Not applicable in desktop mode - no terminal to compact."""
        self._add_system_message(
            "The /compact command is not available in the desktop app."
            " Use /zoom to adjust text size."
        )

    def suspend(self) -> None:
        """Textual suspend -- no-op for desktop."""

    def query_one(self, selector: str, *args: Any) -> Any:
        """Textual query_one -- not available in desktop."""
        raise RuntimeError(
            f"query_one('{selector}') not available in desktop interface"
        )

    def set_interval(
        self, interval: float, callback: Any, *args: Any, **kwargs: Any
    ) -> None:  # type: ignore[return]
        """Textual set_interval -- return None (timer not needed yet)."""
        return None  # type: ignore[return-value]

    @property
    def theme(self) -> str:
        return "dark"

    def action_copy_response(self) -> None:
        pass

    def action_open_editor(self) -> None:
        self._add_system_message("Editor not available in desktop interface yet")

    def action_show_shortcuts(self) -> None:
        self._add_system_message(
            "**Desktop Keyboard Shortcuts**\n\n"
            "| Shortcut | Action |\n"
            "|----------|--------|\n"
            "| `Enter` | Send message |\n"
            "| `Up/Down` | Command history |\n"
            "| `/` | Start command |\n"
        )

    def _cmd_theme(self, text: str = "") -> None:
        """Show or switch theme."""
        arg = text.strip().lower()
        available = ["dark"]
        if not arg or arg == "list":
            current = "dark"  # only one for now
            self._add_system_message(
                f"Current theme: {current}\nAvailable: {', '.join(available)}"
            )
        elif arg in available:
            self._add_system_message(f"Theme '{arg}' is already active.")
        else:
            self._add_system_message(
                f"Unknown theme '{arg}'. Available: {', '.join(available)}"
            )

    # UI update stubs (no-op for desktop Phase 1)
    def _apply_theme_to_all_widgets(self) -> None:
        pass

    def _preview_theme(self, name: str) -> None:
        pass

    def _revert_theme_preview(self) -> None:
        pass

    def _clear_welcome(self) -> None:
        pass

    def _populate_session_list(
        self, sessions: list[dict[str, Any]] | None = None
    ) -> None:
        """Refresh the session sidebar (runs I/O on a background thread)."""
        thread = threading.Thread(
            target=self._populate_session_list_worker,
            daemon=True,
        )
        thread.start()

    def _populate_session_list_worker(self) -> None:
        """Background worker: scan session dirs and emit signal with results."""
        try:
            raw = SessionManager.list_all_sessions(limit=50)
            sidebar_sessions: list[dict[str, Any]] = []
            session_names = self._session_name_store.load_names()
            for s in raw:
                sid = s.get("session_id", "")
                title = (
                    session_names.get(sid, "")
                    or s.get("name", "")
                    or s.get("description", "")
                    or sid[:12]
                )
                sidebar_sessions.append(
                    {
                        "session_id": sid,
                        "title": title,
                        "date": s.get("date_str", ""),
                        "project": s.get("project", ""),
                    }
                )
            self._signals.session_list_ready.emit(sidebar_sessions)
        except Exception:
            logger.warning("Failed to load session list", exc_info=True)

    def _resume_session_worker(self, session_id: str, conversation_id: str) -> None:
        """Background thread: resume an Amplifier session and load its transcript.

        On success emits ``session_resumed(cid, session_id, messages)``
        where *messages* is a list of DisplayBlock-style dicts suitable for
        replay in the ChatDisplay.  On failure emits
        ``session_resume_failed(session_id, error)``.
        """
        from amplifier_tui.core.transcript_loader import (
            load_transcript,
            parse_message_blocks,
        )

        try:
            # 1) Load transcript from disk (quick I/O, no session needed)
            transcript_path = SessionManager.get_session_transcript_path(session_id)
            display_messages: list[dict[str, Any]] = []
            if transcript_path:
                for msg in load_transcript(transcript_path):
                    for block in parse_message_blocks(msg):
                        display_messages.append(
                            {
                                "kind": block.kind,
                                "content": block.content,
                                "tool_name": block.tool_name,
                            }
                        )

            # 2) Resume the Amplifier session via the bridge
            # Determine working directory from session metadata
            working_dir: Path | None = None
            all_sessions = SessionManager.list_all_sessions(limit=200)
            for s in all_sessions:
                if s.get("session_id") == session_id:
                    pp = s.get("project_path", "")
                    if pp and Path(pp).is_dir():
                        working_dir = Path(pp)
                    break

            handle = asyncio.run(
                self.session_manager.resume_session(
                    session_id,
                    conversation_id=conversation_id,
                    working_dir=working_dir,
                )
            )
            self._amplifier_ready = True

            # Extract model info for status bar
            if handle and handle.model_name:
                pass  # model_name already set on handle

            self._signals.session_resumed.emit(
                conversation_id, session_id, display_messages
            )
        except Exception as e:
            logger.debug("Failed to resume session %s", session_id, exc_info=True)
            self._signals.session_resume_failed.emit(session_id, str(e))

    def _play_bell(self) -> None:
        pass

    def _update_attachment_indicator(self) -> None:
        pass

    def _update_mode_display(self) -> None:
        """Update the status bar mode label when mode changes."""
        app = self._desktop_app
        if app:
            mode = getattr(self, "_current_mode", None)
            app._status_bar.set_mode(mode)

    def _update_pinned_panel(self) -> None:
        pass

    def _update_system_indicator(self) -> None:
        pass

    def _update_token_display(self) -> None:
        """Update the status bar token labels from current session usage."""
        app = self._desktop_app
        if not app:
            return
        cid = self._conversation.conversation_id
        handle = self.session_manager.get_handle(cid)
        if handle:
            app._status_bar.set_tokens(
                handle.total_input_tokens,
                handle.total_output_tokens,
                self._get_context_window(),
            )

    def _remove_all_pin_classes(self) -> None:
        pass

    def _jump_to_bookmark(self, index: int) -> None:
        pass

    def _cmd_agent_tree_panel(self, args: str = "") -> None:
        self._add_system_message("Agent tree panel: use /agents instead")

    def _cmd_fork_tab(self, args: str = "") -> None:  # noqa: ARG002
        self._add_system_message(
            "Tab forking is not yet available. Use /split to create a new empty tab."
        )

    # Include/attach (simplified for desktop Phase 1)
    def _include_and_send(self, content: str, prompt: str = "") -> None:
        """Include content and send it as a message."""
        msg = content
        if prompt:
            msg = f"{prompt}\n\n{msg}"
        self._add_system_message("Including content and sending...")
        self._handle_submitted_text(msg)

    def _include_into_input(self, path: str) -> None:
        self._add_system_message(f"Use /include {path} to include file content")

    def _attach_file(self, path: str) -> None:
        self._attachments.append({"path": path})
        self._add_system_message(f"Attached: {path}")

    def _show_attachments(self) -> None:
        if not self._attachments:
            self._add_system_message("No attachments")
            return
        lines = ["**Attachments:**"]
        for a in self._attachments:
            lines.append(f"- {a.get('path', 'unknown')}")
        self._add_system_message("\n".join(lines))

    def _do_autosave(self) -> None:
        """SharedAppBase stub -- actual autosave driven by DesktopApp timer."""

    def _autosave_restore(self) -> None:
        """SharedAppBase stub -- actual restore driven by DesktopApp startup."""

    def _edit_snippet_in_editor(self, name: str) -> None:
        self._add_system_message(
            "Editor not available in desktop interface. Use /snippet save instead."
        )

    def _start_watch_timer(self) -> None:
        # File watching polling is not implemented for desktop yet.
        # The /watch command will register files but changes won't be detected.
        logger.debug("File watch timer requested but not implemented for desktop")

    def _stop_watch_timer(self) -> None:
        logger.debug("File watch timer stop requested (no-op for desktop)")

    # Desktop-only: simple /model handler (not in a mixin)
    def _cmd_model(self, text: str) -> None:
        """Show or switch the model."""
        text = text.strip()
        sm = self.session_manager
        if not text or text == "/model":
            model = sm.model_name if sm else "unknown"
            self._add_system_message(f"Current model: **{model}**")
            return
        new_model = text
        if sm:
            sm.model_name = new_model
            self._add_system_message(f"Model set to: **{new_model}**")
        else:
            self._show_error("No session manager available")

    # Desktop-only: /new handler
    def _cmd_new(self, args: str = "") -> None:
        """Start a new session."""
        if self.session_manager:
            old_cid = self._conversation.conversation_id
            self.session_manager.remove_handle(old_cid)
            self.session_manager.reset_usage()
        self._amplifier_ready = False
        self._conversation = ConversationState()
        self._add_system_message("Starting new session... Send a message to begin.")
        # Refresh the sidebar so the old session appears in the list
        self._populate_session_list()

    # Desktop-only: /help handler
    def _cmd_help(self, args: str = "") -> None:
        """Show categorized help for all available commands."""
        self._add_system_message(
            "**Amplifier Desktop Commands**\n"
            "\n"
            "**Session**\n"
            "  /new            Start a new session\n"
            "  /model [name]   Show or switch model\n"
            "\n"
            "**Information**\n"
            "  /help           Show this help\n"
            "  /info           Session info\n"
            "  /stats [sub]    Session statistics\n"
            "  /tokens         Token usage summary\n"
            "  /context [sub]  Context window analysis\n"
            "  /dashboard      Session dashboard\n"
            "\n"
            "**Content & Modes**\n"
            "  /system [text]  Set/view/clear system prompt\n"
            "  /mode [name]    Set/view mode\n"
            "  /copy [N]       Copy message\n"
            "  /history [sub]  Prompt history\n"
            "  /undo [N]       Undo last N messages\n"
            "  /redo           Resend last message\n"
            "  /retry          Retry last exchange\n"
            "\n"
            "**Files**\n"
            "  /include <path> Include file content\n"
            "  /attach <path>  Attach file\n"
            "  /cat <path>     Display file content\n"
            "  /run <cmd>      Run shell command\n"
            "  /shell <cmd>    Run shell command\n"
            "\n"
            "**Persistence**\n"
            "  /alias, /snippet, /template, /draft, /note\n"
            "  /bookmark, /ref, /tag, /pin, /clipboard\n"
            "\n"
            "**AI & Tools**\n"
            "  /agents         Agent delegation tree\n"
            "  /recipe         Recipe pipeline\n"
            "  /tools          Tool introspection\n"
            "  /plugins        Plugin management\n"
            "\n"
            "**Git**\n"
            "  /git [sub]      Git status/operations\n"
            "  /diff [args]    Show git diff\n"
        )


# ==================================================================
# DesktopApp -- QMainWindow, the actual Qt window (Phase 2)
# ==================================================================
class DesktopApp(QMainWindow):
    """PySide6 main window for Amplifier desktop."""

    _SETTINGS_ORG = "Amplifier"
    _SETTINGS_APP = "AmplifierDesktop"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Amplifier")
        self.resize(1400, 900)

        # Create signal bridge and backend
        self._signals = StreamSignals()
        self._backend = DesktopBackend(self._signals)
        self._backend._desktop_app = self  # back-reference for desktop command mixins

        # Tab state
        self._tabs: list[DesktopTabState] = []
        self._cid_to_tab: dict[str, int] = {}  # conversation_id -> tab index
        self._current_tab_index: int = 0
        self._font_size: int = 14

        # Build full Phase 2 UI
        self._setup_ui()
        self._setup_menus()
        self._setup_shortcuts()
        self._connect_signals()
        self._restore_state()

        # Autosave timer (every 60 seconds)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._do_autosave_all)
        self._autosave_timer.start(60_000)

        # Try restoring from autosave; fall back to a fresh tab
        if not self._try_restore_autosave():
            self._new_tab()

        # Populate session sidebar on startup (background I/O)
        self._backend._populate_session_list()

    # ==================================================================
    # UI Setup
    # ==================================================================

    def _setup_ui(self) -> None:
        """Build the full Phase 2 layout."""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Main horizontal splitter: sidebar | center ---
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(self._main_splitter, 1)

        # Session sidebar (left)
        self._session_sidebar = SessionSidebar()
        self._session_sidebar.setMinimumWidth(200)
        self._session_sidebar.setMaximumWidth(400)
        self._session_sidebar.session_selected.connect(self._on_session_selected)
        self._main_splitter.addWidget(self._session_sidebar)

        # Center vertical splitter: tabs | input
        self._center_splitter = QSplitter(Qt.Orientation.Vertical)
        self._main_splitter.addWidget(self._center_splitter)

        # Tab widget containing ChatDisplays
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._center_splitter.addWidget(self._tab_widget)

        # Bottom area: find bar + input + status bar
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        # Find bar (hidden by default)
        self._find_bar = FindBar()
        self._find_bar.search_requested.connect(self._on_find)
        self._find_bar.search_next.connect(self._on_find_next)
        self._find_bar.search_prev.connect(self._on_find_prev)
        bottom_layout.addWidget(self._find_bar)

        # Chat input
        self._chat_input = ChatInput()
        self._chat_input.submitted.connect(self._on_submit)
        bottom_layout.addWidget(self._chat_input)

        # Status bar
        self._status_bar = AmplifierStatusBar()
        bottom_layout.addWidget(self._status_bar)

        self._center_splitter.addWidget(bottom_container)

        # Splitter proportions: chat area gets most space
        self._center_splitter.setStretchFactor(0, 8)
        self._center_splitter.setStretchFactor(1, 0)
        self._main_splitter.setStretchFactor(0, 0)
        self._main_splitter.setStretchFactor(1, 1)
        self._main_splitter.setSizes([220, 1180])

        # --- Dock panels (right side) ---
        self._todo_panel = TodoPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._todo_panel)

        self._agent_panel = AgentTreePanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._agent_panel)

        self._project_panel = ProjectPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._project_panel)

        # Stack the dock panels as tabs
        self.tabifyDockWidget(self._todo_panel, self._agent_panel)
        self.tabifyDockWidget(self._agent_panel, self._project_panel)
        self._todo_panel.raise_()

    def _setup_menus(self) -> None:
        """Build the menu bar."""
        menu_bar: QMenuBar = self.menuBar()  # type: ignore[assignment]

        # --- File menu ---
        file_menu = menu_bar.addMenu("&File")
        if file_menu:
            new_session = QAction("&New Session", self)
            new_session.setShortcut(QKeySequence("Ctrl+N"))
            new_session.triggered.connect(self._new_session)
            file_menu.addAction(new_session)

            new_tab = QAction("New &Tab", self)
            new_tab.setShortcut(QKeySequence("Ctrl+T"))
            new_tab.triggered.connect(self._new_tab)
            file_menu.addAction(new_tab)

            close_tab = QAction("&Close Tab", self)
            close_tab.setShortcut(QKeySequence("Ctrl+W"))
            close_tab.triggered.connect(
                lambda: self._close_tab(self._tab_widget.currentIndex())
            )
            file_menu.addAction(close_tab)

            file_menu.addSeparator()

            quit_action = QAction("&Quit", self)
            quit_action.setShortcut(QKeySequence("Ctrl+Q"))
            quit_action.triggered.connect(self.close)
            file_menu.addAction(quit_action)

        # --- Edit menu ---
        edit_menu = menu_bar.addMenu("&Edit")
        if edit_menu:
            find_action = QAction("&Find...", self)
            find_action.setShortcut(QKeySequence("Ctrl+F"))
            find_action.triggered.connect(self._show_find)
            edit_menu.addAction(find_action)

            clear_action = QAction("Clear Chat", self)
            clear_action.triggered.connect(self._clear_current_chat)
            edit_menu.addAction(clear_action)

        # --- View menu ---
        view_menu = menu_bar.addMenu("&View")
        if view_menu:
            toggle_sidebar = QAction("Toggle &Sidebar", self)
            toggle_sidebar.setShortcut(QKeySequence("Ctrl+B"))
            toggle_sidebar.triggered.connect(self._toggle_sidebar)
            view_menu.addAction(toggle_sidebar)

            view_menu.addSeparator()

            zoom_in = QAction("Zoom &In", self)
            zoom_in.setShortcut(QKeySequence("Ctrl+="))
            zoom_in.triggered.connect(self._zoom_in)
            view_menu.addAction(zoom_in)

            zoom_out = QAction("Zoom &Out", self)
            zoom_out.setShortcut(QKeySequence("Ctrl+-"))
            zoom_out.triggered.connect(self._zoom_out)
            view_menu.addAction(zoom_out)

            view_menu.addSeparator()

            toggle_todo = self._todo_panel.toggleViewAction()
            toggle_todo.setText("Todo Panel")
            view_menu.addAction(toggle_todo)

            toggle_agents = self._agent_panel.toggleViewAction()
            toggle_agents.setText("Agents Panel")
            view_menu.addAction(toggle_agents)

            toggle_projects = self._project_panel.toggleViewAction()
            toggle_projects.setText("Projects Panel")
            view_menu.addAction(toggle_projects)

        # --- Help menu ---
        help_menu = menu_bar.addMenu("&Help")
        if help_menu:
            about_action = QAction("&About", self)
            about_action.triggered.connect(
                lambda: self._display_system("Amplifier Desktop - PySide6 Frontend", "")
            )
            help_menu.addAction(about_action)

            shortcuts_action = QAction("&Keyboard Shortcuts", self)
            shortcuts_action.triggered.connect(
                lambda: self._backend.action_show_shortcuts()
            )
            help_menu.addAction(shortcuts_action)

    def _setup_shortcuts(self) -> None:
        """Additional keyboard shortcuts not covered by menu actions."""
        # Focus input on Escape
        pass  # Menu-based shortcuts are sufficient; extras can be added later

    # ==================================================================
    # Tab Management
    # ==================================================================

    def _new_tab(self) -> None:
        """Create a new conversation tab."""
        from amplifier_tui.core.conversation import ConversationState

        conv = ConversationState()
        tab_name = f"Chat {len(self._tabs) + 1}"
        tab_state = DesktopTabState(
            name=tab_name,
            tab_id=conv.conversation_id,
            conversation=conv,
        )
        self._tabs.append(tab_state)
        self._backend._conversation = conv

        # Create the ChatDisplay widget for this tab
        display = ChatDisplay()
        display.document().setDefaultStyleSheet(MESSAGE_CSS)
        index = self._tab_widget.addTab(display, tab_name)

        # Register conversation_id -> tab index mapping
        self._cid_to_tab[conv.conversation_id] = index

        self._tab_widget.setCurrentIndex(index)
        self._chat_input.setFocus()

    def _close_tab(self, index: int) -> None:
        """Close tab at index. Can't close the last tab."""
        if self._tab_widget.count() <= 1:
            return
        # Remove from cid mapping and tab list
        if 0 <= index < len(self._tabs):
            closed_cid = self._tabs[index].tab_id
            self._cid_to_tab.pop(closed_cid, None)
            self._tabs.pop(index)
        self._tab_widget.removeTab(index)
        # Rebuild cid->index mapping (indices shifted after removal)
        self._cid_to_tab = {tab.tab_id: i for i, tab in enumerate(self._tabs)}

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab switch: save/restore input text, update state."""
        # Save input text from the previous tab
        if 0 <= self._current_tab_index < len(self._tabs):
            self._tabs[
                self._current_tab_index
            ].input_text = self._chat_input.toPlainText()

        self._current_tab_index = index

        # Restore input text for new tab
        if 0 <= index < len(self._tabs):
            self._chat_input.setPlainText(self._tabs[index].input_text)
            cursor = self._chat_input.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._chat_input.setTextCursor(cursor)
            self._backend._conversation = self._tabs[index].conversation

    def _current_display(self) -> ChatDisplay | None:
        """Get the ChatDisplay for the active tab."""
        widget = self._tab_widget.currentWidget()
        if isinstance(widget, ChatDisplay):
            return widget
        return None

    def _display_for_cid(self, cid: str) -> ChatDisplay | None:
        """Get the ChatDisplay for a specific conversation_id.

        Falls back to the current tab if *cid* is not in the mapping (e.g.
        system messages emitted before any session is created).
        """
        index = self._cid_to_tab.get(cid)
        if index is not None and 0 <= index < self._tab_widget.count():
            widget = self._tab_widget.widget(index)
            if isinstance(widget, ChatDisplay):
                return widget
        # Fallback: current tab
        return self._current_display()

    def _current_tab_state(self) -> DesktopTabState | None:
        """Get the tab state for the active tab."""
        index = self._tab_widget.currentIndex()
        if 0 <= index < len(self._tabs):
            return self._tabs[index]
        return None

    # ==================================================================
    # Signal connections
    # ==================================================================

    def _connect_signals(self) -> None:
        """Wire all backend signals to UI display slots."""
        s = self._signals
        s.system_message.connect(self._display_system)
        s.user_message.connect(self._display_user)
        s.assistant_message.connect(self._display_assistant)
        s.error_message.connect(self._display_error)
        s.status_update.connect(self._display_status)
        s.processing_started.connect(self._display_processing_start)
        s.processing_finished.connect(self._display_processing_end)
        s.block_start.connect(self._on_block_start)
        s.block_delta.connect(self._on_block_delta)
        s.block_end.connect(self._on_block_end)
        s.tool_start.connect(self._on_tool_start)
        s.tool_end.connect(self._on_tool_end)
        s.usage_update.connect(self._on_usage_update)
        s.session_list_ready.connect(self._on_session_list_ready)
        s.session_resumed.connect(self._on_session_resumed)
        s.session_resume_failed.connect(self._on_session_resume_failed)

    # ==================================================================
    # Input handling
    # ==================================================================

    def _on_submit(self, text: str) -> None:
        """Handle submitted text from ChatInput."""
        text = text.strip()
        if not text:
            return
        self._backend._handle_submitted_text(text)

    # ==================================================================
    # Display handlers -> ChatDisplay methods
    # ==================================================================

    def _display_system(self, text: str, cid: str) -> None:
        display = self._display_for_cid(cid)
        if display:
            display.add_system_message(text)

    def _display_user(self, text: str, cid: str) -> None:
        display = self._display_for_cid(cid)
        if display:
            display.add_user_message(text)

    def _display_assistant(self, text: str, cid: str) -> None:
        display = self._display_for_cid(cid)
        if display:
            display.add_assistant_message(text)

    def _display_error(self, text: str, cid: str) -> None:
        display = self._display_for_cid(cid)
        if display:
            display.add_error_message(text)

    def _display_status(self, text: str, cid: str) -> None:  # noqa: ARG002
        self.statusBar().showMessage(text, 5000)

    def _display_processing_start(self, label: str, cid: str) -> None:  # noqa: ARG002
        self._status_bar.set_processing(label)

    def _display_processing_end(self, cid: str) -> None:  # noqa: ARG002
        self._status_bar.set_processing(None)

    # ==================================================================
    # Streaming display -> ChatDisplay streaming methods
    # ==================================================================

    def _on_block_start(self, cid: str, block_type: str) -> None:
        display = self._display_for_cid(cid)
        if display:
            display.start_streaming_block(block_type)

    def _on_block_delta(self, cid: str, block_type: str, text: str) -> None:
        display = self._display_for_cid(cid)
        if display:
            display.update_streaming_block(text, block_type)

    def _on_block_end(
        self,
        cid: str,
        block_type: str,
        text: str,
        had_start: bool,  # noqa: ARG002
    ) -> None:
        display = self._display_for_cid(cid)
        if display:
            display.end_streaming_block(text, block_type)

    def _on_tool_start(
        self,
        cid: str,
        name: str,
        tool_input: object,
    ) -> None:
        display = self._display_for_cid(cid)
        if display:
            tool_id = ""
            if isinstance(tool_input, dict):
                tool_id = (
                    str(tool_input.get("agent", ""))
                    or str(tool_input.get("instruction", ""))[:60]
                )
            display.add_tool_start_message(name, tool_id)

        # --- Panel auto-show wiring ---
        if name == "todo":
            self._todo_panel.show()
            self._todo_panel.raise_()
        elif name in ("delegate", "task"):
            self._agent_panel.show()
            self._agent_panel.raise_()
            agent_name = ""
            if isinstance(tool_input, dict):
                agent_name = str(tool_input.get("agent", name))
            self._agent_panel.add_agent(agent_name or name)

    def _on_tool_end(
        self,
        cid: str,
        name: str,
        tool_input: object,
        result: object,
    ) -> None:
        display = self._display_for_cid(cid)
        result_preview = str(result)[:200] if result else "done"
        if display:
            display.add_tool_end_message(name, result_preview)

        # --- Panel auto-show wiring ---
        if name == "todo":
            try:
                parsed = json.loads(str(result)) if result else {}
                items = parsed.get("todos", [])
                if not items and isinstance(parsed, list):
                    items = parsed
                if items:
                    self._todo_panel.update_todos(items)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        elif name in ("delegate", "task"):
            agent_name = ""
            if isinstance(tool_input, dict):
                agent_name = str(tool_input.get("agent", name))
            self._agent_panel.update_agent_status(agent_name or name, "completed")

    def _on_usage_update(self, cid: str) -> None:
        handle = self._backend.session_manager.get_handle(cid)
        if handle:
            self._status_bar.set_model(handle.model_name or "")
            self._status_bar.set_tokens(
                handle.total_input_tokens,
                handle.total_output_tokens,
                self._backend._get_context_window(),
            )

    # ==================================================================
    # Session actions
    # ==================================================================

    def _new_session(self) -> None:
        """Start a new session in the current tab."""
        self._backend._cmd_new()
        display = self._current_display()
        if display:
            display.clear_chat()
        self._status_bar.set_session("")
        self._status_bar.set_tokens(0, 0)
        self._agent_panel.clear_agents()
        self._chat_input.setFocus()
        # Refresh sidebar so the list stays current
        self._backend._populate_session_list()

    def _on_session_selected(self, session_id: str) -> None:
        """Handle session selection from the sidebar.

        If the session is already open in a tab, switch to it.
        Otherwise create a new tab and resume the session in the background.
        """
        # 1) Check if this session is already open in a tab
        for i, tab in enumerate(self._tabs):
            if tab.conversation.session_id == session_id:
                self._tab_widget.setCurrentIndex(i)
                return

        # 2) Create a new tab for the resumed session
        conv = ConversationState()
        tab_name = f"Resuming {session_id[:8]}..."
        tab_state = DesktopTabState(
            name=tab_name,
            tab_id=conv.conversation_id,
            conversation=conv,
        )
        self._tabs.append(tab_state)

        display = ChatDisplay()
        display.document().setDefaultStyleSheet(MESSAGE_CSS)
        index = self._tab_widget.addTab(display, tab_name)
        self._cid_to_tab[conv.conversation_id] = index
        self._tab_widget.setCurrentIndex(index)

        # Show loading indicator
        display.add_system_message("Loading session...")
        self._status_bar.set_session(session_id[:12])
        self._status_bar.set_processing("Resuming")

        # 3) Resume on background thread
        thread = threading.Thread(
            target=self._backend._resume_session_worker,
            args=(session_id, conv.conversation_id),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Session signal handlers (main thread, called via Qt signals)
    # ------------------------------------------------------------------

    def _on_session_list_ready(self, sessions: list) -> None:
        """Sidebar data arrived from background thread."""
        self._session_sidebar.set_sessions(sessions)

    def _on_session_resumed(self, cid: str, session_id: str, messages: list) -> None:
        """Session resume succeeded -- replay transcript into the tab."""
        self._status_bar.set_processing(None)
        self._status_bar.set_session(session_id[:12])

        # Update tab title
        tab_index = self._cid_to_tab.get(cid)
        if tab_index is not None:
            short = session_id[:8]
            self._tab_widget.setTabText(tab_index, short)
            if 0 <= tab_index < len(self._tabs):
                self._tabs[tab_index].name = short
                self._tabs[tab_index].conversation.session_id = session_id

        # Get the ChatDisplay for this conversation
        display = self._display_for_cid(cid)
        if display:
            display.clear_chat()
            self._load_transcript_into_display(display, messages)
            display.add_system_message(
                f"Resumed session `{session_id[:12]}...`  "
                f"({len(messages)} blocks loaded)"
            )

        # Wire streaming callbacks for future messages
        for tab in self._tabs:
            if tab.tab_id == cid:
                self._backend._wire_streaming_callbacks(cid, tab.conversation)
                break

        # Sync backend conversation if this is the active tab
        if tab_index == self._tab_widget.currentIndex():
            self._backend._conversation = self._tabs[tab_index].conversation

        # Update usage display
        handle = self._backend.session_manager.get_handle(cid)
        if handle:
            self._status_bar.set_model(handle.model_name or "")

        self._chat_input.setFocus()

        # Refresh sidebar (session order may have changed)
        self._backend._populate_session_list()

    def _on_session_resume_failed(self, session_id: str, error: str) -> None:
        """Session resume failed -- show error in the tab."""
        self._status_bar.set_processing(None)
        # Find the tab that was loading this session and show error there
        display = self._current_display()
        if display:
            display.clear_chat()
            display.add_error_message(
                f"Failed to resume session {session_id[:12]}...\n{error}"
            )

    # ------------------------------------------------------------------
    # Transcript replay
    # ------------------------------------------------------------------

    @staticmethod
    def _load_transcript_into_display(
        display: ChatDisplay, messages: list[dict]
    ) -> None:
        """Replay transcript blocks into a ChatDisplay widget.

        *messages* is a list of dicts with keys ``kind``, ``content``,
        ``tool_name`` -- produced by ``parse_message_blocks`` in the
        background thread.
        """
        for msg in messages:
            kind = msg.get("kind", "")
            content = msg.get("content", "")
            tool_name = msg.get("tool_name", "")

            if kind == "user":
                display.add_user_message(content)
            elif kind == "text":
                display.add_assistant_message(content)
            elif kind == "thinking":
                # Show thinking blocks as collapsed system messages
                preview = content[:200] + ("..." if len(content) > 200 else "")
                display.add_system_message(f"*Thinking:* {preview}")
            elif kind == "tool_use":
                display.add_tool_message(tool_name, "called")
            elif kind == "tool_result":
                preview = content[:200] if content else "done"
                display.add_tool_message(tool_name or "tool", preview)

    # ==================================================================
    # Find / Search
    # ==================================================================

    def _show_find(self) -> None:
        self._find_bar.show_bar()

    def _on_find(self, text: str) -> None:
        display = self._current_display()
        if display and text:
            found = display.find(text)
            self._find_bar.set_count(1 if found else 0, 1 if found else 0)

    def _on_find_next(self) -> None:
        display = self._current_display()
        if display:
            display.find(self._find_bar._input.text())

    def _on_find_prev(self) -> None:
        from PySide6.QtGui import QTextDocument

        display = self._current_display()
        if display:
            display.find(
                self._find_bar._input.text(),
                QTextDocument.FindFlag.FindBackward,
            )

    # ==================================================================
    # View actions
    # ==================================================================

    def _toggle_sidebar(self) -> None:
        visible = self._session_sidebar.isVisible()
        self._session_sidebar.setVisible(not visible)
        # Refresh session list when showing the sidebar
        if not visible:
            self._backend._populate_session_list()

    def _zoom_in(self) -> None:
        self._font_size = min(self._font_size + 1, 24)
        self._apply_font_size()

    def _zoom_out(self) -> None:
        self._font_size = max(self._font_size - 1, 9)
        self._apply_font_size()

    def _apply_font_size(self) -> None:
        for i in range(self._tab_widget.count()):
            widget = self._tab_widget.widget(i)
            if isinstance(widget, ChatDisplay):
                font = widget.font()
                font.setPointSize(self._font_size)
                widget.setFont(font)
        font = self._chat_input.font()
        font.setPointSize(self._font_size)
        self._chat_input.setFont(font)

    def _clear_current_chat(self) -> None:
        display = self._current_display()
        if display:
            display.clear_chat()

    # ==================================================================
    # Window state persistence (QSettings)
    # ==================================================================

    def _save_state(self) -> None:
        settings = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.setValue("mainSplitter", self._main_splitter.saveState())
        settings.setValue("centerSplitter", self._center_splitter.saveState())
        settings.setValue("fontSize", self._font_size)

    def _restore_state(self) -> None:
        settings = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)  # type: ignore[arg-type]
        window_state = settings.value("windowState")
        if window_state:
            self.restoreState(window_state)  # type: ignore[arg-type]
        main_sp = settings.value("mainSplitter")
        if main_sp:
            self._main_splitter.restoreState(main_sp)  # type: ignore[arg-type]
        center_sp = settings.value("centerSplitter")
        if center_sp:
            self._center_splitter.restoreState(center_sp)  # type: ignore[arg-type]
        saved_size = settings.value("fontSize")
        if saved_size is not None:
            self._font_size = int(saved_size)
            self._apply_font_size()

    # ==================================================================
    # Autosave (Phase 11)
    # ==================================================================

    def _do_autosave_all(self) -> None:
        """Persist lightweight state for every open tab to JSON.

        Called by the 60-second QTimer and by closeEvent.  Data is collected
        on the main thread (fast -- just reads memory), then written to disk
        on a background thread to avoid blocking the UI.
        """
        # Snapshot the current input text into the active tab state
        if 0 <= self._current_tab_index < len(self._tabs):
            self._tabs[
                self._current_tab_index
            ].input_text = self._chat_input.toPlainText()

        tabs_data: list[dict[str, Any]] = []
        for i, tab_state in enumerate(self._tabs):
            widget = self._tab_widget.widget(i)
            html_content = ""
            scroll_pos = 0
            if isinstance(widget, ChatDisplay):
                html_content = widget.toHtml()
                scroll_pos = widget.verticalScrollBar().value()

            tabs_data.append(
                {
                    "tab_id": tab_state.tab_id,
                    "name": tab_state.name,
                    "input_text": tab_state.input_text,
                    "html_content": html_content,
                    "scroll_position": scroll_pos,
                }
            )

        # Write on background thread to avoid blocking the UI
        threading.Thread(
            target=self._write_autosave,
            args=(tabs_data, self._current_tab_index),
            daemon=True,
        ).start()

    def _write_autosave(self, tabs_data: list, current_tab: int) -> None:
        """Background thread: write autosave JSON to disk."""
        _AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        save_path = _AUTOSAVE_DIR / "tabs.json"
        try:
            save_path.write_text(
                json.dumps({"tabs": tabs_data, "current_tab": current_tab})
            )
        except Exception:
            logger.debug("Autosave write failed", exc_info=True)

    def _try_restore_autosave(self) -> bool:
        """Check for an autosave file and offer to restore open tabs.

        Returns True if tabs were restored, False otherwise.
        """
        save_path = _AUTOSAVE_DIR / "tabs.json"
        if not save_path.exists():
            return False

        try:
            data = json.loads(save_path.read_text())
        except Exception:
            logger.debug("Autosave file unreadable, ignoring", exc_info=True)
            save_path.unlink(missing_ok=True)
            return False

        tabs = data.get("tabs", [])
        if not tabs:
            save_path.unlink(missing_ok=True)
            return False

        # Only offer to restore if at least one tab had content
        has_content = any(t.get("html_content", "").strip() for t in tabs)
        if not has_content:
            save_path.unlink(missing_ok=True)
            return False

        reply = QMessageBox.question(
            self,
            "Restore Session",
            f"Found {len(tabs)} autosaved tab(s). Restore?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            save_path.unlink(missing_ok=True)
            return False

        # Restore each tab
        for tab_data in tabs:
            conv = ConversationState()
            tab_name = tab_data.get("name", "Restored")
            tab_state = DesktopTabState(
                name=tab_name,
                tab_id=conv.conversation_id,
                conversation=conv,
                input_text=tab_data.get("input_text", ""),
            )
            self._tabs.append(tab_state)

            display = ChatDisplay()
            display.document().setDefaultStyleSheet(MESSAGE_CSS)
            index = self._tab_widget.addTab(display, tab_name)
            self._cid_to_tab[conv.conversation_id] = index

            # Restore HTML content
            html_content = tab_data.get("html_content", "")
            if html_content:
                display.setHtml(html_content)
                # Re-apply stylesheet (setHtml replaces the document)
                display.document().setDefaultStyleSheet(MESSAGE_CSS)

            # Restore scroll position (deferred so layout settles first)
            scroll_pos = tab_data.get("scroll_position", 0)
            if scroll_pos:
                QTimer.singleShot(
                    100,
                    lambda sp=scroll_pos, d=display: d.verticalScrollBar().setValue(sp),
                )

        # Switch to the previously-active tab
        target = data.get("current_tab", 0)
        if 0 <= target < self._tab_widget.count():
            self._tab_widget.setCurrentIndex(target)

        # Restore input text for the active tab
        if 0 <= self._current_tab_index < len(self._tabs):
            self._chat_input.setPlainText(
                self._tabs[self._current_tab_index].input_text
            )

        self._chat_input.setFocus()
        save_path.unlink(missing_ok=True)
        return True

    def closeEvent(self, event: object) -> None:  # noqa: N802
        """Save window state and autosave all open tabs on close."""
        self._autosave_timer.stop()
        self._save_state()
        self._do_autosave_all()
        super().closeEvent(event)  # type: ignore[arg-type]
