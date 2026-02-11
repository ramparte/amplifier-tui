"""WebApp: web frontend inheriting SharedAppBase + all 16 command mixins."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from amplifier_tui.core.app_base import SharedAppBase
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

logger = logging.getLogger(__name__)

# Shared Amplifier home directory for persistence stores
_amp_home = Path.home() / ".amplifier"
_amp_home.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Minimal FileWatcher stub (web doesn't do filesystem polling)
# ------------------------------------------------------------------
class _WebFileWatcher:
    """Minimal FileWatcher stub for web."""

    def __init__(self) -> None:
        self.watched_files: dict[str, Any] = {}

    def add(self, path: str, interval: float | None = None) -> None:  # noqa: ARG002
        pass

    def remove(self, path: str) -> None:  # noqa: ARG002
        pass

    def check(self) -> None:
        pass


# ------------------------------------------------------------------
# WebApp
# ------------------------------------------------------------------
class WebApp(
    SharedAppBase,
    GitCommandsMixin,
    TokenCommandsMixin,
    AgentCommandsMixin,
    RecipeCommandsMixin,
    BranchCommandsMixin,
    CompareCommandsMixin,
    ContentCommandsMixin,
    DashboardCommandsMixin,
    FileCommandsMixin,
    PersistenceCommandsMixin,
    PluginCommandsMixin,
    ReplayCommandsMixin,
    ShellCommandsMixin,
    ThemeCommandsMixin,
    ToolCommandsMixin,
    WatchCommandsMixin,
):
    """Web frontend app inheriting shared backend + all command mixins."""

    def __init__(self, websocket: Any) -> None:
        super().__init__()
        self._ws = websocket
        self._loop: asyncio.AbstractEventLoop | None = None
        self.session_manager = SessionManager()

        # ==============================================================
        # Category 1: Data Attributes
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
        self._clipboard_store = ClipboardStore(
            _amp_home / "tui-clipboard-ring.json"
        )

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
        self._file_watcher = _WebFileWatcher()
        self._watched_files = self._file_watcher.watched_files

    # ------------------------------------------------------------------
    # Thread-safe WebSocket send
    # ------------------------------------------------------------------

    def _send_event(self, event: dict[str, Any]) -> None:
        """Thread-safe WebSocket send.  Can be called from background threads."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._ws_send_json(event), self._loop)

    async def _ws_send_json(self, event: dict[str, Any]) -> None:
        """Actually send JSON over WebSocket (must run on event loop)."""
        try:
            await self._ws.send_json(event)
        except Exception:
            logger.debug("WebSocket send failed", exc_info=True)

    # ------------------------------------------------------------------
    # Abstract display methods (SharedAppBase)
    # ------------------------------------------------------------------

    def _add_system_message(self, text: str, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
        self._send_event({"type": "system_message", "text": text})

    def _add_user_message(self, text: str, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
        self._send_event({"type": "user_message", "text": text})

    def _add_assistant_message(self, text: str, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
        self._send_event({"type": "assistant_message", "text": text})

    def _show_error(self, text: str) -> None:
        self._send_event({"type": "error", "text": text})

    def _update_status(self, text: str) -> None:
        self._send_event({"type": "status", "text": text})

    def _start_processing(self, label: str = "Thinking") -> None:
        self.is_processing = True
        self._send_event({"type": "processing_start", "label": label})

    def _finish_processing(self) -> None:
        self.is_processing = False
        self._send_event({"type": "processing_end"})

    # ------------------------------------------------------------------
    # Abstract streaming methods (called from BACKGROUND THREAD)
    # ------------------------------------------------------------------

    def _on_stream_block_start(self, block_type: str) -> None:
        self._send_event({"type": "stream_start", "block_type": block_type})

    def _on_stream_block_delta(self, block_type: str, accumulated_text: str) -> None:
        self._send_event({
            "type": "stream_delta",
            "block_type": block_type,
            "text": accumulated_text,
        })

    def _on_stream_block_end(
        self, block_type: str, final_text: str, had_block_start: bool
    ) -> None:
        self._send_event({
            "type": "stream_end",
            "block_type": block_type,
            "text": final_text,
        })

    def _on_stream_tool_start(self, name: str, tool_input: dict) -> None:  # type: ignore[type-arg]
        self._send_event({
            "type": "tool_start",
            "tool_name": name,
            "tool_input": tool_input,
        })

    def _on_stream_tool_end(self, name: str, tool_input: dict, result: str) -> None:  # type: ignore[type-arg]
        self._send_event({
            "type": "tool_end",
            "tool_name": name,
            "tool_input": tool_input,
            "result": result,
        })

    def _on_stream_usage_update(self) -> None:
        sm = self.session_manager
        if sm:
            self._send_event({
                "type": "usage_update",
                "input_tokens": sm.total_input_tokens,
                "output_tokens": sm.total_output_tokens,
                "model": sm.model_name or "",
            })

    # ==================================================================
    # Category 4: Utility Methods
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

    def _send_message_worker(self, text: str) -> None:
        """Sync wrapper - web uses handle_message instead."""
        pass  # Not used in web (web uses async handle_message)

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
    # Category 5: Persistence Delegate Methods
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
        pass  # Not critical for web

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

    def _bookmark_last_message(self, label: str = "") -> None:
        self._add_system_message("Bookmarking not yet supported in web interface")

    def _bookmark_nth_message(self, n: int, label: str = "") -> None:
        self._add_system_message("Bookmarking not yet supported in web interface")

    def _remove_bookmark(self, index: int) -> None:
        self._add_system_message("Bookmark removal not yet supported in web interface")

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
        self._add_system_message("Undo not yet supported in web interface")

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
    # Category 6: Textual-Specific Stubs (no-ops for web)
    # ==================================================================

    def suspend(self) -> None:
        """Textual suspend - no-op for web."""

    def query_one(self, selector: str, *args: Any) -> Any:
        """Textual query_one - not available in web."""
        raise RuntimeError(f"query_one('{selector}') not available in web interface")

    def set_interval(self, interval: float, callback: Any, *args: Any, **kwargs: Any) -> None:  # type: ignore[return]
        """Textual set_interval - return None (timer not needed for web)."""
        return None  # type: ignore[return-value]

    @property
    def theme(self) -> str:
        return "dark"

    def action_copy_response(self) -> None:
        pass

    def action_open_editor(self) -> None:
        self._add_system_message("Editor not available in web interface")

    def action_show_shortcuts(self) -> None:
        self._add_system_message(
            "**Web Keyboard Shortcuts**\n\n"
            "| Shortcut | Action |\n"
            "|----------|--------|\n"
            "| `Enter` | Send message |\n"
            "| `Shift+Enter` | New line |\n"
            "| `Up/Down` | Command history |\n"
            "| `Tab` | Complete /command |\n"
            "| `Escape` | Clear input |\n"
            "| `/` | Focus input + start command |\n"
            "| `Ctrl+L` | Focus input |\n"
            "| `Ctrl+/` | Show help |\n"
            "| `Ctrl+Shift+N` | New session |\n"
            "| `Ctrl+Shift+S` | Session list |\n"
            "| `Ctrl+Shift+K` | Clear chat |\n"
            "| `Ctrl+Shift+G` | Git status |\n"
            "| `Ctrl+Shift+T` | Token info |\n"
            "| `Ctrl+Shift+D` | Dashboard |\n"
            "\n*Note: Uses Ctrl+Shift combos to avoid browser shortcut conflicts.*"
        )

    # UI update stubs (no-op for web - handled by events)
    def _apply_theme_to_all_widgets(self) -> None:
        pass

    def _preview_theme(self, name: str) -> None:
        pass

    def _revert_theme_preview(self) -> None:
        pass

    def _clear_welcome(self) -> None:
        pass

    def _populate_session_list(self) -> None:
        pass

    def _play_bell(self) -> None:
        pass

    def _update_attachment_indicator(self) -> None:
        pass

    def _update_mode_display(self) -> None:
        pass

    def _update_pinned_panel(self) -> None:
        pass

    def _update_system_indicator(self) -> None:
        pass

    def _update_token_display(self) -> None:
        pass

    def _remove_all_pin_classes(self) -> None:
        pass

    def _jump_to_bookmark(self, index: int) -> None:
        pass

    def _cmd_agent_tree_panel(self, args: str = "") -> None:
        self._add_system_message("Agent tree panel: use /agents instead")

    def _cmd_fork_tab(self) -> None:
        self._add_system_message("Tab forking not available in web interface")

    # Include/attach (simplified for web)
    def _include_and_send(self, path: str, prompt: str = "") -> None:
        content = self._read_file_for_include(path)
        if content:
            msg = f"[Included: {path}]\n{content}"
            if prompt:
                msg = f"{prompt}\n\n{msg}"
            self._add_system_message(f"Including file: {path}")

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
        pass

    def _autosave_restore(self) -> None:
        pass

    def _edit_snippet_in_editor(self, name: str) -> None:
        self._add_system_message(
            "Editor not available in web interface. Use /snippet save instead."
        )

    def _start_watch_timer(self) -> None:
        pass  # File watching timer not implemented for web yet

    def _stop_watch_timer(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Web-only: simple /model handler (not in a mixin)
    # ------------------------------------------------------------------
    def _cmd_model(self, text: str) -> None:
        """Show or switch the model."""
        text = text.strip()
        sm = self.session_manager
        if not text or text == "/model":
            model = sm.model_name if sm else "unknown"
            self._add_system_message(f"Current model: **{model}**")
            return
        # Attempt to set model
        new_model = text
        if sm:
            sm.model_name = new_model
            self._add_system_message(f"Model set to: **{new_model}**")
        else:
            self._show_error("No session manager available")

    # Web-only: /sessions handler (not in a mixin)
    def _cmd_sessions(self, args: str) -> None:
        """List recent sessions."""
        self._add_system_message(
            "Session listing is available in the sidebar. "
            "Use /new to start a new session."
        )

    # ------------------------------------------------------------------
    # Command routing
    # ------------------------------------------------------------------

    def _route_command(self, text: str) -> bool:
        """Route slash commands.  Returns True if handled."""
        if not text.startswith("/"):
            return False

        parts = text.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Primary command map -- maps /cmd to the mixin handler
        handlers: dict[str, Any] = {
            "/help": lambda: self._cmd_help_web(),
            # Git
            "/git": lambda: self._cmd_git(args),
            "/diff": lambda: self._cmd_diff(args),
            "/gitstatus": lambda: self._cmd_git(""),
            "/gs": lambda: self._cmd_git(""),
            # Tokens / info
            "/tokens": lambda: self._cmd_tokens(),
            "/token": lambda: self._cmd_tokens(),
            "/stats": lambda: self._cmd_stats(args),
            "/info": lambda: self._cmd_info(),
            "/context": lambda: self._cmd_context(args),
            "/keys": lambda: self._cmd_keys(),
            # Agents / recipes / tools
            "/agents": lambda: self._cmd_agents(args),
            "/recipe": lambda: self._cmd_recipe(args),
            "/tools": lambda: self._cmd_tools(args),
            # Branching
            "/compare": lambda: self._cmd_compare(args),
            "/branch": lambda: self._cmd_branch(args),
            "/branches": lambda: self._cmd_branches(args),
            "/fork": lambda: self._cmd_fork(args),
            # Replay / dashboard / watch
            "/replay": lambda: self._cmd_replay(args),
            "/dashboard": lambda: self._cmd_dashboard(args),
            "/watch": lambda: self._cmd_watch(args),
            # Plugins / shell / theme
            "/plugins": lambda: self._cmd_plugins(args),
            "/shell": lambda: self._cmd_shell(args),
            "/theme": lambda: self._cmd_theme(args),
            # Content
            "/system": lambda: self._cmd_system(args),
            "/mode": lambda: self._cmd_mode(args),
            "/modes": lambda: self._cmd_mode(""),
            "/model": lambda: self._cmd_model(args),
            "/attach": lambda: self._cmd_attach(args),
            "/cat": lambda: self._cmd_cat(args),
            "/include": lambda: self._cmd_include(args),
            "/history": lambda: self._cmd_history(args),
            "/copy": lambda: self._cmd_copy(args),
            "/redo": lambda: self._cmd_redo(args),
            "/retry": lambda: self._cmd_retry(args),
            "/undo": lambda: self._cmd_undo(args),
            "/autosave": lambda: self._cmd_autosave(args),
            # Persistence
            "/ref": lambda: self._cmd_ref(args),
            "/refs": lambda: self._cmd_ref(args),
            "/alias": lambda: self._cmd_alias(args),
            "/snippet": lambda: self._cmd_snippet(args),
            "/snippets": lambda: self._cmd_snippet(""),
            "/snip": lambda: self._cmd_snippet(args),
            "/template": lambda: self._cmd_template(args),
            "/templates": lambda: self._cmd_template(""),
            "/draft": lambda: self._cmd_draft(args),
            "/drafts": lambda: self._cmd_drafts(args),
            "/note": lambda: self._cmd_note(args),
            "/notes": lambda: self._show_notes(),
            "/bookmark": lambda: self._cmd_bookmark(args),
            "/bookmarks": lambda: self._cmd_bookmarks(args),
            "/bm": lambda: self._cmd_bookmark(args),
            "/tag": lambda: self._cmd_tag(args),
            "/tags": lambda: self._cmd_tag("list-all"),
            "/pin": lambda: self._cmd_pin_msg(args),
            "/pins": lambda: self._cmd_pins(args),
            "/unpin": lambda: self._cmd_unpin(args),
            "/pin-session": lambda: self._cmd_pin_session(args),
            "/clipboard": lambda: self._cmd_clipboard(args),
            "/clip": lambda: self._cmd_clipboard(args),
            # Session management
            "/new": lambda: self._handle_new_session(),
            "/clear": lambda: self._send_event({"type": "clear"}),
            "/sessions": lambda: self._cmd_sessions(args),
            "/session": lambda: self._cmd_sessions(args),
            "/list": lambda: self._cmd_sessions(args),
            # File commands
            "/run": lambda: self._cmd_run(args),
            "/editor": lambda: self._cmd_editor(args),
            "/edit": lambda: self.action_open_editor(),
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                handler()
            except Exception as exc:
                self._show_error(f"Command error: {exc}")
            return True

        # Try plugin commands
        if self._plugin_loader.execute_command(cmd.lstrip("/"), self, args):
            return True

        self._add_system_message(
            f"Unknown command: {cmd}\nType /help for available commands."
        )
        return True

    def _cmd_help_web(self) -> None:
        """Show categorized help for all available commands."""
        self._add_system_message(
            "**Amplifier Web Commands**\n"
            "\n"
            "**Session**\n"
            "  /new            Start a new session\n"
            "  /clear          Clear the chat display\n"
            "  /sessions       List sessions\n"
            "  /model [name]   Show or switch model\n"
            "\n"
            "**Information**\n"
            "  /help           Show this help\n"
            "  /info           Session info\n"
            "  /stats [sub]    Session statistics (tools, tokens, time)\n"
            "  /tokens         Token usage summary\n"
            "  /context [sub]  Context window analysis\n"
            "  /keys           API key status\n"
            "  /dashboard [sub] Session dashboard\n"
            "\n"
            "**Content & Modes**\n"
            "  /system [text]  Set/view/clear system prompt\n"
            "  /mode [name]    Set/view mode (planning, research, review, debug)\n"
            "  /modes          List available modes\n"
            "  /copy [N]       Copy message to clipboard\n"
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
            "  /watch [sub]    Watch files for changes\n"
            "  /autosave [sub] Auto-save settings\n"
            "\n"
            "**Persistence**\n"
            "  /alias          Manage command aliases\n"
            "  /snippet        Manage reusable snippets\n"
            "  /template       Manage prompt templates\n"
            "  /draft          Save/load drafts\n"
            "  /drafts         List all drafts\n"
            "  /note           Add session notes\n"
            "  /notes          Show session notes\n"
            "  /bookmark       Bookmark messages\n"
            "  /bookmarks      List bookmarks\n"
            "  /ref            Manage references\n"
            "  /tag            Manage session tags\n"
            "  /pin            Pin a message\n"
            "  /pins           Show pinned messages\n"
            "  /unpin          Remove a pin\n"
            "  /clipboard      Clipboard ring\n"
            "\n"
            "**AI & Tools**\n"
            "  /agents [sub]   Agent delegation tree\n"
            "  /recipe [sub]   Recipe pipeline\n"
            "  /tools [sub]    Tool introspection\n"
            "  /plugins [sub]  Plugin management\n"
            "\n"
            "**Branching**\n"
            "  /fork [name]    Fork conversation\n"
            "  /branch [name]  Switch branch\n"
            "  /branches       List branches\n"
            "  /compare [sub]  Model A/B testing\n"
            "  /replay [sub]   Session replay\n"
            "\n"
            "**Appearance**\n"
            "  /theme [name]   Switch theme\n"
            "\n"
            "**Git**\n"
            "  /git [sub]      Git status/operations\n"
            "  /diff [args]    Show git diff\n"
        )

    def _handle_new_session(self) -> None:
        """Start a new session.  Actual creation deferred to handle_message."""
        if self.session_manager:
            # Reset for fresh session
            self.session_manager.session = None
            self.session_manager.reset_usage()
        self._amplifier_ready = False
        self._send_event({"type": "clear"})
        self._add_system_message("Starting new session... Send a message to begin.")

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def handle_message(self, text: str) -> None:
        """Handle a user message (chat or command)."""
        text = text.strip()
        if not text:
            return

        if text.startswith("/"):
            self._route_command(text)
            return

        # Chat message
        self._add_user_message(text)
        self._start_processing()
        self._wire_streaming_callbacks()
        self._tool_count_this_turn = 0
        self._got_stream_content = False

        try:
            if not self.session_manager.session:
                await self.session_manager.start_new_session()
                self._amplifier_ready = True
                self._send_event({
                    "type": "session_started",
                    "session_id": self.session_manager.session_id or "",
                    "model": self.session_manager.model_name or "",
                })

            response = await self.session_manager.send_message(text)

            # If streaming didn't produce content, show the final response
            if not self._got_stream_content and response:
                self._add_assistant_message(response)
        except Exception as exc:
            self._show_error(f"Error: {exc}")
            logger.exception("Message handling error")
        finally:
            self._finish_processing()

    async def initialize(self) -> None:
        """Initialize the app (called once when WebSocket connects)."""
        self._loop = asyncio.get_event_loop()
        self._send_event({"type": "connected", "status": "ready"})

    async def shutdown(self) -> None:
        """Clean up when WebSocket disconnects."""
        if self.session_manager and self.session_manager.session:
            try:
                await self.session_manager.end_session()
            except Exception:
                logger.debug("Error ending session on disconnect", exc_info=True)
