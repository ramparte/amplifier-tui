"""Session lifecycle commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

from textual import work
from textual.widgets import Tree

from ..platform import amplifier_projects_dir
from ..preferences import (
    save_session_sort,
)
from ..log import logger
from ..session_manager import SessionManager


class SessionCommandsMixin:
    """Session lifecycle commands."""

    def _load_session_list(self) -> None:
        """Show loading state then populate in background."""
        if not self._amplifier_available:
            return
        tree = self.query_one("#session-tree", Tree)
        tree.clear()
        tree.root.add_leaf("Loading sessions...")
        self._load_sessions_worker()

    @work(thread=True)
    def _load_sessions_worker(self) -> None:
        """Load session list in background thread."""
        sessions = SessionManager.list_all_sessions(limit=50)
        self.call_from_thread(self._populate_session_list, sessions)

    def _cmd_fork_tab(self, args: str) -> None:
        """Fork conversation at a specific point into a new tab (legacy)."""
        args = args.strip()

        # Get current messages
        messages = self._search_messages
        if not messages:
            self._add_system_message("No messages to fork from.")
            return

        # Determine fork point (N is 1-based from bottom)
        if args and args.isdigit():
            n = int(args)
            if n < 1 or n > len(messages):
                self._add_system_message(
                    f"Invalid message number: {n}. Must be 1\u2013{len(messages)}."
                )
                return
            fork_idx = len(messages) - n
        else:
            # Fork from last message (include all)
            fork_idx = len(messages) - 1

        # Collect message data before switching tabs (role + text only)
        fork_data = [(role, txt) for role, txt, _ in messages[: fork_idx + 1]]
        total_messages = len(messages)

        # Save source tab info
        source_tab = self._tabs[self._active_tab_index]
        source_tab_name = source_tab.name
        source_system_prompt = self._system_prompt
        source_system_preset = self._system_preset_name

        # Create new tab without welcome message
        new_tab_name = f"Fork of {source_tab_name}"
        self._create_new_tab(name=new_tab_name, show_welcome=False)

        # Copy system prompt from source tab
        self._system_prompt = source_system_prompt
        self._system_preset_name = source_system_preset

        # Replay messages into the new tab
        for role, txt in fork_data:
            if role == "user":
                self._add_user_message(txt)
            elif role == "assistant":
                self._add_assistant_message(txt)
            # Skip system/thinking/note messages in fork

        # Add fork indicator
        fork_msg_count = len(fork_data)
        self._add_system_message(
            f"(forked from {source_tab_name} at msg {fork_msg_count}/{total_messages})\n"
            f"Continue the conversation from here.\n"
            f"Note: AI context starts fresh \u2014 the AI won't recall earlier messages\n"
            f"until you send a new message in this tab."
        )

        # Scroll to bottom
        try:
            chat = self._active_chat_view()
            chat.scroll_end(animate=False)
        except Exception:
            logger.debug("Failed to scroll chat to bottom", exc_info=True)

    def _cmd_clear(self) -> None:
        self.action_clear_chat()
        # No system message needed - the chat is cleared

    def _cmd_new(self) -> None:
        self.action_new_session()
        # new session shows its own welcome message

    def _cmd_sessions(self, args: str) -> None:
        """Manage and search saved sessions."""
        args = args.strip()

        # No args: toggle sidebar (backward compatible)
        if not args:
            self.action_toggle_sidebar()
            state = "opened" if self._sidebar_visible else "closed"
            self._add_system_message(f"Session sidebar {state}.")
            return

        if args.lower() == "help":
            self._add_system_message(
                "Session Management\n\n"
                "  /sessions              Toggle session sidebar\n"
                "  /sessions list         List all saved sessions\n"
                "  /sessions recent       Show 10 most recent sessions\n"
                "  /sessions search <q>   Search across all sessions\n"
                "  /sessions open <id>    Open/resume a session by ID\n"
                "  /sessions delete <id>  Delete a session (with confirmation)\n"
                "  /sessions info <id>    Show session details\n"
                "\n"
                "Partial session IDs are supported (e.g. /sessions open 7de3)."
            )
            return

        parts = args.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "list":
            self._sessions_list()
        elif cmd == "recent":
            self._sessions_recent()
        elif cmd == "search":
            if not arg:
                self._add_system_message("Usage: /sessions search <query>")
                return
            self._sessions_search(arg)
        elif cmd == "open":
            if not arg:
                self._add_system_message("Usage: /sessions open <session-id>")
                return
            self._sessions_open(arg)
        elif cmd == "delete":
            if not arg:
                self._add_system_message("Usage: /sessions delete <session-id>")
                return
            self._sessions_delete(arg)
        elif cmd == "info":
            if not arg:
                self._add_system_message("Usage: /sessions info <session-id>")
                return
            self._sessions_info(arg)
        else:
            # Treat entire args as a search query
            self._sessions_search(args)

    def _sessions_search(self, query: str) -> None:
        """Search across all saved sessions for matching text."""
        projects_dir = amplifier_projects_dir()
        if not projects_dir.exists():
            self._add_system_message("No saved sessions found.")
            return

        query_lower = query.lower()
        results: list[dict] = []
        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue

            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Skip sub-sessions
                if "_" in session_dir.name:
                    continue

                sid = session_dir.name
                transcript = session_dir / "transcript.jsonl"
                if not transcript.exists():
                    continue

                try:
                    mtime = transcript.stat().st_mtime
                except OSError:
                    continue

                # Search metadata first (name, description)
                meta_match = ""
                metadata_path = session_dir / "metadata.json"
                meta_name = ""
                meta_desc = ""
                if metadata_path.exists():
                    try:
                        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                        meta_name = meta.get("name", "")
                        meta_desc = meta.get("description", "")
                        for field in (meta_name, meta_desc):
                            if query_lower in field.lower():
                                meta_match = field
                                break
                    except (OSError, json.JSONDecodeError):
                        logger.debug(
                            "Failed to read metadata from %s",
                            metadata_path,
                            exc_info=True,
                        )

                # Search custom names / titles
                if not meta_match:
                    for field in (
                        custom_names.get(sid, ""),
                        session_titles.get(sid, ""),
                    ):
                        if field and query_lower in field.lower():
                            meta_match = field
                            break

                # Search filename
                if not meta_match and query_lower in sid.lower():
                    meta_match = f"(session ID: {sid})"

                # If metadata matched, record and skip transcript scan
                if meta_match:
                    results.append(
                        {
                            "session_id": sid,
                            "mtime": mtime,
                            "date_str": datetime.fromtimestamp(mtime).strftime(
                                "%m/%d %H:%M"
                            ),
                            "match_preview": meta_match.replace("\n", " ")[:100],
                            "match_role": "metadata",
                            "name": meta_name,
                            "description": meta_desc,
                        }
                    )
                    continue

                # Scan transcript lines for content match
                try:
                    with open(transcript, "r", encoding="utf-8") as fh:
                        for raw_line in fh:
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            try:
                                msg = json.loads(raw_line)
                            except json.JSONDecodeError:
                                continue
                            role = msg.get("role", "")
                            if role not in ("user", "assistant"):
                                continue
                            text = self._extract_transcript_text(msg.get("content", ""))
                            if query_lower in text.lower():
                                preview = text.replace("\n", " ")[:120]
                                results.append(
                                    {
                                        "session_id": sid,
                                        "mtime": mtime,
                                        "date_str": datetime.fromtimestamp(
                                            mtime
                                        ).strftime("%m/%d %H:%M"),
                                        "match_preview": preview,
                                        "match_role": role,
                                        "name": meta_name,
                                        "description": meta_desc,
                                    }
                                )
                                break  # One match per session is enough
                except OSError:
                    continue

        if not results:
            self._add_system_message(f"No sessions matching '{query}'.")
            return

        # Sort by mtime descending (most recent first)
        results.sort(key=lambda r: r["mtime"], reverse=True)

        lines = [f"Found {len(results)} session(s) matching '{query}':\n"]
        for i, r in enumerate(results[:20], 1):
            sid_short = r["session_id"][:8]
            label = self._session_label(r, custom_names, session_titles)
            lines.append(f"  {i:2}. {r['date_str']}  [{sid_short}]  {label}")
            preview = r["match_preview"][:80]
            lines.append(f"      [{r['match_role']}] {preview}")

        if len(results) > 20:
            lines.append(f"\n... and {len(results) - 20} more")
        lines.append("\nUse /sessions open <id> to resume a session.")
        self._add_system_message("\n".join(lines))

    def _cmd_quit(self) -> None:
        # Use call_later so the current handler finishes before quit runs
        self.call_later(self.action_quit)

    def _cmd_sort(self, text: str) -> None:
        """Show or change the session sort order in the sidebar."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if not arg:
            current = getattr(self._prefs, "session_sort", "date")
            self._add_system_message(
                f"Session sort: {current}\n"
                f"Available: {', '.join(self._SORT_MODES)}\n"
                f"Usage: /sort <mode>"
            )
            return

        if arg not in self._SORT_MODES:
            self._add_system_message(
                f"Unknown sort mode '{arg}'.\nAvailable: {', '.join(self._SORT_MODES)}"
            )
            return

        self._prefs.session_sort = arg
        save_session_sort(arg)

        # Refresh sidebar if it has data loaded
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        self._add_system_message(f"Sessions sorted by: {arg}")

    def _cmd_delete(self, text: str) -> None:
        """Delete a session with two-step confirmation."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # Handle confirmation
        if arg == "confirm" and self._pending_delete:
            session_id = self._pending_delete
            self._pending_delete = None
            self._execute_session_delete(session_id)
            return

        # Handle cancellation
        if arg == "cancel":
            self._pending_delete = None
            self._add_system_message("Delete cancelled.")
            return

        # Determine which session to delete
        if arg and arg not in ("confirm", "cancel"):
            session_id = arg
        elif self.session_manager and getattr(self.session_manager, "session_id", None):
            session_id = self.session_manager.session_id
        else:
            self._add_system_message("No active session to delete.")
            return

        # Set up confirmation
        self._pending_delete = session_id
        short_id = session_id[:12] if session_id else "unknown"
        self._add_system_message(
            f"Delete session {short_id}...?\n"
            "Type /delete confirm to proceed or /delete cancel to abort."
        )
