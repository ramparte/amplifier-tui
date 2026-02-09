# amplifier-tui Manual Test Plan

**Generated**: 2026-02-08
**Source**: 139 commits from session 653a396c
**App file**: amplifier_tui/app.py (13,712 lines, 25 classes, 76+ slash commands, 38 keybindings)

## Testing Infrastructure

### Available Tools
- **Headless capture**: `tools/tui_capture.py` (Textual Pilot, exports SVG+PNG)
- **SVG parser**: `tools/svg_parser.py` (text extraction, layout analysis, message detection)
- **Image analyzer**: `tools/tui_analyze.py` (color palette, layout bands, sidebar detection)
- **Pipeline script**: `tools/ux_test.sh --mock-chat` (runs all three)

### Test Environment
- Run via shadow environment for isolation
- Use `--mock-chat` flag for pre-populated conversation state
- SVG analysis provides structured YAML for automated assertions
- Manual inspection via SVG/PNG for visual correctness

### Severity Definitions
- **P0 - Critical**: App crashes, data loss, session corruption
- **P1 - Major**: Feature completely broken, no workaround
- **P2 - Moderate**: Feature partially broken, workaround exists
- **P3 - Minor**: Cosmetic issues, rough edges, polish needed

---

## Category 1: App Launch & Core Lifecycle

### T1.1 - App Startup
- [ ] App launches without errors: `python -m amplifier_tui`
- [ ] Initial UI renders: sidebar, chat area, input box, status bar visible
- [ ] Session list loads in sidebar
- [ ] Status bar shows model name and context info
- [ ] No Python tracebacks in terminal output

### T1.2 - Session Creation
- [ ] `/new` creates a new session
- [ ] New session appears in sidebar
- [ ] Chat area clears for new session
- [ ] Session auto-titles from first message (commit ed3b7b5)
- [ ] Smart auto-titles strip filler words (commit ff95b08)

### T1.3 - Session Resume
- [ ] Clicking existing session in sidebar resumes it
- [ ] Previous messages load and display correctly
- [ ] Transcript file existence verified before resume (commit c729173)
- [ ] Message types render distinctly (user/assistant/thinking/tool)
- [ ] Timestamps preserved from original messages (commit 1b5443e)

### T1.4 - Session Quit & Persistence
- [ ] Ctrl+Q exits cleanly
- [ ] `/quit` exits cleanly
- [ ] Session state persisted on quit (commit 76ebb5b)
- [ ] No data loss on exit
- [ ] Draft input preserved for crash recovery (commit a68b395, 4740488)

### T1.5 - Session Delete
- [ ] `/delete` prompts two-step confirmation (commit 832de56)
- [ ] Confirming deletes session from sidebar
- [ ] Canceling preserves session
- [ ] Cannot accidentally delete without confirmation

---

## Category 2: Message Display & Rendering

### T2.1 - Message Type Distinction
- [ ] User messages render in orange/gold color (commit 5e853fd)
- [ ] Assistant messages render in blue with markdown (commit 634)
- [ ] Thinking blocks render in gray/italic (commit 94feb9e)
- [ ] Tool output renders with descriptive collapsible titles (commit 5f043c9)
- [ ] Error messages render distinctly (commit 1402)
- [ ] System messages render for slash command output (commit 1408)

### T2.2 - Markdown Rendering
- [ ] Code blocks render with syntax highlighting (commit 05956ee)
- [ ] Bold, italic, lists render correctly
- [ ] Inline code renders with background
- [ ] Links render and are distinguishable
- [ ] Nested markdown elements render correctly

### T2.3 - Streaming Display
- [ ] Tokens stream progressively as they arrive (commit ae0b069, 9125186)
- [ ] Progressive markdown rendering during stream (commit ae0b069)
- [ ] `/stream` toggle controls streaming behavior
- [ ] No visual artifacts during streaming

### T2.4 - Message Timestamps
- [ ] Timestamps display on messages (commit eac9368)
- [ ] Relative timestamps ("2m ago") with live updates (commit 59bc385)
- [ ] `/ts` toggles timestamp display
- [ ] Date-aware timestamps with persistence (commit 1b5443e)
- [ ] Rich metadata with response time display (commit 4c319ee)

### T2.5 - Message Folding
- [ ] Long messages auto-fold (commit ef17cd9)
- [ ] Click fold toggle to expand/collapse
- [ ] `/fold` toggles all messages
- [ ] `/fold N` sets fold threshold (commit 7712b2a -> 7d10bff)
- [ ] `/unfold` expands all messages (commit 940f787)
- [ ] Vim `z` commands for folding (commit 940f787)
- [ ] Visual fold indicators present (commit 940f787)
- [ ] Persistent fold threshold preference (commit 7d10bff)

### T2.6 - Auto-Scroll
- [ ] Chat auto-scrolls to latest message
- [ ] Ctrl+A toggles auto-scroll (commit 025b16c)
- [ ] Smart pause: scrolling up pauses auto-scroll
- [ ] Scrolling to bottom re-enables auto-scroll

