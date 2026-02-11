"""File watcher — monitors files for changes and reports diffs.

The :class:`FileWatcher` owns the ``watched_files`` dict and polling logic.
It communicates back to the app through three callbacks injected at
construction time, keeping it decoupled from Textual and the app class.
"""

from __future__ import annotations

import difflib
import os
from datetime import datetime
from typing import Any, Callable

from ..log import logger

# Type alias for the timer handle returned by ``App.set_interval``.
TimerHandle = Any


class FileWatcher:
    """Manage a set of watched files and poll for changes.

    Parameters
    ----------
    add_message:
        Callback to display a message (e.g. ``app._add_system_message``).
    notify_sound:
        Callback to play a notification sound.
    set_interval:
        Callback to start a periodic timer (e.g. ``app.set_interval``).
        Must return a handle with a ``.stop()`` method.
    """

    MAX_WATCHED = 10

    def __init__(
        self,
        *,
        add_message: Callable[[str], object],
        notify_sound: Callable[..., object],
        set_interval: Callable[..., TimerHandle],
    ) -> None:
        self.watched_files: dict[str, dict[str, Any]] = {}
        self._timer: TimerHandle | None = None
        self._add_message = add_message
        self._notify_sound = notify_sound
        self._set_interval = set_interval

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self.watched_files)

    def add(self, path: str) -> str | None:
        """Start watching *path*.  Returns an error string, or ``None`` on success."""
        abs_path = os.path.abspath(os.path.expanduser(path))

        if not os.path.exists(abs_path):
            return f"Path not found: {path}"

        if len(self.watched_files) >= self.MAX_WATCHED:
            return f"Maximum {self.MAX_WATCHED} watched files. Use /watch stop <path> to remove one."

        if abs_path in self.watched_files:
            return f"Already watching: {os.path.relpath(abs_path)}"

        stat = os.stat(abs_path)
        initial_content: str | None = None
        if os.path.isfile(abs_path):
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as f:
                    initial_content = f.read()
            except OSError:
                pass

        self.watched_files[abs_path] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "added_at": datetime.now().isoformat(),
            "prev_content": None,
            "last_content": initial_content,
        }

        self._start_timer()
        return None  # success

    def remove(self, path: str) -> str | None:
        """Stop watching *path*.  Returns an error string, or ``None`` on success."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if abs_path not in self.watched_files:
            return f"Not watching: {path}"
        del self.watched_files[abs_path]
        if not self.watched_files:
            self._stop_timer()
        return None

    def remove_all(self) -> int:
        """Stop watching everything.  Returns the count of removed watches."""
        count = len(self.watched_files)
        self.watched_files.clear()
        self._stop_timer()
        return count

    def list_watches(self) -> list[str]:
        """Return a human-readable list of currently watched files."""
        lines = ["Watched files:"]
        for path, info in self.watched_files.items():
            rel = os.path.relpath(path)
            lines.append(f"  {rel} (since {info['added_at'][:16]})")
        lines.append(f"\n{len(self.watched_files)} file(s) watched")
        return lines

    def get_diff(self, path: str) -> str | None:
        """Return a unified diff for the last change to *path*, or ``None``."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if abs_path not in self.watched_files:
            return None
        return self._compute_diff(abs_path)

    def check(self) -> None:
        """Poll all watched files for changes (called by the timer)."""
        for path, info in list(self.watched_files.items()):
            try:
                if not os.path.exists(path):
                    rel = os.path.relpath(path)
                    self._add_message(f"[watch] File removed: {rel}")
                    del self.watched_files[path]
                    continue

                stat = os.stat(path)
                if stat.st_mtime != info["mtime"] or stat.st_size != info["size"]:
                    rel = os.path.relpath(path)

                    new_content: str | None = None
                    line_delta_str = ""
                    if os.path.isfile(path):
                        try:
                            with open(path, encoding="utf-8", errors="replace") as f:
                                new_content = f.read()
                        except OSError:
                            pass

                        if new_content is not None and info["last_content"] is not None:
                            line_delta_str = self._line_delta(
                                info["last_content"], new_content
                            )

                    # Byte-level fallback
                    size_delta = stat.st_size - info["size"]
                    if not line_delta_str:
                        if size_delta > 0:
                            line_delta_str = f" (+{size_delta} bytes)"
                        elif size_delta < 0:
                            line_delta_str = f" ({size_delta} bytes)"

                    # Rotate content snapshots
                    info["prev_content"] = info["last_content"]
                    info["last_content"] = new_content
                    info["mtime"] = stat.st_mtime
                    info["size"] = stat.st_size

                    self._add_message(f"[watch] Changed: {rel}{line_delta_str}")
                    self._notify_sound(event="file_change")
            except Exception:
                logger.debug("File watch check failed for %s", path, exc_info=True)

        if not self.watched_files:
            self._stop_timer()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        if self._timer is None:
            self._timer = self._set_interval(2.0, self.check)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    @staticmethod
    def _line_delta(old_content: str, new_content: str) -> str:
        """Compute a ``(+N, -M lines)`` summary between two strings."""
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        added = 0
        removed = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, old_lines, new_lines
        ).get_opcodes():
            if tag == "insert":
                added += j2 - j1
            elif tag == "delete":
                removed += i2 - i1
            elif tag == "replace":
                added += j2 - j1
                removed += i2 - i1
        parts = []
        if added:
            parts.append(f"+{added}")
        if removed:
            parts.append(f"-{removed}")
        if parts:
            return f" ({', '.join(parts)} lines)"
        return ""

    def _compute_diff(self, abs_path: str) -> str:
        """Return a formatted unified diff string for *abs_path*."""
        info = self.watched_files[abs_path]
        rel = os.path.relpath(abs_path)

        prev = info.get("prev_content")
        current = info.get("last_content")

        if prev is None and current is None:
            return f"[watch] No content captured yet for: {rel}"

        if prev is None:
            return (
                f"[watch] No previous version to diff against: {rel}\n"
                "Waiting for first change..."
            )

        diff_lines = list(
            difflib.unified_diff(
                prev.splitlines(keepends=True),
                current.splitlines(keepends=True) if current else [],
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )

        if not diff_lines:
            return f"[watch] No diff available for: {rel}"

        max_lines = 80
        truncated = len(diff_lines) > max_lines
        display = diff_lines[:max_lines]
        text = "".join(display)
        if truncated:
            text += f"\n... ({len(diff_lines) - max_lines} more lines)"

        return f"[watch] Diff for {rel}:\n{text}"
