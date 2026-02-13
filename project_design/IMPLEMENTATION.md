# Project Intelligence: Implementation Plan

This document breaks the design into ordered implementation tasks with exact file locations, dependencies, and acceptance criteria. Tasks are grouped into phases that can each be a single working session.

---

## Phase 1: Tag Foundation (Backend + TUI)

**Goal:** Make tags useful and visible. This is the prerequisite for everything else.

**Estimated effort:** 1 session

### Task 1.1: Tags in sidebar filter

**Files to modify:**
- `amplifier_tui/app.py` -- `_filter_sessions()` method (around line 2114)

**What to do:**
- Load tag data once at the start of the filter: `all_tags = self._tag_store.load()`
- Extend the `_matches()` closure to check tags:
  ```python
  tags = all_tags.get(sid, [])
  # ... add to the return condition:
  or any(q in t for t in tags)
  ```
- Add `#` prefix detection: if query starts with `#`, strip it and match tags only (not name/project/id)

**Acceptance criteria:**
- Typing `auth` in the filter finds sessions tagged "auth" (alongside name/id/project matches)
- Typing `#auth` in the filter finds ONLY sessions tagged "auth"
- Performance: no noticeable delay (single JSON file read)

### Task 1.2: Tags visible in sidebar session entries

**Files to modify:**
- `amplifier_tui/app.py` -- `_session_display_label()` method and `_populate_session_list()`

**What to do:**
- In `_populate_session_list()`, load tags once: `all_tags = self._tag_store.load()`
- Pass tags to `_session_display_label()` or append after it returns
- After the label, append up to 2 tags in dim styling:
  ```python
  session_tags = all_tags.get(sid, [])[:2]
  tag_suffix = "  " + " ".join(f"[dim]#{t}[/dim]" for t in session_tags) if session_tags else ""
  ```
- Reduce label truncation from 28 to ~22 chars to make room
- Show full tag list in the collapsed child node (alongside session ID)

**Acceptance criteria:**
- Sessions with tags show `#tag1 #tag2` after the session name in dim text
- Tags don't overflow or break the sidebar layout
- Full tag list visible when expanding the session node

### Task 1.3: Tags in `_filter_sessions()` tree rebuild

**Files to modify:**
- `amplifier_tui/app.py` -- the tree rebuild portion of `_filter_sessions()` (around line 2134+)

**What to do:**
- Ensure the filtered tree rebuild also shows tags on session entries (same as 1.2)
- Pass `all_tags` through to the display label rendering in the filter path

**Acceptance criteria:**
- Tags remain visible on session entries even when a filter is active

### Task 1.4: Tag sort/grouping mode

**Files to modify:**
- `amplifier_tui/core/preferences.py` -- validation (around line 597), `save_session_sort()` 
- `amplifier_tui/app.py` -- `_sort_sessions()` method

**What to do:**
- Add `"tag"` to valid sort values: `if val in ("date", "name", "project", "tag"):`
- In `_sort_sessions()`, add a `"tag"` case:
  ```python
  elif sort_mode == "tag":
      # Group by first tag, then by date within group
      def tag_key(s):
          tags = all_tags.get(s["session_id"], [])
          first_tag = tags[0] if tags else "~untagged"  # ~ sorts last
          return (first_tag.lower(), -s["mtime"])
      sessions.sort(key=tag_key)
  ```
- Update `_populate_session_list()` to group by tag instead of project when in tag sort mode
- Each tag becomes a tree group node, untagged sessions under "Untagged"

**Acceptance criteria:**
- `/sort tag` groups sessions by their first tag
- Untagged sessions appear under "Untagged" group at the bottom
- Within each tag group, sessions sorted by date descending
- Preference persists across sessions

---

## Phase 2: Auto-Tagging (Backend)

**Goal:** Sessions get tagged automatically. Users don't have to manually tag everything.

**Estimated effort:** 1 session

### Task 2.1: Auto-tagger state store

**Files to create:**
- `amplifier_tui/core/features/auto_tagger.py`

**What to do:**
- Create `AutoTagState` store (extends `JsonStore`) at `~/.amplifier/tui-auto-tag-state.json`
- Schema:
  ```json
  {
    "session-uuid": {
      "tagged_at": "2026-02-11T20:00:00Z",
      "mtime_at_tagging": 1739304000.0,
      "tags_generated": ["web", "frontend"],
      "removed_by_user": ["misc"]
    }
  }
  ```
