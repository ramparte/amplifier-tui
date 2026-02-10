# amplifier-tui Build Session

You are building features for **amplifier-tui**, a Textual-based terminal UI for Amplifier.

## Project Context

- **Repo**: ~/dev/ANext/amplifier-tui
- **Tech**: Python 3.11+ / Textual 7.5 TUI framework
- **Runtime dependency**: Amplifier CLI (`uv tool install amplifier`) provides `amplifier_core`, `amplifier_app_cli`, `amplifier_foundation` at runtime. These are NOT in the project venv. Pyright errors about missing imports from these packages are expected and correct.
- **Origin**: Rewritten from Claude Chic (open-source TUI by Matthew Rocklin) to use Amplifier's session/bundle/hook system.
- **Current state**: 356/356 tests passing (263 unit + 93 interactive), 78+ slash commands, 38 keybindings, 13 persistence stores. Stable and healthy.

## Feature Backlog

Read `FEATURE-BACKLOG.md` at the project root for the complete feature specifications. It contains 16 features organized into waves:

**Wave 1 (Foundation)**: Command Palette (F1.1), Session Tags (F1.2), Clipboard Ring (F1.3), Inline Diff View (F2.4)
**Wave 2 (Transparency)**: Agent Tree View (F2.1), Context Window Profiler (F2.2), Live Tool Introspection (F4.1)
**Wave 3 (Workflow)**: Recipe Pipeline Viz (F2.3), Smart /include (F1.4), Conversation Branching (F3.1)
**Wave 4 (Advanced)**: Model A/B Testing (F3.2), Session Replay (F3.3), Semantic Cross-Session Search (F3.4)
**Wave 5 (Extensibility)**: Plugin System (F4.3), Session Heatmap Dashboard (F4.2), Voice Input (F4.4)

Each feature spec includes: description, detailed sub-features, implementation notes, and test IDs.

## How This Project Was Originally Built

The original build was a **38-hour marathon session** (`653a396c`) that produced 167 commits and spawned 440 sub-agents. The orchestrator session drove implementation by:

1. Giving high-level feature directives
2. Letting the agent build, test, and commit autonomously
3. Periodically checking in with feedback and new directions
4. A second session (`588bbe3a`) then drove a 6-phase refactoring with tests after each phase

The key to success was: **autonomous implementation with frequent commits and continuous testing.**

---

## Operating Mode: Autonomous Orchestrator

You are an **autonomous feature builder**. Your workflow for each feature:

### The Build Loop

```
1. READ the feature spec from FEATURE-BACKLOG.md
2. PLAN the implementation (which files to create/modify, what patterns to follow)
3. IMPLEMENT the feature
4. TEST -- run BOTH test suites:
   a. Unit tests: uv run python -m pytest tests/ -v
   b. Interactive tests: uv run python tools/interactive_test_runner.py --batch all
5. FIX any failures
6. COMMIT when stable (all tests green)
7. MOVE to the next feature
```

### Commit Discipline

**COMMIT AFTER EVERY STABLE FEATURE OR MEANINGFUL MILESTONE.**

Do not accumulate uncommitted changes across multiple features. The commit cadence should be:
- After each complete feature (all tests pass)
- After significant sub-milestones within complex features
- After fixing a batch of related issues
- Before starting a new feature (ensure clean state)

Commit message format:
```
feat: short description of what was added

Longer explanation if needed.

🤖 Generated with [Amplifier](https://github.com/microsoft/amplifier)

Co-Authored-By: Amplifier <240397093+microsoft-amplifier@users.noreply.github.com>
```

Use `feat:` for new features, `fix:` for bug fixes, `refactor:` for restructuring, `test:` for test-only changes.

### Testing Requirements

**Both test suites must pass before every commit.**

#### Unit Tests (pytest)

```bash
uv run python -m pytest tests/ -v
```

