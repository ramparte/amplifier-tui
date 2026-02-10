# amplifier-tui Feature Backlog

**Status**: Active backlog for next build session
**Generated**: 2026-02-09
**Context**: Health check passed 356/356 tests (263 unit + 93 interactive). Codebase is stable and ready for feature work.

---

## Tier 1: Polish & Quality of Life

### F1.1 Command Palette (fuzzy search overlay)

**Priority**: High -- 78+ commands demands discoverability
**Complexity**: Medium

A fuzzy-search overlay activated by `ctrl+shift+p` (or `/palette`) that searches across:
- All slash commands (with descriptions)
- All keybindings (with current bindings)
- Recent sessions (by name/title)
- Settings/preferences

**Implementation notes**:
- Model after VS Code's command palette
- Use existing `ModalScreen` pattern (see `ShortcutOverlay` and `HistorySearchScreen` in `widgets/screens.py`)
- Fuzzy matching on command name + description text
- Show keybinding next to each command if one exists
- Enter to execute, Escape to dismiss
- Filter as you type with ranked results

**Test IDs**: T21.1a (open palette), T21.1b (filter by typing), T21.1c (execute command), T21.1d (dismiss with escape)

---

### F1.2 Session Tags

**Priority**: High -- organizational power for heavy users
**Complexity**: Medium

Tag sessions with user-defined categories (`#debugging`, `#auth-work`, `#design`, `#research`).

**Features**:
- `/tag add <tag>` -- add tag to current session
- `/tag remove <tag>` -- remove tag
- `/tag list` -- show tags on current session
- `/tags` -- list all tags across all sessions with counts
- Tags displayed in sidebar next to session name (colored chips)
- `/sessions search #tag` -- filter sessions by tag
- Tag auto-complete from existing tags
- Tags stored in a new `TagStore` persistence module

**Persistence**: New `TagStore` in `amplifier_tui/persistence/tags.py` following the existing store patterns. Key: session_id -> list of tag strings. Separate file: `~/.amplifier/tui-session-tags.json`.

**Test IDs**: T22.1a (tag add), T22.1b (tag list), T22.1c (tag remove), T22.2a (tags command), T22.2b (session search by tag)

---

### F1.3 Clipboard Ring

**Priority**: Medium -- power user feature
**Complexity**: Low-Medium

Keep the last N copies in a searchable ring.

**Features**:
- Every `/copy` and `ctrl+y` operation appends to the ring (max 50 entries)
- `/clipboard` or `/clip` -- show ring with numbered entries, timestamps, previews
- `/clipboard N` -- re-copy entry N to system clipboard
- `/clipboard search <query>` -- search ring contents
- `/clipboard clear` -- clear ring
- Persist across sessions via `ClipboardStore`
- Each entry stores: content, timestamp, source (message index, code block, manual)

**Persistence**: New `ClipboardStore` in `amplifier_tui/persistence/clipboard.py`. File: `~/.amplifier/tui-clipboard-ring.json`. Prune to 50 entries on save.

**Test IDs**: T23.1a (clipboard list empty), T23.1b (clipboard after copy), T23.1c (clipboard search), T23.1d (clipboard N re-copy)

---

### F1.4 Smart `/include` with Auto-Complete

**Priority**: Medium -- reduces friction for file inclusion
**Complexity**: Medium

Enhance `/include` with contextual awareness.

**Features**:
- Path auto-complete as you type (tab completion after `/include `)
- `/include tree` -- include the project's directory tree (respecting .gitignore)
- `/include git` -- include git status + recent diff
- `/include context` -- include all files currently in Amplifier's context window
- `/include recent` -- show recently included files for quick re-include
- File preview in a split panel before confirming include
- Detect file references in conversation and offer to include them (suggestion bar)
- Syntax-aware preview (show language, line count, size before including)

**Test IDs**: T24.1a (include tree), T24.1b (include git), T24.1c (include recent)

