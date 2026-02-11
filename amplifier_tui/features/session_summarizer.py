"""LLM-powered session status summaries for the monitor view.

Wraps :class:`~session_scanner.SessionScanner` and enhances the ``activity``
field with concise, human-readable status lines produced by a cheap/fast LLM
(haiku-class).

Key design decisions
--------------------
* **Summarize on state transitions only** -- not every poll.  When a session
  moves to IDLE or DONE, we read the transcript tail and ask the LLM for a
  status line.  The result is cached until the session's mtime changes.
* **Non-blocking** -- :meth:`SessionSummarizer.scan` always returns
  immediately with the best available text (cached LLM summary or raw
  truncated text).  Pending summaries are processed separately via
  :meth:`process_pending`, which the caller can run on a slower timer or
  in a background task.
* **Provider-agnostic** -- the summarizer accepts a plain callable
  ``(str) -> str`` for the LLM call.  The TUI wires in whatever provider
  the user has configured.  A default implementation using the ``anthropic``
  SDK is provided but entirely optional.
* **Graceful degradation** -- if no LLM callable is provided, or if the call
  fails, the raw truncated text from the scanner is shown instead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from amplifier_tui.features.session_scanner import (
    MonitoredSession,
    SessionScanner,
    SessionState,
    _tail_lines,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Bytes to read from the tail of transcript.jsonl.
#: 16 KB captures several conversation turns even with tool results.
_TRANSCRIPT_TAIL_BYTES: int = 16384

#: Maximum characters of transcript text sent to the LLM.
_MAX_PROMPT_CHARS: int = 2000

#: Maximum characters for the returned status line.
_MAX_STATUS_CHARS: int = 60

# ---------------------------------------------------------------------------
# LLM call protocol
# ---------------------------------------------------------------------------


class SummarizeFn(Protocol):
    """Callable that sends a prompt to an LLM and returns the response text."""

    def __call__(self, prompt: str) -> str: ...


# ---------------------------------------------------------------------------
# Transcript reading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranscriptExcerpt:
    """Last user message and assistant response from a transcript."""

    user_message: str
    assistant_text: str


def read_transcript_excerpt(session_dir: Path) -> TranscriptExcerpt | None:
    """Read the last user/assistant exchange from ``transcript.jsonl``.

    Returns *None* if the transcript is missing or has no usable content.
    """
    transcript_path = session_dir / "transcript.jsonl"
    lines = _tail_lines(transcript_path, max_bytes=_TRANSCRIPT_TAIL_BYTES)
    if not lines:
        return None

    # Parse the tail lines into message dicts (tolerating bad lines).
    messages: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue

    if not messages:
        return None

    last_user = ""
    last_assistant = ""

    # Walk backwards to find the last assistant and last user messages.
    for msg in reversed(messages):
        role = msg.get("role", "")
        if role == "assistant" and not last_assistant:
            last_assistant = _extract_assistant_text(msg)
        elif role == "user" and not last_user:
            if isinstance(msg.get("content"), str):
                last_user = msg["content"]
        if last_user and last_assistant:
            break

    if not last_assistant and not last_user:
        return None

    return TranscriptExcerpt(
        user_message=last_user[:_MAX_PROMPT_CHARS],
        assistant_text=last_assistant[:_MAX_PROMPT_CHARS],
    )


def _extract_assistant_text(msg: dict) -> str:
    """Pull plain text from an assistant message's content field.

    Assistant content can be either a string or a list of content blocks
    (``[{"type": "text", "text": "..."}, {"type": "thinking", ...}]``).
    We want only the ``text`` blocks, concatenated.
    """
    content = msg.get("content", "")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts)

    return ""


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a session monitor status writer.  Given the tail of a conversation \
between a user and an AI coding assistant, write a SHORT status line \
(max 8 words) that tells a busy human what this session's current state is \
at a glance.

Rules:
- Max 8 words.  Shorter is better.
- Start with the key fact: what happened or what's needed.
- Use sentence fragments, not full sentences.
- No quotes, no markdown, no punctuation beyond commas.
- If the assistant is waiting for a decision, say so.
- If there was an error or blocker, surface it.

Good examples:
- Committed fix, tests passing
- Waiting for decision on auth approach
- Hit rate limit, needs retry
- Built feature, ready for review
- Debugging test failure in auth module
- Blocked on missing API key
- Refactored caching, needs testing
- Exploring codebase structure
"""


def build_summary_prompt(
    excerpt: TranscriptExcerpt,
    state: SessionState,
) -> str:
    """Build the prompt for the LLM summarization call."""
    state_label = {
        SessionState.IDLE: "Waiting for user input",
        SessionState.DONE: "Session ended",
        SessionState.RUNNING: "Still working",
        SessionState.STALE: "Appears inactive",
        SessionState.UNKNOWN: "Unknown state",
    }.get(state, "Unknown")

    parts = [_SYSTEM_PROMPT, f"\nSession state: {state_label}\n"]

    if excerpt.user_message:
        trimmed = excerpt.user_message[:500].replace("\n", " ")
        parts.append(f"Last user request:\n{trimmed}\n")

    if excerpt.assistant_text:
        trimmed = excerpt.assistant_text[:1000].replace("\n", " ")
        parts.append(f"Last assistant response (truncated):\n{trimmed}\n")

    parts.append("Status line:")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass
