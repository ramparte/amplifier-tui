"""Shared test fixtures for amplifier-tui test suite."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for file-based tests."""
    return tmp_path


# -- Simple message fixtures --------------------------------------------------


@pytest.fixture
def sample_messages():
    """Sample chat message tuples for export tests.

    Each entry is ``(role, content, widget_or_none)`` matching the
    ``MessageTuple`` type alias used by the export formatters.
    """
    return [
        ("user", "Hello", None),
        ("assistant", "Hi there! How can I help?", None),
        ("user", "Tell me about Python", None),
        ("assistant", "Python is a programming language...", None),
    ]


@pytest.fixture
def sample_metadata():
    """Sample metadata dict matching ``get_export_metadata`` output."""
    return {
        "date": "2026-01-15 10:30:30",
        "session_id": "abc123def456",
        "session_title": "Test Session",
        "model": "claude-sonnet-4-20250514",
        "message_count": "4",
        "token_estimate": "~100",
    }


# -- Rich message fixtures (TUI-014) -----------------------------------------


@pytest.fixture
def messages_with_tool_use():
    """Messages containing tool_use blocks (tool name + input JSON).

    Simulates the assistant requesting a tool call, as rendered in the TUI.
    """
    return [
        ("user", "List the files in the current directory", None),
        (
            "assistant",
            '[tool_use: bash]\n{"command": "ls -la"}',
            None,
        ),
        (
            "tool",
            '{"stdout": "total 42\\ndrwxr-xr-x  5 user user 4096 Jan 15 file.py\\n"}',
            None,
        ),
        ("assistant", "Here are the files in the current directory.", None),
    ]


@pytest.fixture
def messages_with_tool_result():
    """Messages with explicit tool_result blocks (success and error).

    Covers both successful tool output and tool error responses.
    """
    return [
        ("user", "Read the config file", None),
        (
            "assistant",
            '[tool_use: read_file]\n{"file_path": "/etc/config.yaml"}',
            None,
        ),
        (
            "tool",
            "server:\n  host: localhost\n  port: 8080\n  debug: false",
            None,
        ),
        ("user", "Now read a file that doesn't exist", None),
        (
            "assistant",
            '[tool_use: read_file]\n{"file_path": "/nonexistent"}',
            None,
        ),
        (
            "tool",
            "Error: FileNotFoundError: [Errno 2] No such file or directory: '/nonexistent'",
            None,
        ),
        ("assistant", "That file doesn't exist.", None),
    ]


@pytest.fixture
def messages_with_thinking():
    """Messages containing thinking/reasoning blocks.

    The thinking role is used by models that expose chain-of-thought.
    """
    return [
        ("user", "What is 127 * 389?", None),
        (
            "thinking",
            "Let me calculate step by step.\n"
            "127 * 389\n"
            "= 127 * 400 - 127 * 11\n"
            "= 50800 - 1397\n"
            "= 49403",
            None,
        ),
        ("assistant", "127 * 389 = 49,403", None),
    ]


@pytest.fixture
def messages_with_long_content():
    """Messages with content exceeding 1000 characters.

    Useful for testing fold/truncation, scroll behaviour, and export sizing.
    """
    long_paragraph = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    ) * 20  # ~2400 chars
    long_code = "def process(data):\n" + "".join(
        f"    step_{i} = transform(data, level={i})\n" for i in range(80)
    )  # ~3200 chars
    return [
        ("user", "Write me a very long explanation", None),
        ("assistant", long_paragraph, None),
        ("user", "Now show me a large code block", None),
        ("assistant", f"```python\n{long_code}\n```", None),
    ]


@pytest.fixture
def messages_with_code_and_markdown():
    """Messages with code blocks, inline code, and markdown formatting.

    Covers fenced code blocks (with language tag), inline backticks,
    headers, bold, italic, lists, and links.
    """
    return [
        ("user", "Show me a Python example with `dataclasses`", None),
        (
            "assistant",
            "Here's an example using **dataclasses**:\n\n"
            "```python\n"
            "from dataclasses import dataclass, field\n"
            "\n"
            "@dataclass\n"
            "class Config:\n"
            '    host: str = "localhost"\n'
            "    port: int = 8080\n"
            "    tags: list[str] = field(default_factory=list)\n"
            "```\n\n"
            "Key points:\n"
            "- Use `@dataclass` decorator\n"
            "- Use `field()` for *mutable* defaults\n"
            "- See [docs](https://docs.python.org/3/library/dataclasses.html)",
            None,
        ),
        ("user", "What about a shell command?", None),
        (
            "assistant",
            "Run this:\n\n"
            "```bash\n"
            "curl -s https://api.example.com/health | jq '.status'\n"
            "```\n\n"
            'Expected output: `"ok"`',
            None,
        ),
    ]


