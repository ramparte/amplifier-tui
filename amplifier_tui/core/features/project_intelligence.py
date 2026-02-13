"""LLM-powered project intelligence: ask questions about project activity.

Uses the ProjectAggregator to build context and an LLM to synthesize
answers about what's happening in a project.  When a
:class:`~projector_client.ProjectorClient` is available, enriches context
with tasks, strategies, people, notes, and outcomes from Projector.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .project_aggregator import ProjectAggregator, ProjectInfo

if TYPE_CHECKING:
    from .projector_client import ProjectorClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS: int = 300  # 5 minutes


# ---------------------------------------------------------------------------
# LLM call protocol
# ---------------------------------------------------------------------------


class AskFn(Protocol):
    """Callable that sends a prompt to an LLM and returns the response text."""

    def __call__(self, prompt: str) -> str: ...


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass
class _CachedAnswer:
    """A cached LLM answer keyed by question hash."""

    answer: str
    created_at: float


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_ASK_SYSTEM = """\
You are a project intelligence assistant. Given context about an Amplifier \
project (its sessions, tags, and activity), answer the user's question \
concisely and specifically.

Rules:
- Reference specific sessions by date and name/ID when relevant.
- Be specific about what happened, not generic.
- If you don't have enough context, say so.
- Keep answers under 200 words unless more detail is clearly needed.
"""

_ATTENTION_SYSTEM = """\
You are a project intelligence assistant. Review the project context below \
and identify what needs attention: stalled work, frequent topics that may \
indicate issues, sessions that ended without resolution, or areas with lots \
of recent activity.

Rules:
- Be specific: reference session dates and topics.
- Prioritize: most important items first.
- Be actionable: suggest what to do next.
- Keep it concise: 3-5 bullet points max.
"""

_WEEKLY_SYSTEM = """\
You are a project intelligence assistant. Summarize the past week's activity \
for this project based on the session data provided.

Rules:
- Group by theme/area of work, not chronologically.
- Mention key outcomes and decisions.
- Note any unfinished work or blockers.
- Keep it to 5-8 bullet points.
"""

_FOCUS_SYSTEM = """\
You are a project intelligence assistant. Based on the project context \
(sessions, tasks, strategies, and recent outcomes), recommend what the user \
should work on next.

