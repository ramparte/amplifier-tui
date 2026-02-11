# Web Frontend: Implementation Stages

Instructions for staged implementation of the web frontend refactoring.
Each stage ends with a full TUI regression -- the TUI must work identically
after every stage. Do not proceed to the next stage until the current one
is green.

## Pre-Read (Required Context)

Before starting any stage, read these files to understand the current architecture:

- `docs/WEB_ARCHITECTURE.md` -- the design document and target state
- `amplifier_tui/session_manager.py` -- the Bridge-based session engine
- `amplifier_tui/app.py` -- the main Textual app (6450 lines, the big file)
- `amplifier_tui/commands/` -- 23 command mixin files
- `amplifier_tui/features/` -- 19 feature modules
- `amplifier_tui/widgets/` -- 13 widget files
- `amplifier_tui/persistence/` -- 12 persistence stores

Key architectural insight: 16 of 23 command mixins have ZERO Textual imports.
They only couple to the UI via `self._add_system_message()`. The mixin pattern
is already the abstraction layer -- no new framework needed.

---

## Stage 1: Create core/ and Move Framework-Agnostic Files

**Goal:** Move all Textual-free code into `amplifier_tui/core/`. The TUI continues
to work identically via re-export shims in the old locations.

**Why this is safe:** We add re-export shims (`from amplifier_tui.core.X import *`)
in the original module locations. Every existing import continues to resolve.
We can then incrementally update imports and remove shims.

### Step 1.1: Create directory structure

```
amplifier_tui/core/
amplifier_tui/core/__init__.py
amplifier_tui/core/features/
amplifier_tui/core/features/__init__.py
amplifier_tui/core/persistence/
amplifier_tui/core/persistence/__init__.py
amplifier_tui/core/commands/
amplifier_tui/core/commands/__init__.py
```

### Step 1.2: Move session_manager.py and utility modules

Move these files from `amplifier_tui/` to `amplifier_tui/core/`:

| Source | Destination |
|--------|-------------|
| `session_manager.py` | `core/session_manager.py` |
| `preferences.py` | `core/preferences.py` |
| `constants.py` | `core/constants.py` |
| `history.py` | `core/history.py` |
| `transcript_loader.py` | `core/transcript_loader.py` |
| `platform.py` | `core/platform_info.py` (rename to avoid stdlib shadow) |
| `_utils.py` | `core/_utils.py` |
| `log.py` | `core/log.py` |
| `environment.py` | `core/environment.py` |

For EACH moved file:
1. `git mv` the file to its new location
2. Create a shim at the old location: `from amplifier_tui.core.<module> import *`
3. Update internal imports within the moved file (e.g., `.log` becomes
   `amplifier_tui.core.log` or use relative imports within core/)
4. Verify no circular imports

**Special case: `platform.py` -> `core/platform_info.py`**
This rename avoids shadowing Python's stdlib `platform` module. Update all
internal references from `.platform` to `.core.platform_info`.

### Step 1.3: Move features/ directory

```bash
git mv amplifier_tui/features amplifier_tui/core/features
```

Create shim at `amplifier_tui/features/__init__.py`:
```python
from amplifier_tui.core.features import *  # noqa: F401,F403
```

Update internal imports within features/ modules. These modules import from
each other and from `..log`, `..platform`, etc. Update to `amplifier_tui.core.*`.

### Step 1.4: Move persistence/ directory

```bash
git mv amplifier_tui/persistence amplifier_tui/core/persistence
```

Create shim at `amplifier_tui/persistence/__init__.py` with re-exports.

### Step 1.5: Move the 16 Textual-free command mixins

These 16 files have ZERO Textual imports (verified by architectural survey):

```
git_cmds.py, token_cmds.py, content_cmds.py, file_cmds.py,
persistence_cmds.py, theme_cmds.py, watch_cmds.py, agent_cmds.py,
tool_cmds.py, recipe_cmds.py, branch_cmds.py, compare_cmds.py,
replay_cmds.py, plugin_cmds.py, dashboard_cmds.py, shell_cmds.py
```

Move each to `amplifier_tui/core/commands/`. Leave the 7 Textual-coupled
mixins in `amplifier_tui/commands/`:

