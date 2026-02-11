"""Split pane and tab management commands."""

from __future__ import annotations

import os

from textual.containers import ScrollableContainer
from textual.css.query import NoMatches
from textual.widgets import Static

from ..log import logger
from ..widgets import (
    ChatInput,
)


class SplitCommandsMixin:
    """Split pane and tab management commands."""

    def _cmd_tab(self, args: str) -> None:
        """Handle /tab subcommands."""
        args = args.strip()
        if not args:
            # List tabs (same as /tabs)
            lines = ["Tabs:"]
            for i, tab in enumerate(self._tabs):
                marker = " ▶" if i == self._active_tab_index else "  "
                sid = ""
                if tab.conversation.session_id or (
                    i == self._active_tab_index
                    and self.session_manager
                    and getattr(self.session_manager, "session_id", None)
                ):
                    s = (
                        tab.conversation.session_id
                        if i != self._active_tab_index
                        else getattr(self.session_manager, "session_id", "")
                    )
                    if s:
                        sid = f" [{s[:8]}]"
                display_name = tab.custom_name or tab.name
                lines.append(f"{marker} {i + 1}. {display_name}{sid}")
            lines.append("")
            lines.append(
                "Usage: /tab new [name] | switch <n> | close [n] | rename <name>"
            )
            self._add_system_message("\n".join(lines))
            return

        parts = args.split(None, 1)
        subcmd = parts[0].lower()
        subargs = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "new":
            self._create_new_tab(subargs or None)
        elif subcmd == "switch":
            if not subargs:
                self._add_system_message("Usage: /tab switch <name|number>")
                return
            idx = self._find_tab_by_name_or_index(subargs)
            if idx is None:
                self._add_system_message(f"Tab not found: {subargs}")
                return
            self._switch_to_tab(idx)
        elif subcmd == "close":
            if not subargs:
                self._close_tab()
            else:
                idx = self._find_tab_by_name_or_index(subargs)
                if idx is None:
                    self._add_system_message(f"Tab not found: {subargs}")
                    return
                self._close_tab(idx)
        elif subcmd == "rename":
            if not subargs:
                self._add_system_message("Usage: /tab rename <new-name>")
                return
            name = subargs[:30]
            self._rename_tab(name)
            self._add_system_message(f'Tab renamed to: "{name}"')
        elif subcmd == "list":
            # Recurse with empty args to show list
            self._cmd_tab("")
        else:
            # Maybe a number or name for quick switch
            idx = self._find_tab_by_name_or_index(subcmd)
            if idx is not None:
                self._switch_to_tab(idx)
            else:
                self._add_system_message(
                    "Unknown /tab subcommand. "
                    "Usage: /tab new [name] | switch <n> | close [n] | rename <name>"
                )

    def _cmd_split(self, text: str) -> None:
        """Toggle or configure split view.

        /split          Toggle tab split (2+ tabs) or reference panel
        /split N        Split current tab with tab N
        /split off      Close any split view
        /split swap     Swap left and right panes (tab split)
        /split pins     Show pinned messages in right panel
        /split chat     Mirror of chat at independent scroll position
        /split file <p> Show file content in right panel
        """
        raw = text.strip() if text else ""
        lower = raw.lower()

        if lower == "off":
            if self._tab_split_mode:
                self._exit_tab_split()
            else:
                self._close_split()
            return

        if lower == "swap":
            if self._tab_split_mode:
                self._swap_tab_split()
            else:
                self._add_system_message("Swap requires tab split mode")
            return

        if lower == "pins":
            if self._tab_split_mode:
                self._exit_tab_split()
            self._open_split_pins()
            return

        if lower == "chat":
            if self._tab_split_mode:
                self._exit_tab_split()
            self._open_split_chat()
            return

        # /split file <path> – preserve original case for the path
        if lower.startswith("file ") or lower.startswith("file\t"):
            if self._tab_split_mode:
                self._exit_tab_split()
            path = raw[5:].strip()
            if not path:
                self._add_system_message("Usage: /split file <path>")
                return
            self._open_split_file(path)
            return

        # /split N – split with a specific tab number
        if lower and lower.isdigit():
            target_index = int(lower) - 1  # 1-based to 0-based
            if target_index < 0 or target_index >= len(self._tabs):
                self._add_system_message(
                    f"Tab {lower} not found (have {len(self._tabs)} tabs)"
                )
                return
            if target_index == self._active_tab_index:
                self._add_system_message("Cannot split a tab with itself")
                return
            if self.has_class("split-mode"):
                self._close_split()
            if self._tab_split_mode:
                self._exit_tab_split()
            self._enter_tab_split(self._active_tab_index, target_index)
            return

        if lower == "on" or not lower:
            # Toggle: if already in any split, exit
            if self._tab_split_mode:
                self._exit_tab_split()
                return
            if self.has_class("split-mode"):
                self._close_split()
                return
            # Enter tab split if 2+ tabs, otherwise fall back to pins
            if len(self._tabs) >= 2:
                next_idx = (self._active_tab_index + 1) % len(self._tabs)
                self._enter_tab_split(self._active_tab_index, next_idx)
            else:
                self._open_split_pins()
            return

        self._add_system_message(
            "Usage: /split [on|off|swap|N|pins|chat|file <path>]\n"
            "  /split          Toggle tab split (2+ tabs) or reference panel\n"
            "  /split N        Split current tab with tab N\n"
            "  /split swap     Swap left and right panes\n"
            "  /split off      Close split view\n"
            "  /split pins     Pinned messages in right panel\n"
            "  /split chat     Chat mirror (independent scroll)\n"
            "  /split file <p> File content in right panel\n"
            "  Alt+Left/Right  Switch active pane in split mode"
        )

    def _open_split_pins(self) -> None:
        """Open split panel showing pinned messages."""
        panel = self.query_one("#split-panel", ScrollableContainer)
        panel.remove_children()

        panel.mount(Static("\U0001f4cc Pinned Messages", classes="split-panel-title"))

        if not self._message_pins:
            panel.mount(
                Static(
                    "No pinned messages.\nUse /pin to pin messages.",
                    classes="split-panel-hint",
                )
            )
        else:
            total = len(self._search_messages)
            for i, pin in enumerate(self._message_pins, 1):
                idx = pin["index"]
                if idx < total:
                    role, content, _widget = self._search_messages[idx]
                else:
                    role = "?"
                    content = pin.get("preview", "(unavailable)")
                role_label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                    role, role
                )
                pin_label = pin.get("label", "")
                label_str = f" [{pin_label}]" if pin_label else ""
                # Truncate very long content for display
                display = content[:500]
                if len(content) > 500:
                    display += "\n..."
                panel.mount(
                    Static(
                        f"[bold]#{i} ({role_label} msg {idx + 1}){label_str}:[/bold]\n{display}",
                        classes="split-panel-content",
                    )
                )

        panel.mount(
            Static(
                "Tab to switch focus • /split off to close",
                classes="split-panel-hint",
            )
        )

        self.add_class("split-mode")
        self._add_system_message("Split view: pinned messages (Tab to switch panels)")

    def _open_split_chat(self) -> None:
        """Open split panel with a copy of current chat messages."""
        panel = self.query_one("#split-panel", ScrollableContainer)
        panel.remove_children()

        panel.mount(Static("\U0001f4ac Chat Reference", classes="split-panel-title"))

        if not self._search_messages:
            panel.mount(Static("No messages yet.", classes="split-panel-hint"))
        else:
            for role, content, _widget in self._search_messages:
                label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                    role, role
                )
                # Truncate very long messages
                display = content[:800]
                if len(content) > 800:
                    display += "\n..."
                panel.mount(
                    Static(
                        f"[bold]{label}:[/bold] {display}",
                        classes="split-panel-content",
                    )
                )

        panel.mount(
            Static(
                "Tab to switch focus • /split off to close",
                classes="split-panel-hint",
            )
        )

        self.add_class("split-mode")
        self._add_system_message("Split view: chat reference (Tab to switch panels)")

    def _open_split_file(self, path: str) -> None:
        """Open split panel showing file content."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(abs_path):
            self._add_system_message(f"File not found: {path}")
            return

        try:
            with open(abs_path) as f:
                content = f.read()
        except OSError as e:
            logger.debug("Failed to read file %s", abs_path, exc_info=True)
            self._add_system_message(f"Cannot read file: {e}")
            return

        panel = self.query_one("#split-panel", ScrollableContainer)
        panel.remove_children()

        rel = os.path.relpath(abs_path)
        panel.mount(Static(f"\U0001f4c4 {rel}", classes="split-panel-title"))

        # Truncate very large files for display
        display = content
        if len(display) > 10_000:
            display = (
                display[:10_000] + f"\n\n... ({len(content):,} chars total, truncated)"
            )

        panel.mount(Static(display, classes="split-panel-content"))

        panel.mount(
            Static(
                "Tab to switch focus • /split off to close",
                classes="split-panel-hint",
            )
        )

        self.add_class("split-mode")
        self._add_system_message(f"Split view: {rel}")

    def _close_split(self) -> None:
        """Close the reference split panel."""
        self.remove_class("split-mode")
        try:
            panel = self.query_one("#split-panel", ScrollableContainer)
            panel.remove_children()
        except NoMatches:
            logger.debug("Split panel not found during close", exc_info=True)
        self._add_system_message("Split view closed")

    # ── Tab split view (two live tabs side by side) ──────────────────────

    def _enter_tab_split(self, left_index: int, right_index: int) -> None:
        """Enter tab split mode showing two tabs side by side."""
        if self.is_processing:
            self._add_system_message("Cannot enter split view while processing.")
            return

        self._save_current_tab_state()

        self._tab_split_mode = True
        self._tab_split_left_index = left_index
        self._tab_split_right_index = right_index
        self._tab_split_active = "left"
        self._active_tab_index = left_index

        # Load left tab state
        self._load_tab_state(self._tabs[left_index])

        # Show both containers side by side
        left_tab = self._tabs[left_index]
        right_tab = self._tabs[right_index]

        try:
            left_container = self.query_one(
                f"#{left_tab.container_id}", ScrollableContainer
            )
            right_container = self.query_one(
                f"#{right_tab.container_id}", ScrollableContainer
            )

            # Ensure both are visible
            left_container.remove_class("tab-chat-hidden")
            right_container.remove_class("tab-chat-hidden")

            # Add split styling classes
            left_container.add_class("split-left-pane")
            right_container.add_class("split-right-pane")
            left_container.add_class("split-pane-active")

            # Ensure correct DOM order: left before right
            # (move right after left in case they aren't adjacent)
            right_container.move_after(left_container)
        except Exception:
            logger.debug("Failed to set up tab split view", exc_info=True)
            self._tab_split_mode = False
            self._tab_split_left_index = None
            self._tab_split_right_index = None
            self._add_system_message("Failed to set up split view")
            return

        self.add_class("tab-split-mode")

        left_name = self._tabs[left_index].name
        right_name = self._tabs[right_index].name
        self._update_tab_bar()
        self._add_system_message(
            f"Split view: [{left_name}] | [{right_name}]\n"
            "Alt+Left/Right or Ctrl+W to switch pane \u2022 /split off to close"
        )

    def _exit_tab_split(self) -> None:
        """Exit tab split mode, return to single-pane view."""
        if not self._tab_split_mode:
            return

        self._save_current_tab_state()

        left_index = self._tab_split_left_index
        right_index = self._tab_split_right_index
        active_index = self._active_tab_index

        # Determine which tab is NOT active (needs to be hidden)
        if left_index is not None and right_index is not None:
            other_index = right_index if active_index == left_index else left_index
        else:
            other_index = None

        # Clean up CSS classes from both containers
        for idx in (left_index, right_index):
            if idx is not None and idx < len(self._tabs):
                tab = self._tabs[idx]
                try:
                    container = self.query_one(
                        f"#{tab.container_id}", ScrollableContainer
                    )
                    container.remove_class(
                        "split-left-pane",
                        "split-right-pane",
                        "split-pane-active",
                    )
                except NoMatches:
                    logger.debug(
                        "Container not found during split cleanup", exc_info=True
                    )

        # Hide the non-active tab's container
        if other_index is not None and other_index < len(self._tabs):
            other_tab = self._tabs[other_index]
            try:
                other_container = self.query_one(
                    f"#{other_tab.container_id}", ScrollableContainer
                )
                other_container.add_class("tab-chat-hidden")
            except NoMatches:
                logger.debug("Container not found during split exit", exc_info=True)

        self.remove_class("tab-split-mode")
        self._tab_split_mode = False
        self._tab_split_left_index = None
        self._tab_split_right_index = None
        self._tab_split_active = "left"

        self._update_tab_bar()
        self._add_system_message("Split view closed")

    def _swap_tab_split(self) -> None:
        """Swap left and right panes in tab split mode."""
        if not self._tab_split_mode:
            return

        left_index = self._tab_split_left_index
        right_index = self._tab_split_right_index

        if left_index is None or right_index is None:
            return

        # Swap indices
        self._tab_split_left_index = right_index
        self._tab_split_right_index = left_index

        # Update CSS classes on containers
        old_left_tab = self._tabs[left_index]
        old_right_tab = self._tabs[right_index]

        try:
            old_left_container = self.query_one(
                f"#{old_left_tab.container_id}", ScrollableContainer
            )
            old_right_container = self.query_one(
                f"#{old_right_tab.container_id}", ScrollableContainer
            )

            # Swap left/right CSS classes
            old_left_container.remove_class("split-left-pane")
            old_left_container.add_class("split-right-pane")

            old_right_container.remove_class("split-right-pane")
            old_right_container.add_class("split-left-pane")

            # Reorder in DOM so new-left appears before new-right
            old_right_container.move_before(old_left_container)
        except Exception:
            logger.debug("Failed to swap split panes", exc_info=True)

        # Update active indicator
        self._update_split_active_indicator()

        left_name = self._tabs[self._tab_split_left_index].name
        right_name = self._tabs[self._tab_split_right_index].name
        self._update_tab_bar()
        self._add_system_message(f"Panes swapped: [{left_name}] | [{right_name}]")

    def _switch_split_pane(self) -> None:
        """Switch the active pane in tab split mode."""
        if not self._tab_split_mode:
            return

        self._save_current_tab_state()

        # Toggle active side
        if self._tab_split_active == "left":
            self._tab_split_active = "right"
            self._active_tab_index = self._tab_split_right_index or 0
        else:
            self._tab_split_active = "left"
            self._active_tab_index = self._tab_split_left_index or 0

        # Load the newly active tab's state
        self._load_tab_state(self._tabs[self._active_tab_index])

        # Update visual indicator
        self._update_split_active_indicator()

        # Update UI
        self._update_tab_bar()
        self._update_session_display()
        self._update_word_count_display()
        self._update_breadcrumb()
        self._update_pinned_panel()
        self.sub_title = self._session_title or ""

        # Restore input text for the new active pane's tab
        try:
            input_widget = self.query_one("#chat-input", ChatInput)
            active_tab = self._tabs[self._active_tab_index]
            input_widget.clear()
            if active_tab.input_text:
                input_widget.insert(active_tab.input_text)
            input_widget.focus()
        except Exception:
            logger.debug("Failed to restore input for split pane", exc_info=True)

    def _update_split_active_indicator(self) -> None:
        """Update CSS classes to show which pane is active in tab split."""
        if not self._tab_split_mode:
            return

        for idx in (self._tab_split_left_index, self._tab_split_right_index):
            if idx is not None and idx < len(self._tabs):
                tab = self._tabs[idx]
                try:
                    container = self.query_one(
                        f"#{tab.container_id}", ScrollableContainer
                    )
                    if idx == self._active_tab_index:
                        container.add_class("split-pane-active")
                    else:
                        container.remove_class("split-pane-active")
                except NoMatches:
                    logger.debug(
                        "Container not found during active indicator update",
                        exc_info=True,
                    )

    # ── /watch – file change monitoring ──────────────────────────────────
