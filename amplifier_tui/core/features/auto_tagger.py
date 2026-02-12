"""LLM-powered automatic session tagging.

Follows the :class:`~session_summarizer.SessionSummarizer` pattern:
queue-based, non-blocking, with a slow timer for LLM processing.

Key design decisions
--------------------
* **Tag vocabulary reuse** -- the LLM is given existing tags and told to
  prefer them for consistency.  New tags are only created when nothing fits.
* **User override respected** -- tags the user explicitly removes are
  tracked and never re-generated for that session.
* **Throttled** -- at most 3 sessions processed per cycle to avoid
  bursty API costs.
* **Graceful degradation** -- if no LLM callable is provided, or the call
  fails, the session simply remains untagged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..persistence._base import JsonStore
from ..persistence.tags import TagStore
from .session_summarizer import read_transcript_excerpt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum tags to generate per session.
_DEFAULT_MAX_TAGS: int = 3

# ---------------------------------------------------------------------------
# LLM call protocol
# ---------------------------------------------------------------------------


class TagFn(Protocol):
    """Callable that sends a prompt to an LLM and returns the response text."""

    def __call__(self, prompt: str) -> str: ...


# ---------------------------------------------------------------------------
# Auto-tag state persistence
# ---------------------------------------------------------------------------


class AutoTagState(JsonStore):
    """Tracks which sessions have been auto-tagged.

    Schema::

        {
            "session-uuid": {
                "tagged_at": "2026-02-11T20:00:00Z",
                "mtime_at_tagging": 1739304000.0,
                "tags_generated": ["web", "frontend"],
                "removed_by_user": ["misc"]
            }
        }
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load(self) -> dict[str, dict]:
        raw = self.load_raw()
        if not isinstance(raw, dict):
            return {}
        return raw

    def save(self, data: dict[str, dict]) -> None:
        self.save_raw(data, sort_keys=True)

    def get_state(self, session_id: str) -> dict | None:
        """Return the auto-tag state for a session, or None."""
        return self.load().get(session_id)

    def set_state(
        self,
        session_id: str,
        *,
        mtime: float,
        tags_generated: list[str],
    ) -> None:
        """Record that a session was auto-tagged."""
        from datetime import datetime, timezone

        data = self.load()
        existing = data.get(session_id, {})
        data[session_id] = {
            "tagged_at": datetime.now(timezone.utc).isoformat(),
            "mtime_at_tagging": mtime,
            "tags_generated": tags_generated,
            "removed_by_user": existing.get("removed_by_user", []),
        }
        self.save(data)

    def record_user_removal(self, session_id: str, tag: str) -> None:
        """Record that the user removed a tag (don't re-generate it)."""
        data = self.load()
        state = data.get(session_id)
        if state is None:
            # Only track removals for auto-tagged sessions
            return
        removed = state.get("removed_by_user", [])
        if tag not in removed:
            removed.append(tag)
            state["removed_by_user"] = removed
            data[session_id] = state
            self.save(data)

    def get_removed_tags(self, session_id: str) -> list[str]:
        """Tags the user explicitly removed from this session."""
        state = self.load().get(session_id, {})
        return state.get("removed_by_user", [])


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_TAG_PROMPT_TEMPLATE = """\
You are tagging an Amplifier coding session for organization.

Existing tags in use (prefer these for consistency):
{tag_vocabulary}

Session project: {project_name}
Session transcript (recent):
{transcript_text}

Generate 1-{max_tags} short tags (1-2 words each) that describe what this \
session is about. Prefer existing tags when they fit. Output only the tags, \
one per line, no punctuation or hashtags."""


def _build_tag_prompt(
    transcript_text: str,
    project_name: str,
    tag_vocabulary: list[str],
    max_tags: int = _DEFAULT_MAX_TAGS,
) -> str:
    """Build the prompt for the LLM tagging call."""
    vocab_str = ", ".join(tag_vocabulary[:30]) if tag_vocabulary else "(none yet)"
    return _TAG_PROMPT_TEMPLATE.format(
        tag_vocabulary=vocab_str,
        project_name=project_name,
        transcript_text=transcript_text[:2000],
        max_tags=max_tags,
    )


def _clean_tags(raw: str, max_tags: int = _DEFAULT_MAX_TAGS) -> list[str]:
    """Parse and normalize LLM-generated tags.

    Handles various output formats: one-per-line, comma-separated,
    with or without # prefixes or numbering.
    """
    tags: list[str] = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Handle comma-separated on one line
        parts = line.split(",") if "," in line else [line]
        for part in parts:
            # Strip numbering like "1. " or "- "
            tag = part.strip().lstrip("0123456789.-) ").strip()
            # Strip # prefix and quotes
            tag = tag.strip("#\"'`* ").lower()
            # Skip empty or too-long tags
            if tag and (
                " " not in tag
                and len(tag) <= 30
                or (" " in tag and len(tag.split()) <= 2)
            ):
                # Normalize multi-word: keep as-is but limit to 2 words
                words = tag.split()
                tag = "-".join(words) if len(words) > 1 else tag
                if tag and tag not in tags:
                    tags.append(tag)
    return tags[:max_tags]


