# Web-Native Frontend Design

## The Problem

The current web frontend is a "terminal emulator in a browser." Every command returns
text through `_add_system_message()`, the JS renders system messages as `textContent`
(not HTML), and the result is raw markdown blobs instead of proper web UI. Keyboard
shortcuts conflict with browsers. There's no sidebar, no session list, no command
palette — just a chat box.

But the **backend is solid**. SharedAppBase + 16 command mixins + SessionManager +
WebSocket transport all work. The problem is entirely in the presentation layer.

## Design Philosophy

**Web-native, not TUI-clone.** The web frontend should:
- Use the same command pipeline but render results as proper HTML
- Have web-native chrome (sidebar, panels, command palette)
- Use click-based interactions where the TUI uses keyboard shortcuts
- Feel like a modern chat app (think: ChatGPT, Cursor chat), not a terminal

**Incremental, not rewrite.** The existing ~2000 lines of web code are mostly right.
We fix rendering first, then add structure, then add chrome.

## Architecture

### Current Flow (broken)
```
Command mixin → _add_system_message("markdown text")
             → WebSocket {type: "system_message", text: "..."}
             → JS: body.textContent = text  ← BUG: raw text, not HTML
```

### Target Flow (two tiers)

**Tier 1 — Markdown rendering (fixes 80% of issues):**
```
Command mixin → _add_system_message("markdown text")
             → WebSocket {type: "system_message", text: "..."}
             → JS: body.innerHTML = renderMarkdown(text)  ← renders tables, bold, etc.
```

**Tier 2 — Structured events (for interactive commands):**
```
WebApp override → _send_event({type: "session_list", sessions: [...]})
               → JS: renderSessionList(data)  ← proper clickable UI component
```

Tier 1 is a one-line fix. Tier 2 is progressive enhancement for specific commands.

---

## Implementation Stages

### Stage 1: Fix Rendering (30 min)

**The #1 bug:** `app.js` line 174 uses `body.textContent = text` for system messages.
Change it to use `renderMarkdown()` like assistant messages do.

File: `amplifier_tui/web/static/app.js`, in `appendMessage()`:
```javascript
// BEFORE (line 171-175):
if (role === "assistant") {
  body.innerHTML = renderMarkdown(text);
} else {
  body.textContent = text;
}

// AFTER:
if (role === "user") {
  body.textContent = text;  // User messages stay plain text
} else {
  body.innerHTML = renderMarkdown(text);  // Everything else renders markdown
}
```

This single change fixes:
- /help renders as a proper table with bold headers
- /stats renders with formatting
- /diff renders with syntax highlighting
- /info renders structured data properly
- Every command that outputs markdown now "just works"

**Verify:** Run the web server, type `/help` — should show a nicely formatted table.

### Stage 2: Sidebar + Session Management (2-3 hours)

Add a collapsible sidebar for sessions and navigation.

**HTML changes** (`templates/index.html`):
Add a sidebar element inside `#app`, before `#main`:
```html
<aside id="sidebar" class="sidebar hidden">
  <div class="sidebar-header">
    <h3>Sessions</h3>
    <button id="new-session-btn" class="sidebar-action">+ New</button>
  </div>
  <div id="session-list" class="sidebar-list"></div>
  <div class="sidebar-footer">
    <button id="sidebar-close" class="sidebar-action">Close</button>
  </div>
</aside>
```

Add a sidebar toggle button to the header:
```html
<button id="sidebar-toggle" class="header-btn" title="Sessions (Ctrl+Shift+B)">
  <!-- hamburger icon -->
</button>
```

**CSS changes** (`static/style.css`):
```css
/* Sidebar */
.sidebar {
  width: 280px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
  transition: width 0.2s ease, opacity 0.2s ease;
}
.sidebar.hidden {
  width: 0;
  opacity: 0;
  pointer-events: none;
}

/* #main becomes a row with sidebar */
#main {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: row;  /* sidebar + chat side by side */
}
```

**JS changes** (`static/app.js`):
- Add sidebar toggle logic
- Handle new event type `session_list`:
```javascript
case "session_list":
  renderSessionList(ev.sessions);
  break;
```
- `renderSessionList()` creates clickable items that send `{type: "switch_session", id: "..."}`

