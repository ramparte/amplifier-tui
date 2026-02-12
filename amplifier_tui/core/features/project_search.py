"""Cross-session transcript search.

Searches transcript.jsonl files across sessions in a project for a text
query, returning matching sessions with context snippets.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from amplifier_tui.core.platform_info import amplifier_projects_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_CONTEXT_CHARS: int = 150
_MAX_RESULTS: int = 20


@dataclass
class SearchResult:
    """A single search match in a session transcript."""

    session_id: str
    short_id: str
    project: str
    match_context: str
    role: str  # user/assistant
    date_str: str
    mtime: float


class ProjectSearch:
    """Search across session transcripts within a project.

    Usage::

        searcher = ProjectSearch()
        results = searcher.search(sessions, "filter bug", limit=10)
    """

    @staticmethod
    def search(
        sessions: list[dict],
        query: str,
        *,
        project_filter: str | None = None,
        limit: int = _MAX_RESULTS,
    ) -> list[SearchResult]:
        """Search transcript content across sessions.

        Parameters
        ----------
        sessions:
            Session dicts from list_all_sessions().
        query:
            Text to search for (case-insensitive substring match).
        project_filter:
            If set, only search sessions in this project (partial match).
        limit:
            Maximum results to return.

        Returns
        -------
        List of SearchResult, sorted by mtime descending.
        """
        if not query.strip():
            return []

        query_lower = query.lower()
        results: list[SearchResult] = []
        projects_dir = amplifier_projects_dir()

        for s in sessions:
            if limit and len(results) >= limit:
                break

            # Apply project filter
            if project_filter:
                if project_filter.lower() not in s["project"].lower():
                    continue

            # Find transcript file
            sid = s["session_id"]
            transcript_path = _find_transcript(projects_dir, sid)
            if transcript_path is None:
                continue

            # Search the transcript
            match = _search_transcript(transcript_path, query_lower)
            if match:
                results.append(
                    SearchResult(
                        session_id=sid,
                        short_id=sid[:8],
                        project=s["project"],
                        match_context=match[0],
                        role=match[1],
                        date_str=s["date_str"],
                        mtime=s["mtime"],
                    )
                )

        results.sort(key=lambda r: r.mtime, reverse=True)
        return results[:limit]

    @staticmethod
    def format_results(results: list[SearchResult], query: str) -> str:
        """Format search results for display."""
        if not results:
            return f"No results found for '{query}'."

        lines = [f"Search results for '{query}' ({len(results)} matches):"]
        for r in results:
            context = r.match_context
            if len(context) > 80:
                context = context[:77] + "..."
            lines.append(f"  {r.date_str}  {r.short_id}  [{r.role}]  {r.project}")
            lines.append(f"    ...{context}...")
        return "\n".join(lines)


def _find_transcript(projects_dir: Path, session_id: str) -> Path | None:
    """Locate transcript.jsonl for a session ID."""
    if not projects_dir.exists():
        return None
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        transcript = project_dir / "sessions" / session_id / "transcript.jsonl"
        if transcript.exists():
            return transcript
    return None


def _search_transcript(
    path: Path,
    query_lower: str,
) -> tuple[str, str] | None:
    """Search a transcript file for a query.

    Returns (context_snippet, role) for the first match, or None.
    Only searches user and assistant text content (not tool calls).
    """
    try:
        # Read last 64KB to avoid loading massive files
        file_size = path.stat().st_size
        read_start = max(0, file_size - 65536)

        with open(path, encoding="utf-8", errors="replace") as f:
            if read_start > 0:
                f.seek(read_start)
                f.readline()  # Skip partial line
            lines = f.readlines()

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                # Extract text blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                content = " ".join(text_parts)

            if not isinstance(content, str):
                continue

            idx = content.lower().find(query_lower)
            if idx >= 0:
                # Extract context around match
                start = max(0, idx - 50)
                end = min(len(content), idx + len(query_lower) + 100)
                snippet = content[start:end].replace("\n", " ").strip()
                return (snippet, role)

    except (OSError, UnicodeDecodeError):
        logger.debug("Failed to search %s", path, exc_info=True)

    return None
