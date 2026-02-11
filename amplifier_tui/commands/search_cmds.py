"""Search and grep commands."""

from __future__ import annotations

from datetime import datetime
import json

from textual import work
from textual.widgets import Static

from ..log import logger
from ..platform import amplifier_projects_dir


class SearchCommandsMixin:
    """Search and grep commands."""

    def _cmd_find(self, text: str) -> None:
        """Handle the /find slash command — open find bar with optional query."""
        parts = text.strip().split(None, 1)
        query = parts[1] if len(parts) > 1 else ""
        self._show_find_bar(query)

    def _cmd_search(self, text: str) -> None:
        """Unified search command.

        Subcommands:
          /search <query>        Search across ALL past sessions
          /search here <query>   Search current chat only
          /search open <N>       Open Nth result from last cross-session search
        """
        parts = text.strip().split(None, 1)
        query = parts[1] if len(parts) > 1 else ""
        if not query:
            self._add_system_message(
                "Usage:\n"
                "  /search <query>        Search across all past sessions\n"
                "  /search here <query>   Search current chat only\n"
                "  /search open <N>       Open result from last search"
            )
            return

        # --- /search here <query> --- current chat only
        if query.startswith("here "):
            self._search_current_chat(query[5:].strip())
            return

        # --- /search open <N> --- open a result from the last cross-session search
        if query.startswith("open "):
            self._search_open_result(query[5:].strip())
            return

        # --- /search <query> --- cross-session search (threaded)
        self._add_system_message(f"Searching all sessions for '{query}'...")
        self._search_all_sessions_worker(query)

    def _search_current_chat(self, query: str) -> None:
        """Search only the current chat's in-memory messages."""
        if not query:
            self._add_system_message("Usage: /search here <query>")
            return

        query_lower = query.lower()
        matches: list[dict] = []

        for i, (role, msg_text, widget) in enumerate(self._search_messages):
            if query_lower in msg_text.lower():
                idx = msg_text.lower().index(query_lower)
                start = max(0, idx - 30)
                end = min(len(msg_text), idx + len(query) + 30)
                snippet = msg_text[start:end].replace("\n", " ")
                if start > 0:
                    snippet = "..." + snippet
                if end < len(msg_text):
                    snippet = snippet + "..."
                matches.append(
                    {"index": i + 1, "role": role, "snippet": snippet, "widget": widget}
                )

        if not matches:
            self._add_system_message(f"No matches found for '{query}'")
            return

        count = len(matches)
        label = "match" if count == 1 else "matches"
        lines = [f"Found {count} {label} for '{query}':"]
        for m in matches[:20]:
            lines.append(f"  [{m['role']}] {m['snippet']}")
        if count > 20:
            lines.append(f"  ... and {count - 20} more")
        self._add_system_message("\n".join(lines))

        # Scroll to the first match
        first_widget = matches[0].get("widget")
        if first_widget is not None:
            try:
                first_widget.scroll_visible()
            except Exception:
                logger.debug("Failed to scroll to search result", exc_info=True)

    def _search_open_result(self, arg: str) -> None:
        """Open a session from the last cross-session search results."""
        if not self._last_search_results:
            self._add_system_message("No search results. Run /search <query> first.")
            return
        try:
            n = int(arg)
        except ValueError:
            self._add_system_message("Usage: /search open <number>")
            return
        if n < 1 or n > len(self._last_search_results):
            self._add_system_message(
                f"Invalid result number. Valid range: 1-{len(self._last_search_results)}"
            )
            return
        result = self._last_search_results[n - 1]
        sid = result["session_id"]
        # Set active search query so find bar auto-opens after transcript loads
        self._active_search_query = getattr(self, "_last_search_query", "")
        self._sessions_open(sid)

    @work(thread=True)
    def _search_all_sessions_worker(self, query: str) -> None:
        """Search transcript content across all saved sessions in a background thread."""
        projects_dir = amplifier_projects_dir()
        if not projects_dir.exists():
            self.call_from_thread(self._add_system_message, "No saved sessions found.")
            return

        query_lower = query.lower()
        results: list[dict] = []

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue

            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Skip sub-sessions (agent delegations)
                if "_" in session_dir.name:
                    continue

                sid = session_dir.name
                transcript = session_dir / "transcript.jsonl"
                if not transcript.exists():
                    continue

                try:
                    mtime = session_dir.stat().st_mtime
                except OSError:
                    continue

                # Read metadata
                meta_name = ""
                meta_desc = ""
                metadata_path = session_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                        meta_name = meta.get("name", "")
                        meta_desc = meta.get("description", "")
                    except (OSError, json.JSONDecodeError):
                        logger.debug(
                            "Failed to read session metadata from %s",
                            metadata_path,
                            exc_info=True,
                        )

                # Derive project name from the encoded directory name
                project_name = (
                    project_dir.name.rsplit("-", 1)[-1]
                    if "-" in project_dir.name
                    else project_dir.name
                )

                # Scan transcript for ALL matches (not just first)
                match_count = 0
                first_snippet = ""
                first_role = ""
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
                            content = self._extract_transcript_text(
                                msg.get("content", "")
                            )
                            content_lower = content.lower()
                            # Count occurrences in this message
                            start = 0
                            while True:
                                idx = content_lower.find(query_lower, start)
                                if idx == -1:
                                    break
                                match_count += 1
                                if match_count == 1:
                                    # Capture snippet around first match
                                    snip_start = max(0, idx - 40)
                                    snip_end = min(len(content), idx + len(query) + 40)
                                    snippet = content[snip_start:snip_end].replace(
                                        "\n", " "
                                    )
                                    if snip_start > 0:
                                        snippet = "..." + snippet
                                    if snip_end < len(content):
                                        snippet = snippet + "..."
                                    first_snippet = snippet
                                    first_role = role
                                start = idx + 1
                except OSError:
                    continue

                # Also check metadata fields
                for meta_field in (meta_name, meta_desc):
                    if meta_field and query_lower in meta_field.lower():
                        if not first_snippet:
                            first_snippet = meta_field.replace("\n", " ")[:100]
                            first_role = "metadata"
                            match_count = max(match_count, 1)
                        break

                if match_count > 0:
                    results.append(
                        {
                            "session_id": sid,
                            "mtime": mtime,
                            "date_str": datetime.fromtimestamp(mtime).strftime(
                                "%m/%d %H:%M"
                            ),
                            "match_count": match_count,
                            "first_snippet": first_snippet,
                            "first_role": first_role,
                            "name": meta_name,
                            "description": meta_desc,
                            "project": project_name,
                        }
                    )

        # Sort by most recent first
        results.sort(key=lambda r: r["mtime"], reverse=True)

        # Store for /search open N and sidebar integration
        self._last_search_results = results
        self._last_search_query = query

        # Also populate sidebar with results
        self.call_from_thread(self._show_sidebar_search_results, results, query)

        # Build output
        if not results:
            self.call_from_thread(
                self._add_system_message,
                f"No sessions found matching '{query}'.",
            )
            return

        total_matches = sum(r["match_count"] for r in results)
        lines = [
            f"Found {total_matches} match{'es' if total_matches != 1 else ''} "
            f"across {len(results)} session{'s' if len(results) != 1 else ''}:\n"
        ]

        custom_names = self._load_session_names()
        session_titles = self._load_session_titles()

        for i, r in enumerate(results[:20], 1):
            sid_short = r["session_id"][:8]
            label = self._session_label(r, custom_names, session_titles)
            count = r["match_count"]
            count_str = f"{count} match{'es' if count != 1 else ''}"
            project = r["project"]
            lines.append(
                f"  {i:2}. [{r['date_str']}]  {project}/{sid_short}  ({count_str})"
            )
            lines.append(f"      {label}")
            snippet = r["first_snippet"][:80]
            lines.append(f"      [{r['first_role']}] {snippet}")

        if len(results) > 20:
            lines.append(f"\n  ... and {len(results) - 20} more sessions")

        lines.append("\nUse /search open <N> to open a result in a new tab.")
        lines.append("Use /search here <query> to search only the current chat.")

        self.call_from_thread(self._add_system_message, "\n".join(lines))

    def _cmd_grep(self, text: str) -> None:
        """Search chat messages with options (case-sensitive flag, role labels)."""
        parts = text.strip().split(None, 1)
        args = parts[1] if len(parts) > 1 else ""

        if not args.strip():
            self._add_system_message(
                "Usage: /grep <pattern>  (search conversation, case-insensitive)\n"
                "       /grep -c <pattern>  (case-sensitive search)"
            )
            return

        # Parse flags
        case_sensitive = False
        pattern = args.strip()
        if pattern.startswith("-c "):
            case_sensitive = True
            pattern = pattern[3:].strip()

        if not pattern:
            self._add_system_message("Please provide a search pattern.")
            return

        if not self._search_messages:
            self._add_system_message("No messages to search.")
            return

        # Search through messages
        search_pat = pattern if case_sensitive else pattern.lower()
        matches: list[tuple[int, str, str, "Static | None"]] = []

        for i, (role, msg_text, widget) in enumerate(self._search_messages):
            text_to_search = msg_text if case_sensitive else msg_text.lower()
            if search_pat not in text_to_search:
                continue
            # Find matching lines for context
            for line in msg_text.split("\n"):
                line_search = line if case_sensitive else line.lower()
                if search_pat in line_search:
                    preview = line.strip()
                    if len(preview) > 80:
                        preview = preview[:80] + "..."
                    matches.append((i, role, preview, widget))
                    break  # one match per message is enough

        if not matches:
            flag_hint = "" if case_sensitive else " (case-insensitive)"
            self._add_system_message(f"No matches for '{pattern}'{flag_hint}")
            return

        # Format results
        count = len(matches)
        label = "match" if count == 1 else "matches"
        cs_label = " (case-sensitive)" if case_sensitive else ""
        lines = [f"Found {count} {label} for '{pattern}'{cs_label}:"]

        role_labels = {"user": "You", "assistant": "AI", "system": "Sys"}
        shown = min(count, 20)
        for msg_idx, role, preview, _widget in matches[:shown]:
            role_label = role_labels.get(role, role)
            lines.append(f"  [{role_label} #{msg_idx + 1}] {preview}")

        if count > shown:
            lines.append(f"  ... and {count - shown} more matches")

        self._add_system_message("\n".join(lines))

        # Scroll to the first match
        first_widget = matches[0][3]
        if first_widget is not None:
            try:
                first_widget.scroll_visible()
            except Exception:
                logger.debug("Failed to scroll to grep result", exc_info=True)

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------
