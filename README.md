# Amplifier Chic - POC

A Textual TUI for Amplifier, inspired by Claude Chic's design.

## Status: Proof of Concept

This is an early POC demonstrating:
- ✅ Textual TUI with Claude Chic styling
- ✅ Session resumption (load transcript)
- ✅ Basic message input/output
- ⚠️ Amplifier integration (placeholder - needs real session API)

## Installation

```bash
cd amplifier-chic-poc
uv venv
source .venv/bin/activate
uv pip install -e .
```

## Usage

### Demo Mode (No Amplifier Required)

Just run it - it will echo your messages:

```bash
amplifier-chic
```

### Resume a Session

Resume the most recent session:

```bash
amplifier-chic --resume
```

Resume a specific session by ID:

```bash
amplifier-chic --session 426c8ab0-178f-43ed-b332-8df041dbab5e
```

**Note**: This will load and display the session transcript, but actual message sending requires proper Amplifier integration.

### Example: Resume This Session!

```bash
# Resume the session we're in right now
cd amplifier-chic-poc
source .venv/bin/activate
amplifier-chic --session 426c8ab0-178f-43ed-b332-8df041dbab5e
```

You'll see all the messages from this conversation displayed in the TUI!

## UI Features

**Current:**
- Chat message display with role-based coloring
  - User messages: Orange left border
  - Assistant messages: Blue left border
  - Tool uses: Gray left border (placeholder)
- Scrollable chat history
- Input box with Enter to submit
- Dark theme with constrained width

**Keyboard:**
- `Enter` - Send message
- `Ctrl+C` or `Ctrl+D` - Quit

## Architecture

```
amplifier_chic/
├── __main__.py           # CLI entry point
├── app.py                # Main Textual app
├── theme.py              # Claude Chic color scheme
├── styles.tcss           # Textual CSS
├── session_manager.py    # Amplifier session wrapper
└── transcript_loader.py  # Load transcript.jsonl files
```

## Next Steps (See ROADMAP.md)

Phase 1 (current):
- [x] Command-line args for resume
- [x] Load session transcript
- [x] Basic message input
- [ ] Real Amplifier session integration
- [ ] Stream responses in real-time

Phase 2:
- [ ] Tool use rendering (collapsible blocks)
- [ ] Multi-session support
- [ ] Bundle/mode indicators

## Known Issues

- **Amplifier integration is placeholder** - Uses echo mode instead of real sessions
- No streaming responses yet
- Tool uses not rendered separately
- No "thinking" indicator removal after response

## Why This POC Matters

We've successfully built a working Textual TUI - something that's been challenging before. The core UI works, styling is clean, and we can load/display sessions. The foundation is solid for adding real Amplifier integration.