---

## Category 3: Input & Editing

### T3.1 - Basic Input
- [ ] Text input works in input area
- [ ] Enter submits message (commit 7b937dc)
- [ ] No crash on Enter key when Key lacks .shift attribute (regression commit ba488a2)
- [ ] Shift+Enter for newline (commit 1cced41)
- [ ] Multiline input with Alt+M toggle (commit cce9f33)
- [ ] `/multiline` command toggles mode
- [ ] Input border shows word/character count (commit 217c113, bc08e2e)
- [ ] Cursor position indicator for multi-line (commit 2a6226c)

### T3.2 - Prompt History
- [ ] Up/Down arrows browse history (commit 6695fdf)
- [ ] Ctrl+R opens reverse search (commit 3d1c7bf, 9009d20)
- [ ] Dedicated search bar widget for Ctrl+R history search (commit 66a6b5a)
- [ ] Fuzzy filtering in history search
- [ ] Wrap-around cycling like bash/zsh (commit eb06bab)
- [ ] Ctrl+S forward search (commit a97c6c8)
- [ ] `/history search` subcommand (commit a97c6c8)

### T3.3 - External Editor
- [ ] Ctrl+G opens external editor (commit de12910)
- [ ] `/editor` command with options (commit 177c959)
- [ ] Editor fallback chain works (commit 0d39dd2)
- [ ] `/edit` alias works (commit 0d39dd2)
- [ ] Comment template in editor (commit 6be292c)
- [ ] `/editor submit` toggle for auto-send (commit 6be292c)

### T3.4 - Tab Completion
- [ ] Tab completes slash commands (commit 2b477da)
- [ ] @@snippet shorthand expands with tab (commit 1825045)
- [ ] Completion shows available options

### T3.5 - Prompt Stashing
- [ ] Ctrl+S stashes current prompt (commit c737c95)
- [ ] Stack of 5 stashes maintained
- [ ] Can pop stashed prompts back

### T3.6 - Smart Suggestions
- [ ] `/suggest` toggle controls suggestions (commit 6543e01)
- [ ] Suggestion bar shows contextual prompts
- [ ] History-based and template-based suggestions

---

## Category 4: Vim Mode

### T4.1 - Mode Switching
- [ ] `/vim on` enables vim mode (commit 2885889)
- [ ] `/vim off` disables vim mode
- [ ] Escape enters normal mode
- [ ] `i` enters insert mode
- [ ] Mode indicator visible in status area

### T4.2 - Normal Mode Navigation
- [ ] `h/j/k/l` cursor movement
- [ ] `w/b` word movement
- [ ] `gg` go to top
- [ ] `G` go to bottom
- [ ] `0` / `$` line start/end

### T4.3 - Normal Mode Editing
- [ ] `dd` delete line
- [ ] `yy` yank line
- [ ] `o/O` open line below/above
- [ ] `p` paste
- [ ] `x` delete character

### T4.4 - Vim Fold Commands
- [ ] `z` fold commands work (commit 940f787)
- [ ] Fold/unfold messages from normal mode

### T4.5 - Vim Bookmark Commands
- [ ] `'m` bookmark commands (commit 940f787)
- [ ] Navigate between bookmarks

---

## Category 5: Slash Commands - Session Management

### T5.1 - /help
- [ ] `/help` shows available commands (commit a94f67c)
- [ ] Output is organized and readable
- [ ] All 76+ slash commands listed in help output

### T5.2 - /clear
- [ ] `/clear` clears chat display
- [ ] Ctrl+L also clears (keybinding)

### T5.3 - /sessions
- [ ] `/sessions` lists all sessions
- [ ] `/sessions search <query>` filters sessions (commit f583b96)
- [ ] `/sessions recent` shows recent sessions
- [ ] `/sessions info` shows session details
- [ ] `/sessions open <id>` opens a session
- [ ] `/sessions delete <id>` deletes a session

### T5.4 - /name
- [ ] `/name <text>` sets friendly session name (commit b1bc020)
- [ ] Tab label updates to reflect name
- [ ] Name persists across restarts

### T5.5 - /fork
- [ ] `/fork` creates conversation branch in new tab (commit 0886442)
- [ ] Forked tab has conversation history up to fork point
- [ ] Original tab unaffected

### T5.6 - /undo and /redo
- [ ] `/undo` removes last chat exchange (commit 7b5eaaa)
- [ ] `/redo` re-sends previous message (commit 5a3c6d6, 84f1d38)
- [ ] `/retry` alias works for regeneration (commit 84f1d38)

### T5.7 - /info
- [ ] `/info` shows comprehensive session details (commit 8b2724d)
- [ ] Shows model, tokens used, message count, etc.

---

## Category 6: Slash Commands - Display & Navigation

