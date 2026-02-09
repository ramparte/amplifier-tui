"""Tests for the constants module."""

from __future__ import annotations

from pathlib import Path

from amplifier_tui.constants import (
    AUTOSAVE_DIR,
    AVAILABLE_MODELS,
    DEFAULT_CONTEXT_WINDOW,
    EXTENSION_TO_LANGUAGE,
    MAX_ATTACHMENT_SIZE,
    MAX_AUTOSAVES_PER_TAB,
    MAX_INCLUDE_LINES,
    MAX_INCLUDE_SIZE,
    MAX_TABS,
    MODES,
    MODEL_ALIASES,
    MODEL_CONTEXT_WINDOWS,
    PROMPT_TEMPLATES,
    SLASH_COMMANDS,
    SYSTEM_PRESETS,
    TOOL_LABELS,
    _DANGEROUS_PATTERNS,
    _MAX_LABEL_LEN,
    _MAX_RUN_OUTPUT_LINES,
    _RUN_TIMEOUT,
)


class TestToolLabels:
    def test_is_dict(self):
        assert isinstance(TOOL_LABELS, dict)

    def test_has_common_tools(self):
        for tool in ("read_file", "write_file", "edit_file", "bash", "grep"):
            assert tool in TOOL_LABELS

    def test_values_are_strings(self):
        for k, v in TOOL_LABELS.items():
            assert isinstance(k, str)
            assert isinstance(v, str)


class TestSlashCommands:
    def test_is_tuple(self):
        assert isinstance(SLASH_COMMANDS, tuple)

    def test_all_start_with_slash(self):
        for cmd in SLASH_COMMANDS:
            assert cmd.startswith("/"), f"{cmd!r} does not start with /"

    def test_has_common_commands(self):
        for cmd in ("/help", "/clear", "/new", "/quit", "/export"):
            assert cmd in SLASH_COMMANDS

    def test_not_empty(self):
        assert len(SLASH_COMMANDS) > 50  # We know there are 89


class TestPaths:
    def test_autosave_dir_is_path(self):
        assert isinstance(AUTOSAVE_DIR, Path)

    def test_autosave_dir_under_home(self):
        assert ".amplifier" in str(AUTOSAVE_DIR)


class TestNumericConstants:
    def test_max_autosaves_per_tab(self):
        assert isinstance(MAX_AUTOSAVES_PER_TAB, int)
        assert MAX_AUTOSAVES_PER_TAB > 0

    def test_max_label_len(self):
        assert isinstance(_MAX_LABEL_LEN, int)
        assert _MAX_LABEL_LEN > 0

    def test_run_timeout(self):
        assert isinstance(_RUN_TIMEOUT, int)
        assert _RUN_TIMEOUT > 0

    def test_max_run_output_lines(self):
        assert isinstance(_MAX_RUN_OUTPUT_LINES, int)
        assert _MAX_RUN_OUTPUT_LINES > 0

    def test_max_include_lines(self):
        assert isinstance(MAX_INCLUDE_LINES, int)
        assert MAX_INCLUDE_LINES > 0

    def test_max_include_size(self):
        assert isinstance(MAX_INCLUDE_SIZE, int)
        assert MAX_INCLUDE_SIZE > 0

    def test_max_tabs(self):
        assert isinstance(MAX_TABS, int)
        assert MAX_TABS > 0

    def test_max_attachment_size(self):
        assert isinstance(MAX_ATTACHMENT_SIZE, int)
        assert MAX_ATTACHMENT_SIZE > 0

    def test_default_context_window(self):
        assert isinstance(DEFAULT_CONTEXT_WINDOW, int)
        assert DEFAULT_CONTEXT_WINDOW > 0


class TestSystemPresets:
    def test_is_dict(self):
        assert isinstance(SYSTEM_PRESETS, dict)

    def test_has_known_presets(self):
        for name in ("coder", "reviewer", "teacher", "concise"):
            assert name in SYSTEM_PRESETS

    def test_values_are_nonempty_strings(self):
        for k, v in SYSTEM_PRESETS.items():
            assert isinstance(v, str)
            assert len(v) > 10  # meaningful prompt text


class TestModes:
    def test_is_dict(self):
        assert isinstance(MODES, dict)

    def test_has_expected_modes(self):
        for mode in ("planning", "research", "review", "debug"):
            assert mode in MODES

    def test_mode_entries_have_required_keys(self):
        for name, entry in MODES.items():
            assert "description" in entry
            assert "indicator" in entry
            assert "accent" in entry


class TestModelAliases:
    def test_is_dict(self):
        assert isinstance(MODEL_ALIASES, dict)

    def test_has_common_aliases(self):
        assert "sonnet" in MODEL_ALIASES
        assert "haiku" in MODEL_ALIASES

    def test_values_are_model_ids(self):
        for alias, model_id in MODEL_ALIASES.items():
            assert isinstance(model_id, str)
            assert len(model_id) > 1


class TestAvailableModels:
    def test_is_tuple(self):
        assert isinstance(AVAILABLE_MODELS, tuple)

    def test_entries_are_triples(self):
        for entry in AVAILABLE_MODELS:
            assert len(entry) == 3
            model_id, provider, description = entry
            assert isinstance(model_id, str)
            assert isinstance(provider, str)
            assert isinstance(description, str)


class TestDangerousPatterns:
    def test_is_tuple(self):
        assert isinstance(_DANGEROUS_PATTERNS, tuple)

    def test_not_empty(self):
        assert len(_DANGEROUS_PATTERNS) > 0


class TestPromptTemplates:
    def test_is_tuple(self):
        assert isinstance(PROMPT_TEMPLATES, tuple)

    def test_not_empty(self):
        assert len(PROMPT_TEMPLATES) > 0

    def test_entries_are_strings(self):
        for t in PROMPT_TEMPLATES:
            assert isinstance(t, str)


class TestExtensionToLanguage:
    def test_is_dict(self):
        assert isinstance(EXTENSION_TO_LANGUAGE, dict)

    def test_has_python(self):
        assert ".py" in EXTENSION_TO_LANGUAGE
        assert EXTENSION_TO_LANGUAGE[".py"] == "python"

    def test_keys_start_with_dot(self):
        for ext in EXTENSION_TO_LANGUAGE:
            assert ext.startswith(".")


class TestModelContextWindows:
    def test_is_dict(self):
        assert isinstance(MODEL_CONTEXT_WINDOWS, dict)

    def test_values_are_positive_ints(self):
        for model, window in MODEL_CONTEXT_WINDOWS.items():
            assert isinstance(window, int)
            assert window > 0