**Python changes** (`web_app.py`):
Override `/sessions` command to send structured data:
```python
def _cmd_sessions(self, text: str = "") -> None:
    sessions = self._list_recent_sessions()  # existing method
    self._send_event({
        "type": "session_list",
        "sessions": [
            {"id": s.id, "title": s.title, "date": s.date, "active": s.is_current}
            for s in sessions
        ]
    })
```

Add WebSocket handler for `switch_session` message type in `handle_ws_message()`.

### Stage 3: Command Palette (1-2 hours)

Replace slash commands with a Ctrl+K command palette (the web-native pattern).

**Trigger:** Ctrl+K (or Cmd+K on Mac) opens an overlay with:
- Search/filter input
- List of all commands with descriptions
- Click or Enter to execute
- Escape to dismiss

This replaces the need for /help entirely — the command palette IS the help.

**Implementation:**
- Pure JS overlay (no framework needed)
- Command registry: array of `{name, description, action}` objects
- Fuzzy filter on keystroke
- The `/` key in the input still works as before (type `/help` Enter)
- Command palette is additive, not replacement

```javascript
// Command palette data (mirror the Python command list)
var commandPalette = [
  { name: "New Session",    cmd: "/new",       keys: "Ctrl+Shift+N", category: "session" },
  { name: "Clear Chat",     cmd: "/clear",     keys: "Ctrl+Shift+K", category: "session" },
  { name: "Sessions",       cmd: "/sessions",  keys: "",              category: "session" },
  { name: "Git Status",     cmd: "/git",       keys: "Ctrl+Shift+G", category: "git" },
  { name: "Token Usage",    cmd: "/tokens",    keys: "",              category: "info" },
  { name: "Statistics",     cmd: "/stats",     keys: "",              category: "info" },
  // ... all commands
];
```

### Stage 4: Structured Events for Key Commands (2-3 hours)

Override specific commands in `WebApp` to send structured events instead of text:

| Command | Event Type | Payload | JS Renders As |
|---------|-----------|---------|---------------|
| `/sessions` | `session_list` | `{sessions: [...]}` | Clickable list in sidebar |
| `/stats` | `stats_panel` | `{duration, tokens, tools, ...}` | Formatted stats card |
| `/tokens` | `token_usage` | `{input, output, cost, model}` | Token meter/bar |
| `/agents` | `agent_tree` | `{agents: [...], active: "..."}` | Tree visualization |
| `/dashboard` | `dashboard` | `{stats: {...}}` | Dashboard panel |
| `/git` | `git_status` | `{branch, changed, staged, ...}` | Git status card |
| `/help` | (not needed) | - | Markdown rendering + command palette handle this |

**Python pattern** (in `web_app.py`):
```python
def _cmd_stats(self, text: str = "") -> None:
    # Gather data (reuse existing logic from mixin)
    elapsed = time.monotonic() - self._session_start_time
    # ... gather stats ...

    # Send structured event for web
    self._send_event({
        "type": "stats_panel",
        "duration": format_duration(elapsed),
        "messages": self._user_message_count,
        "tokens": {"input": inp, "output": out},
        "tools": dict(self._tool_usage),
    })
```

**JS pattern:**
```javascript
case "stats_panel":
  renderStatsPanel(ev);  // Creates a nicely formatted card
  break;
```

### Stage 5: Web-Appropriate Keyboard Shortcuts (1 hour)

**Problem:** Browser reserves Ctrl+B, Ctrl+D, Ctrl+F, Ctrl+H, Ctrl+N, Ctrl+T, Ctrl+W.
Even Ctrl+Shift+S is "Save As" in many browsers.

**Solution:** Use the command palette as the primary interaction, with minimal safe shortcuts:

| Shortcut | Action | Rationale |
|----------|--------|-----------|
| `Ctrl+K` / `Cmd+K` | Command palette | Standard web pattern (VS Code, Slack, Linear) |
| `Escape` | Close palette/clear input | Universal |
| `/` (when not in input) | Focus input + start command | Vim/Slack pattern |
| `Enter` | Send message | Universal |
| `Shift+Enter` | Newline | Universal |
| `Up/Down` in input | Command history | Shell pattern |
| `Tab` on `/text` | Autocomplete command | Shell pattern |

That's it. No Ctrl+Shift combos. The command palette handles everything else via
click or search-then-Enter.

### Stage 6: Polish and Responsive (2 hours)

- Mobile-friendly sidebar (overlay instead of push)
- Touch-friendly tap targets (44px minimum)
- Dark/light theme toggle in header
- Copy button on code blocks
- Collapsible tool call details (already works)
- Session title in header bar
- Favicon and proper `<title>` updates