```
session_cmds.py, split_cmds.py, export_cmds.py, display_cmds.py,
search_cmds.py, terminal_cmds.py, monitor_cmds.py
```

Update `amplifier_tui/commands/__init__.py` to re-export from core:
```python
# Re-export shared commands so existing app.py imports don't break
from amplifier_tui.core.commands.git_cmds import *  # noqa: F401,F403
from amplifier_tui.core.commands.token_cmds import *  # noqa: F401,F403
# ... etc for all 16
```

### Step 1.6: Update pyproject.toml

Add the new packages:
```toml
[tool.setuptools]
packages = [
    "amplifier_tui",
    "amplifier_tui.core",
    "amplifier_tui.core.commands",
    "amplifier_tui.core.features",
    "amplifier_tui.core.persistence",
    "amplifier_tui.commands",
    "amplifier_tui.widgets",
]
```

### Step 1.7: Regression

```bash
# Import smoke test - verify all modules load
python -c "from amplifier_tui.app import AmplifierTuiApp; print('OK')"

# Verify core imports work
python -c "from amplifier_tui.core.session_manager import SessionManager; print('OK')"
python -c "from amplifier_tui.core.preferences import Preferences; print('OK')"

# Run existing tests
pytest tests/ -x -v

# Manual TUI test
amplifier-tui --version
# Launch and verify: new session, /git, /token, /skills, send a message
```

**Commit after this step. Tag: `refactor/stage-1-core-extraction`**

---

## Stage 2: Create SharedAppBase and ConversationState

**Goal:** Extract the shared state and abstract display interface into
`core/app_base.py` and `core/conversation.py`. The TUI app inherits from
SharedAppBase. Behavior identical.

### Step 2.1: Create core/conversation.py

Extract backend-relevant fields from `datamodels.py:TabState` into a new
`ConversationState` dataclass. See `WEB_ARCHITECTURE.md` for the field list.

Update `TabState` to hold a `conversation: ConversationState` reference
instead of duplicating those fields. Update all reads of `tab.session_title`
to `tab.conversation.title`, etc.

This is a large mechanical change across app.py. Take care with each field.

### Step 2.2: Create core/app_base.py

Define `SharedAppBase` class with:
- SessionManager instance
- State flags (is_processing, _amplifier_ready, _auto_mode, etc.)
- Feature trackers (agent_tracker, tool_log, recipe_tracker)
- Persistence store initialization
- Abstract display methods (_add_system_message, etc.) as `raise NotImplementedError`
- Abstract streaming methods
- Concrete `_wire_streaming_callbacks()` that connects SessionManager callbacks
  to the abstract streaming methods
- Command routing infrastructure

### Step 2.3: Make TUI app inherit SharedAppBase

Update `app.py`:
```python
class AmplifierTuiApp(
    SharedAppBase,     # NEW: shared state and abstractions
    # ... existing command mixins ...
    textual.App,
):
```

Move state initialization from app `__init__` to `SharedAppBase.__init__`.
The TUI app's `__init__` calls `super().__init__()` and then does
Textual-specific setup.

The existing `_add_system_message()` etc. methods in app.py become the
concrete implementations of the abstract methods from SharedAppBase.

### Step 2.4: Regression

Same as Stage 1. The TUI must behave identically.

**Commit after this step. Tag: `refactor/stage-2-shared-base`**

---

## Stage 3: Abstract Streaming Callbacks

**Goal:** Replace the `call_from_thread` streaming wiring with the abstract
streaming methods from SharedAppBase. The TUI implements them using
`call_from_thread`; the web will implement them differently.

### Step 3.1: Refactor _setup_streaming_callbacks

Currently in app.py around line 5651, this method creates closures that call
`self.call_from_thread()`. Refactor to:

1. Move the framework-agnostic parts (text accumulation, tool counting,
   agent tracking, recipe tracking) into SharedAppBase._wire_streaming_callbacks()
2. Have _wire_streaming_callbacks() call the abstract methods
3. TUI overrides the abstract methods to do the `call_from_thread()` + widget updates

