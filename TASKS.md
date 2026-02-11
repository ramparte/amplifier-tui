# Amplifier TUI - Task List

## Priority Guide
- **P0**: Blocks confidence in the codebase (do first)
- **P1**: Real bugs affecting users
- **P2**: Test quality improvements
- **P3**: Code quality / type safety

---

## P0: Test Infrastructure (Do First)

### TUI-001: Add pytest-cov and establish coverage baseline
- Add `pytest-cov` to dev dependencies in `pyproject.toml`
- Add `[tool.pytest.ini_options]` with `addopts = --cov=amplifier_tui --cov-report=term-missing`
- Add `[tool.coverage.run]` with `source = ["amplifier_tui"]`
- Add `[tool.coverage.report]` with `fail_under = 25` (realistic starting floor)
- Run once, record the baseline number in this file
- **Baseline**: 26.77% (925 tests, recorded 2026-02-10)
- **Acceptance**: `pytest` output includes coverage report; CI-ready config exists

### TUI-002: Replace test_commands.py with real behavioral tests
- Current file: 150 lines of `assert isinstance(X, type)` and `assert hasattr(X, "_cmd_foo")` -- zero behavior tested
- DELETE the entire file content and replace with tests that actually exercise command logic
- Since command mixins need `self` to be a full Textual app, use one of these approaches:
  - **Option A (preferred)**: Use `textual.pilot` async tests -- `async with app.run_test() as pilot:` then type commands and verify output
  - **Option B (acceptable)**: Create a minimal mock app class that provides the `self._*` attributes the mixins need, then call command methods directly and verify side effects
- Minimum tests to write:
  - `/new` creates a new tab (or calls session_manager.start_new_session)
  - `/export markdown` produces markdown output
  - `/theme dark` changes the active theme
  - `/search <term>` filters messages
  - `/bookmark` adds a bookmark to persistence
  - `/snippet save <name>` saves a snippet
  - `/compact` toggles compact mode
  - `/help` produces help text
- **Acceptance**: Every test calls a real command method and asserts on observable side effects (state change, output content, persistence write). Zero `hasattr` or `isinstance` assertions.

### TUI-003: Replace test_widgets.py import smoke tests with real tests
- Keep the 4 good tests (TestTabState + TestAttachment)
- Replace the 9 `assert X is not None` import tests with a single parametrized import test
- Add real widget tests using Textual's async test framework:
  - `ChatInput`: test that typing text and pressing Enter produces the expected message
  - `FindBar`: test that entering a search term triggers the search callback
  - `FoldToggle`: test that clicking toggles the fold state
  - `TabBar`/`TabButton`: test that clicking a tab triggers tab-switch
- **Acceptance**: Widget tests exercise real Textual widget behavior via `app.run_test()`, not just import checks

### TUI-004: Add Textual Pilot tests for core app.py flows
- This is the heart of the application (6,038 lines) with ZERO test coverage
- Create `tests/test_app_pilot.py` using `textual.pilot`:
  ```python
  from textual.pilot import Pilot
  from amplifier_tui.app import AmplifierTuiApp

  async def test_app_boots():
      """App mounts without error."""
      app = AmplifierTuiApp()
      async with app.run_test() as pilot:
          assert app.is_running
  ```
- Minimum test scenarios:
  1. **App boots without crash** -- mount, verify no exceptions
  2. **Typing in input area** -- type text, verify it appears in ChatInput
  3. **Slash command dispatch** -- type `/help`, press Enter, verify help output appears
  4. **Theme switching** -- type `/theme dracula`, verify theme changes
  5. **Focus mode toggle** -- press Ctrl+F, verify sidebar hides
  6. **Tab creation** -- type `/new`, verify a new tab appears
  7. **Export** -- type `/export markdown`, verify markdown output
  8. **Keyboard shortcuts** -- press `?`, verify shortcut overlay appears
- Note: The app may need amplifier-core to be importable for session features. For tests where amplifier isn't available, patch `session_manager` or test in "demo mode" (no active session).
- **Acceptance**: At least 8 pilot tests covering the scenarios above, all passing

---

## P1: Real Bugs (Fix and Close in bugs.db)

### TUI-005: Fix preferences not loading 3 display fields (Bugs #7, #8, #9)
- File: `amplifier_tui/preferences.py`, function `load_preferences()` (line 513)
- The `display` section loading block (around line 547) reads 9 fields but SKIPS:
  - `editor_auto_send` (dataclass default: False)
  - `fold_threshold` (dataclass default: 20)
  - `show_suggestions` (dataclass default: True)
