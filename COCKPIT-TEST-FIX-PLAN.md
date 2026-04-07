# Cockpit Mode Test Remediation Plan

**Date:** 2026-04-07
**Branch:** feat/web-native-frontend
**Status:** In progress

## Problem Statement

The cockpit mode test suite is broken in three distinct ways:

1. **Integration tests hang** -- 26 unit tests pass, then the suite never terminates
2. **A critical integration test swallows all exceptions** -- `test_steering_queue_flow`
   wraps assertions in `try/except: pass`, making it structurally unable to fail
3. **Tests and production code disagree on visibility mechanism** -- tests check
   `panel.display` but production uses `panel.has_class("visible")` via CSS classes

These were identified during a COE review of session 9adaec5c's work.

---

## Task 1: Diagnose and fix hanging integration tests

**Priority:** Critical -- nothing else matters if the suite doesn't terminate

**Diagnosis approach:**
- Run integration tests individually with `--timeout=15` to identify the specific
  hanging test(s)
- Likely candidates: `test_block_click_to_inspector_flow` or
  `test_inspector_navigation_flow` (both call `_toggle_inspector()` which may
  trigger recomposition that deadlocks the Textual event loop in test mode)
- The `on_click()` call in integration tests bypasses Textual's message dispatch,
  which may leave the event loop in an inconsistent state

**Fix approach:**
- Add `pytest.ini` / `pyproject.toml` timeout for async tests (15s per test)
- For hanging tests: replace direct `on_click()` calls with `pilot.click()` on
  the widget, or add explicit `await pilot.pause()` after inspector mutations
- If `_toggle_inspector()` causes hangs, inspect whether it triggers async
  recomposition that requires event loop ticks to complete

**Files:**
- `tests/test_cockpit_integration.py`
- `pyproject.toml` (timeout config)

**Verification:** `pytest tests/test_cockpit_integration.py -v --timeout=15` completes
with all tests either passing or explicitly failing (no hangs).

---

## Task 2: Fix swallowed exceptions in steering test

**Priority:** High -- test that can't fail is worse than no test

**Current code (test_cockpit_integration.py:97-113):**
```python
try:
    panel = app.query_one("#inspector-panel", InspectorPanel)
    panel.pin_to_block(0)
    await pilot.pause()
    panel.handle_input("/steer focus on error handling")
    await pilot.pause()
    assert len(app._steer_queue) == 1
except Exception:
    # Inspector might not be available in test mode
    pass
```

**Fix:** Remove the try/except entirely. If the inspector isn't available in test
mode, that is a real bug to fix, not a thing to swallow. The unit test
`TestCockpitSteering::test_steer_request_queued` in `test_cockpit_app.py` already
tests steering via `post_message(InspectorSteerRequest(...))` and passes. This
integration test should work the same way, or be deleted.

**Files:**
- `tests/test_cockpit_integration.py` (lines 97-113)

**Verification:** Test either passes or fails with a clear error. No silent swallowing.

---

## Task 3: Align test visibility checks with production code

**Priority:** Medium -- currently a latent bug, will bite when CSS behavior changes

**Problem:** Production code (`cockpit_app.py`) uses:
- `panel.has_class("visible")` to check visibility
- `panel.add_class("visible")` / `panel.remove_class("visible")` to toggle

Tests use:
- `panel.display` (Textual's display property, line 199, 210, 225 in test_cockpit_app.py)
- `panel.display` (line 52 in test_cockpit_integration.py)

**Fix:** Replace all `panel.display` / `not panel.display` assertions with
`panel.has_class("visible")` / `not panel.has_class("visible")` to match production.

**Locations (5 total):**
- `tests/test_cockpit_app.py:189` -- `assert not panels[0].display`
- `tests/test_cockpit_app.py:199` -- `assert panel.display`
- `tests/test_cockpit_app.py:210` -- `assert not panel.display`
- `tests/test_cockpit_app.py:225` -- `assert panel.display`
- `tests/test_cockpit_integration.py:52` -- `assert panel.display`

**Verification:** All modified tests still pass, and the assertions now test what
production actually does.

---

## Task 4: Run full cockpit test suite and verify green

**Priority:** Gate -- must pass before declaring done

Run:
```bash
.venv/bin/python -m pytest tests/test_cockpit_app.py tests/test_cockpit_integration.py tests/test_cockpit_cmds.py -v -o "addopts=" --timeout=15
```

**Exit criteria:** All tests pass. No hangs. No swallowed exceptions. Clean output.

---

## Task 5: Real session smoke test

**Priority:** Medium -- user reports it works "to a degree"

Launch cockpit mode and verify:
```bash
cd /home/samschillace/dev/ANext/amplifier-tui
.venv/bin/python -m amplifier_tui --cockpit
```

Check:
- App starts without crash
- Can type a message and get a response
- Blocks appear in the chat view
- F2 toggles inspector
- /help works
- /clear works
- Status bar shows session info

This is a manual verification step. Document what works and what doesn't.

---

## Execution Order

1. Task 1 (hangs) -- must fix first, everything depends on runnable tests
2. Task 2 (swallowed exceptions) -- quick fix, do alongside Task 1
3. Task 3 (visibility alignment) -- straightforward substitution
4. Task 4 (full run) -- gate check
5. Task 5 (real session) -- manual check

## Exit Criteria

- [ ] All cockpit tests pass with `--timeout=15`
- [ ] No `try/except: pass` in any test
- [ ] All visibility assertions use `has_class("visible")` matching production
- [ ] Full test run completes in under 60 seconds
- [ ] Real session launches and handles at least one exchange