The key insight: the streaming callbacks currently do TWO things:
- Update shared state (token counts, agent tracker, accumulated text)
- Update UI widgets (via call_from_thread)

Split those two concerns. SharedAppBase handles state. Subclass handles display.

### Step 3.2: Regression

Streaming is the most critical path. Test thoroughly:
- Start new session, send a message, verify streaming works
- Verify tool calls display correctly
- Verify agent delegation shows in agent tree panel
- Verify todo panel updates
- Verify token counts in status bar

**Commit after this step. Tag: `refactor/stage-3-streaming-abstraction`**

---

## Stage 4: Clean Up Re-Export Shims

**Goal:** Update all imports throughout the codebase to use `amplifier_tui.core.*`
directly. Remove the compatibility shims.

### Step 4.1: Update imports in app.py

The big file. Replace:
```python
from amplifier_tui.session_manager import SessionManager
```
With:
```python
from amplifier_tui.core.session_manager import SessionManager
```

Do this for ALL imports from moved modules.

### Step 4.2: Update imports in commands/ and widgets/

Same treatment for the 7 Textual-coupled command mixins and all widget files.

### Step 4.3: Remove shim files

Delete the re-export shim files:
- `amplifier_tui/session_manager.py` (was shim)
- `amplifier_tui/preferences.py` (was shim)
- etc.

### Step 4.4: Verify no stale imports

```bash
# Grep for old import paths
grep -r "from amplifier_tui\.session_manager" amplifier_tui/ --include="*.py"
grep -r "from amplifier_tui\.preferences" amplifier_tui/ --include="*.py"
grep -r "from amplifier_tui\.constants" amplifier_tui/ --include="*.py"
# etc. -- should find nothing (or only __init__.py public API)
```

### Step 4.5: Regression

Full regression. This is the last refactoring stage before web work begins.

**Commit after this step. Tag: `refactor/stage-4-clean-imports`**

---

## Stage 5: Web Server (MVP)

**Goal:** Minimal web frontend -- chat + streaming + slash commands.
Not feature-complete, but functional.

### Step 5.1: Add web dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
web = [
    "fastapi>=0.100",
    "uvicorn>=0.20",
    "websockets>=12.0",
    "jinja2>=3.1",
]
```

### Step 5.2: Create web/server.py

FastAPI app with:
- `GET /` -- serves index.html
- `GET /api/sessions` -- lists sessions (calls SessionManager.list_all_sessions)
- `WS /ws` -- bidirectional WebSocket for chat

### Step 5.3: Create web/web_app.py

`WebApp(SharedAppBase, GitCommandsMixin, TokenCommandsMixin, ...)` class.
Implements all abstract display methods as `ws.send_json()` calls.

Implements the message loop:
```python
async def run(self, ws: WebSocket):
    self._ws = ws
    while True:
        data = await ws.receive_json()
        if data["type"] == "message":
            text = data["text"]
            if text.startswith("/"):
                self._route_command(text)
            else:
                await self._send_message(text)
```

### Step 5.4: Create web/templates/index.html

Single-page app shell:
- Header: session info, model, context gauge
- Main area: scrolling chat messages (markdown rendered)
- Right panels: todo panel, agent tree (hidden until needed)
- Bottom: input textarea with slash command support
- Left sidebar: session list (collapsible)

Keep it simple -- vanilla JS + a lightweight markdown library (marked.js).
No React, no build step. Just `<script src="app.js">`.

### Step 5.5: Create web/static/app.js

WebSocket client that:
- Connects to `ws://localhost:{port}/ws`
- Handles all event types from the vocabulary table in WEB_ARCHITECTURE.md
- Renders chat messages with markdown support
- Handles slash commands (sends as regular messages, server routes them)
- Updates todo panel and agent tree panel from events

### Step 5.6: Create web/static/style.css

Layout matching the TUI's information architecture:
- Dark theme (matching TUI default)
- Monospace font for code, proportional for chat
- Panel layout similar to TUI but taking advantage of browser capabilities

### Step 5.7: Add entry point

