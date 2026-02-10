# Amplifier TUI - Feature Roadmap

## Phase 1: Core Session Management
- [x] Start a new Amplifier session
- [x] Resume an existing session (by ID or "most recent")
- [x] Display session messages from transcript
- [x] Send user input to session
- [x] Stream assistant responses in real-time
- [x] Show session ID in UI

## Phase 2: Tool Rendering
- [x] Detect tool uses in streaming response
- [x] Render tool calls as collapsible blocks (gray border)
- [x] Show tool name and summary when collapsed
- [x] Expand tool blocks to see input/output
- [x] Show tool execution state (pending/running/complete/error)

## Phase 3: Multi-Session Support
- [x] List available sessions in sidebar
- [x] Switch between sessions
- [x] Show session status (active/idle)
- [x] Start new session in background
- [x] Close sessions

## Phase 4: Amplifier-Specific Features
- [x] Show active bundle name
- [ ] Bundle switcher UI
- [x] Mode indicator (e.g., "planning mode" badge)
- [x] Mode toggle command
- [x] Sub-session tree view (show delegate hierarchy)

## Phase 5: Visual Polish
- [x] Thinking/working indicator while agent responds
- [x] Status footer (session info, token count)
- [x] Keyboard shortcuts (Ctrl+N new session, Ctrl+W close)
- [x] Command palette (`/` commands)
- [x] Session search/filter

## Phase 6: Advanced Features
- [x] Diff viewer for file changes (from tool calls)
- [x] Recipe execution panel
- [x] Hook event log viewer (tool log)
- [x] Session history browser
- [x] Export session to markdown

## Phase 7: Git Integration
- [x] Git status in footer
- [ ] Worktree management
- [x] Commit helper

## Nice-to-Have
- [ ] Image attachment support
- [x] Syntax highlighting in code blocks
- [x] Copy message to clipboard
- [x] Session bookmarks/favorites
- [x] Custom themes