- 263 tests across 6 files
- Tests cover: commands, constants, features, persistence, utils, widgets
- When you add a new persistence store, add tests in `tests/test_persistence.py`
- When you add new utility functions, add tests in `tests/test_utils.py`
- When you add new commands, add attribute tests in `tests/test_commands.py`

#### Interactive Tests (Textual Pilot)

```bash
# Run all batches
uv run python tools/interactive_test_runner.py --batch all

# Run specific batch
uv run python tools/interactive_test_runner.py --batch 1

# Run multiple batches
uv run python tools/interactive_test_runner.py --batch 1,3
```

- 93 tests across 4 batches, run headlessly via Textual's Pilot
- Each test drives the app, submits commands/keys, and checks results
- Tests verify: no crash, no error messages, SVG has content, plus custom checks

**When adding new features, add interactive tests too.** See the test definition format below.

---

## Architecture Guide

### Directory Structure

```
amplifier_tui/
  app.py              # Main Textual App class (~5600 lines, the monolith)
  session_manager.py  # Wraps Amplifier session lifecycle
  transcript_loader.py # Replays transcript.jsonl on resume
  theme.py            # Color theme definitions
  styles.tcss         # Textual CSS stylesheet
  constants.py        # Constants, model lists, modes, extension maps
  commands/           # Slash command mixins (one file per domain)
    content_cmds.py   # mode, copy, undo, redo, retry, draft, autosave, etc.
    display_cmds.py   # compact, wrap, fold, timestamps, stream, scroll, focus
    export_cmds.py    # export, snippet operations
    file_cmds.py      # editor, run, include, notify, sound, attach
    git_cmds.py       # git status/log/branches, diff
    persistence_cmds.py # bookmark, pin, note, ref, alias, template
    search_cmds.py    # find, grep, search, history
    session_cmds.py   # new, clear, fork, sessions, delete, sort, quit
    split_cmds.py     # tab, split
    theme_cmds.py     # theme, colors
    token_cmds.py     # showtokens, contextwindow, stats, info, tokens
    watch_cmds.py     # watch (file watcher)
  features/           # Feature modules
    export.py         # Export to markdown/text/JSON/HTML
    file_watch.py     # File watcher (inotify/polling)
    git_integration.py # Git operations, diff coloring
    notifications.py  # Desktop/terminal notifications
    reverse_search.py # Ctrl+R history search
  persistence/        # Persistence stores (all follow same pattern)
    _base.py          # BaseStore class
    aliases.py, bookmarks.py, drafts.py, notes.py,
    pinned_sessions.py, pins.py, refs.py, session_names.py,
    snippets.py, templates.py
  widgets/            # Textual widgets
    bars.py           # SuggestionBar, HistorySearchBar, FindBar
    chat_input.py     # ChatInput widget
    commands.py       # Slash command registration/dispatch
    datamodels.py     # Data classes for tabs, messages
    indicators.py     # ProcessingIndicator
    messages.py       # UserMessage, AssistantMessage, MessageMeta
    panels.py         # PinnedPanel, PinnedPanelItem
    screens.py        # ShortcutOverlay, HistorySearchScreen
    tabs.py           # TabState, tab management
tools/                # Testing and capture tools
  interactive_test_runner.py
  tui_capture.py, svg_parser.py, tui_analyze.py
  ux_test.sh
tests/                # Unit tests
  test_commands.py, test_constants.py, test_features.py,
  test_persistence.py, test_utils.py, test_widgets.py
```

### Key Patterns

**Command Mixins**: All slash commands are implemented as mixin classes in `commands/`. The main `AmplifierTuiApp` in `app.py` inherits from all of them. Each mixin defines `_cmd_<name>(self, text: str)` methods. The dispatcher in `app.py:_handle_slash_command()` routes `/name args` to `self._cmd_name(args)`.

**Persistence Stores**: All stores extend `BaseStore` in `persistence/_base.py`. Pattern:
```python
class MyStore(BaseStore):
    def __init__(self, path: Path):
        super().__init__(path)
    # Add domain-specific methods
    # Data is a dict loaded/saved as JSON
```

