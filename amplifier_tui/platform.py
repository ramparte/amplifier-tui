"""Cross-platform abstractions for Amplifier TUI.

Detects the runtime platform once at import time and provides
platform-appropriate paths, tools, and behaviors. Every other module
imports from here instead of doing its own platform detection.

Supported platforms:
  - linux   (native Linux)
  - wsl     (Windows Subsystem for Linux)
  - macos   (macOS / Darwin)
  - windows (native Windows / PowerShell)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .log import logger

# ---------------------------------------------------------------------------
# Platform detection (runs once at import time)
# ---------------------------------------------------------------------------

_system = platform.system()  # "Linux", "Darwin", "Windows"

try:
    _uname_release = platform.uname().release.lower()
except OSError:
    _uname_release = ""

IS_WINDOWS = _system == "Windows"
IS_MACOS = _system == "Darwin"
IS_LINUX = _system == "Linux"
IS_WSL = IS_LINUX and "microsoft" in _uname_release

if IS_WINDOWS:
    PLATFORM = "windows"
elif IS_WSL:
    PLATFORM = "wsl"
elif IS_MACOS:
    PLATFORM = "macos"
else:
    PLATFORM = "linux"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def amplifier_home() -> Path:
    """Return the canonical Amplifier config/data directory.

    ``~/.amplifier`` on every platform -- this is the Amplifier ecosystem
    convention and matches what amplifier-core uses everywhere.
    """
    return Path.home() / ".amplifier"


def amplifier_tui_file(name: str) -> Path:
    """Return ``~/.amplifier/<name>`` for a TUI-specific data file."""
    return amplifier_home() / name


def amplifier_projects_dir() -> Path:
    """Return ``~/.amplifier/projects`` where sessions are stored."""
    return amplifier_home() / "projects"


def amplifier_uv_site_packages() -> Path | None:
    """Discover the site-packages directory for the ``amplifier`` uv tool.

    Tries (in order):
    1. ``uv tool dir`` command output  (works on all platforms)
    2. Platform-specific well-known paths as fallback

    Returns None if not found.
    """
    # Strategy 1: Ask uv directly (most reliable, cross-platform)
    uv = shutil.which("uv")
    if uv:
        try:
            result = subprocess.run(
                [uv, "tool", "dir"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                tool_dir = Path(result.stdout.strip()) / "amplifier"
                sp = _find_site_packages_in(tool_dir)
                if sp:
                    return sp
        except (subprocess.SubprocessError, OSError):
            logger.debug("uv tool dir failed", exc_info=True)

    # Strategy 2: Well-known paths per platform
    candidates: list[Path] = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(Path(local) / "uv" / "tools" / "amplifier")
    elif IS_MACOS:
        candidates.append(
            Path.home()
            / "Library"
            / "Application Support"
            / "uv"
            / "tools"
            / "amplifier"
        )
        candidates.append(
            Path.home() / ".local" / "share" / "uv" / "tools" / "amplifier"
        )
    else:
        # Linux / WSL
        candidates.append(
            Path.home() / ".local" / "share" / "uv" / "tools" / "amplifier"
        )

    for base in candidates:
        sp = _find_site_packages_in(base)
        if sp:
            return sp

    return None


def _find_site_packages_in(tool_dir: Path) -> Path | None:
    """Look for site-packages inside a uv tool installation directory."""
    if not tool_dir.exists():
        return None
    lib_dir = tool_dir / "lib"
    if not lib_dir.exists():
        # Windows layout: Lib/site-packages (capital L)
        lib_dir = tool_dir / "Lib"
    if not lib_dir.exists():
        return None
    for child in lib_dir.iterdir():
        if child.name.startswith("python"):
            sp = child / "site-packages"
            if sp.exists():
                return sp
    # Windows: Lib/site-packages directly (no pythonX.Y subdirectory)
    sp = lib_dir / "site-packages"
    if sp.exists():
        return sp
    return None


# ---------------------------------------------------------------------------
# Editors
# ---------------------------------------------------------------------------


def editor_candidates() -> list[str | None]:
    """Return an ordered list of editor candidates for the current platform.

    Includes $VISUAL and $EDITOR (which may be None), followed by
    platform-appropriate fallbacks.
    """
    env_editors: list[str | None] = [
        os.environ.get("VISUAL"),
        os.environ.get("EDITOR"),
    ]
    if IS_WINDOWS:
        return [*env_editors, "code", "notepad"]
    if IS_MACOS:
        return [*env_editors, "nano", "vim", "vi", "code"]
    # Linux / WSL
    return [*env_editors, "nano", "vim", "vi"]


def no_editor_message() -> str:
    """Return a helpful error message when no editor is found."""
    if IS_WINDOWS:
        return "No editor found. Set %EDITOR% or install VS Code."
    return "No editor found. Set $EDITOR or install vim/nano."


# ---------------------------------------------------------------------------
# Shell execution (/run command)
# ---------------------------------------------------------------------------

# Platform-appropriate dangerous command patterns for /run safety
if IS_WINDOWS:
    DANGEROUS_PATTERNS: tuple[str, ...] = (
        "del /s /q c:\\",
        "rd /s /q c:\\",
        "format c:",
        "remove-item -recurse -force c:\\",
        "rm -rf /",  # in case someone tries unix commands
        "rm -rf /*",
    )
else:
    DANGEROUS_PATTERNS: tuple[str, ...] = (
        "rm -rf /",
        "rm -rf /*",
        "sudo rm",
        "mkfs",
        "dd if=",
        ":(){:|:&};:",
        "> /dev/sda",
    )


def shell_name() -> str:
    """Return a human-readable name for the platform's default shell."""
    if IS_WINDOWS:
        # Check if running in PowerShell vs cmd
        if os.environ.get("PSModulePath"):
            return "PowerShell"
        return "cmd.exe"
    shell = os.environ.get("SHELL", "/bin/sh")
    return Path(shell).name


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

