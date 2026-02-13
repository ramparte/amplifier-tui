# Project Intelligence: Implementation Context

This document provides everything a future implementation session needs to start working immediately. Read this first, then DESIGN.md for the full vision, then IMPLEMENTATION.md for the task list.

---

## What This Is

A multi-phase feature set that makes "project" a first-class concept in the TUI and web app. Sessions get auto-tagged with labels, the sidebar becomes tag-aware, and you can ask questions like "what needs attention in tui?" and get answers synthesized from local session data.

**The user works in clusters of amplifier sessions** -- small focused sessions that together serve a larger goal (like "improve the TUI" or "rebuild the web frontend"). Today each session is an island. This feature connects them.

---

## Current Codebase Orientation

### Key Files You'll Touch

| File | What It Does | Why It Matters |
|------|-------------|----------------|
| `amplifier_tui/app.py` | Main TUI application | Contains sidebar, session list, filtering, display label |
| `amplifier_tui/core/persistence/tags.py` | TagStore | Already stores `{sid: [tag, ...]}` in JSON. Multi-tag per session already works. |
| `amplifier_tui/core/features/session_scanner.py` | Session state detection | Knows RUNNING/IDLE/DONE/STALE via events.jsonl tail-reading |
| `amplifier_tui/core/features/session_summarizer.py` | LLM session summaries | 8-word status lines via haiku. Pattern to follow for auto-tagger. |
| `amplifier_tui/core/session_manager.py` | Session lifecycle | `list_all_sessions()` returns session metadata. Does NOT return tags or state. |
| `amplifier_tui/core/preferences.py` | User preferences | YAML-based, surgical updates. Add new preference keys here. |
| `amplifier_tui/commands/persistence_cmds.py` | `/tag` command | Existing tag add/remove/list. Wire auto-tagger awareness here. |
| `amplifier_tui/commands/monitor_cmds.py` | `/monitor` command | Timer architecture pattern to follow. 2s fast / 15s slow timers. |
| `amplifier_tui/core/shared_app_base.py` | Shared base for TUI + web | Command mixins go here. New `/project` mixin inherits from this. |
| `amplifier_tui/web/web_app.py` | Web app | Has all persistence stores, stubs session list. Being rebuilt. |

### Key Methods to Understand

**Read these before starting Phase 1:**

| Method | Location | What It Does |
|--------|----------|-------------|
| `_filter_sessions()` | `app.py` ~line 2114 | Filters sidebar by query. Matches name/id/project. **Add tag matching here.** |
| `_session_display_label()` | `app.py` ~line 2070 | Builds the text shown per session: `"{pin}{date}  {label}"`. **Add tags here.** |
| `_populate_session_list()` | `app.py` ~line 2105 | Builds the sidebar tree. Groups by project. **Add tag display + project counts here.** |
| `_sort_sessions()` | `app.py` ~line 2092 | Sorts by date/name/project. **Add tag sort mode here.** |
| `TagStore.all_tags()` | `tags.py` line 64 | Returns `{tag: count}` sorted by frequency. **Use for auto-tagger vocabulary.** |
| `TagStore.sessions_with_tag()` | `tags.py` line 72 | Returns session IDs with a given tag. **Currently unused in UI.** |

### Data Locations

| Data | File | Format |
|------|------|--------|
| Session tags | `~/.amplifier/tui-session-tags.json` | `{sid: [tag, ...]}` |
| Session names | `~/.amplifier/tui-session-names.json` | `{sid: name}` |
| Session titles | `~/.amplifier/tui-session-titles.json` | `{sid: title}` |
| Pinned sessions | `~/.amplifier/tui-pinned-sessions.json` | `[sid, ...]` |
| Preferences | `~/.amplifier/tui-preferences.yaml` | YAML with surgical update support |
| Sessions | `~/.amplifier/projects/*/sessions/*/` | transcript.jsonl, metadata.json, events.jsonl |

### Patterns to Follow

