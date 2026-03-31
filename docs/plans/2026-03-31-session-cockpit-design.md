# Session Cockpit Design

## Goal

Build a "Session Cockpit" -- a new CockpitApp frontend for amplifier-tui providing a focused single-session experience optimized for tmux, with block-level observability, side LLM conversations, and steering of the running main session.

## Background

The current amplifier-tui project has four frontends (TUI, Web, Desktop, TmuxApp), but none provide a focused single-session experience with deep observability into the conversation stream. Users working in tmux need a streamlined interface that lets them inspect individual blocks (tool calls, assistant responses, thinking), ask side questions about what the agent is doing, and steer the session mid-flight -- all without leaving the terminal.

## Approach

**Approach B: New CockpitApp on `feat/web-native-frontend` branch.** Cherry-pick tmux-mode concepts (single-session, stripped layout, tmux integration) but write against current `SharedAppBase`. Extract duplicated worker methods into `SharedAppBase`. This becomes the fifth frontend alongside TUI, Web, Desktop, and old TmuxApp.

## Architecture & Layout

CockpitApp inherits `SharedAppBase` + 6 core command mixins + `CockpitCommandsMixin` (tmux commands).

### Two-Zone Layout

| Zone | Description |
|------|-------------|
| **Status bar** (1 line) | Session ID, model, state, tokens |
| **Main panel** | Conversation stream with clickable block widgets |
| **Inspector panel** | Hidden by default; shown right or bottom (user preference, changeable via slash command) |
| **Input area** | Sends to main session when inspector closed; directed to inspector when open |

A visual indicator shows the current input target (main session vs. inspector).

### Entry Points

- `--cockpit` flag (explicit)
- Auto-detect `$TMUX` environment variable
- `--no-cockpit` override to suppress auto-detection

### Tmux Integration

- `@amp_session_id` pane variable for auto-resume across pane restarts
- BEL character on turn completion for tmux alert integration
- `/shell` command for quick shell-out

## Components

### ChatBlock Widget

Wraps every event in the conversation stream. Thin `Vertical` container with:

- `block_id`: sequential integer
- `block_type` enum: `user`, `assistant`, `thinking`, `tool_call`, `tool_result`, `agent_delegation`, `system`
- `turn_index`: conversational turn number
- `on_click` -> `BlockSelected` message
- Hover/selected visual state

Wraps existing widgets (`UserMessage`, `AssistantMessage`, `Collapsible`). Inner rendering is unchanged.

#### Block Metadata

`self._blocks: list[BlockInfo]` dataclass with:
- `block_id`
- `block_type`
- `turn_index`
- `summary`
- `content` reference

#### Streaming

`block_index` passed through `_on_stream_block_start`/`delta`/`end` (currently discarded; 2-line fix to wire through).

#### Performance

~600 DOM nodes for a 30-turn conversation. Textual handles this fine.

### Inspector Panel

Three sub-areas:

1. **Block detail area**: full content of current/pinned block in `ScrollableContainer`
2. **Status line**: displays mode and position
   - `[LIVE] thinking... (block 14/14)`
   - `[PINNED] tool_call: grep (block 8/14)`
   - `[ASK] waiting...`
3. **Input area**: compact `TextArea` (1-3 lines) with distinct border color

#### Inspector Commands

| Command | Behavior |
|---------|----------|
| Free text + Enter | Steer (graceful inject into main session) -- **default** |
| `/steer text` | Same as free text (explicit) |
| `/ask question` | Sent to side LLM session with pinned/current block context |
| `/prev` | Previous block |
| `/next` | Next block |
| `/search term` | Search backward (default) |
| `/search forward term` | Search forward |
| `/help` | List commands |

#### Open Modes

- **Keystroke**: opens in live mode (follows current active block)
- **Click block** in main panel: opens in pinned mode (locked to that block)
- Closing and reopening returns to live mode

### Side LLM Session

Lazily created on first `/ask`. Uses same config as main session. Persists for inspector lifetime.

#### /ask Context Injection

Assembled from the pinned/current block:
- Block type
- Content (tool name/args/result, or message text)
- User question

Response rendered in the inspector detail area.

### Steering Queue

`self._steer_queue: deque[str]` -- main session checks at pause points (between tool calls, before next LLM turn). Steer messages injected as user messages.

When idle: steer becomes the regular next user message.

## Data Flow

```
User Input
    │
    ├─ Inspector closed ──> Main session (normal message)
    │
    └─ Inspector open
         │
         ├─ Free text / /steer ──> self._steer_queue
         │                              │
         │                              └──> Main session checks at pause points
         │                                   └──> Injected as user message
         │
         └─ /ask question ──> Side LLM session (lazy-created)
                                  │
                                  ├── Context: block type + content + question
                                  │
                                  └── Response ──> Inspector detail area
```

Block creation flow:

```
Stream events (_on_stream_block_start/delta/end)
    │
    └──> ChatBlock widget created with block_id, block_type, turn_index
              │
              ├──> Appended to main panel conversation stream
              ├──> Registered in self._blocks: list[BlockInfo]
              └──> If inspector in LIVE mode, inspector follows to latest block
```

## SharedAppBase Extraction

To keep CockpitApp lean (~500-600 lines), extract shared worker methods into `SharedAppBase`:

### Moves to SharedAppBase

1. `_init_amplifier_worker` -> `_init_session(resume_id=None)` + `_on_session_ready()` hook
2. `_send_message_worker` -> `_submit_message(text, conversation_id)` + `_on_message_sent()` hook
3. `block_index` passthrough in streaming callbacks

### Stays Frontend-Specific

- `compose()`
- Streaming display methods
- Slash command dispatch
- Panel management

## Error Handling

- **Side session failure**: Error displayed in inspector detail area; main session unaffected
- **Steer injection timing**: If main session is mid-LLM-turn, steer queues until next pause point; no interruption of active generation
- **Tmux auto-detect failure**: Falls back to standard TUI mode with warning
- **Block click on stale block**: Inspector shows last-known content with `[STALE]` indicator
- **Session resume**: `@amp_session_id` pane variable lookup fails gracefully; prompts for new session

## Testing Strategy

### Unit Tests
- `BlockInfo` dataclass construction and field validation
- Block registry operations (add, lookup by id, lookup by turn)
- Steering queue: enqueue, dequeue at pause points, behavior when idle

### Widget Tests (Textual Pilot)
- `compose()` produces expected layout
- Inspector toggle (open/close) and position (right/bottom)
- Block click dispatches `BlockSelected` message
- Keybinding routing (input target indicator switches correctly)

### Integration Tests (Mock Bridge)
- Full flow: send message -> stream events -> blocks created -> inspector pin -> navigate
- Block creation from streaming events with correct `block_id`/`block_type`
- Inspector pin and navigate across blocks

### Side Session Tests
- Context assembly from pinned block (tool_call, assistant, etc.)
- Response rendering in inspector detail area
- Lazy creation (no session until first `/ask`)

## Open Questions

1. **Steer injection mechanism**: Verify `LocalBridge` supports `inject_user_message` mid-loop, or whether queuing must happen at the app level
2. **Inspector keystroke**: `Ctrl-I`, `Ctrl-P`, or `Tab` -- finalize during implementation based on conflict testing
3. **Side session cleanup**: Current plan is keep-alive for app lifetime with lazy creation; confirm no resource leak concerns
4. **History replay on resume**: How to render existing transcript into `ChatBlock` widgets when resuming a session via `@amp_session_id`