# ---------------------------------------------------------------------------
# Pending session tracking
# ---------------------------------------------------------------------------


@dataclass
class _PendingSession:
    """A session queued for auto-tagging."""

    session_id: str
    project: str
    session_dir: Path
    mtime: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class AutoTagger:
    """Automatic tag generation for sessions without tags.

    Usage::

        tagger = AutoTagger(tag_store, state_store, tag_fn=my_llm_call)

        # Queue sessions that need tagging
        tagger.queue_session(sid, project, session_dir, mtime)

        # On slow timer (every 30s) -- processes LLM queue
        tagger.process_pending(max_count=3)

    If *tag_fn* is ``None``, the tagger is a no-op.
    """

    def __init__(
        self,
        tag_store: TagStore,
        state_store: AutoTagState,
        tag_fn: TagFn | None = None,
        max_tags: int = _DEFAULT_MAX_TAGS,
    ) -> None:
        self._tag_store = tag_store
        self._state_store = state_store
        self._tag_fn = tag_fn
        self._max_tags = max_tags
        self._pending: list[_PendingSession] = []

    @property
    def has_pending(self) -> bool:
        return len(self._pending) > 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def needs_tagging(self, session_id: str, mtime: float) -> bool:
        """Check if a session needs auto-tagging.

        Returns True if:
        - Session has no tags in TagStore
        - Session hasn't been auto-tagged at this mtime
        """
        # Already has tags? Skip.
        if self._tag_store.get_tags(session_id):
            return False
        # Already auto-tagged at this mtime? Skip.
        state = self._state_store.get_state(session_id)
        if state and state.get("mtime_at_tagging") == mtime:
            return False
        return True

    def queue_session(
        self,
        session_id: str,
        project: str,
        session_dir: Path,
        mtime: float,
    ) -> None:
        """Add a session to the tagging queue (if not already queued)."""
        if any(p.session_id == session_id for p in self._pending):
            return
        self._pending.append(
            _PendingSession(
                session_id=session_id,
                project=project,
                session_dir=session_dir,
                mtime=mtime,
            )
        )

    def process_pending(self, max_count: int = 3) -> int:
        """Process up to *max_count* pending auto-tagging requests.

        Returns the number of sessions successfully tagged.
        """
        if not self._tag_fn:
            self._pending.clear()
            return 0

        processed = 0
        while self._pending and processed < max_count:
            session = self._pending.pop(0)

            excerpt = read_transcript_excerpt(session.session_dir)
            if excerpt is None:
                continue

            # Build transcript text from excerpt
            parts: list[str] = []
            if excerpt.user_message:
                parts.append(f"User: {excerpt.user_message[:500]}")
            if excerpt.assistant_text:
                parts.append(f"Assistant: {excerpt.assistant_text[:1000]}")
            transcript_text = "\n".join(parts)
            if not transcript_text.strip():
                continue

            # Get existing tag vocabulary
            all_tags_vocab = list(self._tag_store.all_tags().keys())

            # Get user-removed tags for this session
            removed = self._state_store.get_removed_tags(session.session_id)

            prompt = _build_tag_prompt(
                transcript_text=transcript_text,
                project_name=session.project,
                tag_vocabulary=all_tags_vocab,
                max_tags=self._max_tags,
            )

            try:
                raw_response = self._tag_fn(prompt)
                tags = _clean_tags(raw_response, self._max_tags)

                # Filter out user-removed tags
                tags = [t for t in tags if t not in removed]

                # Add tags to store
                for tag in tags:
                    self._tag_store.add_tag(session.session_id, tag)

                # Record in state
                self._state_store.set_state(
                    session.session_id,
                    mtime=session.mtime,
                    tags_generated=tags,
                )
                processed += 1
                logger.debug("Auto-tagged %s with %s", session.session_id[:8], tags)
            except Exception:
                logger.debug(
                    "Auto-tagging failed for %s",
                    session.session_id,
                    exc_info=True,
                )
                continue

        return processed

    def record_user_removal(self, session_id: str, tag: str) -> None:
        """Notify the auto-tagger that a user removed a tag."""
        self._state_store.record_user_removal(session_id, tag)


# ---------------------------------------------------------------------------
# Default tag_fn using the anthropic SDK (optional)
# ---------------------------------------------------------------------------


def make_anthropic_auto_tagger(
    model: str = "claude-haiku-4-20250506",
    max_tokens: int = 50,
) -> TagFn | None:
    """Create a :class:`TagFn` using the ``anthropic`` SDK.

    Returns ``None`` if the SDK is not installed or no API key is found.
    """
    try:
        import anthropic  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("anthropic SDK not installed; auto-tagging disabled")
        return None

    try:
        client = anthropic.Anthropic()
    except anthropic.AuthenticationError:
        logger.debug("No valid Anthropic API key; auto-tagging disabled")
        return None

    def _tag(prompt: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    return _tag
