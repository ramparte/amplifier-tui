# Cockpit Remediation Plan

Comprehensive fix plan for all issues identified in the Session Cockpit code review.
Organized into 5 phases by dependency ordering.

---

## Phase 1: Data Model and Foundation Fixes

These fixes are prerequisites for Phase 2. They repair the data layer so the
integration plumbing has correct structures to work with.

### Task 1.1: Add `content` field to BlockInfo and store full text

**Files:** `amplifier_tui/models/block_model.py`, `amplifier_tui/cockpit_app.py`

**Problem:** `BlockInfo.summary` is truncated to 60 chars. Inspector shows summaries,
not content. The spec says "full content of current/pinned block."

**Fix:**
- Add `content: str = ""` field to `BlockInfo` dataclass (after `summary`)
- In `cockpit_app.py`, everywhere `_block_registry.add()` is called, pass the full
  text as `content=text` parameter:
  - `_add_system_message` (line ~389): `content=text`
  - `_add_user_message` (line ~407): `content=text`
  - `_add_assistant_message` (line ~427): `content=text`
  - `_begin_streaming_block` (line ~551): `content=""` (updated on finalize)
  - `_finalize_streaming_block` (line ~608): set `block.content = final_text`
  - `_add_thinking_block` (line ~619): `content=text`
  - `_add_tool_use` (line ~632): `content=f"Input:\n{input_str}\n\nResult:\n{result}"`
    (use FULL result, not `result[:500]`)
- Remove the `content_ref: Any = None` dead field from BlockInfo

### Task 1.2: Add `clear()` to BlockRegistry and sync with DOM

**Files:** `amplifier_tui/models/block_model.py`, `amplifier_tui/cockpit_app.py`

**Problem:** `action_clear_chat` (line ~900) clears DOM children but `_block_registry`
retains stale blocks. Inspector shows "block 5/10" when 0 exist in DOM.

**Fix:**
- Add `clear()` method to `BlockRegistry` that resets `_blocks` to `[]`
- In `action_clear_chat`, after clearing DOM children, call:
  `self._block_registry.clear()`
  `self._turn_index = 0`

### Task 1.3: Add backpressure to SteerQueue

**Files:** `amplifier_tui/models/block_model.py`

**Problem:** No size limit. Misbehaving loop could enqueue thousands of steer messages.

**Fix:**
- Add `MAX_SIZE = 10` class constant to `SteerQueue`
- In `enqueue()`, if `len(self._queue) >= self.MAX_SIZE`, drop oldest:
  `self._queue.popleft()`
- Add `@property def is_full(self) -> bool` for callers to check

### Task 1.4: Fix `list.pop(0)` -> deque in SessionHandle._pending_injects

**Files:** `amplifier_tui/core/session_manager.py`

**Problem:** `_pending_injects` uses `list` with `pop(0)` which is O(n).
`SteerQueue` uses `deque` correctly -- this is an inconsistency.

**Fix:**
- Change `_pending_injects: list[str] = field(default_factory=list)` to
  `_pending_injects: deque[str] = field(default_factory=deque)` (line ~61)
- Change `self._pending_injects.append(message)` stays the same (deque supports it)
- Change `self._pending_injects.pop(0)` to `self._pending_injects.popleft()` (line ~77)
- Add `from collections import deque` import at top of file (already present via
  module, but verify)

---

## Phase 2: Integration Plumbing (Steering and /ask)

These fix the broken pipes that are the core value proposition of the cockpit.

### Task 2.1: Fix steering end-to-end -- drain _pending_injects in send_message

**Files:** `amplifier_tui/core/session_manager.py`, `amplifier_tui/cockpit_app.py`

**Problem:** The entire steering feature is broken. Messages go into
`_pending_injects` but nothing ever reads that list. `send_message()` just calls
`handle.session.execute(message)` without checking for pending injects.

**Fix approach:** When the session is idle (not mid-execution), steer messages should
become the next regular user message. When the session is mid-execution (tool pause),
they should be injected as additional context.

**In `cockpit_app.py` `_check_steer_queue` (line ~998):**
The current code already dequeues from `SteerQueue` and calls
`handle.inject_user_message()`. But nothing consumes `_pending_injects`.

**Fix 1 - Idle case:** In `_check_steer_queue`, when the session is NOT processing
(i.e., `_conversation.is_processing` is False), dequeue the steer message and send
it as a regular message instead of injecting:

