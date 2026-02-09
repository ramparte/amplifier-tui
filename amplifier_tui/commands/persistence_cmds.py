"""Bookmarks, pins, notes, drafts, snippets, and templates."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import re

from ..log import logger
from ..constants import (
    SLASH_COMMANDS,
)
from ..widgets import (
    ChatInput,
)


class PersistenceCommandsMixin:
    """Bookmarks, pins, notes, drafts, snippets, and templates."""

    def _cmd_ref(self, text: str) -> None:
        """Handle /ref command for URL/reference collection."""
        # Strip the command prefix ("/ref" or "/refs")
        parts = text.strip().split(None, 1)
        args = parts[1].strip() if len(parts) > 1 else ""

        # /ref  or  /refs  — list all refs
        if not args:
            if not self._session_refs:
                self._add_system_message(
                    "No saved references.\n"
                    "Add: /ref <url-or-text> [label]\n"
                    "Example: /ref https://docs.python.org Python Docs"
                )
                return
            lines = ["Saved References:"]
            for i, ref in enumerate(self._session_refs, 1):
                label = ref.get("label", "")
                url = ref["url"]
                ts = ref.get("timestamp", "")[:10]
                if label:
                    lines.append(f"  {i}. [{label}] {url}  ({ts})")
                else:
                    lines.append(f"  {i}. {url}  ({ts})")
            lines.append("")
            lines.append("  /ref remove <#> | /ref clear | /ref export")
            self._add_system_message("\n".join(lines))
            return

        # /ref clear
        if args == "clear":
            count = len(self._session_refs)
            self._session_refs.clear()
            self._save_refs()
            self._add_system_message(f"Cleared {count} reference(s)")
            return

        # /ref remove <N>
        if args.startswith("remove"):
            remove_parts = args.split()
            if len(remove_parts) < 2:
                self._add_system_message("Usage: /ref remove <number>")
                return
            try:
                idx = int(remove_parts[1]) - 1
                if 0 <= idx < len(self._session_refs):
                    removed = self._session_refs.pop(idx)
                    self._save_refs()
                    self._add_system_message(f"Removed: {removed['url']}")
                else:
                    self._add_system_message(
                        f"Invalid index. Range: 1-{len(self._session_refs)}"
                    )
            except (ValueError, IndexError):
                self._add_system_message("Usage: /ref remove <number>")
            return

        # /ref export
        if args == "export":
            self._export_refs()
            return

        # /ref <url-or-text> [label]  — add a new reference
        add_parts = args.split(None, 1)
        url = add_parts[0]
        label = add_parts[1] if len(add_parts) > 1 else ""

        self._session_refs.append(
            {
                "url": url,
                "label": label,
                "timestamp": datetime.now().isoformat(),
                "source": "manual",
            }
        )
        self._save_refs()

        msg = f"Saved reference: {url}"
        if label:
            msg += f" [{label}]"
        self._add_system_message(msg)

    def _export_refs(self) -> None:
        """Export saved references to a markdown file."""
        if not self._session_refs:
            self._add_system_message("No references to export")
            return

        sid = self._get_session_id() or "default"
        lines = [
            "# Session References",
            "",
            f"Session: `{sid[:12]}`",
            f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for i, ref in enumerate(self._session_refs, 1):
            label = ref.get("label") or ref["url"]
            url = ref["url"]
            ts = ref.get("timestamp", "")[:10]
            source = ref.get("source", "manual")
            lines.append(f"{i}. [{label}]({url}) -- {ts} ({source})")

        filepath = Path.home() / ".amplifier" / "refs-export.md"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text("\n".join(lines) + "\n")
        self._add_system_message(
            f"Exported {len(self._session_refs)} reference(s) to {filepath}"
        )

    # ── Message Pins ─────────────────────────────────────────────

    def _cmd_alias(self, text: str) -> None:
        """List, create, or remove custom command aliases."""
        text = text.strip()

        if not text:
            # List all aliases
            if not self._aliases:
                self._add_system_message(
                    "No aliases defined.\n"
                    "Usage: /alias <name> <command>\n"
                    "Example: /alias r /clear\n"
                    "         /alias review /diff all"
                )
                return
            lines = ["Aliases:"]
            for name, expansion in sorted(self._aliases.items()):
                lines.append(f"  /{name} \u2192 {expansion}")
            lines.append("")
            lines.append("Use /alias remove <name> to delete")
            self._add_system_message("\n".join(lines))
            return

        # Clear all aliases
        if text == "clear":
            self._aliases.clear()
            self._save_aliases()
            self._add_system_message("All aliases cleared")
            return

        # Remove alias
        if text.startswith("remove "):
            name = text[7:].strip().lstrip("/")
            if name in self._aliases:
                del self._aliases[name]
                self._save_aliases()
                self._add_system_message(f"Alias /{name} removed")
            else:
                self._add_system_message(f"No alias '/{name}' found")
            return

        # Create/update alias: supports both "name = expansion" and "name expansion"
        if "=" in text:
            name, expansion = text.split("=", 1)
            name = name.strip().lstrip("/")
            expansion = expansion.strip()
        else:
            parts = text.split(None, 1)
            if len(parts) < 2:
                self._add_system_message(
                    "Usage: /alias <name> <command>\n"
                    "Example: /alias r /clear\n"
                    "         /alias review /diff all\n"
                    "         /alias remove <name>\n"
                    "         /alias clear"
                )
                return
            name = parts[0].lstrip("/")
            expansion = parts[1]

        if not name or not expansion:
            self._add_system_message(
                "Both name and command required: /alias <name> <command>"
            )
            return

        # Don't allow overriding built-in commands
        if "/" + name in SLASH_COMMANDS:
            self._add_system_message(f"Cannot override built-in command /{name}")
            return

        # Ensure command aliases start with /
        if not expansion.startswith("/"):
            expansion = f"/{expansion}"

        self._aliases[name] = expansion
        self._save_aliases()
        self._add_system_message(f"Alias created: /{name} \u2192 {expansion}")

    # -- Snippet helpers ------------------------------------------------

    def _cmd_snippet(self, text: str) -> None:
        """List, save, search, tag, export, import, use, remove, clear, or edit snippets."""
        text = text.strip()

        # ── No arguments → list all snippets grouped by category ──
        if not text:
            if not self._snippets:
                self._add_system_message(
                    "No snippets saved.\n"
                    "Save: /snip save <name> [#category] <text>\n"
                    "Use:  /snip <name>"
                )
                return
            categorized: dict[str, list[str]] = defaultdict(list)
            uncategorized: list[str] = []
            for name, data in sorted(self._snippets.items()):
                cat = self._snippet_category(data)
                if cat:
                    categorized[cat].append(name)
                else:
                    uncategorized.append(name)
            lines: list[str] = ["Saved snippets:"]
            for cat in sorted(categorized):
                lines.append(f"\n  [{cat}]")
                for name in categorized[cat]:
                    content = self._snippet_content(self._snippets[name])
                    preview = content[:60].replace("\n", " ")
                    if len(content) > 60:
                        preview += "..."
                    lines.append(f"    {name}: {preview}")
            if uncategorized:
                if categorized:
                    lines.append("\n  [uncategorised]")
                for name in uncategorized:
                    content = self._snippet_content(self._snippets[name])
                    preview = content[:60].replace("\n", " ")
                    if len(content) > 60:
                        preview += "..."
                    lines.append(f"    {name}: {preview}")
            lines.append("")
            lines.append(
                "Insert: /snip <name>  |  Send: /snip use <name>"
                "  |  Save: /snip save <name> <text>"
            )
            self._add_system_message("\n".join(lines))
            return

        # ── Parse subcommand ──
        parts = text.split(maxsplit=2)
        subcmd = parts[0].lower()

        if subcmd == "clear":
            self._snippets.clear()
            self._save_snippets()
            self._add_system_message("All snippets cleared")

        elif subcmd == "save":
            self._cmd_snippet_save(parts)

        elif subcmd in ("use", "send"):
            self._cmd_snippet_use(parts)

        elif subcmd in ("remove", "delete"):
            if len(parts) < 2:
                self._add_system_message("Usage: /snippet delete <name>")
                return
            sname = parts[1]
            if sname in self._snippets:
                del self._snippets[sname]
                self._save_snippets()
                self._add_system_message(f"Snippet '{sname}' deleted")
            else:
                self._add_system_message(f"No snippet named '{sname}'")

        elif subcmd == "edit":
            if len(parts) < 2:
                self._add_system_message("Usage: /snippet edit <name>")
                return
            sname = parts[1]
            content = (
                self._snippet_content(self._snippets[sname])
                if sname in self._snippets
                else ""
            )
            self._edit_snippet_in_editor(sname, content)

        elif subcmd == "search":
            query = text[len("search") :].strip()
            if not query:
                self._add_system_message("Usage: /snippet search <query>")
                return
            self._cmd_snippet_search(query)

        elif subcmd == "cat":
            category = text[len("cat") :].strip()
            if not category:
                self._add_system_message("Usage: /snippet cat <category>")
                return
            self._cmd_snippet_cat(category)

        elif subcmd == "tag":
            self._cmd_snippet_tag(parts)

        elif subcmd == "export":
            self._cmd_snippet_export()

        elif subcmd == "import":
            path = text[len("import") :].strip()
            if not path:
                self._add_system_message("Usage: /snippet import <path>")
                return
            self._cmd_snippet_import(path)

        else:
            # Default: insert snippet into input (doesn't send)
            if subcmd in self._snippets:
                try:
                    inp = self.query_one("#chat-input", ChatInput)
                    inp.clear()
                    content = self._snippet_content(self._snippets[subcmd])
                    inp.insert(content)
                    # If snippet has {placeholder} markers, position the
                    # cursor at the first one so the user can replace it.
                    ph_match = re.search(r"\{(\w+)\}", content)
                    if ph_match:
                        # Find the (row, col) for the first placeholder
                        before = content[: ph_match.start()]
                        row = before.count("\n")
                        col = (
                            ph_match.start()
                            if row == 0
                            else ph_match.start() - before.rfind("\n") - 1
                        )
                        inp.cursor_location = (row, col)
                        placeholders = re.findall(r"\{(\w+)\}", content)
                        ph_note = ", ".join(f"{{{p}}}" for p in placeholders)
                        self._add_system_message(
                            f"Snippet '{subcmd}' inserted — "
                            f"fill in placeholders: {ph_note}"
                        )
                    else:
                        self._add_system_message(f"Snippet '{subcmd}' inserted")
                    inp.focus()
                except Exception:
                    logger.debug("Failed to insert snippet into input", exc_info=True)
            else:
                self._add_system_message(
                    f"No snippet '{subcmd}'.\n"
                    "Use /snip to list, /snip save <name> <text> to create."
                )

    # -- /snippet sub-command implementations ---------------------------

    def _cmd_snippet_save(self, parts: list[str]) -> None:
        """Save a snippet with an optional ``#category`` tag."""
        if len(parts) < 3:
            self._add_system_message("Usage: /snippet save <name> [#category] <text>")
            return
        sname = parts[1]
        if not re.match(r"^[a-zA-Z0-9_-]+$", sname):
            self._add_system_message(
                "Snippet names must be alphanumeric (hyphens and underscores allowed)"
            )
            return
        remaining = parts[2]
        # Parse optional #category prefix
        category = ""
        cat_match = re.match(r"#(\w+)\s+", remaining)
        if cat_match:
            category = cat_match.group(1)
            remaining = remaining[cat_match.end() :]
        today = datetime.now().strftime("%Y-%m-%d")
        self._snippets[sname] = {
            "content": remaining,
            "category": category,
            "created": today,
        }
        self._save_snippets()
        cat_note = f" [{category}]" if category else ""
        self._add_system_message(
            f"Snippet '{sname}'{cat_note} saved ({len(remaining)} chars)"
        )

    def _cmd_snippet_use(self, parts: list[str]) -> None:
        """Send a snippet as a chat message immediately."""
        if len(parts) < 2:
            self._add_system_message("Usage: /snippet use <name>")
            return
        sname = parts[1]
        if sname not in self._snippets:
            self._add_system_message(f"No snippet named '{sname}'")
            return
        if self.is_processing:
            self._add_system_message("Please wait for the current response to finish.")
            return
        if not self._amplifier_available:
            self._add_system_message("Amplifier is not available.")
            return
        if not self._amplifier_ready:
            self._add_system_message("Still loading Amplifier...")
            return
        message = self._snippet_content(self._snippets[sname])
        self._add_system_message(f"Sending snippet '{sname}'")
        self._clear_welcome()
        self._add_user_message(message)
        has_session = self.session_manager and getattr(
            self.session_manager, "session", None
        )
        self._start_processing("Starting session" if not has_session else "Thinking")
        self._send_message_worker(message)

    def _cmd_snippet_search(self, query: str) -> None:
        """Fuzzy search across snippet names, content, and categories."""
        query_lower = query.lower()
        matches: list[tuple[str, str, str]] = []
        for name, data in self._snippets.items():
            content = self._snippet_content(data)
            category = self._snippet_category(data)
            if (
                query_lower in name.lower()
                or query_lower in content.lower()
                or query_lower in category.lower()
            ):
                matches.append((name, content, category))

        if not matches:
            self._add_system_message(f"No snippets matching: {query}")
            return

        lines = [f"Snippets matching '{query}':"]
        for name, content, cat in sorted(matches):
            cat_str = f" [{cat}]" if cat else ""
            preview = content[:60].replace("\n", " ")
            if len(content) > 60:
                preview += "..."
            lines.append(f"  {name}{cat_str}: {preview}")
        lines.append(f"\n{len(matches)} match(es)")
        self._add_system_message("\n".join(lines))

    def _cmd_snippet_cat(self, category: str) -> None:
        """List all snippets belonging to *category*."""
        matches: list[tuple[str, str]] = []
        for name, data in self._snippets.items():
            cat = self._snippet_category(data)
            if cat.lower() == category.lower():
                matches.append((name, self._snippet_content(data)))

        if not matches:
            self._add_system_message(f"No snippets in category: {category}")
            return

        lines = [f"Category '{category}':"]
        for name, content in sorted(matches):
            preview = content[:60].replace("\n", " ")
            if len(content) > 60:
                preview += "..."
            lines.append(f"  {name}: {preview}")
        lines.append(f"\n{len(matches)} snippet(s)")
        self._add_system_message("\n".join(lines))

    def _cmd_snippet_tag(self, parts: list[str]) -> None:
        """Add or change the category tag on an existing snippet."""
        if len(parts) < 3:
            self._add_system_message("Usage: /snippet tag <name> <category>")
            return
        sname = parts[1]
        category = parts[2]
        if sname not in self._snippets:
            self._add_system_message(f"No snippet named '{sname}'")
            return
        data = self._snippets[sname]
        if isinstance(data, str):
            # Shouldn't happen after migration, but be safe
            data = {
                "content": data,
                "category": "",
                "created": datetime.now().strftime("%Y-%m-%d"),
            }
        data["category"] = category
        self._snippets[sname] = data
        self._save_snippets()
        self._add_system_message(f"Snippet '{sname}' tagged [{category}]")

    def _cmd_snippet_export(self) -> None:
        """Export all snippets as JSON to ``~/.amplifier/tui-snippets-export.json``."""
        if not self._snippets:
            self._add_system_message("No snippets to export")
            return
        export_path = Path.home() / ".amplifier" / "tui-snippets-export.json"
        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text(json.dumps(self._snippets, indent=2, sort_keys=True))
            self._add_system_message(
                f"Exported {len(self._snippets)} snippets to:\n{export_path}"
            )
        except OSError as e:
            logger.debug("Failed to export snippets to %s", export_path, exc_info=True)
            self._add_system_message(f"Export error: {e}")

    def _cmd_snippet_import(self, path: str) -> None:
        """Import snippets from a JSON file (additive — existing names are kept)."""
        abs_path = Path(path).expanduser().resolve()
        if not abs_path.exists():
            self._add_system_message(f"File not found: {path}")
            return
        try:
            raw = json.loads(abs_path.read_text())
            data = self._migrate_snippets(raw) if isinstance(raw, dict) else {}
            count = 0
            for name, value in data.items():
                if name not in self._snippets:
                    self._snippets[name] = value
                    count += 1
            self._save_snippets()
            skipped = len(data) - count
            self._add_system_message(
                f"Imported {count} new snippet(s)"
                + (f" ({skipped} already existed)" if skipped else "")
            )
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Failed to import snippets from %s", abs_path, exc_info=True)
            self._add_system_message(f"Import error: {e}")

    # -- Snippet editor -------------------------------------------------

    def _cmd_template(self, text: str) -> None:
        """List, save, use, remove, or clear prompt templates with {{variable}} placeholders."""
        text = text.strip()

        if not text:
            # List all templates
            if not self._templates:
                self._add_system_message(
                    "No templates saved.\n"
                    "Save: /template save <name> <text with {{vars}}>\n"
                    "Use:  /template <name>"
                )
                return
            lines = ["Saved templates:"]
            for name, tmpl in sorted(self._templates.items()):
                variables = re.findall(r"\{\{(\w+)\}\}", tmpl)
                vars_str = (
                    ", ".join(dict.fromkeys(variables)) if variables else "no variables"
                )
                preview = tmpl[:60].replace("\n", " ")
                if len(tmpl) > 60:
                    preview += "..."
                lines.append(f"  {name:15s} ({vars_str})")
                lines.append(f"                  {preview}")
            lines.append("")
            lines.append(f"{len(self._templates)} template(s)")
            lines.append("Insert: /template <name>  |  Use: /template use <name>")
            self._add_system_message("\n".join(lines))
            return

        parts = text.split(maxsplit=2)
        subcmd = parts[0].lower()

        if subcmd == "clear":
            self._templates.clear()
            self._save_templates()
            self._add_system_message("All templates cleared")

        elif subcmd == "save":
            if len(parts) < 3:
                self._add_system_message(
                    "Usage: /template save <name> <text with {{vars}}>"
                )
                return
            tname = parts[1]
            if not re.match(r"^[a-zA-Z0-9_-]+$", tname):
                self._add_system_message(
                    "Template names must be alphanumeric "
                    "(hyphens and underscores allowed)"
                )
                return
            content = parts[2]
            self._templates[tname] = content
            self._save_templates()
            variables = re.findall(r"\{\{(\w+)\}\}", content)
            unique_vars = list(dict.fromkeys(variables))
            self._add_system_message(
                f"Template '{tname}' saved ({len(content)} chars)"
                + (f" — variables: {', '.join(unique_vars)}" if unique_vars else "")
            )

        elif subcmd == "use":
            # Insert template into input (doesn't send)
            if len(parts) < 2:
                self._add_system_message("Usage: /template use <name>")
                return
            tname = parts[1]
            if tname not in self._templates:
                self._add_system_message(f"No template named '{tname}'")
                return
            tmpl = self._templates[tname]
            variables = re.findall(r"\{\{(\w+)\}\}", tmpl)
            unique_vars = list(dict.fromkeys(variables))
            try:
                inp = self.query_one("#chat-input", ChatInput)
                inp.clear()
                inp.insert(tmpl)
                inp.focus()
            except Exception:
                logger.debug("Failed to insert template into input", exc_info=True)
            if unique_vars:
                self._add_system_message(
                    f"Template '{tname}' inserted. "
                    f"Fill in placeholders: {', '.join(unique_vars)}"
                )
            else:
                self._add_system_message(f"Template '{tname}' inserted")

        elif subcmd == "remove":
            if len(parts) < 2:
                self._add_system_message("Usage: /template remove <name>")
                return
            tname = parts[1]
            if tname in self._templates:
                del self._templates[tname]
                self._save_templates()
                self._add_system_message(f"Template '{tname}' removed")
            else:
                self._add_system_message(f"No template named '{tname}'")

        else:
            # Default: treat subcmd as a template name (shortcut for /template use <name>)
            if subcmd in self._templates:
                self._cmd_template(f"use {subcmd}")
            else:
                self._add_system_message(
                    f"No template '{subcmd}'.\n"
                    "Usage:\n"
                    "  /template              List templates\n"
                    "  /template save <name> <text>  Save template with {{vars}}\n"
                    "  /template use <name>   Insert template into input\n"
                    "  /template remove <name>  Remove template\n"
                    "  /template clear        Remove all\n"
                    "  /template <name>       Quick insert"
                )

    def _cmd_draft(self, text: str) -> None:
        """Show, save, clear, or load the input draft."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "clear":
            self._clear_draft()
            self._clear_crash_draft()
            self._add_system_message("Draft cleared")
            return

        if arg == "save":
            self._save_draft()
            self._save_crash_draft()
            self._add_system_message("Draft saved")
            return

        if arg == "load":
            draft = self._load_crash_draft()
            if draft:
                input_widget = self.query_one("#chat-input", ChatInput)
                input_widget.clear()
                input_widget.insert(draft)
                self._add_system_message(f"Draft loaded ({len(draft)} chars)")
            else:
                self._add_system_message("No saved draft")
            return

        # Show current draft status
        lines: list[str] = []
        session_id = self._get_session_id()
        drafts = self._load_drafts()
        if session_id and session_id in drafts:
            draft = self._draft_text(drafts[session_id])
            preview = draft[:80].replace("\n", " ")
            suffix = "..." if len(draft) > 80 else ""
            lines.append(f"Session draft ({len(draft)} chars): {preview}{suffix}")

        crash = self._load_crash_draft()
        if crash:
            preview = crash[:80].replace("\n", " ")
            suffix = "..." if len(crash) > 80 else ""
            lines.append(
                f"Crash-recovery draft ({len(crash)} chars): {preview}{suffix}"
            )

        if not lines:
            # Check if there's unsaved input
            try:
                input_text = self.query_one("#chat-input", ChatInput).text.strip()
            except Exception:
                logger.debug("Failed to read input widget text", exc_info=True)
                input_text = ""
            if input_text:
                lines.append(
                    f"Unsaved input: {len(input_text)} chars (auto-saves in 5s)"
                )
            else:
                lines.append("No draft or unsaved input")

        self._add_system_message("\n".join(lines))

    def _cmd_drafts(self, text: str) -> None:
        """List all saved drafts across sessions, or clear current draft."""
        arg = (
            text.strip().split(None, 1)[1].strip().lower()
            if " " in text.strip()
            else ""
        )

        if arg == "clear":
            sid = self._get_session_id()
            if sid:
                self._clear_draft()
                self._clear_crash_draft()
                try:
                    input_widget = self.query_one("#chat-input", ChatInput)
                    input_widget.clear()
                except Exception:
                    logger.debug("Failed to clear input widget", exc_info=True)
                self._add_system_message("Draft cleared")
            else:
                self._add_system_message("No active session")
            return

        # List all drafts
        drafts = self._load_drafts()
        if not drafts:
            self._add_system_message("No saved drafts")
            return

        lines = ["Saved Drafts:", ""]
        sorted_drafts = sorted(
            drafts.items(),
            key=lambda kv: (
                kv[1].get("timestamp", "") if isinstance(kv[1], dict) else ""
            ),
            reverse=True,
        )
        for sid, entry in sorted_drafts:
            if isinstance(entry, dict):
                ts = entry.get("timestamp", "unknown")[:16]
                preview = entry.get("preview", "")[:60]
                text_len = len(entry.get("text", ""))
            else:
                ts = "unknown"
                preview = str(entry)[:60].replace("\n", " ")
                text_len = len(str(entry))
            suffix = "..." if len(preview) >= 60 else ""
            lines.append(
                f"  {sid[:12]}... [{ts}] ({text_len} chars): {preview}{suffix}"
            )

        self._add_system_message("\n".join(lines))

    def _cmd_pin_session(self, text: str) -> None:
        """Pin or unpin a session so it appears at the top of the sidebar."""
        sm = self.session_manager if hasattr(self, "session_manager") else None
        sid = getattr(sm, "session_id", None) if sm else None
        if not sid:
            self._add_system_message("No active session to pin.")
            return

        # Toggle pin state
        if sid in self._pinned_sessions:
            self._pinned_sessions.discard(sid)
            self._save_pinned_sessions()
            verb = "unpinned"
        else:
            self._pinned_sessions.add(sid)
            self._save_pinned_sessions()
            verb = "pinned"

        # Refresh sidebar if it has data loaded
        if self._session_list_data:
            self._populate_session_list(self._session_list_data)

        short = sid[:8]
        if verb == "pinned":
            self._add_system_message(
                f"Session {short} pinned (will appear at top of sidebar)."
            )
        else:
            self._add_system_message(f"Session {short} unpinned.")

    # ── Message Pin Commands ─────────────────────────────────────

    def _cmd_pin_msg(self, text: str) -> None:
        """Pin a message for quick recall.

        /pin              – pin last assistant message
        /pin <N>          – pin message number N (1-based)
        /pin list         – list all pinned messages
        /pin clear        – clear all pins
        /pin remove <N>   – remove pin number N
        /pin <label>      – pin last assistant message with a label
        """
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg.lower() == "clear":
            self._remove_all_pin_classes()
            self._message_pins = []
            self._save_message_pins()
            self._add_system_message("All message pins cleared.")
            self._update_pinned_panel()
            return

        if arg.lower() == "list":
            self._cmd_pins(text)
            return

        if not arg:
            # Pin last assistant message
            for i in range(len(self._search_messages) - 1, -1, -1):
                role, content, _widget = self._search_messages[i]
                if role == "assistant":
                    self._add_message_pin(i, content)
                    return
            self._add_system_message("No assistant message to pin.")
            return

        # /pin remove N
        sub_parts = arg.split(None, 1)
        if sub_parts[0].lower() == "remove":
            if len(sub_parts) > 1 and sub_parts[1].strip().isdigit():
                self._remove_pin(int(sub_parts[1].strip()))
                return
            self._add_system_message("Usage: /pin remove <pin-number>")
            return

        if arg.isdigit():
            idx = int(arg) - 1  # 1-based for user
            if 0 <= idx < len(self._search_messages):
                _role, content, _widget = self._search_messages[idx]
                self._add_message_pin(idx, content)
            else:
                total = len(self._search_messages)
                self._add_system_message(f"Message {arg} not found (valid: 1-{total})")
            return

        # Treat remaining text as a label for the last assistant message
        for i in range(len(self._search_messages) - 1, -1, -1):
            role, content, _widget = self._search_messages[i]
            if role == "assistant":
                self._add_message_pin(i, content, label=arg)
                return
        self._add_system_message("No assistant message to pin.")

    def _cmd_pins(self, text: str) -> None:
        """List all pinned messages."""
        if not self._message_pins:
            self._add_system_message("No pinned messages. Use /pin to pin one.")
            return

        lines = ["\U0001f4cc Pinned messages:"]
        total = len(self._search_messages)
        for i, pin in enumerate(self._message_pins, 1):
            idx = pin["index"]
            if idx < total:
                role = self._search_messages[idx][0]
            else:
                role = pin.get("role", "?")
            role_label = {"user": "You", "assistant": "AI", "system": "Sys"}.get(
                role, role
            )
            pin_label = pin.get("label", "")
            label_str = f" [{pin_label}]" if pin_label else ""
            lines.append(
                f"  #{i} [{role_label} msg {idx + 1}]{label_str}: {pin['preview']}"
            )
        lines.append("")
        lines.append(
            "Use /pin remove <N> or /unpin <N> to remove, /pin clear to clear all"
        )
        self._add_system_message("\n".join(lines))

    def _cmd_unpin(self, text: str) -> None:
        """Remove a message pin by its pin number."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg or not arg.isdigit():
            self._add_system_message("Usage: /unpin <pin-number>")
            return

        self._remove_pin(int(arg))

    # ── Session Notes Commands ─────────────────────────────────────────

    def _cmd_note(self, args: str) -> None:
        """Add or manage session notes.

        /note <text>    – add a note
        /note list      – show all notes
        /note clear     – remove all notes
        /notes          – alias for /note list
        """
        text = args.strip()

        if not text:
            self._add_system_message(
                "Usage:\n"
                "  /note <text>    Add a note\n"
                "  /note list      Show all notes\n"
                "  /note clear     Remove all notes\n"
                "  /notes          Alias for /note list"
            )
            return

        if text.lower() == "list":
            self._show_notes()
            return

        if text.lower() == "clear":
            self._session_notes.clear()
            self._save_notes()
            self._add_system_message("All notes cleared.")
            return

        # Add a note
        note = {
            "text": text,
            "created_at": datetime.now().isoformat(),
            "position": len(self._search_messages),
        }
        self._session_notes.append(note)
        self._save_notes()

        # Display the note in chat with special styling
        self._add_note_message(text)

    def _cmd_bookmark(self, text: str) -> None:
        """Bookmark command with subcommands.

        /bookmark          — bookmark last assistant message
        /bookmark list     — list all bookmarks
        /bookmark N        — toggle bookmark on Nth message from bottom
        /bookmark jump N   — scroll to bookmark N
        /bookmark clear    — remove all bookmarks
        /bookmark remove N — remove bookmark N
        /bookmark <label>  — bookmark last message with a label
        """
        parts = text.strip().split(None, 1)
        args = parts[1].strip() if len(parts) > 1 else ""

        if not args:
            self._bookmark_last_message()
            return

        arg_parts = args.split(None, 1)
        subcmd = arg_parts[0].lower()

        if subcmd == "list":
            self._list_bookmarks()
        elif subcmd == "clear":
            self._clear_bookmarks()
        elif subcmd == "jump" and len(arg_parts) > 1 and arg_parts[1].strip().isdigit():
            self._jump_to_bookmark(int(arg_parts[1].strip()))
        elif (
            subcmd == "remove" and len(arg_parts) > 1 and arg_parts[1].strip().isdigit()
        ):
            self._remove_bookmark(int(arg_parts[1].strip()))
        elif subcmd.isdigit():
            self._bookmark_nth_message(int(subcmd))
        else:
            # Treat remaining text as a label for the last message
            self._bookmark_last_message(label=args)

    def _cmd_bookmarks(self, text: str) -> None:
        """List bookmarks or jump to a specific bookmark by number."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg.isdigit():
            self._jump_to_bookmark(int(arg))
            return

        self._list_bookmarks()

    def _find_session_dir(self, session_id: str) -> Path | None:
        """Find the directory for a session by searching all projects."""
        sessions_dir = Path.home() / ".amplifier" / "projects"
        if not sessions_dir.exists():
            return None

        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / "sessions" / session_id
            if candidate.is_dir():
                return candidate

        return None

    # ── Bookmark helpers ──────────────────────────────────────────
