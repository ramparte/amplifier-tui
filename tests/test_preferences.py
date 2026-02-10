"""Tests for preferences loading -- TUI-005.

Verifies that the three previously-missing display fields
(editor_auto_send, fold_threshold, show_suggestions) are loaded
from YAML correctly.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from amplifier_tui.preferences import load_preferences


def test_missing_display_fields_load_from_yaml(tmp_path: Path) -> None:
    """editor_auto_send, fold_threshold, show_suggestions load non-default values."""
    prefs_file = tmp_path / "preferences.yaml"
    prefs_file.write_text(
        dedent("""\
            display:
              editor_auto_send: true
              fold_threshold: 50
              show_suggestions: false
        """)
    )
    prefs = load_preferences(prefs_file)

    assert prefs.display.editor_auto_send is True, "editor_auto_send should be True"
    assert prefs.display.fold_threshold == 50, "fold_threshold should be 50"
    assert prefs.display.show_suggestions is False, "show_suggestions should be False"


def test_missing_display_fields_use_defaults(tmp_path: Path) -> None:
    """When YAML omits the three fields, dataclass defaults apply."""
    prefs_file = tmp_path / "preferences.yaml"
    prefs_file.write_text(
        dedent("""\
            display:
              show_timestamps: true
        """)
    )
    prefs = load_preferences(prefs_file)

    assert prefs.display.editor_auto_send is False
    assert prefs.display.fold_threshold == 20
    assert prefs.display.show_suggestions is True


def test_fold_threshold_zero_disables(tmp_path: Path) -> None:
    """fold_threshold=0 should load as 0 (disabled), not fall back to default."""
    prefs_file = tmp_path / "preferences.yaml"
    prefs_file.write_text(
        dedent("""\
            display:
              fold_threshold: 0
        """)
    )
    prefs = load_preferences(prefs_file)
    assert prefs.display.fold_threshold == 0


def test_all_display_fields_roundtrip(tmp_path: Path) -> None:
    """All 12 display fields load correctly from a full YAML."""
    prefs_file = tmp_path / "preferences.yaml"
    prefs_file.write_text(
        dedent("""\
            display:
              show_timestamps: false
              word_wrap: false
              compact_mode: true
              vim_mode: true
              streaming_enabled: false
              multiline_default: true
              show_token_usage: false
              context_window_size: 128000
              progress_labels: false
              editor_auto_send: true
              fold_threshold: 10
              show_suggestions: false
        """)
    )
    prefs = load_preferences(prefs_file)

    assert prefs.display.show_timestamps is False
    assert prefs.display.word_wrap is False
    assert prefs.display.compact_mode is True
    assert prefs.display.vim_mode is True
    assert prefs.display.streaming_enabled is False
    assert prefs.display.multiline_default is True
    assert prefs.display.show_token_usage is False
    assert prefs.display.context_window_size == 128000
    assert prefs.display.progress_labels is False
    assert prefs.display.editor_auto_send is True
    assert prefs.display.fold_threshold == 10
    assert prefs.display.show_suggestions is False


def test_nonexistent_file_returns_defaults(tmp_path: Path) -> None:
    """Loading from a nonexistent path returns default Preferences."""
    prefs = load_preferences(tmp_path / "does_not_exist.yaml")
    assert prefs.display.editor_auto_send is False
    assert prefs.display.fold_threshold == 20
    assert prefs.display.show_suggestions is True


def test_corrupt_yaml_returns_defaults(tmp_path: Path) -> None:
    """Corrupt YAML falls back to defaults without crashing."""
    prefs_file = tmp_path / "preferences.yaml"
    prefs_file.write_text(": : : not valid yaml [[[")
    prefs = load_preferences(prefs_file)
    assert prefs.display.fold_threshold == 20
