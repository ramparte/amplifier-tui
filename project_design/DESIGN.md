# Project Intelligence: Design Document

## Vision

Amplifier sessions are worked in clusters -- small, focused sessions that together serve a larger goal like "improve the TUI sidebar" or "rebuild the web frontend." Today, each session is an island. The data to connect them exists locally (transcripts, metadata, tags, scanner state), but nothing synthesizes it into project-level understanding.

This design introduces **Project Intelligence** -- the ability to ask coherent questions like "what needs attention in tui?", see all open sessions for a project, and eventually surface this in a web experience.

## Design Principles

1. **Tags are labels, not hierarchy.** A session can have multiple tags. Tags are flat, overlapping, and user-controlled. Think Gmail labels, not folders.

2. **Auto-tag by default, manual override.** The system generates tags automatically using existing user tags as a vocabulary plus its own judgment. Users can always add/remove tags manually.

3. **Surface existing data first.** Most of the intelligence comes from aggregating data that already exists (scanner state, transcripts, metadata). New data collection is minimal.

4. **Project = working directory.** The `project_path` already tracked on every session is the natural project boundary. No new "project" entity needed -- it's an aggregation view.

5. **Web is suggestive.** The web app is being rebuilt. Web-related design here describes intent and data contracts, not specific UI. The implementation session will adapt to the web app's current state.

---

## Architecture Overview

Three layers, each building on the previous:

```
Layer 3: Cross-Session Intelligence
  "What did I accomplish in tui this week?"
  "What needs attention?"
  LLM synthesis across session summaries and transcripts
  
Layer 2: Project Aggregation
  /project command, project summary views
  Combines: sessions + tags + scanner state + summaries
  Project health: active/idle/stale/done counts
  
Layer 1: Tag & Filter Foundation
  Auto-tagging, tags in sidebar, tag-aware filtering
  The data backbone everything else builds on
```

---

## Layer 1: Tag & Filter Foundation

### 1.1 Tag Data Model

**Current state:** `TagStore` at `amplifier_tui/core/persistence/tags.py` already stores `{session_id: [tag1, tag2, ...]}` in `~/.amplifier/tui-session-tags.json`. Multiple tags per session are already supported. Tags are normalized (stripped, lowercased, `#` prefix removed).

**No schema change needed.** The existing data model already supports labels (multiple tags per session). The work is in surfacing and generating them.

### 1.2 Auto-Tagging System

**New component:** `amplifier_tui/core/features/auto_tagger.py`

**Approach:**

1. When a session is first displayed in the sidebar and has no tags, queue it for auto-tagging.
2. Auto-tagging reads the session transcript tail (similar to `SessionSummarizer` -- last 16KB) and the existing tag vocabulary (from `TagStore.all_tags()`).
3. An LLM (haiku-class, same as summarizer) generates 1-3 tags from:
   - The existing tag vocabulary (prefer reusing known tags for consistency)
   - Its own judgment if no existing tags fit
   - The session's project name as context
4. Auto-generated tags are stored in `TagStore` with a prefix convention: no prefix for auto-generated, no prefix for manual. They're indistinguishable on purpose -- the system bootstraps the vocabulary, the user refines it.

**Tag generation prompt design:**

```
You are tagging an Amplifier coding session for organization.

Existing tags in use (prefer these for consistency):
{tag_vocabulary}

Session project: {project_name}
Session transcript (recent):
{transcript_tail}

Generate 1-3 short tags (1-2 words each) that describe what this session
is about. Prefer existing tags when they fit. Output only the tags,
one per line, no punctuation or hashtags.
```

**Caching and throttling:**
- Cache: auto-tagged sessions tracked in a separate store (`~/.amplifier/tui-auto-tags-state.json`) mapping `{session_id: {tagged_at, mtime_at_tagging}}`. Re-tag only if transcript mtime has changed significantly (session resumed and more work done).
- Throttle: process at most 3 sessions per cycle (same pattern as `SessionSummarizer.process_pending()`).
- Timer: piggyback on the existing slow timer architecture (15s cycle) or a separate background timer.