**Widgets**: Custom Textual widgets in `widgets/`. Messages are `UserMessage(Static)`, `AssistantMessage(Markdown)`, `MessageMeta(Static)`. Screens use `ModalScreen` base class.

**System Messages**: To show feedback to the user within the chat, call `self._add_system_message("text")`. This creates a styled system message in the chat view. All commands use this for output.

**Split View**: The right side of the app supports a split panel for displaying content alongside the chat. Toggle with `self._open_split(content)` and `self._close_split()`.

**Tabs**: Each tab is a `TabState` dataclass that stores the full state of a conversation (messages, session, bookmarks, etc.). Tab switching saves/restores state via `_save_tab_state()` / `_restore_tab_state()`.

---

## Interactive Test System

### Adding New Tests

Tests are 5-tuples in `tools/interactive_test_runner.py`:

```python
(test_id, action_type, action_data, description, extra_checks)
```

**Action types**:
- `"command"` -- types text into chat input and submits (e.g., `"/help"`)
- `"key"` -- presses a key combo (e.g., `"ctrl+b"`, `"f1"`)
- `"sequence"` -- list of `(step_type, step_data)` for multi-step tests

**Test ID convention**: `T{category}.{sequence}{variant}` -- e.g., `T22.1a`

Categories for new features:
```
T21.x  Command palette
T22.x  Session tags
T23.x  Clipboard ring
T24.x  Smart include
T25.x  Agent tree view
T26.x  Context profiler
T27.x  Recipe pipeline
T28.x  Inline diff
T29.x  Conversation branching
T30.x  Model A/B testing
T31.x  Session replay
T32.x  Cross-session search
T33.x  Tool introspection
T34.x  Heatmap dashboard
T35.x  Plugin system
T36.x  Voice input
```

**Standard checks** (applied automatically to every test):
- `check_no_crash` -- app is still alive (`#chat-input` queryable)
- `check_no_error_message` -- no `ErrorMessage` widgets in DOM
- `check_svg_has_content` -- SVG output has >5 text lines

**Writing custom check functions**:
```python
def check_my_thing(app, svg_data):
    """Return (passed: bool, detail: str)."""
    try:
        widget = app.query_one("#my-widget")
        return widget.display, "Widget visible" if widget.display else "Widget hidden"
    except Exception as e:
        return False, f"Not found: {e}"
```

**Adding tests to a batch** (or creating a new batch):
```python
BATCH_5_NEW_FEATURES = [
    ("T21.1a", "command", "/palette", "Open command palette",
     [("modal", check_modal_appeared)]),
    ("T21.1b", "key", "escape", "Dismiss palette", []),
]
BATCHES["5"] = BATCH_5_NEW_FEATURES
```

### Running Tests

```bash
# All tests (4 batches currently, ~93 tests, takes ~20s)
uv run python tools/interactive_test_runner.py --batch all

# Just your new batch
uv run python tools/interactive_test_runner.py --batch 5

# Output goes to .test-results/ with SVG captures per test
```

### UX Visual Verification

For visual changes (themes, layouts, new panels), use the capture pipeline:

```bash
# Quick SVG capture with mock content
./tools/ux_test.sh --mock-chat --svg-only

# Full capture (SVG + PNG + image analysis)
./tools/ux_test.sh --mock-chat

# Output in .ux-tests/ with timestamped files
```

The SVG parser (`tools/svg_parser.py`) extracts pixel-perfect text, colors, and styles from Textual's SVG export. This is your primary tool for verifying visual changes without a real terminal.

---

## Using Sub-Agents Effectively

For complex features, delegate exploration and implementation to sub-agents:

### Exploration Before Building
```
delegate(agent="foundation:explorer", instruction="Survey amplifier_tui/commands/ and map all command mixin patterns")
```