### T6.1 - /focus
- [ ] `/focus` toggles focus mode (commit ad2d67b)
- [ ] F11 keybinding toggles focus mode
- [ ] Sidebar hides in focus mode (commit 64c1214)
- [ ] Sidebar state preserved when exiting focus (commit 64c1214)

### T6.2 - /compact
- [ ] `/compact` toggles dense view (commit a896f59)
- [ ] Messages render more tightly in compact mode

### T6.3 - /wrap
- [ ] `/wrap` toggles word wrap (commit 169c39c)
- [ ] Long lines wrap/truncate based on setting

### T6.4 - /search and /grep
- [ ] `/search <query>` searches across sessions (commit 1d7d829, 61b36a2)
- [ ] `/search here` searches current session (commit 1d7d829)
- [ ] `/search open` opens search result (commit 1d7d829)
- [ ] `/grep <pattern>` searches within conversation (commit 6508c4e)
- [ ] Ctrl+F opens find-in-chat bar (commit 649c70f)
- [ ] Real-time search with match navigation (commit 649c70f)
- [ ] `/find` alias works

### T6.5 - /sort
- [ ] `/sort date` sorts sidebar by date (commit 7c15bc8)
- [ ] `/sort name` sorts by name
- [ ] `/sort project` sorts by project
- [ ] Sort persists

---

## Category 7: Slash Commands - Content & Clipboard

### T7.1 - /copy
- [ ] `/copy` copies last assistant response (commit 3f58226)
- [ ] `/copy N` copies Nth message (commit a6cacf0)
- [ ] `/copy all` copies entire conversation (commit 18b617e)
- [ ] `/copy code` copies code blocks only (commit 18b617e)
- [ ] Ctrl+Y copies last response (commit 3f58226)
- [ ] Ctrl+Shift+C enhanced copy (commit ea814b8)
- [ ] Bottom-counting with negative indices (commit ea814b8)
- [ ] Preview feedback on copy (commit ea814b8)

### T7.2 - /export
- [ ] `/export` exports as markdown (default) (commit 562425a, 547f73b, 6f29405)
- [ ] `/export html` exports styled HTML (commit 789e9b7)
- [ ] `/export json` exports as JSON (commit 190817e)
- [ ] `/export txt` exports as plain text
- [ ] `/export last N` exports last N messages (commit 987f5cc)
- [ ] `/export clipboard` copies to clipboard (commit 547f73b)
- [ ] Exported files are readable and complete

### T7.3 - /snippet
- [ ] `/snippet save <name> <text>` saves snippet (commit 192c6e2)
- [ ] `/snippet use <name>` inserts snippet
- [ ] `/snippet search <query>` finds snippets (commit 2e183a3)
- [ ] `/snippet cat <name>` shows snippet content (commit 2e183a3)
- [ ] `/snippet tag` tags snippets (commit 2e183a3)
- [ ] `/snippet export/import` for portability (commit 2e183a3)
- [ ] `/snippet edit` modifies existing (commit 2e183a3)
- [ ] `/snippet clear-all` removes all (commit 1221bdf)
- [ ] `/snip` alias works (commit 0b15eb9)
- [ ] 10 built-in snippets with {placeholder} support (commit 0b15eb9)
- [ ] `/snippet send` inserts and sends (commit 1221bdf)
- [ ] Categories work (commit 2e183a3)

### T7.4 - /template
- [ ] `/template save <name> <text>` saves template (commit 9375983)
- [ ] `/template use <name>` inserts template
- [ ] `/template remove <name>` deletes template
- [ ] `/template list` shows all templates

### T7.5 - /alias
- [ ] `/alias <name> <command>` creates alias (commit d23a330)
- [ ] Using alias triggers mapped command
- [ ] `/alias remove <name>` removes alias (commit 4bea887)
- [ ] `/alias clear-all` removes all (commit 4bea887)
- [ ] Simpler syntax support (commit 4bea887)

---

## Category 8: Slash Commands - Files & Shell

### T8.1 - /include and @file
- [ ] `/include <path>` includes file content in prompt (commit c767646)
- [ ] `@file` syntax works inline in messages (commit c767646)
- [ ] File content appears in context

### T8.2 - /attach
- [ ] `/attach <path>` attaches file (commit f1e36b4)
- [ ] `/attach clear` removes attachments
- [ ] `/attach remove <name>` removes specific
- [ ] `/cat <path>` shows file contents (commit f1e36b4)

### T8.3 - /run and /!
- [ ] `/run <command>` executes shell command (commit e3a208b)
- [ ] `/! <command>` shorthand works (commit e3a208b)
- [ ] Output displays in chat

### T8.4 - /git
- [ ] `/git status` shows git status (commit 57659a6)
- [ ] `/git log` shows recent commits
- [ ] `/git diff` shows changes
- [ ] `/git branches` lists branches
- [ ] `/git stashes` lists stashes
- [ ] `/git blame <file>` shows blame

