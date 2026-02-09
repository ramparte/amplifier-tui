"""Snippet persistence store."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ._base import JsonStore

DEFAULT_SNIPPETS: dict[str, dict[str, str]] = {
    "review": {
        "content": "Review {file_or_code} for bugs, performance issues, and best practices:",
        "category": "prompts",
    },
    "explain": {
        "content": "Explain {file_or_code} in detail:",
        "category": "prompts",
    },
    "tests": {
        "content": "Write comprehensive tests for {file_or_code}:",
        "category": "prompts",
    },
    "fix": {
        "content": "Fix the bug in {file_or_code}:",
        "category": "prompts",
    },
    "refactor": {
        "content": "Refactor {file_or_code} to be cleaner and more maintainable:",
        "category": "prompts",
    },
    "doc": {
        "content": "Write documentation for {file_or_code}:",
        "category": "prompts",
    },
    "debug": {
        "content": "Debug this error:",
        "category": "prompts",
    },
    "plan": {
        "content": "Create a detailed plan for implementing {feature_or_task}:",
        "category": "prompts",
    },
    "optimize": {
        "content": "Optimize {file_or_code} for better performance:",
        "category": "prompts",
    },
    "security": {
        "content": "Review {file_or_code} for security vulnerabilities:",
        "category": "prompts",
    },
}


class SnippetStore(JsonStore):
    """Reusable prompt snippets (``{name: {content, category, created}}``)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load(self) -> dict[str, dict[str, str]]:
        """Load snippets, migrating old format and seeding defaults on first run."""
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                migrated = self._migrate(raw)
                if migrated is not raw:
                    # Re-persist in the new format
                    try:
                        self.save_raw(migrated, sort_keys=True)
                    except Exception:
                        pass
                return migrated
        except Exception:
            pass
        # First run: seed with default snippets
        defaults = dict(DEFAULT_SNIPPETS)
        try:
            self.save_raw(defaults, sort_keys=True)
        except Exception:
            pass
        return defaults

    def save(self, snippets: dict[str, dict[str, str]]) -> None:
        """Persist snippets to disk."""
        self.save_raw(snippets, sort_keys=True)

    # -- migration ------------------------------------------------------------

    @staticmethod
    def _migrate(
        data: dict[str, str | dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """Migrate old ``{name: text}`` format to ``{name: {content, category, created}}``."""
        needs_migration = any(isinstance(v, str) for v in data.values())
        if not needs_migration:
            return data  # type: ignore[return-value]
        migrated: dict[str, dict[str, str]] = {}
        today = datetime.now().strftime("%Y-%m-%d")
        for name, value in data.items():
            if isinstance(value, str):
                migrated[name] = {"content": value, "category": "", "created": today}
            else:
                migrated[name] = value  # type: ignore[assignment]
        return migrated