import base64  # noqa: E402


def copy_to_clipboard(text: str) -> bool:
    """Copy *text* to the system clipboard using the best available method.

    Tries in order:
    1. OSC 52 terminal escape (works over SSH, in modern terminals)
    2. Platform-native clipboard tool
    """
    # OSC 52: works in most modern terminals (WezTerm, iTerm2, kitty, etc.)
    try:
        encoded = base64.b64encode(text.encode()).decode()
        sys.stdout.write(f"\033]52;c;{encoded}\a")
        sys.stdout.flush()
        return True
    except OSError:
        logger.debug("OSC 52 clipboard write failed", exc_info=True)

    # Platform-specific fallbacks
    if IS_WSL:
        return _clip_wsl(text)
    if IS_WINDOWS:
        return _clip_windows(text)
    if IS_MACOS:
        return _clip_macos(text)
    return _clip_linux(text)


def _clip_wsl(text: str) -> bool:
    """WSL: use clip.exe with UTF-16LE encoding."""
    if not shutil.which("clip.exe"):
        return False
    try:
        proc = subprocess.Popen(
            ["clip.exe"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.communicate(text.encode("utf-16-le"))
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        logger.debug("clip.exe clipboard copy failed", exc_info=True)
        return False


def _clip_windows(text: str) -> bool:
    """Native Windows: use clip.exe (UTF-8 on modern Windows)."""
    if not shutil.which("clip.exe"):
        return False
    try:
        proc = subprocess.Popen(
            ["clip.exe"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.communicate(text.encode())
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        logger.debug("clip.exe clipboard copy failed", exc_info=True)
        return False


def _clip_macos(text: str) -> bool:
    """macOS: use pbcopy."""
    if not shutil.which("pbcopy"):
        return False
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=2)
        return True
    except (subprocess.SubprocessError, OSError):
        logger.debug("pbcopy clipboard copy failed", exc_info=True)
        return False


def _clip_linux(text: str) -> bool:
    """Linux: try wl-copy (Wayland), xclip, xsel."""
    for cmd in [
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ]:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=2)
                return True
            except (subprocess.SubprocessError, OSError):
                logger.debug("Clipboard via %s failed", cmd[0], exc_info=True)
                continue
    return False


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def send_notification(title: str, body: str = "") -> None:
    """Send a desktop/terminal notification using the best available method.

    Writes to sys.__stdout__ to bypass Textual's stdout capture.
    """
    out = sys.__stdout__
    if out is None:
        return

    try:
        if IS_WINDOWS:
            # On Windows Terminal: BEL works, OSC 9 may work
            out.write("\a")
            out.flush()
            # Also try PowerShell toast (best-effort, non-blocking)
            _toast_windows(title, body)
            return

        if IS_MACOS:
            # OSC 9 (iTerm2, WezTerm, kitty) + BEL
            out.write(f"\033]9;{title}: {body}\a")
            out.write("\a")
            out.flush()
            # Also try osascript for native Notification Center
            _notify_macos(title, body)
            return

        # Linux / WSL: OSC 9 + OSC 777 + BEL
        out.write(f"\033]9;{title}: {body}\a")
        out.write(f"\033]777;notify;{title};{body}\a")
        out.write("\a")
        out.flush()
    except OSError:
        logger.debug("Notification write failed", exc_info=True)


def play_bell() -> None:
    """Write BEL character to the real terminal."""
    out = sys.__stdout__
    if out is None:
        return
    try:
        out.write("\a")
        out.flush()
    except OSError:
        logger.debug("Terminal bell write failed", exc_info=True)


def _toast_windows(title: str, body: str) -> None:
    """Best-effort Windows toast notification via PowerShell."""
    ps = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not ps:
        return
    # Simple BurntToast or basic toast - best effort
    try:
        subprocess.Popen(
            [ps, "-NoProfile", "-Command", "[console]::beep(800,200)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _notify_macos(title: str, body: str) -> None:
    """Best-effort macOS Notification Center via osascript."""
    if not shutil.which("osascript"):
        return
    # Escape single quotes in the strings
    safe_title = title.replace("'", "'\\''")
    safe_body = body.replace("'", "'\\''")
    try:
        subprocess.Popen(
            [
                "osascript",
                "-e",
                f'display notification "{safe_body}" with title "{safe_title}"',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Terminal title
# ---------------------------------------------------------------------------


def set_terminal_title(title: str) -> None:
    """Set the terminal window title via OSC 2 escape sequence."""
    out = sys.__stdout__
    if out is None:
        return
    try:
        out.write(f"\033]2;{title}\a")
        out.flush()
    except OSError:
        logger.debug("Failed to set terminal title", exc_info=True)


# ---------------------------------------------------------------------------
# @-file mention regex
# ---------------------------------------------------------------------------

import re  # noqa: E402

if IS_WINDOWS:
    # Match @./path, @../path, @~/path, @/path, and @C:\path (drive letter)
    AT_MENTION_RE = re.compile(r"@((?:\.\.?[/\\]|~/|/|[A-Za-z]:[/\\])\S+)")
else:
    # Match @./path, @../path, @~/path, @/path
    AT_MENTION_RE = re.compile(r"@((?:\.\.?/|~/|/)\S+)")


# ---------------------------------------------------------------------------
# Session path reconstruction
# ---------------------------------------------------------------------------


def reconstruct_project_path(encoded_name: str) -> str:
    """Decode an Amplifier project directory name back to a filesystem path.

    Amplifier encodes project paths as directory names by replacing
    path separators with hyphens. E.g.:
        -home-user-dev-project -> /home/user/dev/project

    On Windows, paths may be encoded as:
        C--Users-user-dev-project -> C:\\Users\\user\\dev\\project
    """
    if not encoded_name:
        return encoded_name

    # Windows drive-letter encoding: "C-" prefix (letter followed by single hyphen)
    if len(encoded_name) >= 2 and encoded_name[0].isalpha() and encoded_name[1] == "-":
        # Looks like a Windows drive letter: C-Users-... -> C:\Users\...
        drive = encoded_name[0]
        rest = encoded_name[2:]
        if IS_WINDOWS:
            return f"{drive}:\\" + rest.replace("-", "\\")
        # On Unix viewing Windows-encoded paths, use forward slashes
        return f"{drive}:/" + rest.replace("-", "/")

    # Unix encoding: -home-user-project -> /home/user/project
    if encoded_name.startswith("-"):
        sep = "\\" if IS_WINDOWS else "/"
        return sep + encoded_name[1:].replace("-", sep)

    # Unknown format -- return as-is
    return encoded_name


# ---------------------------------------------------------------------------
# Path display helpers
# ---------------------------------------------------------------------------


def abbreviate_home(path_str: str) -> str:
    """Replace the user's home directory prefix with ``~``."""
    home = str(Path.home())
    if path_str.startswith(home):
        return "~" + path_str[len(home) :]
    return path_str