### T8.5 - /diff
- [ ] `/diff` shows git diff (commit 08dff44, 32b93fd)
- [ ] `/diff staged` shows staged changes
- [ ] `/diff all` shows all changes
- [ ] `/diff <file>` shows file-specific diff
- [ ] `/diff msgs` compares conversation messages (commit 194a14b)
- [ ] Color-coded inline diff viewing (commit 32b93fd)

---

## Category 9: Slash Commands - Theme & Colors

### T9.1 - /theme
- [ ] `/theme` shows current theme (commit 1105f85)
- [ ] `/theme <name>` switches theme
- [ ] Available themes: dark, light, solarized, gruvbox, catppuccin, midnight, solarized-light (commits 95bbac8, 7712b2a, 4039bdc, 5eb8c64)
- [ ] `/theme preview` shows color swatches (commit 4039bdc, 5eb8c64)
- [ ] `/theme revert` undoes last theme change (commit 5eb8c64)
- [ ] Custom themes supported (commit 5eb8c64)
- [ ] Theme persists across restarts

### T9.2 - /colors
- [ ] `/colors` shows current color settings (commit 6c5ecfd, ccd3a3b, 5378c37)
- [ ] `/colors set <key> <value>` changes a color (commit ccd3a3b)
- [ ] `/colors presets` lists color presets (commit ccd3a3b)
- [ ] `/colors use <preset>` applies preset (commit ccd3a3b)
- [ ] `/colors reset` restores defaults (commit ccd3a3b)
- [ ] User-configurable color preferences apply correctly (commit 523cc7e)
- [ ] Text color preferences with presets (commit c90e470)
- [ ] Note color theming (commit c90e470)
- [ ] Consistent 4-tier context color coding (commit d42701c)
- [ ] Orange tier in 4-tier context colors renders correctly (fix commit de650f8)

---

## Category 10: Slash Commands - Tokens & Stats

### T10.1 - /tokens and /context
- [ ] `/tokens` shows token usage (commit 6cef4ef)
- [ ] `/context` shows visual token usage bar (commit 336d2d9)
- [ ] Token display in status bar (commit a660faa)
- [ ] Per-message token updates (commit bed1db0)
- [ ] `/showtokens` preference toggle (commit e6b0b02)
- [ ] `/contextwindow` preference toggle (commit e6b0b02)
- [ ] Wider bar display (commit bed1db0)
- [ ] Persistent context fuel gauge in status bar (commit 34aa7b4)

### T10.2 - /stats
- [ ] `/stats` shows session statistics (commit ceb71aa, 0840ec2)
- [ ] `/stats tools` shows tool usage breakdown (commit 0d76e40)
- [ ] `/stats tokens` shows token analytics (commit 0d76e40)
- [ ] `/stats time` shows timing analytics (commit d6fd05e)
- [ ] Cost estimate included (commit d6fd05e)
- [ ] Top words analysis (commit d6fd05e)
- [ ] Response time tracking (commit 0840ec2)

---

## Category 11: Tabs & Split View

### T11.1 - Tab Management
- [ ] Ctrl+T creates new tab (commit 5dc6fdc)
- [ ] Ctrl+W closes current tab
- [ ] Ctrl+PageUp / Alt+Left switches to previous tab
- [ ] Ctrl+PageDown / Alt+Right switches to next tab
- [ ] Alt+1-9 switches to tab N (commit d42701c)
- [ ] Alt+0 switches to last tab
- [ ] `/tab new` creates tab
- [ ] `/tab close` closes tab
- [ ] `/tab goto N` switches to tab N
- [ ] `/tab list` shows all tabs
- [ ] Tab bar displays correctly (commit 1712)
- [ ] Tab status bar indicator (commit d42701c)

### T11.2 - Tab Renaming
- [ ] F2 renames current tab (commit 3298505)
- [ ] `/rename <name>` renames tab (commit 3298505, 9cb7fdc)
- [ ] Renamed label persists

### T11.3 - Split View
- [ ] `/split` enters split view (commit 6885b49, f7ba31d)
- [ ] `/split N` splits with specific tab
- [ ] `/split swap` swaps panes
- [ ] `/split off` exits split view
- [ ] `/split pins` shows pins in split
- [ ] `/split chat` shows chat in split
- [ ] `/split file <path>` shows file in split
- [ ] Side-by-side reference panel works (commit f7ba31d)

---

## Category 12: Bookmarks, Pins & Notes

### T12.1 - Bookmarks
- [ ] Ctrl+M bookmarks last message (commit d89e0f6)
- [ ] `/bookmark` adds bookmark
- [ ] `/bookmark list` shows all bookmarks (commit dda29f1)
- [ ] `/bookmark jump <N>` navigates to bookmark
- [ ] `/bookmark remove <N>` removes bookmark
- [ ] `/bookmark clear` removes all
- [ ] `/bookmarks` alias works
- [ ] Vim bookmark navigation (commit dda29f1)
- [ ] Enhanced toggle behavior (commit dda29f1)

