"""Command palette provider for Amplifier TUI."""

from __future__ import annotations

from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider

# (display_name, description, command_key)
# command_key: "/cmd" delegates to _handle_slash_command; "action:name" calls action_name
_PALETTE_COMMANDS: tuple[tuple[str, str, str], ...] = (
    # ── Slash commands ──────────────────────────────────────────────
    ("/help", "Show help reference", "/help"),
    ("/clear", "Clear chat display", "/clear"),
    ("/new", "Start a new session", "/new"),
    ("/sessions", "Toggle session sidebar", "/sessions"),
    ("/sessions list", "List all saved sessions", "/sessions list"),
    ("/sessions recent", "Show 10 most recent sessions", "/sessions recent"),
    ("/sessions search", "Search across all sessions", "/sessions search "),
    ("/sessions open", "Open/resume a session by ID", "/sessions open "),
    ("/sessions delete", "Delete a session by ID", "/sessions delete "),
    ("/sessions info", "Show session details", "/sessions info "),
    ("/prefs", "Open preferences", "/preferences"),
    ("/model", "Show or switch AI model", "/model"),
    ("/stats", "Session statistics (tools, tokens, time)", "/stats"),
    ("/tokens", "Detailed token and context usage breakdown", "/tokens"),
    ("/context", "Visual context window usage bar", "/context"),
    ("/showtokens", "Toggle token/context usage in status bar", "/showtokens"),
    ("/contextwindow", "Set context window size (e.g. 128k, auto)", "/contextwindow"),
    ("/info", "Session details (ID, model, project, counts)", "/info"),
    ("/copy", "Copy last response (last, N, all, code)", "/copy"),
    ("/bookmark", "Bookmark last AI response", "/bookmark"),
    ("/bookmark list", "List all bookmarks with preview", "/bookmark list"),
    ("/bookmark jump", "Jump to a bookmark by number", "/bookmark jump "),
    ("/bookmark remove", "Remove a specific bookmark", "/bookmark remove "),
    ("/bookmark clear", "Remove all bookmarks", "/bookmark clear"),
    ("/bookmarks", "List or jump to bookmarks", "/bookmarks"),
    ("/ref", "Save a URL or reference", "/ref"),
    ("/refs", "List saved references", "/refs"),
    ("/title", "View or set session title", "/title"),
    ("/rename", "Rename current tab (F2)", "/rename"),
    ("/rename reset", "Reset tab name to default", "/rename reset"),
    ("/pin", "Pin message (last, by number, or with label)", "/pin"),
    ("/pins", "List pinned messages", "/pins"),
    ("/unpin", "Remove a pin by number", "/unpin"),
    ("/pin-session", "Pin or unpin session in sidebar", "/pin-session"),
    ("/note", "Add a session note (not sent to AI)", "/note"),
    ("/note list", "List all session notes", "/note list"),
    ("/note clear", "Remove all session notes", "/note clear"),
    ("/notes", "List all session notes", "/notes"),
    ("/delete", "Delete session (with confirmation)", "/delete"),
    ("/export", "Export chat (md/html/json/txt/last [N]/clipboard)", "/export"),
    ("/notify", "Toggle notifications (on, off, sound, silent, flash)", "/notify"),
    ("/sound", "Toggle notification sound (on, off, test)", "/sound"),
    ("/scroll", "Toggle auto-scroll on/off", "/scroll"),
    ("/timestamps", "Toggle message timestamps", "/timestamps"),
    ("/ts", "Toggle message timestamps (alias for /timestamps)", "/ts"),
    ("/wrap", "Toggle word wrap (on, off)", "/wrap"),
    ("/fold", "Fold or unfold long messages", "/fold"),
    ("/fold all", "Fold all long messages", "/fold all"),
    ("/fold none", "Unfold all messages", "/fold none"),
    ("/fold toggle", "Toggle fold on all long messages", "/fold toggle"),
    ("/fold threshold", "Show or set auto-fold line threshold", "/fold threshold"),
    ("/unfold", "Unfold the last folded message", "/unfold"),
    ("/unfold all", "Unfold all folded messages", "/unfold all"),
    ("/theme", "Switch color theme", "/theme"),
    ("/theme preview", "Preview all themes with swatches", "/theme preview"),
    ("/theme revert", "Restore saved theme after preview", "/theme revert"),
    ("/colors", "View or set text colors", "/colors"),
    (
        "/colors presets",
        "Show available color presets with swatches",
        "/colors presets",
    ),
    ("/colors use", "Apply a color preset", "/colors use "),
    ("/colors reset", "Reset all colors to defaults", "/colors reset"),
    ("/focus", "Toggle focus mode", "/focus"),
    ("/search", "Search across all past sessions", "/search"),
    ("/search here", "Search current chat only", "/search here "),
    ("/search open", "Open a result from last search", "/search open "),
    ("/grep", "Search chat with regex", "/grep"),
    ("/find", "Interactive find-in-chat (Ctrl+F)", "/find"),
    ("/diff", "Show git diff (staged, all, file)", "/diff"),
    ("/diff msgs", "Compare assistant messages (last two, or N M)", "/diff msgs"),
    ("/git", "Quick git info (status, log, diff, branch, stash, blame)", "/git"),
    ("/watch", "Watch files for changes", "/watch"),
    ("/sort", "Sort sessions (date, name, project)", "/sort"),
    ("/edit", "Open $EDITOR for input", "/edit"),
    ("/draft", "Save, load, or clear input draft", "/draft"),
    ("/drafts", "List all saved drafts across sessions", "/drafts"),
    ("/drafts clear", "Clear the current session draft", "/drafts clear"),
    ("/snippet", "Manage prompt snippets", "/snippet"),
    ("/snippets", "List all prompt snippets", "/snippets"),
    ("/snip", "Prompt snippets (alias for /snippet)", "/snippet"),
    ("/template", "Manage prompt templates", "/template"),
    ("/templates", "List all prompt templates", "/templates"),
    ("/alias", "List, create, or remove command aliases", "/alias"),
    ("/compact", "Toggle compact view mode", "/compact"),
    ("/history", "Browse or search input history", "/history"),
    ("/undo", "Remove last exchange", "/undo"),
    ("/retry", "Undo last exchange & re-send (or send new text)", "/retry"),
    ("/redo", "Alias for /retry (undo + re-send)", "/redo"),
    ("/split", "Toggle split view (tab split, pins, chat, file)", "/split"),
    ("/split N", "Split current tab with tab N", "/split "),
    ("/split swap", "Swap left and right panes in split view", "/split swap"),
    ("/split off", "Close split view", "/split off"),
    ("/stream", "Toggle streaming display", "/stream"),
    (
        "/multiline",
        "Toggle multiline mode (Enter=newline, Shift+Enter=send)",
        "/multiline",
    ),
    ("/ml", "Toggle multiline mode (alias for /multiline)", "/ml"),
    ("/suggest", "Toggle smart prompt suggestions (on/off)", "/suggest"),
    ("/progress", "Toggle detailed progress labels (on/off)", "/progress"),
    ("/mode", "Amplifier mode (planning, research, review, debug)", "/mode"),
    ("/mode planning", "Activate planning mode", "/mode planning"),
    ("/mode research", "Activate research mode", "/mode research"),
    ("/mode review", "Activate review mode", "/mode review"),
    ("/mode debug", "Activate debug mode", "/mode debug"),
    ("/mode off", "Deactivate current mode", "/mode off"),
    ("/modes", "List available modes", "/modes"),
    ("/vim", "Toggle vim keybindings", "/vim"),
    ("/tab", "Tab management (new, switch, close, rename, list)", "/tab"),
    ("/tab new", "Open a new conversation tab", "/tab new"),
    ("/tab list", "List all open tabs", "/tab list"),
    ("/tab rename", "Rename current tab", "/tab rename"),
    ("/tabs", "List all open tabs", "/tabs"),
    ("/keys", "Keyboard shortcuts overlay", "/keys"),
    ("/quit", "Quit the application", "/quit"),
    ("/run", "Run a shell command inline (/! shorthand)", "/run"),
    ("/include", "Include file contents in prompt (@file syntax too)", "/include"),
    ("/autosave", "Auto-save status, toggle, force save, or restore", "/autosave"),
    ("/autosave on", "Enable periodic auto-save", "/autosave on"),
    ("/autosave off", "Disable periodic auto-save", "/autosave off"),
    ("/autosave now", "Force an immediate auto-save", "/autosave now"),
    ("/autosave restore", "List and restore from auto-saves", "/autosave restore"),
    ("/system", "Set or view custom system prompt", "/system"),
    ("/system presets", "Show available system prompt presets", "/system presets"),
    ("/system use coder", "Apply 'coder' system prompt preset", "/system use coder"),
    (
        "/system use reviewer",
        "Apply 'reviewer' system prompt preset",
        "/system use reviewer",
    ),
    (
        "/system use teacher",
        "Apply 'teacher' system prompt preset",
        "/system use teacher",
    ),
    (
        "/system use concise",
        "Apply 'concise' system prompt preset",
        "/system use concise",
    ),
    (
        "/system use creative",
        "Apply 'creative' system prompt preset",
        "/system use creative",
    ),
    ("/system use debug", "Apply 'debug' system prompt preset", "/system use debug"),
    (
        "/system use architect",
        "Apply 'architect' system prompt preset",
        "/system use architect",
    ),
    ("/system use writer", "Apply 'writer' system prompt preset", "/system use writer"),
    ("/system clear", "Remove custom system prompt", "/system clear"),
    ("/fork", "Fork conversation into a new tab", "/fork"),
    ("/fork N", "Fork from message N (from bottom) into a new tab", "/fork"),
    ("/branch", "Fork conversation into a new tab (alias for /fork)", "/branch"),
    ("/name", "Name current session (/name <text>, /name clear)", "/name"),
    ("/attach", "Attach file(s) to next message", "/attach "),
    ("/attach clear", "Remove all attachments", "/attach clear"),
    ("/attach remove", "Remove a specific attachment by number", "/attach remove "),
    ("/tag", "Session tags (add, remove, list)", "/tag"),
    ("/tag add", "Add a tag to current session", "/tag add "),
    ("/tag remove", "Remove a tag from current session", "/tag remove "),
    ("/tag list", "Show tags on current session", "/tag list"),
    ("/tags", "List all tags across all sessions", "/tags"),
    ("/cat", "Display file contents in chat", "/cat "),
    ("/clipboard", "Show clipboard ring history", "/clipboard"),
    ("/clip", "Clipboard ring (alias)", "/clip"),
    ("/clip search", "Search clipboard ring", "/clip search "),
    ("/clip clear", "Clear clipboard ring", "/clip clear"),
    # ── Keyboard-shortcut actions ───────────────────────────────────────────
    ("New Session  Ctrl+N", "Start a new conversation", "action:new_session"),
    ("New Tab  Ctrl+T", "Open a new conversation tab", "action:new_tab"),
    ("Close Tab  Ctrl+W", "Close the current tab", "action:close_tab"),
    ("Previous Tab  Ctrl+PgUp", "Switch to previous tab", "action:prev_tab"),
    ("Next Tab  Ctrl+PgDn", "Switch to next tab", "action:next_tab"),
    (
        "Toggle Sidebar  Ctrl+B",
        "Show or hide session sidebar",
        "action:toggle_sidebar",
    ),
    (
        "Open Editor  Ctrl+G",
        "Open external editor for input",
        "action:open_editor",
    ),
    (
        "Copy Response  Ctrl+Y / Ctrl+Shift+C",
        "Copy last AI response to clipboard",
        "action:copy_response",
    ),
    (
        "Stash Prompt  Ctrl+S",
        "Stash or restore draft prompt",
        "action:stash_prompt",
    ),
    (
        "Bookmark Last  Ctrl+M",
        "Bookmark the last AI response",
        "action:bookmark_last",
    ),
    (
        "Search History  Ctrl+R",
        "Reverse search prompt history",
        "action:search_history",
    ),
    (
        "Find in Chat  Ctrl+F",
        "Interactive find-in-chat search bar",
        "action:search_chat",
    ),
    (
        "Toggle Auto-scroll  Ctrl+A",
        "Toggle auto-scroll on/off",
        "action:toggle_auto_scroll",
    ),
    ("Clear Chat  Ctrl+L", "Clear the chat display", "action:clear_chat"),
    (
        "Focus Mode  F11",
        "Toggle focus mode (hide chrome)",
        "action:toggle_focus_mode",
    ),
    (
        "Keyboard Shortcuts  F1",
        "Show keyboard shortcuts overlay",
        "action:show_shortcuts",
    ),
    (
        "Scroll to Top  Ctrl+Home",
        "Jump to top of chat",
        "action:scroll_chat_top",
    ),
    (
        "Scroll to Bottom  Ctrl+End",
        "Jump to bottom of chat",
        "action:scroll_chat_bottom",
    ),
)


class AmplifierCommandProvider(Provider):
    """Provide all TUI slash commands and actions to the command palette."""

    async def search(self, query: str) -> Hits:
        """Yield commands that fuzzy-match *query*."""
        matcher = self.matcher(query)
        for name, description, command_key in _PALETTE_COMMANDS:
            score = matcher.match(f"{name} {description}")
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    partial(self._run_command, command_key),
                    help=description,
                )

    async def discover(self) -> Hits:
        """Show every command when the palette first opens (no query yet)."""
        for name, description, command_key in _PALETTE_COMMANDS:
            yield DiscoveryHit(
                name,
                partial(self._run_command, command_key),
                help=description,
            )

    def _run_command(self, key: str) -> None:
        """Execute a palette command by dispatching to the app."""
        app = self.app
        if key.startswith("action:"):
            action_name = key[7:]
            method = getattr(app, f"action_{action_name}", None)
            if method is not None:
                method()
        else:
            # Delegate to the existing slash-command router
            app._handle_slash_command(key)  # type: ignore[attr-defined]
