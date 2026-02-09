"""Shared test fixtures for amplifier-tui test suite."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for file-based tests."""
    return tmp_path


@pytest.fixture
def sample_messages():
    """Sample chat message tuples for export tests.

    Each entry is ``(role, content, widget_or_none)`` matching the
    ``MessageTuple`` type alias used by the export formatters.
    """
    return [
        ("user", "Hello", None),
        ("assistant", "Hi there! How can I help?", None),
        ("user", "Tell me about Python", None),
        ("assistant", "Python is a programming language...", None),
    ]


@pytest.fixture
def sample_metadata():
    """Sample metadata dict matching ``get_export_metadata`` output."""
    return {
        "date": "2025-01-15 10:30",
        "session_id": "abc123def456",
        "session_title": "Test Session",
        "model": "claude-sonnet-4-20250514",
        "message_count": "4",
        "token_estimate": "~100",
    }
