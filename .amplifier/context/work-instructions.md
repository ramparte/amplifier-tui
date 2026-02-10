# Work Instructions: amplifier-tui Test & Bug Fix Sprint

You are working on the amplifier-tui project at `/home/samschillace/dev/ANext/amplifier-tui`.

## Project Context

This is a Textual-based TUI (Terminal UI) for the Amplifier AI agent framework. It's a 23,000-line Python application with 78+ slash commands, session management, streaming responses, and many features.

**Current state (from a skeptical audit):**
- 925 tests pass (`.venv/bin/python -m pytest tests/` -- must use venv, not system python)
- BUT ~28% of those tests are import-checks or hasattr-checks that test nothing meaningful
- The core app.py (6,038 lines) has ZERO test coverage
- 20 bugs are logged in `bugs.db` (SQLite), all status "open", zero resolved
- 3 preferences fields don't load from YAML despite having save functions
- Sidebar toggle is broken (bugs #17, #19)
- Type annotations for `session_manager` and timers are `object | None` defeating type checking

## Your Task List

Read `TASKS.md` in the repo root. It contains 15 tasks organized by priority:
- **P0 (TUI-001 through TUI-004)**: Test infrastructure -- add coverage, replace fake tests, add pilot tests
- **P1 (TUI-005 through TUI-010)**: Real bugs -- fix and close in bugs.db
- **P2 (TUI-011 through TUI-014)**: Test coverage expansion
- **P3 (TUI-015)**: Code quality

**Execute in the order specified in the "Execution Order" section of TASKS.md.**

## Critical Rules

### 1. Use the venv
```bash
cd /home/samschillace/dev/ANext/amplifier-tui
.venv/bin/python -m pytest tests/  # NOT python3 -m pytest
```
System python3 does NOT have textual installed. All commands must use `.venv/bin/python`.

### 2. Tests must be REAL
The whole point of this sprint is replacing fake tests with real ones. Every test you write must:
- Call actual functions or methods (not just check they exist)
- Assert on observable behavior (return values, state changes, output content)
- Cover at least one error/edge case per function tested
- NEVER use `assert True`, `assert X is not None` (for non-None checks), or `assert isinstance(X, type)` as the primary assertion

### 3. For Textual Pilot tests
The Textual testing pattern:
```python
import pytest
from textual.pilot import Pilot
from amplifier_tui.app import AmplifierTuiApp

@pytest.mark.asyncio
async def test_something():
    app = AmplifierTuiApp()
    async with app.run_test() as pilot:
        # pilot.press("ctrl+n")  # simulate keypress
        # await pilot.type("hello")  # type text
        # await pilot.press("enter")  # press enter
        # Use app.query_one(Selector) to find widgets and assert on them
        pass
```
The app may fail to start if amplifier-core isn't importable. If so, mock the session manager at the import level or use the app's built-in demo/fallback mode.

### 4. Update bugs.db when fixing bugs
```bash
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('bugs.db')
conn.execute(\"UPDATE bugs SET status='fixed', notes='Fixed in TUI-00X' WHERE id=N\")
conn.commit()
"
```
Valid statuses: `open`, `fixed`, `wontfix`, `partial`

### 5. Run tests after EVERY change
After every file edit, run:
```bash
.venv/bin/python -m pytest tests/ -x --tb=short
```
Do NOT accumulate changes without testing. If tests break, fix immediately before continuing.

### 6. Commit after each task
Each TUI-XXX task should be a separate commit. Use conventional commits:
```
fix: TUI-005 load missing display preferences from YAML
test: TUI-002 replace hasattr smoke tests with real command tests
chore: TUI-007 delete stale test_session_creation.py
```

## Key File Locations

| File | Purpose |
|------|---------|
| `amplifier_tui/app.py` | Main app (6,038 lines, the god object) |
| `amplifier_tui/preferences.py` | Preferences loading/saving (1,600 lines) |
| `amplifier_tui/session_manager.py` | Amplifier integration (504 lines) |
| `amplifier_tui/commands/` | 20 command mixin files |
| `amplifier_tui/features/` | 16 feature modules |
| `amplifier_tui/persistence/` | 13 JSON store modules |
| `amplifier_tui/widgets/` | 10 widget modules |
| `tests/` | Test directory (this is where you work) |
| `tests/conftest.py` | Shared fixtures (needs enrichment) |
| `tests/test_commands.py` | FAKE tests -- replace entirely |
| `tests/test_widgets.py` | Mostly fake -- replace import tests |
| `bugs.db` | SQLite bug database (20 open bugs) |
| `TASKS.md` | Your task list with full specs |
| `pyproject.toml` | Project config (needs pytest-cov additions) |
| `test_session_creation.py` | STALE file at repo root -- delete this (TUI-007) |

## Architecture Notes

- The app uses Textual (https://textual.textualize.io/) as the TUI framework
- `AmplifierTuiApp` inherits from `textual.App` plus 20 command mixin classes
- Command mixins access app state via `self._*` attributes (no formal interface/Protocol)
- All mixins have `# type: ignore[attr-defined]` on the class line since they reference parent attrs
- The persistence layer uses `JsonStore` base class with atomic writes to `~/.amplifier/tui/`
- Feature modules are pure logic (state machines, trackers) -- they don't import Textual
- The app has a "demo mode" fallback when amplifier-core isn't installed

## What Success Looks Like

When you're done:
- `pytest --cov=amplifier_tui` shows a coverage report with a real number (target: >25%)
- Zero `assert True` or `assert isinstance(X, type)` tests remain as primary assertions
- At least 8 Textual Pilot tests exercise real app behavior
- All 20 bugs in bugs.db have a non-"open" status (fixed, wontfix, or partial with notes)
- Preferences load all 12 display fields correctly (tested)
- Tests still pass: 0 failures, 0 errors
