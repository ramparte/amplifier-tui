"""Modal screen widgets for Amplifier TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..history import PromptHistory

SHORTCUTS_TEXT = """\
                   Keyboard Shortcuts
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

 NAVIGATION \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  Ctrl+\u2191/\u2193         Scroll chat up/down
  Ctrl+Home/End    Jump to top/bottom
  Home/End          Top/bottom (input empty)
  \u2191/\u2193              Browse prompt history
  Ctrl+B           Toggle sidebar
  Tab              Cycle focus
  F11              Focus mode

 CHAT \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  Enter            Send message
  Shift+Enter      New line (also Ctrl+J)
  Alt+M            Toggle multiline mode
                    (ML: Enter=newline, Shift+Enter=send)
  Escape           Cancel AI streaming
  Ctrl+C           Cancel AI response
  Ctrl+L           Clear chat
  Ctrl+A           Toggle auto-scroll

 SEARCH & EDIT \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  Ctrl+F           Find in chat (search bar)
  Ctrl+R           Reverse history search (Ctrl+S fwd)
  Ctrl+G           Open external editor
  Ctrl+Y           Copy last AI response
  Ctrl+M           Bookmark last response
  Ctrl+S           Stash/restore draft

 VIM BOOKMARKS (normal mode) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  Ctrl+B           Toggle bookmark on last msg
  [                Jump to previous bookmark
  ]                Jump to next bookmark

 SESSIONS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  Ctrl+N           New session
  Ctrl+T           New tab
  F2               Rename current tab
  Ctrl+W           Close tab (or switch split pane)
  Ctrl+PgUp/Dn    Switch tabs (or split pane)
  Alt+Left/Right   Prev/next tab (or split pane)
  Alt+1-9          Jump to tab 1-9
  Alt+0            Jump to last tab
  Ctrl+P           Command palette (fuzzy search)
  F1 / Ctrl+/      This help
  Ctrl+Q           Quit

 SPLIT VIEW \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /split           Toggle tab split (2+ tabs)
  /split N         Split with tab N
  /split swap      Swap left/right panes
  /split off       Close split view
  Alt+Left/Right   Switch active pane
  Ctrl+W           Switch active pane

                    Slash Commands
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  Type /help for the full reference

 SESSION \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /new             New session
  /sessions        Toggle session sidebar
  /rename          Rename tab (F2)
  /title           View/set session title
  /delete          Delete current session
  /pin-session     Pin/unpin in sidebar
  /sort            Sort sessions
  /split           Split view (tab, pins, chat, file)
  /tab             Tab management
  /tabs            List open tabs
  /info            Session details
  /stats           Session stats (tools, tokens, time)

 CHAT & HISTORY \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /clear           Clear chat display
  /copy            Copy response (last/N/all/code)
  /undo [N]        Undo last N exchange(s)
  /retry [text]    Undo & resend (or send new text)
  /redo [text]     Alias for /retry
  /fold            Fold long message (all/none/<N>)
  /unfold          Unfold last folded message (all)
  /compact         Toggle compact mode
  /history         Browse/search/clear history

 SEARCH \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /find            Interactive find-in-chat (Ctrl+F)
  /search          Search chat messages
  /grep            Search chat (regex)

 PINS & BOOKMARKS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /pin             Pin message (N, list, clear, rm N)
  /pins            List pinned messages
  /unpin N         Remove a pin
  /bookmark        Bookmark response (list/N/jump/rm)
  /bookmarks       List/jump to bookmarks
  /note            Session note (list, clear)
  /notes           List all notes
  /ref             Save URL/reference
  /refs            List saved references

 MODEL & DISPLAY \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /model [name]    View/switch AI model
  /theme [name]    Switch theme (preview/revert)
  /colors          Text colors (presets, use <name>)
  /wrap            Toggle word wrap
  /timestamps      Toggle timestamps (/ts)
  /focus           Toggle focus mode
  /stream          Toggle streaming display
  /scroll          Toggle auto-scroll

 EXPORT & DATA \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /export          Export chat (md/html/json/txt)
  /diff            Show git diff (color-coded)
  /diff msgs       Compare assistant messages
  /git             Git ops (status/log/diff/branch)
  /watch           Watch files for changes
  /run <cmd>       Run shell command (/! shorthand)
  /tokens          Token/context usage
  /context         Context window details
  /showtokens      Toggle token display
  /contextwindow   Set context window size

 FILES \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /attach <path>   Attach file(s) to next message
  /attach          Show current attachments
  /attach clear    Remove all attachments
  /cat <path>      Display file contents in chat

 INPUT & SETTINGS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  /edit            Open $EDITOR for input
  /editor          Open editor (/editor submit)
  /draft           Save/load input drafts
  /snippet         Prompt snippets
  /template        Prompt templates ({{vars}})
  /mode            Modes (planning/research/review)
  /system          System prompt (presets/use/clear)
  /alias           Custom command shortcuts
  /vim             Toggle vim keybindings
  /suggest         Toggle smart suggestions
  /prefs           Preferences
  /notify          Toggle notifications
  /sound           Notification sound (on/off/test)
  /palette         Command palette (Ctrl+P)
  /keys            Show this overlay
  /quit            Quit

           Press F1, Ctrl+/, or Esc to close\
"""


class ShortcutOverlay(ModalScreen):
    """Modal overlay showing all keyboard shortcuts and slash commands."""

    BINDINGS = [
        Binding("escape", "dismiss_overlay", show=False),
        Binding("f1", "dismiss_overlay", show=False),
        Binding("ctrl+question_mark", "dismiss_overlay", show=False),
        Binding("ctrl+slash", "dismiss_overlay", show=False),
    ]

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="shortcut-modal"):
            yield Static(SHORTCUTS_TEXT, id="shortcut-content")

    def action_dismiss_overlay(self) -> None:
        self.app.pop_screen()

    def on_click(self, event) -> None:
        """Dismiss overlay when clicking outside the modal content."""
        modal = self.query_one("#shortcut-modal")
        if (event.screen_x, event.screen_y) not in modal.region:
            self.app.pop_screen()


class HistorySearchScreen(ModalScreen[str]):
    """Modal for searching prompt history with fuzzy filtering."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

    def __init__(self, history: PromptHistory) -> None:
        super().__init__()
        self._history = history

    def compose(self) -> ComposeResult:
        with Vertical(id="history-search-modal"):
            yield Static(
                "Search History  [dim](type to filter, Enter selects)[/]",
                id="history-search-title",
            )
            yield Input(placeholder="Type to filter\u2026", id="history-search-input")
            yield OptionList(id="history-search-results")

    def on_mount(self) -> None:
        self._update_results("")
        self.query_one("#history-search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "history-search-input":
            self._update_results(event.value)

    def _update_results(self, query: str) -> None:
        option_list = self.query_one("#history-search-results", OptionList)
        option_list.clear_options()
        matches = self._history.search(query)
        for item in matches:
            display = item[:120] + "\u2026" if len(item) > 120 else item
            option_list.add_option(Option(display, id=item))
        if matches:
            option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # Option id stores the full original text
        if event.option.id is not None:
            self.dismiss(event.option.id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "history-search-input":
            option_list = self.query_one("#history-search-results", OptionList)
            if option_list.option_count > 0 and option_list.highlighted is not None:
                opt = option_list.get_option_at_index(option_list.highlighted)
                if opt.id is not None:
                    self.dismiss(opt.id)
            else:
                self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")