### Implementation with Spec
```
delegate(agent="foundation:modular-builder", instruction="Implement TagStore in amplifier_tui/persistence/tags.py following the pattern in _base.py and snippets.py. [full spec here]")
```

### Architecture Decisions
```
delegate(agent="foundation:zen-architect", instruction="Design the agent tree view widget. Consider: where to hook into events, widget hierarchy, how to handle nested delegation, split pane vs overlay rendering.")
```

### Bug Hunting
```
delegate(agent="foundation:bug-hunter", instruction="Interactive test T22.1a is failing with: [error]. The test expects a system message after /tag add but none appears.")
```

### Pattern: Explore -> Design -> Build -> Test
For each complex feature:
1. **Explore**: Use explorer to understand the relevant code areas
2. **Design**: Use zen-architect if the feature needs architectural decisions
3. **Build**: Implement directly or delegate to modular-builder with a clear spec
4. **Test**: Run both test suites, fix issues

For simpler features (new persistence store, new command), you can often build directly without the explore/design steps since the patterns are well-established.

---

## Codebase Conventions

### Adding a New Slash Command

1. Choose the right command mixin file in `commands/` (or create a new one for a new domain)
2. Add a method: `def _cmd_mycommand(self, text: str) -> None:`
3. Use `self._add_system_message()` for output
4. Add to the help text in `app.py:_cmd_help()` (search for the help string)
5. If it takes subcommands, use `parts = text.split(None, 1)` pattern
6. Add interactive test(s)
7. Add attribute test in `tests/test_commands.py`

### Adding a New Persistence Store

1. Create `amplifier_tui/persistence/mystore.py` extending `BaseStore`
2. Add to `amplifier_tui/persistence/__init__.py` exports
3. Initialize in `app.py` `__init__` (follow the pattern of existing stores)
4. Load data in `on_mount()` or first access
5. Add tests in `tests/test_persistence.py`
6. File path: `~/.amplifier/tui-mystore.json` (follow naming convention)

### Adding a New Widget

1. Create in `amplifier_tui/widgets/` (new file for substantial widgets)
2. Add to `amplifier_tui/widgets/__init__.py` exports
3. For panels: consider reusing the split pane infrastructure
4. For overlays: extend `ModalScreen` (see `ShortcutOverlay` pattern)
5. For inline content: extend `Static` or `Markdown`

### Adding a New Screen/Overlay

1. Add class to `amplifier_tui/widgets/screens.py` extending `ModalScreen`
2. Define `compose()` for layout and `key_*` handlers for interaction
3. Push screen with `self.push_screen(MyScreen())`
4. Return value via `ModalScreen[ReturnType]` and `self.dismiss(value)`

### Styling

- All CSS goes in `amplifier_tui/styles.tcss`
- Follow existing naming: `#widget-id` for unique elements, `.class-name` for reusable styles
- Color variables defined in `theme.py` and referenced as `$primary`, `$secondary`, etc.
- Dark theme is default; test visual changes with SVG capture

---

## Known Pyright Situation

Pyright reports ~993 errors. This is expected:
- **958 `reportAttributeAccessIssue`**: Mixin classes reference `self.query()`, `self.notify()`, etc. that only exist at runtime when composed onto the App class. These are NOT bugs.
- **34 `reportArgumentType`**: Minor type mismatches, low priority.
- **3 ruff F401 (unused imports)**: Auto-fixable with `ruff check --fix`.

Do not spend time trying to fix the mixin-related Pyright errors. They are structural to the mixin pattern and all 356 tests prove the code works.

---

## What Success Looks Like

At the end of a build session, we want:
- New features implemented and working
- All existing tests still passing (no regressions)
- New interactive tests added for each feature
- New unit tests where applicable
- Clean commits with descriptive messages
- The `FEATURE-BACKLOG.md` updated with completed items

The north star: **make the invisible parts of AI work visible.** Agent delegation, context consumption, tool execution, workflow progress -- these are the things only a rich TUI can show, and nobody else is showing them.
