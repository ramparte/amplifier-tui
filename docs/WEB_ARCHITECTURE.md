# Web Frontend Architecture

## Goal

Add a browser-based frontend to amplifier-tui that shares the same backend as the TUI.
Both frontends live in this repo. The TUI remains the primary interface; the web version
is a second rendering surface over the same session engine.

Localhost only. The browser talks to a local Python server on this machine, identical
backend to the TUI, just a different display layer.

## Current State (Why This Is Feasible)

The codebase already has a clean separation -- the recent Bridge refactor made it
almost ready. Key findings from the architectural survey:

| Layer | Files | Textual Imports | Status |
|-------|-------|-----------------|--------|
| SessionManager | 1 file (425 lines) | Zero | Ready to share |
| features/ | 19 modules | Zero | Ready to share |
| persistence/ | 12 stores | Zero | Ready to share |
| Command mixins | 16 of 23 | Zero | Ready to share |
| Command mixins | 7 of 23 | Yes (UI widgets) | Stay in TUI layer |
| Widgets | 13 files | All Textual | Stay in TUI layer |
| app.py | 1 file (6450 lines) | Heavy | TUI-specific |

The coupling is narrow and well-defined:
- **483 calls to `_add_system_message()`** -- commands display results via this method
- **~30 `call_from_thread()` calls** -- streaming events bridge to UI thread
- **1 Textual type leak** -- `TabState.last_assistant_widget: Static`

## Design Principle: The Mixin Pattern IS the Abstraction

The 16 pure command mixins don't know they're in a Textual app. They call
`self._add_system_message()`, `self.session_manager`, `self._amplifier_ready`, etc.
Any class that provides those attributes and methods can mix in the same commands.

This means: **no rewrite of command logic for the web frontend.** The web server
class mixes in the exact same command classes. When a user types `/git` in the
browser, the same `GitCommandsMixin._cmd_git()` runs and calls
`self._add_system_message()` -- which the web server implements as a WebSocket push
instead of a Textual widget mount.

```
                    ┌─────────────────────────┐
                    │   16 Command Mixins      │
                    │   (git, token, agent,    │
                    │    recipe, skills, ...)   │
                    │                          │
                    │   Call: self._add_system  │
                    │         _message(text)    │
                    └─────────┬───────┬────────┘
                              │       │
                    ┌─────────┘       └──────────┐
                    ▼                             ▼
        ┌───────────────────┐         ┌──────────────────┐
        │   TUI App         │         │   Web Server     │
        │                   │         │                  │
        │ _add_system_msg → │         │ _add_system_msg →│
        │  mount(Static())  │         │  ws.send_json()  │
        │                   │         │                  │
        │ Textual widgets   │         │ FastAPI + WS     │
        │ call_from_thread  │         │ JSON events      │
        └───────────────────┘         └──────────────────┘
```

## Package Layout (After Refactor)

```
amplifier_tui/
├── core/                          # Shared backend -- NO Textual imports
│   ├── __init__.py
│   ├── session_manager.py         # Moved from root
│   ├── preferences.py             # Moved from root
│   ├── constants.py               # Moved from root
│   ├── history.py                 # Moved from root
│   ├── transcript_loader.py       # Moved from root
│   ├── platform_info.py           # Moved from root (was platform.py)
│   ├── _utils.py                  # Moved from root
│   ├── log.py                     # Moved from root
│   ├── environment.py             # Moved from root
│   ├── app_base.py                # NEW: SharedAppBase with state + command routing
│   ├── conversation.py            # NEW: ConversationState (from TabState)
│   ├── features/                  # Moved from root (all 19 modules)
│   │   ├── __init__.py
│   │   ├── agent_tracker.py
│   │   ├── tool_log.py
│   │   ├── recipe_tracker.py
│   │   ├── git_integration.py
│   │   ├── branch_manager.py
│   │   ├── ... (14 more)
│   ├── persistence/               # Moved from root (all 12 stores)
│   │   ├── __init__.py
│   │   ├── _base.py
│   │   ├── aliases.py
│   │   ├── ... (11 more)
│   └── commands/                  # Moved: the 16 Textual-free mixins
│       ├── __init__.py
│       ├── git_cmds.py
│       ├── token_cmds.py
│       ├── agent_cmds.py
│       ├── recipe_cmds.py
│       ├── ... (12 more)
│
├── tui/                           # TUI frontend -- Textual-specific
│   ├── __init__.py
│   ├── app.py                     # Main Textual app (inherits SharedAppBase)
│   ├── theme.py
│   ├── datamodels.py              # TabState (UI-specific fields only)
│   ├── chat_input.py
│   ├── styles.tcss
│   ├── widgets/                   # All Textual widgets
│   │   ├── __init__.py
│   │   ├── chat_view.py
│   │   ├── todo_panel.py
│   │   ├── agent_tree_panel.py
│   │   ├── ... (10 more)
│   └── commands/                  # 7 Textual-coupled command mixins
│       ├── __init__.py
│       ├── session_cmds.py
│       ├── split_cmds.py
│       ├── search_cmds.py
│       ├── terminal_cmds.py
│       ├── monitor_cmds.py
│       ├── export_cmds.py
│       └── display_cmds.py
│
├── web/                           # Web frontend -- FastAPI + vanilla JS
│   ├── __init__.py
│   ├── server.py                  # FastAPI app, WebSocket handler
│   ├── web_app.py                 # WebApp class (inherits SharedAppBase)
│   ├── static/
│   │   ├── app.js                 # Client-side: WebSocket, markdown, panels
│   │   └── style.css              # Styling
│   └── templates/
│       └── index.html             # Single-page app shell
│
├── __init__.py
└── __main__.py                    # Entry: --web flag dispatches to web server
```

