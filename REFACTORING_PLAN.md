# Amplifier TUI Refactoring Plan

**Goal:** Decompose the 13,712-line monolith `amplifier_tui/app.py` (25 classes, 366 methods) into a maintainable package structure. Each phase leaves the app fully functional and is independently committable.

**Current state:** One god file with `AmplifierChicApp` (~11,650 lines, 366 methods). Support modules (`history.py`, `preferences.py`, `session_manager.py`, `transcript_loader.py`, `theme.py`) are clean and tested.

**Related bugs fixed by this plan:**
- #10 P2: `session_manager` typed as `object | None` defeats type checking
- #11 P2: Timer objects typed as `object | None`
- #13 P3: 144 bare `except Exception: pass` clauses
- #14 P2: 15 unguarded `session_manager` accesses risk crash
- #15 P3: 88 pyright errors total
- #16 P3: God file (this entire plan)
- #17 P2: Sidebar toggle does not restore sidebar on second invocation (interactive testing)
- #18 P3: Keyboard shortcuts dialog truncates descriptions (interactive testing)
- #19 P2: Sidebar toggle-back corrupts input area and status bar layout (interactive testing)

---

## Phase 0: Type Safety Foundation

**Fixes bugs:** #10, #11, #14, #15 (partial)
**Scope:** Type annotation changes and null guards only. Zero structural changes.
**Estimated effort:** 1-2 hours

### 0.1 Fix `session_manager` typing (bug #10)

The `SessionManager` class is imported lazily at line 2513. The attribute is declared as `object | None` at line 2198, defeating all type checking on every access.

**File:** `amplifier_tui/app.py`

Change the declaration (line 2198):
```python
# BEFORE
self.session_manager: object | None = None

# AFTER
from .session_manager import SessionManager
self.session_manager: SessionManager | None = None
```

Move the import to the top of the file (with other local imports, after line 40):
```python
from .session_manager import SessionManager
```

Remove the lazy `from .session_manager import SessionManager` at lines 2513 and 4114 (they become redundant).

### 0.2 Fix timer typing (bug #11)

Five attributes are typed `object | None` but hold Textual `Timer` instances:

| Line | Attribute | Fix |
|------|-----------|-----|
| 2206 | `self._spinner_timer` | `Timer \| None` |
| 2207 | `self._timestamp_timer` | `Timer \| None` |
| 2307 | `self._crash_draft_timer` | `Timer \| None` |
| 2317 | `self._watch_timer` | `Timer \| None` |
| 2341 | `self._autosave_timer` | `Timer \| None` |

Add to imports:
```python
from textual.timer import Timer
```

Change each declaration from `object | None` to `Timer | None`.

