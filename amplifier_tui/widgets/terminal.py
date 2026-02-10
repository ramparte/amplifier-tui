"""Embedded terminal widget for Amplifier TUI.

Vendored and adapted from textual-terminal (MIT/LGPL-3.0) by mitosch.
Original: https://github.com/mitosch/textual-terminal

Changes from upstream:
- Removed broken Textual v5.3+ imports (DEFAULT_COLORS, ColorSystem)
- Forward parent environment variables to PTY subprocess
- Simplified to "system" colors only (no Textual color detection)
- Added Terminal.Stopped message for command termination
- Feature-flag guard via TERMINAL_AVAILABLE sentinel
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import shlex
import struct
from asyncio import Task

try:
    import fcntl
    import pty
    import termios

    import pyte
    from pyte.screens import Char

    TERMINAL_AVAILABLE = True
except ImportError:
    TERMINAL_AVAILABLE = False

from rich.color import ColorParseError
from rich.style import Style
from rich.text import Text

from textual import events, log
from textual.message import Message
from textual.widget import Widget


class _TerminalPyteScreen(pyte.Screen if TERMINAL_AVAILABLE else object):
    """Overrides pyte.Screen to handle TERM=xterm edge cases."""

    def set_margins(self, *args, **kwargs):
        kwargs.pop("private", None)
        return super().set_margins(*args, **kwargs)


class _TerminalDisplay:
    """Rich renderable for terminal screen buffer."""

    def __init__(self, lines: list[Text]) -> None:
        self.lines = lines

    def __rich_console__(self, _console, _options):
        for line in self.lines:
            yield line


_RE_ANSI_SEQUENCE = re.compile(r"(\x1b\[\??[\d;]*[a-zA-Z])")
_DECSET_PREFIX = "\x1b[?"


class Terminal(Widget, can_focus=True):
    """Embedded terminal widget using pyte for terminal emulation."""

    DEFAULT_CSS = """
    Terminal {
        background: $background;
    }
    """

    class Stopped(Message):
        """Posted when the terminal command exits."""

        def __init__(self, terminal: Terminal) -> None:
            self.terminal = terminal
            super().__init__()

    # Key → escape sequence mapping
    _CTRL_KEYS = {
        "up": "\x1bOA",
        "down": "\x1bOB",
        "right": "\x1bOC",
        "left": "\x1bOD",
        "home": "\x1bOH",
        "end": "\x1b[F",
        "delete": "\x1b[3~",
        "pageup": "\x1b[5~",
        "pagedown": "\x1b[6~",
        "shift+tab": "\x1b[Z",
        "f1": "\x1bOP",
        "f2": "\x1bOQ",
        "f3": "\x1bOR",
        "f4": "\x1bOS",
        "f5": "\x1b[15~",
        "f6": "\x1b[17~",
        "f7": "\x1b[18~",
        "f8": "\x1b[19~",
        "f9": "\x1b[20~",
        "f10": "\x1b[21~",
        "f11": "\x1b[23~",
        "f12": "\x1b[24~",
    }

    def __init__(
        self,
        command: str | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        shell = command or os.environ.get("SHELL", "/bin/bash")
        self.command = shell

        self.ncol = 80
        self.nrow = 24
        self.mouse_tracking = False

        self._emulator: _TerminalEmulator | None = None
        self._send_queue: asyncio.Queue | None = None
        self._recv_queue: asyncio.Queue | None = None
        self._recv_task: Task | None = None

        self._screen = _TerminalPyteScreen(self.ncol, self.nrow)
        self._stream = pyte.Stream(self._screen)
        self._display: _TerminalDisplay = _TerminalDisplay([Text()])

        super().__init__(name=name, id=id, classes=classes)

    def start(self) -> None:
        """Start the terminal subprocess."""
        if self._emulator is not None:
            return
        self._emulator = _TerminalEmulator(command=self.command)
        self._emulator.start()
        self._send_queue = self._emulator.recv_queue
        self._recv_queue = self._emulator.send_queue
        self._recv_task = asyncio.create_task(self._recv())

    def stop(self) -> None:
        """Stop the terminal subprocess."""
        if self._emulator is None:
            return
        self._display = _TerminalDisplay([Text()])
        if self._recv_task is not None:
            self._recv_task.cancel()
        self._emulator.stop()
        self._emulator = None

    @property
    def is_running(self) -> bool:
        """Whether the terminal subprocess is active."""
        return self._emulator is not None

    def render(self):
        return self._display

    async def on_key(self, event: events.Key) -> None:
        if self._emulator is None:
            return

        # Ctrl+F1 releases focus back to the app
        if event.key == "ctrl+f1":
            self.app.set_focus(None)
            return

        event.stop()
        char = self._CTRL_KEYS.get(event.key) or event.character
        if char and self._send_queue is not None:
            await self._send_queue.put(["stdin", char])

    async def on_resize(self, _event: events.Resize) -> None:
        if self._emulator is None:
            return
        self.ncol = self.size.width
        self.nrow = self.size.height
        if self._send_queue is not None:
            await self._send_queue.put(["set_size", self.nrow, self.ncol])
        self._screen.resize(self.nrow, self.ncol)

    async def on_click(self, event: events.MouseEvent) -> None:
        if self._emulator is None or not self.mouse_tracking:
            return
        if self._send_queue is not None:
            await self._send_queue.put(["click", event.x, event.y, event.button])

    async def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self._emulator is None or not self.mouse_tracking:
            return
        if self._send_queue is not None:
            await self._send_queue.put(["scroll", "down", event.x, event.y])

    async def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self._emulator is None or not self.mouse_tracking:
            return
        if self._send_queue is not None:
            await self._send_queue.put(["scroll", "up", event.x, event.y])

    async def _recv(self) -> None:
        """Receive loop: reads PTY output and renders to screen buffer."""
        try:
            while True:
                if self._recv_queue is None:
                    break
                message = await self._recv_queue.get()
                cmd = message[0]

                if cmd == "setup":
                    if self._send_queue is not None:
                        await self._send_queue.put(["set_size", self.nrow, self.ncol])

                elif cmd == "stdout":
                    chars = message[1]
                    # Track mouse mode changes
                    for sep_match in re.finditer(_RE_ANSI_SEQUENCE, chars):
                        seq = sep_match.group(0)
                        if seq.startswith(_DECSET_PREFIX):
                            params = seq.removeprefix(_DECSET_PREFIX).split(";")
                            if "1000h" in params:
                                self.mouse_tracking = True
                            if "1000l" in params:
                                self.mouse_tracking = False

                    try:
                        self._stream.feed(chars)
                    except TypeError as error:
                        log.warning("could not feed:", error)

                    self._render_screen()

                elif cmd == "disconnect":
                    self.stop()
                    self.post_message(self.Stopped(self))

        except asyncio.CancelledError:
            pass

    def _render_screen(self) -> None:
        """Render the pyte screen buffer into Rich Text lines."""
        lines: list[Text] = []
        for y in range(self._screen.lines):
            line_text = Text()
            line = self._screen.buffer[y]
            style_change_pos: int = 0

            for x in range(self._screen.columns):
                char: Char = line[x]
                line_text.append(char.data)

                if x > 0:
                    last_char: Char = line[x - 1]
                    if (
                        not self._char_style_eq(char, last_char)
                        or x == self._screen.columns - 1
                    ):
                        style = self._char_to_style(last_char)
                        if style:
                            line_text.stylize(style, style_change_pos, x + 1)
                        style_change_pos = x

                if self._screen.cursor.x == x and self._screen.cursor.y == y:
                    line_text.stylize("reverse", x, x + 1)

            lines.append(line_text)

        self._display = _TerminalDisplay(lines)
        self.refresh()

    @staticmethod
    def _char_to_style(char: Char) -> Style | None:
        """Convert a pyte Char to a Rich Style."""
        fg = _fix_color(char.fg)
        bg = _fix_color(char.bg)
        try:
            return Style(
                color=fg if fg != "default" else None,
                bgcolor=bg if bg != "default" else None,
                bold=char.bold,
            )
        except ColorParseError as error:
            log.warning("color parse error:", error)
            return None

    @staticmethod
    def _char_style_eq(a: Char, b: Char) -> bool:
        """Compare two pyte Chars for style equality."""
        return (
            a.fg == b.fg
            and a.bg == b.bg
            and a.bold == b.bold
            and a.italics == b.italics
            and a.underscore == b.underscore
            and a.strikethrough == b.strikethrough
            and a.reverse == b.reverse
            and a.blink == b.blink
        )


def _fix_color(color: str) -> str:
    """Normalize pyte color names for Rich."""
    if color == "brown":
        return "yellow"
    if color == "brightblack":
        return "#808080"
    if re.match("[0-9a-f]{6}", color, re.IGNORECASE):
        return f"#{color}"
    return color


class _TerminalEmulator:
    """PTY subprocess manager."""

    def __init__(self, command: str) -> None:
        self.ncol = 80
        self.nrow = 24
        self.data_or_disconnect: str | None = None
        self.run_task: asyncio.Task | None = None
        self.send_task: asyncio.Task | None = None

        self.fd = self._open_pty(command)
        self.p_out = os.fdopen(self.fd, "w+b", 0)
        self.recv_queue: asyncio.Queue = asyncio.Queue()
        self.send_queue: asyncio.Queue = asyncio.Queue()
        self.event = asyncio.Event()
        self.pid: int  # set in _open_pty

    def start(self) -> None:
        self.run_task = asyncio.create_task(self._run())
        self.send_task = asyncio.create_task(self._send_data())

    def stop(self) -> None:
        if self.run_task:
            self.run_task.cancel()
        if self.send_task:
            self.send_task.cancel()
        try:
            os.kill(self.pid, signal.SIGTERM)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass

    def _open_pty(self, command: str) -> int:
        """Fork a PTY and exec the command with full parent env."""
        self.pid, fd = pty.fork()
        if self.pid == 0:
            argv = shlex.split(command)
            # Forward parent env, override TERM for compatibility
            env = os.environ.copy()
            env["TERM"] = "xterm"
            os.execvpe(argv[0], argv, env)
        return fd

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()

        def on_output():
            try:
                self.data_or_disconnect = self.p_out.read(65536).decode()
                self.event.set()
            except UnicodeDecodeError as error:
                log.warning("decode error:", error)
            except Exception:
                loop.remove_reader(self.p_out)
                self.data_or_disconnect = None
                self.event.set()

        loop.add_reader(self.p_out, on_output)
        await self.send_queue.put(["setup", {}])
        try:
            while True:
                msg = await self.recv_queue.get()
                if msg[0] == "stdin":
                    self.p_out.write(msg[1].encode())
                elif msg[0] == "set_size":
                    winsize = struct.pack("HH", msg[1], msg[2])
                    fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
                elif msg[0] == "click":
                    x = msg[1] + 1
                    y = msg[2] + 1
                    if msg[3] == 1:
                        self.p_out.write(f"\x1b[<0;{x};{y}M".encode())
                        self.p_out.write(f"\x1b[<0;{x};{y}m".encode())
                elif msg[0] == "scroll":
                    x = msg[2] + 1
                    y = msg[3] + 1
                    if msg[1] == "up":
                        self.p_out.write(f"\x1b[<64;{x};{y}M".encode())
                    if msg[1] == "down":
                        self.p_out.write(f"\x1b[<65;{x};{y}M".encode())
        except asyncio.CancelledError:
            pass

    async def _send_data(self) -> None:
        try:
            while True:
                await self.event.wait()
                self.event.clear()
                if self.data_or_disconnect is not None:
                    await self.send_queue.put(["stdout", self.data_or_disconnect])
                else:
                    await self.send_queue.put(["disconnect", 1])
        except asyncio.CancelledError:
            pass
