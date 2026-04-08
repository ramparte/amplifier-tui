# Cockpit Mode Test Remediation Plan

**Date:** 2026-04-08 (updated from 2026-04-07)
**Branch:** feat/web-native-frontend
**Status:** In progress -- root cause found, fix verified

## Root Cause Analysis (NEW)

The cockpit mode's "Error: No providers available" failure in tmux has a single
root cause with two layers:

**Layer 1 -- Missing API key injection:**
The Amplifier CLI loads `~/.amplifier/keys.env` into `os.environ` via
`KeyManager()` at import time (`amplifier_app_cli/main.py:100`).  The cockpit
TUI bypasses the CLI, calling `PreparedBundle.create_session()` directly.  No
key loading happens.  The Anthropic provider's `mount()` checks
`os.environ.get("ANTHROPIC_API_KEY")`, finds nothing, logs a warning, and
returns `None` -- silently skipping mount.

**Layer 2 -- Silent provider mount failure:**
The loop-streaming orchestrator's `_select_provider()` receives an empty dict,
returns `None`, and yields `"Error: No providers available"` (exactly 29 chars)
with `turn_count=0` in ~10ms.  The cockpit displays this as-is.

**Evidence:**
- `/tmp/cockpit.log` at 09:53 and 09:54: `send_message returned len=29` in 23ms and 10ms
- Direct test with `ANTHROPIC_API_KEY` removed from env, then _load_keys_env(): providers mount, LLM responds

**Fix:** `_load_keys_env()` added to `session_manager.py`, called in `prepare_bundle()` before
any provider mounting.  Verified working.

---

## Problem Statement (test suite)

The cockpit mode test suite has four problems (one fixed by prior session):

1. **Tests hang** -- every `CockpitApp().run_test()` triggers `_init_amplifier()` which
   spawns a thread calling `asyncio.run(prepare_bundle())` -> `uv pip install`.  No mock.
2. ~~**Swallowed exceptions**~~ -- DONE (prior session removed try/except: pass)
3. ~~**Visibility assertion mismatch**~~ -- DONE (prior session aligned to has_class)
4. **No conftest.py** -- the fundamental problem.  Every Textual test creates a real app
   which fires on_mount -> _init_amplifier -> real network I/O.

---

## Task 0: Fix provider mounting in cockpit (DONE)

**Status:** DONE -- verified

`_load_keys_env()` added to `session_manager.py:prepare_bundle()`.
Post-session provider check added to `start_new_session()`.
Direct test confirms providers mount with env var removed.

---

## Task 1: Fix test hang with conftest.py mock fixture

**Priority:** Critical -- nothing works without runnable tests

**Root cause:** `CockpitApp.on_mount()` calls `_init_amplifier()` which is
`@work(thread=True)`.  It creates a `SessionManager`, calls `check_environment()`,
and runs `prepare_bundle()` -- all real network I/O that blocks indefinitely in tests.

**Fix:** Create `tests/conftest.py` with autouse fixture that patches
`CockpitApp._init_amplifier` to a lightweight stub that sets `self._ready = True`
without doing real bundle preparation.

**Files:**
- `tests/conftest.py` (new)

**Verification:** `pytest tests/test_cockpit_app.py -v --timeout=15` completes < 30s.

---

## Task 2: Run full cockpit test suite and verify green

**Priority:** Gate

```bash
.venv/bin/python -m pytest tests/test_cockpit_app.py tests/test_cockpit_integration.py tests/test_cockpit_cmds.py -v -o "addopts=" --timeout=15
```

**Exit criteria:** All tests pass.  No hangs.  < 60 seconds.

---

## Task 3: Clean up diagnostic logging

Remove the extra diagnostic logging from `cockpit_app.py` that was added during
debugging (coordinator provider check in `_do_send_message`, response[:200] logging).
Keep the useful stuff: response length + first 200 chars in the log is actually
good for debugging.  Remove the `_handles` private access for provider checks.

---

## Task 4: Commit and push

Commit all fixes in logical order.

---

## Exit Criteria

- [x] Provider mounting works in tmux (keys.env loaded)
- [x] Swallowed exceptions removed from tests
- [x] Visibility assertions aligned with production
- [ ] conftest.py mocks _init_amplifier for all cockpit tests
- [ ] All cockpit tests pass with --timeout=15
- [ ] Full test run completes in under 60 seconds
- [ ] Diagnostic logging cleaned up
- [ ] Changes committed
