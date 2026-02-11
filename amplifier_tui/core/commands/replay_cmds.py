"""Session replay commands (F3.3 - Session Replay)."""

from __future__ import annotations


class ReplayCommandsMixin:
    """Mixin providing /replay command for session replay."""

    def _cmd_replay(self, args: str = "") -> None:
        """Handle /replay subcommands.

        Subcommands:
            /replay              Show status
            /replay status       Show replay state
            /replay pause        Pause playback
            /replay resume       Resume playback
            /replay skip         Skip to next message
            /replay stop         Stop replay
            /replay speed <N>x   Set speed (0.5x, 1x, 2x, 5x, instant)
            /replay timeline     Show timeline window
            /replay clear        Clear replay state
            /replay <session_id> Load session for replay
        """
        text = args.strip() if args else ""

        if not text:
            self._add_system_message(self._replay_engine.format_status())  # type: ignore[attr-defined]
            return

        if text == "status":
            self._add_system_message(self._replay_engine.format_status())  # type: ignore[attr-defined]
            return

        if text == "pause":
            self._replay_engine.pause()  # type: ignore[attr-defined]
            self._add_system_message(  # type: ignore[attr-defined]
                "[yellow]\u23f8 Replay paused.[/yellow] Use /replay resume to continue."
            )
            return

        if text == "resume":
            self._replay_engine.resume()  # type: ignore[attr-defined]
            self._add_system_message("[green]\u25b6 Replay resumed.[/green]")  # type: ignore[attr-defined]
            return

        if text == "stop":
            self._replay_engine.stop()  # type: ignore[attr-defined]
            self._add_system_message("Replay stopped.")  # type: ignore[attr-defined]
            return

        if text == "skip":
            msg = self._replay_engine.skip()  # type: ignore[attr-defined]
            if msg:
                preview = msg.content[:100].replace("\n", " ")
                self._add_system_message(  # type: ignore[attr-defined]
                    f"Skipped to: [{msg.role}] {preview}"
                )
            else:
                self._add_system_message("No more messages to skip to.")  # type: ignore[attr-defined]
            return

        if text == "timeline":
            self._add_system_message(self._replay_engine.format_timeline())  # type: ignore[attr-defined]
            return

        if text.startswith("speed "):
            speed = text[6:].strip()
            try:
                self._replay_engine.set_speed(speed)  # type: ignore[attr-defined]
                self._add_system_message(  # type: ignore[attr-defined]
                    f"Replay speed set to {self._replay_engine.speed_label}."  # type: ignore[attr-defined]
                )
            except ValueError as e:
                self._add_system_message(f"[red]Error:[/red] {e}")  # type: ignore[attr-defined]
            return

        if text == "clear":
            self._replay_engine.clear()  # type: ignore[attr-defined]
            self._add_system_message("Replay state cleared.")  # type: ignore[attr-defined]
            return

        # Otherwise treat as session_id to load
        self._add_system_message(  # type: ignore[attr-defined]
            f"Loading session '{text}' for replay...\n\n"
            "[dim]Note: Session loading requires access to transcript files.\n"
            "Use the session's transcript.jsonl path for full replay.[/dim]\n\n"
            "Commands:\n"
            "  /replay              Show status\n"
            "  /replay pause        Pause playback\n"
            "  /replay resume       Resume playback\n"
            "  /replay skip         Skip to next message\n"
            "  /replay stop         Stop replay\n"
            "  /replay speed <N>x   Set speed (0.5x, 1x, 2x, 5x, instant)\n"
            "  /replay timeline     Show timeline window\n"
            "  /replay clear        Clear replay state"
        )
