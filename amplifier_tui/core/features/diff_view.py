"""Inline diff rendering for file-edit tool calls.

Pure functions that generate Rich-markup colored diffs from
``edit_file`` / ``write_file`` tool arguments.  Following the same
stateless pattern as :mod:`git_integration`.
"""

from __future__ import annotations

import difflib
import os

from rich.markup import escape


# --------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------


def format_edit_diff(file_path: str, old_string: str, new_string: str) -> str:
    """Generate Rich-markup colored unified diff for an *edit_file* operation.

    Returns a string ready to be displayed via ``Static(text, markup=True)``.
    """
    old_lines = old_string.splitlines(keepends=True)
    new_lines = new_string.splitlines(keepends=True)

    basename = os.path.basename(file_path)
    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{basename}",
            tofile=f"b/{basename}",
            n=3,
        )
    )

    if not diff:
        return f"[dim]No changes in {escape(file_path)}[/dim]"

    lines: list[str] = [f"[bold]{escape(file_path)}[/bold]", ""]
    for line in diff:
        line = line.rstrip("\n")
        escaped = escape(line)
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f"[bold]{escaped}[/bold]")
        elif line.startswith("@@"):
            lines.append(f"[cyan]{escaped}[/cyan]")
        elif line.startswith("+"):
            lines.append(f"[green]{escaped}[/green]")
        elif line.startswith("-"):
            lines.append(f"[red]{escaped}[/red]")
        else:
            lines.append(f"[dim]{escaped}[/dim]")

    return "\n".join(lines)


def format_new_file_diff(file_path: str, content: str) -> str:
    """Generate Rich-markup for a new/overwritten file (all lines green)."""
    lines: list[str] = [
        f"[bold]{escape(file_path)}[/bold] [dim](new file)[/dim]",
        "",
    ]

    content_lines = content.splitlines()
    max_lines = 200
    truncated = len(content_lines) > max_lines
    display_lines = content_lines[:max_lines] if truncated else content_lines

    for i, line in enumerate(display_lines, 1):
        escaped = escape(line)
        lines.append(f"[dim]{i:4d}[/dim] [green]+{escaped}[/green]")

    if truncated:
        remaining = len(content_lines) - max_lines
        lines.append(f"\n[dim]... and {remaining} more lines[/dim]")

    return "\n".join(lines)


def diff_summary(file_path: str, old_string: str, new_string: str) -> str:
    """Return a summary like ``'Edited src/auth.py (+12, -3)'``."""
    old_lines = old_string.splitlines(keepends=True)
    new_lines = new_string.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, n=0))

    additions = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    deletions = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))

    short = _short_path(file_path)
    return f"Edited {short} (+{additions}, -{deletions})"


def new_file_summary(file_path: str, content: str) -> str:
    """Return a summary like ``'Wrote src/auth.py (+25)'``."""
    line_count = len(content.splitlines()) if content else 0
    short = _short_path(file_path)
    return f"Wrote {short} (+{line_count})"


# --------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------


def _short_path(file_path: str) -> str:
    """Shorten a file path for display in titles."""
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return file_path