**Integration with TagStore:**
- `AutoTagger` writes tags via `TagStore.add_tag()` -- no special API needed.
- `TagStore.get_tags()` returns both manual and auto tags (they're the same).
- Users can remove auto-generated tags freely; the auto-tagger won't re-add a tag the user explicitly removed (track removals in state file).

### 1.3 Tags in Sidebar Display

**Current:** `_session_display_label()` in `app.py` returns `"{pin}{date}  {label}"` where label is truncated to 28 chars.

**Change:** After the label, append tag indicators. Two options:

**Option A -- Inline tags (compact):**
```
01/15 14:02  Fix Auth Module  #auth #bug
```
Reduce label truncation to ~20 chars, append up to 2-3 tags in dim/muted style. The tree widget supports Rich markup, so tags can be styled differently: `[dim]#auth #bug[/dim]`.

**Option B -- Tags on hover/expand only:**
Keep the current display clean. Show tags in the collapsed child node alongside the session ID:
```
Fix Auth Module
  id: abc12345...  #auth #bug #p1
```

**Recommendation:** Option A with a limit of 2 tags shown inline (most frequent/recent first), with the full tag list visible in the child node. This keeps the sidebar scannable while making tags visible.

### 1.4 Tag-Aware Filtering

**Current:** `_filter_sessions()` in `app.py` matches against display label, session ID, and project name. Does not consult `TagStore`.

**Change:** Extend the `_matches()` closure to also check tags:

```python
def _matches(s: dict) -> bool:
    if not q:
        return True
    sid = s["session_id"]
    display = self._session_display_label(s, custom_names, session_titles)
    project = s["project"]
    tags = all_tags.get(sid, [])  # loaded once before the loop
    return (
        q in display.lower()
        or q in sid.lower()
        or q in project.lower()
        or any(q in t for t in tags)
    )
```

**Special prefix:** Consider a `#` prefix in the filter to mean "tag search only":
- `#auth` matches only sessions tagged `auth`
- `auth` matches sessions with "auth" anywhere (name, project, tags, ID)

**Performance:** `TagStore.load()` is a single JSON file read. Call once at filter start, not per-session.

### 1.5 Tag-Based Sort/Grouping Mode

**Current:** Three sort modes: `date`, `name`, `project`. Stored in preferences.

**Change:** Add `tag` as a fourth sort mode.

**Behavior when `session_sort: "tag"`:**
- Sessions grouped by their first (most relevant) tag
- Sessions with no tags grouped under "Untagged"
- Within each tag group, sorted by date descending
- Sessions with multiple tags appear under their first tag only (no duplication)

**Preference update:** Add `"tag"` to valid values in `preferences.py` validation and `_sort_sessions()` in `app.py`.

---

## Layer 2: Project Aggregation

### 2.1 Project Summary Data

**New component:** `amplifier_tui/core/features/project_aggregator.py`

This aggregates data from multiple existing sources into a project-level view:

```python
@dataclass
class ProjectSummary:
    project_path: str           # canonical path
    project_name: str           # human-readable label
    total_sessions: int
    active_sessions: int        # RUNNING state
    idle_sessions: int          # IDLE state
    stale_sessions: int         # STALE state
    done_sessions: int          # DONE state
    recent_sessions: list[SessionSummary]  # last 5-10, sorted by recency
    all_tags: dict[str, int]    # tag frequency within this project
    last_activity: datetime     # most recent session mtime
    needs_attention: list[str]  # session IDs that are stale or need action
```

```python
@dataclass
class SessionSummary:
    session_id: str
    short_id: str
    name: str                   # custom name or auto-title
    state: SessionState
    tags: list[str]
    activity: str               # from scanner/summarizer
    last_active: datetime
    age_str: str                # "3m", "1h", "2d"
```

**Data sources:**
- `SessionManager.list_all_sessions()` -- session list filtered by project_path
- `SessionScanner.scan()` -- state detection for active sessions
- `TagStore` -- tags per session
- `SessionSummarizer` -- activity summaries

**Caching:** Project summaries are transient (rebuilt on demand or every 30s). No persistence needed -- it's a view over existing data.

### 2.2 The `/project` Command

**New command mixin:** `amplifier_tui/commands/project_cmds.py`

**Usage:**
```
/project                    -- summary of current session's project
/project <name>             -- summary of named project
/project list               -- all projects with counts
/project attention           -- sessions needing attention across all projects
```

**Output format (for `/project`):**
```
Project: amplifier-tui
Path:    ~/dev/ANext/amplifier-tui

Sessions: 12 total
  Running: 2    Idle: 4    Stale: 1    Done: 5

Needs attention:
  [STALE] abc123  "Fix sidebar filter"  -- no activity for 4 hours
  
Recent activity:
  [RUNNING] def456  "Web frontend rebuild"  #web #frontend  -- 3m ago
  [IDLE]    ghi789  "Tag system design"     #tags           -- 2h ago
  [DONE]    jkl012  "Monitor panel CSS"     #monitor        -- yesterday

Top tags: #web (4), #sidebar (3), #monitor (2), #tags (2)
```

### 2.3 Project Summary in Sidebar Headers

**Current:** Sidebar groups show project name only, e.g., `"dev/amplifier-tui"`.

**Change:** Append session counts and state indicators:
```
dev/amplifier-tui (12)  2 running, 1 stale
```

Or more compact with icons:
```
dev/amplifier-tui (12)  2x running  1x stale
```

**Implementation:** In `_populate_session_list()`, after grouping sessions by project, compute counts from scanner data (if available) or just total count (cheap fallback).

**Performance consideration:** Getting scanner state for sidebar headers means running `SessionScanner.scan()` during sidebar population. This adds ~100ms for filesystem stat calls. Options:
- Use cached scanner data from the monitor if it's open
- Only show total count by default; show state breakdown if monitor is active
- Background-refresh with a timer (like the monitor's 2s cycle)

---

## Layer 3: Cross-Session Intelligence

### 3.1 Project Questions

**New capability:** Natural language queries about a project, synthesized from local session data.

**Interface options:**
- `/project ask <question>` -- in the TUI
- A project chat pane in the web app
- Integration with the main session (the AI can answer "what needs attention in tui?" by querying local data)

**How it works:**

1. Gather context for the project:
   - Project summary (from Layer 2)
   - Recent session summaries (from SessionSummarizer)
   - Optionally: transcript tails from recent sessions
2. Build a prompt with this context + the user's question
3. LLM (sonnet-class for quality) synthesizes an answer

**Example flow for "what needs attention in tui?":**

```
Context assembled:
  - 12 sessions, 2 running, 1 stale (4h idle on "fix sidebar filter")
  - Recent summaries: "Rebuilding web frontend", "Tag system design in progress"
  - Tags: #web, #sidebar, #monitor, #tags
  
LLM response:
  "The sidebar filter fix session (abc123) has been idle for 4 hours
   and may need to be resumed or closed. You have 2 active sessions
   working on the web frontend rebuild. The tag system design session
   is idle -- you may want to resume it after the current web work."
```

**Cost management:**
- Use cached summaries (no re-reading transcripts if summaries exist)
- Limit context to recent sessions (last 10-20 per project)
- Cache project-level synthesis for 5-10 minutes

### 3.2 Cross-Session Search

**Current:** The `>` prefix in the session filter searches transcript content, but only within the currently visible session list.

**Enhancement:** `/project search <query>` that searches across all session transcripts for a project:
- Uses grep-style search on `transcript.jsonl` files
- Returns matching sessions with context snippets
- "Did I already fix the filter bug?" becomes answerable

**Implementation:** This is mostly file I/O -- iterate session dirs for the project, grep transcript files. No LLM needed for basic search. LLM-powered semantic search is a future enhancement.

### 3.3 Project Activity Timeline

**For the web app:** A timeline view showing activity across all sessions in a project:

```
Today
  14:02  [RUNNING] "Web frontend rebuild"    #web     Currently streaming...
  12:30  [IDLE]    "Tag system design"        #tags    Designed auto-tagger
  09:15  [DONE]    "Monitor panel CSS"        #monitor Fixed panel sizing

Yesterday  
  16:45  [DONE]    "Sidebar filter cleanup"   #sidebar Added description search
  ...
```

**Data source:** `list_all_sessions()` + scanner state + summarizer activity. All local.

---

## Web App Considerations

The web app is being rebuilt. These are design intentions, not prescriptions.

### Data Contracts

The web app has access to all the same persistence stores (TagStore, SessionNameStore, etc.) and can instantiate SessionScanner/SessionSummarizer. The data layer is shared.

**Suggested WebSocket events for project features:**

```json
// Project summary update (push to client on timer)
{
  "type": "project_summary",
  "project_path": "/home/user/dev/amplifier-tui",
  "project_name": "amplifier-tui",
  "session_counts": {"total": 12, "running": 2, "idle": 4, "stale": 1, "done": 5},
  "needs_attention": ["abc123"],
  "top_tags": {"web": 4, "sidebar": 3}
}

// Session tag update (push when tags change)
{
  "type": "session_tags_updated",
  "session_id": "abc123",
  "tags": ["auth", "bug", "p1"]
}

// Auto-tag completion
{
  "type": "auto_tag_complete",
  "session_id": "abc123",
  "tags": ["web", "frontend"],
  "source": "auto"
}
```

### Web Surface Ideas

These are aspirational. The implementation session should adapt to the web app's actual architecture:

1. **Project cards** on a dashboard -- one card per project with health indicators (active/stale counts, last activity, top tags)
2. **Session list with tag pills** -- similar to GitHub issue labels, clickable to filter
3. **Project detail view** -- all sessions for a project, filterable by tag and state, with timeline
4. **"Needs attention" panel** -- stale sessions, long-idle sessions, sessions with errors
5. **Tag management UI** -- view all tags, merge similar tags, see tag frequency

### API Surface (if web moves to REST)

If the web app evolves toward a REST API:

```
GET /api/projects                        -- list all projects with summary counts
GET /api/projects/:path/sessions         -- sessions for a project (filterable)
GET /api/projects/:path/summary          -- full project summary
GET /api/sessions/:id/tags               -- tags for a session
PUT /api/sessions/:id/tags               -- set tags (auto or manual)
GET /api/tags                            -- all tags with counts
POST /api/projects/:path/ask             -- natural language project query
```

---

## Data Flow Diagram

```
                          User Actions
                              |
                    +---------+---------+
                    |                   |
               Manual tags         Session work
               /tag add X         (transcripts grow)
                    |                   |
                    v                   v
              +----------+      +---------------+
              | TagStore |      | transcript.jsonl|
              |  .json   |      | metadata.json   |
              +----------+      | events.jsonl    |
                    |           +---------------+
                    |                   |
                    |    +--------------+
                    |    |
                    v    v
              +------------------+
              |   AutoTagger     |  (reads transcripts + tag vocab,
              |                  |   writes to TagStore)
              +------------------+
                    |
                    v
     +-----------------------------+
     |     ProjectAggregator       |  (combines all sources)
     |  TagStore + SessionScanner  |
     |  + SessionSummarizer        |
     |  + list_all_sessions()      |
     +-----------------------------+
              |           |
              v           v
         TUI Views    Web Views
         /project     WebSocket events
         sidebar      project cards
         filter       timeline
```

---

## Privacy and Performance

### Privacy
- All data stays local. No new data leaves the machine.
- Auto-tagging uses a local LLM call (same as SessionSummarizer).
- Tag data in `tui-session-tags.json` is human-readable and editable.
- Users can disable auto-tagging in preferences.

### Performance
- Auto-tagging: haiku-class LLM, ~$0.001 per session, 3 at a time max.
- Project aggregation: pure local I/O, ~100-200ms for 50 sessions.
- Cross-session queries: sonnet-class LLM, ~$0.01-0.03 per query.
- All heavy operations are async/background -- never block the UI.

### Preferences

New preference keys:
```yaml
sidebar:
  session_sort: "date"          # date, name, project, tag
  show_tags: true               # show tag labels in sidebar
  show_project_counts: true     # show session counts in project headers

auto_tagging:
  enabled: true                 # auto-generate tags for untagged sessions
  max_tags: 3                   # max auto-generated tags per session
  reuse_vocabulary: true        # prefer existing tags over new ones
```
