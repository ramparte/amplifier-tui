"""Tests for amplifier_tui.preferences -- TUI-011.

Covers load_preferences, resolve_color, apply_theme, custom themes,
and the save_* round-trip functions.  All file I/O uses tmp_path so
nothing touches the real user config.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from amplifier_tui.preferences import (
    Preferences,
    load_preferences,
    resolve_color,
    save_compact_mode,
    save_editor_auto_send,
    save_fold_threshold,
    save_show_suggestions,
    save_show_timestamps,
    save_streaming_enabled,
    save_theme_name,
    save_vim_mode,
    save_word_wrap,
)


# -- resolve_color -----------------------------------------------------------


class TestResolveColor:
    """resolve_color accepts named colors, hex codes, and rejects junk."""

    def test_named_color(self):
        assert resolve_color("cyan") == "#00cccc"

    def test_named_color_case_insensitive(self):
        assert resolve_color("Cyan") == "#00cccc"

    def test_hex_color(self):
        assert resolve_color("#ff0000") == "#ff0000"

    def test_hex_uppercase(self):
        assert resolve_color("#FF0000") == "#FF0000"

    def test_invalid_color_returns_none(self):
        assert resolve_color("rainbow") is None

    def test_short_hex_rejected(self):
        assert resolve_color("#fff") is None

    def test_whitespace_stripped(self):
        assert resolve_color("  cyan  ") == "#00cccc"
        assert resolve_color("  #aabbcc  ") == "#aabbcc"


# -- load_preferences --------------------------------------------------------


class TestLoadPreferencesDefaults:
    """When no file exists, load_preferences returns sensible defaults."""

    def test_defaults_when_no_file(self, tmp_path: Path):
        prefs = load_preferences(tmp_path / "nonexistent.yaml")
        assert prefs.display.show_timestamps is True
        assert prefs.display.word_wrap is True
        assert prefs.display.compact_mode is False
        assert prefs.display.fold_threshold == 20
        assert prefs.display.editor_auto_send is False
        assert prefs.display.show_suggestions is True
        assert prefs.notifications.enabled is True
        assert prefs.theme_name == "dark"

    def test_creates_default_file(self, tmp_path: Path):
        path = tmp_path / "prefs.yaml"
        load_preferences(path)
        assert path.exists()


class TestLoadPreferencesFromYAML:
    """Loading from valid YAML sets all fields correctly."""

    def test_all_sections(self, tmp_path: Path):
        path = tmp_path / "prefs.yaml"
        path.write_text(
            yaml.dump(
                {
                    "display": {
                        "show_timestamps": False,
                        "word_wrap": False,
                        "compact_mode": True,
                        "vim_mode": True,
                        "streaming_enabled": False,
                        "editor_auto_send": True,
                        "multiline_default": True,
                        "show_token_usage": False,
                        "context_window_size": 128000,
                        "fold_threshold": 50,
                        "show_suggestions": False,
                        "progress_labels": False,
                    },
                    "notifications": {
                        "enabled": False,
                        "min_seconds": 10.0,
                        "sound_enabled": True,
                        "title_flash": False,
                    },
                    "colors": {
                        "user_text": "#111111",
                        "assistant_text": "#222222",
                    },
                    "model": {"preferred": "claude-sonnet-4-20250514"},
                    "theme": {"name": "light"},
                    "sidebar": {"session_sort": "name"},
                    "autosave": {"enabled": False, "interval": 60},
                }
            )
        )
        prefs = load_preferences(path)

        # Display
        assert prefs.display.show_timestamps is False
        assert prefs.display.word_wrap is False
        assert prefs.display.compact_mode is True
        assert prefs.display.vim_mode is True
        assert prefs.display.streaming_enabled is False
        assert prefs.display.editor_auto_send is True
        assert prefs.display.multiline_default is True
        assert prefs.display.show_token_usage is False
        assert prefs.display.context_window_size == 128000
        assert prefs.display.fold_threshold == 50
        assert prefs.display.show_suggestions is False
        assert prefs.display.progress_labels is False

        # Notifications
        assert prefs.notifications.enabled is False
        assert prefs.notifications.min_seconds == 10.0
        assert prefs.notifications.sound_enabled is True
        assert prefs.notifications.title_flash is False

        # Colors
        assert prefs.colors.user_text == "#111111"
        assert prefs.colors.assistant_text == "#222222"

        # Other top-level
        assert prefs.preferred_model == "claude-sonnet-4-20250514"
        assert prefs.theme_name == "light"
        assert prefs.session_sort == "name"
        assert prefs.autosave.enabled is False
        assert prefs.autosave.interval == 60

    def test_missing_sections_use_defaults(self, tmp_path: Path):
        """Partial YAML still returns valid Preferences with defaults."""
        path = tmp_path / "prefs.yaml"
        path.write_text(yaml.dump({"display": {"compact_mode": True}}))
        prefs = load_preferences(path)
        assert prefs.display.compact_mode is True
        assert prefs.display.show_timestamps is True  # default
        assert prefs.notifications.enabled is True  # default
        assert prefs.colors.user_text == "#e0e0e0"  # default

    def test_corrupt_yaml_returns_defaults(self, tmp_path: Path):
        path = tmp_path / "prefs.yaml"
        path.write_text("{{{{not valid yaml:::::")
        prefs = load_preferences(path)
        # Should return defaults without crashing
        assert prefs.display.show_timestamps is True
        assert prefs.theme_name == "dark"

    def test_empty_yaml_returns_defaults(self, tmp_path: Path):
        path = tmp_path / "prefs.yaml"
        path.write_text("")
        prefs = load_preferences(path)
        assert prefs.display.fold_threshold == 20

    def test_fold_threshold_none_uses_default(self, tmp_path: Path):
        """fold_threshold: null in YAML should use default 20."""
        path = tmp_path / "prefs.yaml"
        path.write_text("display:\n  fold_threshold: null\n")
        prefs = load_preferences(path)
        assert prefs.display.fold_threshold == 20

    def test_invalid_session_sort_ignored(self, tmp_path: Path):
        path = tmp_path / "prefs.yaml"
        path.write_text(yaml.dump({"sidebar": {"session_sort": "random"}}))
        prefs = load_preferences(path)
        assert prefs.session_sort == "date"  # default

    def test_autosave_interval_minimum(self, tmp_path: Path):
        """Autosave interval has a floor of 30 seconds."""
        path = tmp_path / "prefs.yaml"
        path.write_text(yaml.dump({"autosave": {"interval": 5}}))
        prefs = load_preferences(path)
        assert prefs.autosave.interval == 30


# -- apply_theme -------------------------------------------------------------


class TestApplyTheme:
    """Preferences.apply_theme applies built-in themes."""

    def test_apply_dark_theme(self):
        prefs = Preferences()
        assert prefs.apply_theme("dark") is True
        assert prefs.colors.user_border == "#cb7700"

    def test_apply_light_theme(self):
        prefs = Preferences()
        assert prefs.apply_theme("light") is True
        # Light theme overrides colors
        assert prefs.colors.user_text != "#e0e0e0"  # changed from dark default

    def test_unknown_theme_returns_false(self):
        prefs = Preferences()
        assert prefs.apply_theme("nonexistent") is False

    def test_theme_does_not_modify_noncolor_fields(self):
        prefs = Preferences()
        prefs.display.compact_mode = True
        prefs.apply_theme("light")
        assert prefs.display.compact_mode is True  # unchanged


# -- save_* round-trips ------------------------------------------------------


class TestSaveRoundTrips:
    """save_* functions write to YAML and load_preferences reads them back."""

    def _make_base(self, tmp_path: Path) -> Path:
        path = tmp_path / "prefs.yaml"
        path.write_text("display:\n  show_timestamps: true\n  fold_threshold: 20\n")
        return path

    def test_save_fold_threshold(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_fold_threshold(42, path=path)
        prefs = load_preferences(path)
        assert prefs.display.fold_threshold == 42

    def test_save_fold_threshold_zero_disables(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_fold_threshold(0, path=path)
        prefs = load_preferences(path)
        assert prefs.display.fold_threshold == 0

    def test_save_fold_threshold_negative_clamps(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_fold_threshold(-5, path=path)
        prefs = load_preferences(path)
        assert prefs.display.fold_threshold == 0

    def test_save_editor_auto_send(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_editor_auto_send(True, path=path)
        prefs = load_preferences(path)
        assert prefs.display.editor_auto_send is True

    def test_save_show_suggestions(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_show_suggestions(False, path=path)
        prefs = load_preferences(path)
        assert prefs.display.show_suggestions is False

    def test_save_show_timestamps(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_show_timestamps(False, path=path)
        prefs = load_preferences(path)
        assert prefs.display.show_timestamps is False

    def test_save_word_wrap(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_word_wrap(False, path=path)
        prefs = load_preferences(path)
        assert prefs.display.word_wrap is False

    def test_save_compact_mode(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_compact_mode(True, path=path)
        prefs = load_preferences(path)
        assert prefs.display.compact_mode is True

    def test_save_vim_mode(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_vim_mode(True, path=path)
        prefs = load_preferences(path)
        assert prefs.display.vim_mode is True

    def test_save_streaming_enabled(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_streaming_enabled(False, path=path)
        prefs = load_preferences(path)
        assert prefs.display.streaming_enabled is False

    def test_save_theme_name(self, tmp_path: Path):
        path = self._make_base(tmp_path)
        save_theme_name("dracula", path=path)
        prefs = load_preferences(path)
        assert prefs.theme_name == "dracula"

    def test_save_to_nonexistent_file(self, tmp_path: Path):
        """save_* creates file if it doesn't exist."""
        path = tmp_path / "new" / "prefs.yaml"
        save_fold_threshold(99, path=path)
        prefs = load_preferences(path)
        assert prefs.display.fold_threshold == 99
