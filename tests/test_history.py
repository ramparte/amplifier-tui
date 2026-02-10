"""Tests for amplifier_tui.history -- TUI-013.

Covers PromptHistory: add/dedup, Up/Down browsing, search,
persistence, slash-command filtering, and MAX_ENTRIES cap.
All file I/O uses tmp_path via monkeypatching HISTORY_FILE.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_tui.history import PromptHistory


@pytest.fixture()
def hist(tmp_path: Path):
    """PromptHistory with an isolated history file."""
    path = tmp_path / "history.txt"
    PromptHistory.HISTORY_FILE = path  # type: ignore[assignment]
    return PromptHistory()


# -- Basic add & entries ------------------------------------------------------


class TestAdd:
    """add() records prompts and persists them."""

    def test_add_single(self, hist: PromptHistory):
        hist.add("hello world")
        assert hist.entry_count == 1
        assert hist.entries == ["hello world"]

    def test_deduplicates(self, hist: PromptHistory):
        hist.add("alpha")
        hist.add("beta")
        hist.add("alpha")  # duplicate
        assert hist.entries == ["beta", "alpha"]

    def test_skips_slash_commands(self, hist: PromptHistory):
        hist.add("/help")
        assert hist.entry_count == 0

    def test_force_allows_slash(self, hist: PromptHistory):
        hist.add("/run git status", force=True)
        assert hist.entry_count == 1

    def test_skips_empty(self, hist: PromptHistory):
        hist.add("")
        hist.add("   ")
        assert hist.entry_count == 0

    def test_flattens_multiline(self, hist: PromptHistory):
        hist.add("line one\nline two\n  line three")
        assert hist.entries == ["line one line two line three"]

    def test_max_entries_cap(
        self, hist: PromptHistory, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(PromptHistory, "MAX_ENTRIES", 5)
        for i in range(10):
            hist.add(f"entry-{i}")
        assert hist.entry_count == 5
        assert hist.entries[0] == "entry-5"
        assert hist.entries[-1] == "entry-9"


# -- Persistence --------------------------------------------------------------


class TestPersistence:
    """History survives across PromptHistory instances."""

    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "history.txt"
        PromptHistory.HISTORY_FILE = path  # type: ignore[assignment]
        h1 = PromptHistory()
        h1.add("first")
        h1.add("second")

        h2 = PromptHistory()
        assert h2.entries == ["first", "second"]

    def test_missing_file_gives_empty(self, tmp_path: Path):
        PromptHistory.HISTORY_FILE = tmp_path / "nope.txt"  # type: ignore[assignment]
        h = PromptHistory()
        assert h.entry_count == 0

    def test_blank_lines_filtered(self, tmp_path: Path):
        path = tmp_path / "history.txt"
        path.write_text("\n\n  \nactual entry\n  \n")
        PromptHistory.HISTORY_FILE = path  # type: ignore[assignment]
        h = PromptHistory()
        assert h.entries == ["actual entry"]


# -- Browsing (Up/Down) ------------------------------------------------------


class TestBrowsing:
    """Up/Down arrow history browsing."""

    def test_not_browsing_initially(self, hist: PromptHistory):
        assert hist.is_browsing is False

    def test_start_browse(self, hist: PromptHistory):
        hist.add("a")
        hist.start_browse("current")
        assert hist.is_browsing is True

    def test_previous_returns_entries(self, hist: PromptHistory):
        hist.add("first")
        hist.add("second")
        hist.start_browse("")
        assert hist.previous() == "second"
        assert hist.previous() == "first"

    def test_previous_at_oldest_returns_none(self, hist: PromptHistory):
        hist.add("only")
        hist.start_browse("")
        hist.previous()  # "only"
        assert hist.previous() is None

    def test_previous_empty_history(self, hist: PromptHistory):
        hist.start_browse("")
        assert hist.previous() is None

    def test_next_returns_to_draft(self, hist: PromptHistory):
        hist.add("old")
        hist.start_browse("my draft")
        hist.previous()  # "old"
        result = hist.next()
        assert result == "my draft"
        assert hist.is_browsing is False

    def test_next_without_browsing(self, hist: PromptHistory):
        assert hist.next() is None

    def test_full_browse_cycle(self, hist: PromptHistory):
        hist.add("a")
        hist.add("b")
        hist.add("c")
        hist.start_browse("draft")

        assert hist.previous() == "c"
        assert hist.previous() == "b"
        assert hist.previous() == "a"
        assert hist.previous() is None  # at oldest

        assert hist.next() == "b"
        assert hist.next() == "c"
        assert hist.next() == "draft"  # back to draft
        assert hist.is_browsing is False

    def test_add_resets_browsing(self, hist: PromptHistory):
        hist.add("old")
        hist.start_browse("")
        hist.previous()
        hist.add("new")
        assert hist.is_browsing is False


# -- Search -------------------------------------------------------------------


class TestSearch:
    """Substring search returns matches most-recent-first."""

    def test_search_finds_matches(self, hist: PromptHistory):
        hist.add("hello world")
        hist.add("goodbye world")
        hist.add("hello again")
        results = hist.search("hello")
        assert results == ["hello again", "hello world"]

    def test_search_case_insensitive(self, hist: PromptHistory):
        hist.add("Hello World")
        results = hist.search("hello")
        assert len(results) == 1

    def test_search_empty_query_returns_recent(self, hist: PromptHistory):
        for i in range(25):
            hist.add(f"entry-{i}")
        results = hist.search("")
        assert len(results) == 20  # capped at 20
        assert results[0] == "entry-24"  # most recent first

    def test_search_no_matches(self, hist: PromptHistory):
        hist.add("hello")
        assert hist.search("xyz") == []


class TestReverseSearchIndices:
    """reverse_search_indices returns matching indices."""

    def test_returns_indices(self, hist: PromptHistory):
        hist.add("alpha")
        hist.add("beta")
        hist.add("alpha two")
        indices = hist.reverse_search_indices("alpha")
        assert indices == [2, 0]

    def test_empty_query_returns_empty(self, hist: PromptHistory):
        hist.add("something")
        assert hist.reverse_search_indices("") == []


# -- get_entry ----------------------------------------------------------------


class TestGetEntry:
    """get_entry returns entry by index or None."""

    def test_valid_index(self, hist: PromptHistory):
        hist.add("zero")
        hist.add("one")
        assert hist.get_entry(0) == "zero"
        assert hist.get_entry(1) == "one"

    def test_negative_index(self, hist: PromptHistory):
        hist.add("something")
        assert hist.get_entry(-1) is None

    def test_out_of_range(self, hist: PromptHistory):
        assert hist.get_entry(999) is None


# -- clear & reset_browse ----------------------------------------------------


class TestClearAndReset:
    """clear() wipes all entries; reset_browse() stops browsing."""

    def test_clear(self, hist: PromptHistory):
        hist.add("a")
        hist.add("b")
        hist.clear()
        assert hist.entry_count == 0
        assert hist.is_browsing is False

    def test_clear_persists(self, tmp_path: Path):
        path = tmp_path / "history.txt"
        PromptHistory.HISTORY_FILE = path  # type: ignore[assignment]
        h1 = PromptHistory()
        h1.add("will be cleared")
        h1.clear()

        h2 = PromptHistory()
        assert h2.entry_count == 0

    def test_reset_browse(self, hist: PromptHistory):
        hist.add("x")
        hist.start_browse("")
        assert hist.is_browsing is True
        hist.reset_browse()
        assert hist.is_browsing is False