Update `__main__.py`:
```python
parser.add_argument("--web", action="store_true", help="Launch web interface")
parser.add_argument("--port", type=int, default=8765, help="Web server port")

if args.web:
    from amplifier_tui.web import main as web_main
    web_main(port=args.port, resume_session_id=resume_session_id)
else:
    from amplifier_tui.tui.app import run_app
    run_app(...)
```

Also add `amplifier-web` script entry point in pyproject.toml.

### Step 5.8: Test

```bash
# Install with web extras
pip install -e ".[web]"

# Launch
amplifier-tui --web

# Or
amplifier-web

# Open browser to http://localhost:8765
# Test: new session, send message, verify streaming
# Test: /git, /skills, /token commands
# Test: agent delegation shows in agent tree
# Test: todo tool shows in todo panel
```

**Commit after this step. Tag: `feat/stage-5-web-mvp`**

---

## Stage 6: Web Enhancements (Post-MVP)

These are incremental improvements after the MVP works:

### 6.1: Session Management
- Session list in sidebar
- Resume session by clicking
- New session button
- Session title editing

### 6.2: Mouse-Enabled Features
- Click to expand/collapse tool results
- Copy button on code blocks
- Hover preview on file paths
- Resizable panel splits (CSS resize or drag handles)

### 6.3: Command Palette
- Cmd+K / Ctrl+K opens searchable command list
- Autocomplete as you type /commands
- Recently used commands

### 6.4: Port TUI-Only Commands
- Session sidebar (web equivalent of session_cmds tree)
- Search/highlight (web equivalent of search_cmds)
- Export (download conversation as markdown/JSON)
- Monitor dashboard (Chart.js equivalent of monitor_cmds DataTable)

### 6.5: Progressive Enhancement
- Code syntax highlighting (highlight.js or Prism)
- Interactive diffs (side-by-side viewer)
- File tree for referenced files
- Image display in chat (screenshots, diagrams)

---

## Regression Checklist (Use After Every Stage)

```
[ ] amplifier-tui --version prints correctly
[ ] Launch TUI, verify UI renders
[ ] Start new session (or verify "no Amplifier" graceful degradation)
[ ] Send a message, verify streaming response
[ ] Run /git -- verify output
[ ] Run /token -- verify output
[ ] Run /skills -- verify output
[ ] Run /todo -- verify panel toggles
[ ] Run /agents tree -- verify panel toggles
[ ] Verify context gauge in status bar
[ ] Type during processing (mid-turn steering)
[ ] pytest tests/ -x passes
[ ] python -c "from amplifier_tui.core import session_manager" works
```

---

## Risk Mitigation

### The Big Risk: Import Breakage in Stage 1

Stage 1 moves ~40 files. The shim approach (re-exports at old locations)
means existing code never breaks, but internal imports within moved files
need updating.

**Mitigation:** Move one category at a time (utilities first, then features,
then persistence, then commands). Run the import smoke test after each batch.
Commit after each successful batch so you can roll back granularly.

### The Medium Risk: SharedAppBase in Stage 2

Extracting state from the 6450-line app.py into a base class touches many
attribute references. Miss one and the TUI breaks.

**Mitigation:** Start with just SessionManager and is_processing. Get that
working. Then move state fields one batch at a time. Each batch: move fields,
update references, run regression.

### The Low Risk: Streaming in Stage 3

The streaming callbacks are well-understood (complete event vocabulary
documented). The refactoring is mechanical: split state updates from UI updates.

**Mitigation:** Implement one callback at a time. Start with content_block_delta
(the most common). Verify streaming still works. Then do the rest.

---

## Notes on Shared Feature Development

After refactoring, new features should follow this pattern:

1. **Command logic goes in `core/commands/`** -- framework-agnostic mixin
2. **TUI rendering goes in `tui/`** -- Textual-specific display code
3. **Web rendering goes in `web/`** -- HTML/JS display code

For most slash commands, only step 1 is needed. The existing
`_add_system_message()` abstraction means both frontends display the output
automatically.

Only features that need custom UI (new panels, interactive widgets, etc.)
require steps 2 and 3.

This means: **adding a new slash command to the TUI automatically makes it
available in the web frontend with zero additional code.** This was the
key design goal.
