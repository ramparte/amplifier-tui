# Desktop App Implementation Plan

Native Windows desktop frontend for amplifier-tui using PySide6 (Qt for Python).

## Architecture Summary

The TUI already has a clean three-layer architecture:

```
amplifier_tui/
  core/           <-- UI-agnostic: session management, commands, features, persistence
  app.py          <-- Textual TUI frontend
  widgets/        <-- Textual widgets
  commands/       <-- TUI-only command mixins (7)
  web/            <-- FastAPI/WebSocket web frontend
  desktop/        <-- NEW: PySide6 desktop frontend (this plan)
```

The `core/` package is completely framework-agnostic. Both the TUI and web frontends
inherit from `SharedAppBase` (in `core/app_base.py`) and mix in the 18 shared command
mixins from `core/commands/`. The desktop app does the same thing.

### What We Reuse (zero changes needed)

- `core/app_base.py` -- SharedAppBase with streaming callback wiring
- `core/session_manager.py` -- SessionManager + SessionHandle (Bridge API)
- `core/conversation.py` -- ConversationState dataclass
- `core/commands/` -- All 18 shared command mixins (slash commands)
- `core/features/` -- AgentTracker, ToolLog, RecipeTracker, BranchManager, etc.
- `core/persistence/` -- All 12 JSON persistence stores
- `core/preferences.py` -- User preferences
- `core/history.py` -- PromptHistory
- `core/constants.py`, `core/platform_info.py`, `core/environment.py`
- `core/transcript_loader.py` -- Session history parsing

### What We Build New

- `desktop/` package -- Qt app class, widgets, theming
- 14 abstract method implementations from SharedAppBase
- Qt widget equivalents of Textual widgets
- Qt signal/slot bridge for background thread streaming
- QSS dark theme
- Desktop-specific command mixins (equivalent of the 7 TUI-only ones)

### Reference Implementation

Use `web/web_app.py` as the template. It's a clean 1,335-line example of a
non-Textual frontend implementing SharedAppBase. The desktop app follows the
same pattern but renders to Qt widgets instead of WebSocket JSON.


## Phase 0: Project Scaffolding

**Goal:** PySide6 dependency, package structure, entry point, bare window launches.

### 0.1 Add optional dependency group to pyproject.toml

```toml
[project.optional-dependencies]
desktop = [
    "PySide6>=6.6",
]
```

Add entry point:

```toml
[project.scripts]
amplifier-desktop = "amplifier_tui.desktop:main"
```

Add package to setuptools:

```toml
[tool.setuptools]
packages = [
    # ... existing ...
    "amplifier_tui.desktop",
    "amplifier_tui.desktop.widgets",
]
```

### 0.2 Create directory structure

```
amplifier_tui/desktop/
  __init__.py          # main() entry point
  desktop_app.py       # DesktopApp class (SharedAppBase + QMainWindow)
  widgets/
    __init__.py
    chat_display.py    # Chat message rendering (QTextBrowser-based)
    chat_input.py      # Input area with slash completion
    message_widgets.py # User/Assistant/System/Error message formatters
    tab_bar.py         # Tab bar for conversations
    status_bar.py      # Bottom status bar
    panels.py          # TodoPanel, AgentTreePanel, ProjectPanel (QDockWidget)
    session_sidebar.py # Left session browser
    find_bar.py        # In-chat search
  commands/
    __init__.py
    display_cmds.py    # Desktop-specific display commands
    session_cmds.py    # Session management commands
    search_cmds.py     # Search commands
    export_cmds.py     # Export commands
  theme.py             # QSS dark theme + theme switching
  signals.py           # Qt signal definitions for thread marshaling
```

### 0.3 Minimal entry point

```python
# amplifier_tui/desktop/__init__.py
import sys

def main():
    from PySide6.QtWidgets import QApplication
    from amplifier_tui.desktop.desktop_app import DesktopApp

    app = QApplication(sys.argv)
    window = DesktopApp()
    window.show()
    sys.exit(app.exec())
```

### Success criteria
- `uv pip install -e ".[desktop]"` succeeds
- `amplifier-desktop` launches a blank QMainWindow and exits cleanly


## Phase 1: Core App Class + Abstract Method Stubs

**Goal:** DesktopApp subclasses SharedAppBase + all 18 core command mixins.
All 14 abstract methods implemented as stubs that print to console.
App initializes SessionManager and all shared state (preferences, persistence
stores, features) identically to WebApp.