Also fix in the `TabState` dataclass:
- Line 368: `sm_session: object | None = None` -> `sm_session: Any = None` (this holds an SDK Session object whose type we don't control)
- Line 383: `last_assistant_widget: object | None = None` -> `last_assistant_widget: Static | None = None`

### 0.3 Add null guards on session_manager accesses (bug #14)

There are 15 places where `self.session_manager` is accessed without a null check. Each unguarded access risks `AttributeError` at runtime. Add a guard pattern:

```python
# Pattern: early return with user message
if self.session_manager is None:
    self._add_system_message("No active session")
    return
```

Locations to audit (grep `self.session_manager` and verify each has a guard):
- Line 4817: `await self.session_manager.end_session()` - unguarded
- Lines 4839-4841, 4846-4849: attribute accesses without guard
- All `getattr(self.session_manager, ...)` calls are safe (getattr handles None) but should use proper attribute access after typing fix

### 0.4 Verification

```bash
# Type check - should reduce pyright errors significantly
cd /home/samschillace/dev/ANext/amplifier-tui
pyright amplifier_tui/app.py 2>&1 | tail -5

# Run the app to verify it starts
python -m amplifier_tui

# Smoke test: launch, type /help, type /quit
```

---

## Phase 1: Extract Widget Classes

**Scope:** Move the 23 non-App classes out of `app.py` into a `widgets/` package. Pure file moves with import updates - no logic changes.
**Estimated effort:** 2-3 hours

### 1.1 Create package structure

```
amplifier_tui/
  widgets/
    __init__.py          (~40 lines - re-exports all widget classes)
    datamodels.py        (~60 lines - TabState, Attachment dataclasses)
    messages.py          (~80 lines - UserMessage, ThinkingStatic, AssistantMessage, ThinkingBlock, MessageMeta)
    chat_input.py        (~700 lines - ChatInput, the large text area widget)
    bars.py              (~120 lines - SuggestionBar, HistorySearchBar, FindBar)
    indicators.py        (~60 lines - ProcessingIndicator, ErrorMessage, SystemMessage, NoteMessage, FoldToggle)
    panels.py            (~200 lines - PinnedPanelHeader, PinnedPanelItem, PinnedPanel)
    screens.py           (~120 lines - ShortcutOverlay, HistorySearchScreen)
    tabs.py              (~80 lines - TabButton, TabBar)
    commands.py          (~40 lines - AmplifierCommandProvider)
```

### 1.2 Class-to-file mapping

**`datamodels.py`** - Lines 361-619
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `TabState` | 361-401 | Dataclass. Uses `field()` from dataclasses. After Phase 0, `sm_session` typed as `Any` |
| `Attachment` | 403-619 | Dataclass with class methods for file processing |

Dependencies: `dataclass`, `field`, `Path`, `base64`, `json`, `os`. Self-contained.

**`messages.py`** - Lines 621-651
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `UserMessage` | 621-626 | `Static` subclass, trivial |
| `ThinkingStatic` | 628-632 | `Static` subclass, trivial |
| `AssistantMessage` | 634-639 | `Markdown` subclass, trivial |
| `ThinkingBlock` | 641-645 | `Static` subclass, trivial |
| `MessageMeta` | 647-651 | `Static` subclass, trivial |

Dependencies: `Static`, `Markdown` from textual.

**`chat_input.py`** - Lines 653-1295
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `ChatInput` | 653-1295 | Large widget. Has `Submitted` message class, `_on_key`, auto-complete logic |

Dependencies: `TextArea`, `Static`, `events` from textual. References `SLASH_COMMANDS` (module-level tuple defined at line 112) and `SuggestionBar`. `SLASH_COMMANDS` stays in `app.py` or moves to a `constants.py`.

**`bars.py`** - Lines 1297-1394 + 1754-2020
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `SuggestionBar` | 1297-1346 | Referenced by ChatInput |
| `HistorySearchBar` | 1348-1394 | Simple static widget |
| `FindBar` | 1754-2020 | Horizontal container with Input, buttons |

Dependencies: `Static`, `Horizontal`, `Input`, `Button` from textual.

**`indicators.py`** - Lines 1396-1444
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `ProcessingIndicator` | 1396-1400 | Trivial Static |
| `ErrorMessage` | 1402-1406 | Trivial Static |
| `SystemMessage` | 1408-1413 | Trivial Static |
| `NoteMessage` | 1415-1420 | Trivial Static |
| `FoldToggle` | 1422-1444 | Static with click handler and label logic |

**`panels.py`** - Lines 1446-1629
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `PinnedPanelHeader` | 1446-1453 | Static with click handler |
| `PinnedPanelItem` | 1455-1469 | Static with click handler, stores pin data |
| `PinnedPanel` | 1471-1629 | Vertical container, compose method, manages pin items |

Dependencies: `Static`, `Vertical`, `Collapsible` from textual.

**`screens.py`** - Lines 1631-1710
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `ShortcutOverlay` | 1631-1653 | ModalScreen, compose + dismiss |
| `HistorySearchScreen` | 1655-1710 | ModalScreen[str], Input + OptionList |

Dependencies: `ModalScreen`, `Input`, `OptionList` from textual.

**`tabs.py`** - Lines 1712-1752
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `TabButton` | 1712-1721 | Static with click handler, stores tab_index |
| `TabBar` | 1723-1752 | Horizontal, `update_tabs()` method |

**`commands.py`** - Lines 2022-2058
| Class | Current Lines | Notes |
|-------|--------------|-------|
| `AmplifierCommandProvider` | 2022-2058 | Provider subclass, references `_PALETTE_COMMANDS` tuple |

Note: `_PALETTE_COMMANDS` (lines 1786-2020) is a module-level tuple that should move with this class or to `constants.py`.

### 1.3 Handle module-level constants

Two module-level tuples need to be accessible:

1. **`SLASH_COMMANDS`** (line 112-200): Used by `ChatInput` for auto-complete and by `AmplifierChicApp._handle_slash_command`. Move to `amplifier_tui/constants.py` (~100 lines).

2. **`_PALETTE_COMMANDS`** (line 1786-2020): Used only by `AmplifierCommandProvider`. Move to `widgets/commands.py`.

3. **Other module-level constants** (lines 72-110): `AMPLIFIER_DIR`, `SESSIONS_DIR`, `AUTOSAVE_DIR`, `MAX_AUTOSAVES_PER_TAB`, system prompt presets dict. Move to `amplifier_tui/constants.py`.

### 1.4 Create `widgets/__init__.py`

```python
"""Amplifier TUI widget classes."""

from .datamodels import TabState, Attachment
from .messages import UserMessage, ThinkingStatic, AssistantMessage, ThinkingBlock, MessageMeta
from .chat_input import ChatInput
from .bars import SuggestionBar, HistorySearchBar, FindBar
from .indicators import ProcessingIndicator, ErrorMessage, SystemMessage, NoteMessage, FoldToggle
from .panels import PinnedPanelHeader, PinnedPanelItem, PinnedPanel
from .screens import ShortcutOverlay, HistorySearchScreen
from .tabs import TabButton, TabBar
from .commands import AmplifierCommandProvider

__all__ = [
    "TabState", "Attachment",
    "UserMessage", "ThinkingStatic", "AssistantMessage", "ThinkingBlock", "MessageMeta",
    "ChatInput",
    "SuggestionBar", "HistorySearchBar", "FindBar",
    "ProcessingIndicator", "ErrorMessage", "SystemMessage", "NoteMessage", "FoldToggle",
    "PinnedPanelHeader", "PinnedPanelItem", "PinnedPanel",
    "ShortcutOverlay", "HistorySearchScreen",
    "TabButton", "TabBar",
    "AmplifierCommandProvider",
]
```

### 1.5 Update app.py imports

Replace the 23 class definitions (lines 361-2058, ~1,700 lines) with:
```python
from .widgets import (
    TabState, Attachment,
    UserMessage, ThinkingStatic, AssistantMessage, ThinkingBlock, MessageMeta,
    ChatInput, SuggestionBar, HistorySearchBar, FindBar,
    ProcessingIndicator, ErrorMessage, SystemMessage, NoteMessage, FoldToggle,
    PinnedPanelHeader, PinnedPanelItem, PinnedPanel,
    ShortcutOverlay, HistorySearchScreen,
    TabButton, TabBar,
    AmplifierCommandProvider,
)
from .constants import SLASH_COMMANDS, AMPLIFIER_DIR, SESSIONS_DIR, AUTOSAVE_DIR, MAX_AUTOSAVES_PER_TAB
```

**Expected app.py reduction:** ~1,700 lines removed -> ~12,000 lines remaining.

### 1.6 Verification

```bash
# Ensure no import errors
python -c "from amplifier_tui.widgets import TabState, ChatInput, AmplifierCommandProvider"

# Ensure app still starts
python -m amplifier_tui

# Verify no class definitions remain in app.py (only AmplifierChicApp)
grep -c "^class " amplifier_tui/app.py
# Expected: 1

# Pyright check
pyright amplifier_tui/
```

---

## Phase 2: Extract Command Handlers

**Scope:** Move 88 `_cmd_*` methods out of `AmplifierChicApp` into domain-grouped mixin classes.
**Pattern:** Python mixin classes that `AmplifierChicApp` inherits from. Each mixin is a plain class with methods that reference `self` (which will be the App instance at runtime).
**Estimated effort:** 4-6 hours

### 2.1 Why mixins (not a registry)

The 88 command handlers deeply reference `self` for state access (`self._add_system_message`, `self._prefs`, `self.session_manager`, `self._tabs`, etc.). A registry pattern would require passing the app instance everywhere or heavyweight refactoring. Mixins let us move methods verbatim with zero signature changes.

### 2.2 Create package structure

```
amplifier_tui/
  commands/
    __init__.py              (~30 lines - re-exports all mixin classes)
    _base.py                 (~30 lines - CommandMixin protocol/base)
    session_cmds.py          (~500 lines - session lifecycle commands)
    display_cmds.py          (~600 lines - UI display commands)
    content_cmds.py          (~700 lines - content manipulation commands)
    file_cmds.py             (~400 lines - file and run commands)
    persistence_cmds.py      (~800 lines - bookmark, pin, note, draft, snippet, template, ref, alias commands)
    search_cmds.py           (~500 lines - search, grep, find commands)
    git_cmds.py              (~350 lines - git and diff commands)
    theme_cmds.py            (~500 lines - theme and colors commands)
    token_cmds.py            (~400 lines - token, stats, info, context commands)
    export_cmds.py           (~400 lines - export and naming commands)
    split_cmds.py            (~450 lines - split view commands)
    watch_cmds.py            (~250 lines - file watch commands)
```

### 2.3 Mixin pattern

Each file follows this pattern:

```python
"""Session lifecycle commands."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # Any types needed only for annotations


class SessionCommandsMixin:
    """Mixin providing /sessions, /new, /clear, /fork, /delete, /sort commands."""

    def _cmd_new(self) -> None:
        ...  # method body unchanged, uses self.*

    def _cmd_clear(self) -> None:
        ...
```

### 2.4 Command-to-file mapping

**`session_cmds.py`** - `SessionCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_new` | 6784 | |
| `_cmd_clear` | 6780 | |
| `_cmd_sessions` | 6788 | Large method with sub-commands |
| `_cmd_fork` | 6715 | |
| `_cmd_delete` | 12003 | Two-step confirmation |
| `_cmd_sort` | 11974 | |
| `_cmd_quit` | 7396 | |
| `_sessions_search` | 6957 | Helper for /sessions search |
Also moves: `_load_session_list`, `_load_sessions_worker` (lines 4102-4115)

**`display_cmds.py`** - `DisplayCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_compact` | 7400 | |
| `_cmd_focus` | 9196 | |
| `_cmd_scroll` | 9327 | |
| `_cmd_timestamps` | 9403 | |
| `_cmd_wrap` | 9445 | |
| `_cmd_stream` | 9473 | |
| `_cmd_fold` | 9506 | |
| `_cmd_unfold` | 9561 | |
| `_cmd_suggest` | 7521 | |
| `_cmd_progress` | 7558 | |
| `_cmd_multiline` | 7469 | |
| `_cmd_vim` | 7432 | |
Also moves: fold helpers (`_fold_last_message`, `_unfold_last_message`, `_fold_all_messages`, `_unfold_all_messages`, `_toggle_fold_all`, `_toggle_fold_nearest`, `_toggle_fold_nth` - lines 9579-9666)

**`content_cmds.py`** - `ContentCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_copy` | 9219 | |
| `_cmd_history` | 9668 | |
| `_cmd_redo` | 9722 | |
| `_cmd_retry` | 9791 | |
| `_cmd_undo` | 9848 | |
| `_cmd_system` | 3443 | System prompt management |
| `_cmd_autosave` | 3555 | |
| `_cmd_mode` | 7598 | Planning/research/review/debug modes |
| `_cmd_attach` | 5739 | |
| `_cmd_cat` | 5891 | |

**`file_cmds.py`** - `FileCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_run` | 5506 | Shell command execution |
| `_cmd_include` | 5616 | File include |
| `_cmd_editor` | 5038 | External editor |
| `_cmd_notify` | 9331 | |
| `_cmd_sound` | 9376 | |

**`persistence_cmds.py`** - `PersistenceCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_bookmark` | 12125 | |
| `_cmd_bookmarks` | 12162 | |
| `_cmd_pin_msg` | 11778 | |
| `_cmd_pin_session` | 11746 | |
| `_cmd_pins` | 11840 | |
| `_cmd_unpin` | 11868 | |
| `_cmd_note` | 11881 | |
| `_cmd_draft` | 6526 | |
| `_cmd_drafts` | 6587 | |
| `_cmd_snippet` | 6029 | |
| `_cmd_snippet_save` | 6182 | |
| `_cmd_snippet_use` | 6212 | |
| `_cmd_snippet_search` | 6240 | |
| `_cmd_snippet_cat` | 6268 | |
| `_cmd_snippet_tag` | 6289 | |
| `_cmd_snippet_export` | 6312 | |
| `_cmd_snippet_import` | 6327 | |
| `_cmd_template` | 6410 | |
| `_cmd_alias` | 5933 | |
| `_cmd_ref` | 3780 | |

**`search_cmds.py`** - `SearchCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_search` | 8358 | |
| `_cmd_grep` | 8623 | |
| `_cmd_find` | 4757 | |
Also moves: search helpers (`_search_current_chat`, `_search_open_result`, `_search_all_sessions_worker` - lines 8391-8700)

**`git_cmds.py`** - `GitCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_git` | 8787 | |
| `_cmd_diff` | 8949 | |
| `_cmd_diff_msgs` | 9087 | |
Also moves: git helpers (`_run_git`, `_git_overview`, `_git_status`, `_git_log`, `_git_diff_summary`, `_git_branches`, `_git_stashes`, `_git_blame` - lines 8702-8948)

**`theme_cmds.py`** - `ThemeCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_theme` | 10853 | |
| `_cmd_theme_preview` | 10974 | |
| `_cmd_colors` | 11052 | |
| `_cmd_colors_presets` | 11173 | |
| `_cmd_colors_use_preset` | 11198 | |

**`token_cmds.py`** - `TokenCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_stats` | 10047 | |
| `_cmd_stats_tools` | 10212 | |
| `_cmd_stats_tokens` | 10242 | |
| `_cmd_stats_time` | 10309 | |
| `_cmd_info` | 10519 | |
| `_cmd_tokens` | 10618 | |
| `_cmd_context` | 10703 | |
| `_cmd_showtokens` | 10776 | |
| `_cmd_contextwindow` | 10798 | |
| `_cmd_keys` | 10043 | |

**`export_cmds.py`** - `ExportCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_export` | 11462 | |
| `_cmd_title` | 11630 | |
| `_cmd_rename` | 11657 | |
| `_cmd_name` | 11687 | |
Also moves: export helpers (`_get_export_metadata`, `_export_markdown`, `_export_text`, `_export_json`, `_export_html` - lines 11227-11460)

**`split_cmds.py`** - `SplitCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_split` | 7687 | |
| `_cmd_tab` | 6640 | |
Also moves: split/tab helpers (`_open_split_pins`, `_open_split_chat`, `_open_split_file`, `_close_split`, `_enter_tab_split`, `_exit_tab_split`, `_swap_tab_split`, `_switch_split_pane`, `_update_split_active_indicator` - lines 7784-8136)

**`watch_cmds.py`** - `WatchCommandsMixin`
| Method | Line | Notes |
|--------|------|-------|
| `_cmd_watch` | 8138 | |
Also moves: watch helpers (`_start_watch_timer`, `_stop_watch_timer`, `_check_watched_files` - lines 8235-8355)

### 2.5 Update `_handle_slash_command`

The dispatch dict at line 5281 stays in `app.py` (it's the router). No changes needed since the mixin methods become methods on `self` via inheritance.

### 2.6 Update `AmplifierChicApp` class declaration

```python
# BEFORE
class AmplifierChicApp(App):

# AFTER
from .commands import (
    SessionCommandsMixin,
    DisplayCommandsMixin,
    ContentCommandsMixin,
    FileCommandsMixin,
    PersistenceCommandsMixin,
    SearchCommandsMixin,
    GitCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    ExportCommandsMixin,
    SplitCommandsMixin,
    WatchCommandsMixin,
)

class AmplifierChicApp(
    SessionCommandsMixin,
    DisplayCommandsMixin,
    ContentCommandsMixin,
    FileCommandsMixin,
    PersistenceCommandsMixin,
    SearchCommandsMixin,
    GitCommandsMixin,
    ThemeCommandsMixin,
    TokenCommandsMixin,
    ExportCommandsMixin,
    SplitCommandsMixin,
    WatchCommandsMixin,
    App,
):
```

### 2.7 `_cmd_help` and `_cmd_prefs` stay in app.py

`_cmd_help` (line 5377) prints a long help string that lists all commands - it's a cross-cutting concern and stays in app.py. `_cmd_prefs` (line 7206) and `_cmd_model` (line 7229) are tightly coupled to app initialization and stay in app.py.

Remaining commands in app.py: `_cmd_help`, `_cmd_prefs`, `_cmd_model`, `_cmd_model_show`, `_cmd_model_list`, `_cmd_model_set`, `_handle_slash_command`.

### 2.8 Verification

```bash
# Count methods - should show ~88 fewer in app.py
grep -c "def _cmd_" amplifier_tui/app.py
# Expected: ~7 (help, prefs, model*)

# Each mixin should have its commands
grep -c "def _cmd_" amplifier_tui/commands/*.py

# Type check
pyright amplifier_tui/

# Run the app and test commands:
# /help, /sessions, /theme dark, /stats, /export md, /git status
python -m amplifier_tui
```

**Expected app.py reduction:** ~5,500 lines removed -> ~6,500 lines remaining.

---

## Phase 3: Extract Persistence Layer

**Scope:** Move load/save methods and their associated state into dedicated persistence modules. Each module owns its file path, data structure, and load/save logic.
**Estimated effort:** 3-4 hours

### 3.1 Create package structure

```
amplifier_tui/
  persistence/
    __init__.py          (~40 lines - re-exports all stores)
    _base.py             (~60 lines - JsonStore base class)
    bookmarks.py         (~80 lines)
    pins.py              (~80 lines - message pins)
    pinned_sessions.py   (~60 lines)
    notes.py             (~60 lines)
    snippets.py          (~120 lines - includes DEFAULT_SNIPPETS)
    aliases.py           (~60 lines)
    templates.py         (~80 lines - includes DEFAULT_TEMPLATES)
    refs.py              (~80 lines)
    drafts.py            (~120 lines - includes crash draft)
    session_names.py     (~80 lines - names and titles)
```

### 3.2 Base class pattern

```python
"""Base JSON persistence store."""
from __future__ import annotations
import json
from pathlib import Path


class JsonStore:
    """Simple JSON file store with atomic write."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict | list:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return self._default()

    def save(self, data: dict | list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _default(self) -> dict | list:
        return {}
```

### 3.3 Method-to-module mapping

**`bookmarks.py`** - `BookmarkStore(JsonStore)`
| Method to extract | Line | Becomes |
|-------------------|------|---------|
| `_load_bookmarks` | 3714 | `BookmarkStore.load_all()` |
| `_save_bookmark` | 3723 | `BookmarkStore.add(session_id, bookmark)` |
| `_load_session_bookmarks` | 3732 | `BookmarkStore.for_session(session_id)` |
| `_save_session_bookmarks` | 12353 | `BookmarkStore.save_for_session(session_id)` |

State moved out of App: `self._session_bookmarks`, `self._bookmark_cursor`

**`pins.py`** - `MessagePinStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_message_pins` | 3892 | `MessagePinStore.load()` |
| `_save_message_pins` | 3903 | `MessagePinStore.save()` |

State: `self._message_pins`

**`pinned_sessions.py`** - `PinnedSessionStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_pinned_sessions` | 3078 | `PinnedSessionStore.load()` |
| `_save_pinned_sessions` | 3088 | `PinnedSessionStore.save()` |

State: `self._pinned_sessions`

**`notes.py`** - `NoteStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_notes` | 3926 | `NoteStore.load()` |
| `_save_notes` | 3937 | `NoteStore.save()` |

State: `self._session_notes`

**`snippets.py`** - `SnippetStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_snippets` | 3127 | `SnippetStore.load()` |
| `_save_snippets` | 3176 | `SnippetStore.save()` |

State: `self._snippets`. Also takes `DEFAULT_SNIPPETS` constant.

**`aliases.py`** - `AliasStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_aliases` | 3106 | `AliasStore.load()` |
| `_save_aliases` | 3115 | `AliasStore.save()` |

State: `self._aliases`

**`templates.py`** - `TemplateStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_templates` | 3188 | `TemplateStore.load()` |
| `_save_templates` | 3206 | `TemplateStore.save()` |

State: `self._templates`. Also takes `DEFAULT_TEMPLATES` constant.

**`refs.py`** - `RefStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_all_refs` | 3751 | `RefStore.load_all()` |
| `_save_refs` | 3760 | `RefStore.save()` |
| `_load_session_refs` | 3773 | `RefStore.for_session(session_id)` |
| `_export_refs` | 3862 | `RefStore.export()` |

State: `self._session_refs`

**`drafts.py`** - `DraftStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_drafts` | 3218 | `DraftStore.load()` |
| `_save_draft` | 3240 | `DraftStore.save_for_tab(tab_id, content)` |
| `_save_crash_draft` | 3675 | `DraftStore.save_crash(content)` |
| `_load_crash_draft` | 3696 | `DraftStore.load_crash()` |

State: crash draft path

**`session_names.py`** - `SessionNameStore(JsonStore)`
| Method | Line | Becomes |
|--------|------|---------|
| `_load_session_names` | 2966 | `SessionNameStore.load_names()` |
| `_save_session_name` | 2975 | `SessionNameStore.save_name()` |
| `_load_session_titles` | 3035 | `SessionNameStore.load_titles()` |
| `_save_session_title` | 3044 | `SessionNameStore.save_title()` |
| `_load_session_title_for` | 3065 | `SessionNameStore.title_for(session_id)` |

### 3.4 Update App initialization

In `AmplifierChicApp.__init__`, replace raw state with store instances:

```python
# BEFORE (scattered across __init__)
self._aliases: dict[str, str] = {}
self._snippets: dict[str, dict[str, str]] = {}
# ... load calls scattered through on_mount

# AFTER
from .persistence import (
    BookmarkStore, MessagePinStore, PinnedSessionStore,
    NoteStore, SnippetStore, AliasStore, TemplateStore,
    RefStore, DraftStore, SessionNameStore,
)

self._bookmark_store = BookmarkStore()
self._pin_store = MessagePinStore()
# ... etc.
self._aliases = self._alias_store.load()
```

### 3.5 Update command mixins

The persistence command mixin methods (from Phase 2) will need to call store methods instead of the old `_load_*`/`_save_*` methods. Example:

```python
# BEFORE (in _cmd_alias)
self._aliases = self._load_aliases()

# AFTER
self._aliases = self._alias_store.load()
```

### 3.6 Verification

```bash
# Unit test each store independently
python -c "
from amplifier_tui.persistence import AliasStore
store = AliasStore()
data = store.load()
print(f'Loaded {len(data)} aliases')
"

# Full app smoke test
python -m amplifier_tui
# Test: /alias test echo hello, /aliases, /snippet list, /bookmarks

# Pyright
pyright amplifier_tui/
```

**Expected app.py reduction:** ~400 lines of load/save methods removed -> ~6,100 lines remaining.

---

## Phase 4: Extract Feature Modules

**Scope:** Move self-contained feature clusters into their own modules. These are groups of methods + state that form coherent features.
**Estimated effort:** 3-4 hours

### 4.1 Create modules

```
amplifier_tui/
  features/
    __init__.py              (~20 lines)
    split_view.py            (~450 lines)
    file_watch.py            (~200 lines)
    search.py                (~400 lines - find-in-chat + cross-session search)
    git_integration.py       (~300 lines)
    export.py                (~350 lines)
    notifications.py         (~120 lines)
    reverse_search.py        (~200 lines)
    tab_manager.py           (~350 lines)
```

### 4.2 Module-to-method mapping

**`split_view.py`** - `SplitViewManager`
| Method | Line | State Managed |
|--------|------|---------------|
| `_open_split_pins` | 7784 | `_tab_split_mode` |
| `_open_split_chat` | 7833 | `_tab_split_left_index` |
| `_open_split_file` | 7868 | `_tab_split_right_index` |
| `_close_split` | 7907 | `_tab_split_active` |
| `_enter_tab_split` | 7919 | |
| `_exit_tab_split` | 7977 | |
| `_swap_tab_split` | 8030 | |
| `_switch_split_pane` | 8077 | |
| `_update_split_active_indicator` | 8117 | |

Pattern: Can be a mixin or a helper class that takes `app` reference.

**`file_watch.py`** - `FileWatcher`
| Method | Line | State Managed |
|--------|------|---------------|
| `_start_watch_timer` | 8235 | `_watched_files` |
| `_stop_watch_timer` | 8240 | `_watch_timer` |
| `_check_watched_files` | 8246 | |

Self-contained: manages its own timer and file dict. Good candidate for a helper class:
```python
class FileWatcher:
    def __init__(self, app: App) -> None:
        self.app = app
        self.watched_files: dict[str, dict] = {}
        self._timer: Timer | None = None
```

**`search.py`** - `SearchManager`
| Method | Line | State Managed |
|--------|------|---------------|
| `_find_execute_search` | 4659 | `_find_visible`, `_find_matches` |
| `_find_next` | 4685 | `_find_index`, `_find_case_sensitive` |
| `_find_prev` | 4693 | `_find_highlighted` |
| `_find_scroll_to_current` | 4701 | |
| `_find_update_counter` | 4722 | |
| `_find_clear_highlights` | 4733 | |
| `_find_toggle_case` | 4743 | |
| `_search_current_chat` | 8391 | `_last_search_results` |
| `_search_open_result` | 8435 | |
| `_search_all_sessions_worker` | 8455 | |

**`git_integration.py`** - `GitHelper`
| Method | Line | Notes |
|--------|------|-------|
| `_run_git` | 8702 | Static utility |
| `_git_overview` | 8819 | |
| `_git_status` | 8867 | |
| `_git_log` | 8875 | |
| `_git_diff_summary` | 8890 | |
| `_git_branches` | 8912 | |
| `_git_stashes` | 8920 | |
| `_git_blame` | 8931 | |

Stateless: all methods are pure helpers that run git commands and format output. Good candidate for standalone functions.

**`export.py`** - `ExportManager`
| Method | Line | Notes |
|--------|------|-------|
| `_get_export_metadata` | 11227 | |
| `_export_markdown` | 11245 | |
| `_export_text` | 11296 | |
| `_export_json` | 11321 | |
| `_export_html` | 11374 | |

Mostly stateless: take message lists, return strings. Can be pure functions.

**`notifications.py`** - `NotificationManager`
| Method | Line | Notes |
|--------|------|-------|
| `_maybe_send_notification` | 12884 | |
| `_send_terminal_notification` | 12900 | Static method |
| `_notify_sound` | 12964 | |

**`reverse_search.py`** - `ReverseSearchManager`
| Method | Line | State Managed |
|--------|------|---------------|
| `_handle_rsearch_key` | 4481 | `_rsearch_active`, `_rsearch_query` |
| `_rsearch_cycle_next` | 4523 | `_rsearch_matches`, `_rsearch_match_idx` |
| `_rsearch_cycle_prev` | 4539 | `_rsearch_original` |
| `_do_rsearch` | 4555 | |
| `_rsearch_cancel` | 4578 | |
| `_rsearch_accept` | 4586 | |
| `_update_rsearch_display` | 4591 | |
| `_clear_rsearch_display` | 4613 | |

**`tab_manager.py`** - `TabManager`
| Method | Line | State Managed |
|--------|------|---------------|
| `_update_tab_bar` | 2544 | `_tabs`, `_active_tab_index` |
| `_update_tab_indicator` | 2560 | `_tab_counter` |
| `_save_current_tab_state` | 2577 | |
| `_load_tab_state` | 2609 | |
| `_switch_to_tab` | 2635 | |
| `_create_new_tab` | 2699 | |
| `_close_tab` | 2790 | |
| `_rename_tab` | 2849 | |
| `_find_tab_by_name_or_index` | 2856 | |
| `_reset_tab_state` | 907 (in ChatInput, stays) | |

### 4.3 Integration pattern

Feature modules that are stateless (git, export) become standalone functions:
```python
# In git_cmds.py mixin:
from ..features.git_integration import run_git, git_overview
```

Feature modules with state become helper objects initialized in `__init__`:
```python
self._file_watcher = FileWatcher(self)
self._search = SearchManager(self)
```

### 4.4 Verification

```bash
# Test each feature module can be imported
python -c "from amplifier_tui.features.git_integration import run_git"
python -c "from amplifier_tui.features.export import export_markdown"

# Full app test - each feature:
# /split pins, /watch somefile.py, Ctrl+F search, /git status, /export md
python -m amplifier_tui

# Pyright
pyright amplifier_tui/
```

**Expected app.py reduction:** ~2,500 lines removed -> ~3,600 lines remaining.

---

## Phase 5: Error Handling Cleanup

**Fixes bug:** #13 (144 bare `except Exception: pass` clauses)
**Scope:** Replace bare excepts with specific types and add logging.
**Estimated effort:** 3-4 hours

### 5.1 Add logging infrastructure

Create `amplifier_tui/log.py` (~15 lines):
```python
"""Logging configuration for Amplifier TUI."""
import logging

logger = logging.getLogger("amplifier_tui")
```

### 5.2 Categorize the 144 bare excepts

Run analysis to categorize:
```bash
grep -n "except Exception" amplifier_tui/app.py | head -20
```

Expected categories:
| Category | Count (est.) | Correct Exception Type |
|----------|-------------|----------------------|
| File I/O (JSON load/save) | ~40 | `(OSError, json.JSONDecodeError)` |
| Subprocess/git calls | ~10 | `(subprocess.SubprocessError, OSError)` |
| Clipboard operations | ~5 | `OSError` |
| Textual widget queries | ~20 | `(NoMatches, QueryError)` from textual |
| String/regex parsing | ~15 | `(ValueError, IndexError, re.error)` |
| Session manager calls | ~15 | `(AttributeError, RuntimeError)` |
| Notification/sound | ~5 | `OSError` |
| Catch-all safety nets | ~34 | Keep as `Exception` but add `logger.debug()` |

### 5.3 Replacement pattern

```python
# BEFORE
try:
    data = json.loads(path.read_text())
except Exception:
    pass

# AFTER
try:
    data = json.loads(path.read_text())
except (OSError, json.JSONDecodeError):
    logger.debug("Failed to load %s", path, exc_info=True)
```

For the ~34 cases that genuinely need broad catching (safety nets around entire features), keep `except Exception` but add logging:
```python
except Exception:
    logger.debug("Unexpected error in %s", feature_name, exc_info=True)
```

### 5.4 Verification

```bash
# Count remaining bare excepts (should be ~34 intentional ones, all with logging)
grep -c "except Exception:" amplifier_tui/**/*.py

# Verify logging works
AMPLIFIER_TUI_DEBUG=1 python -m amplifier_tui 2>debug.log
# Trigger some errors, check debug.log has entries

# Pyright
pyright amplifier_tui/
```

---

## Phase 6: Test Infrastructure

**Scope:** Create test framework and unit tests for each extracted module.
**Estimated effort:** 4-6 hours

### 6.1 Test structure

```
tests/
  __init__.py
  conftest.py                  (~100 lines - Textual Pilot fixtures, tmp dirs)
  test_persistence/
    __init__.py
    test_bookmarks.py          (~60 lines)
    test_pins.py               (~40 lines)
    test_snippets.py           (~80 lines)
    test_aliases.py            (~40 lines)
    test_templates.py          (~60 lines)
    test_drafts.py             (~60 lines)
    test_refs.py               (~50 lines)
    test_notes.py              (~40 lines)
    test_session_names.py      (~50 lines)
  test_features/
    __init__.py
    test_export.py             (~80 lines)
    test_git_integration.py    (~60 lines)
    test_notifications.py      (~40 lines)
  test_widgets/
    __init__.py
    test_datamodels.py         (~60 lines - TabState, Attachment)
    test_chat_input.py         (~80 lines - Textual Pilot)
  test_app_smoke.py            (~60 lines - app starts, basic commands)
```

### 6.2 conftest.py fixtures

```python
"""Shared test fixtures for Amplifier TUI."""
import pytest
from pathlib import Path
from textual.pilot import Pilot


@pytest.fixture
def tmp_amplifier_dir(tmp_path: Path) -> Path:
    """Create a temporary .amplifier directory for persistence tests."""
    amp_dir = tmp_path / ".amplifier"
    amp_dir.mkdir()
    return amp_dir


@pytest.fixture
def app():
    """Create an AmplifierChicApp instance for testing."""
    from amplifier_tui.app import AmplifierChicApp
    return AmplifierChicApp()


@pytest.fixture
async def pilot(app):
    """Create a Textual Pilot for integration testing."""
    async with app.run_test() as pilot:
        yield pilot
```

### 6.3 Persistence tests pattern

```python
"""Tests for bookmark persistence."""
from amplifier_tui.persistence.bookmarks import BookmarkStore


def test_load_empty(tmp_amplifier_dir):
    store = BookmarkStore(tmp_amplifier_dir / "bookmarks.json")
    assert store.load() == {}


def test_save_and_load(tmp_amplifier_dir):
    store = BookmarkStore(tmp_amplifier_dir / "bookmarks.json")
    store.add("session-1", {"text": "hello", "index": 0})
    bookmarks = store.for_session("session-1")
    assert len(bookmarks) == 1
    assert bookmarks[0]["text"] == "hello"
```

### 6.4 Feature tests pattern

```python
"""Tests for export functions."""
from amplifier_tui.features.export import export_markdown, export_json


def test_export_markdown_empty():
    result = export_markdown([])
    assert "# Chat Export" in result


def test_export_json_messages():
    messages = [("user", "hello", None), ("assistant", "hi", None)]
    result = export_json(messages)
    import json
    data = json.loads(result)
    assert len(data["messages"]) == 2
```

### 6.5 Add test dependencies to pyproject.toml

```toml
[project.optional-dependencies]
test = ["pytest>=7.0", "pytest-asyncio>=0.21"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 6.6 Verification

```bash
# Run all tests
pytest tests/ -v

# Coverage report
pytest tests/ --cov=amplifier_tui --cov-report=term-missing
```

---

## Final State

### File structure after all phases

```
amplifier_tui/
  __init__.py
  __main__.py
  app.py                     (~3,600 lines - core App class, compose, on_mount, streaming, message handling)
  constants.py               (~200 lines - SLASH_COMMANDS, paths, defaults)
  history.py                 (unchanged)
  preferences.py             (unchanged)
  session_manager.py         (unchanged)
  transcript_loader.py       (unchanged)
  theme.py                   (unchanged)
  log.py                     (~15 lines)
  styles.tcss                (unchanged)
  widgets/
    __init__.py
    datamodels.py
    messages.py
    chat_input.py
    bars.py
    indicators.py
    panels.py
    screens.py
    tabs.py
    commands.py
  commands/
    __init__.py
    session_cmds.py
    display_cmds.py
    content_cmds.py
    file_cmds.py
    persistence_cmds.py
    search_cmds.py
    git_cmds.py
    theme_cmds.py
    token_cmds.py
    export_cmds.py
    split_cmds.py
    watch_cmds.py
  persistence/
    __init__.py
    _base.py
    bookmarks.py
    pins.py
    pinned_sessions.py
    notes.py
    snippets.py
    aliases.py
    templates.py
    refs.py
    drafts.py
    session_names.py
  features/
    __init__.py
    split_view.py
    file_watch.py
    search.py
    git_integration.py
    export.py
    notifications.py
    reverse_search.py
    tab_manager.py
tests/
  conftest.py
  test_persistence/
  test_features/
  test_widgets/
  test_app_smoke.py
```

### Line count summary

| Component | Lines | % of original |
|-----------|-------|---------------|
| `app.py` (core) | ~3,600 | 26% |
| `constants.py` | ~200 | 1% |
| `widgets/` (10 files) | ~1,500 | 11% |
| `commands/` (13 files) | ~5,500 | 40% |
| `persistence/` (12 files) | ~800 | 6% |
| `features/` (9 files) | ~2,400 | 17% |
| `log.py` | ~15 | <1% |
| **Total** | **~14,015** | ~102% (slight growth from imports/headers) |

### What remains in app.py (~3,600 lines)

- `AmplifierChicApp` class declaration with mixin inheritance
- `__init__` (instance variables that aren't owned by persistence stores)
- `compose()` - UI layout
- `on_mount()` - startup logic
- `_handle_slash_command()` - command dispatch router
- `_cmd_help`, `_cmd_prefs`, `_cmd_model*` - tightly coupled commands
- `_send_message_worker()` and streaming callbacks (~10 methods)
- Textual event handlers (`on_key`, `on_input_changed`, etc.)
- `action_*` methods that are simple one-liners delegating to commands
- Status bar, scrolling, and core UI state methods

### Bugs resolved

| Bug | Phase | Resolution |
|-----|-------|------------|
| #10 | Phase 0 | `session_manager: SessionManager \| None` |
| #11 | Phase 0 | Timers typed as `Timer \| None` |
| #14 | Phase 0 | Null guards on all 15 accesses |
| #15 | Phase 0 + all | Pyright errors reduced incrementally |
| #13 | Phase 5 | 144 bare excepts replaced with specific types + logging |
| #16 | Phase 1-4 | God file decomposed into 44 focused files |

### Execution order and dependencies

```
Phase 0 (types)  ─── no dependencies, do first
    │
Phase 1 (widgets) ── depends on Phase 0 (uses fixed types in TabState)
    │
Phase 2 (commands) ─ depends on Phase 1 (imports from widgets/)
    │
Phase 3 (persistence) ─ depends on Phase 2 (command mixins call stores)
    │
Phase 4 (features) ── depends on Phase 2+3 (command mixins use feature modules)
    │
Phase 5 (errors) ──── can run after any phase, best after Phase 4
    │
Phase 6 (tests) ───── depends on Phase 3+4 (tests persistence + features)
```

Each phase produces a single commit. Phases 0-1 are low-risk. Phase 2 is the highest-effort phase. Phases 3-4 are medium-risk and can be done incrementally (one module at a time).
