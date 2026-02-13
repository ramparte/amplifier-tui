# Concurrent Multi-Session Architecture Spec

## Context Transfer File

This spec was produced in a planning session analyzing the amplifier-tui architecture and comparing it with payneio/lakehouse (a GUI for Amplifier that uses a daemon model). The goal is to enable concurrent session processing across tabs -- kick off work in tab 1, switch to tab 2, tab 1 keeps running in the background.

**Branch:** `feat/web-native-frontend`
**Date:** 2026-02-11

---

## Problem

The TUI currently blocks tab switching while any session is processing:

```python
# app.py:860-862
if self.is_processing:
    self._add_system_message("Cannot switch tabs while processing.")
    return
```

Root cause: `SessionManager` holds ONE session pointer, `is_processing` is a global boolean on `SharedAppBase`, and streaming callbacks are wired to a single set of slots. There's no infrastructure for parallel execution.

## Design: SessionHandle Registry with Closure-Captured Callbacks

Replace the session swap-in/swap-out pattern with a registry of `SessionHandle` objects. Each handle permanently owns its session, its callbacks, and its token counters. The Bridge's `on_stream` is bound per-handle at creation time -- no event bus, no routing table.

```
Tab 1 creates session  -->  SessionHandle("conv-1")  -->  Bridge binds handle._on_stream
Tab 2 creates session  -->  SessionHandle("conv-2")  -->  Bridge binds handle._on_stream
                                                          (different handle, different closures)
```

Two concurrent `session.execute()` calls on two different handles call two different `_on_stream` methods. Routing is structural -- baked into the object graph at construction time.

---

## Files Changed (6 files, 2 commits)

### Commit 1: Core refactor (no behavior change)

| File | Change | Risk |
|------|--------|------|
| `core/session_manager.py` | `SessionHandle` dataclass + registry API with backward-compat properties | Low |
| `core/conversation.py` | Add 7 per-conversation processing fields, remove `session`/`session_id` | None (additive) |
| `core/app_base.py` | `conversation_id` on all abstract methods; `_wire_streaming_callbacks` targets handles | Medium |
| `web/web_app.py` | Signature updates only, behavior identical | Low |

### Commit 2: TUI concurrency enabled

| File | Change | Risk |
|------|--------|------|
| `widgets/datamodels.py` | Add per-tab streaming widget state to `TabState` | Low |
| `app.py` | Remove blocking guards, per-conversation workers, route streaming to correct container | Medium-high |

---

## Part 1: SessionHandle Dataclass

New dataclass in `core/session_manager.py`, above `SessionManager`:

```python
@dataclass
class SessionHandle:
    """Isolated per-session state, owned by SessionManager, keyed by conversation_id.

    Each handle carries its own session object, streaming callbacks, and token
    counters.  The Bridge's ``on_stream`` is bound to ``self._on_stream`` at
    session creation, so streaming events dispatch to THIS handle's callbacks
    with zero cross-talk between concurrent sessions.
    """

    conversation_id: str = ""

    # --- Amplifier session ---
    session: AmplifierSession | None = None
    session_id: str | None = None
    _bridge_handle: Any = None  # bridge.SessionHandle returned by LocalBridge

    # --- Per-session streaming callbacks ---
    # Set by SharedAppBase._wire_streaming_callbacks() before each message send.
    # These are the SAME callback slots that currently live on SessionManager
    # (lines 38-47), moved here so each session has its own independent set.
    on_content_block_start: Callable[[str, int], None] | None = None
    on_content_block_delta: Callable[[str, str], None] | None = None
    on_content_block_end: Callable[[str, str], None] | None = None
    on_tool_pre: Callable[[str, dict], None] | None = None
    on_tool_post: Callable[[str, dict, str], None] | None = None
    on_execution_start: Callable[[], None] | None = None
    on_execution_end: Callable[[], None] | None = None
    on_usage_update: Callable[[], None] | None = None

    # --- Per-session token usage ---
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_name: str = ""
    context_window: int = 0

    def reset_usage(self) -> None:
        """Reset token usage counters for a new session."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.model_name = ""
        self.context_window = 0

    def _on_stream(self, event: str, data: dict[str, Any]) -> None:
        """Dispatch bridge streaming events to THIS handle's callbacks.

        This is an exact port of SessionManager._on_stream, but reading/writing
        self's callbacks and token counters -- i.e., THIS handle's state, not a
        shared singleton's state.

        Called from the background thread where session.execute() runs.
        Each session's Bridge holds a reference to ITS handle's _on_stream,
        bound at session creation time.
        """
        if event == "content_block:start":
            if self.on_content_block_start:
                self.on_content_block_start(
                    data.get("block_type", "text"),
                    data.get("block_index", 0),
                )
        elif event == "content_block:delta":
            delta = (
                data.get("delta", "")
                or data.get("text", "")
                or data.get("content", "")
            )
            if delta and self.on_content_block_delta:
                self.on_content_block_delta(data.get("block_type", "text"), delta)
        elif event == "content_block:end":
            block = data.get("block", {})
            block_type = block.get("type", "")
            if block_type == "text" and self.on_content_block_end:
                self.on_content_block_end("text", block.get("text", ""))
            elif block_type in ("thinking", "reasoning") and self.on_content_block_end:
                text = block.get("thinking", "") or block.get("text", "")
                self.on_content_block_end("thinking", text)
        elif event == "tool:pre":
            if self.on_tool_pre:
                self.on_tool_pre(
                    data.get("tool_name", "unknown"),
                    data.get("tool_input", {}),
                )
        elif event == "tool:post":
            if self.on_tool_post:
                result = data.get("result", "")
                if isinstance(result, dict):
                    result = json.dumps(result, indent=2)
                self.on_tool_post(
                    data.get("tool_name", "unknown"),
                    data.get("tool_input", {}),
                    str(result)[:2000],
                )
        elif event == "execution:start":
            if self.on_execution_start:
                self.on_execution_start()
        elif event == "execution:end":
            if self.on_execution_end:
                self.on_execution_end()
        elif event == "llm:response":
            usage = data.get("usage", {})
            if usage:
                self.total_input_tokens += usage.get("input", 0)
                self.total_output_tokens += usage.get("output", 0)
            model = data.get("model", "")
            if model and not self.model_name:
                self.model_name = model
            if self.on_usage_update:
                self.on_usage_update()
```

### How the Bridge Binding Works

The critical change is one line in session creation. Currently:

```python
on_stream=self._on_stream,     # self = SessionManager singleton
```

After:

```python
on_stream=handle._on_stream,   # handle = this conversation's SessionHandle
```

The Bridge stores this function reference internally and calls it from the background thread where `session.execute()` runs. It's a permanent binding -- set once at `create_session` time, never rewired.

### Closure Chain for Streaming Events

`SessionHandle._on_stream` dispatches by event type to its own callback slots. Those slots are set by `SharedAppBase._wire_streaming_callbacks()`, which creates closures that capture both a `conversation_id` and a `ConversationState` reference:

```
Bridge (background thread)
  -> handle_for_conv42._on_stream("content_block:delta", data)
    -> handle_for_conv42.on_content_block_delta("text", "Hello wor")
      -> closure installed by _wire_streaming_callbacks("conv-42", conv_state):
          def on_block_delta(block_type, delta):
              conv.stream_accumulated_text = ...  # writes to conv-42's state
              self._on_stream_block_delta("conv-42", block_type, snapshot)
                                          ^^^^^^^^^ captured in closure scope
```

---

## Part 2: SessionManager Registry API

### What Gets Removed from SessionManager

These instance attributes move to `SessionHandle` and are deleted from `__init__`:

```python
# DELETE from __init__:
self.session                    # -> SessionHandle.session
self.session_id                 # -> SessionHandle.session_id
self.on_content_block_start     # -> SessionHandle
self.on_content_block_delta     # -> SessionHandle
self.on_content_block_end       # -> SessionHandle
self.on_tool_pre                # -> SessionHandle
self.on_tool_post               # -> SessionHandle
self.on_execution_start         # -> SessionHandle
self.on_execution_end           # -> SessionHandle
self.on_usage_update            # -> SessionHandle
self.total_input_tokens         # -> SessionHandle
self.total_output_tokens        # -> SessionHandle
self.model_name                 # -> SessionHandle
self.context_window             # -> SessionHandle
```

Delete entirely: `def _on_stream(self, event, data)` (moved to SessionHandle._on_stream)

### New `__init__`