## SharedAppBase (core/app_base.py)

The key new abstraction. Holds all state and behavior that both frontends need.

```python
class SharedAppBase:
    """Base class providing shared state and command infrastructure.

    Both TUI and Web inherit from this. Command mixins are mixed in
    alongside this class. Subclasses implement the abstract display methods.
    """

    def __init__(self):
        # Session
        self.session_manager = SessionManager()
        self.is_processing: bool = False
        self._amplifier_ready: bool = False
        self._auto_mode: str = "full"
        self._active_mode: str | None = None

        # Conversation state
        self._conversations: dict[str, ConversationState] = {}
        self._active_conversation_id: str | None = None

        # Command routing (populated by subclass or mixin registration)
        self._command_handlers: dict[str, Callable] = {}

        # Features (shared trackers)
        self.agent_tracker = AgentTracker()
        self.tool_log = ToolLog()
        self.recipe_tracker = RecipeTracker()

        # Persistence stores
        self._init_persistence_stores()

    # --- Abstract display methods (subclasses MUST implement) ---

    def _add_system_message(self, text: str) -> None:
        raise NotImplementedError

    def _add_user_message(self, text: str) -> None:
        raise NotImplementedError

    def _add_assistant_message(self, text: str) -> None:
        raise NotImplementedError

    def _show_error(self, text: str) -> None:
        raise NotImplementedError

    def _update_status(self, text: str) -> None:
        raise NotImplementedError

    def _start_processing(self, label: str = "Thinking") -> None:
        raise NotImplementedError

    def _finish_processing(self) -> None:
        raise NotImplementedError

    # --- Abstract streaming methods (subclasses MUST implement) ---

    def _on_stream_block_start(self, block_type: str, index: int) -> None:
        raise NotImplementedError

    def _on_stream_block_delta(self, block_type: str, text: str) -> None:
        raise NotImplementedError

    def _on_stream_block_end(self, block_type: str, text: str) -> None:
        raise NotImplementedError

    def _on_tool_start(self, tool_name: str, tool_input: dict) -> None:
        raise NotImplementedError

    def _on_tool_end(self, name: str, inp: dict, result: str) -> None:
        raise NotImplementedError

    # --- Concrete shared methods ---

    def _route_command(self, text: str) -> bool:
        """Parse and dispatch a slash command. Returns True if handled."""
        ...

    def _wire_streaming_callbacks(self) -> None:
        """Connect SessionManager callbacks to abstract streaming methods."""
        sm = self.session_manager
        sm.on_content_block_start = self._on_stream_block_start
        sm.on_content_block_delta = self._on_stream_block_delta
        sm.on_content_block_end = self._on_stream_block_end
        sm.on_tool_pre = self._on_tool_start
        sm.on_tool_post = self._on_tool_end
        sm.on_usage_update = lambda: self._on_usage_update()
```

## ConversationState (core/conversation.py)

Extracted from `TabState` -- only the backend-relevant fields:

```python
@dataclass
class ConversationState:
    """Backend state for a single conversation (framework-agnostic)."""
    conversation_id: str
    session_id: str | None = None
    title: str = ""
    system_prompt: str = ""
    system_preset_name: str = ""
    active_mode: str | None = None
    messages: list[dict] = field(default_factory=list)  # {role, content, timestamp}

    # Metrics
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_call_count: int = 0
    total_words: int = 0
    response_times: list[float] = field(default_factory=list)
    tool_usage: dict[str, int] = field(default_factory=dict)

    # Annotations
    bookmarks: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    notes: list = field(default_factory=list)
```

`TabState` in `tui/datamodels.py` then becomes just the UI-specific additions:
- `container_id`, `tab_id` (Textual widget IDs)
- `last_assistant_widget: Static | None` (Textual widget reference)
- `conversation: ConversationState` (reference to the shared state)

## Web Frontend Architecture

### Server (web/server.py)