class _CachedSummary:
    """A cached LLM summary keyed by session mtime."""

    summary: str
    mtime: float  # mtime of session dir when summary was generated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SessionSummarizer:
    """Wraps a :class:`SessionScanner` and enhances activity with LLM summaries.

    Usage::

        scanner = SessionScanner()
        summarizer = SessionSummarizer(scanner, summarize_fn=my_llm_call)

        # On fast timer (every 2s) -- always instant
        sessions = summarizer.scan(limit=10)

        # On slow timer (every 10-30s) -- processes LLM queue
        summarizer.process_pending(max_count=3)

    If *summarize_fn* is ``None``, the summarizer acts as a transparent
    pass-through: sessions are returned with the scanner's raw activity text.
    """

    #: States that trigger LLM summarization.
    _SUMMARIZABLE_STATES: frozenset[SessionState] = frozenset(
        {SessionState.IDLE, SessionState.DONE}
    )

    def __init__(
        self,
        scanner: SessionScanner,
        summarize_fn: SummarizeFn | None = None,
    ) -> None:
        self._scanner = scanner
        self._summarize_fn = summarize_fn
        self._cache: dict[str, _CachedSummary] = {}
        self._pending: list[MonitoredSession] = []

    @property
    def has_pending(self) -> bool:
        """Whether there are sessions waiting for LLM summarization."""
        return len(self._pending) > 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def scan(self, limit: int = 10) -> list[MonitoredSession]:
        """Scan sessions and return them with the best available activity text.

        * If a cached LLM summary exists and the session hasn't changed,
          the cached summary replaces the raw ``activity`` field.
        * If the session needs summarization but hasn't been processed yet,
          the raw scanner text is returned and the session is queued.
        * RUNNING / STALE / UNKNOWN sessions are never queued -- their
          real-time scanner activity (tool name, "Thinking...") is more
          useful than a summary.
        """
        sessions = self._scanner.scan(limit=limit)
        result: list[MonitoredSession] = []

        for s in sessions:
            mtime = s.last_active.timestamp()
            cached = self._cache.get(s.session_id)

            if cached and cached.mtime == mtime:
                # Cache hit -- use the LLM summary.
                result.append(replace(s, activity=cached.summary))
                continue

            if (
                s.state in self._SUMMARIZABLE_STATES
                and self._summarize_fn is not None
                and not self._is_pending(s.session_id)
            ):
                self._pending.append(s)

            result.append(s)

        return result

    def process_pending(self, max_count: int = 3) -> int:
        """Process up to *max_count* pending LLM summarizations.

        Returns the number of summaries successfully generated.  Failed
        summaries are silently dropped (the raw text remains in the UI
        until the next state transition triggers a retry).
        """
        if not self._summarize_fn:
            self._pending.clear()
            return 0

        processed = 0
        while self._pending and processed < max_count:
            session = self._pending.pop(0)

            if session.session_dir is None:
                continue

            excerpt = read_transcript_excerpt(session.session_dir)
            if excerpt is None:
                continue

            prompt = build_summary_prompt(excerpt, session.state)

            try:
                raw_summary = self._summarize_fn(prompt)
                summary = self._clean_summary(raw_summary)
                self._cache[session.session_id] = _CachedSummary(
                    summary=summary,
                    mtime=session.last_active.timestamp(),
                )
                processed += 1
            except Exception:
                logger.debug(
                    "Summary generation failed for %s",
                    session.session_id,
                    exc_info=True,
                )
                continue

        return processed

    def invalidate(self, session_id: str) -> None:
        """Remove a cached summary, forcing re-generation on next scan."""
        self._cache.pop(session_id, None)

    def clear_cache(self) -> None:
        """Remove all cached summaries."""
        self._cache.clear()
        self._pending.clear()

    # -- Internal -----------------------------------------------------------

    def _is_pending(self, session_id: str) -> bool:
        return any(s.session_id == session_id for s in self._pending)

    @staticmethod
    def _clean_summary(raw: str) -> str:
        """Normalize an LLM-produced status line."""
        # Take only the first line (models sometimes add explanation).
        line = raw.strip().split("\n")[0].strip()
        # Strip quotes and markdown artifacts.
        line = line.strip("\"'`*")
        # Enforce length limit.
        if len(line) > _MAX_STATUS_CHARS:
            line = line[: _MAX_STATUS_CHARS - 1] + "\u2026"
        return line


# ---------------------------------------------------------------------------
# Default summarize_fn using the anthropic SDK (optional)
# ---------------------------------------------------------------------------


def make_anthropic_summarizer(
    model: str = "claude-haiku-4-20250506",
    max_tokens: int = 50,
) -> SummarizeFn | None:
    """Create a :class:`SummarizeFn` using the ``anthropic`` SDK.

    Returns ``None`` if the SDK is not installed or no API key is found,
    allowing the caller to fall back to raw text.
    """
    try:
        import anthropic  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("anthropic SDK not installed; LLM summaries disabled")
        return None

    try:
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    except anthropic.AuthenticationError:
        logger.debug("No valid Anthropic API key; LLM summaries disabled")
        return None

    def _summarize(prompt: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        # Extract text from the response.
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    return _summarize