- Fix: Add the 3 missing fields to the display loading block, matching the existing pattern:
  ```python
  if "editor_auto_send" in ddata:
      prefs.display.editor_auto_send = bool(ddata["editor_auto_send"])
  if "fold_threshold" in ddata:
      prefs.display.fold_threshold = int(ddata["fold_threshold"] or 20)
  if "show_suggestions" in ddata:
      prefs.display.show_suggestions = bool(ddata["show_suggestions"])
  ```
- Write a test in `tests/test_preferences.py` (new file) that:
  - Creates a YAML file with these 3 fields set to non-default values
  - Calls `load_preferences(path)` 
  - Asserts the returned Preferences object has the non-default values
- Mark bugs #7, #8, #9 as "fixed" in bugs.db
- **Acceptance**: Test passes, all 3 fields load from YAML correctly

### TUI-006: Fix sidebar toggle bugs (Bugs #17, #19)
- Bug #17: Sidebar toggle doesn't restore sidebar on second invocation
- Bug #19: Sidebar toggle-back corrupts input area and status bar layout
- These share a root cause: the sidebar show/hide state gets out of sync
- Investigate `app.py` for the sidebar toggle logic (search for `action_toggle_sidebar` or `ctrl+b` binding)
- The likely fix: ensure the toggle reads and writes a single source-of-truth boolean, and that showing the sidebar restores CSS display properties correctly
- Write a Textual Pilot test that: hides sidebar, then shows it again, verifying layout is correct both times
- Mark bugs #17, #19 as "fixed" in bugs.db
- **Acceptance**: Sidebar can be toggled on/off/on repeatedly without layout corruption

### TUI-007: Delete stale test_session_creation.py (Bug #3)
- File: `test_session_creation.py` at repo root (NOT in tests/)
- Imports from `amplifier_chic` which doesn't exist (old package name)
- Just delete it
- Mark bug #3 as "fixed" in bugs.db
- **Acceptance**: File is gone, `git status` shows deletion