### T12.2 - Pinned Messages
- [ ] `/pin` pins a message (commit dfb30a7, 80be47b)
- [ ] `/pin <label>` pins with label (commit 80be47b)
- [ ] Pinned panel appears at top of chat (commit e9c8dac)
- [ ] `/pin list` shows all pins (commit 80be47b)
- [ ] `/pin remove <N>` removes pin
- [ ] `/pin clear` removes all
- [ ] `/unpin` removes last pin
- [ ] `/pins` alias works
- [ ] `/pin-session` pins/favorites session in sidebar (commit 764b194)
- [ ] Visual indicators for pinned messages (commit 80be47b)
- [ ] Persistent pinned panel (commit e9c8dac)

### T12.3 - Notes
- [ ] `/note <text>` adds session annotation (commit b2aabee)
- [ ] Notes render with sticky-note styling
- [ ] `/note list` shows all notes
- [ ] `/note clear` removes all notes
- [ ] `/notes` alias works

### T12.4 - References
- [ ] `/ref <url>` adds reference (commit 74f2cce)
- [ ] `/ref add <url>` explicit add
- [ ] `/ref list` shows all references
- [ ] `/ref export` exports references
- [ ] `/refs` alias works

---

## Category 13: Notifications & Sound

### T13.1 - Notifications
- [ ] Title bar flash when response ready (commit 887d6b3)
- [ ] OSC terminal notifications (commit 0888b37)
- [ ] `/notify on/off` toggles notifications (commit 070c05b)
- [ ] `/notify sound/silent` controls sound
- [ ] `/notify flash` controls flash
- [ ] Persistence of notification preferences (commit 070c05b)
- [ ] Min-duration setting (commit 070c05b)

### T13.2 - Sound
- [ ] `/sound on/off` toggles terminal bell (commit 151a50e, 8095996)
- [ ] `/sound test` plays test sound
- [ ] Per-event sound control (commit 8095996)

---

## Category 14: Model & System

### T14.1 - /model
- [ ] `/model` shows current model (commit a6ca441, 93d20bd)
- [ ] `/model <name>` switches model
- [ ] `/model list` shows available models (commit 93d20bd)
- [ ] Model aliases work (commit 8f5efd7)
- [ ] Model descriptions display (commit 8f5efd7)
- [ ] Preference setting persists (commit 93d20bd)

### T14.2 - /system
- [ ] `/system <text>` sets custom system prompt (commit a835ace)
- [ ] `/system presets` lists preset prompts
- [ ] `/system use <preset>` applies preset
- [ ] `/system clear` removes custom prompt

### T14.3 - /mode
- [ ] `/mode planning` activates planning mode (commit e57e7e7)
- [ ] `/mode research` activates research mode
- [ ] `/mode review` activates review mode
- [ ] `/mode debug` activates debug mode
- [ ] `/mode off` deactivates mode
- [ ] `/modes` lists available modes

---

## Category 15: Keyboard Shortcuts & Navigation

### T15.1 - Core Keybindings
- [ ] F1 shows shortcut overlay (commit 9d3725f)
- [ ] Ctrl+? / Ctrl+/ shows shortcuts (commit 29fe99c)
- [ ] Ctrl+B toggles sidebar
- [ ] Ctrl+N creates new session
- [ ] Ctrl+Q quits
- [ ] Categorized cheatsheet display (commit 29fe99c)

### T15.2 - Chat Navigation
- [ ] Ctrl+Home scrolls to top
- [ ] Ctrl+End scrolls to bottom
- [ ] Ctrl+Up/Down scrolls chat
- [ ] Keyboard navigation for chat scrolling (commit a116dcb)

### T15.3 - Command Palette
- [ ] Ctrl+P opens command palette (commit 42757df)
- [ ] All 76 commands listed
- [ ] Fuzzy search filters commands
- [ ] Selecting command executes it

### T15.4 - Session Sidebar
- [ ] Sidebar shows session list
- [ ] Tree structure rendering (commit 5e853fd)
- [ ] Session search/filter (commit 6c36e75)
- [ ] Sidebar stays open on select (commit 3bc50ba)
- [ ] Breadcrumb bar shows project/session/model (commit 6c28100)

---

## Category 16: Auto-Save & Drafts

### T16.1 - Auto-Save
- [ ] Periodic snapshots save session state (commit 4fafdd3)
- [ ] Response-triggered saves (commit 4fafdd3)
- [ ] Draft input preserved on crash (commit a68b395, 4740488)
- [ ] Auto-save preferences configurable

### T16.2 - Drafts
- [ ] Per-tab draft preservation (commit 4560413)
- [ ] `/drafts list` shows saved drafts
- [ ] `/drafts clear` removes drafts
- [ ] Drafts survive tab switches

---

## Category 17: File Watching