### 1.1 Create signals.py -- Thread marshaling bridge

The streaming callbacks from SharedAppBase fire on a background thread.
Qt requires all widget updates on the GUI thread. Define custom signals:

```python
# amplifier_tui/desktop/signals.py
from PySide6.QtCore import QObject, Signal

class StreamSignals(QObject):
    """Signals for marshaling streaming events from background thread to GUI thread."""

    # Main display signals
    system_message = Signal(str, str)           # text, conversation_id
    user_message = Signal(str, str)             # text, conversation_id
    assistant_message = Signal(str, str)        # text, conversation_id
    error_message = Signal(str, str)            # text, conversation_id
    status_update = Signal(str, str)            # text, conversation_id
    processing_started = Signal(str, str)       # label, conversation_id
    processing_finished = Signal(str)           # conversation_id

    # Streaming signals (background thread -> GUI thread)
    block_start = Signal(str, str)              # conversation_id, block_type
    block_delta = Signal(str, str, str)         # conversation_id, block_type, accumulated_text
    block_end = Signal(str, str, str, bool)     # conversation_id, block_type, final_text, had_start
    tool_start = Signal(str, str, object)       # conversation_id, tool_name, tool_input
    tool_end = Signal(str, str, object, object) # conversation_id, tool_name, tool_input, result
    usage_update = Signal(str)                  # conversation_id
```

### 1.2 Create desktop_app.py -- Main app class

```python
# amplifier_tui/desktop/desktop_app.py
from PySide6.QtWidgets import QMainWindow
from amplifier_tui.core.app_base import SharedAppBase
from amplifier_tui.core.commands import (
    AgentCommandsMixin, BranchCommandsMixin, CompareCommandsMixin,
    ContentCommandsMixin, DashboardCommandsMixin, FileCommandsMixin,
    GitCommandsMixin, PersistenceCommandsMixin, PluginCommandsMixin,
    ProjectCommandsMixin, RecipeCommandsMixin, ReplayCommandsMixin,
    ShellCommandsMixin, ThemeCommandsMixin, TokenCommandsMixin,
    ToolCommandsMixin, WatchCommandsMixin,
)
from amplifier_tui.desktop.signals import StreamSignals

class DesktopApp(
    SharedAppBase,
    AgentCommandsMixin,
    BranchCommandsMixin,
    # ... all 18 core mixins (same list as WebApp) ...
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Amplifier")
        self.resize(1400, 900)

        # Thread-safe signal bridge
        self._signals = StreamSignals()

        # Initialize shared state (copy from WebApp.__init__)
        # - self._prefs = Preferences()
        # - self._history = PromptHistory()
        # - All persistence stores
        # - All feature trackers
        # - self.session_manager = SessionManager()
```

Reference: `web/web_app.py` lines 1-120 for the complete `__init__` pattern.
Copy the initialization sequence exactly, replacing WebSocket-specific bits.

### 1.3 Implement all 14 abstract methods as stubs

Each abstract method should:
1. Emit the corresponding signal from `self._signals`
2. Print to console for debugging

```python
    # --- Abstract method implementations ---

    def _all_conversations(self):
        return [tab.conversation for tab in self._tabs]

    def _add_system_message(self, text, *, conversation_id="", **kwargs):
        self._signals.system_message.emit(text, conversation_id)

    def _add_user_message(self, text, *, conversation_id="", **kwargs):
        self._signals.user_message.emit(text, conversation_id)

    def _add_assistant_message(self, text, *, conversation_id="", **kwargs):
        self._signals.assistant_message.emit(text, conversation_id)

    def _show_error(self, text, *, conversation_id="", **kwargs):
        self._signals.error_message.emit(text, conversation_id)

    def _update_status(self, text, *, conversation_id="", **kwargs):
        self._signals.status_update.emit(text, conversation_id)

    def _start_processing(self, label="", *, conversation_id="", **kwargs):
        self._signals.processing_started.emit(label, conversation_id)

    def _finish_processing(self, *, conversation_id="", **kwargs):
        self._signals.processing_finished.emit(conversation_id)

    # Streaming methods (called from background thread -- MUST use signals)
    def _on_stream_block_start(self, conversation_id, block_type):
        self._signals.block_start.emit(conversation_id, block_type)

    def _on_stream_block_delta(self, conversation_id, block_type, accumulated_text):
        self._signals.block_delta.emit(conversation_id, block_type, accumulated_text)

    def _on_stream_block_end(self, conversation_id, block_type, final_text, had_block_start):
        self._signals.block_end.emit(conversation_id, block_type, final_text, had_block_start)

    def _on_stream_tool_start(self, conversation_id, name, tool_input):
        self._signals.tool_start.emit(conversation_id, name, tool_input)

    def _on_stream_tool_end(self, conversation_id, name, tool_input, result):
        self._signals.tool_end.emit(conversation_id, name, tool_input, result)

    def _on_stream_usage_update(self, conversation_id):
        self._signals.usage_update.emit(conversation_id)
```

