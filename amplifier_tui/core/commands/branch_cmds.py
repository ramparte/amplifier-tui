"""Branch management commands (F3.1 - Conversation Branching)."""

from __future__ import annotations


class BranchCommandsMixin:
    """Mixin providing /fork (extended), /branches, and /branch commands."""

    def _cmd_fork(self, args: str) -> None:  # type: ignore[override]
        """Create a new conversation branch, or fork into a new tab.

        Extended behavior:
        - ``/fork`` with no args → show usage help
        - ``/fork <number>`` → legacy tab-fork (delegates to session mixin)
        - ``/fork <name> [description]`` → create a named branch
        """
        text = args.strip() if args else ""

        if not text:
            self._add_system_message(  # type: ignore[attr-defined]
                "[bold]Fork / Branch[/bold]\n\n"
                "  /fork <name> [description]  Create a named branch\n"
                "  /fork <N>                   Fork at message N into a new tab\n"
                "  /branches                   Show branch tree\n"
                "  /branch switch <name>       Switch to a branch\n"
                "  /branch compare <a> <b>     Compare two branches\n"
                "  /branch merge <name>        Merge messages from a branch\n"
                "  /branch delete <name>       Delete a branch"
            )
            return

        # If the argument is a bare integer, delegate to legacy tab-fork
        if text.isdigit():
            self._cmd_fork_tab(text)  # type: ignore[attr-defined]
            return

        # Otherwise, create a named branch
        parts = text.split(None, 1)
        branch_name = parts[0]
        description = parts[1] if len(parts) > 1 else ""

        # Use the length of _search_messages as the fork point
        fork_point = len(getattr(self, "_search_messages", []))

        try:
            self._branch_manager.fork(  # type: ignore[attr-defined]
                name=branch_name,
                fork_point=fork_point,
                description=description,
            )
            self._add_system_message(  # type: ignore[attr-defined]
                f"Created branch [cyan]{branch_name}[/cyan] "
                f"at message {fork_point}.\n"
                f"Use /branch switch {branch_name} to switch to it.\n"
                f"Use /branches to see all branches."
            )
        except ValueError as e:
            self._add_system_message(f"[red]Error:[/red] {e}")  # type: ignore[attr-defined]

    def _cmd_branches(self, args: str = "") -> None:
        """Show all conversation branches."""
        self._add_system_message(  # type: ignore[attr-defined]
            self._branch_manager.format_tree()  # type: ignore[attr-defined]
        )

    def _cmd_branch(self, args: str = "") -> None:
        """Handle /branch subcommands."""
        text = args.strip() if args else ""

        if not text:
            # Show current branch info
            current = self._branch_manager.current_branch  # type: ignore[attr-defined]
            branch = self._branch_manager.get_branch(current)  # type: ignore[attr-defined]
            if branch:
                self._add_system_message(  # type: ignore[attr-defined]
                    f"Current branch: [cyan]{current}[/cyan]\n"
                    f"Messages: {branch.message_count}\n"
                    f"Fork point: {branch.fork_point}"
                )
            return

        parts = text.split(None, 2)
        subcmd = parts[0].lower()

        if subcmd == "switch" and len(parts) >= 2:
            name = parts[1]
            try:
                self._branch_manager.switch(name)  # type: ignore[attr-defined]
                self._add_system_message(  # type: ignore[attr-defined]
                    f"Switched to branch [cyan]{name}[/cyan]."
                )
            except KeyError as e:
                self._add_system_message(f"[red]Error:[/red] {e}")  # type: ignore[attr-defined]
            return

        if subcmd == "compare" and len(parts) >= 3:
            self._add_system_message(  # type: ignore[attr-defined]
                self._branch_manager.format_compare(parts[1], parts[2])  # type: ignore[attr-defined]
            )
            return

        if subcmd == "merge" and len(parts) >= 2:
            name = parts[1]
            try:
                messages = self._branch_manager.merge_messages(name)  # type: ignore[attr-defined]
                if messages:
                    self._add_system_message(  # type: ignore[attr-defined]
                        f"Merged {len(messages)} messages from "
                        f"[cyan]{name}[/cyan] into current branch."
                    )
                else:
                    self._add_system_message(  # type: ignore[attr-defined]
                        f"Branch [cyan]{name}[/cyan] has no messages to merge."
                    )
            except KeyError as e:
                self._add_system_message(f"[red]Error:[/red] {e}")  # type: ignore[attr-defined]
            return

        if subcmd == "delete" and len(parts) >= 2:
            name = parts[1]
            try:
                self._branch_manager.delete_branch(name)  # type: ignore[attr-defined]
                self._add_system_message(  # type: ignore[attr-defined]
                    f"Deleted branch [cyan]{name}[/cyan]."
                )
            except (ValueError, KeyError) as e:
                self._add_system_message(f"[red]Error:[/red] {e}")  # type: ignore[attr-defined]
            return

        if subcmd == "list":
            self._cmd_branches("")
            return

        self._add_system_message(  # type: ignore[attr-defined]
            "[bold]Branch subcommands:[/bold]\n\n"
            "  /branch                        Show current branch info\n"
            "  /branch switch <name>          Switch to a branch\n"
            "  /branch compare <a> <b>        Compare two branches\n"
            "  /branch merge <name>           Merge messages from branch\n"
            "  /branch delete <name>          Delete a branch\n"
            "  /branch list                   Same as /branches"
        )