### T17.1 - /watch
- [ ] `/watch <path>` monitors file for changes (commit a73e45a)
- [ ] `/watch list` shows watched files
- [ ] `/watch clear` stops all watches
- [ ] Change notifications appear in chat

---

## Category 18: Progress & Status Display

### T18.1 - Progress Labels
- [ ] Contextual progress labels during tool execution (commit 7c5f1ec, 9ff9a74, 9289f3f)
- [ ] Activity-specific labels ("Reading file.py", "Searching...") (commit d5db43c)
- [ ] Tool counter display (commit 9289f3f)
- [ ] Elapsed time on progress labels (commit 5d57993)
- [ ] `/progress` toggle for detailed vs generic (commit 48bce6a)

### T18.2 - Status Bar
- [ ] Word count and reading time display (commit 628255c)
- [ ] Token/context usage in status bar (commit a660faa)
- [ ] Context fuel gauge persistent (commit 34aa7b4)
- [ ] Model name visible
- [ ] Tab indicator visible (commit d42701c)

---

## Category 19: Preferences System

### T19.1 - Preference Persistence
- [ ] `/preferences` or `/prefs` shows current preferences
- [ ] Theme preference persists
- [ ] Color preferences persist
- [ ] Notification preferences persist
- [ ] Token display preferences persist
- [ ] Fold threshold persists
- [ ] All preferences survive app restart

---

## Category 20: Visual Regression (SVG Pipeline)

### T20.1 - Headless Capture
- [ ] `tools/tui_capture.py --mock-chat` produces valid SVG
- [ ] SVG contains expected UI elements
- [ ] PNG export works (requires cairosvg)

### T20.2 - SVG Analysis
- [ ] `tools/svg_parser.py` correctly identifies message types
- [ ] Layout regions classified (header, content, input, status_bar)
- [ ] Color theme detection works
- [ ] Text content extracted accurately

### T20.3 - Image Analysis
- [ ] `tools/tui_analyze.py` lite mode works (Pillow only)
- [ ] Sidebar detection works
- [ ] Layout band analysis produces reasonable results

### T20.4 - Pipeline Integration
- [ ] `tools/ux_test.sh --mock-chat` runs end-to-end
- [ ] Output files created in `.ux-tests/`
- [ ] YAML outputs parse cleanly

---

## Category 21: Edge Cases & Integration

### T21.0 - CSS & Styling Regressions
- [ ] No unsupported CSS pseudo-classes in Textual stylesheet (fix commit 58799f7)
- [ ] App stylesheet loads without CSS parse errors
- [ ] All CSS selectors compatible with current Textual version

### T21.1 - Overlapping Features
These features were implemented multiple times and may have conflicts:
- [ ] `/export` (5 implementations) - verify final behavior is coherent
- [ ] `/theme` (4 implementations) - verify themes don't conflict
- [ ] Auto-save (4 implementations) - verify no duplicate save logic
- [ ] `/pin` vs `/bookmark` - verify they are distinct features
- [ ] `/search` vs `/grep` vs `/find` vs Ctrl+F - verify all work and are distinct
- [ ] `/copy` vs Ctrl+Y vs Ctrl+Shift+C - verify all clipboard paths work

### T21.2 - Feature Interactions
- [ ] Vim mode + slash commands (can type / in normal mode?)
- [ ] Split view + tab switching
- [ ] Focus mode + sidebar operations
- [ ] Multiline mode + external editor
- [ ] Auto-scroll + find-in-chat
- [ ] Folded messages + search highlighting

### T21.3 - Resource & Performance
- [ ] App handles 100+ messages without lag
- [ ] Tab switching is responsive with many tabs
- [ ] Memory usage remains reasonable over time
- [ ] No zombie processes from /run or /watch

---

## Test Execution Notes

### For Headless/SVG Testing
Tests T20.x can be run non-interactively using the SVG pipeline. The `--mock-chat` flag
pre-populates the TUI with sample messages of each type.

### For Interactive Testing
Most tests in categories 1-19 require interactive execution:
1. Launch the app in a terminal
2. Execute commands manually
3. Verify visual output and behavior
4. Log any failures to the bug database

### Bug Logging
All bugs found should be logged to the SQLite database at:
`/home/samschillace/dev/ANext/amplifier-tui/bugs.db`

Use the `bugdb` CLI tool (see `tools/bugdb.py`) to log bugs:
```bash
python tools/bugdb.py add --test-id T1.1 --severity P1 --title "App crashes on startup" --description "Traceback: ..."
python tools/bugdb.py list
python tools/bugdb.py list --severity P0
```

---

## Category 22: Support Module Unit Tests

These tests cover the underlying support modules that the TUI app depends on.
Each function should be testable in isolation without launching the full TUI.