```python
def _check_steer_queue(self) -> None:
    """Inject pending steer messages at natural pause points."""
    if self._steer_queue.is_empty:
        return
    cid = self._conversation.conversation_id
    handle = self.session_manager.get_handle(cid) if self.session_manager else None
    if not handle:
        return
    steer_text = self._steer_queue.dequeue()
    if not steer_text:
        return
    if not self._conversation.is_processing:
        # Session is idle: send as a regular message
        self._add_user_message(steer_text)
        self._start_processing("Steering", conversation_id=cid)
        self._do_send_message(steer_text)
    else:
        # Session is mid-execution: inject for next tool pause
        handle.inject_user_message(steer_text)
        self._add_system_message(f"[steer queued] {steer_text}")
```

**Fix 2 - Mid-execution case:** In `session_manager.py` `send_message` (line ~485),
after `execute()` returns, drain any pending injects by sending them as follow-up
messages:

```python
async def send_message(self, message: str, conversation_id: str | None = None) -> str:
    cid = conversation_id or self._default_conversation_id
    if cid is None:
        raise ValueError("No conversation_id and no default session")
    handle = self._handles.get(cid)
    if handle is None or handle.session is None:
        raise ValueError(f"No active session for conversation {cid!r}")
    response = await handle.session.execute(message)
    # Drain pending steering injects
    while handle.has_pending_inject:
        inject = handle.pop_pending_inject()
        if inject:
            response = await handle.session.execute(inject)
    return response
```

### Task 2.2: Fix inspector to show full block content

**Files:** `amplifier_tui/widgets/inspector_panel.py`

**Problem:** `_display_block` (line ~209) only shows `block.summary` (60 chars).

**Fix:** Use the new `block.content` field from Task 1.1:

```python
def _display_block(self, block_id: int) -> None:
    block = self._registry.get_by_id(block_id)
    if block is None:
        self._set_detail_content("[STALE] Block not found")
        return
    header = (
        f"Block {block.block_id} | {block.block_type.value} | Turn {block.turn_index}\n"
        f"{'=' * 40}\n"
    )
    body = block.content if block.content else block.summary
    self._set_detail_content(header + body)
```

### Task 2.3: Fix /ask to actually retrieve and display response

**Files:** `amplifier_tui/cockpit_app.py`

**Problem:** `_do_ask` (line ~1050) creates a side session, injects a message,
does `await asyncio.sleep(1)`, and never retrieves the response. `display_ask_response`
is orphaned.

**Fix:** Replace the stub implementation:

```python
@work(exclusive=True)
async def _do_ask(self, context: str) -> None:
    """Send ask context to side session and display response."""
    if not self.session_manager:
        return

    # Lazy create side session
    if not self._side_session_id:
        try:
            handle = await self.session_manager.start_new_session()
            self._side_session_id = handle.conversation_id
        except Exception as e:
            self.call_from_thread(
                self._add_system_message, f"Failed to create side session: {e}"
            )
            return

    self.call_from_thread(self._update_status, "Side session thinking...")

    try:
        response = await self.session_manager.send_message(
            context, conversation_id=self._side_session_id
        )
        if response:
            self.call_from_thread(self._show_ask_response, response)
    except Exception as e:
        self.call_from_thread(
            self._add_system_message, f"Side session error: {e}"
        )
    finally:
        self.call_from_thread(self._update_status, "Ready")

def _show_ask_response(self, response: str) -> None:
    """Display /ask response in the inspector panel."""
    try:
        panel = self.query_one("#inspector-panel", InspectorPanel)
        panel.display_ask_response(response)
    except NoMatches:
        pass
```

Also fix `_build_ask_context` to use `block.content` instead of `str(block_widget)`:

```python
def _build_ask_context(self, block: BlockInfo, question: str) -> str:
    context_parts = []
    context_parts.append(
        f"Block {block.block_id} ({block.block_type.name} from turn {block.turn_index})"
    )
    if block.content:
        context_parts.append(f"Content:\n{block.content}")
    elif block.summary:
        context_parts.append(f"Summary: {block.summary}")
    context_parts.append(f"\nUser question: {question}")
    return "\n".join(context_parts)
```

---

## Phase 3: UX and Safety Fixes

### Task 3.1: Add input target indicator

**Files:** `amplifier_tui/cockpit_app.py`

**Problem:** No visual indicator showing where input is routed (main vs inspector).
Spec says "A visual indicator shows the current input target."

