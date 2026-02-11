"""Shell escape commands (/shell)."""

from __future__ import annotations

import os
import subprocess


class ShellCommandsMixin:
    """Mixin providing the /shell command (suspend TUI, drop to bash)."""

    def _cmd_shell(self, args: str = "") -> None:
        """Suspend TUI and drop into an interactive shell."""
        shell = os.environ.get("SHELL", "/bin/bash")
        session_id = getattr(self, "session_id", None) or "none"

        def _run_shell() -> None:
            banner = (
                "\n"
                "--- Amplifier TUI shell escape ---\n"
                f"Session: {session_id}\n"
                "Type 'exit' to return to the TUI.\n"
            )
            print(banner)
            env = os.environ.copy()
            env["AMPLIFIER_TUI_SESSION"] = str(session_id)
            subprocess.call([shell, "-l"], env=env)

        with self.suspend():  # type: ignore[attr-defined]
            _run_shell()