### T22.1 - history.py (PromptHistory)
- [ ] `__init__` creates empty history or loads from disk
- [ ] `_load` reads history file; handles missing/corrupt file gracefully
- [ ] `_save` persists entries to disk; respects max-entries limit
- [ ] `add` appends new entry; deduplicates consecutive identical entries
- [ ] `add` with `force=True` bypasses dedup logic
- [ ] `start_browse` snapshots current text and initialises browse cursor
- [ ] `previous` returns prior entry; stops at oldest
- [ ] `next` returns newer entry; returns snapshot text at end
- [ ] `is_browsing` returns True only between `start_browse` and `reset_browse`
- [ ] `entry_count` returns correct length
- [ ] `search` returns entries matching substring (case-insensitive)
- [ ] `reverse_search_indices` returns indices in reverse order for matching entries
- [ ] `get_entry` returns entry by index; returns None for out-of-range
- [ ] `entries` returns full list copy (not internal reference)
- [ ] `clear` removes all entries and persists empty state
- [ ] `reset_browse` exits browse mode cleanly

### T22.2 - preferences.py (Preferences & Persistence)
- [ ] `load_preferences` returns valid Preferences with defaults when no file exists
- [ ] `load_preferences` reads existing preferences file correctly
- [ ] `load_preferences` handles corrupt/partial JSON gracefully (returns defaults)
- [ ] `resolve_color` maps named colors to hex values
- [ ] `resolve_color` returns None for invalid color names
- [ ] `Preferences.apply_theme` switches theme and returns True on success
- [ ] `Preferences.apply_theme` returns False for unknown theme name
- [ ] `_load_custom_themes` registers user-defined themes from dict
- [ ] `save_colors` writes ColorPreferences to disk and is re-loadable
- [ ] `save_theme_name` persists theme name and survives reload
- [ ] `save_preferred_model` persists model name
- [ ] `save_show_timestamps` persists boolean toggle
- [ ] `save_word_wrap` persists boolean toggle
- [ ] `save_compact_mode` persists boolean toggle
- [ ] `save_vim_mode` persists boolean toggle
- [ ] `save_multiline_default` persists boolean toggle
- [ ] `save_streaming_enabled` persists boolean toggle
- [ ] `save_notification_sound` persists boolean toggle
- [ ] `save_notification_enabled` persists boolean toggle
- [ ] `save_notification_min_seconds` persists float value
- [ ] `save_notification_title_flash` persists boolean toggle
- [ ] `save_session_sort` persists sort mode string
- [ ] `save_autosave_enabled` persists boolean toggle
- [ ] `save_autosave_interval` persists integer seconds
- [ ] `save_show_token_usage` persists boolean toggle
- [ ] `save_context_window_size` persists integer size
- [ ] `save_fold_threshold` persists integer threshold
- [ ] `save_editor_auto_send` persists boolean toggle
- [ ] `save_show_suggestions` persists boolean toggle
- [ ] `save_progress_labels` persists boolean toggle
- [ ] Round-trip: save then load returns identical preference values

### T22.3 - session_manager.py (SessionManager)
- [ ] `__init__` initialises without active session
- [ ] `reset_usage` zeroes out token counters
- [ ] `_extract_model_info` populates model metadata from coordinator config
- [ ] `switch_model` returns True and updates model on valid name
- [ ] `switch_model` returns False on invalid/unknown model
- [ ] `get_provider_models` returns list of (id, description) tuples
- [ ] `_apply_model_override` correctly mutates config dict
- [ ] `start_new_session` creates coordinator and returns session id
- [ ] `start_new_session` registers hooks for streaming
- [ ] `resume_session` loads transcript and returns session id
- [ ] `resume_session` handles missing transcript file gracefully (commit c729173)
- [ ] `_register_hooks` wires up block_start, block_delta, block_end, tool_start, tool_end
- [ ] `_load_transcript` parses valid events.jsonl
- [ ] `_load_transcript` handles empty or malformed transcript
- [ ] `_find_most_recent_session` returns latest session id
- [ ] `get_session_transcript_path` returns correct Path for valid session
- [ ] `end_session` emits SESSION_END and cleans up coordinator
- [ ] `send_message` forwards user text and returns assistant response
- [ ] `list_all_sessions` returns list of dicts with session metadata

### T22.4 - transcript_loader.py
- [ ] `load_transcript` yields message dicts from valid events.jsonl
- [ ] `load_transcript` handles empty file (yields nothing)
- [ ] `load_transcript` skips malformed JSON lines without crashing
- [ ] `parse_message_blocks` returns correct DisplayBlock list for user message
- [ ] `parse_message_blocks` returns correct DisplayBlock list for assistant message
- [ ] `parse_message_blocks` handles thinking blocks
- [ ] `parse_message_blocks` handles tool_use and tool_result blocks
- [ ] `format_message_for_display` returns (role, content) tuple for valid message
- [ ] `format_message_for_display` returns None for unrenderable message types

### T22.5 - theme.py
- [ ] `make_custom_textual_theme` returns valid Theme object with "dark" base
- [ ] `make_custom_textual_theme` returns valid Theme object with "light" base
- [ ] `make_custom_textual_theme` assigns custom name correctly
- [ ] Returned Theme is usable by Textual App.theme setter