```python
def __init__(self) -> None:
    self._bridge: Any | None = None
    self._handles: dict[str, SessionHandle] = {}
    self._default_conversation_id: str | None = None
```

### New Registry Methods

```python
def get_handle(self, conversation_id: str) -> SessionHandle | None:
    """Look up a session handle by conversation_id."""
    return self._handles.get(conversation_id)

@property
def active_handles(self) -> dict[str, SessionHandle]:
    """Read-only snapshot of all registered handles."""
    return dict(self._handles)

def remove_handle(self, conversation_id: str) -> None:
    """Remove a handle without ending the session."""
    self._handles.pop(conversation_id, None)
    if self._default_conversation_id == conversation_id:
        self._default_conversation_id = None
```

### Refactored Lifecycle Methods

**`start_new_session`** -- now returns SessionHandle:

```python
async def start_new_session(
    self,
    conversation_id: str | None = None,
    cwd: Path | None = None,
    model_override: str = "",
) -> SessionHandle:
    """Start a new Amplifier session, returning its SessionHandle.

    If conversation_id is None, an ID is auto-generated and this handle
    becomes the default (backward compat).
    """
    from amplifier_distro.bridge import BridgeConfig
    import uuid

    auto_generated = conversation_id is None
    if auto_generated:
        conversation_id = str(uuid.uuid4())

    if cwd is None:
        cwd = Path.cwd()

    handle = SessionHandle(conversation_id=conversation_id)

    bridge = self._get_bridge()
    config = BridgeConfig(
        working_dir=cwd,
        run_preflight=False,
        on_stream=handle._on_stream,  # <-- THE KEY CHANGE: per-handle binding
    )

    bridge_handle = await bridge.create_session(config)
    handle._bridge_handle = bridge_handle
    handle.session = bridge_handle._session
    handle.session_id = bridge_handle.session_id

    if model_override:
        self._switch_model_on_handle(handle, model_override)

    handle.reset_usage()
    self._extract_model_info_on_handle(handle)

    self._handles[conversation_id] = handle

    if auto_generated:
        self._default_conversation_id = conversation_id

    return handle
```

**`resume_session`** -- same pattern, returns SessionHandle:

```python
async def resume_session(
    self,
    session_id: str,
    conversation_id: str | None = None,
    model_override: str = "",
    working_dir: Path | None = None,
) -> SessionHandle:
    # Same pattern as start_new_session but calls bridge.resume_session(session_id, config)
```

**`send_message`** -- dispatches to specific handle:

```python
async def send_message(
    self,
    message: str,
    conversation_id: str | None = None,
) -> str:
    cid = conversation_id or self._default_conversation_id
    if cid is None:
        raise ValueError("No conversation_id and no default session")
    handle = self._handles.get(cid)
    if handle is None or handle.session is None:
        raise ValueError(f"No active session for conversation {cid!r}")
    response = await handle.session.execute(message)
    return response
```

**`end_session`** -- ends specific handle, removes from registry:

```python
async def end_session(self, conversation_id: str | None = None) -> None:
    cid = conversation_id or self._default_conversation_id
    if cid is None:
        return
    handle = self._handles.get(cid)
    if handle is None:
        return
    # ... same cleanup logic as current, but on handle.session / handle._bridge_handle ...
    handle.session = None
    handle._bridge_handle = None
    self._handles.pop(cid, None)
    if self._default_conversation_id == cid:
        self._default_conversation_id = None
```

### Refactored Model Methods

`_extract_model_info` and `switch_model` become static methods operating on a handle:

```python
@staticmethod
def _extract_model_info_on_handle(handle: SessionHandle) -> None:
    # Same logic as current _extract_model_info, but reads handle.session,
    # writes handle.model_name / handle.context_window

@staticmethod
def _switch_model_on_handle(handle: SessionHandle, model_name: str) -> bool:
    # Same logic as current switch_model, but operates on handle.session / handle.model_name
```

### Backward-Compat Properties

These let existing callers (`self.session_manager.session`, `self.session_manager.model_name`, etc.) work unchanged. They delegate to whichever handle `_default_conversation_id` points to. The TUI updates `_default_conversation_id` in `_load_tab_state` on tab switch.