### 1.4 Message send flow

Implement `_handle_submitted_text(text)` following the WebApp pattern:

1. If starts with "/": route to `_handle_slash_command(text)`
2. Else: call `_add_user_message(text)`, then start background send
3. Background send: `_wire_streaming_callbacks()` then `session_manager.send_message()`
4. Use `QThread` or `threading.Thread` for the background work

Reference: `web/web_app.py` `handle_message()` at line ~1278.

### Success criteria
- App launches with blank window
- `DesktopApp.__init__` initializes all shared state without errors
- Typing in a temporary QLineEdit and pressing Enter triggers
  `_handle_submitted_text` which prints to console
- Session can be created via SessionManager (verify with print statements)


## Phase 2: Main Layout

**Goal:** The core visual structure with resizable panels.

### 2.1 Layout structure

```
QMainWindow
  +-- QMenuBar (minimal: File, Edit, View, Help)
  +-- Central Widget (QSplitter horizontal)
  |     +-- Left: Session sidebar (QTreeWidget, collapsible)
  |     +-- Center: QSplitter vertical
  |     |     +-- Tab bar (QTabWidget)
  |     |     |     +-- Each tab: QWidget with QVBoxLayout
  |     |     |           +-- Chat display (QTextBrowser or custom)
  |     |     +-- Input area (QTextEdit, resizable height)
  |     |     +-- Status bar row (QHBoxLayout with QLabels)
  +-- Right dock: TodoPanel (QDockWidget)
  +-- Right dock: AgentTreePanel (QDockWidget)
  +-- Right dock: ProjectPanel (QDockWidget)
```

### 2.2 Create the layout in desktop_app.py

Key Qt classes:

| TUI Concept | Qt Widget | Why |
|---|---|---|
| Main horizontal split | `QSplitter(Qt.Horizontal)` | Draggable divider between sidebar and chat |
| Session sidebar | `QTreeWidget` in left split | Collapsible, filterable session list |
| Chat area | `QSplitter(Qt.Vertical)` in center | Resizable split between chat display and input |
| Tab bar | `QTabWidget` | Native tab support with close buttons |
| Chat display | `QTextBrowser` per tab | Rich HTML rendering, smooth scrolling |
| Input area | `QTextEdit` | Multi-line with dynamic height |
| Status bar | `QStatusBar` or custom `QHBoxLayout` | Model, tokens, session info |
| Right panels | `QDockWidget` (3x) | Draggable, resizable, floatable, closable |

### 2.3 Panel resizing (key user requirement)

```python
# Main horizontal splitter -- sidebar : chat area
self._main_splitter = QSplitter(Qt.Horizontal)
self._main_splitter.addWidget(self._session_sidebar)
self._main_splitter.addWidget(self._center_area)
self._main_splitter.setSizes([250, 1150])  # default proportions
self._main_splitter.setStretchFactor(0, 0)  # sidebar doesn't stretch
self._main_splitter.setStretchFactor(1, 1)  # chat area stretches

# Vertical splitter -- chat display : input
self._chat_splitter = QSplitter(Qt.Vertical)
self._chat_splitter.addWidget(self._tab_widget)
self._chat_splitter.addWidget(self._input_area)
self._chat_splitter.setSizes([700, 150])
```

### 2.4 Tab data model

