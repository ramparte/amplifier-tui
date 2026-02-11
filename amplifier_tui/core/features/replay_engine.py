"""Session replay engine (F3.3 - Session Replay).

A pure state-machine that manages replay timeline and playback state.
No I/O, no async — the app layer schedules message display based on
the delays this engine calculates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ReplayState(Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass
class ReplayMessage:
    """A single message in the replay timeline."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: datetime | None = None
    delay_ms: float = 0  # delay from previous message
    tool_name: str = ""
    index: int = 0  # position in timeline


class ReplayEngine:
    """Manages session replay state and timeline.

    This is a pure state-machine that doesn't do I/O or async work.
    The app layer is responsible for scheduling message display based
    on the delays this engine calculates.
    """

    SPEED_OPTIONS: dict[str, float] = {
        "0.5x": 0.5,
        "1x": 1.0,
        "2x": 2.0,
        "5x": 5.0,
        "instant": 0.0,
    }

    def __init__(self) -> None:
        self._state: ReplayState = ReplayState.IDLE
        self._messages: list[ReplayMessage] = []
        self._position: int = 0  # current message index
        self._speed: float = 1.0
        self._speed_label: str = "1x"
        self._session_id: str = ""
        self._source_path: str = ""

    # -- Properties -----------------------------------------------------------

    @property
    def state(self) -> ReplayState:
        return self._state

    @property
    def position(self) -> int:
        return self._position

    @property
    def total_messages(self) -> int:
        return len(self._messages)

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def speed_label(self) -> str:
        return self._speed_label

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def is_playing(self) -> bool:
        return self._state == ReplayState.PLAYING

    @property
    def is_paused(self) -> bool:
        return self._state == ReplayState.PAUSED

    @property
    def is_finished(self) -> bool:
        return self._state == ReplayState.FINISHED

    @property
    def messages(self) -> list[ReplayMessage]:
        """Return a copy of the message list."""
        return list(self._messages)

    @property
    def progress_pct(self) -> float:
        """Return replay progress as 0-100 percentage."""
        if not self._messages:
            return 0.0
        return (self._position / len(self._messages)) * 100

    # -- Loading --------------------------------------------------------------

    def load_transcript(
        self,
        lines: list[str],
        session_id: str = "",
        source_path: str = "",
    ) -> int:
        """Load a transcript from JSONL lines.

        Each line should be a JSON object with at least ``role`` and ``content``.
        Optional: ``timestamp`` (ISO format), ``tool_name``.

        Returns the number of messages loaded.
        """
        self._messages.clear()
        self._position = 0
        self._session_id = session_id
        self._source_path = source_path

        prev_timestamp: datetime | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = data.get("role", "")
            content = data.get("content", "")

            if not role or not content:
                # Skip entries without role/content (tool results, metadata)
                # But include them if they have a tool_name
                if not data.get("tool_name"):
                    continue

            # Parse timestamp
            ts: datetime | None = None
            ts_str = data.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            # Calculate delay from previous message
            delay_ms = 0.0
            if ts and prev_timestamp:
                delta = (ts - prev_timestamp).total_seconds() * 1000
                delay_ms = max(0, min(delta, 30000))  # Cap at 30 seconds

            msg = ReplayMessage(
                role=role,
                content=content if isinstance(content, str) else str(content),
                timestamp=ts,
                delay_ms=delay_ms,
                tool_name=data.get("tool_name", ""),
                index=len(self._messages),
            )
            self._messages.append(msg)

            if ts:
                prev_timestamp = ts

        return len(self._messages)

    # -- Playback control -----------------------------------------------------

    def play(self) -> None:
        """Start or resume playback.

        Raises:
            RuntimeError: If no transcript is loaded.
        """
        if not self._messages:
            raise RuntimeError("No transcript loaded")
        if self._state == ReplayState.FINISHED:
            self._position = 0
        self._state = ReplayState.PLAYING

    def pause(self) -> None:
        """Pause playback."""
        if self._state == ReplayState.PLAYING:
            self._state = ReplayState.PAUSED

    def resume(self) -> None:
        """Resume paused playback."""
        if self._state == ReplayState.PAUSED:
            self._state = ReplayState.PLAYING

    def stop(self) -> None:
        """Stop replay and reset position."""
        self._state = ReplayState.IDLE
        self._position = 0

    def next_message(self) -> ReplayMessage | None:
        """Get the next message and advance position.

        Returns ``None`` if replay is finished or not playing.
        """
        if self._state != ReplayState.PLAYING:
            return None
        if self._position >= len(self._messages):
            self._state = ReplayState.FINISHED
            return None

        msg = self._messages[self._position]
        self._position += 1

        if self._position >= len(self._messages):
            self._state = ReplayState.FINISHED

        return msg

    def skip(self) -> ReplayMessage | None:
        """Skip to next message regardless of state (if paused or playing)."""
        if self._state not in (ReplayState.PLAYING, ReplayState.PAUSED):
            return None
        if self._position >= len(self._messages):
            self._state = ReplayState.FINISHED
            return None

        msg = self._messages[self._position]
        self._position += 1

        if self._position >= len(self._messages):
            self._state = ReplayState.FINISHED

        return msg

    # -- Speed ----------------------------------------------------------------

    def set_speed(self, label: str) -> None:
        """Set playback speed.

        Args:
            label: One of ``"0.5x"``, ``"1x"``, ``"2x"``, ``"5x"``, ``"instant"``

        Raises:
            ValueError: If *label* is not a valid speed option.
        """
        label = label.lower().strip()
        if label not in self.SPEED_OPTIONS:
            raise ValueError(
                f"Invalid speed '{label}'. Options: {', '.join(self.SPEED_OPTIONS)}"
            )
        self._speed = self.SPEED_OPTIONS[label]
        self._speed_label = label

    def get_adjusted_delay(self, msg: ReplayMessage) -> float:
        """Get the delay for a message adjusted by current speed.

        Returns delay in milliseconds, or 0 for instant speed.
        """
        if self._speed == 0:
            return 0
        return msg.delay_ms / self._speed

    # -- Formatting -----------------------------------------------------------

    def format_status(self) -> str:
        """Format current replay status as Rich markup."""
        if self._state == ReplayState.IDLE and not self._messages:
            return (
                "[dim]No replay active.[/dim]\n\n"
                "Usage: /replay [session_id]\n"
                "  /replay speed 2x\n"
                "  /replay pause / resume / skip / stop"
            )

        state_str = {
            ReplayState.IDLE: "[dim]idle[/dim]",
            ReplayState.PLAYING: "[green]\u25b6 playing[/green]",
            ReplayState.PAUSED: "[yellow]\u23f8 paused[/yellow]",
            ReplayState.FINISHED: "[blue]\u23f9 finished[/blue]",
        }.get(self._state, str(self._state))

        lines = [
            f"[bold]Session Replay[/bold] {state_str}",
            "",
        ]

        if self._session_id:
            sid = self._session_id
            display_sid = f"{sid[:20]}..." if len(sid) > 20 else sid
            lines.append(f"  Session: [dim]{display_sid}[/dim]")

        pos = min(self._position, len(self._messages))
        total = len(self._messages)
        lines.append(f"  Progress: {pos}/{total} messages ({self.progress_pct:.0f}%)")
        lines.append(f"  Speed: {self._speed_label}")

        # Progress bar
        bar_width = 30
        filled = int((pos / total) * bar_width) if total > 0 else 0
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        lines.append(f"  [{bar}]")

        # Current message preview
        if 0 < self._position <= len(self._messages):
            current = self._messages[self._position - 1]
            preview = current.content[:80].replace("\n", " ")
            lines.append(f"  Last: [{current.role}] {preview}")

        return "\n".join(lines)

    def format_timeline(self, window: int = 5) -> str:
        """Format a window of the timeline around current position."""
        if not self._messages:
            return "[dim]No messages loaded.[/dim]"

        lines = [f"Timeline (showing {window} around position {self._position}):"]
        lines.append("")

        start = max(0, self._position - window)
        end = min(len(self._messages), self._position + window)

        for i in range(start, end):
            msg = self._messages[i]
            marker = "\u2192 " if i == self._position else "  "
            role_color = {
                "user": "green",
                "assistant": "blue",
                "system": "dim",
                "tool": "yellow",
            }.get(msg.role, "white")
            preview = msg.content[:60].replace("\n", " ")
            ts = msg.timestamp.strftime("%H:%M:%S") if msg.timestamp else "??:??:??"
            lines.append(
                f"  {marker}[{role_color}]{i:3d}. [{msg.role:9s}] {ts}"
                f" {preview}[/{role_color}]"
            )

        return "\n".join(lines)

    # -- Reset ----------------------------------------------------------------

    def clear(self) -> None:
        """Clear all replay state."""
        self._state = ReplayState.IDLE
        self._messages.clear()
        self._position = 0
        self._speed = 1.0
        self._speed_label = "1x"
        self._session_id = ""
        self._source_path = ""
