"""Conversation branch manager for fork/switch/compare operations (F3.1).

Tracks named branches of conversation within a session.  Each branch
records its parent, the message index where it forked, and any messages
added after the fork.  The ``main`` branch always exists and represents
the primary conversation — its messages are managed externally by the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConversationBranch:
    """A named branch of conversation."""

    name: str
    parent_branch: str = "main"  # which branch this was forked from
    fork_point: int = 0  # message index where fork occurred
    messages: list[dict] = field(default_factory=list)  # messages added after fork
    created_at: datetime = field(default_factory=datetime.now)
    description: str = ""

    @property
    def message_count(self) -> int:
        return len(self.messages)


class BranchManager:
    """Manages conversation branches for fork/switch/compare operations."""

    def __init__(self) -> None:
        self._branches: dict[str, ConversationBranch] = {}
        self._current_branch: str = "main"
        # Main branch messages are managed externally by the app.
        # We just track metadata here.
        self._branches["main"] = ConversationBranch(
            name="main",
            parent_branch="",
            fork_point=0,
            description="Main conversation",
        )

    @property
    def current_branch(self) -> str:
        return self._current_branch

    @property
    def branch_names(self) -> list[str]:
        return sorted(self._branches.keys())

    def get_branch(self, name: str) -> ConversationBranch | None:
        return self._branches.get(name)

    def fork(
        self,
        name: str,
        fork_point: int,
        description: str = "",
        snapshot_messages: list[dict] | None = None,
    ) -> ConversationBranch:
        """Create a new branch from the current branch at the given message index.

        Args:
            name: Branch name (must be unique).
            fork_point: Message index where the fork occurs.
            description: Optional description.
            snapshot_messages: Messages up to the fork point (for context).

        Returns:
            The new ConversationBranch.

        Raises:
            ValueError: If branch name already exists or is invalid.
        """
        if not name or name == "main":
            raise ValueError(f"Invalid branch name: '{name}'")
        if name in self._branches:
            raise ValueError(f"Branch '{name}' already exists")

        branch = ConversationBranch(
            name=name,
            parent_branch=self._current_branch,
            fork_point=fork_point,
            description=description,
            messages=list(snapshot_messages) if snapshot_messages else [],
        )
        self._branches[name] = branch
        return branch

    def switch(self, name: str) -> ConversationBranch:
        """Switch to a different branch.

        Returns:
            The branch switched to.

        Raises:
            KeyError: If branch doesn't exist.
        """
        if name not in self._branches:
            raise KeyError(f"Branch '{name}' not found")
        self._current_branch = name
        return self._branches[name]

    def add_message(self, message: dict) -> None:
        """Add a message to the current branch (non-main branches only)."""
        if self._current_branch != "main" and self._current_branch in self._branches:
            self._branches[self._current_branch].messages.append(message)

    def delete_branch(self, name: str) -> None:
        """Delete a branch.

        Raises:
            ValueError: If trying to delete main.
            KeyError: If branch doesn't exist.
        """
        if name == "main":
            raise ValueError("Cannot delete main branch")
        if name not in self._branches:
            raise KeyError(f"Branch '{name}' not found")
        if self._current_branch == name:
            self._current_branch = "main"
        del self._branches[name]

    def merge_messages(self, source_name: str) -> list[dict]:
        """Get messages from a branch for merging into current.

        Returns the branch's messages (caller decides how to merge them).

        Raises:
            KeyError: If branch doesn't exist.
        """
        if source_name not in self._branches:
            raise KeyError(f"Branch '{source_name}' not found")
        return list(self._branches[source_name].messages)

    def format_tree(self) -> str:
        """Format all branches as a Rich-markup tree view."""
        if len(self._branches) <= 1:
            return (
                "[bold]main[/bold] (no branches yet)\n\n"
                "Use /fork <name> to create a branch."
            )

        lines: list[str] = []
        # Build parent -> children mapping
        children: dict[str, list[str]] = {}
        for name, branch in self._branches.items():
            parent = branch.parent_branch or ""
            if parent not in children:
                children[parent] = []
            if name != "main":
                children[parent].append(name)

        # Render from main
        current_marker = (
            " [yellow]<-- current[/yellow]" if self._current_branch == "main" else ""
        )
        lines.append(f"[bold]main[/bold]{current_marker}")
        self._render_branch_children("main", children, lines, "  ")

        return "\n".join(lines)

    def _render_branch_children(
        self,
        parent: str,
        children: dict[str, list[str]],
        lines: list[str],
        prefix: str,
    ) -> None:
        """Recursively render branch children."""
        kids = children.get(parent, [])
        for i, name in enumerate(sorted(kids)):
            branch = self._branches[name]
            is_last = i == len(kids) - 1
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "

            current_marker = (
                " [yellow]<-- current[/yellow]" if self._current_branch == name else ""
            )
            msg_info = (
                f"({branch.message_count} messages)"
                if branch.message_count
                else "(empty)"
            )
            fork_info = f"[dim]@msg {branch.fork_point}[/dim]"

            desc = f" - {branch.description}" if branch.description else ""
            lines.append(
                f"{prefix}{connector}[cyan]{name}[/cyan] {fork_info} "
                f"{msg_info}{desc}{current_marker}"
            )

            # Recurse for nested branches
            extension = prefix + ("    " if is_last else "\u2502   ")
            self._render_branch_children(name, children, lines, extension)

    def format_compare(self, name_a: str, name_b: str) -> str:
        """Format a comparison of two branches."""
        branch_a = self._branches.get(name_a)
        branch_b = self._branches.get(name_b)

        if not branch_a:
            return f"Branch '{name_a}' not found."
        if not branch_b:
            return f"Branch '{name_b}' not found."

        lines = [
            "[bold]Comparing branches:[/bold]",
            "",
            f"  [cyan]{name_a}[/cyan]",
            f"    Parent: {branch_a.parent_branch}",
            f"    Fork point: message {branch_a.fork_point}",
            f"    Messages: {branch_a.message_count}",
            f"    Created: {branch_a.created_at.strftime('%H:%M:%S')}",
            "",
            f"  [cyan]{name_b}[/cyan]",
            f"    Parent: {branch_b.parent_branch}",
            f"    Fork point: message {branch_b.fork_point}",
            f"    Messages: {branch_b.message_count}",
            f"    Created: {branch_b.created_at.strftime('%H:%M:%S')}",
        ]

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all branches except main."""
        self._branches = {
            "main": ConversationBranch(
                name="main",
                parent_branch="",
                fork_point=0,
                description="Main conversation",
            )
        }
        self._current_branch = "main"
