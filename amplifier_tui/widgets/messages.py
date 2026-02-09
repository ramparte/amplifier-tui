"""Chat message widget classes for Amplifier TUI."""

from __future__ import annotations

from textual.widgets import Markdown, Static


class UserMessage(Static):
    """A user chat message (plain text with styling)."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message user-message")


class ThinkingStatic(Static):
    """A thinking block rendered as a static widget (for transcript replay)."""

    pass


class AssistantMessage(Markdown):
    """An assistant chat message rendered as markdown."""

    def __init__(self, content: str) -> None:
        super().__init__(content, classes="chat-message assistant-message")


class ThinkingBlock(Static):
    """A dimmed thinking/reasoning block."""

    pass


class MessageMeta(Static):
    """Subtle metadata line below messages (timestamp, tokens, response time)."""

    pass
