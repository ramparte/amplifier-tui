"""Git integration commands."""

from __future__ import annotations

import difflib

from ..features.git_integration import (
    run_git,
    looks_like_commit_ref,
    show_diff as _show_diff_text,
)


class GitCommandsMixin:
    """Git integration commands."""

    def _run_git(self, *args: str, cwd: str | None = None) -> tuple[bool, str]:
        """Run a git command and return *(success, output)*.

        Thin adapter — delegates to :func:`features.git_integration.run_git`.
        """
        return run_git(*args, cwd=cwd)

    # ------------------------------------------------------------------
    # Diff display helpers
    # ------------------------------------------------------------------

    def _cmd_git(self, text: str) -> None:
        """Quick git operations (read-only)."""
        text = text.strip()

        if not text:
            self._git_overview()
            return

        parts = text.split(None, 1)
        subcmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "status": self._git_status,
            "st": self._git_status,
            "log": self._git_log,
            "diff": self._git_diff_summary,
            "branch": self._git_branches,
            "br": self._git_branches,
            "stash": self._git_stashes,
            "blame": self._git_blame,
        }

        handler = handlers.get(subcmd)
        if handler:
            handler(args)
        else:
            self._add_system_message(
                f"Unknown git subcommand: {subcmd}\n\n"
                "Available: status (st), log, diff, branch (br), stash, blame"
            )

    def _git_overview(self) -> None:
        """Quick git overview: branch, status summary, ahead/behind."""
        from rich.markup import escape

        ok, branch = self._run_git("branch", "--show-current")
        if not ok:
            self._add_system_message(f"Not a git repo or git error: {branch}")
            return
        branch = branch.strip() or "(detached HEAD)"

        # Status summary
        _, status_out = self._run_git("status", "--porcelain")
        lines = [ln for ln in status_out.splitlines() if ln.strip()]
        staged = sum(1 for ln in lines if ln[0] not in (" ", "?"))
        modified = sum(1 for ln in lines if len(ln) > 1 and ln[1] == "M")
        untracked = sum(1 for ln in lines if ln.startswith("??"))

        # Ahead/behind
        ahead, behind = 0, 0
        ab_ok, ab_out = self._run_git(
            "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
        )
        if ab_ok and ab_out.strip():
            ab_parts = ab_out.strip().split()
            if len(ab_parts) == 2:
                ahead, behind = int(ab_parts[0]), int(ab_parts[1])

        # Last commit
        _, last_commit = self._run_git("log", "-1", "--format=%h %s (%cr)")

        parts = [f"[bold]Branch:[/bold] {escape(branch)}"]
        if staged:
            parts.append(f"  [green]Staged:[/green] {staged}")
        if modified:
            parts.append(f"  [yellow]Modified:[/yellow] {modified}")
        if untracked:
            parts.append(f"  [dim]Untracked:[/dim] {untracked}")
        if ahead:
            parts.append(f"  [cyan]↑ {ahead} ahead[/cyan]")
        if behind:
            parts.append(f"  [red]↓ {behind} behind[/red]")
        if not (staged or modified or untracked):
            parts.append("  [green]Clean working tree[/green]")
        if last_commit.strip():
            parts.append(f"\n[dim]Last:[/dim] {escape(last_commit.strip())}")

        self._add_system_message("\n".join(parts))

    def _git_status(self, args: str) -> None:
        """Detailed git status."""
        ok, out = self._run_git("status", "--short", "--branch")
        if not ok:
            self._add_system_message(f"git status error: {out}")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_log(self, args: str) -> None:
        """Recent commits."""
        n = "10"
        if args.strip().isdigit():
            n = args.strip()
        ok, out = self._run_git(
            "log",
            f"-{n}",
            "--format=%h %s (%cr) <%an>",
        )
        if not ok:
            self._add_system_message(f"git log error: {out}")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_diff_summary(self, args: str) -> None:
        """Diff summary or specific file diff."""
        if args.strip():
            ok, out = self._run_git("diff", args.strip())
        else:
            ok, out = self._run_git("diff", "--stat")
        if not ok:
            self._add_system_message(f"git diff error: {out}")
            return
        if not out.strip():
            self._add_system_message("No changes (working tree clean)")
            return
        # Truncate if too long
        lines = out.splitlines()
        if len(lines) > 50:
            out = "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} more lines)"
        # Use colorized display for actual diffs, plain for --stat
        if args.strip():
            self._add_system_message(_show_diff_text(out))
        else:
            self._add_system_message(f"```\n{out}\n```")

    def _git_branches(self, args: str) -> None:
        """List branches."""
        ok, out = self._run_git("branch", "-vv")
        if not ok:
            self._add_system_message(f"git branch error: {out}")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_stashes(self, args: str) -> None:
        """List stashes."""
        ok, out = self._run_git("stash", "list")
        if not ok:
            self._add_system_message(f"git stash error: {out}")
            return
        if not out.strip():
            self._add_system_message("No stashes")
            return
        self._add_system_message(f"```\n{out}\n```")

    def _git_blame(self, args: str) -> None:
        """Quick blame view."""
        if not args.strip():
            self._add_system_message("Usage: /git blame <file>")
            return
        ok, out = self._run_git("blame", "--date=short", args.strip())
        if not ok:
            self._add_system_message(f"git blame error: {out}")
            return
        lines = out.splitlines()
        if len(lines) > 50:
            out = "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} more lines)"
        self._add_system_message(f"```\n{out}\n```")

    # ------------------------------------------------------------------
    # /diff command
    # ------------------------------------------------------------------

    def _cmd_diff(self, text: str) -> None:
        """Show git diff with color-coded output, or compare messages.

        /diff              Unstaged changes (or file summary when clean)
        /diff staged       Staged changes
        /diff all          All unstaged (+ staged fallback)
        /diff last         Re-show last file-edit diff from tool calls
        /diff <file>       Diff for one file (tries staged too)
        /diff <f1> <f2>    Compare two files
        /diff HEAD~N       Changes since N commits ago
        /diff <commit>     Changes since a commit
        /diff msgs         Diff last two assistant messages
        /diff msgs N M     Diff message N vs M (from bottom, 1-based)
        /diff msgs last    Same as /diff msgs
        """
        text = text.strip()

        # --- /diff msgs ... -> message comparison ---
        if text == "msgs" or text.startswith("msgs "):
            self._cmd_diff_msgs(text[4:].strip())
            return

        # Check if we're inside a git repo
        ok, _ = self._run_git("rev-parse", "--is-inside-work-tree")
        if not ok:
            self._add_system_message("Not in a git repository")
            return

        # --- /diff (no args) -> unstaged diff, or status summary ---
        if not text:
            ok, output = self._run_git("diff", "--color=never")
            if not ok:
                self._add_system_message(f"git error: {output}")
                return
            if not output:
                # No unstaged diff — show status summary as guidance
                ok, status = self._run_git("status", "--short")
                if not ok or not status:
                    self._add_system_message("No changes detected (working tree clean)")
                    return
                lines = ["No unstaged changes. Changed files:", ""]
                for line in status.split("\n"):
                    if line.strip():
                        lines.append(f"  {line}")
                lines.append("")
                lines.append("Use /diff staged, /diff <file>, or /diff all")
                self._add_system_message("\n".join(lines))
                return
            self._add_system_message(_show_diff_text(output))
            return

        # --- /diff all ---
        if text == "all":
            ok, output = self._run_git("diff", "--color=never")
            if not ok or not output:
                # Also check staged changes
                ok2, staged = self._run_git("diff", "--staged", "--color=never")
                if staged:
                    output = staged
                elif not output:
                    self._add_system_message("No changes")
                    return
            self._add_system_message(_show_diff_text(output))
            return

        # --- /diff staged ---
        if text == "staged":
            ok, output = self._run_git("diff", "--staged", "--color=never")
            if not ok or not output:
                self._add_system_message("No staged changes")
                return
            self._add_system_message(_show_diff_text(output))
            return

        # --- /diff last  (most recent file-edit diff from tool calls) ---
        if text == "last":
            last_diff = getattr(self, "_last_file_edit_diff", None)
            if last_diff is not None:
                _title, diff_text = last_diff
                self._add_system_message(diff_text)
            else:
                self._add_system_message(
                    "No file-edit diffs in this session.\n"
                    "Use /diff HEAD~1 for the last git commit diff."
                )
            return

        # --- /diff <file1> <file2> (two paths) ---
        if " " in text:
            parts = text.split(None, 1)
            if len(parts) == 2:
                # --no-index returns exit-code 1 when files differ (normal)
                _ok, output = self._run_git(
                    "diff",
                    "--no-index",
                    "--color=never",
                    parts[0],
                    parts[1],
                )
                if not output:
                    self._add_system_message(
                        f"No differences between '{parts[0]}' and '{parts[1]}'"
                    )
                    return
                self._add_system_message(_show_diff_text(output))
                return

        # --- /diff HEAD~N or commit-ish ---
        if looks_like_commit_ref(text):
            ok, output = self._run_git("diff", text, "--color=never")
            if not ok:
                self._add_system_message(f"git error: {output}")
                return
            if not output:
                self._add_system_message(f"No changes from {text}")
                return
            self._add_system_message(_show_diff_text(output))
            return

        # --- /diff <file> ---
        ok, output = self._run_git("diff", "--color=never", "--", text)
        if not ok:
            self._add_system_message(f"git error: {output}")
            return
        if not output:
            # Try staged changes for this file
            ok, output = self._run_git("diff", "--staged", "--color=never", "--", text)
            if not ok or not output:
                self._add_system_message(f"No changes for '{text}'")
                return
        self._add_system_message(_show_diff_text(output))

    # ------------------------------------------------------------------
    # /diff msgs  – compare two chat messages
    # ------------------------------------------------------------------

    def _cmd_diff_msgs(self, text: str) -> None:
        """Compare two chat messages side-by-side (unified diff).

        /diff msgs          Last two assistant messages
        /diff msgs last     Same as above
        /diff msgs N M      Message N vs M (from bottom, 1-based)
        """
        from rich.markup import escape

        # Collect non-system messages for indexing
        messages = [
            (role, content)
            for role, content, _ in self._search_messages
            if role in ("user", "assistant")
        ]

        if len(messages) < 2:
            self._add_system_message("Need at least 2 messages to diff")
            return

        # Parse arguments
        if not text or text == "last":
            # Diff last two assistant messages
            assistant_msgs = [(r, c) for r, c in messages if r == "assistant"]
            if len(assistant_msgs) < 2:
                self._add_system_message("Need at least 2 assistant messages to diff")
                return
            msg_a = assistant_msgs[-2][1]
            msg_b = assistant_msgs[-1][1]
            label_a = "Previous response"
            label_b = "Latest response"
        else:
            parts = text.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                n, m = int(parts[0]), int(parts[1])
                total = len(messages)
                if n < 1 or n > total or m < 1 or m > total:
                    self._add_system_message(
                        f"Message numbers must be 1\u2013{total} (from bottom)"
                    )
                    return
                if n == m:
                    self._add_system_message("Messages are identical (same index)")
                    return
                msg_a = messages[-n][1]
                msg_b = messages[-m][1]
                role_a = messages[-n][0]
                role_b = messages[-m][0]
                label_a = f"Message #{n} from bottom ({role_a})"
                label_b = f"Message #{m} from bottom ({role_b})"
            else:
                self._add_system_message("Usage: /diff msgs [N M | last]")
                return

        # Generate unified diff
        lines_a = msg_a.splitlines(keepends=True)
        lines_b = msg_b.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=label_a,
                tofile=label_b,
                n=3,
            )
        )

        if not diff:
            self._add_system_message("Messages are identical")
            return

        # Count changes
        additions = sum(
            1 for ln in diff if ln.startswith("+") and not ln.startswith("+++")
        )
        deletions = sum(
            1 for ln in diff if ln.startswith("-") and not ln.startswith("---")
        )

        # Format with Rich markup colors
        formatted: list[str] = []
        for line in diff:
            line = line.rstrip("\n")
            escaped = escape(line)
            if line.startswith("+++") or line.startswith("---"):
                formatted.append(f"[bold]{escaped}[/bold]")
            elif line.startswith("+"):
                formatted.append(f"[green]{escaped}[/green]")
            elif line.startswith("-"):
                formatted.append(f"[red]{escaped}[/red]")
            elif line.startswith("@@"):
                formatted.append(f"[cyan]{escaped}[/cyan]")
            else:
                formatted.append(escaped)

        # Truncate very long diffs
        max_lines = 200
        truncated = len(formatted) > max_lines
        if truncated:
            remaining = len(formatted) - max_lines
            formatted = formatted[:max_lines]
            formatted.append(f"\n... and {remaining} more lines (diff truncated)")

        summary = f"\n\n{additions} addition(s), {deletions} deletion(s)"
        result = "\n".join(formatted) + summary

        self._add_system_message(f"Message diff:\n{result}")