```python
def _default_handle(self) -> SessionHandle | None:
    if self._default_conversation_id is None:
        return None
    return self._handles.get(self._default_conversation_id)

@property
def session(self) -> AmplifierSession | None:
    h = self._default_handle()
    return h.session if h else None

@session.setter
def session(self, value: AmplifierSession | None) -> None:
    h = self._default_handle()
    if h:
        h.session = value

@property
def session_id(self) -> str | None:
    h = self._default_handle()
    return h.session_id if h else None

# ... same pattern for total_input_tokens, total_output_tokens, model_name,
# context_window (all with getter + setter), plus:

def reset_usage(self) -> None:
    h = self._default_handle()
    if h: h.reset_usage()

def switch_model(self, model_name: str) -> bool:
    h = self._default_handle()
    if h: return self._switch_model_on_handle(h, model_name)
    return False

def get_provider_models(self) -> list[tuple[str, str]]:
    # Delegates to default handle's session
```

### What Stays Unchanged

- `list_all_sessions(limit)` -- reads filesystem, no instance state
- `_find_most_recent_session()` -- calls list_all_sessions
- `get_session_transcript_path(session_id)` -- reads filesystem
- `_get_bridge()` -- still lazily creates one LocalBridge singleton shared across all sessions

---

## Part 3: SharedAppBase Changes

### What Gets Removed from `__init__`

```python
# DELETE these 6 attributes (move to ConversationState):
self.is_processing: bool = False
self._queued_message: str | None = None
self._got_stream_content: bool = False
self._stream_accumulated_text: str = ""
self._streaming_cancelled: bool = False
self._tool_count_this_turn: int = 0
```

### New Abstract Method

```python
def _all_conversations(self) -> list[ConversationState]:
    """Return all active ConversationState objects.
    TUI returns: [tab.conversation for tab in self._tabs]
    Web returns: [self._conversation]
    """
    raise NotImplementedError

@property
def is_any_processing(self) -> bool:
    """True if ANY conversation is currently processing."""
    return any(c.is_processing for c in self._all_conversations())
```

### Abstract Display Methods -- New Signatures

**Design principle:** Display methods get `*, conversation_id: str = ""` as keyword-only so the 16 command mixins need ZERO changes. Streaming methods get `conversation_id` as positional first param (only called from closures).

```python
# Display methods (keyword-only, default="" means "active conversation"):
def _add_system_message(self, text: str, *, conversation_id: str = "", **kwargs) -> None: ...
def _add_user_message(self, text: str, *, conversation_id: str = "", **kwargs) -> None: ...
def _add_assistant_message(self, text: str, *, conversation_id: str = "", **kwargs) -> None: ...
def _show_error(self, text: str, *, conversation_id: str = "") -> None: ...
def _update_status(self, text: str, *, conversation_id: str = "") -> None: ...
def _start_processing(self, label: str = "Thinking", *, conversation_id: str = "") -> None: ...
def _finish_processing(self, *, conversation_id: str = "") -> None: ...

# Streaming methods (positional first param, called from background thread):
def _on_stream_block_start(self, conversation_id: str, block_type: str) -> None: ...
def _on_stream_block_delta(self, conversation_id: str, block_type: str, accumulated_text: str) -> None: ...
def _on_stream_block_end(self, conversation_id: str, block_type: str, final_text: str, had_block_start: bool) -> None: ...
def _on_stream_tool_start(self, conversation_id: str, name: str, tool_input: dict) -> None: ...
def _on_stream_tool_end(self, conversation_id: str, name: str, tool_input: dict, result: str) -> None: ...
def _on_stream_usage_update(self, conversation_id: str) -> None: ...
```

### `_wire_streaming_callbacks` Rewrite

New signature:

```python
def _wire_streaming_callbacks(
    self,
    conversation_id: str,
    conversation: ConversationState,
) -> None:
```

Key changes inside:
- Closures read/write `conv.streaming_cancelled`, `conv.stream_accumulated_text`, `conv.got_stream_content`, `conv.tool_count_this_turn` instead of `self._streaming_cancelled` etc.
- All abstract method calls pass `conversation_id` as first arg (streaming) or keyword (display)
- Wires closures to `handle.on_content_block_start` etc. (the SessionHandle) instead of `self.session_manager.on_content_block_start`
- Gets the handle via `self.session_manager.get_handle(conversation_id)`

---

## Part 4: ConversationState Changes

### Remove

