"""Pure-function git helpers.

Every function in this module is stateless — it takes explicit parameters
and returns a value.  No ``self`` references, no widget access.
"""

from __future__ import annotations

import os
import re
import subprocess


def run_git(*args: str, cwd: str | None = None) -> tuple[bool, str]:
    """Run a git command and return *(success, output)*."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd or os.getcwd(),
        )
        return (
            result.returncode == 0,
            result.stdout.strip() or result.stderr.strip(),
        )
    except FileNotFoundError:
        return False, "git not found"
    except subprocess.TimeoutExpired:
        return False, "git command timed out"
    except Exception as exc:
        return False, str(exc)


def looks_like_commit_ref(text: str) -> bool:
    """Check if *text* looks like a git commit reference."""
    if text.startswith("HEAD"):
        return True
    # SHA-like hex string (7-40 chars)
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", text):
        return True
    # Contains ~ or ^ (e.g., main~3, abc123^2)
    if "~" in text or "^" in text:
        return True
    return False


def colorize_diff(diff_text: str) -> str:
    """Apply Rich markup colors to diff output."""
    from rich.markup import escape

    lines: list[str] = []
    for line in diff_text.split("\n"):
        escaped = escape(line)
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f"[bold]{escaped}[/bold]")
        elif line.startswith("@@"):
            lines.append(f"[cyan]{escaped}[/cyan]")
        elif line.startswith("+"):
            lines.append(f"[green]{escaped}[/green]")
        elif line.startswith("-"):
            lines.append(f"[red]{escaped}[/red]")
        elif line.startswith("diff "):
            lines.append(f"[bold yellow]{escaped}[/bold yellow]")
        else:
            lines.append(escaped)
    return "\n".join(lines)


def show_diff(diff_output: str, header: str = "", max_lines: int = 500) -> str:
    """Return a colorized, possibly truncated diff string.

    Unlike the original ``_show_diff`` method this does **not** call
    ``_add_system_message`` — the caller is responsible for displaying
    the result.
    """
    all_lines = diff_output.split("\n")
    total = len(all_lines)
    truncated = total > max_lines

    text = "\n".join(all_lines[:max_lines]) if truncated else diff_output
    colored = colorize_diff(text)

    if header:
        from rich.markup import escape

        colored = escape(header) + colored

    if truncated:
        colored += (
            f"\n\n... truncated ({total} total lines)."
            " Use /diff <file> to see specific files."
        )

    return colored
