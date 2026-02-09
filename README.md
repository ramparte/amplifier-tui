# Amplifier TUI

A rich terminal user interface for Amplifier, built with [Textual](https://textual.textualize.io/).

## Features

- Rich chat interface with role-based message coloring
- Session resumption (load and continue past conversations)
- Streaming responses with live tool-use display
- Multi-tab support for parallel conversations
- 11 built-in color themes (dark, light, solarized, monokai, nord, dracula, etc.)
- Customizable via `~/.amplifier/tui-preferences.yaml`
- Cross-platform (Linux, macOS, Windows/WSL)

## Installation

```bash
cd amplifier-tui
uv venv
source .venv/bin/activate
uv pip install -e .
```

## Usage

### Start a New Session

```bash
amplifier-tui
```

### Resume a Session

Resume the most recent session:

```bash
amplifier-tui --resume
```

Resume a specific session by ID:

```bash
amplifier-tui --session <session-id>
```

## Keyboard Shortcuts

- `Enter` - Send message
- `Ctrl+C` or `Ctrl+D` - Quit
- `/help` - List all slash commands

## Architecture

```
amplifier_tui/
├── __main__.py           # CLI entry point
├── app.py                # Main Textual app
├── platform.py           # Cross-platform abstractions
├── theme.py              # Color themes
├── preferences.py        # User preference management
├── session_manager.py    # Amplifier session wrapper
├── transcript_loader.py  # Load transcript.jsonl files
├── history.py            # Prompt history (Up/Down arrow)
├── constants.py          # Shared constants
├── commands/             # Slash command mixins
├── features/             # Feature modules (notifications, etc.)
└── styles.tcss           # Textual CSS
```

## Next Steps (See ROADMAP.md)

See `ROADMAP.md` for the full feature roadmap.