```python
session: Any = None       # DELETE -- sessions live on SessionHandle, looked up by conversation_id
session_id: str | None = None  # DELETE -- same
```

### Add (after conversation_id, before title)

```python
# --- Processing state (moved from SharedAppBase where they were global) ---
is_processing: bool = False
streaming_cancelled: bool = False
stream_accumulated_text: str = ""
tool_count_this_turn: int = 0
got_stream_content: bool = False
queued_message: str | None = None
processing_start_time: float | None = None
```

### Implementation Note

Steps 2 and 5 have a dependency: removing `conv.session` / `conv.session_id` breaks `_save_current_tab_state` / `_load_tab_state` in app.py which currently swap sessions through those fields. Options:

- **Recommended:** Keep `session` and `session_id` as deprecated fields in Commit 1 (with `# DEPRECATED` comment). Remove them in Commit 2 when the TUI stops using them.
- Alternative: Do Commit 1 and 2 atomically.

---

## Part 5: Web Frontend Changes (web/web_app.py)

Signature updates only -- behavior identical:

1. Add `self._conversation = ConversationState()` in `__init__`
2. Implement `_all_conversations()` returning `[self._conversation]`
3. Add `*, conversation_id: str = ""` to all display method signatures
4. Add `conversation_id: str` as first positional param to all `_on_stream_*` method signatures
5. Update `_start_processing` / `_finish_processing` to use `self._conversation.is_processing`
6. Update `handle_message` to pass `conversation_id` to new APIs
7. Update session creation/shutdown to use handle API

---

## Part 6: TUI Frontend Changes (app.py + widgets/datamodels.py)

### datamodels.py

Add per-tab streaming widget state to `TabState`:

```python
stream_widget: Any = None          # reference to the active streaming RichLog widget
stream_container: Any = None       # reference to the streaming container
stream_block_type: str = ""        # current block type being streamed
processing_label: str = ""         # "Thinking", "Thinking [#3]", etc.
status_activity_label: str = ""    # status bar activity text
```

### app.py Changes (in order)

1. **`__init__`**: Delete 8 global state attributes (processing, streaming, queue)
2. **Add property**: `is_processing` -> reads active tab's `conv.is_processing`; setter writes it
3. **Add methods**: `_all_conversations()`, `_tab_for_conversation(id)`, `_chat_view_for_conversation(id)`
4. **`_save_current_tab_state`**: Delete session swap-out lines (sessions live on handles now)
5. **`_load_tab_state`**: Delete session swap-in lines, add `session_manager._default_conversation_id` update
6. **`_switch_to_tab`**: DELETE the processing guard. Add re-display-on-switch logic
7. **`_create_new_tab`**: DELETE the processing guard. Delete session null-out
8. **`_close_tab`**: Change guard to per-tab (`if tab.conversation.is_processing: return`)
9. **`_submit_message`**: Per-conversation queuing and worker launch
10. **`_start_processing`**: Per-conversation with conversation_id param
11. **`_finish_processing`**: Per-conversation with conversation_id param
12. **`action_cancel_streaming`**: Per-conversation, per-worker-group cancel
13. **`_send_message_worker`**: New `_start_send_message` launcher + refactored worker with conversation_id
14. **`_send_queued_message`** -> `_send_queued_message_for_conv` with conversation_id
15. **All 6 `_on_stream_*` overrides**: Add conversation_id param, route to correct tab container
16. **`_begin_streaming_block`, `_update_streaming_content`, `_finalize_streaming_block`**: Use per-tab widget state via `_tab_for_conversation`
17. **`_animate_spinner`**: Read from active tab's state

---

## Migration Order

Each step is testable. No step breaks the build if earlier steps are done.

### Step 1: `core/session_manager.py` -- SessionHandle + Registry
- Add SessionHandle dataclass
- Move `_on_stream` logic into SessionHandle._on_stream
- Add `_handles` dict, registry methods
- Refactor lifecycle methods with `conversation_id` parameter
- Add backward-compat properties
- **Verify:** App works identically in single-tab mode. Web frontend needs no changes yet.

### Step 2: `core/conversation.py` -- Add Processing State Fields
- Add 7 processing state fields with defaults
- Keep `session` / `session_id` as DEPRECATED (removed in Step 5)
- **Verify:** App still starts. ConversationState() creates with correct defaults.