---

## Tier 2: Make the Invisible Visible

### F2.1 Agent Tree View

**Priority**: Critical -- the killer differentiating feature
**Complexity**: High

Live visualization of Amplifier's multi-agent delegation tree.

**What to show**:
```
Delegating...
  +-- foundation:explorer (surveying auth/)      [12s, 3.2k tokens]  RUNNING
  +-- python-code-intel (tracing call graph)     [8s, 1.1k tokens]   RUNNING
  +-- zen-architect (reviewing design)           [pending]            QUEUED
```

**Features**:
- Real-time tree that updates as agents spawn and complete
- Each node shows: agent name, instruction summary (truncated), elapsed time, token consumption, status (queued/running/completed/failed)
- Collapsible nodes -- expand to see agent's instruction and result summary
- Color-coded status: gray=queued, yellow=running, green=completed, red=failed
- Nested delegation (agents spawning sub-agents) shown as nested tree nodes
- Total delegation summary when all complete: N agents, total time, total tokens
- Toggle visibility with a keybinding or `/agents` command
- `/agents` with no args shows current tree; `/agents history` shows past delegations in this session

**Implementation approach**:
- Hook into Amplifier's event system -- listen for `session:spawn`, `session:complete`, agent lifecycle events
- New widget: `AgentTreePanel` in `widgets/panels.py` or new `widgets/agent_tree.py`
- Can render in the split pane (right side) or as an overlay
- Track agent hierarchy via parent_id linking

**Data source**: Amplifier emits events for sub-session creation and completion. The `session_manager.py` would need to expose callbacks or the app would register hooks to capture these events. If event data isn't directly available, poll the session's sub-session list.

**Test IDs**: T25.1a (agents command empty), T25.1b (agents panel visibility toggle)

---

### F2.2 Context Window Profiler

**Priority**: High -- solves the universal "why is it forgetting?" problem
**Complexity**: Medium-High

Visual breakdown of what's consuming the context window. Replaces or extends the existing `/context` command.

**Features**:
- `/context` -- show the profiler view (replaces current simple display)
- Stacked bar visualization:
  ```
  Context: [=============================----] 78% (156k / 200k tokens)
    System prompt:    @@@@              12%  (24k)
    Conversation:     @@@@@@@@@@@@      38%  (76k)
    Tool results:     @@@@@@@@          24%  (48k)
    Injected context: @@@               10%  (20k)
    Available:        ----              16%  (32k)
  ```
- `/context detail` -- expanded view with per-message token estimates
- `/context history` -- how context usage has grown over the session (sparkline)
- Warning indicators when approaching limits (yellow at 75%, orange at 85%, red at 95%)
- Persistent mini-indicator in status bar (e.g., `CTX: 78%` with color)
- Identify the largest single items consuming context (biggest tool result, longest message)

**Implementation notes**:
- Token estimation: use the tiktoken or character-based estimation already in the codebase
- Pull data from Amplifier's context module (the session's context manager tracks messages)
- The status bar indicator updates on every message exchange

**Test IDs**: T26.1a (context profiler display), T26.1b (context detail), T26.1c (status bar indicator)

---

### F2.3 Recipe Pipeline Visualization

**Priority**: Medium-High -- makes recipes tangible
**Complexity**: Medium

Step-by-step progress view when recipes are executing.

**Features**:
- When a recipe starts, show a pipeline panel:
  ```
  Recipe: code-review (step 3/5)
    [x] 1. Explore codebase          4m22s
    [x] 2. Analyze architecture      2m11s
    [>] 3. Review security           1m05s  RUNNING
    [ ] 4. Generate report           pending
    [ ] 5. APPROVAL: review-gate     waiting
  ```
- Completed steps show duration, running step shows elapsed time
- Approval gates are interactive -- user can approve/deny inline
- Click/select a completed step to see its output summary
- Recipe metadata shown: recipe name, source file, total steps
- Error states highlighted in red with error message preview
- `/recipe` command to toggle visibility of the pipeline panel

