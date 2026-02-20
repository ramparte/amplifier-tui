"""Desktop export commands: export to HTML, text, markdown."""

from __future__ import annotations

from pathlib import Path


class DesktopExportCommandsMixin:
    """Export current conversation to various formats."""

    def _cmd_export(self, args: str = "") -> None:
        """Export conversation content.

        Subcommands:
          /export html [path]  - Save as styled HTML
          /export text [path]  - Save as plain text
          /export md [path]    - Save as markdown
        """
        app = getattr(self, "_desktop_app", None)
        if not app:
            self._add_system_message("Desktop app not available.")
            return
        display = app._current_display()
        if not display:
            self._add_system_message("No active chat display.")
            return

        parts = args.strip().split(None, 1)
        if not parts:
            self._add_system_message(
                "Usage: /export <format> [path]\nFormats: html, text, md"
            )
            return

        fmt = parts[0].lower()
        custom_path = parts[1].strip() if len(parts) > 1 else ""

        if fmt not in ("html", "text", "md"):
            self._add_system_message(
                f"Unknown format: {fmt}\nAvailable: html, text, md"
            )
            return

        # Build export path
        session_id = getattr(self, "_get_session_id", lambda: None)()
        stem = session_id[:12] if session_id else "export"
        ext = {"html": ".html", "text": ".txt", "md": ".md"}[fmt]

        if custom_path:
            out_path = Path(custom_path).expanduser()
        else:
            export_dir = Path.home() / "amplifier-exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            out_path = export_dir / f"{stem}{ext}"

        # Ensure parent directory exists
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            content = self._export_content(display, fmt)
            out_path.write_text(content, encoding="utf-8")
            self._add_system_message(f"Exported ({fmt}) -> **{out_path}**")
        except Exception as e:
            self._add_system_message(f"Export failed: {e}")

    @staticmethod
    def _export_content(display: object, fmt: str) -> str:
        """Extract content from a ChatDisplay in the requested format."""
        # display is a QTextBrowser (ChatDisplay)
        if fmt == "html":
            raw_html = display.toHtml()  # type: ignore[union-attr]
            # Wrap with minimal styling for standalone viewing
            return (
                "<!DOCTYPE html>\n"
                "<html><head><meta charset='utf-8'>\n"
                "<title>Amplifier Export</title>\n"
                "<style>body{font-family:sans-serif;max-width:800px;"
                "margin:0 auto;padding:20px;}"
                ".user-msg{background:#1a1a2e;padding:10px;margin:8px 0;"
                "border-radius:6px;}"
                ".assistant-msg{background:#16213e;padding:10px;margin:8px 0;"
                "border-radius:6px;}"
                ".system-msg{color:#888;font-style:italic;padding:6px 0;}"
                ".error-msg{color:#ff6b6b;padding:6px 0;}"
                "code{background:#0d1117;padding:2px 4px;border-radius:3px;}"
                "</style></head><body>\n"
                f"{raw_html}\n"
                "</body></html>"
            )
        elif fmt == "text":
            return display.toPlainText()  # type: ignore[union-attr]
        else:
            # Markdown: extract role-labeled sections from the HTML structure
            raw_html = display.toHtml()  # type: ignore[union-attr]
            import re

            lines: list[str] = ["# Amplifier Conversation Export\n"]
            # Match div blocks with role CSS classes and extract their text
            for match in re.finditer(
                r'<div\s+class="(\w[\w-]*)"\s*>(.*?)</div>', raw_html, re.DOTALL
            ):
                cls = match.group(1)
                # Strip HTML tags to get plain text content
                content = re.sub(r"<[^>]+>", "", match.group(2)).strip()
                if not content:
                    continue
                role_map = {
                    "user-msg": "## User",
                    "assistant-msg": "## Assistant",
                    "system-msg": "## System",
                    "error-msg": "## Error",
                    "tool-msg": "## Tool",
                    "tool-start-msg": "## Tool",
                    "tool-end-msg": "## Tool Result",
                    "thinking-block": "## Thinking",
                    "thinking-msg": "## Thinking",
                }
                heading = role_map.get(cls)
                if heading:
                    lines.append(f"{heading}\n\n{content}\n")
            # Fallback if no structured blocks were found
            if len(lines) <= 1:
                plain = display.toPlainText()  # type: ignore[union-attr]
                lines.append(plain)
            return "\n".join(lines)