```python
# FastAPI + WebSocket, localhost only
app = FastAPI()

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    web_app = WebApp(ws)  # Inherits SharedAppBase
    await web_app.run(session_id)

@app.get("/")
async def index():
    return FileResponse("templates/index.html")

@app.get("/api/sessions")
async def list_sessions():
    return SessionManager.list_all_sessions()
```

### WebApp (web/web_app.py)

```python
class WebApp(
    SharedAppBase,
    GitCommandsMixin,
    TokenCommandsMixin,
    AgentCommandsMixin,
    # ... all 16 shared command mixins
):
    def __init__(self, websocket: WebSocket):
        super().__init__()
        self._ws = websocket

    def _add_system_message(self, text: str) -> None:
        asyncio.create_task(self._ws.send_json({
            "type": "system_message", "text": text
        }))

    def _on_stream_block_delta(self, block_type: str, text: str) -> None:
        asyncio.create_task(self._ws.send_json({
            "type": "stream_delta", "block_type": block_type, "text": text
        }))

    # ... implement all abstract methods as WebSocket JSON pushes
```

### Client (web/static/app.js)

```javascript
// Single-page app, connects to localhost WebSocket
const ws = new WebSocket(`ws://localhost:8765/ws/${sessionId}`);

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
        case "system_message": appendSystemMessage(msg.text); break;
        case "stream_delta":   appendStreamDelta(msg.text); break;
        case "tool_start":     showToolIndicator(msg); break;
        case "todo_update":    updateTodoPanel(msg); break;
        case "agent_update":   updateAgentTree(msg); break;
        // ...
    }
};

// Commands go through the same input
input.onsubmit = (text) => {
    ws.send(JSON.stringify({ type: "message", text }));
};
```

### WebSocket Event Vocabulary

The web client receives JSON events that mirror the TUI's streaming callbacks:

| Event Type | Fields | TUI Equivalent |
|------------|--------|----------------|
| `stream_start` | `block_type`, `index` | `_on_stream_block_start` |
| `stream_delta` | `block_type`, `text` | `_on_stream_block_delta` |
| `stream_end` | `block_type`, `text` | `_on_stream_block_end` |
| `tool_start` | `tool_name`, `tool_input` | `_on_tool_start` |
| `tool_end` | `tool_name`, `tool_input`, `result` | `_on_tool_end` |
| `system_message` | `text` | `_add_system_message` |
| `user_message` | `text` | `_add_user_message` |
| `assistant_message` | `text` | `_add_assistant_message` |
| `error` | `text` | `_show_error` |
| `status` | `text` | `_update_status` |
| `processing_start` | `label` | `_start_processing` |
| `processing_end` | (empty) | `_finish_processing` |
| `usage_update` | `input_tokens`, `output_tokens`, `context_pct` | `_on_usage_update` |
| `todo_update` | `items: [{content, status}]` | TodoPanel.update_todos |
| `agent_update` | `agent_id`, `name`, `status` | AgentTreePanel methods |

## Entry Points

```toml
# pyproject.toml
[project.scripts]
amplifier-tui = "amplifier_tui.__main__:main"
amplifier-web = "amplifier_tui.web:main"
```

Or unified: `amplifier-tui --web` launches the web server instead of the TUI.

## What the Web Gets "for Free"

Because the 16 command mixins are shared, these work identically in the browser
with zero additional code:

- All `/git*` commands (git, diff, log, blame, gitstatus)
- `/skills`, `/commit`, `/auto`
- `/agents`, `/recipe`, `/branch`, `/compare`
- `/token`, `/cost`, `/model`
- `/pin`, `/bookmark`, `/note`, `/tag`, `/snippet`
- `/replay`, `/dashboard`, `/watch`
- `/alias`, `/template`, `/draft`

The web frontend can then ADD mouse-enabled features on top:
- Click to expand tool results
- Drag to reorder todos
- Hover previews on file paths
- Resizable panel splits
- Copy buttons on code blocks
- Interactive markdown (collapsible sections, tabs)

## What Stays TUI-Only (Initially)

These 7 Textual-coupled command mixins need web-specific implementations later:

| Mixin | Why TUI-Only | Web Alternative |
|-------|-------------|-----------------|
| `session_cmds.py` | Textual Tree widget | Session list component |
| `split_cmds.py` | Textual container manipulation | CSS grid layout |
| `search_cmds.py` | Mounts Static widgets | DOM search/highlight |
| `terminal_cmds.py` | Embedded terminal widget | xterm.js or similar |
| `monitor_cmds.py` | Textual DataTable + Timer | Chart.js dashboard |
| `export_cmds.py` | Reads Textual widget content | Reads from ConversationState |
| `display_cmds.py` | CSS class toggling | Different CSS mechanism |

These represent ~15% of commands. They can be ported incrementally after the
core web experience works.

## Dependencies

```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.100",
    "uvicorn>=0.20",
    "websockets>=12.0",
    "jinja2>=3.1",
]
```

The web dependencies are optional -- TUI-only users don't need them.