**Implementation approach**:
- Hook into recipe events (step_start, step_complete, approval_pending)
- New widget: `RecipePipelinePanel` that renders in split pane or as overlay
- Approval gates trigger an interactive prompt (Y/N) in the TUI

**Test IDs**: T27.1a (recipe panel display), T27.1b (recipe step progress)

---

### F2.4 Inline Diff View for File Edits

**Priority**: Medium -- visual clarity for the most common AI action
**Complexity**: Medium

When the AI uses `edit_file` or `write_file`, render a proper colored diff inline.

**Features**:
- Detect `edit_file` and `write_file` tool results in the message stream
- Render unified diff with syntax coloring (green=added, red=removed, gray=context)
- Collapsible (like existing tool blocks) with summary: "Edited src/auth.py (+12, -3)"
- File name as header, line numbers in gutter
- For `write_file` on new files, show the full content with "new file" indicator
- Option to show side-by-side diff in split view
- `/diff last` -- re-show the most recent file edit diff

**Implementation notes**:
- Leverage existing `colorize_diff()` and `show_diff()` in `features/git_integration.py`
- Parse tool call arguments to extract old_string/new_string for edit_file
- For write_file, show a "new file" diff (all lines green)
- Render as a `Static` widget with Rich markup inside a `Collapsible`

**Test IDs**: T28.1a (diff display for edit), T28.1b (diff collapsible toggle)

---

## Tier 3: Workflow Power Tools

### F3.1 Conversation Branching (Fork UI)

**Priority**: High -- unique capability for exploring alternatives
**Complexity**: High

Visual branch explorer extending the existing `/fork` command.

**Features**:
- `/fork` at any message creates a named branch from that point
- `/branches` -- show a tree view of all branches in the current session
  ```
  main
    +-- [msg 5] branch: "alternative-approach" (8 messages)
    |     +-- [msg 3] branch: "with-caching" (4 messages)
    +-- [msg 12] branch: "try-redis" (3 messages)
  ```
- `/branch switch <name>` -- switch to a branch (loads that conversation state)
- `/branch compare <a> <b>` -- show two branches side-by-side in split view
- `/branch merge <name>` -- copy key messages from a branch back to main
- Branch indicator in status bar showing current branch name
- Branches persist across session resume

**Implementation notes**:
- Each branch is a snapshot of conversation state at the fork point plus new messages
- Store in a new `BranchStore` persistence module, keyed by session_id
- The tab system could be reused (each branch as a hidden tab)
- Compare view uses existing split infrastructure

**Test IDs**: T29.1a (fork creates branch), T29.1b (branches list), T29.1c (branch switch)

---

### F3.2 Model A/B Testing

**Priority**: Medium -- powerful for model evaluation
**Complexity**: Medium-High

Send the same prompt to two models simultaneously and compare responses.

**Features**:
- `/compare <model_a> <model_b>` -- enter A/B mode
- Next prompt goes to both models in parallel
- Results shown side-by-side in split view (left=model_a, right=model_b)
- Header shows model name, response time, token count for each
- `/compare off` -- exit A/B mode
- `/compare pick left|right` -- choose the preferred response and continue conversation with it
- `/compare history` -- show past comparisons in this session

**Implementation notes**:
- Use Amplifier's multi-provider support to route to different models
- Split view rendering with two `AssistantMessage` widgets side by side
- Both responses stream simultaneously
- After pick, the non-chosen response is discarded from context

**Test IDs**: T30.1a (compare mode activation), T30.1b (compare off), T30.1c (compare display)

---

### F3.3 Session Replay

**Priority**: Medium -- great for demos and learning
**Complexity**: Medium

Play back any session like a movie with original timing.

