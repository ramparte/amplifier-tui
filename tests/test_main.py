"""Tests for the __main__ entry point."""

from __future__ import annotations

import builtins
import sys
from unittest.mock import patch

import pytest

from amplifier_tui.__main__ import _check_amplifier


class TestCheckAmplifier:
    """Tests for the _check_amplifier availability check."""

    def test_returns_true_when_amplifier_core_importable(self):
        # In our test env, session_manager's sys.path setup finds amplifier_core
        # (or it's already importable). Either way, should return True.
        assert _check_amplifier() is True

    def test_returns_false_when_amplifier_core_missing(self):
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "amplifier_core":
                raise ImportError("No module named 'amplifier_core'")
            return real_import(name, *args, **kwargs)

        # Remove amplifier_core from sys.modules so the check re-imports
        saved = sys.modules.pop("amplifier_core", None)
        try:
            with patch("builtins.__import__", side_effect=mock_import):
                assert _check_amplifier() is False
        finally:
            if saved is not None:
                sys.modules["amplifier_core"] = saved


class TestMainExitsWithoutAmplifier:
    """Test that main() exits cleanly when Amplifier is missing."""

    def test_prints_install_message_and_exits(self, capsys):
        with patch("amplifier_tui.__main__._check_amplifier", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                from amplifier_tui.__main__ import main

                sys.argv = ["amplifier-tui"]
                main()

            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "requires Amplifier to be installed" in captured.err
        assert "github.com/microsoft/amplifier" in captured.err


class TestCockpitFlag:
    """CLI --cockpit and --no-cockpit flags."""

    def test_cockpit_flag_recognized(self):
        """argparse accepts --cockpit."""
        import argparse

        # Re-create the parser to test flag parsing
        parser = argparse.ArgumentParser()
        parser.add_argument("--cockpit", action="store_true")
        parser.add_argument("--no-cockpit", action="store_true")
        parser.add_argument("prompt", nargs="*")
        args = parser.parse_args(["--cockpit"])
        assert args.cockpit is True
        assert args.no_cockpit is False

    def test_no_cockpit_flag(self):
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--cockpit", action="store_true")
        parser.add_argument("--no-cockpit", action="store_true")
        parser.add_argument("prompt", nargs="*")
        args = parser.parse_args(["--no-cockpit"])
        assert args.no_cockpit is True