**Fix:** Update the status bar in `_toggle_inspector` and `_handle_input`:
- When inspector opens: update status bar to include "[Inspector]" prefix
- When inspector closes: remove the prefix
- The ChatInput placeholder text should change: "Message..." vs "Inspector: /steer, /ask..."

### Task 3.2: Make tmux cockpit opt-in, not opt-out

**Files:** `amplifier_tui/__main__.py`

**Problem:** Line ~241: `TMUX` env auto-detects and forces cockpit mode.
Existing tmux users will be surprised.

**Fix:** Remove the auto-detection. Only use cockpit when `--cockpit` is explicit:
```python
use_cockpit = args.cockpit
# Remove: if not use_cockpit and not args.no_cockpit and os.environ.get("TMUX"):
#     use_cockpit = True
```
Remove the `--no-cockpit` flag entirely (no longer needed).

### Task 3.3: Add session cleanup on app exit

**Files:** `amplifier_tui/cockpit_app.py`

**Problem:** No `on_unmount`. Sessions leak, transcripts incomplete, file logger
handle dangles.

**Fix:** Add cleanup method:
```python
async def on_unmount(self) -> None:
    """Clean up sessions and resources on app exit."""
    if self.session_manager:
        cid = self._conversation.conversation_id
        try:
            await self.session_manager.end_session(cid)
        except Exception:
            _cockpit_log.debug("Failed to end main session on unmount", exc_info=True)
        # Clean up side session
        if self._side_session_id:
            try:
                await self.session_manager.end_session(self._side_session_id)
            except Exception:
                _cockpit_log.debug("Failed to end side session on unmount", exc_info=True)
```

### Task 3.4: Fix help text to match actual commands

**Files:** `amplifier_tui/commands/cockpit_cmds.py`

**Problem:** Help lists `/model`, `/tokens`, `/include`, `/git` which don't exist
in `_dispatch_slash_command` (cockpit_app.py line ~752).

**Fix:** Remove non-existent commands from help text (lines 97-100):
```python
def _cmd_cockpit_help(self) -> None:
    help_text = (
        "Cockpit Commands:\n"
        "  /help        Show this help\n"
        "  /shell       Open tmux split for shell access\n"
        "  /clear       Clear chat\n"
        "  /quit        Exit cockpit\n"
    )
    self._add_system_message(help_text)
```

### Task 3.5: Fix BEL to only fire in tmux

**Files:** `amplifier_tui/cockpit_app.py`

**Problem:** `_send_bel()` fires unconditionally on every turn completion (line ~473).
In non-tmux terminals, this produces an audible beep.

**Fix:** In `_finish_processing`, guard the BEL:
```python
import os
if os.environ.get("TMUX"):
    _send_bel()
```

---

## Phase 4: Robustness and Cleanup

### Task 4.1: Fix race condition in send/cancel

**Files:** `amplifier_tui/cockpit_app.py`

**Problem:** `_do_send_message` (line ~769) is `@work(thread=True, group="send-message")`.
Cancellation triggers `_finish_processing` in `finally` while replacement worker runs.

**Fix:** Check `self.is_current` in the finally block:
```python
finally:
    if not hasattr(self, '_current_worker') or self._current_worker is None:
        self.call_from_thread(self._finish_processing, conversation_id=cid)
```

Actually, the simpler fix: use a flag to track if the worker was cancelled:
- At the top of `_do_send_message`, check if the current worker is still valid
- In `finally`, only call `_finish_processing` if `not conv.streaming_cancelled`
  AND the worker wasn't replaced

Better approach -- use Textual's `Worker.is_cancelled` property:
```python
finally:
    current_worker = get_current_worker()
    if current_worker and not current_worker.is_cancelled:
        self.call_from_thread(self._finish_processing, conversation_id=cid)
```

### Task 4.2: Fix bare `except Exception: pass` in inspector

**Files:** `amplifier_tui/widgets/inspector_panel.py`

**Problem:** Line ~229: errors during widget mounting are silently swallowed.

**Fix:** Log the exception:
```python
except Exception:
    import logging
    logging.getLogger("amplifier_tui.cockpit").debug(
        "Inspector _set_detail_content error", exc_info=True
    )
```

### Task 4.3: Fix conditional file logging

**Files:** `amplifier_tui/cockpit_app.py`