**Features**:
- `/replay [session_id]` -- start replay of a session (default: current)
- `/replay speed 2x` -- adjust playback speed (0.5x, 1x, 2x, 5x, instant)
- `/replay pause` / `/replay resume` -- pause/resume playback
- `/replay skip` -- jump to next message
- Messages appear with simulated typing effect for user messages
- Assistant messages stream in at adjusted speed
- Tool calls shown as collapsible blocks (appear at original timing)
- Timeline scrubber bar at bottom showing progress through the session
- Replay runs in a dedicated tab (read-only, can't send messages)

**Implementation notes**:
- Read `transcript.jsonl` for the target session
- Use timestamps from transcript to calculate inter-message delays
- Render into a read-only chat view (reuse existing message widgets)
- The `transcript_loader.py` already knows how to parse transcripts -- extend it with timing

**Test IDs**: T31.1a (replay command), T31.1b (replay speed change), T31.1c (replay in tab)

---

### F3.4 Semantic Cross-Session Search

**Priority**: Medium-High -- transforms session history into a knowledge base
**Complexity**: High

Search across all sessions using meaning, not just text matching.

**Features**:
- `/search --semantic <query>` -- find sessions by meaning
  - "the session where I debugged the auth token expiry" should match even without those exact words
- `/search --deep <query>` -- full-text search across all session transcripts (existing, enhanced)
- Results ranked by relevance with preview snippets
- `/search open N` -- open result N in a new tab (existing feature, enhanced)
- Index sessions in background for fast search
- Search scope filters: `--since`, `--project`, `--tag`, `--model`

**Implementation notes**:
- Local embedding model (e.g., sentence-transformers or similar small model) for semantic vectors
- Store embeddings alongside session metadata
- Fall back to enhanced text search if embeddings unavailable
- Background indexing on session close
- Could also leverage Amplifier's session-analyst agent for complex queries

**Test IDs**: T32.1a (search deep), T32.1b (search with filters)

---

## Tier 4: "Nobody Has Done This Yet"

### F4.1 Live Tool Introspection Panel

**Priority**: Medium -- transparency superpower
**Complexity**: Medium

Real-time panel showing exactly what the AI is doing with tools, as it happens.

**Features**:
- Side panel (toggle with keybinding or `/tools live`) showing a scrolling log:
  ```
  [14:32:01] read_file  src/auth.py (lines 1-50)
  [14:32:02] grep        "validate_token" in src/
  [14:32:03] bash        git log --oneline -5
  [14:32:04] edit_file   src/auth.py:42  (+3 lines)
  ```
- Each entry shows: timestamp, tool name, key arguments (truncated), duration
- Color coded by tool type (file ops=blue, search=yellow, bash=green, delegate=purple)
- Click/select an entry to see full input/output in a detail view
- Counter in status bar: "Tools: 12" showing total tool calls this turn
- `/tools log` -- show the full tool log for the session
- `/tools stats` -- aggregate stats (already exists, but link from here)

**Implementation notes**:
- Hook into tool call/result events from the orchestrator
- New `ToolLogPanel` widget in the split pane area
- Buffer last 100 tool calls for scrollback
- Lightweight: just capture tool name + key args, not full payloads

**Test IDs**: T33.1a (tools live toggle), T33.1b (tools log display)

---

### F4.2 Session Heatmap Dashboard

**Priority**: Low-Medium -- nice for self-awareness
**Complexity**: Medium

Usage patterns visualization.

**Features**:
- `/dashboard` -- show a full-screen dashboard with:
  - Activity heatmap (hour x day grid, colored by session count)
  - Top commands used (bar chart)
  - Models used (pie/bar)
  - Tokens consumed over time (sparkline)
  - Average session duration
  - Most active projects
  - Streak counter (consecutive days with sessions)
- Data pulled from session metadata files
- Dashboard can be exported as HTML (`/dashboard export`)

**Implementation notes**:
- New full-screen `DashboardScreen` (like `ShortcutOverlay` but richer)
- Aggregate data from `~/.amplifier/projects/*/sessions/*/session-info.json`
- TUI charts using braille characters or block elements for heatmaps
- Cache aggregated stats to avoid re-scanning on every open

**Test IDs**: T34.1a (dashboard display), T34.1b (dashboard export)

---

### F4.3 Plugin System (Custom Slash Commands)

**Priority**: Medium -- extensibility
**Complexity**: Medium

Drop-in Python scripts that register as slash commands.

**Features**:
- Plugin directory: `~/.amplifier/tui-plugins/` (user-global) and `.amplifier/tui-plugins/` (project)
- Each plugin is a single Python file with a registration decorator:
  ```python
  from amplifier_tui.plugin import slash_command

  @slash_command("greet", description="Say hello")
  def cmd_greet(app, args: str):
      app._add_system_message(f"Hello, {args or 'world'}!")
  ```
- `/plugins` -- list loaded plugins
- `/plugins reload` -- hot-reload plugins without restarting
- Plugins have access to the app instance (read messages, add system messages, access persistence)
- Sandboxed: plugins can't modify core app internals directly
- Error isolation: a crashing plugin doesn't crash the app

**Implementation notes**:
- Plugin loader scans directories on startup and on `/plugins reload`
- Each plugin file is imported dynamically
- The `@slash_command` decorator registers into a plugin registry
- The main `_handle_slash_command` checks plugin registry before built-in commands
- Error handling wraps each plugin call in try/except

**Test IDs**: T35.1a (plugins list), T35.1b (plugin execution)

---

### F4.4 Voice Input Mode

**Priority**: Low -- future-looking
**Complexity**: High

Speech-to-text for hands-free interaction.

**Features**:
- `/voice` -- toggle voice input mode
- When active, captures microphone audio and transcribes to text
- Transcribed text appears in the input field for review before sending
- `/voice send` -- auto-send after transcription (no review)
- `/voice lang <code>` -- set transcription language
- Visual indicator: pulsing microphone icon in status bar when listening
- Push-to-talk mode: hold a key to record, release to transcribe

**Implementation notes**:
- Use local Whisper (whisper.cpp or faster-whisper) for privacy
- Fallback to OS speech input APIs (macOS dictation, Windows speech)
- Audio capture via sounddevice or pyaudio
- This is the highest-complexity feature -- consider as a plugin first

**Test IDs**: T36.1a (voice toggle -- mock only, no real audio in tests)

---

## Implementation Order (Suggested)

The ordering below optimizes for: impact, testability, and dependency chains.

### Wave 1: Foundation & Quick Wins
1. **F1.1** Command Palette -- sets up the modal overlay pattern reused later
2. **F1.2** Session Tags -- new persistence store pattern, sidebar enhancement
3. **F1.3** Clipboard Ring -- simple persistence store, small scope
4. **F2.4** Inline Diff View -- leverages existing diff code, high visibility

### Wave 2: The Transparency Layer
5. **F2.1** Agent Tree View -- the signature feature, needs event hookup
6. **F2.2** Context Window Profiler -- data may already be available, high user value
7. **F4.1** Live Tool Introspection -- complements agent tree, similar event patterns

### Wave 3: Workflow Power
8. **F2.3** Recipe Pipeline Visualization -- similar panel pattern to agent tree
9. **F1.4** Smart /include -- builds on existing command
10. **F3.1** Conversation Branching -- complex but high value

### Wave 4: Advanced
11. **F3.2** Model A/B Testing -- requires multi-provider coordination
12. **F3.3** Session Replay -- standalone, can be done anytime
13. **F3.4** Semantic Cross-Session Search -- needs embedding infrastructure

### Wave 5: Extensibility & Future
14. **F4.3** Plugin System -- enables community contributions
15. **F4.2** Session Heatmap Dashboard -- data aggregation, standalone
16. **F4.4** Voice Input -- highest complexity, lowest priority