@pytest.fixture
def messages_with_unicode():
    """Messages with Unicode characters, emoji, and non-ASCII scripts.

    Tests rendering of CJK, Arabic, emoji, mathematical symbols,
    and mixed-script content.
    """
    return [
        ("user", "Can you greet me in multiple languages?", None),
        (
            "assistant",
            "Hello / Bonjour / Hola / Hallo\n"
            "Japanese: \u3053\u3093\u306b\u3061\u306f\u4e16\u754c\n"
            "Arabic: \u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645\n"
            "Korean: \uc548\ub155\ud558\uc138\uc694\n"
            "Emoji: \U0001f680\U0001f30d\u2728\U0001f916\U0001f4a1",
            None,
        ),
        (
            "user",
            "Show me some math: \u2200x \u2208 \u211d, x\u00b2 \u2265 0",
            None,
        ),
        (
            "assistant",
            "That's the non-negativity of squares:\n"
            "\u2200x \u2208 \u211d : x\u00b2 \u2265 0\n"
            "Proof sketch: x\u00b2 = |x|\u00b2 and |x| \u2265 0. \u220e",
            None,
        ),
    ]


@pytest.fixture
def rich_metadata():
    """Metadata with multiple models, long session IDs, and extra fields.

    More realistic than ``sample_metadata`` -- includes fields seen in
    real sessions with model switching, high token counts, and project info.
    """
    return {
        "date": "2026-02-10 14:22:07",
        "session_id": "d40748ac-415e-422a-96ff-a7264507f302",
        "session_title": "Amplifier TUI Test Sprint - Session 3",
        "model": "claude-sonnet-4-20250514",
        "previous_models": ["claude-haiku-3-20250310", "gpt-4o-2024-08-06"],
        "message_count": "247",
        "token_estimate": "~85,400",
        "input_tokens": "72341",
        "output_tokens": "13059",
        "context_window": "200000",
        "project": "amplifier-tui",
        "project_path": "/home/user/dev/amplifier-tui",
        "duration_seconds": "3847",
    }


@pytest.fixture
def messages_mixed_conversation():
    """Full realistic conversation with user, assistant, thinking, tool, and system.

    Combines multiple message types in a single conversation flow for
    integration-level export and rendering tests.
    """
    return [
        ("system", "You are a helpful assistant.", None),
        ("user", "Fix the bug in app.py line 42", None),
        (
            "thinking",
            "I need to read app.py first to understand the bug.",
            None,
        ),
        (
            "assistant",
            '[tool_use: read_file]\n{"file_path": "app.py", "offset": 40, "limit": 5}',
            None,
        ),
        (
            "tool",
            "40: def process(data):\n"
            "41:     result = data.get('key')\n"
            "42:     return result.strip()  # BUG: result may be None\n"
            "43:\n"
            "44: def main():",
            None,
        ),
        (
            "thinking",
            "The bug is on line 42: `result.strip()` will raise "
            "AttributeError when `result` is None.",
            None,
        ),
        (
            "assistant",
            "Found the bug on line 42. `result` can be `None` when the key "
            "is missing, causing `AttributeError` on `.strip()`.\n\n"
            "Fix:\n```python\nreturn (result or '').strip()\n```",
            None,
        ),
        ("user", "Good catch, apply the fix", None),
        (
            "assistant",
            "[tool_use: edit_file]\n"
            '{"file_path": "app.py", '
            '"old_string": "return result.strip()", '
            '"new_string": "return (result or \'\').strip()"}',
            None,
        ),
        ("tool", "File edited successfully.", None),
        ("assistant", "Fixed. The `None` case is now handled.", None),
    ]
