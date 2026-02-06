"""Load and parse Amplifier session transcripts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class DisplayBlock:
    """A renderable block from a transcript message."""

    kind: str  # "text", "thinking", "tool_use", "tool_result", "user"
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_id: str = ""


def load_transcript(transcript_path: Path) -> Iterator[dict]:
    """Load messages from a transcript.jsonl file."""
    if not transcript_path.exists():
        return

    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
                yield msg
            except json.JSONDecodeError:
                continue


def parse_message_blocks(msg: dict) -> list[DisplayBlock]:
    """Parse a transcript message into renderable blocks.

    Handles user messages, assistant text, thinking, tool_use, and tool_result.
    """
    role = msg.get("role")
    blocks: list[DisplayBlock] = []

    if role == "user":
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                part.get("text", "") for part in content if part.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        if content:
            blocks.append(DisplayBlock(kind="user", content=content))

    elif role == "assistant":
        content_blocks = msg.get("content", [])
        if isinstance(content_blocks, str):
            # Simple string content
            blocks.append(DisplayBlock(kind="text", content=content_blocks))
        elif isinstance(content_blocks, list):
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")

                if btype == "text":
                    text = block.get("text", "")
                    if text.strip():
                        blocks.append(DisplayBlock(kind="text", content=text))

                elif btype == "thinking":
                    thinking = block.get("thinking", "")
                    if thinking.strip():
                        blocks.append(DisplayBlock(kind="thinking", content=thinking))

                elif btype == "tool_use":
                    blocks.append(
                        DisplayBlock(
                            kind="tool_use",
                            tool_name=block.get("name", "unknown"),
                            tool_input=block.get("input", {}),
                            tool_id=block.get("id", ""),
                        )
                    )

                elif btype == "tool_result":
                    # Tool results come as separate messages but may be inline
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        parts = [
                            p.get("text", "")
                            for p in result_content
                            if p.get("type") == "text"
                        ]
                        result_content = "\n".join(parts)
                    blocks.append(
                        DisplayBlock(
                            kind="tool_result",
                            content=str(result_content)[:500],
                            tool_id=block.get("tool_use_id", ""),
                        )
                    )

    elif role == "tool":
        # Tool result messages (separate from assistant)
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content if p.get("type") == "text"]
            content = "\n".join(parts)
        blocks.append(
            DisplayBlock(
                kind="tool_result",
                content=str(content)[:500],
                tool_id=msg.get("tool_use_id", ""),
            )
        )

    return blocks


def format_message_for_display(msg: dict) -> tuple[str, str] | None:
    """Legacy: Format a transcript message as (content, role) for simple display."""
    role = msg.get("role")

    if role == "user":
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                part.get("text", "") for part in content if part.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        return (content, "user")

    elif role == "assistant":
        content_blocks = msg.get("content", [])
        text_parts = []
        if isinstance(content_blocks, str):
            text_parts.append(content_blocks)
        elif isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
        if text_parts:
            return ("\n\n".join(text_parts), "assistant")

    return None