---

## Category 23: Error Handling & Edge Cases

### T23.1 - Empty & Missing Data States
- [ ] App launches with zero sessions (empty session list) without error
- [ ] Sidebar renders empty state message when no sessions exist
- [ ] `/sessions list` with no sessions shows informative message
- [ ] `/stats` with no messages shows zero/empty stats, no crash
- [ ] `/copy` with no messages shows informative error, no crash
- [ ] `/export` with no messages produces empty or informative output
- [ ] `/undo` with no messages shows informative error, no crash
- [ ] `/bookmark list` with no bookmarks shows empty state
- [ ] `/pin list` with no pins shows empty state
- [ ] `/snippet list` with no snippets shows empty state

### T23.2 - No Model Available
- [ ] App starts when no model is configured (graceful error in status bar)
- [ ] `/model list` with no providers shows informative message
- [ ] Sending a message with no model configured shows clear error
- [ ] `/model <invalid>` shows error without crashing

### T23.3 - Network & API Errors
- [ ] Network timeout during `send_message` shows error in chat, no crash
- [ ] API rate-limit response displays user-friendly error
- [ ] Connection refused (provider down) shows clear error message
- [ ] Partial streaming response interrupted mid-stream recovers gracefully
- [ ] Retry after transient network error works

### T23.4 - Corrupt & Invalid Data
- [ ] Corrupt preferences JSON file: app starts with defaults, no crash
- [ ] Corrupt session transcript (invalid JSON lines): session loads partially
- [ ] Corrupt history file: app starts with empty history, no crash
- [ ] Corrupt snippet store: snippets reset to defaults, no crash
- [ ] Preferences file with unknown keys: ignored gracefully
- [ ] Preferences file with wrong value types: falls back to defaults

### T23.5 - Extreme Input
- [ ] Very long message (10,000+ characters) submits and renders without hang
- [ ] Very long single-line message (no spaces, 5,000 chars) wraps correctly
- [ ] Message with only whitespace is rejected or handled gracefully
- [ ] Message with only newlines is rejected or handled gracefully
- [ ] Pasting large clipboard content (100KB+) into input area
- [ ] Unicode emoji, CJK characters, RTL text render without crash
- [ ] ANSI escape sequences in user input are escaped/stripped

### T23.6 - Rapid Action Spam
- [ ] Rapid Enter key presses do not duplicate messages
- [ ] Rapid `/new` commands do not create orphan sessions
- [ ] Rapid Ctrl+T does not create unbounded tabs
- [ ] Rapid tab switching (Alt+1, Alt+2 repeatedly) does not corrupt state
- [ ] Typing during active streaming does not crash or lose input
- [ ] Submitting message while previous response still streaming queues correctly

### T23.7 - Special Characters in Commands
- [ ] `/name` with special characters (quotes, backslashes, unicode)
- [ ] `/snippet save` with special characters in name and body
- [ ] `/alias` with special characters in alias name
- [ ] `/system` with markdown/HTML in prompt text
- [ ] `/note` with very long text and special characters
- [ ] `/search` with regex metacharacters does not crash
- [ ] `/grep` with invalid regex shows error, no crash

---

## Category 24: Startup Variants

### T24.1 - First Launch (No Existing Data)
- [ ] App starts cleanly with no `~/.amplifier` directory
- [ ] App starts cleanly with no preferences file
- [ ] App starts cleanly with no session history
- [ ] Default theme applied on first launch
- [ ] Default preferences populated on first launch
- [ ] Sidebar shows empty state or welcome message
- [ ] First `/new` command works and creates session directory structure

### T24.2 - Launch with Corrupt Session Data
- [ ] App starts when sessions directory contains non-session files
- [ ] App starts when a session directory is missing events.jsonl
- [ ] App starts when a session's events.jsonl is empty (0 bytes)
- [ ] App starts when a session's events.jsonl contains only invalid JSON
- [ ] App starts when sessions directory has permission errors (read-only)
- [ ] Corrupt session is skipped in sidebar; other sessions load normally
- [ ] App starts when preferences file is 0 bytes

### T24.3 - Launch Without amplifier-core Installed
- [ ] App shows clear error message when amplifier-core is not importable
- [ ] Error message includes installation instructions or guidance
- [ ] App does not show raw Python ImportError traceback to user
- [ ] App exits gracefully (non-zero exit code) when dependency missing

### T24.4 - Launch with Various Configurations
- [ ] App respects `--mock-chat` flag for testing (commit 2a21101)
- [ ] App startup with renamed package (amplifier-tui) works (commit 2a21101)
- [ ] App launches from different working directories
- [ ] App launches when terminal is very small (e.g., 40x10)
- [ ] App launches when terminal is very large (e.g., 300x80)
- [ ] App launches with `$EDITOR` unset (editor fallback chain works)
- [ ] App launches with `$TERM` set to dumb terminal
