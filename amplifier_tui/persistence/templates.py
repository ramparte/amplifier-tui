"""Template persistence store."""

from __future__ import annotations

from pathlib import Path

from ._base import JsonStore

DEFAULT_TEMPLATES: dict[str, str] = {
    "review": (
        "Review this code for bugs, performance issues, and best practices:\n\n"
        "```{{language}}\n{{code}}\n```"
    ),
    "explain": (
        "Explain this {{language}} code in detail, covering what it does and why:\n\n"
        "```{{language}}\n{{code}}\n```"
    ),
    "refactor": (
        "Refactor this {{language}} code to improve {{aspect}}:\n\n"
        "```{{language}}\n{{code}}\n```"
    ),
    "test": (
        "Write comprehensive tests for this {{language}} function:\n\n"
        "```{{language}}\n{{code}}\n```"
    ),
    "debug": (
        "Help me debug this {{language}} code. The error is: {{error}}\n\n"
        "```{{language}}\n{{code}}\n```"
    ),
    "commit": "Write a commit message for these changes:\n\n{{diff}}",
}


class TemplateStore(JsonStore):
    """Prompt templates with ``{{variable}}`` placeholders."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def load(self) -> dict[str, str]:
        """Load templates, seeding defaults on first run."""
        try:
            if self.path.exists():
                return self.load_raw()  # type: ignore[return-value]
        except Exception:
            pass
        # First run: seed with default templates
        defaults = dict(DEFAULT_TEMPLATES)
        try:
            self.save_raw(defaults, sort_keys=True)
        except Exception:
            pass
        return defaults

    def save(self, templates: dict[str, str]) -> None:
        """Persist templates to disk."""
        self.save_raw(templates, sort_keys=True)
