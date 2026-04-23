# Cockpit CLI Parity Plan

**Date:** 2026-04-08
**Branch:** feat/web-native-frontend

## Short Framing

The cockpit is a TUI app that calls Amplifier foundation APIs directly,
bypassing the CLI's `session_runner.create_initialized_session()`.  That
function does ~8 things the cockpit doesn't.  The result is a half-working
session that can't persist, can't delegate agents, can't resolve @mentions,
auto-approves all risky tool calls, and silently drops most slash commands.

The prior sessions patched surface symptoms (timeout wrappers, provider
injection checks, status logging) without noticing that the cockpit
reimplements 30% of the CLI's session setup and skips the other 70%.

## Root Cause

`SessionManager.start_new_session()` calls `self._prepared.create_session()`
and registers streaming hooks.  That's it.  The CLI's equivalent path
(`session_runner.create_initialized_session()`) does all of the above plus:

1. `register_incremental_save(session)` -- session persistence
2. `register_session_spawning(session)` -- agent delegation (spawn/resume)
3. `register_mention_handling(session)` -- @file.txt resolution
4. `register_approval_provider(session)` -- interactive approval gating
5. Injects session config metadata (working_dir, application_host, project_slug)
6. `check_first_run()` / `auto_init_from_env()` -- first-run setup
7. `diagnose_transcript()` / `repair_transcript()` -- resume safety
8. `CommandProcessor` -- 15+ slash commands handled before the LLM sees them

## Fix Strategy

Don't reimplement.  Import and call the same functions the CLI uses.  Most
of the gaps are one-line imports + calls in `start_new_session()`.

---

## Phase 1: Session Infrastructure (Critical)

These fix data loss and broken features.  All are single-call additions to
`SessionManager.start_new_session()`.

### Task 1.1: Session persistence (prevents data loss)

```python
# After streaming hooks, before returning handle
from amplifier_app_cli.incremental_save import register_incremental_save
register_incremental_save(session)
```

Without this, closing the cockpit loses the entire conversation.

### Task 1.2: Agent delegation (enables tool-task)

```python
from amplifier_app_cli.session_runner import register_session_spawning
register_session_spawning(session, self._prepared)
```

Without this, the `delegate` tool fails silently.  The LLM can call tools
but can't spawn sub-agents.

### Task 1.3: @mention resolution

```python
from amplifier_app_cli.session_runner import register_mention_handling
register_mention_handling(session)
```

Without this, `@file.txt` in user messages is sent as literal text.

### Task 1.4: Session config metadata

```python
session.config["working_dir"] = str(cwd)
session.config["application_host"] = "Amplifier Cockpit"
session.config["project_slug"] = cwd.name if cwd else ""
session.config["project_name"] = cwd.name if cwd else ""
```

Without this, hooks that read session config get empty values.

---

## Phase 2: UX Parity (High)

### Task 2.1: Fix "Starting session" on every message

Line 827 in cockpit_app.py:
```python
# BEFORE (wrong):
self._start_processing("Starting session", conversation_id=cid)

# AFTER (correct):
has_session = self.session_manager.get_handle(cid) is not None
label = "Starting session" if not has_session else "Thinking"
self._start_processing(label, conversation_id=cid)
```

### Task 2.2: Handle bare `exit` and `quit`

Line 841 in cockpit_app.py -- add to the handlers:
```python
handlers = {
    "/help": ...,
    "/shell": ...,
    "/clear": ...,
    "/quit": lambda: self.exit(),
    "/q": lambda: self.exit(),
    "/exit": lambda: self.exit(),
}
```

Also add pre-slash-command catch for bare `exit` and `quit`:
```python
if text.strip().lower() in ("exit", "quit"):
    self.exit()
    return
```

### Task 2.3: Make /clear actually clear session context

Current /clear only removes DOM nodes.  It should also call
`session.coordinator.get("context").clear()` to clear the LLM's memory.

### Task 2.4: Add /status, /new slash commands

`/status` -- show session ID, model, message count, provider list.
`/new` -- end current session, start fresh one.

---

## Phase 3: Safety (Medium)

### Task 3.1: Approval gating

Replace `BridgeApprovalSystem(auto_approve=True)` with a cockpit-aware
provider.  Minimum viable: auto-approve low risk, prompt for high/critical.

This is medium because the cockpit is currently a dev tool, not production.
But it's a silent security bypass that should be fixed before wider use.

### Task 3.2: Transcript repair on resume

Import `diagnose_transcript()` and `repair_transcript()` from
`amplifier_foundation.session` and call them in `_inject_transcript()`
before adding messages.  Without this, resuming a session that crashed
mid-tool-call causes HTTP 400 errors.

---

## Phase 4: Polish (Low)

### Task 4.1: First-run initialization
### Task 4.2: Full CommandProcessor integration
### Task 4.3: Mode management commands

These can wait.  They improve UX but don't fix broken functionality.

---

## Exit Criteria

Phase 1:
- [ ] Sessions persist to disk (transcript.jsonl written after every turn)
- [ ] Agent delegation works (tool-task can spawn sub-agents)
- [ ] @mentions resolve to file content
- [ ] Session config metadata populated

Phase 2:
- [ ] Status shows "Thinking" on second+ messages, "Starting session" only on first
- [ ] `exit`, `quit`, `/exit` all exit the app
- [ ] /clear resets session context
- [ ] /status shows session info
- [ ] /new starts a fresh session

Phase 3:
- [ ] High-risk tools require explicit approval
- [ ] Resume handles corrupted transcripts gracefully

## Execution Order

Phase 1 first (all in one commit).  Phase 2 next.  Phase 3 separately.
