"""User preferences for Amplifier TUI.

Loads color customizations from ~/.amplifier/tui-preferences.yaml.
Falls back to sensible defaults if the file doesn't exist or is invalid.
Creates a default file on first run so users can discover and edit it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PREFS_PATH = Path.home() / ".amplifier" / "tui-preferences.yaml"

_DEFAULT_YAML = """\
# Amplifier TUI Preferences
# Customize colors for the chat interface.
# All values are CSS color strings (hex recommended).
# Delete this file to reset to defaults.

colors:
  user_text: "#ffffff"           # bright white - your messages
  user_border: "#cb7700"         # orange left bar
  assistant_text: "#44bb77"      # green - model speaking to you
  assistant_border: "#336699"    # blue left bar
  thinking_text: "#666677"       # dim gray - background reasoning
  thinking_border: "#665588"     # purple left bar
  thinking_background: "#110e18" # dark purple tint
  tool_text: "#555555"           # dimmest - mechanical tool output
  tool_border: "#444444"         # gray left bar
  tool_background: "#0a0a0a"     # near-black tint
  status_bar: "#888888"          # bottom status text
"""


@dataclass
class ColorPreferences:
    """Color values for chat message types."""

    user_text: str = "#ffffff"
    user_border: str = "#cb7700"
    assistant_text: str = "#44bb77"
    assistant_border: str = "#336699"
    thinking_text: str = "#666677"
    thinking_border: str = "#665588"
    thinking_background: str = "#110e18"
    tool_text: str = "#555555"
    tool_border: str = "#444444"
    tool_background: str = "#0a0a0a"
    status_bar: str = "#888888"


@dataclass
class Preferences:
    """Top-level TUI preferences."""

    colors: ColorPreferences = field(default_factory=ColorPreferences)


def load_preferences(path: Path | None = None) -> Preferences:
    """Load preferences from YAML file.

    Falls back to sensible defaults if the file doesn't exist or is invalid.
    Creates a default preferences file on first run.
    """
    path = path or PREFS_PATH
    prefs = Preferences()

    if path.exists():
        try:
            data = yaml.safe_load(path.read_text()) or {}
            if isinstance(data.get("colors"), dict):
                for key, value in data["colors"].items():
                    if hasattr(prefs.colors, key):
                        setattr(prefs.colors, key, str(value))
        except Exception:
            pass  # Fall back to defaults on any parse error
    else:
        # Create default file for user to customize
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_DEFAULT_YAML)
        except Exception:
            pass  # Don't fail if we can't write

    return prefs
