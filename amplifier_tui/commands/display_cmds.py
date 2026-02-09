"""Display and UI preference commands."""

from __future__ import annotations

from ..preferences import (
    save_compact_mode,
    save_fold_threshold,
    save_multiline_default,
    save_progress_labels,
    save_show_suggestions,
    save_show_timestamps,
    save_streaming_enabled,
    save_vim_mode,
    save_word_wrap,
)
from ..widgets import (
    ChatInput,
    FoldToggle,
    SuggestionBar,
)


class DisplayCommandsMixin:
    """Display and UI preference commands."""

    def _cmd_compact(self, text: str) -> None:
        """Toggle compact view mode on/off for denser chat display."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg in ("on", "true", "1"):
            compact = True
        elif arg in ("off", "false", "0"):
            compact = False
        elif not arg:
            compact = not self._prefs.display.compact_mode
        else:
            self._add_system_message("Usage: /compact [on|off]")
            return

        self._prefs.display.compact_mode = compact
        save_compact_mode(compact)

        # Toggle CSS class on the app for cascading style changes
        if compact:
            self.add_class("compact-mode")
            # Collapse tool and thinking blocks for maximum density
            for widget in self.query(".tool-use, .thinking-block"):
                if hasattr(widget, "collapsed"):
                    widget.collapsed = True
        else:
            self.remove_class("compact-mode")

        state = "ON" if compact else "OFF"
        self._update_status()
        self._add_system_message(f"Compact mode: {state}")

    def _cmd_vim(self, text: str) -> None:
        """Toggle vim-style keybindings in the input area."""
        text = text.strip().lower()

        if text in ("on", "true", "1"):
            vim = True
        elif text in ("off", "false", "0"):
            vim = False
        elif not text:
            vim = not self._prefs.display.vim_mode
        else:
            self._add_system_message("Usage: /vim [on|off]")
            return

        self._prefs.display.vim_mode = vim
        save_vim_mode(vim)

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget._vim_enabled = vim

        if vim:
            input_widget._vim_state = "normal"
            input_widget._vim_key_buffer = ""
            input_widget._update_vim_border()
            self._add_system_message(
                "Vim mode enabled (NORMAL mode — press i for INSERT)"
            )
        else:
            input_widget._vim_state = "insert"
            input_widget._vim_key_buffer = ""
            input_widget.border_title = ""
            self._add_system_message("Vim mode disabled")

        self._update_vim_status()

    # ── /multiline – toggle multiline input mode ─────────────────────────

    def _cmd_multiline(self, text: str) -> None:
        """Toggle multiline input mode.

        /multiline       Toggle multiline mode
        /multiline on    Enable multiline mode
        /multiline off   Disable multiline mode
        /ml              Alias for /multiline
        """
        text = text.strip().lower()

        if text in ("on", "true", "1"):
            ml = True
        elif text in ("off", "false", "0"):
            ml = False
        elif not text:
            ml = not self._prefs.display.multiline_default
        else:
            self._add_system_message("Usage: /multiline [on|off]")
            return

        self._prefs.display.multiline_default = ml
        save_multiline_default(ml)

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget._multiline_mode = ml

        if ml:
            self._add_system_message(
                "Multiline mode ON — Enter inserts newline, "
                "Shift+Enter sends (Ctrl+J also sends)"
            )
        else:
            self._add_system_message(
                "Multiline mode OFF — Enter sends, Shift+Enter inserts newline"
            )

        self._update_multiline_status()

    def _cmd_suggest(self, text: str) -> None:
        """Toggle smart prompt suggestions on/off.

        /suggest       Toggle suggestions
        /suggest on    Enable suggestions
        /suggest off   Disable suggestions
        """
        text = text.strip().lower()

        if text in ("on", "true", "1"):
            enabled = True
        elif text in ("off", "false", "0"):
            enabled = False
        elif not text:
            enabled = not self._prefs.display.show_suggestions
        else:
            self._add_system_message("Usage: /suggest [on|off]")
            return

        self._prefs.display.show_suggestions = enabled
        save_show_suggestions(enabled)

        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget._suggestions_enabled = enabled

        if enabled:
            self._add_system_message(
                "Smart suggestions ON — type 2+ chars to see suggestions, Tab to accept"
            )
        else:
            self._add_system_message("Smart suggestions OFF")
            # Dismiss any visible suggestions
            try:
                self.query_one("#suggestion-bar", SuggestionBar).dismiss()
            except Exception:
                pass

    def _cmd_progress(self, text: str) -> None:
        """Toggle detailed progress labels on/off.

        /progress       Toggle progress labels
        /progress on    Enable detailed labels (Reading file..., Searching...)
        /progress off   Disable labels (always show Thinking...)
        """
        text = text.strip().lower()

        if text in ("on", "true", "1"):
            enabled = True
        elif text in ("off", "false", "0"):
            enabled = False
        elif not text:
            enabled = not self._prefs.display.progress_labels
        else:
            self._add_system_message(
                "Usage: /progress [on|off]\n"
                "  /progress      Toggle detailed progress labels\n"
                "  /progress on   Show tool details (Reading file..., Searching...)\n"
                "  /progress off  Generic indicator (Thinking...)"
            )
            return

        self._prefs.display.progress_labels = enabled
        save_progress_labels(enabled)

        if enabled:
            self._add_system_message(
                "Progress labels: ON\n"
                "Shows detailed tool activity (Reading file..., Delegating to agent..., etc.)"
            )
        else:
            self._add_system_message(
                "Progress labels: OFF\n"
                "Shows generic Thinking... indicator during processing."
            )

    # ── /mode – Amplifier mode switching ─────────────────────────────────────

    def _cmd_focus(self, text: str = "") -> None:
        """Toggle focus mode via slash command.

        /focus      - toggle
        /focus on   - enable
        /focus off  - disable
        """
        arg = text.strip().lower()
        if arg == "on":
            self._set_focus_mode(True)
        elif arg == "off":
            self._set_focus_mode(False)
        else:
            self._set_focus_mode(not self._focus_mode)

    def _cmd_scroll(self) -> None:
        """Toggle auto-scroll on/off."""
        self.action_toggle_auto_scroll()

    def _cmd_timestamps(self) -> None:
        """Toggle message timestamps on/off."""
        self._prefs.display.show_timestamps = not self._prefs.display.show_timestamps
        save_show_timestamps(self._prefs.display.show_timestamps)
        state = "on" if self._prefs.display.show_timestamps else "off"
        # Show/hide existing timestamp widgets
        for ts_widget in self.query(".msg-timestamp"):
            ts_widget.display = self._prefs.display.show_timestamps
        # Manage periodic refresh timer for relative timestamps
        if self._prefs.display.show_timestamps:
            self._refresh_timestamps()
            if self._timestamp_timer is None:
                self._timestamp_timer = self.set_interval(
                    30.0, self._refresh_timestamps
                )
        else:
            if self._timestamp_timer is not None:
                self._timestamp_timer.stop()
                self._timestamp_timer = None
        self._add_system_message(f"Timestamps {state}")

    def _cmd_wrap(self, text: str) -> None:
        """Toggle word wrap on/off for chat messages."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "on":
            wrap = True
        elif arg == "off":
            wrap = False
        elif not arg:
            wrap = not self._prefs.display.word_wrap
        else:
            self._add_system_message("Usage: /wrap [on|off]")
            return

        self._prefs.display.word_wrap = wrap
        save_word_wrap(wrap)

        # Toggle CSS class on chat view
        chat = self._active_chat_view()
        if wrap:
            chat.remove_class("no-wrap")
        else:
            chat.add_class("no-wrap")

        state = "on" if wrap else "off"
        self._add_system_message(f"Word wrap: {state}")

    def _cmd_stream(self, args: str) -> None:
        """Toggle streaming token display on/off."""
        arg = args.strip().lower()

        if arg in ("on", "true", "1"):
            enabled = True
        elif arg in ("off", "false", "0"):
            enabled = False
        elif not arg:
            enabled = not self._prefs.display.streaming_enabled
        else:
            self._add_system_message(
                "Usage: /stream [on|off]\n"
                "  /stream      Toggle streaming display\n"
                "  /stream on   Enable progressive token streaming\n"
                "  /stream off  Disable streaming (show full response at once)"
            )
            return

        self._prefs.display.streaming_enabled = enabled
        save_streaming_enabled(enabled)

        if enabled:
            self._add_system_message(
                "Streaming: ON\n"
                "Tokens appear progressively as they arrive.\n"
                "Press Escape to cancel mid-stream."
            )
        else:
            self._add_system_message(
                "Streaming: OFF\nFull response will appear after generation completes."
            )

    def _cmd_fold(self, text: str) -> None:
        """Fold/unfold long messages, toggle Nth, or set fold threshold."""
        parts = text.strip().split(None, 2)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "all":
            self._fold_all_messages()
            return
        if arg in ("none", "off"):
            self._unfold_all_messages()
            return
        if arg == "toggle":
            self._toggle_fold_all()
            return
        if arg == "threshold":
            # /fold threshold [N] — set or show the auto-fold threshold
            val = parts[2].strip() if len(parts) > 2 else ""
            if val.isdigit():
                threshold = max(5, int(val))
                self._fold_threshold = threshold
                self._prefs.display.fold_threshold = threshold
                save_fold_threshold(threshold)
                self._add_system_message(
                    f"Fold threshold set to {threshold} lines (saved)"
                )
            elif val == "off" or val == "0":
                self._fold_threshold = 0
                self._prefs.display.fold_threshold = 0
                save_fold_threshold(0)
                self._add_system_message("Auto-fold disabled (saved)")
            else:
                self._add_system_message(
                    f"Fold threshold: {self._fold_threshold} lines\n"
                    "Usage: /fold threshold <n>  (min 5, 0 = disabled)"
                )
            return
        if arg.isdigit():
            # /fold N — toggle fold on Nth message from bottom
            self._toggle_fold_nth(int(arg))
            return
        if not arg:
            self._fold_last_message()
            return

        self._add_system_message(
            "Usage: /fold [all|none|toggle|threshold|<N>]\n"
            "  /fold            Fold the last long message\n"
            "  /fold all        Fold all long messages\n"
            "  /fold none       Unfold all messages\n"
            "  /fold toggle     Toggle fold on all long messages\n"
            "  /fold <N>        Toggle fold on Nth message from bottom\n"
            "  /fold threshold  Show or set auto-fold threshold\n"
            "  /fold threshold <n>  Set threshold (min 5, 0 = disabled)"
        )

    def _cmd_unfold(self, text: str) -> None:
        """Unfold/expand folded messages."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "all":
            self._unfold_all_messages()
            return
        if not arg:
            self._unfold_last_message()
            return

        self._add_system_message(
            "Usage: /unfold [all]\n"
            "  /unfold      Unfold the last folded message\n"
            "  /unfold all  Unfold all folded messages"
        )

    def _fold_last_message(self) -> None:
        """Fold the last unfolded foldable message (bottom-up)."""
        toggles = list(self.query(FoldToggle))
        for toggle in reversed(toggles):
            if not toggle._target.has_class("folded"):
                toggle._target.add_class("folded")
                toggle.update(toggle._make_label(folded=True))
                self._add_system_message("Folded last long message")
                return
        self._add_system_message("No unfoldable messages found")

    def _unfold_last_message(self) -> None:
        """Unfold the last folded message (bottom-up)."""
        toggles = list(self.query(FoldToggle))
        for toggle in reversed(toggles):
            if toggle._target.has_class("folded"):
                toggle._target.remove_class("folded")
                toggle.update(toggle._make_label(folded=False))
                self._add_system_message("Unfolded last folded message")
                return
        self._add_system_message("No folded messages found")

    def _fold_all_messages(self) -> None:
        """Fold all messages that have fold toggles."""
        count = 0
        for toggle in self.query(FoldToggle):
            if not toggle._target.has_class("folded"):
                toggle._target.add_class("folded")
                toggle.update(toggle._make_label(folded=True))
                count += 1
        self._add_system_message(f"Folded {count} message{'s' if count != 1 else ''}")

    def _unfold_all_messages(self) -> None:
        """Unfold all folded messages."""
        count = 0
        for toggle in self.query(FoldToggle):
            if toggle._target.has_class("folded"):
                toggle._target.remove_class("folded")
                toggle.update(toggle._make_label(folded=False))
                count += 1
        self._add_system_message(f"Unfolded {count} message{'s' if count != 1 else ''}")

    def _toggle_fold_all(self) -> None:
        """Toggle: fold unfolded messages, or unfold all if all are folded."""
        toggles = list(self.query(FoldToggle))
        if not toggles:
            self._add_system_message("No foldable messages")
            return
        any_unfolded = any(not t._target.has_class("folded") for t in toggles)
        if any_unfolded:
            self._fold_all_messages()
        else:
            self._unfold_all_messages()

    def _toggle_fold_nearest(self) -> None:
        """Toggle fold on the last foldable message (vim 'z' key)."""
        toggles = list(self.query(FoldToggle))
        if not toggles:
            return
        toggle = toggles[-1]
        folded = toggle._target.has_class("folded")
        if folded:
            toggle._target.remove_class("folded")
        else:
            toggle._target.add_class("folded")
        toggle.update(toggle._make_label(folded=not folded))

    def _toggle_fold_nth(self, n: int) -> None:
        """Toggle fold on the Nth foldable message from the bottom (1-based)."""
        toggles = list(self.query(FoldToggle))
        if not toggles:
            self._add_system_message("No foldable messages")
            return
        if n < 1 or n > len(toggles):
            self._add_system_message(
                f"Message #{n} not found ({len(toggles)} foldable message"
                f"{'s' if len(toggles) != 1 else ''} available)"
            )
            return
        toggle = toggles[-n]
        folded = toggle._target.has_class("folded")
        if folded:
            toggle._target.remove_class("folded")
        else:
            toggle._target.add_class("folded")
        toggle.update(toggle._make_label(folded=not folded))
        state = "unfolded" if folded else "folded"
        self._add_system_message(f"Message #{n} from bottom {state}")

