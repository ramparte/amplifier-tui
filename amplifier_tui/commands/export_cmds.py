"""Export, title, and rename commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from textual.widgets import Static

from ..log import logger
from .._utils import _copy_to_clipboard
from ..features.export import (
    get_export_metadata,
    export_markdown as _fmt_markdown,
    export_text as _fmt_text,
    export_json as _fmt_json,
    export_html as _fmt_html,
)


class ExportCommandsMixin:
    """Export, title, and rename commands."""

    def _get_export_metadata(self) -> dict[str, str]:
        """Gather metadata for export headers.

        Thin adapter — extracts state from *self* and delegates to
        :func:`features.export.get_export_metadata`.
        """
        sm = self.session_manager if hasattr(self, "session_manager") else None
        session_id = (getattr(sm, "session_id", None) or "") if sm else ""
        model = (getattr(sm, "model_name", None) or "unknown") if sm else "unknown"
        return get_export_metadata(
            session_id=session_id,
            session_title=self._session_title or "",
            model=model,
            message_count=len(self._search_messages),
            user_words=getattr(self, "_user_words", 0),
            assistant_words=getattr(self, "_assistant_words", 0),
        )

    def _export_markdown(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as markdown.

        Thin adapter — delegates to :func:`features.export.export_markdown`.
        """
        return _fmt_markdown(messages, self._get_export_metadata())

    def _export_text(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as plain text.

        Thin adapter — delegates to :func:`features.export.export_text`.
        """
        return _fmt_text(messages, self._get_export_metadata())

    def _export_json(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as JSON.

        Thin adapter — delegates to :func:`features.export.export_json`.
        """
        return _fmt_json(messages, self._get_export_metadata())

    def _export_html(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as styled HTML with dark theme.

        Thin adapter — delegates to :func:`features.export.export_html`.
        """
        return _fmt_html(messages, self._get_export_metadata())

    # ------------------------------------------------------------------
    # /export command
    # ------------------------------------------------------------------

    def _cmd_export(self, text: str) -> None:
        """Export the current chat to markdown, HTML, plain text, or JSON.

        Usage:
            /export                  Export to markdown (default)
            /export md [path]        Markdown
            /export html [path]      Styled HTML (dark theme)
            /export json [path]      Structured JSON
            /export txt [path]       Plain text
            /export last             Export last assistant response
            /export last N           Export last N messages
            /export clipboard        Copy markdown to clipboard
            /export <fmt> --clipboard Copy <fmt> to clipboard
            /export help             Show this help
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # /export help — show usage
        if arg.lower() in ("help", "?"):
            self._add_system_message(
                "Export conversation:\n"
                "  /export                    Markdown (default)\n"
                "  /export md [path]          Markdown\n"
                "  /export html [path]        Styled HTML (dark theme)\n"
                "  /export json [path]        Structured JSON\n"
                "  /export txt [path]         Plain text\n"
                "  /export last               Last assistant response only\n"
                "  /export last N             Last N messages\n"
                "  /export <fmt> last [N]     Combine format + scope\n"
                "  /export clipboard          Copy markdown to clipboard\n"
                "  /export <fmt> --clipboard  Copy to clipboard\n\n"
                "Default path: ./amplifier-chat-{timestamp}.{ext}"
            )
            return

        if not self._search_messages:
            self._add_system_message("No messages to export")
            return

        # Check for --clipboard flag
        to_clipboard = "--clipboard" in arg or "--clip" in arg
        arg = arg.replace("--clipboard", "").replace("--clip", "").strip()

        # Check for 'last [N]' scope filter anywhere in the args.
        # Matches: "last", "last 5", "md last", "json last 3", etc.
        scope = "all"
        scope_count = 0
        scope_match = re.search(r"\blast\b(?:\s+(\d+))?", arg, re.IGNORECASE)
        if scope_match:
            scope = "last"
            if scope_match.group(1):
                scope_count = int(scope_match.group(1))
            # Remove 'last [N]' from arg so format/path parsing is unaffected
            arg = (arg[: scope_match.start()] + arg[scope_match.end() :]).strip()

        # Parse format and optional path
        tokens = arg.split(None, 1)
        first = tokens[0].lower() if tokens else ""
        rest = tokens[1].strip() if len(tokens) > 1 else ""

        fmt = "md"
        custom_path = ""

        format_map = {
            "md": "md",
            "markdown": "md",
            "html": "html",
            "json": "json",
            "txt": "txt",
            "text": "txt",
        }

        if first == "clipboard":
            # /export clipboard — shorthand for markdown to clipboard
            to_clipboard = True
            fmt = "md"
        elif first in format_map:
            fmt = format_map[first]
            custom_path = rest
        elif first:
            # Treat entire arg as a filename; infer format from extension
            custom_path = arg
            if arg.endswith(".html"):
                fmt = "html"
            elif arg.endswith(".json"):
                fmt = "json"
            elif arg.endswith(".txt"):
                fmt = "txt"
            else:
                fmt = "md"

        # Select messages based on scope
        if scope == "last" and scope_count:
            # /export last N — last N messages (any role)
            messages = self._search_messages[-scope_count:]
        elif scope == "last":
            # /export last — last assistant response only
            messages = []
            for entry in reversed(self._search_messages):
                if entry[0] == "assistant":
                    messages = [entry]
                    break
            if not messages:
                self._add_system_message("No assistant messages to export")
                return
        else:
            messages = self._search_messages
        if fmt == "json":
            content = self._export_json(messages)
        elif fmt == "html":
            content = self._export_html(messages)
        elif fmt == "txt":
            content = self._export_text(messages)
        else:
            content = self._export_markdown(messages)

        msg_count = len(messages)

        # Clipboard mode
        if to_clipboard:
            if _copy_to_clipboard(content):
                size_str = (
                    f"{len(content):,} bytes"
                    if len(content) < 1024
                    else f"{len(content) / 1024:.1f} KB"
                )
                self._add_system_message(
                    f"Copied {msg_count} messages as {fmt.upper()}"
                    f" to clipboard ({size_str})"
                )
            else:
                self._add_system_message(
                    "Failed to copy \u2014 no clipboard tool available"
                    " (install xclip or xsel)"
                )
            return

        # Determine output path (default: cwd with amplifier-chat-* naming)
        if custom_path:
            out_path = Path(custom_path).expanduser()
        else:
            ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            out_path = Path.cwd() / f"amplifier-chat-{ts}.{fmt}"

        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
        out_path = out_path.resolve()

        # Ensure extension matches format
        ext_map = {"md": ".md", "html": ".html", "json": ".json", "txt": ".txt"}
        expected_ext = ext_map.get(fmt, f".{fmt}")
        if not out_path.suffix == expected_ext and not custom_path:
            out_path = out_path.with_suffix(expected_ext)

        # Write file
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            size = out_path.stat().st_size
            size_str = f"{size:,} bytes" if size < 1024 else f"{size / 1024:.1f} KB"
            self._add_system_message(
                f"Exported {msg_count} messages to {out_path}\n"
                f"Format: {fmt.upper()}, Size: {size_str}"
            )
        except OSError as e:
            self._add_system_message(f"Export failed: {e}")

    def _cmd_title(self, text: str) -> None:
        """View or set the session title."""
        text = text.strip()

        if not text:
            # Show current title
            if self._session_title:
                self._add_system_message(f"Session title: {self._session_title}")
            else:
                self._add_system_message(
                    "No session title set (auto-generates from first message)"
                )
            return

        if text == "clear":
            self._session_title = ""
            self.sub_title = ""
            self._save_session_title()
            self._update_breadcrumb()
            self._add_system_message("Session title cleared")
            return

        # Set custom title (max 80 chars for manual titles)
        self._session_title = text[:80]
        self._apply_session_title()
        self._add_system_message(f"Session title set: {self._session_title}")

    def _cmd_rename(self, text: str) -> None:
        """Rename the current tab.

        Usage:
            /rename              Show current tab name
            /rename <name>       Set tab name (max 30 chars)
            /rename reset|default|auto   Reset to auto-generated name
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        tab = self._tabs[self._active_tab_index]

        if not arg:
            current = tab.custom_name or tab.name
            self._add_system_message(
                f'Current tab: "{current}"\n'
                "Usage: /rename <name> to rename, /rename reset to restore default"
            )
            return

        if arg.lower() in ("reset", "default", "auto"):
            tab.custom_name = ""
            self._update_tab_bar()
            self._add_system_message(f'Tab name reset to default: "{tab.name}"')
            return

        name = arg[:30]
        self._rename_tab(name)
        self._add_system_message(f'Tab renamed to: "{name}"')

    def _cmd_name(self, text: str) -> None:
        """Name the current session (friendly label for search/sidebar/tabs).

        Usage:
            /name              Show current name
            /name <text>       Set session name
            /name clear        Remove the name
        """
        sid = self._get_session_id()
        if not sid:
            self._add_system_message("No active session to name.")
            return

        text = text.strip()

        # No argument: show current name
        if not text:
            custom_names = self._load_session_names()
            current = custom_names.get(sid)
            if current:
                self._add_system_message(f'Session name: "{current}"')
            else:
                self._add_system_message(
                    "Session is unnamed.\nUsage: /name <text> to set a name."
                )
            return

        # Clear the name
        if text.lower() == "clear":
            self._remove_session_name(sid)
            # Reset tab name back to default
            tab = self._tabs[self._active_tab_index]
            tab.name = f"Tab {self._active_tab_index + 1}"
            self._update_tab_bar()
            self._update_breadcrumb()
            if self._session_list_data:
                self._populate_session_list(self._session_list_data)
            self._add_system_message("Session name cleared.")
            return

        # Set the name
        try:
            self._save_session_name(sid, text)
        except OSError as e:
            logger.debug("Failed to save session name for %s", sid, exc_info=True)
            self._add_system_message(f"Failed to save name: {e}")
            return

        # Update tab bar label so the name is visible immediately
        tab = self._tabs[self._active_tab_index]
        tab.name = text
        self._update_tab_bar()
        self._update_breadcrumb()

        # Refresh sidebar if loaded
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        self._add_system_message(f'Session named: "{text}"')
