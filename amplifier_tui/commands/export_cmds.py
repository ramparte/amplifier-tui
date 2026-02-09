"""Export, title, and rename commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import re

from textual.widgets import Static

from .._utils import _copy_to_clipboard


class ExportCommandsMixin:
    """Export, title, and rename commands."""

    def _get_export_metadata(self) -> dict[str, str]:
        """Gather metadata for export headers."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        session_id = (getattr(sm, "session_id", None) or "") if sm else ""
        model = (getattr(sm, "model_name", None) or "unknown") if sm else "unknown"
        total_words = getattr(self, "_user_words", 0) + getattr(
            self, "_assistant_words", 0
        )
        est_tokens = int(total_words * 1.3)
        return {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "session_id": session_id,
            "session_title": self._session_title or "",
            "model": model,
            "message_count": str(len(self._search_messages)),
            "token_estimate": f"~{est_tokens:,}",
        }

    def _export_markdown(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as markdown."""
        meta = self._get_export_metadata()
        lines = [
            "# Amplifier Chat Export",
            "",
        ]
        lines.append(f"- **Date**: {meta['date']}")
        if meta["session_id"]:
            lines.append(f"- **Session**: {meta['session_id'][:12]}")
        if meta["session_title"]:
            lines.append(f"- **Title**: {meta['session_title']}")
        lines.append(f"- **Model**: {meta['model']}")
        lines.append(f"- **Messages**: {meta['message_count']}")
        lines.append(f"- **Tokens**: {meta['token_estimate']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for role, content, _widget in messages:
            if role == "user":
                lines.append("## User")
            elif role == "assistant":
                lines.append("## Assistant")
            elif role == "thinking":
                lines.append("<details><summary>Thinking</summary>")
                lines.append("")
                lines.append(content)
                lines.append("")
                lines.append("</details>")
                lines.append("")
                lines.append("---")
                lines.append("")
                continue
            elif role == "system":
                lines.append(f"> **System**: {content}")
                lines.append("")
                lines.append("---")
                lines.append("")
                continue
            else:
                lines.append(f"## {role.title()}")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

        lines.append("*Exported from Amplifier TUI*")
        return "\n".join(lines)

    def _export_text(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as plain text."""
        meta = self._get_export_metadata()
        lines: list[str] = [
            f"Amplifier Chat - {meta['date']}",
            "=" * 40,
            f"Session: {meta['session_id'][:12] if meta['session_id'] else 'n/a'}",
            f"Model: {meta['model']}",
            f"Messages: {meta['message_count']}",
            f"Tokens: {meta['token_estimate']}",
            "=" * 40,
            "",
        ]
        for role, content, _widget in messages:
            label = {
                "user": "You",
                "assistant": "AI",
                "system": "System",
                "thinking": "Thinking",
            }.get(role, role)
            lines.append(f"[{label}]")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    def _export_json(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as JSON."""
        meta = self._get_export_metadata()
        data = {
            "session_id": meta["session_id"],
            "session_title": meta["session_title"],
            "model": meta["model"],
            "exported_at": datetime.now().isoformat(),
            "message_count": len(messages),
            "token_estimate": meta["token_estimate"],
            "messages": [
                {"role": role, "content": content}
                for role, content, _widget in messages
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def _export_html(self, messages: list[tuple[str, str, Static | None]]) -> str:
        """Format messages as styled HTML with dark theme."""
        meta = self._get_export_metadata()
        title_text = (
            self._html_escape(meta["session_title"])
            if meta["session_title"]
            else "Chat Export"
        )
        html = [
            "<!DOCTYPE html>",
            "<html lang='en'><head>",
            "<meta charset='utf-8'>",
            f"<title>Amplifier - {title_text} - {meta['date']}</title>",
            "<style>",
            "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"
            " max-width: 800px; margin: 0 auto; padding: 20px; background: #1e1e2e; color: #cdd6f4; }",
            ".metadata { color: #6c7086; font-size: 0.85em; border-bottom: 1px solid #313244;"
            " padding-bottom: 1rem; margin-bottom: 2rem; }",
            ".metadata span { margin-right: 1.5em; }",
            ".message { margin: 16px 0; padding: 12px 16px; border-radius: 8px; }",
            ".user { background: #313244; border-left: 3px solid #89b4fa; }",
            ".assistant { background: #1e1e2e; border-left: 3px solid #a6e3a1; }",
            ".system { background: #181825; border-left: 3px solid #f9e2af; font-style: italic; }",
            ".thinking { background: #181825; border-left: 3px solid #9399b2; }",
            ".role { font-weight: bold; margin-bottom: 8px; color: #89b4fa; }",
            ".assistant .role { color: #a6e3a1; }",
            ".system .role { color: #f9e2af; }",
            ".thinking .role { color: #9399b2; }",
            "pre { background: #11111b; padding: 12px; border-radius: 4px; overflow-x: auto; }",
            "code { font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace; font-size: 0.9em; }",
            "p code { background: #313244; padding: 2px 5px; border-radius: 3px; }",
            "details { margin: 8px 0; }",
            "summary { cursor: pointer; color: #9399b2; font-weight: bold; }",
            ".meta { color: #6c7086; font-size: 0.85em; margin-top: 12px; }",
            "h1 { color: #cba6f7; border-bottom: 1px solid #313244; padding-bottom: 8px; }",
            "a { color: #89b4fa; }",
            "</style>",
            "</head><body>",
            "<h1>Amplifier Chat Export</h1>",
        ]
        sid_short = meta["session_id"][:12] if meta["session_id"] else "n/a"
        meta_parts = [
            f"<span><strong>Date:</strong> {meta['date']}</span>",
            f"<span><strong>Session:</strong> {self._html_escape(sid_short)}</span>",
            f"<span><strong>Model:</strong> {self._html_escape(meta['model'])}</span>",
            f"<span><strong>Messages:</strong> {meta['message_count']}</span>",
            f"<span><strong>Tokens:</strong> {self._html_escape(meta['token_estimate'])}</span>",
        ]
        if meta["session_title"]:
            meta_parts.insert(
                1,
                f"<span><strong>Title:</strong> {self._html_escape(meta['session_title'])}</span>",
            )
        html.append(f"<div class='metadata'>{''.join(meta_parts)}</div>")

        for role, content, _widget in messages:
            escaped = self._html_escape(content)
            rendered = self._md_to_html(escaped)

            if role == "thinking":
                html.append(
                    f"<details class='message thinking'>"
                    f"<summary class='role'>Thinking</summary>"
                    f"<div>{rendered}</div></details>"
                )
            else:
                role_label = {
                    "user": "User",
                    "assistant": "Assistant",
                    "system": "System",
                }.get(role, role.title())
                html.append(
                    f"<div class='message {self._html_escape(role)}'>"
                    f"<div class='role'>{role_label}</div>"
                    f"<div>{rendered}</div></div>"
                )

        html.append(
            "<p class='meta' style='text-align:center; margin-top:32px;'>"
            "Exported from Amplifier TUI</p>"
        )
        html.append("</body></html>")
        return "\n".join(html)

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
        except Exception as e:
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

