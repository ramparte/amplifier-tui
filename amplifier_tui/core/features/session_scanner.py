"""Session scanner for the monitor view.

Scans Amplifier session directories on disk and determines the live state
of each session by tail-reading ``events.jsonl``.  Returns lightweight
:class:`MonitoredSession` records suitable for display in a dashboard table.

This module has **no UI dependencies** -- it only reads the filesystem and
returns dataclasses.  The TUI widget layer consumes these records.

State detection logic
---------------------
The last event in ``events.jsonl`` tells us what the session is doing:

* ``session:end``         -> DONE   (session exited)
* ``execution:end``       -> IDLE   (waiting for user input)
* ``execution:start``     -> RUNNING
* ``tool:pre``/``tool:post``/``llm:*``/``content_block:*`` -> RUNNING
* ``prompt:submit``       -> RUNNING
* no events / unknown     -> UNKNOWN

A session whose directory hasn't been modified for > ``STALE_THRESHOLD``
seconds is downgraded to STALE regardless of last event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Sessions with no filesystem activity for this many seconds are STALE.
STALE_THRESHOLD_SECONDS: int = 30 * 60  # 30 minutes

#: How many bytes to read from the tail of events.jsonl.
#: 8 KB is enough for several events even with large data payloads stripped.
_TAIL_BYTES: int = 8192

#: Maximum characters kept for the activity summary string.
_SUMMARY_MAX_CHARS: int = 120

#: Events that indicate the session is actively working.
_RUNNING_EVENTS: frozenset[str] = frozenset(
    {
        "execution:start",
        "prompt:submit",
        "tool:pre",
        "tool:post",
        "llm:request",
        "llm:response",
        "content_block:start",
        "content_block:delta",
        "content_block:end",
        "provider:request",
    }
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class SessionState(Enum):
    """Observable state of a session on disk."""

    RUNNING = "running"
    IDLE = "idle"
    DONE = "done"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MonitoredSession:
    """Snapshot of a single session's state at scan time."""

    session_id: str
    short_id: str  # first 8 chars for display
    project: str  # human-readable project label
    project_path: str  # original working directory
    model: str
    state: SessionState
    turn_count: int
    started_at: datetime | None
    last_active: datetime  # mtime of session directory
    age_seconds: float  # seconds since started_at (or mtime)
    activity: str  # one-line description of current/last activity
    session_dir: Path | None = None  # path to session directory on disk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tail_lines(path: Path, max_bytes: int = _TAIL_BYTES) -> list[str]:
    """Read the last *max_bytes* of a file and return complete lines.

    Seeks to ``end - max_bytes``, discards the (likely partial) first line,
    and returns the rest.  This avoids reading multi-megabyte event logs.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []

    if size == 0:
        return []

    try:
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                raw = fh.read(max_bytes)
                # Drop the first (likely truncated) line.
                idx = raw.find(b"\n")
                if idx >= 0:
                    raw = raw[idx + 1 :]
            else:
                raw = fh.read()
        return raw.decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _parse_last_events(lines: list[str], max_events: int = 10) -> list[dict]:
    """Parse up to *max_events* JSON objects from the tail lines.

    Tolerates malformed lines (skips them).  Returns newest-last order.
    """
    events: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
        if len(events) >= max_events:
            break
    events.reverse()  # restore chronological order
    return events


def _detect_state(events: list[dict], stale: bool) -> SessionState:
    """Determine session state from the most recent events."""
    if not events:
        return SessionState.UNKNOWN

    last = events[-1]
    event_name = last.get("event", "")

    if event_name == "session:end":
        return SessionState.DONE
    if event_name == "execution:end":
        return SessionState.STALE if stale else SessionState.IDLE
    if event_name in _RUNNING_EVENTS:
        return SessionState.STALE if stale else SessionState.RUNNING

    # Fallback: if we can't tell, use staleness.
    return SessionState.STALE if stale else SessionState.UNKNOWN


def _extract_activity(events: list[dict], state: SessionState) -> str:
    """Build a one-line activity string from recent events."""
    if not events:
        return ""

    last = events[-1]
    event_name = last.get("event", "")
    data = last.get("data", {})

    if state == SessionState.DONE:
        return _last_assistant_summary(events)

    if state == SessionState.IDLE:
        return _last_assistant_summary(events)

    if state == SessionState.STALE:
        return "(idle)"

    # RUNNING -- describe what's happening right now.
    if event_name == "tool:pre":
        tool = data.get("tool_name", "unknown")
        return f"tool: {tool}"
    if event_name == "tool:post":
        tool = data.get("tool_name", "unknown")
        return f"tool: {tool} (done)"
    if event_name in ("llm:request", "provider:request"):
        return "Thinking..."
    if event_name == "llm:response":
        return "Processing response..."
    if event_name.startswith("content_block:"):
        return "Streaming..."
    if event_name == "execution:start":
        return "Starting turn..."
    if event_name == "prompt:submit":
        prompt = data.get("prompt", "")
        if isinstance(prompt, str) and prompt:
            preview = prompt[:60].replace("\n", " ")
            return f'Sent: "{preview}"'
        return "Processing prompt..."

    return ""


def _last_assistant_summary(events: list[dict]) -> str:
    """Find the last content_block:end with text and return a preview.

    Falls back to scanning for llm:response data if no content blocks found.
    """
    # Walk backwards looking for the last text content block.
    for ev in reversed(events):
        if ev.get("event") == "content_block:end":
            block = ev.get("data", {}).get("block", {})
            text = block.get("text", "")
            if text:
                clean = text.strip().replace("\n", " ")
                if len(clean) > _SUMMARY_MAX_CHARS:
                    return clean[: _SUMMARY_MAX_CHARS - 1] + "\u2026"
                return clean

    return ""


def _read_metadata(session_dir: Path) -> dict:
    """Read metadata.json from a session directory."""
    for name in ("metadata.json", "session-info.json"):
        path = session_dir / name
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue
    return {}


def _parse_timestamp(raw: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating Z suffix."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _project_label(meta: dict, project_dir_name: str) -> tuple[str, str]:
    """Return (label, path) for the session's project.

    Tries metadata ``working_dir`` first, falls back to the project
    directory name with path-encoding reversed.
    """
    wd = meta.get("working_dir", "")
    if wd:
        return Path(wd).name, wd

    # Amplifier encodes paths as directory names with - separators.
    # The leading - represents /.  E.g. "-home-sam-dev-proj" -> "proj"
    decoded = project_dir_name.replace("-", "/")
    label = decoded.rstrip("/").rsplit("/", 1)[-1] or project_dir_name[:20]
    return label, decoded


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SessionScanner:
    """Scan Amplifier session directories and return live state snapshots.

    Usage::

        scanner = SessionScanner()
        sessions = scanner.scan()       # list of MonitoredSession
        sessions = scanner.scan(limit=10)

    The scanner is stateless -- each :meth:`scan` call reads the filesystem
    fresh.  The caller (e.g. a Textual timer) decides the refresh cadence.
    """

    DEFAULT_SESSION_DIR = Path.home() / ".amplifier" / "projects"

    def __init__(
        self,
        session_dir: Path | None = None,
        stale_threshold: int = STALE_THRESHOLD_SECONDS,
    ) -> None:
        self._session_dir = session_dir or self.DEFAULT_SESSION_DIR
        self._stale_threshold = stale_threshold

    def scan(self, limit: int = 10) -> list[MonitoredSession]:
        """Return up to *limit* sessions sorted by most-recently-active first.

        Only root sessions are returned (sub-sessions with ``_`` in the ID
        are skipped, matching the existing TUI convention).
        """
        if not self._session_dir.exists():
            return []

        candidates: list[tuple[float, Path, str]] = []
        # project_dir_name is used for label fallback.
        now = datetime.now().timestamp()

        for project_dir in self._session_dir.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            if not sessions_subdir.exists():
                continue

            for session_dir in sessions_subdir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Skip sub-sessions.
                if "_" in session_dir.name:
                    continue
                # Must have either events or transcript to be interesting.
                events_path = session_dir / "events.jsonl"
                transcript_path = session_dir / "transcript.jsonl"
                if not events_path.exists() and not transcript_path.exists():
                    continue

                try:
                    mtime = session_dir.stat().st_mtime
                except OSError:
                    continue

                candidates.append((mtime, session_dir, project_dir.name))

        # Sort by mtime descending, take top N.
        candidates.sort(key=lambda t: t[0], reverse=True)
        candidates = candidates[:limit]

        results: list[MonitoredSession] = []
        for mtime, sdir, proj_dir_name in candidates:
            results.append(self._scan_one(sdir, proj_dir_name, mtime, now))

        return results

    def _scan_one(
        self,
        session_dir: Path,
        project_dir_name: str,
        mtime: float,
        now: float,
    ) -> MonitoredSession:
        """Build a MonitoredSession from a single session directory."""
        meta = _read_metadata(session_dir)
        session_id = meta.get("session_id", session_dir.name)
        model = meta.get("model", "")
        turn_count = meta.get("turn_count", 0) or 0
        started_at = _parse_timestamp(
            meta.get("created", "") or meta.get("started_at", "")
        )
        project_label, project_path = _project_label(meta, project_dir_name)

        # Determine state from events.
        events_path = session_dir / "events.jsonl"
        tail = _tail_lines(events_path)
        events = _parse_last_events(tail)

        seconds_since_activity = now - mtime
        is_stale = seconds_since_activity > self._stale_threshold

        state = _detect_state(events, stale=is_stale)
        activity = _extract_activity(events, state)

        # Age: prefer started_at if available, else use mtime.
        if started_at:
            age = now - started_at.timestamp()
        else:
            age = seconds_since_activity

        last_active_dt = datetime.fromtimestamp(mtime)

        return MonitoredSession(
            session_id=session_id,
            short_id=session_id[:8],
            project=project_label,
            project_path=project_path,
            model=model,
            state=state,
            turn_count=turn_count,
            started_at=started_at,
            last_active=last_active_dt,
            age_seconds=max(0.0, age),
            activity=activity,
            session_dir=session_dir,
        )

    # -- Formatting helpers (no Rich/Textual dependency) --------------------

    @staticmethod
    def format_age(seconds: float) -> str:
        """Human-readable age string: ``3m``, ``1h``, ``2d``."""
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        if seconds < 86400:
            return f"{seconds / 3600:.1f}h"
        return f"{seconds / 86400:.1f}d"

    @staticmethod
    def state_icon(state: SessionState) -> str:
        """Single-character icon for a session state."""
        return {
            SessionState.RUNNING: "\u27f3",  # ⟳
            SessionState.IDLE: "\u23f3",  # ⏳
            SessionState.DONE: "\u2713",  # ✓
            SessionState.STALE: "\u00b7",  # ·
            SessionState.UNKNOWN: "?",
        }.get(state, "?")

    @staticmethod
    def state_color(state: SessionState) -> str:
        """Rich markup color name for a session state."""
        return {
            SessionState.RUNNING: "yellow",
            SessionState.IDLE: "cyan",
            SessionState.DONE: "green",
            SessionState.STALE: "dim",
            SessionState.UNKNOWN: "dim",
        }.get(state, "dim")