---

## Keyboard Interaction Model

```
                    ┌─────────────────────────┐
                    │     Command Palette      │
                    │  ┌─────────────────────┐ │
  Ctrl+K ─────────►│  │ Search commands...   │ │
                    │  └─────────────────────┘ │
                    │  > New Session    Ctrl+N  │
                    │    Clear Chat             │
                    │    Git Status             │
                    │    Token Usage            │
                    │    Statistics             │
                    │    ...                    │
                    └─────────────────────────┘

  / (outside input) ──► Focus input with "/" prefix
  Enter             ──► Send message (or execute command if /prefixed)
  Escape            ──► Close palette / clear input
  Up/Down           ──► Command history (in input)
  Tab               ──► Autocomplete /command (in input)
```

The command palette eliminates the need for keyboard shortcuts entirely. Users
discover commands by searching, not by memorizing Ctrl+Shift combos.

---

## File Change Summary

| File | Changes |
|------|---------|
| `app.js` | Fix markdown rendering, add sidebar logic, command palette, structured event handlers |
| `style.css` | Sidebar styles, command palette overlay, stats/dashboard card styles |
| `index.html` | Add sidebar HTML, command palette overlay, sidebar toggle button |
| `web_app.py` | Override key commands to send structured events, add WS handlers for session switching |

**What does NOT change:** SharedAppBase, command mixins, SessionManager, server.py,
the WebSocket transport protocol. The backend stays as-is.

---

## Using amplifier-ux-analyzer for Iteration

The repo at `~/dev/ANext/amplifier-ux-analyzer` can validate visual quality:

1. **Take a baseline screenshot** of the current (broken) state
2. **After each stage**, screenshot and compare:
   ```bash
   amplifier-ux-analyzer compare baseline.png current.png --json
   ```
3. **For style validation**, analyze the screenshot:
   ```bash
   amplifier-ux-analyzer analyze screenshot.png -o analysis.json -v annotated.png
   ```
   This extracts colors, layout regions, text (OCR), and UI elements.

4. **For iterative refinement**, use the roundtrip recipe:
   ```bash
   amplifier tool invoke recipes operation=execute \
     recipe_path=@ux-analyzer:recipes/roundtrip.yaml \
     context='{"reference_image": "reference.png", "max_iterations": 3}'
   ```

The ux-analyzer CLI works today. The roundtrip recipe needs `agent-browser` installed.

For manual iteration: screenshot in browser (F12 → device toolbar → capture), then
run analysis to get structured feedback on layout, colors, and element positioning.

---

## What Success Looks Like

After all 6 stages:

1. `/help` shows a beautifully formatted table (Stage 1)
2. Sessions are visible in a sidebar, clickable to switch (Stage 2)
3. Ctrl+K opens a searchable command palette (Stage 3)
4. `/stats`, `/tokens`, `/agents` show rich formatted cards (Stage 4)
5. No keyboard shortcut conflicts with browsers (Stage 5)
6. Works on mobile, has copy buttons, looks polished (Stage 6)

The web frontend feels like a native chat app that happens to support slash commands,
not a terminal emulator that happens to run in a browser.

---

## Implementation Notes for the Builder

### Priority Order
Stage 1 is a one-line fix and should be done first — it fixes 80% of the visual
issues immediately. Stage 2 (sidebar) is the next highest value. Stage 3 (command
palette) is the signature "web-native" feature. Stages 4-6 are progressive polish.

### Testing Approach
After each stage:
1. Start the web server: `python -m amplifier_tui.web` (or however it's launched)
2. Open browser to localhost
3. Test the specific commands affected
4. Screenshot for comparison if using ux-analyzer
5. Commit when stable

### Existing Code to Preserve
- The WebSocket protocol is stable — don't change event format for existing types
- The command mixin pipeline works — add structured events as OVERRIDES in WebApp,
  don't modify the mixins themselves
- The CSS variables and design tokens are good — extend, don't replace
- Tool call rendering (collapsible details) already works well

### Existing CSS Already Supports
The `style.css` already has styles for tables (`.message-body table`), code blocks,
headings, lists, blockquotes, and links. Once system messages render through
`renderMarkdown()`, all of this "just works" with zero CSS changes. This is why
Stage 1 is so high-impact for one line of code.
