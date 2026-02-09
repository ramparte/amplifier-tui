"""File watch commands."""

from __future__ import annotations

from datetime import datetime
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
        """Start the 2-second polling timer for watched files.

        Thin adapter — delegates to :meth:`FileWatcher._start_timer`.
        """
        self._file_watcher._start_timer()

    def _stop_watch_timer(self) -> None:
        """Stop the polling timer when no files are watched.

        Thin adapter — delegates to :meth:`FileWatcher._stop_timer`.
        """
        self._file_watcher._stop_timer()

    def _check_watched_files(self) -> None:
        """Periodic check for file changes (runs every 2s).

        Thin adapter — delegates to :meth:`FileWatcher.check`.
        """
        self._file_watcher.check()
