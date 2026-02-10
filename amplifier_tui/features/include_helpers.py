"""Pure-function helpers for the enhanced /include command.

Every function in this module is stateless -- it takes explicit parameters
and returns a value.  No ``self`` references, no widget access.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def get_directory_tree(
    root: str | Path, max_depth: int = 4, max_entries: int = 200
) -> str:
    """Generate a directory tree respecting .gitignore.

    Uses ``git ls-files`` if in a git repo, otherwise walks the filesystem
    excluding common patterns (.git, __pycache__, node_modules, .venv, etc.)

    Returns a formatted tree string with box-drawing characters.
    """
    root = Path(root)

    # Try git ls-files first
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = sorted(result.stdout.strip().split("\n"))
            return _build_tree(root.name, files, max_entries)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: walk filesystem
    EXCLUDE = {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
    # Collect up to max_entries + 1 so _build_tree can detect truncation.
    collect_limit = max_entries + 1
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter excluded dirs (including *.egg-info)
        dirnames[:] = [
            d for d in dirnames if d not in EXCLUDE and not d.endswith(".egg-info")
        ]
        rel = os.path.relpath(dirpath, root)
        depth = rel.count(os.sep) + 1 if rel != "." else 0
        if depth > max_depth:
            dirnames.clear()
            continue
        for f in sorted(filenames):
            if rel == ".":
                files.append(f)
            else:
                files.append(os.path.join(rel, f))
            if len(files) >= collect_limit:
                break
        if len(files) >= collect_limit:
            break

    return _build_tree(root.name, files, max_entries)


def _build_tree(root_name: str, files: list[str], max_entries: int) -> str:
    """Build a visual tree from a flat list of relative file paths."""
    if not files:
        return f"{root_name}/\n  (empty)"

    # Build a nested dict
    tree: dict = {}
    for f in files[:max_entries]:
        parts = f.replace("\\", "/").split("/")
        node = tree
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]

    lines = [f"{root_name}/"]
    _render_tree(tree, lines, "")

    if len(files) > max_entries:
        lines.append(f"  ... and {len(files) - max_entries} more files")

    return "\n".join(lines)


def _render_tree(tree: dict, lines: list[str], prefix: str) -> None:
    """Recursively render tree dict into lines with box-drawing characters."""
    items = sorted(tree.items())
    for i, (name, children) in enumerate(items):
        is_last = i == len(items) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "

        if children:  # directory
            lines.append(f"{prefix}{connector}{name}/")
            extension = "    " if is_last else "\u2502   "
            _render_tree(children, lines, prefix + extension)
        else:  # file
            lines.append(f"{prefix}{connector}{name}")


def get_git_status_and_diff(cwd: str | None = None) -> str:
    """Get git status + recent diff as a formatted string."""
    parts: list[str] = []

    # Git status
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if status:
                parts.append("Git Status:")
                parts.append(status)
            else:
                parts.append("Git Status: clean (no changes)")
        else:
            parts.append("Not a git repository")
            return "\n".join(parts)
        parts.append("")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        parts.append("Git status unavailable")
        return "\n".join(parts)

    # Recent diff (last 3 commits)
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD~3..HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append("Recent changes (last 3 commits):")
            parts.append(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Current diff if any
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append("")
            parts.append("Uncommitted changes:")
            parts.append(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return "\n".join(parts) if parts else "Not a git repository"


def file_preview(path: str | Path) -> str:
    """Generate a syntax-aware preview of a file.

    Shows: language (from extension), line count, file size, first 10 lines.
    """
    path = Path(path)
    if not path.exists():
        return f"File not found: {path}"
    if not path.is_file():
        return f"Not a file: {path}"

    size = path.stat().st_size

    # Detect language from extension
    LANG_MAP = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".jsx": "JSX",
        ".tsx": "TSX",
        ".rs": "Rust",
        ".go": "Go",
        ".java": "Java",
        ".c": "C",
        ".cpp": "C++",
        ".h": "C/C++ Header",
        ".rb": "Ruby",
        ".php": "PHP",
        ".swift": "Swift",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".json": "JSON",
        ".toml": "TOML",
        ".md": "Markdown",
        ".txt": "Text",
        ".sh": "Shell",
        ".bash": "Bash",
        ".css": "CSS",
        ".html": "HTML",
        ".xml": "XML",
        ".sql": "SQL",
    }
    ext = path.suffix.lower()
    lang = LANG_MAP.get(ext, ext[1:].upper() if ext else "Unknown")

    # Count lines and read preview
    try:
        with open(path, errors="replace") as f:
            lines = f.readlines()
        line_count = len(lines)
        preview_lines = lines[:10]
    except Exception:
        return f"Cannot read: {path}"

    # Format size
    if size < 1024:
        size_str = f"{size}B"
    elif size < 1024 * 1024:
        size_str = f"{size / 1024:.1f}KB"
    else:
        size_str = f"{size / (1024 * 1024):.1f}MB"

    result = [
        f"File: {path.name}",
        f"Language: {lang} | Lines: {line_count} | Size: {size_str}",
        "---",
    ]
    for i, line in enumerate(preview_lines, 1):
        result.append(f"  {i:4d} | {line.rstrip()}")
    if line_count > 10:
        result.append(f"  ... ({line_count - 10} more lines)")

    return "\n".join(result)