- Track which sessions have been auto-tagged and at what transcript mtime
- Track tags the user explicitly removed (don't re-generate those)

### Task 2.2: Auto-tagger core logic

**Files to create/modify:**
- `amplifier_tui/core/features/auto_tagger.py` (continued)

**What to do:**
- Create `AutoTagger` class following the `SessionSummarizer` pattern:
  ```python
  class AutoTagger:
      def __init__(self, tag_store: TagStore, state_store: AutoTagState, 
                   tag_fn: Callable[[str], str] | None = None)
      def needs_tagging(self, session_id: str, mtime: float) -> bool
      def queue_session(self, session_id: str, project: str, 
                        session_dir: Path, mtime: float) -> None
      def process_pending(self, max_count: int = 3) -> int
  ```
- `needs_tagging()`: True if session has no tags AND hasn't been auto-tagged at this mtime
- `process_pending()`:
  1. Pop from queue
  2. Read transcript tail (16KB, reuse `read_transcript_excerpt` from session_summarizer)
  3. Get existing tag vocabulary via `tag_store.all_tags()`
  4. Build prompt (see DESIGN.md section 1.2)
  5. Parse LLM response into tag list
  6. Filter out any tags in `removed_by_user`
  7. Add tags via `tag_store.add_tag()`
  8. Update state store

- Tag function: `make_anthropic_auto_tagger()` using haiku-class model, max_tokens=50

**Acceptance criteria:**
- Sessions without tags get 1-3 auto-generated tags
- Auto-tagger prefers existing tag vocabulary
- User-removed tags are not re-generated
- Processing is throttled (3 per cycle max)

### Task 2.3: Wire auto-tagger into session list refresh

**Files to modify:**
- `amplifier_tui/app.py` -- session list lifecycle
- `amplifier_tui/commands/monitor_cmds.py` -- timer architecture (reference pattern)

**What to do:**
- Instantiate `AutoTagger` in `AmplifierTUI.__init__()` or `compose()` alongside other stores
- During `_populate_session_list()` or on a background timer:
  1. For each session without tags, call `auto_tagger.queue_session()`
  2. On a slow timer (30s), call `auto_tagger.process_pending(max_count=3)`
  3. After processing, trigger sidebar refresh to show new tags

**Acceptance criteria:**
- New/untagged sessions get tags within 30-60 seconds of appearing
- No UI blocking during auto-tagging
- Sidebar refreshes to show new tags after they're generated

### Task 2.4: Respect user tag removals

**Files to modify:**
- `amplifier_tui/core/persistence/tags.py` -- `remove_tag()` method
- `amplifier_tui/core/features/auto_tagger.py` -- state tracking

**What to do:**
- When a user removes a tag via `/tag remove`, check if it was auto-generated
- If so, record it in the auto-tagger state as `removed_by_user`
- Auto-tagger checks this list before adding tags

**Implementation note:** This needs a hook from `TagStore.remove_tag()` to `AutoTagger`, or the auto-tagger can check at generation time. Simpler: the `/tag remove` command handler (in `persistence_cmds.py`) notifies the auto-tagger directly.

**Acceptance criteria:**
- User removes auto-generated tag "misc" from session X
- Auto-tagger never re-adds "misc" to session X
- User can still manually add "misc" to other sessions

### Task 2.5: Auto-tagging preference

**Files to modify:**
- `amplifier_tui/core/preferences.py` -- add `auto_tagging` section

**What to do:**
- Add to preferences YAML defaults:
  ```yaml
  auto_tagging:
    enabled: true
    max_tags: 3
  ```
- Add validation and accessor methods
- Auto-tagger checks `preferences.auto_tagging.enabled` before processing

**Acceptance criteria:**
- `auto_tagging.enabled: false` disables all auto-tagging
- `max_tags` controls the maximum number of tags generated per session

---

## Phase 3: Project Aggregation (Backend + TUI)

**Goal:** "Project" becomes a queryable concept with health summaries.

**Estimated effort:** 1 session

### Task 3.1: ProjectAggregator service

**Files to create:**
- `amplifier_tui/core/features/project_aggregator.py`

**What to do:**
- Create `ProjectSummary` and `SessionSummary` dataclasses (see DESIGN.md section 2.1)
- Create `ProjectAggregator` class:
  ```python
  class ProjectAggregator:
      def __init__(self, session_manager: SessionManager, 
                   scanner: SessionScanner, 
                   summarizer: SessionSummarizer,
                   tag_store: TagStore)
      
      def get_project_summary(self, project_path: str) -> ProjectSummary
      def list_projects(self) -> list[ProjectSummary]
      def needs_attention(self) -> list[SessionSummary]
  ```
- `get_project_summary()`:
  1. `list_all_sessions()` filtered by project_path
  2. Cross-reference with `scanner.scan()` for state
  3. Merge tags from `tag_store`
  4. Merge summaries from `summarizer` cache
  5. Compute counts, identify stale sessions
- `needs_attention()`: Sessions that are STALE across all projects

**Note on SessionScanner:** Currently `scan()` returns top N sessions by recency regardless of project. The aggregator may need to scan more broadly or filter the scanner's output. Consider adding a `project_path` filter to `scan()` or scanning all sessions and grouping.

**Acceptance criteria:**
- `get_project_summary("~/dev/ANext/amplifier-tui")` returns correct counts
- Stale sessions identified in `needs_attention`
- Tags aggregated per project

### Task 3.2: `/project` command

**Files to create:**
- `amplifier_tui/commands/project_cmds.py` -- `ProjectCommandsMixin`

**Files to modify:**
- `amplifier_tui/core/shared_app_base.py` -- add mixin to the base class
- `amplifier_tui/app.py` -- ensure mixin is in MRO
- `amplifier_tui/web/web_app.py` -- ensure mixin is in MRO

**What to do:**
- Implement `/project` command with subcommands:
  - `/project` (no args) -- summary of current session's project
  - `/project <name>` -- summary of named project (fuzzy match on project name)
  - `/project list` -- all projects with session counts
  - `/project attention` -- sessions needing attention across all projects
- Output rendered as formatted text (see DESIGN.md section 2.2 for format)
- Instantiate `ProjectAggregator` lazily (first use)

**Acceptance criteria:**
- `/project` shows a useful summary of the current project
- `/project list` shows all projects with counts
- `/project attention` highlights stale sessions
- Works in both TUI and web app (via shared mixin)

### Task 3.3: Project counts in sidebar headers

**Files to modify:**
- `amplifier_tui/app.py` -- `_populate_session_list()` project group creation

**What to do:**
- When creating project group nodes in the tree, include session count:
  ```python
  # Current:
  group_label = short_project_path
  # New:
  count = len(project_sessions)
  group_label = f"{short_project_path} ({count})"
  ```
- Optionally, if scanner data is available (monitor is open), include state:
  ```python
  active = sum(1 for s in project_sessions if scanner_state.get(s["session_id"]) == "running")
  if active:
      group_label += f"  {active} active"
  ```

**Acceptance criteria:**
- Sidebar project groups show `(N)` count
- Count updates when sessions are added/removed

---

## Phase 4: Cross-Session Intelligence (Backend + TUI)

**Goal:** Ask questions about a project and get synthesized answers.

**Estimated effort:** 1 session

### Task 4.1: Project question engine

**Files to create:**
- `amplifier_tui/core/features/project_intelligence.py`

**What to do:**
- Create `ProjectIntelligence` class:
  ```python
  class ProjectIntelligence:
      def __init__(self, aggregator: ProjectAggregator, ask_fn: Callable)
      
      async def ask(self, project_path: str, question: str) -> str
      async def what_needs_attention(self, project_path: str) -> str
      async def weekly_summary(self, project_path: str) -> str
  ```
- `ask()`:
  1. Get `ProjectSummary` from aggregator
  2. Build context: project summary + recent session summaries + tags
  3. Prompt with question + context
  4. Return LLM response
- Use sonnet-class model for quality synthesis
- Cache responses for 5 minutes (keyed by project_path + question hash)

**Acceptance criteria:**
- "What needs attention in tui?" returns a useful, specific answer
- "What did I do this week?" summarizes recent session activity
- Responses reference specific sessions by name/ID

### Task 4.2: `/project ask` subcommand

**Files to modify:**
- `amplifier_tui/commands/project_cmds.py` -- add `ask` subcommand

**What to do:**
- `/project ask <question>` routes to `ProjectIntelligence.ask()`
- Response displayed as formatted text in the output pane
- Include a thinking/loading indicator while the LLM processes

**Acceptance criteria:**
- `/project ask what needs attention?` returns a synthesized answer
- Loading indicator shown during processing
- Works in both TUI and web

### Task 4.3: Cross-session search

**Files to create:**
- `amplifier_tui/core/features/project_search.py`

**What to do:**
- Create `ProjectSearch` class:
  ```python
  class ProjectSearch:
      def search(self, project_path: str, query: str, 
                 limit: int = 20) -> list[SearchResult]
  ```
- `SearchResult`: `{session_id, short_id, name, match_context, line_number, timestamp}`
- Implementation: iterate session dirs for the project, grep `transcript.jsonl` for query
- Return matching sessions with surrounding context lines

**Files to modify:**
- `amplifier_tui/commands/project_cmds.py` -- add `search` subcommand

**Acceptance criteria:**
- `/project search "filter bug"` finds sessions where that phrase appears
- Results show session name + matching context snippet
- Performance: <2s for typical project with 20 sessions

---

## Phase 5: Web App Integration

**Goal:** Bring project intelligence to the web experience.

**Estimated effort:** 1-2 sessions (depends on web app state at time of implementation)

**Important:** The web app is being rebuilt. These tasks describe intent. The implementation session must assess the web app's current architecture and adapt.

### Task 5.1: Assess web app state

**What to do:**
- Review the current web app architecture (templates, static files, WebSocket protocol)
- Determine how session lists are rendered on the client
- Identify the right integration points for project features
- Adapt the tasks below to the actual architecture

### Task 5.2: Session list with tags (web)

**Intent:**
- Sessions in the web session list show tag pills/labels
- Tags are clickable to filter
- Tag data sent via WebSocket alongside session data

**Suggested approach:**
- Add `tags` field to session data sent to the client
- Client renders tags as styled labels (colored pills, like GitHub issue labels)
- Clicking a tag filters the session list to that tag

### Task 5.3: Project summary cards (web)

**Intent:**
- Dashboard/home view shows project cards
- Each card: project name, session counts, state indicators, top tags, last activity
- Click to drill into project detail

**Suggested approach:**
- New WebSocket event type `project_summary` pushed on timer
- Client renders as cards with health indicators
- Drill-down shows full session list for that project

### Task 5.4: Project detail view (web)

**Intent:**
- All sessions for a project, filterable by tag and state
- Timeline of activity
- "Needs attention" section at top
- Tag management (add/remove from this view)

### Task 5.5: Project question interface (web)

**Intent:**
- Input field to ask questions about a project
- Routes to `ProjectIntelligence.ask()`
- Response rendered in a chat-like interface or summary panel

---

## Dependency Graph

```
Phase 1 (Tags Foundation)
  1.1 Filter ────────┐
  1.2 Display ───────┤
  1.3 Filter+Display─┤ (depends on 1.1 + 1.2)
  1.4 Sort mode ─────┘
         │
         v
Phase 2 (Auto-Tagging)
  2.1 State store ───┐
  2.2 Core logic ────┤ (depends on 2.1)
  2.3 Wire in ───────┤ (depends on 2.2)
  2.4 User removals──┤ (depends on 2.2)
  2.5 Preferences ───┘
         │
         v
Phase 3 (Project Aggregation)
  3.1 Aggregator ────┐
  3.2 /project cmd ──┤ (depends on 3.1)
  3.3 Sidebar counts─┘ (independent, just needs Phase 1)
         │
         v
Phase 4 (Cross-Session Intelligence)
  4.1 Question engine ──┐ (depends on 3.1)
  4.2 /project ask ─────┤ (depends on 4.1)
  4.3 Cross-search ─────┘ (independent)
         │
         v
Phase 5 (Web Integration)
  5.1-5.5 (depends on web app state + all backend from Phases 1-4)
```

**Critical path:** Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5

**Parallelizable:** Task 3.3 (sidebar counts) can be done alongside Phase 2. Task 4.3 (search) is independent of 4.1/4.2.

---

## Testing Strategy

### Unit Tests

| Component | Test File | Key Tests |
|-----------|-----------|-----------|
| Tag filtering | `tests/test_filter.py` | `#` prefix behavior, multi-tag matching, empty tags |
| Auto-tagger | `tests/test_auto_tagger.py` | Vocabulary reuse, user removal respect, throttling |
| ProjectAggregator | `tests/test_project_aggregator.py` | Count accuracy, stale detection, multi-project |
| ProjectIntelligence | `tests/test_project_intelligence.py` | Context assembly, cache behavior |
| ProjectSearch | `tests/test_project_search.py` | Grep accuracy, context snippets |

### Integration Tests

- Tag flow: add tag -> appears in filter -> appears in sidebar -> persists across restart
- Auto-tag flow: new session -> 30s -> tags appear -> user removes one -> not re-added
- Project flow: `/project` -> correct counts -> `/project attention` -> stale sessions listed

### Manual Verification

Each phase should end with a manual walkthrough:
- Phase 1: Create session, add tags, filter by tag, verify sidebar display
- Phase 2: Create untagged session, wait, verify auto-tags appear
- Phase 3: Run `/project`, verify counts match reality
- Phase 4: Run `/project ask`, verify answer references real sessions
