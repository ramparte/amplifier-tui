"""Tests for persistence stores.

Each store is tested for:
  1. load() on non-existent file returns correct default
  2. save() then load() round-trips correctly
  3. load() on corrupt JSON returns default (graceful degradation)
  4. Store-specific features
"""

from __future__ import annotations

import json

import pytest

from amplifier_tui.persistence import (
    AliasStore,
    BookmarkStore,
    DraftStore,
    MessagePinStore,
    NoteStore,
    PinnedSessionStore,
    RefStore,
    SessionNameStore,
    SnippetStore,
    TagStore,
    TemplateStore,
)
from amplifier_tui.persistence._base import JsonStore


# ---------------------------------------------------------------------------
# Base JsonStore
# ---------------------------------------------------------------------------


class TestJsonStore:
    def test_load_raw_nonexistent(self, tmp_path):
        store = JsonStore(tmp_path / "nope.json")
        assert store.load_raw() == {}

    def test_save_and_load_raw_dict(self, tmp_path):
        path = tmp_path / "data.json"
        store = JsonStore(path)
        store.save_raw({"key": "value"})
        assert store.load_raw() == {"key": "value"}

    def test_save_and_load_raw_list(self, tmp_path):
        path = tmp_path / "data.json"
        store = JsonStore(path)
        store.save_raw([1, 2, 3])
        assert store.load_raw() == [1, 2, 3]

    def test_load_raw_corrupt_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json{{{")
        store = JsonStore(path)
        assert store.load_raw() == {}

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "store.json"
        store = JsonStore(path)
        store.save_raw({"a": 1})
        assert path.exists()
        assert store.load_raw() == {"a": 1}

    def test_default_returns_dict(self):
        store = JsonStore.__new__(JsonStore)
        assert store._default() == {}


# ---------------------------------------------------------------------------
# AliasStore
# ---------------------------------------------------------------------------


class TestAliasStore:
    def test_load_empty(self, tmp_path):
        store = AliasStore(tmp_path / "aliases.json")
        data = store.load()
        assert isinstance(data, dict)
        assert data == {}

    def test_round_trip(self, tmp_path):
        store = AliasStore(tmp_path / "aliases.json")
        aliases = {"ll": "/ls -la", "gs": "/git status"}
        store.save(aliases)
        loaded = store.load()
        assert loaded == aliases

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "aliases.json"
        path.write_text("not valid json{{{")
        store = AliasStore(path)
        data = store.load()
        assert isinstance(data, dict)

    def test_save_sorts_keys(self, tmp_path):
        path = tmp_path / "aliases.json"
        store = AliasStore(path)
        store.save({"zzz": "last", "aaa": "first"})
        raw = json.loads(path.read_text())
        keys = list(raw.keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# SnippetStore
# ---------------------------------------------------------------------------


class TestSnippetStore:
    def test_load_seeds_defaults_on_first_run(self, tmp_path):
        store = SnippetStore(tmp_path / "snippets.json")
        data = store.load()
        assert isinstance(data, dict)
        assert len(data) > 0
        # Should have known defaults
        assert "review" in data
        assert "explain" in data
        assert "content" in data["review"]

    def test_round_trip(self, tmp_path):
        store = SnippetStore(tmp_path / "snippets.json")
        snippets = {
            "custom": {"content": "Do something", "category": "test"},
        }
        store.save(snippets)
        loaded = store.load()
        assert loaded == snippets

    def test_load_corrupt_returns_defaults(self, tmp_path):
        path = tmp_path / "snippets.json"
        path.write_text("corrupt!!!{")
        store = SnippetStore(path)
        data = store.load()
        assert isinstance(data, dict)
        # Should seed defaults since file was unreadable
        assert "review" in data

    def test_migrate_old_format(self):
        """Old format was {name: text_string}; new is {name: {content, ...}}."""
        old = {"mysnip": "some text"}
        migrated = SnippetStore._migrate(old)
        assert isinstance(migrated["mysnip"], dict)
        assert migrated["mysnip"]["content"] == "some text"
        assert "created" in migrated["mysnip"]

    def test_migrate_noop_for_new_format(self):
        new_fmt = {"mysnip": {"content": "text", "category": "test"}}
        result = SnippetStore._migrate(new_fmt)
        # Should return the same object (identity check)
        assert result is new_fmt


# ---------------------------------------------------------------------------
# TemplateStore
# ---------------------------------------------------------------------------


class TestTemplateStore:
    def test_load_seeds_defaults_on_first_run(self, tmp_path):
        store = TemplateStore(tmp_path / "templates.json")
        data = store.load()
        assert isinstance(data, dict)
        assert "review" in data
        assert "debug" in data
        assert "{{" in data["review"]  # Has placeholder syntax

    def test_round_trip(self, tmp_path):
        store = TemplateStore(tmp_path / "templates.json")
        templates = {"greet": "Hello {{name}}!"}
        store.save(templates)
        loaded = store.load()
        assert loaded == templates

    def test_load_corrupt_returns_empty_dict(self, tmp_path):
        """Corrupt JSON: load_raw() handles the decode error and returns {}.

        Since the file *exists*, TemplateStore.load() enters the
        ``if self.path.exists()`` branch, gets ``{}`` from load_raw(),
        and returns it directly (no default seeding).
        """
        path = tmp_path / "templates.json"
        path.write_text("not json!!!")
        store = TemplateStore(path)
        data = store.load()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# BookmarkStore
# ---------------------------------------------------------------------------


class TestBookmarkStore:
    def test_load_all_empty(self, tmp_path):
        store = BookmarkStore(tmp_path / "bookmarks.json")
        assert store.load_all() == {}

    def test_add_and_load(self, tmp_path):
        store = BookmarkStore(tmp_path / "bookmarks.json")
        bm = {"index": 3, "label": "important"}
        store.add("sess1", bm)
        result = store.for_session("sess1")
        assert len(result) == 1
        assert result[0] == bm

    def test_for_session_none(self, tmp_path):
        store = BookmarkStore(tmp_path / "bookmarks.json")
        assert store.for_session(None) == []

    def test_for_session_missing(self, tmp_path):
        store = BookmarkStore(tmp_path / "bookmarks.json")
        assert store.for_session("nonexistent") == []

    def test_save_for_session(self, tmp_path):
        store = BookmarkStore(tmp_path / "bookmarks.json")
        store.add("sess1", {"idx": 1})
        store.add("sess1", {"idx": 2})
        # Replace with a single bookmark
        store.save_for_session("sess1", [{"idx": 99}])
        result = store.for_session("sess1")
        assert len(result) == 1
        assert result[0]["idx"] == 99

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "bookmarks.json"
        path.write_text("{bad json")
        store = BookmarkStore(path)
        assert store.load_all() == {}

    def test_multiple_sessions(self, tmp_path):
        store = BookmarkStore(tmp_path / "bookmarks.json")
        store.add("sess1", {"label": "a"})
        store.add("sess2", {"label": "b"})
        assert len(store.for_session("sess1")) == 1
        assert len(store.for_session("sess2")) == 1


# ---------------------------------------------------------------------------
# NoteStore
# ---------------------------------------------------------------------------


class TestNoteStore:
    def test_load_empty(self, tmp_path):
        store = NoteStore(tmp_path / "notes.json")
        assert store.load("sess1") == []

    def test_round_trip(self, tmp_path):
        store = NoteStore(tmp_path / "notes.json")
        notes = [{"text": "Remember this", "ts": "2025-01-01"}]
        store.save("sess1", notes)
        loaded = store.load("sess1")
        assert loaded == notes

    def test_load_defaults_to_default_session(self, tmp_path):
        store = NoteStore(tmp_path / "notes.json")
        notes = [{"text": "hello"}]
        store.save("", notes)  # empty string -> "default"
        loaded = store.load("")
        assert loaded == notes

    def test_save_empty_removes_session(self, tmp_path):
        store = NoteStore(tmp_path / "notes.json")
        store.save("sess1", [{"text": "note"}])
        store.save("sess1", [])  # empty list removes the key
        assert store.load("sess1") == []

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "notes.json"
        path.write_text("corrupt!!")
        store = NoteStore(path)
        assert store.load("sess1") == []

    def test_prune_to_50_sessions(self, tmp_path):
        store = NoteStore(tmp_path / "notes.json")
        # Add 55 sessions
        for i in range(55):
            store.save(f"sess{i:03d}", [{"text": f"note{i}"}])
        # The file should have at most 50 sessions
        raw = json.loads(store.path.read_text())
        assert len(raw) <= 50


# ---------------------------------------------------------------------------
# MessagePinStore
# ---------------------------------------------------------------------------


class TestMessagePinStore:
    def test_load_empty(self, tmp_path):
        store = MessagePinStore(tmp_path / "pins.json")
        assert store.load("sess1") == []

    def test_round_trip(self, tmp_path):
        store = MessagePinStore(tmp_path / "pins.json")
        pins = [{"index": 5, "content": "pinned msg"}]
        store.save("sess1", pins)
        loaded = store.load("sess1")
        assert loaded == pins

    def test_load_defaults_to_default(self, tmp_path):
        store = MessagePinStore(tmp_path / "pins.json")
        pins = [{"index": 1}]
        store.save("", pins)
        assert store.load("") == pins

    def test_save_empty_removes(self, tmp_path):
        store = MessagePinStore(tmp_path / "pins.json")
        store.save("sess1", [{"index": 1}])
        store.save("sess1", [])
        assert store.load("sess1") == []

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "pins.json"
        path.write_text("{bad")
        store = MessagePinStore(path)
        assert store.load("sess1") == []

    def test_prune_to_50_sessions(self, tmp_path):
        store = MessagePinStore(tmp_path / "pins.json")
        for i in range(55):
            store.save(f"sess{i:03d}", [{"index": i}])
        raw = json.loads(store.path.read_text())
        assert len(raw) <= 50


# ---------------------------------------------------------------------------
# PinnedSessionStore
# ---------------------------------------------------------------------------


class TestPinnedSessionStore:
    def test_load_empty(self, tmp_path):
        store = PinnedSessionStore(tmp_path / "pinned.json")
        result = store.load()
        assert isinstance(result, set)
        assert len(result) == 0

    def test_round_trip(self, tmp_path):
        store = PinnedSessionStore(tmp_path / "pinned.json")
        ids = {"sess1", "sess2", "sess3"}
        store.save(ids)
        loaded = store.load()
        assert loaded == ids

    def test_saved_as_sorted_list(self, tmp_path):
        path = tmp_path / "pinned.json"
        store = PinnedSessionStore(path)
        store.save({"zzz", "aaa", "mmm"})
        raw = json.loads(path.read_text())
        assert isinstance(raw, list)
        assert raw == sorted(raw)

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "pinned.json"
        path.write_text("not json!!!")
        store = PinnedSessionStore(path)
        result = store.load()
        assert isinstance(result, set)
        assert len(result) == 0

    def test_default_returns_list(self, tmp_path):
        store = PinnedSessionStore(tmp_path / "pinned.json")
        assert store._default() == []


# ---------------------------------------------------------------------------
# RefStore
# ---------------------------------------------------------------------------


class TestRefStore:
    def test_load_all_empty(self, tmp_path):
        store = RefStore(tmp_path / "refs.json")
        assert store.load_all() == {}

    def test_save_and_for_session(self, tmp_path):
        store = RefStore(tmp_path / "refs.json")
        refs = [{"url": "https://example.com", "title": "Example"}]
        store.save("sess1", refs)
        loaded = store.for_session("sess1")
        assert loaded == refs

    def test_for_session_none(self, tmp_path):
        store = RefStore(tmp_path / "refs.json")
        assert store.for_session(None) == []

    def test_for_session_missing(self, tmp_path):
        store = RefStore(tmp_path / "refs.json")
        assert store.for_session("nonexistent") == []

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "refs.json"
        path.write_text("corrupt!")
        store = RefStore(path)
        assert store.load_all() == {}


# ---------------------------------------------------------------------------
# DraftStore
# ---------------------------------------------------------------------------


class TestDraftStore:
    def _make_store(self, tmp_path):
        return DraftStore(
            tmp_path / "drafts.json",
            tmp_path / "crash_draft.txt",
        )

    def test_load_empty(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.load() == {}

    def test_save_and_load(self, tmp_path):
        store = self._make_store(tmp_path)
        drafts = {
            "sess1": {"text": "hello", "timestamp": "2025-01-01", "preview": "hel..."},
        }
        store.save_all(drafts)
        loaded = store.load()
        assert loaded == drafts

    def test_remove(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_all({"sess1": {"text": "a"}, "sess2": {"text": "b"}})
        store.remove("sess1")
        loaded = store.load()
        assert "sess1" not in loaded
        assert "sess2" in loaded

    def test_remove_nonexistent_is_safe(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_all({"sess1": {"text": "a"}})
        store.remove("nonexistent")  # Should not crash
        assert store.load() == {"sess1": {"text": "a"}}

    def test_crash_save_and_load(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_crash("unsaved work here")
        recovered = store.load_crash()
        assert recovered == "unsaved work here"

    def test_crash_load_nonexistent(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.load_crash() is None

    def test_crash_save_empty_deletes_file(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_crash("something")
        assert store.crash_path.exists()
        store.save_crash("")  # empty -> delete
        assert not store.crash_path.exists()

    def test_crash_clear(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_crash("important")
        store.clear_crash()
        assert store.load_crash() is None
        assert not store.crash_path.exists()

    def test_load_corrupt(self, tmp_path):
        store = self._make_store(tmp_path)
        store.path.write_text("{bad json")
        assert store.load() == {}


# ---------------------------------------------------------------------------
# SessionNameStore
# ---------------------------------------------------------------------------


class TestSessionNameStore:
    def _make_store(self, tmp_path):
        return SessionNameStore(
            tmp_path / "names.json",
            tmp_path / "titles.json",
        )

    # -- names --

    def test_load_names_empty(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.load_names() == {}

    def test_save_and_load_name(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_name("sess1", "My Session")
        names = store.load_names()
        assert names["sess1"] == "My Session"

    def test_remove_name(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_name("sess1", "Name")
        store.remove_name("sess1")
        names = store.load_names()
        assert "sess1" not in names

    def test_remove_name_nonexistent_is_safe(self, tmp_path):
        store = self._make_store(tmp_path)
        store.remove_name("nonexistent")  # Should not crash

    # -- titles --

    def test_load_titles_empty(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.load_titles() == {}

    def test_save_and_load_title(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_title("sess1", "Auto-generated Title")
        titles = store.load_titles()
        assert titles["sess1"] == "Auto-generated Title"

    def test_title_for_existing(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_title("sess1", "My Title")
        assert store.title_for("sess1") == "My Title"

    def test_title_for_missing(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.title_for("nonexistent") == ""

    def test_save_title_none_removes(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_title("sess1", "Title")
        store.save_title("sess1", None)
        assert store.title_for("sess1") == ""

    def test_titles_pruned_to_200(self, tmp_path):
        store = self._make_store(tmp_path)
        for i in range(210):
            store.save_title(f"sess{i:04d}", f"Title {i}")
        titles = store.load_titles()
        assert len(titles) <= 200

    def test_load_corrupt_names(self, tmp_path):
        store = self._make_store(tmp_path)
        store.path.write_text("{bad json")
        assert store.load_names() == {}

    def test_load_corrupt_titles(self, tmp_path):
        store = self._make_store(tmp_path)
        store.titles_path.parent.mkdir(parents=True, exist_ok=True)
        store.titles_path.write_text("{bad json")
        assert store.load_titles() == {}


# ---------------------------------------------------------------------------
# TagStore
# ---------------------------------------------------------------------------


class TestTagStore:
    def test_tag_store_add_and_get(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        assert store.add_tag("sess1", "debugging") is True
        assert store.add_tag("sess1", "auth-work") is True
        tags = store.get_tags("sess1")
        assert tags == ["debugging", "auth-work"]

    def test_tag_store_remove(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        store.add_tag("sess1", "debugging")
        store.add_tag("sess1", "research")
        assert store.remove_tag("sess1", "debugging") is True
        assert store.get_tags("sess1") == ["research"]

    def test_tag_store_remove_not_found(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        store.add_tag("sess1", "debugging")
        assert store.remove_tag("sess1", "nope") is False
        assert store.remove_tag("sess2", "debugging") is False

    def test_tag_store_duplicate_add(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        assert store.add_tag("sess1", "debugging") is True
        assert store.add_tag("sess1", "debugging") is False
        assert store.get_tags("sess1") == ["debugging"]

    def test_tag_store_all_tags(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        store.add_tag("sess1", "debugging")
        store.add_tag("sess1", "research")
        store.add_tag("sess2", "debugging")
        store.add_tag("sess3", "debugging")
        all_tags = store.all_tags()
        assert all_tags["debugging"] == 3
        assert all_tags["research"] == 1
        # Most common first
        assert list(all_tags.keys())[0] == "debugging"

    def test_tag_store_sessions_with_tag(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        store.add_tag("sess1", "debugging")
        store.add_tag("sess2", "debugging")
        store.add_tag("sess3", "research")
        result = store.sessions_with_tag("debugging")
        assert sorted(result) == ["sess1", "sess2"]
        assert store.sessions_with_tag("nope") == []

    def test_tag_store_normalize(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        store.add_tag("sess1", "  #Debugging  ")
        assert store.get_tags("sess1") == ["debugging"]
        # Duplicate with different casing / prefix
        assert store.add_tag("sess1", "#DEBUGGING") is False
        assert store.remove_tag("sess1", " #Debugging") is True
        assert store.get_tags("sess1") == []

    def test_tag_store_remove_cleans_empty_session(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        store.add_tag("sess1", "only-tag")
        store.remove_tag("sess1", "only-tag")
        # Session key should be removed from the data entirely
        assert store.load() == {}

    def test_tag_store_load_empty(self, tmp_path):
        store = TagStore(tmp_path / "tags.json")
        assert store.load() == {}
        assert store.get_tags("nonexistent") == []

    def test_tag_store_load_corrupt(self, tmp_path):
        path = tmp_path / "tags.json"
        path.write_text("{bad json")
        store = TagStore(path)
        assert store.load() == {}