### Step 3: `core/app_base.py` -- Interface Changes
- Remove 6 global processing state attrs from `__init__`
- Add `_all_conversations()` abstract method and `is_any_processing` property
- Add `conversation_id` to all abstract methods
- Refactor `_wire_streaming_callbacks` to take `conversation_id` + `ConversationState`, wire to SessionHandle
- **NOTE:** This is a breaking change. Steps 3 + 4 + 5 should be one atomic commit.

### Step 4: `web/web_app.py` -- Signature Updates
- Add `self._conversation = ConversationState()`
- Implement `_all_conversations()`
- Add conversation_id to all method signatures
- **Verify:** Web frontend works identically for single-session use.

### Step 5: `app.py` + `widgets/datamodels.py` -- TUI Concurrency
- Add per-tab widget state to TabState
- Delete global state, add per-conversation routing
- Remove blocking guards
- Per-conversation workers and cancellation
- **Verify:** Full concurrency test (see Success Criteria).

### Commit Strategy (Recommended: 2 commits)

1. **Commit 1** (Steps 1-4): `refactor(core): session registry with per-handle callbacks`
   - Core + web. Everything works in single-session mode. No behavior change.
2. **Commit 2** (Step 5): `feat(tui): concurrent multi-tab session processing`
   - TUI concurrency enabled. Behavior change.

---

## Success Criteria

### SC-1: Concurrent Processing
Start a long message in Tab 1. While it's streaming, switch to Tab 2 and send "Hello".
**Expected:** Tab 2 responds independently. Tab 1 continues in background. Switching back shows Tab 1's streaming content.

### SC-2: Tab Switching While Processing
Send a message in Tab 1. While streaming, press tab switch keybind repeatedly.
**Expected:** Tab switching works instantly. No "Cannot switch tabs" message.

### SC-3: Per-Tab Cancellation
Send messages in Tab 1 and Tab 2 simultaneously. Press Escape while Tab 1 is active.
**Expected:** Tab 1's streaming stops. Tab 2 continues unaffected.

### SC-4: Per-Tab Message Queue
While Tab 1 is processing, type another message and press Enter.
**Expected:** "Queued" message in Tab 1. Switch to Tab 2, send a message -- it sends immediately. Switch back to Tab 1 -- queued message auto-sends when first response finishes.

### SC-5: Tab Creation While Processing
While Tab 1 is processing, create a new tab.
**Expected:** New tab created immediately. Tab 1 continues in background.

### SC-6: Tab Close Protection
While Tab 1 is processing, try to close it.
**Expected:** Blocked with "Cannot close tab while it is processing." Closing idle Tab 2 succeeds.

### SC-7: Web Frontend Unbroken
Start the web frontend, send messages, verify streaming works.
**Expected:** Identical behavior to before.

### SC-8: Single-Tab Regression
Normal single-tab usage -- start session, send messages, stream, cancel, resume, switch model, slash commands.
**Expected:** Everything works identically.

### SC-9: Session Lifecycle Isolation
Create 3 tabs, send messages in all 3, close Tab 2.
**Expected:** Tab 2's session cleaned up. Tabs 1 and 3 continue. `session_manager.active_handles` shows 2 handles.

### SC-10: Stats Isolation
Send a long response in Tab 1. Check token count. Switch to Tab 2.
**Expected:** Tab 2 shows 0 tokens. Tab 1 shows accumulated tokens. Display updates correctly on switch.

---

## What Does NOT Change

Explicit non-changes to avoid scope creep:

1. **16 command mixins** (`core/commands/`): Zero changes. They call `self._add_system_message("text")` without conversation_id. Default `""` means "active conversation."
2. **Session discovery** (`list_all_sessions`, `get_session_transcript_path`): Static/class methods, no instance state.
3. **Bridge singleton**: One LocalBridge shared across all sessions. Bridge already supports concurrent sessions.
4. **Feature singletons** (`AgentTracker`, `ToolLog`, `RecipeTracker`, `TodoPanel`): Remain app-level singletons. Per-conversation tracking is a future enhancement.
5. **Preferences/themes/keybindings**: Global, not per-conversation.
6. **`/resume` command**: Still works -- passes active tab's conversation_id.
7. **Model switching**: Backward-compat `switch_model()` delegates to default handle.