**Problem:** `/tmp/cockpit.log` file handle opened at module import time (line ~69).
Happens even when running standard TUI or tests. Doesn't work on Windows.

**Fix:** Move the file handler setup into `CockpitApp.__init__` or guard with env check:
```python
import os
import tempfile

_cockpit_log = logging.getLogger("amplifier_tui.cockpit")
_cockpit_log.setLevel(logging.DEBUG)

# Only add file handler when running cockpit (lazy, not at import time)
_file_handler_added = False

def _ensure_file_logging() -> None:
    global _file_handler_added
    if _file_handler_added:
        return
    log_path = os.path.join(tempfile.gettempdir(), "cockpit.log")
    handler = logging.FileHandler(log_path, mode="a")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _cockpit_log.addHandler(handler)
    _file_handler_added = True
```
Then call `_ensure_file_logging()` at the top of `CockpitApp.__init__`.

### Task 4.4: Remove private attribute access patterns

**Files:** `amplifier_tui/cockpit_app.py`, `amplifier_tui/core/session_manager.py`

**Problem:**
- `cockpit_app.py:877`: `self.session_manager._handles.pop(cid, None)` -- use
  public `remove_handle(cid)` instead
- `session_manager.py:383,427`: `handle.session = bridge_handle._session` -- the
  bridge's private API. This is harder to fix without bridge changes, so document
  with a comment for now.

**Fix:**
- Line ~877: replace `self.session_manager._handles.pop(cid, None)` with
  `self.session_manager.remove_handle(cid)`

### Task 4.5: Fix dead branching in streaming methods

**Files:** `amplifier_tui/cockpit_app.py`

**Problem:** `_update_streaming_content` (line ~589) and `_finalize_streaming_block`
(line ~598) both have `isinstance` checks with identical branches.

**Fix:** Remove the dead branch, use a single `.update()` call:
```python
def _update_streaming_content(self, block_type: str, accumulated_text: str) -> None:
    if self._stream_widget is not None:
        self._stream_widget.update(accumulated_text)

def _finalize_streaming_block(self, block_type: str, final_text: str) -> None:
    if self._stream_widget is None:
        return
    self._stream_widget.update(final_text)
    # Update the block content and summary in the registry
    if self._current_streaming_block_id is not None:
        block = self._block_registry.get_by_id(self._current_streaming_block_id)
        if block:
            block.content = final_text
            block.summary = final_text[:60]
    self._stream_widget = None
    self._stream_container = None
    self._stream_block_type = ""
    self._current_streaming_block_id = None
```

---

## Phase 5: Test Remediation

### Task 5.1: Add integration test for send -> stream -> block pipeline

**Files:** `tests/test_cockpit_integration.py`

Write a test that mocks the bridge, sends a message through `_do_send_message`,
and verifies streaming callbacks fire and blocks are created in the registry.

### Task 5.2: Add test for steering end-to-end

**Files:** `tests/test_cockpit_integration.py`

Write a test that:
1. Sends an initial message
2. Queues a steer message via `_steer_queue.enqueue()`
3. Verifies the steer message reaches the mock bridge's execute()

### Task 5.3: Add test for /ask end-to-end

**Files:** `tests/test_cockpit_integration.py`

Write a test that:
1. Creates a block
2. Fires InspectorAskRequest
3. Verifies side session is created
4. Verifies response appears in inspector via display_ask_response

### Task 5.4: Add test for cleanup on exit

**Files:** `tests/test_cockpit_app.py`

Write a test that verifies `on_unmount` calls `session_manager.end_session()`.

### Task 5.5: Add test for BlockRegistry.clear()

**Files:** `tests/test_block_model.py`

Write a test that verifies `clear()` resets the registry and block IDs restart from 0.

### Task 5.6: Add test for SteerQueue backpressure

**Files:** `tests/test_block_model.py`

Write a test that enqueues more than MAX_SIZE messages and verifies oldest are dropped.

### Task 5.7: Fix existing steering integration test

**Files:** `tests/test_cockpit_integration.py`

The current test asserts nothing ("Just verify no crash"). Replace with actual
assertions that verify the steer message was processed.

---

## Execution Order

Phases 1-4 are sequential (each depends on prior). Phase 5 tasks can run after
their corresponding Phase 1-4 tasks complete.

```
Phase 1 (data model) → Phase 2 (plumbing) → Phase 3 (UX) → Phase 4 (robustness)
                                                                  ↓
                                                            Phase 5 (tests)
```