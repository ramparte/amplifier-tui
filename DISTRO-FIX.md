# Priority Fix: Eliminate the sys.path Hack

The sys.path hack in `session_manager.py:14-41` is the TUI's biggest
fragility. It manually reaches into uv's internal directory structure
(`~/.local/share/uv/tools/amplifier/lib/python3.x/site-packages/`) to
make amplifier imports work. This breaks when uv changes its layout,
when Python version changes, or on macOS where uv uses a different path.

## The Fix

Declare amplifier-app-cli as a proper dependency. Replace the hack
with normal Python imports.

### Step 1: Update pyproject.toml

```toml
[project]
name = "amplifier-tui"
version = "0.1.0"
description = "Textual TUI for Amplifier"
requires-python = ">=3.10"
dependencies = [
    "textual>=0.47.0",
    "amplifier-app-cli",
]

[tool.uv.sources]
amplifier-app-cli = { git = "https://github.com/microsoft/amplifier-app-cli" }
```

### Step 2: Delete lines 14-41 of session_manager.py

Remove the entire sys.path block. The imports of `amplifier_app_cli`
and `amplifier_core` will just work because they'll be installed in
the same venv as the TUI.

### Step 3: uv sync

```bash
uv sync
```

This installs everything (textual + amplifier + all its deps) into
one venv. No more global `uv tool install amplifier` requirement.

## What This Fixes

- No path assumptions about uv internals
- pyright can see the imports (type checking works)
- Works on any platform (Linux, macOS, WSL)
- `uv sync` is the only install step
- No more "amplifier must be installed globally first" prerequisite

## Context

This is tracked as task 2.3 in the amplifier-distro project:
https://github.com/ramparte/amplifier-distro/blob/main/IMPLEMENTATION.md
