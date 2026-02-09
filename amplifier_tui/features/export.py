"""Pure-function export helpers.

Each formatter takes a list of message tuples and metadata dict,
returning a formatted string.  No ``self`` references.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


def html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def md_to_html(text: str) -> str:
    """Very basic markdown to HTML conversion."""
    # Code blocks (fenced)
    text = re.sub(
        r"```(\w+)?\n(.*?)\n```",
        lambda m: (
            f'<pre><code class="language-{m.group(1) or ""}">{m.group(2)}</code></pre>'
        ),
        text,
        flags=re.DOTALL,
    )
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Line breaks (outside <pre> blocks)
    parts = re.split(r"(<pre>.*?</pre>)", text, flags=re.DOTALL)
    for i, part in enumerate(parts):
        if not part.startswith("<pre>"):
            parts[i] = part.replace("\n", "<br>\n")
    return "".join(parts)


def get_export_metadata(
    *,
    session_id: str = "",
    session_title: str = "",
    model: str = "unknown",
    message_count: int = 0,
    user_words: int = 0,
    assistant_words: int = 0,
) -> dict[str, str]:
    """Build the metadata dict used by export formatters."""
    total_words = user_words + assistant_words
    est_tokens = int(total_words * 1.3)
    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "session_id": session_id,
        "session_title": session_title,
        "model": model,
        "message_count": str(message_count),
        "token_estimate": f"~{est_tokens:,}",
    }


# Type alias for message tuples used by the export formatters.
# Each entry is (role, content, widget_or_none).  The third element
# is kept for signature compatibility but is unused by the formatters.
MessageTuple = tuple[str, str, Any]


def export_markdown(messages: list[MessageTuple], metadata: dict[str, str]) -> str:
    """Format *messages* as markdown."""
    lines = [
        "# Amplifier Chat Export",
        "",
    ]
    lines.append(f"- **Date**: {metadata['date']}")
    if metadata["session_id"]:
        lines.append(f"- **Session**: {metadata['session_id'][:12]}")
    if metadata["session_title"]:
        lines.append(f"- **Title**: {metadata['session_title']}")
    lines.append(f"- **Model**: {metadata['model']}")
    lines.append(f"- **Messages**: {metadata['message_count']}")
    lines.append(f"- **Tokens**: {metadata['token_estimate']}")
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


def export_text(messages: list[MessageTuple], metadata: dict[str, str]) -> str:
    """Format *messages* as plain text."""
    lines: list[str] = [
        f"Amplifier Chat - {metadata['date']}",
        "=" * 40,
        f"Session: {metadata['session_id'][:12] if metadata['session_id'] else 'n/a'}",
        f"Model: {metadata['model']}",
        f"Messages: {metadata['message_count']}",
        f"Tokens: {metadata['token_estimate']}",
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


def export_json(messages: list[MessageTuple], metadata: dict[str, str]) -> str:
    """Format *messages* as JSON."""
    data = {
        "session_id": metadata["session_id"],
        "session_title": metadata["session_title"],
        "model": metadata["model"],
        "exported_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "token_estimate": metadata["token_estimate"],
        "messages": [
            {"role": role, "content": content} for role, content, _widget in messages
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def export_html(messages: list[MessageTuple], metadata: dict[str, str]) -> str:
    """Format *messages* as styled HTML with dark theme."""
    title_text = (
        html_escape(metadata["session_title"])
        if metadata["session_title"]
        else "Chat Export"
    )
    html = [
        "<!DOCTYPE html>",
        "<html lang='en'><head>",
        "<meta charset='utf-8'>",
        f"<title>Amplifier - {title_text} - {metadata['date']}</title>",
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
    sid_short = metadata["session_id"][:12] if metadata["session_id"] else "n/a"
    meta_parts = [
        f"<span><strong>Date:</strong> {metadata['date']}</span>",
        f"<span><strong>Session:</strong> {html_escape(sid_short)}</span>",
        f"<span><strong>Model:</strong> {html_escape(metadata['model'])}</span>",
        f"<span><strong>Messages:</strong> {metadata['message_count']}</span>",
        f"<span><strong>Tokens:</strong> {html_escape(metadata['token_estimate'])}</span>",
    ]
    if metadata["session_title"]:
        meta_parts.insert(
            1,
            f"<span><strong>Title:</strong> {html_escape(metadata['session_title'])}</span>",
        )
    html.append(f"<div class='metadata'>{''.join(meta_parts)}</div>")

    for role, content, _widget in messages:
        escaped = html_escape(content)
        rendered = md_to_html(escaped)

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
                f"<div class='message {html_escape(role)}'>"
                f"<div class='role'>{role_label}</div>"
                f"<div>{rendered}</div></div>"
            )

    html.append(
        "<p class='meta' style='text-align:center; margin-top:32px;'>"
        "Exported from Amplifier TUI</p>"
    )
    html.append("</body></html>")
    return "\n".join(html)