Rules:
- Consider task priority and status (in_progress > blocked > pending).
- Consider session momentum: what was the user recently working on?
- Consider active strategies: do they suggest a preferred approach?
- Be concrete: name specific tasks, sessions, or areas.
- Keep it to 3-5 actionable items, ranked by priority.
"""


def _build_project_context(info: ProjectInfo, all_tags: dict[str, list[str]]) -> str:
    """Build a context string from project data for the LLM."""
    parts = [
        f"Project: {info.name}",
        f"Path: {info.project_path}",
        f"Total sessions: {info.session_count}",
        f"Last active: {info.latest_date_str}",
    ]

    if info.tags:
        top = info.top_tags[:10]
        parts.append(f"Common tags: {', '.join(top)}")

    parts.append("\nRecent sessions:")
    recent = sorted(info.sessions, key=lambda s: s["mtime"], reverse=True)[:15]
    for s in recent:
        sid = s["session_id"][:8]
        tags = all_tags.get(s["session_id"], [])
        tag_str = " ".join(f"#{t}" for t in tags) if tags else ""
        name = s.get("name") or s.get("description") or "(unnamed)"
        if len(name) > 60:
            name = name[:57] + "..."
        parts.append(f"  {s['date_str']}  {sid}  {name}  {tag_str}")

    return "\n".join(parts)


def _build_projector_context(projector: ProjectorClient, project_name: str) -> str:
    """Build additional context from Projector data (tasks, strategies, etc.).

    Returns an empty string if Projector is not available or has no data
    for the given project.
    """
    if not projector.available:
        return ""

    parts: list[str] = []

    proj = projector.get_project(project_name)
    if proj:
        if proj.description:
            parts.append(f"\nProject description: {proj.description.strip()}")
        if proj.people:
            parts.append(f"People: {', '.join(proj.people)}")
        if proj.notes:
            parts.append(f"Notes: {proj.notes.strip()}")
        if proj.relationships:
            rels = []
            for rel_type, targets in proj.relationships.items():
                if isinstance(targets, list):
                    rels.append(f"  {rel_type}: {', '.join(targets)}")
                else:
                    rels.append(f"  {rel_type}: {targets}")
            if rels:
                parts.append("Relationships:\n" + "\n".join(rels))
        if proj.recent_outcomes:
            parts.append("\nRecent outcomes:")
            for o in proj.recent_outcomes:
                ts = o.get("timestamp", "?")[:10]
                summary = o.get("summary", "no summary")
                parts.append(f"  [{ts}] {summary}")

    # Tasks
    tasks = projector.get_tasks(project_name)
    if tasks:
        active = [t for t in tasks if t.status != "completed"]
        if active:
            parts.append("\nActive tasks:")
            for t in active:
                parts.append(
                    f"  [{t.status}] {t.id}: {t.title} (priority: {t.priority})"
                )

    # Active strategies
    strategies = projector.list_strategies(active_only=True)
    if strategies:
        parts.append("\nActive strategies:")
        for s in strategies:
            parts.append(f"  - {s.name}: {s.description.strip()[:100]}")

    return "\n".join(parts)


def _build_ask_prompt(
    context: str,
    question: str,
    system: str = _ASK_SYSTEM,
) -> str:
    """Build the full prompt for the LLM."""
    return f"{system}\n\n--- Project Context ---\n{context}\n\n--- Question ---\n{question}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ProjectIntelligence:
    """LLM-powered project Q&A engine.

    When *projector* is provided and available, all LLM context is
    automatically enriched with Projector tasks, strategies, people,
    notes, and outcomes.

    Usage::

        intel = ProjectIntelligence(ask_fn=my_llm_call,
                                    projector=ProjectorClient())
        answer = intel.ask(sessions, all_tags, "amplifier-tui",
                          "What needs attention?")
    """

    def __init__(
        self,
        ask_fn: AskFn | None = None,
        projector: ProjectorClient | None = None,
    ) -> None:
        self._ask_fn = ask_fn
        self._projector = projector
        self._cache: dict[str, _CachedAnswer] = {}

    def _cache_key(self, project: str, question: str) -> str:
        """Deterministic cache key from project + question."""
        raw = f"{project}:{question}".lower().strip()
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> str | None:
        """Return cached answer if still fresh, else None."""
        cached = self._cache.get(key)
        if cached and (time.time() - cached.created_at) < _CACHE_TTL_SECONDS:
            return cached.answer
        if cached:
            del self._cache[key]
        return None

    def _set_cached(self, key: str, answer: str) -> None:
        self._cache[key] = _CachedAnswer(answer=answer, created_at=time.time())

    def _full_context(
        self,
        sessions: list[dict],
        all_tags: dict[str, list[str]],
        project_name: str,
    ) -> str | None:
        """Build combined session + Projector context for a project.

        Returns ``None`` if the project cannot be found.
        """
        projects = ProjectAggregator.aggregate(sessions, all_tags)
        info = ProjectAggregator.get_project(projects, project_name)
        if info is None:
            return None

        context = _build_project_context(info, all_tags)

        if self._projector:
            projector_ctx = _build_projector_context(self._projector, project_name)
            if projector_ctx:
                context += "\n\n--- Projector Data ---\n" + projector_ctx

        return context

    def ask(
        self,
        sessions: list[dict],
        all_tags: dict[str, list[str]],
        project_name: str,
        question: str,
    ) -> str:
        """Ask a question about a project.

        Returns the LLM's answer, or an error message if unavailable.
        """
        if not self._ask_fn:
            return "Project intelligence requires an LLM provider (anthropic SDK)."

        # Check cache
        cache_key = self._cache_key(project_name, question)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        context = self._full_context(sessions, all_tags, project_name)
        if context is None:
            return f"No project matching '{project_name}'."

        prompt = _build_ask_prompt(context, question)

        try:
            answer = self._ask_fn(prompt)
            self._set_cached(cache_key, answer)
            return answer
        except Exception as e:
            logger.debug("Project intelligence failed", exc_info=True)
            return f"Failed to get answer: {e}"

    def what_needs_attention(
        self,
        sessions: list[dict],
        all_tags: dict[str, list[str]],
        project_name: str,
    ) -> str:
        """Identify what needs attention in a project."""
        if not self._ask_fn:
            return "Project intelligence requires an LLM provider (anthropic SDK)."

        context = self._full_context(sessions, all_tags, project_name)
        if context is None:
            return f"No project matching '{project_name}'."

        prompt = _build_ask_prompt(context, "What needs attention?", _ATTENTION_SYSTEM)

        try:
            return self._ask_fn(prompt)
        except Exception as e:
            logger.debug("Attention check failed", exc_info=True)
            return f"Failed: {e}"

    def weekly_summary(
        self,
        sessions: list[dict],
        all_tags: dict[str, list[str]],
        project_name: str,
    ) -> str:
        """Generate a weekly summary for a project."""
        if not self._ask_fn:
            return "Project intelligence requires an LLM provider (anthropic SDK)."

        context = self._full_context(sessions, all_tags, project_name)
        if context is None:
            return f"No project matching '{project_name}'."

        prompt = _build_ask_prompt(context, "Weekly summary", _WEEKLY_SYSTEM)

        try:
            return self._ask_fn(prompt)
        except Exception as e:
            logger.debug("Weekly summary failed", exc_info=True)
            return f"Failed: {e}"

    def focus(
        self,
        sessions: list[dict],
        all_tags: dict[str, list[str]],
        project_name: str,
    ) -> str:
        """Suggest what to work on next based on tasks, momentum, and strategies."""
        if not self._ask_fn:
            return "Project intelligence requires an LLM provider (anthropic SDK)."

        context = self._full_context(sessions, all_tags, project_name)
        if context is None:
            return f"No project matching '{project_name}'."

        prompt = _build_ask_prompt(
            context, "What should I focus on next?", _FOCUS_SYSTEM
        )

        try:
            return self._ask_fn(prompt)
        except Exception as e:
            logger.debug("Focus suggestion failed", exc_info=True)
            return f"Failed: {e}"


# ---------------------------------------------------------------------------
# Default ask_fn using the anthropic SDK (optional)
# ---------------------------------------------------------------------------


def make_anthropic_ask_fn(
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 500,
) -> AskFn | None:
    """Create an :class:`AskFn` using the ``anthropic`` SDK.

    Uses sonnet-class model for quality synthesis.
    Returns ``None`` if the SDK is not installed or no API key is found.
    """
    try:
        import anthropic  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("anthropic SDK not installed; project intelligence disabled")
        return None

    try:
        client = anthropic.Anthropic()
    except anthropic.AuthenticationError:
        logger.debug("No valid Anthropic API key; project intelligence disabled")
        return None

    def _ask(prompt: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    return _ask
