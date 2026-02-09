# Amplifier TUI - Session Handoff

## Project

**Repo:** https://github.com/ramparte/amplifier-tui
**Location:** ~/dev/ANext/amplifier-tui
**Tech:** Python + Textual 7.5 TUI framework
**Origin:** Adapted from Claude Chic (https://matthewrocklin.com/introducing-claude-chic/), rewritten to use Amplifier's session/bundle/hook system instead of raw Anthropic API.

## What It Does

A terminal UI for Amplifier with:
- Chat interface with markdown rendering for assistant responses
- **Visually distinct message types** (user=orange/bold, assistant=blue, thinking=purple/italic, tools=gray/compact)
- Tool call display in collapsible blocks
- **Session sidebar (Ctrl+B)** with Tree widget - expandable folder groups, single-line session summaries
- Status bar with animated braille spinner during processing
- Lazy Amplifier loading for instant startup
- Multiline input (Ctrl+J for newline, Enter to submit)

## Architecture

- `app.py` - Main Textual App, widgets, UI layout, event handling
- `session_manager.py` - Wraps Amplifier's session lifecycle (start, resume, send, end)
- `transcript_loader.py` - Replays transcript.jsonl into the chat view on resume
- `theme.py` - Color theme
- `styles.tcss` - Textual CSS
- `tools/` - UX testing tools (tui_capture.py, svg_parser.py, tui_analyze.py, ux_test.sh)

**Key design:** SessionManager imports from `amplifier_app_cli` and `amplifier_core` at runtime via sys.path manipulation (line 14-41 of session_manager.py). These packages are installed globally via `uv tool install amplifier`, not in the project venv. This means pyright will complain about missing imports - that's expected and correct.

## Session Save Bug: FIXED

**Problem:** When you quit and resume, the last turn was missing. The `action_quit` called `await self.session_manager.end_session()` before `self.exit()`, but Textual's event loop killed the async cleanup mid-flight.

**Fix (commit 5e853fd):** Session cleanup now runs in a `@work(thread=True)` worker with its own event loop, and `action_quit` does `await worker.wait()` before calling `self.exit()`. This ensures the SESSION_END event and all hook flushes complete before the app exits.

The same pattern is used in `action_new_session` -> `_end_and_reset_session()`.

## Visual Distinction (commit 5e853fd)

Each message type is now visually distinct at a glance:

| Type | Left Border | Background | Text Style | Spacing |
|------|-------------|------------|------------|---------|
| User | thick orange `$primary` | transparent | **bold** | generous (margin 2) |
| Assistant | wide blue `$secondary` | transparent | normal markdown | normal (margin 1) |
| Thinking | wide purple `#665588` | dark tint `#0d0a12` | *italic*, dim | compact, indented |
| Tool calls | wide gray `#444444` | dark tint `#0a0a0a` | dim, compact | compact, indented |

Thinking blocks and tool calls both use Collapsible widgets (collapsed by default) with `▶` prefix in titles. Thinking blocks show `▶ Thinking: preview...`, tool calls show `▶ tool_name`.

## Session Sidebar (commit 5e853fd)

Switched from OptionList to **Tree widget**:
- Project folders are expandable tree nodes (last 2 path components shown)
- Sessions show as single-line leaves: `"Jan 05  Fix the save bug"`
- Session ID stored as node `data`, not displayed (available on selection)
- No more clipping/wrapping issues

## UX Testing Tools

Built and available in `tools/`:

| Tool | Purpose |
|------|---------|
| `tui_capture.py` | Headless screenshot (SVG + PNG) via Textual Pilot |
| `svg_parser.py` | Primary: extracts text, colors, styles from SVG (stdlib only) |
| `tui_analyze.py` | Supplementary: layout bands, color palette from PNG |
| `ux_test.sh` | One-command pipeline: capture + parse + analyze |

**Key insight:** SVG parsing beats OCR for TUI work. Textual's SVG export has every character with exact position, color, bold/italic state.

```bash
./tools/ux_test.sh --mock-chat --svg-only  # Fast validation
```

External toolkit reference: https://github.com/ramparte/amplifier-ux-analyzer (image recognition for more complex UX analysis).

## How to Run

```bash
cd ~/dev/ANext/amplifier-tui
source .venv/bin/activate
amplifier-tui
```

## Key Bindings

| Key | Action |
|-----|--------|
| Enter | Send message |
| Ctrl+J | Insert newline (multiline input) |
| Ctrl+B | Toggle session sidebar |
| Ctrl+N | New session |
| Ctrl+L | Clear chat |
| Ctrl+Q | Quit |

## Next Steps / Feature Ideas

### High Priority (UX Polish)

- **Streaming** - Currently waits for full response; stream tokens as they arrive via hooks (biggest perceived perf improvement)
- **Token/context usage in status bar** - Show context window usage percentage, like Claude Code does
- **Spinner with token count** - Show tokens accumulated during processing, not just braille spinner

### Medium Priority (Features from Claude Code Research)

- **Vim mode** - Claude Code has full vim keybindings (h/j/k/l, w/b/e, text objects, operators). Textual may support this via key bindings
- **Slash commands** - `/mode`, `/help`, `/theme`, `/clear`. Claude Code has a full command system
- **Command history** - Ctrl+R to search previous prompts (like readline)
- **External editor** - Ctrl+G to open $EDITOR for longer prompts (Claude Code does this)
- **Prompt stashing** - Ctrl+S to stash/restore current prompt (useful when you want to ask something else mid-thought)
- **Background tasks** - Ctrl+B to background a running task (Claude Code feature)
- **Image paste** - Cmd+V / Ctrl+V to paste images from clipboard
- **OSC 8 hyperlinks** - Clickable file paths in tool output (iTerm2, WezTerm, Ghostty, Kitty)
- **Progress indicators** - "Reading..." / "Searching..." labels during tool execution (more specific than just "Thinking")

### Lower Priority (Nice to Have)

- **Theme switching** - `/theme` command to pick from presets, or match terminal theme
- **Search sessions** - Filter/search in sidebar by text content
- **Copy/paste** - Easy copy of assistant responses
- **Faster session list** - Cache session metadata locally
- **iTerm2 progress bar** - OSC 9;4 integration for terminal tab progress
- **Notification on completion** - OSC escape sequences for terminal notifications when task completes
- **Custom status line** - Configurable status bar content (model, git branch, context %)
- **Keyboard shortcut customization** - User-configurable keybindings
- **IME support** - CJK input method editor support
- **Reduced motion mode** - Accessibility option to disable animations

## Project Conventions

- All pyright errors about missing imports (textual, amplifier_core, amplifier_app_cli) are expected - those packages aren't in the project venv
- Use `source .venv/bin/activate` before running
- The venv has textual and project deps; amplifier is accessed via sys.path from the global uv tool install
- Be careful with bash commands in the TUI directory - the venv's bin/amplifier-tui is a Python script, not a shell script
- Run `./tools/ux_test.sh --mock-chat --svg-only` after visual changes to validate styling