### TUI-008: Fix session_manager typing (Bug #10)
- File: `amplifier_tui/app.py` ~line 2198
- `self.session_manager: object | None = None` defeats all type checking
- Fix: Create a Protocol or use `TYPE_CHECKING` import:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from amplifier_tui.session_manager import SessionManager
  # Then:
  self.session_manager: SessionManager | None = None
  ```
- This is a type-annotation-only change. Should not affect runtime.
- Mark bug #10 as "fixed" in bugs.db
- **Acceptance**: pyright no longer reports errors for session_manager attribute access

### TUI-009: Fix Timer typing (Bug #11)
- File: `amplifier_tui/app.py`
- 5 timer variables typed as `object | None` instead of `Timer | None`
- Variables: `_spinner_timer`, `_timestamp_timer`, `_autosave_timer`, `_crash_draft_timer`, `_watch_timer`
- Fix: Import `Timer` from textual and use proper typing:
  ```python
  from textual.timer import Timer
  self._spinner_timer: Timer | None = None
  # etc.
  ```
- Mark bug #11 as "fixed" in bugs.db
- **Acceptance**: pyright no longer reports errors for `.stop()` calls on timers

### TUI-010: Triage remaining bugs (close won't-fix or downgrade)
- Review bugs #1, #2, #4, #5, #6 (SVG pipeline / environment) -- these are in the `tools/` directory, not the TUI itself. Mark as `wontfix` with note "SVG capture tooling, not core TUI"
- Review bug #12 (private method access) -- evaluate if still present, mark `wontfix` or fix
- Review bug #13 (bare except Exception) -- the refactoring reduced from 144 to 19. Count remaining, note in bugs.db, close as `partial` with the count
- Review bug #14 (unguarded session_manager) -- will be partially addressed by TUI-008 typing fix. Count remaining unguarded accesses, note in bugs.db
- Review bug #15 (88 pyright errors) -- will be partially addressed by TUI-008 and TUI-009. Run pyright, note new count
- Review bug #16 (god file) -- app.py is now 6,038 lines (down from 13,712). Update description, mark as `partial`
- Review bug #18 (keyboard shortcuts dialog truncation) -- evaluate severity, close or keep
- Review bug #20 (SVG capture timing) -- mark `wontfix`, SVG tooling issue
- **Acceptance**: Every bug in bugs.db has an updated status. Zero bugs left as untouched "open"

---

## P2: Test Coverage Expansion

### TUI-011: Add preferences.py tests
- New file: `tests/test_preferences.py`
- Test scenarios:
  - Load from valid YAML with all sections
  - Load from YAML with missing sections (falls back to defaults)
  - Load from nonexistent file (creates default)
  - Load from corrupt YAML (falls back to defaults)
  - Color resolution (hex, named colors, invalid colors)
  - Theme application (`prefs.apply_theme("dracula")`)
  - Custom theme loading from YAML
  - Save functions: `save_fold_threshold`, `save_editor_auto_send`, `save_show_suggestions`
- **Acceptance**: 15+ tests covering happy path, error paths, and round-trips

### TUI-012: Add session_manager.py tests
- New file: `tests/test_session_manager.py`
- This module integrates with amplifier-core, so tests need mocking at the amplifier boundary
- Test scenarios:
  - SessionManager init when amplifier-core is available
  - SessionManager init when amplifier-core is NOT available (graceful fallback)
  - start_new_session creates a session
  - resume_session loads existing session
  - send_message delegates to amplifier correctly
  - Error handling for network/API failures
- **Acceptance**: 10+ tests covering both with-amplifier and without-amplifier paths

### TUI-013: Add history.py tests
- New file: `tests/test_history.py`
- Test scenarios:
  - Empty history on fresh file
  - Add entries, verify ordering
  - Deduplication (same entry not added twice)
  - Max size limit (oldest entries pruned)
  - Persistence across load/save cycles
  - Corrupt file handling
- **Acceptance**: 8+ tests using tmp_path for file I/O

### TUI-014: Enrich conftest.py fixtures
- Current fixtures are trivially simple (4 messages, all None widgets)
- Add fixtures for:
  - Messages with tool_use blocks (tool name, input JSON)
  - Messages with tool_result blocks
  - Messages with thinking blocks
  - Messages with long content (>1000 chars)
  - Messages with code blocks and markdown
  - Messages with Unicode / emoji
  - Metadata with multiple models, long session IDs
- **Acceptance**: At least 6 new fixtures available for use across test files

---

## P3: Code Quality

### TUI-015: Reduce bare except clauses in app.py
- Currently 19 `except Exception` clauses remain in app.py
- For each one: determine if a more specific exception type is appropriate
- At minimum, add logging to each bare except (many currently just `pass`)
- Target: reduce to <5 bare except clauses, all with justifying comments
- **Acceptance**: `grep -c "except Exception" amplifier_tui/app.py` returns < 5

---

## Execution Order

The recommended execution order respects dependencies:

1. **TUI-007** (delete stale file -- 30 seconds)
2. **TUI-001** (add pytest-cov -- 10 minutes)
3. **TUI-005** (fix preferences loading -- 15 minutes, includes writing tests)
4. **TUI-008** (fix session_manager typing -- 15 minutes)
5. **TUI-009** (fix Timer typing -- 10 minutes)
6. **TUI-002** (replace test_commands.py -- 45 minutes)
7. **TUI-003** (replace test_widgets.py -- 30 minutes)
8. **TUI-004** (add pilot tests for app.py -- 60 minutes)
9. **TUI-006** (fix sidebar toggle -- 30 minutes, needs pilot tests from TUI-004)
10. **TUI-010** (triage remaining bugs -- 20 minutes)
11. **TUI-011** (preferences tests -- 30 minutes)
12. **TUI-012** (session_manager tests -- 30 minutes)
13. **TUI-013** (history tests -- 20 minutes)
14. **TUI-014** (enrich fixtures -- 15 minutes)
15. **TUI-015** (reduce bare excepts -- 30 minutes)

Total estimated effort: ~6 hours of focused AI session time.

## Phase 2: Codex-Inspired Features (New)

Competitive analysis of OpenAI Codex CLI identified features worth adding.
Approved for implementation now, plus deferred items noted for later.

### BUILD NOW

#### TUI-020: Mid-Turn Steering
- **Priority**: P0 - Highest UX impact
- Allow user to type while agent is streaming/working
- Input queued and sent as interrupt or next message
- ChatInput must accept input during streaming state
- `_streaming` flag should not block input focus
- Options: (a) interrupt current turn, (b) queue as next message
- Start with queue-as-next, add interrupt later if needed
- **Acceptance**: User can type and submit while agent is streaming; message is sent after current turn completes

#### TUI-021: Todo Panel
- **Priority**: P1 - Continuous visibility into agent planning
- Surface the agent's `todo` tool state as a live sidebar/panel
- Parse `todo` tool calls from streaming events (`tool_use` where tool name is `todo`)
- Display as a persistent checklist panel (collapsible, like PinnedPanel)
- Update in real-time as todo events stream in
- Show status indicators: pending, in_progress, completed
- Toggle with `/todo` command or keybinding
- **Acceptance**: Todo items appear and update live as agent uses the todo tool

#### TUI-022: Context Pressure Indicator
- **Priority**: P1 - Always-visible context health
- Add persistent element to status bar showing context window usage
- Color-coded thresholds: green (<50%), yellow (50-75%), orange (75-90%), red (>90%)
- Use existing `total_input_tokens` + `total_output_tokens` vs `context_window`
- Compact format: e.g., `[CTX 45%]` or a mini progress bar
- Updates after each LLM response
- **Acceptance**: Status bar shows color-coded context usage percentage that updates live

#### TUI-023: Agent Tree Panel
- **Priority**: P1 - Differentiator vs Codex (they don't have this)
- Collapsible panel showing live delegation hierarchy
- Parse `delegate` tool calls and `session:start`/`session:end` events
- Tree structure: root session -> sub-agents with status (running/completed/failed)
- Clicking/selecting a sub-session shows summary or transcript snippet
- Remove the `_` filter in session listing (make it optional via preference)
- Integrate with existing `agent_tracker.py` feature module
- Toggle with `/agents tree` or keybinding
- **Acceptance**: Live tree of agent delegations visible during multi-agent work; completed agents show summary

#### TUI-024: /skills Command
- **Priority**: P2 - Quality of life
- `/skills` - List available skills (from `~/.amplifier/skills/` and `.amplifier/skills/`)
- `/skills <name>` - Preview a skill's description/metadata
- `/skills load <name>` - Send a message asking the agent to load the skill
- Discover skills by scanning skill directories for `.md` files with YAML frontmatter
- **Acceptance**: User can browse and activate skills from the TUI

#### TUI-025: /commit Shortcut
- **Priority**: P2 - Developer workflow
- Smart commit flow in one command:
  1. Run `git diff --staged` (or `git diff` if nothing staged)
  2. Show diff summary to user
  3. Ask agent to generate commit message based on diff
  4. Show proposed message, user can accept/edit/cancel
  5. Execute commit
- If nothing staged, offer to stage all changes first
- **Acceptance**: `/commit` produces a reviewed, committed change with AI-generated message

#### TUI-026: /recipe Quick-Launch
- **Priority**: P2 - Easy recipe access
- `/recipe run` - List available recipes
- `/recipe run <name>` - Execute a recipe by name
- Discover recipes from bundle paths and local `.amplifier/recipes/`
- Show recipe description before confirming execution
- **Acceptance**: User can browse and launch recipes from the TUI

#### TUI-027: /gitstatus Command
- **Priority**: P3 - Easy and useful
- `/gitstatus` - Show `git status --short` + branch + ahead/behind info
- Compact, colorized output in chat
- Alias: `/gs`
- **Acceptance**: Quick git status visible in chat

#### TUI-028: /auto Command (Approval Mode)
- **Priority**: P3 - Safety toggle
- `/auto` - Show current mode
- `/auto suggest` - Confirm file writes and bash commands (safe default)
- `/auto edit` - Auto-apply file edits, confirm bash
- `/auto full` - Auto-approve everything (current default behavior)
- Default: `full` (preserves current behavior)
- Store in preferences
- **Acceptance**: Mode toggleable, persists across sessions

### DEFERRED (noted for later)

#### TUI-029: Tool Approval Mode (Deferred)
- Optional confirmation dialogs for file writes and bash commands
- Preference: default OFF
- Implement if /auto command proves popular
- Depends on TUI-028

#### TUI-030: Diff Review Overlay (Deferred)
- When agent edits a file, show colored unified diff with approve/reject
- Not doing now per user decision
- Revisit when tool approval mode is built

#### TUI-031: Plan Mode Split UI (Deferred)
- Rejected for now - planning mode behavioral overlay is sufficient
- Would split view into plan pane + chat pane

#### TUI-032: /compact Context Compression (Deferred)
- Rejected for now - needs orchestrator/kernel support
- Would ask model to summarize and compress history