Create a desktop-specific TabState (like the TUI's `widgets/datamodels.py`):

```python
# amplifier_tui/desktop/widgets/tab_bar.py
@dataclass
class DesktopTabState:
    name: str
    tab_id: str
    conversation: ConversationState  # from core/
    input_text: str = ""             # preserved across tab switches
    custom_name: str = ""
    scroll_position: int = 0        # preserve scroll on tab switch
```

### Success criteria
- Window shows three-panel layout: sidebar | chat+input | dock panels
- All splitters are draggable (sidebar width, input height)
- QDockWidget panels can be dragged, resized, floated, closed
- Tab widget shows "Tab 1" with an empty chat area
- New tabs can be created (Ctrl+T or menu)
- Tabs can be closed (X button or Ctrl+W, except last tab)
- Window state (splitter sizes, dock positions) persists via QSettings


## Phase 3: Chat Display

**Goal:** Rich text rendering with markdown, code blocks, syntax highlighting,
and smooth scrolling. This is the hardest widget.

### 3.1 Chat display widget

Create `widgets/chat_display.py` using QTextBrowser as the base:

```python
class ChatDisplay(QTextBrowser):
    """Rich text chat display with markdown rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        # Smooth scrolling
        self.verticalScrollBar().setSingleStep(20)
```

### 3.2 Message rendering

Each message type gets a distinct visual treatment. Render messages as HTML
blocks appended to the QTextBrowser document:

- **User messages**: Light background block, right-aligned or left with user icon
- **Assistant messages**: Markdown-rendered HTML with syntax-highlighted code blocks
- **System messages**: Dimmed, monospace, smaller font
- **Error messages**: Red-tinted background
- **Tool calls**: Collapsible sections (use `<details>` or custom HTML)
- **Thinking blocks**: Dimmed/italic, collapsible

### 3.3 Markdown to HTML

Use Python `markdown` library (or `markdown-it-py` for speed) to convert
assistant responses to HTML:

```python
import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension

def render_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=[
        FencedCodeExtension(),
        CodeHiliteExtension(pygments_style="monokai", noclasses=True),
        "tables",
    ])
    return md.convert(text)
```

### 3.4 Streaming display

Connect signals to update the chat display incrementally:

```python
self._signals.block_delta.connect(self._on_block_delta)

def _on_block_delta(self, conversation_id, block_type, accumulated_text):
    tab = self._get_tab(conversation_id)
    if not tab:
        return
    display = self._get_chat_display(tab)
    if block_type == "thinking":
        display.update_thinking_block(accumulated_text)
    else:
        display.update_streaming_block(render_markdown(accumulated_text))
```

For streaming, maintain a "streaming cursor" -- the position in the document
where the current streaming block lives. On each delta, replace the content
at that position rather than appending. On block_end, finalize and clear
the cursor.

### 3.5 Auto-scroll behavior

- Auto-scroll to bottom when new content arrives IF user is already at bottom
- If user has scrolled up, do NOT auto-scroll (they're reading history)
- Show a "jump to bottom" floating button when scrolled up

```python
def _should_auto_scroll(self) -> bool:
    sb = self.verticalScrollBar()
    return sb.value() >= sb.maximum() - 50  # within 50px of bottom
```

### Success criteria
- User messages render with distinct styling
- Assistant messages render with proper markdown (headers, bold, lists, tables)
- Code blocks have syntax highlighting (Pygments)
- Streaming text appears incrementally without flicker
- Smooth scrolling with mouse wheel and scrollbar
- Auto-scroll works correctly (follows new content, stops when user scrolls up)
- Thinking blocks render dimmed/collapsible


## Phase 4: Input Area

**Goal:** Multi-line text input with slash command completion, key bindings,
and history navigation.

### 4.1 Input widget

Create `widgets/chat_input.py`:

```python
class ChatInput(QTextEdit):
    """Multi-line input with slash completion and key bindings."""

    submitted = Signal(str)  # emitted when user presses Enter to send

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Type a message or /command...")
        self.setMaximumHeight(200)  # grows with content, caps at 200px
        self.setAcceptRichText(False)
```

### 4.2 Key bindings

| Key | Action |
|---|---|
| Enter | Submit message (single-line mode) |
| Shift+Enter | New line (always) |
| Ctrl+Enter | Submit message (always, even in multiline mode) |
| Up (when input empty) | Previous history |
| Down (when input empty) | Next history |
| Tab (after "/") | Cycle slash command completion |
| Escape | Clear input / cancel |
| Ctrl+L | Clear chat display |

Override `keyPressEvent` to intercept these.

### 4.3 Slash command completion

```python
class SlashCompleter(QCompleter):
    """Completer for slash commands."""

    def __init__(self, commands: list[str], parent=None):
        super().__init__(commands, parent)
        self.setCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterMode(Qt.MatchStartsWith)
```

Show a popup with matching commands as user types after "/".
Pull command list from the same `SLASH_COMMANDS` constant used by TUI and web.

### 4.4 Dynamic height

Input area should grow as user types multiple lines, up to a maximum:

```python
def _adjust_height(self):
    doc_height = self.document().size().height()
    margins = self.contentsMargins()
    new_height = min(int(doc_height + margins.top() + margins.bottom() + 10), 200)
    new_height = max(new_height, 36)  # minimum one line
    self.setFixedHeight(new_height)
```

### Success criteria
- Single-line input sends on Enter
- Multi-line input grows dynamically
- Shift+Enter always inserts newline
- Up/Down navigates prompt history when input is empty
- "/" triggers command completion popup
- Tab cycles through completions
- Submitted text routes to `_handle_submitted_text`


## Phase 5: Wire Up Streaming + Session Lifecycle

**Goal:** End-to-end flow: type message -> create session -> stream response ->
display in chat. This is where the app becomes functional.

### 5.1 Connect all signals to widget updates

In `DesktopApp.__init__` or a `_connect_signals()` method:

```python
def _connect_signals(self):
    s = self._signals

    # Display signals
    s.system_message.connect(self._display_system_message)
    s.user_message.connect(self._display_user_message)
    s.assistant_message.connect(self._display_assistant_message)
    s.error_message.connect(self._display_error_message)
    s.status_update.connect(self._display_status_update)
    s.processing_started.connect(self._display_processing_start)
    s.processing_finished.connect(self._display_processing_end)

    # Streaming signals
    s.block_start.connect(self._handle_block_start)
    s.block_delta.connect(self._handle_block_delta)
    s.block_end.connect(self._handle_block_end)
    s.tool_start.connect(self._handle_tool_start)
    s.tool_end.connect(self._handle_tool_end)
    s.usage_update.connect(self._handle_usage_update)
```

### 5.2 Background message sending

Use a QThread worker or Python threading.Thread (like WebApp does):

```python
def _send_message_async(self, message: str, conversation_id: str):
    """Send message on background thread."""
    thread = threading.Thread(
        target=self._send_message_worker,
        args=(message, conversation_id),
        daemon=True,
    )
    thread.start()

def _send_message_worker(self, message: str, conversation_id: str):
    """Background thread: create session if needed, wire callbacks, send."""
    try:
        conv = self._get_conversation(conversation_id)
        if not self.session_manager.get_handle(conversation_id):
            self.session_manager.start_new_session(
                conversation_id=conversation_id,
                cwd=os.getcwd(),
            )
        self._wire_streaming_callbacks(conversation_id, conv)
        response = self.session_manager.send_message(message, conversation_id=conversation_id)
        if not conv.got_stream_content:
            self._add_assistant_message(response, conversation_id=conversation_id)
    except Exception as e:
        self._show_error(str(e), conversation_id=conversation_id)
    finally:
        self._finish_processing(conversation_id=conversation_id)
```

### 5.3 Session resume flow

```python
def _resume_session(self, session_id: str, conversation_id: str):
    """Resume a previous session, loading transcript into chat."""
    # 1. Find transcript on disk
    # 2. Parse with transcript_loader
    # 3. Display history messages in chat
    # 4. Resume session via session_manager.resume_session()
    # Reference: WebApp.resume_session() or TUI._resume_session_worker()
```

### Success criteria
- Type a message, press Enter -> session created -> response streams in
- Streaming text appears word-by-word in chat display
- Tool calls show in status/chat (tool name + result summary)
- Processing indicator (spinner or text) shows during LLM execution
- Status bar shows model name and token count after response
- Multiple messages in a conversation work correctly
- Errors display gracefully (no crash on network failure)


## Phase 6: Status Bar

**Goal:** Bottom status bar showing session state, model, tokens, mode.

### 6.1 Status bar layout

```
[Session: abc123] [Model: sonnet-4] [Tokens: 1.2k/200k] [Mode: planning] [Tab 1 of 3]
```

Create `widgets/status_bar.py`:

```python
class AmplifierStatusBar(QWidget):
    """Status bar with session info, model, tokens, mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._session_label = QLabel("No session")
        self._model_label = QLabel("")
        self._token_label = QLabel("")
        self._mode_label = QLabel("")
        self._tab_label = QLabel("")

        for label in [self._session_label, self._model_label,
                      self._token_label, self._mode_label, self._tab_label]:
            layout.addWidget(label)

        layout.addStretch()
```

### 6.2 Update from signals

Connect `usage_update` and `status_update` signals to refresh labels.
Token display format: `1.2k / 200k` (input / context window).

### Success criteria
- Status bar visible at bottom of chat area
- Shows session ID (short), model name, token usage
- Updates in real-time during streaming
- Shows mode when active


## Phase 7: Side Panels (QDockWidget)

**Goal:** TodoPanel, AgentTreePanel, ProjectPanel as dockable right panels.

### 7.1 Panel base pattern

All panels follow the same structure:

```python
class AmplifierDockPanel(QDockWidget):
    """Base for right-side dock panels."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.setMinimumWidth(250)

        # Content widget
        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self.setWidget(self._content)
```

### 7.2 TodoPanel

- Displays todo items from the `todo` tool calls
- Auto-shows when items arrive (detected in `_on_stream_tool_start`)
- Renders as a list: checkbox + content + status badge
- Reference: `widgets/todo_panel.py` in TUI

### 7.3 AgentTreePanel

- Displays agent delegation tree
- Auto-shows on first delegation
- Renders as indented tree with status indicators
- Updates when agent completes (from `_on_stream_tool_end`)
- Reference: `widgets/agent_tree_panel.py` in TUI

### 7.4 ProjectPanel

- Shows Projector projects, tasks, strategies
- Toggle via Ctrl+P or /project panel
- Reference: `widgets/project_panel.py` in TUI

### Success criteria
- All three panels appear as right-docked panels
- Panels can be dragged to reposition
- Panels can be resized by dragging edges
- Panels can be floated (detached into own window)
- Panels can be closed and reopened via View menu
- TodoPanel auto-shows when todo tool fires
- AgentTreePanel auto-shows on agent delegation


## Phase 8: Session Sidebar

**Goal:** Left sidebar with session browser, search/filter, resume capability.

### 8.1 Session sidebar widget

```python
class SessionSidebar(QWidget):
    """Collapsible session browser."""

    session_selected = Signal(str)  # session_id

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("Filter sessions...")

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Session", "Date"])

        layout.addWidget(self._filter_input)
        layout.addWidget(self._tree)
```

### 8.2 Session loading

Use `session_manager.list_all_sessions()` to populate the tree.
Group by date (Today, Yesterday, This Week, Older).
Show session title, project tag, date.
Double-click to resume in current or new tab.

### 8.3 Collapsible

The sidebar is the left portion of the main QSplitter. Allow collapsing
to a narrow strip (or hiding entirely) via a toggle button or Ctrl+B.

### Success criteria
- Sidebar shows all sessions from ~/.amplifier/projects/
- Sessions grouped by date
- Filter input narrows the list in real-time
- Double-click resumes session in new tab
- Sidebar is collapsible via keyboard shortcut


## Phase 9: Desktop-Specific Command Mixins

**Goal:** Qt equivalents of the 7 TUI-only command mixins.

### 9.1 Commands to port

| TUI Mixin | Desktop Equivalent | Priority |
|---|---|---|
| SessionCommandsMixin | Yes -- session tree, tab management | High |
| DisplayCommandsMixin | Yes -- /compact, /wrap, /fold, /scroll | High |
| SearchCommandsMixin | Yes -- /find (in-chat search bar) | High |
| ExportCommandsMixin | Partial -- /export (save as HTML/PDF) | Medium |
| SplitCommandsMixin | Yes -- /split (side-by-side tabs) | Medium |
| TerminalCommandsMixin | Later -- embedded QTermWidget | Low |
| MonitorCommandsMixin | Later -- session monitor | Low |

### 9.2 Implementation approach

Create `desktop/commands/` with Qt-specific mixins that mirror the TUI ones
but use Qt widgets. The command names and argument parsing stay identical.
Only the widget manipulation changes.

These mixins go into the DesktopApp MRO alongside the 18 core mixins.

### Success criteria
- /clear, /new, /sessions, /quit work
- /compact, /wrap, /fold toggle display modes
- /find opens an in-chat search bar with Ctrl+F
- /export saves chat as HTML file
- /split shows two tabs side-by-side


## Phase 10: Theming and Visual Polish

**Goal:** Dark theme, font selection, visual refinement.

### 10.1 QSS dark theme

Create `theme.py` with a dark theme matching the TUI aesthetic:

```python
DARK_THEME = """
QMainWindow {
    background-color: #1a1a2e;
}
QTextBrowser {
    background-color: #16213e;
    color: #e0e0e0;
    border: none;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 14px;
    padding: 12px;
}
QTextEdit {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #333;
    border-radius: 4px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 14px;
    padding: 8px;
}
QTabWidget::pane {
    border: none;
}
QTabBar::tab {
    background-color: #16213e;
    color: #888;
    padding: 8px 16px;
    border: none;
}
QTabBar::tab:selected {
    color: #e0e0e0;
    border-bottom: 2px solid #e94560;
}
QDockWidget {
    background-color: #16213e;
    color: #e0e0e0;
    titlebar-close-icon: url(close.png);
}
QSplitter::handle {
    background-color: #333;
    width: 2px;
}
QScrollBar:vertical {
    background-color: #1a1a2e;
    width: 8px;
}
QScrollBar::handle:vertical {
    background-color: #444;
    border-radius: 4px;
    min-height: 20px;
}
"""
```

### 10.2 Theme switching

Support the existing /theme command from ThemeCommandsMixin.
Map TUI theme names to QSS variants. Store preference via QSettings.

### 10.3 Font configuration

Allow font family and size configuration via preferences:
- Monospace font for code and input
- Proportional font option for chat text
- Font size adjustment (Ctrl+= / Ctrl+-)

### 10.4 Polish items

- Window icon (Amplifier logo)
- Smooth animations on panel show/hide (QPropertyAnimation)
- Processing indicator animation (pulsing dot or spinner)
- Hover effects on interactive elements
- Proper focus indicators
- System tray icon with notification badge

### Success criteria
- Dark theme applied consistently across all widgets
- /theme switches between color variants
- Ctrl+= and Ctrl+- adjust font size
- Visual quality noticeably above a terminal UI
- No visual glitches during streaming


## Phase 11: Persistence and Window State

**Goal:** Remember window layout, restore on next launch.

### 11.1 QSettings for window state

```python
def closeEvent(self, event):
    settings = QSettings("Amplifier", "Desktop")
    settings.setValue("geometry", self.saveGeometry())
    settings.setValue("windowState", self.saveState())
    settings.setValue("mainSplitter", self._main_splitter.saveState())
    settings.setValue("chatSplitter", self._chat_splitter.saveState())
    super().closeEvent(event)

def _restore_window_state(self):
    settings = QSettings("Amplifier", "Desktop")
    if settings.value("geometry"):
        self.restoreGeometry(settings.value("geometry"))
    if settings.value("windowState"):
        self.restoreState(settings.value("windowState"))
    # etc.
```

### 11.2 Autosave integration

Reuse the existing autosave system from the TUI.
The core autosave logic is in the conversation state serialization --
adapt the TUI's `_do_autosave()` and `_restore_workspace_state()`.

### Success criteria
- Close and reopen: window size, position, splitter sizes restored
- Dock panel positions restored
- Workspace tabs restored (via autosave)


## Implementation Order and Dependencies

```
Phase 0: Scaffolding                     [~0.5 day]
    |
Phase 1: App class + stubs              [~1 day]
    |
Phase 2: Main layout                    [~1.5 days]
    |
    +-- Phase 3: Chat display            [~3 days]  *** hardest phase ***
    |       |
    +-- Phase 4: Input area              [~1.5 days]
    |       |
    +-------+
    |
Phase 5: Wire streaming + sessions      [~2 days]  *** first functional milestone ***
    |
    +-- Phase 6: Status bar              [~0.5 day]
    +-- Phase 7: Side panels             [~2 days]
    +-- Phase 8: Session sidebar         [~1.5 days]
    +-- Phase 9: Desktop commands        [~2 days]
    |
Phase 10: Theming + polish              [~2 days]
    |
Phase 11: Persistence                   [~1 day]
```

**Total estimate: ~18 working days for a solid v1.**

Phases 3+4 and Phases 6+7+8+9 have internal parallelism.


## Key Risks and Mitigations

### Risk: MRO conflicts between SharedAppBase and QMainWindow

Both have `__init__` chains. Use cooperative `super().__init__(**kwargs)`.
Test the MRO early in Phase 1 -- if it conflicts, use composition instead
of inheritance (DesktopApp HAS-A SharedAppBase instead of IS-A).

**Mitigation:** If MRO is problematic, use the composition pattern:
```python
class DesktopApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self._backend = DesktopBackend()  # inherits SharedAppBase + mixins

class DesktopBackend(SharedAppBase, ...all mixins...):
    # No Qt inheritance -- just the backend
    pass
```
This is actually cleaner and avoids all MRO issues. The backend holds all
the shared logic; the QMainWindow holds all the widgets; signals bridge them.

### Risk: Markdown rendering performance during streaming

Re-rendering full markdown on every delta (50ms throttle) could be slow for
long responses.

**Mitigation:** During streaming, render as plain text with minimal formatting.
On block_end, do the full markdown render once. This is what the TUI does
(streaming uses simple Static widget, finalization uses full Markdown widget).

### Risk: PySide6 on WSL2 vs native Windows

The user wants native Windows, not WSLg. PySide6 is a Python package that
works natively on Windows. The app would run on the Windows Python, not WSL
Python.

**Mitigation:** The Bridge API communicates over the filesystem or localhost.
Ensure `session_manager` can connect to an amplifier backend running on WSL.
This may require a small bridge layer (WebSocket or TCP to WSL) if the current
LocalBridge assumes same-OS. Investigate in Phase 1.

**Alternative:** If LocalBridge requires same-OS, the simplest path is to run
the desktop app on WSL via WSLg for v1, then add a network bridge for v2.
WSLg performance for Qt is actually decent (GPU accelerated since WSL 2.2+).

### Risk: Thread safety in Qt

Qt is strict about GUI thread access. All widget updates MUST happen on the
main thread. The signals.py bridge handles this, but any direct widget access
from a background thread will crash.

**Mitigation:** The signal architecture in Phase 1 addresses this structurally.
All 14 abstract methods emit signals; all widget updates happen in signal handlers
on the GUI thread. No abstract method directly touches widgets.


## Testing Strategy

### Unit tests
- `tests/desktop/test_desktop_app.py` -- App initialization, signal emission
- `tests/desktop/test_chat_display.py` -- Message rendering, markdown conversion
- `tests/desktop/test_chat_input.py` -- Key bindings, completion, history

### Integration tests
- Create session, send message, verify streaming callbacks fire signals
- Resume session, verify transcript loads into chat display
- Tab create/switch/close lifecycle

### Manual QA checklist
- [ ] Launch, type message, get response
- [ ] Streaming text appears smoothly
- [ ] Code blocks have syntax highlighting
- [ ] Slash commands complete and execute
- [ ] Tabs create, switch, close correctly
- [ ] Panels dock, resize, float, close, reopen
- [ ] Session sidebar lists sessions, resume works
- [ ] Window state persists across restarts
- [ ] Font size adjustment works
- [ ] Theme switching works
- [ ] Processing indicator shows/hides correctly
- [ ] Auto-scroll behavior correct
- [ ] Copy/paste from chat works
- [ ] Ctrl+C cancels in-flight request


## File Inventory (Final State)

```
amplifier_tui/desktop/
  __init__.py                    # main() entry point, ~20 lines
  desktop_app.py                 # DesktopApp class, ~800-1200 lines
  signals.py                     # StreamSignals, ~40 lines
  theme.py                       # QSS themes, ~200 lines
  widgets/
    __init__.py
    chat_display.py              # ChatDisplay (QTextBrowser), ~400 lines
    chat_input.py                # ChatInput (QTextEdit), ~300 lines
    message_widgets.py           # Message formatting/rendering, ~200 lines
    tab_bar.py                   # DesktopTabState + tab helpers, ~150 lines
    status_bar.py                # AmplifierStatusBar, ~100 lines
    panels.py                    # Todo/Agent/Project dock panels, ~400 lines
    session_sidebar.py           # SessionSidebar, ~250 lines
    find_bar.py                  # In-chat search bar, ~150 lines
  commands/
    __init__.py
    display_cmds.py              # /compact, /wrap, /fold, ~200 lines
    session_cmds.py              # /clear, /new, /sessions, ~200 lines
    search_cmds.py               # /find, /search, ~150 lines
    export_cmds.py               # /export, ~100 lines

Estimated total: ~3,500-4,500 lines of new code
(vs 7,433 lines in app.py alone -- much smaller because core/ is reused)
```