**The SessionSummarizer pattern** is the template for AutoTagger:
- Background processing with queue (`_pending` list)
- Throttled execution (`process_pending(max_count=3)`)
- Timer-driven (slow timer, 15-30s)
- LLM via injected callable (`summarize_fn` / `tag_fn`)
- Graceful degradation (works without LLM, just doesn't auto-tag)
- Cache by `(session_id, mtime)` to avoid re-processing unchanged sessions

**The monitor timer pattern** is the template for background refresh:
- Fast timer (2s): filesystem scan, cheap
- Slow timer (15s): LLM calls, expensive
- Timers started on feature activation, stopped on close

**The command mixin pattern** is how to add `/project`:
- Create `ProjectCommandsMixin` class
- Add to `SharedAppBase` inheritance chain
- Register commands in the mixin
- Works in both TUI and web automatically

---

## Architecture Decisions Already Made

1. **Tags are labels, not hierarchy.** Multiple tags per session. Already supported by TagStore. No schema change.

2. **Auto-tagging reuses existing vocabulary.** The prompt includes `TagStore.all_tags()` so the LLM prefers tags already in use. This keeps the tag space coherent without a fixed taxonomy.

3. **Project = working directory.** No new "project" entity. `project_path` on every session is the grouping key. `ProjectAggregator` is a view over existing data.

4. **All data stays local.** No new external calls. Auto-tagging uses haiku (same as summarizer). Cross-session queries use sonnet.

5. **Background everything.** Auto-tagging, summarization, aggregation -- all async, timer-driven, never blocking the UI.

6. **Web is suggestive.** The web app is being rebuilt. Backend components (AutoTagger, ProjectAggregator, ProjectIntelligence) are shared. Web-specific rendering adapts to whatever the web app looks like when you get to Phase 5.

---

## Phase Execution Guide

### Phase 1: Start Here

This is the highest-value, lowest-risk phase. Pure UI wiring of existing data.

**Start by reading:**
1. `amplifier_tui/core/persistence/tags.py` (76 lines, quick read)
2. The `_filter_sessions()` method in `app.py`
3. The `_session_display_label()` method in `app.py`
4. The `_populate_session_list()` method in `app.py`

**Then implement in order:** Task 1.1 -> 1.2 -> 1.3 -> 1.4

**Test manually:** Add some tags to existing sessions (`/tag add web`, `/tag add sidebar`), then verify they appear in the sidebar and filter works.

### Phase 2: Auto-Tagging

**Start by reading:**
1. `amplifier_tui/core/features/session_summarizer.py` (the pattern to follow)
2. `amplifier_tui/commands/monitor_cmds.py` (timer architecture)

**Key design choice:** The auto-tagger prompt. Get this right and the tag quality is good. Get it wrong and you get useless tags. The prompt should:
- Include the existing tag vocabulary (so it reuses known tags)
- Include the project name (context)
- Include the transcript tail (what the session is about)
- Ask for 1-3 short tags (1-2 words each)
- Be explicit about format (one tag per line, no punctuation)

### Phase 3: Project Aggregation

This is where it starts to feel like a real feature. The `/project` command gives you a dashboard-in-text.

**Key challenge:** `SessionScanner.scan()` returns top N sessions globally, not filtered by project. You'll need to either:
- Scan all sessions and group afterward (may be slow for many sessions)
- Add a `project_path` filter to `scan()` (cleaner)
- Cache scanner results and filter from cache

### Phase 4: Cross-Session Intelligence

The "wow" factor. Natural language questions about your project, answered from local data.

**Key challenge:** Context assembly. You need to gather enough session context to answer the question without overwhelming the LLM. Strategy:
- Project summary (structured data, cheap)
- Recent session summaries (8 words each, cheap)
- Transcript tails only if needed (expensive, use sparingly)

### Phase 5: Web

Assess first, then adapt. The backend components from Phases 1-4 are shared. The web surface is whatever makes sense given the web app's architecture at that point.

---

## Things to Watch Out For

### Performance

- `TagStore.load()` reads the entire JSON file. Fine for <1000 sessions. If it becomes slow, add in-memory caching with mtime-based invalidation.
- `SessionScanner.scan()` does filesystem stat calls. Scanning 50+ sessions takes ~200ms. Don't do this on every keystroke in the filter.
- Auto-tagger LLM calls are ~500ms each. Always background, never inline.

### Concurrency

- TagStore does load-modify-save on every mutation. No locking. If two processes write simultaneously, last write wins. This is fine for current usage (single TUI instance) but worth noting if the web app also writes tags.
- Multiple TUI instances could conflict on `tui-session-tags.json`. Consider file-level locking if this becomes an issue.

### The `_matches()` Closure

The filter function `_matches()` is called for every session on every keystroke. Keep it fast:
- Load tag data ONCE before the loop, not inside `_matches()`
- Use simple string containment (`q in t`), not regex
- The `#` prefix for tag-only search should short-circuit other checks

### Tree Widget Limits

The Textual Tree widget can handle ~500 nodes fine. Beyond that, consider virtual scrolling or pagination. Current session limits (`list_all_sessions(limit=50)`) keep this manageable.

### Web App Stub

`web_app.py:_populate_session_list()` is `pass`. The web app renders session lists client-side via WebSocket events. Any server-side session data needs to be pushed as WebSocket messages, not rendered into a widget.

---

## File Creation Checklist

New files to create across all phases:

```
amplifier_tui/core/features/auto_tagger.py      # Phase 2
amplifier_tui/core/features/project_aggregator.py # Phase 3
amplifier_tui/core/features/project_intelligence.py # Phase 4
amplifier_tui/core/features/project_search.py     # Phase 4
amplifier_tui/commands/project_cmds.py             # Phase 3
```

Files to modify (all phases):

```
amplifier_tui/app.py                              # Phase 1, 3
amplifier_tui/core/persistence/tags.py            # Phase 2 (minor)
amplifier_tui/core/preferences.py                 # Phase 1, 2
amplifier_tui/commands/persistence_cmds.py        # Phase 2
amplifier_tui/core/shared_app_base.py             # Phase 3
amplifier_tui/web/web_app.py                      # Phase 5
```

---

## Open Questions for Implementation

These are decisions deferred to the implementation session:

1. **Tag display style in sidebar:** Inline after session name (compact) vs child node only (clean). DESIGN.md recommends inline with 2-tag limit. Try it and see how it looks.

2. **Auto-tagger trigger:** Timer-based (process queue every 30s) vs event-based (trigger on session list refresh). Timer is simpler and matches the summarizer pattern.

3. **Scanner integration for project counts:** Show scanner state in sidebar headers only when monitor is active (cheap) vs always scan in background (complete but heavier). Start with "only when monitor is active" and upgrade if users want always-on.

4. **Cross-session search implementation:** grep on transcript.jsonl vs building a simple index. Start with grep (simpler, no new state) and optimize if too slow.

5. **Web app architecture:** The web app is being rebuilt. Phase 5 tasks are directional. Assess the web app's actual state before planning web work.
