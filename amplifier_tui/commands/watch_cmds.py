"""File watch commands."""

from __future__ import annotations

from datetime import datetime
import difflib
import os


class WatchCommandsMixin:
    """File watch commands."""

    def _cmd_watch(self, text: str) -> None:
        """Watch files for changes, list watches, stop, or show diffs."""
        text = text.strip()

        # /watch  — list current watches
        if not text:
            if not self._watched_files:
                self._add_system_message(
                    "No files being watched.\n"
                    "Watch: /watch <path>\n"
                    "Stop:  /watch stop <path> | /watch stop all\n"
                    "Diff:  /watch diff <path>"
                )
                return
            lines = ["Watched files:"]
            for path, info in self._watched_files.items():
                rel = os.path.relpath(path)
                lines.append(f"  {rel} (since {info['added_at'][:16]})")
            lines.append(f"\n{len(self._watched_files)} file(s) watched")
            self._add_system_message("\n".join(lines))
            return

        # /watch stop <path> | /watch stop all
        if text.startswith("stop ") or text == "stop":
            target = text[5:].strip() if text.startswith("stop ") else ""
            if not target:
                self._add_system_message("Usage: /watch stop <path> | /watch stop all")
                return
            if target == "all":
                count = len(self._watched_files)
                self._watched_files.clear()
                self._stop_watch_timer()
                self._add_system_message(f"Stopped watching {count} file(s)")
            else:
                abs_path = os.path.abspath(os.path.expanduser(target))
                if abs_path in self._watched_files:
                    del self._watched_files[abs_path]
                    if not self._watched_files:
                        self._stop_watch_timer()
                    self._add_system_message(
                        f"Stopped watching: {os.path.relpath(abs_path)}"
                    )
                else:
                    self._add_system_message(f"Not watching: {target}")
            return

        # /watch diff <path>
        if text.startswith("diff ") or text == "diff":
            target = text[5:].strip() if text.startswith("diff ") else ""
            if not target:
                self._add_system_message("Usage: /watch diff <path>")
                return
            abs_path = os.path.abspath(os.path.expanduser(target))
            if abs_path in self._watched_files:
                self._show_watch_diff(abs_path)
            else:
                self._add_system_message(f"Not watching: {target}")
            return

        # /watch <path>  — add a watch
        abs_path = os.path.abspath(os.path.expanduser(text))

        if not os.path.exists(abs_path):
            self._add_system_message(f"Path not found: {text}")
            return

        if len(self._watched_files) >= 10:
            self._add_system_message(
                "Maximum 10 watched files. Use /watch stop <path> to remove one."
            )
            return

        if abs_path in self._watched_files:
            self._add_system_message(f"Already watching: {os.path.relpath(abs_path)}")
            return

        stat = os.stat(abs_path)
        # Read initial content for future diff comparisons
        initial_content: str | None = None
        if os.path.isfile(abs_path):
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as f:
                    initial_content = f.read()
            except OSError:
                pass

        self._watched_files[abs_path] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "added_at": datetime.now().isoformat(),
            "prev_content": None,
            "last_content": initial_content,
        }

        self._start_watch_timer()
        self._add_system_message(f"Watching: {os.path.relpath(abs_path)}")

    def _start_watch_timer(self) -> None:
        """Start the 2-second polling timer for watched files."""
        if self._watch_timer is None:
            self._watch_timer = self.set_interval(2.0, self._check_watched_files)

    def _stop_watch_timer(self) -> None:
        """Stop the polling timer when no files are watched."""
        if self._watch_timer is not None:
            self._watch_timer.stop()
            self._watch_timer = None

    def _check_watched_files(self) -> None:
        """Periodic check for file changes (runs every 2s)."""
        for path, info in list(self._watched_files.items()):
            try:
                if not os.path.exists(path):
                    rel = os.path.relpath(path)
                    self._add_system_message(f"[watch] File removed: {rel}")
                    del self._watched_files[path]
                    continue

                stat = os.stat(path)
                if stat.st_mtime != info["mtime"] or stat.st_size != info["size"]:
                    rel = os.path.relpath(path)

                    # Read new content for diff (only on change, not every poll)
                    new_content: str | None = None
                    line_delta_str = ""
                    if os.path.isfile(path):
                        try:
                            with open(path, encoding="utf-8", errors="replace") as f:
                                new_content = f.read()
                        except OSError:
                            pass

                        if new_content is not None and info["last_content"] is not None:
                            old_lines = info["last_content"].splitlines()
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
                                line_delta_str = f" ({', '.join(parts)} lines)"

                    # Byte-level fallback when line diff isn't available
                    size_delta = stat.st_size - info["size"]
                    if not line_delta_str:
                        if size_delta > 0:
                            line_delta_str = f" (+{size_delta} bytes)"
                        elif size_delta < 0:
                            line_delta_str = f" ({size_delta} bytes)"

                    # Rotate content snapshots and update tracking
                    info["prev_content"] = info["last_content"]
                    info["last_content"] = new_content
                    info["mtime"] = stat.st_mtime
                    info["size"] = stat.st_size

                    self._add_system_message(f"[watch] Changed: {rel}{line_delta_str}")
                    self._notify_sound(event="file_change")
            except Exception:
                pass

        if not self._watched_files:
            self._stop_watch_timer()

