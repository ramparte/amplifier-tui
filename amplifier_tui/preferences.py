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

# Built-in theme presets: each maps color preference keys to hex values.
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "user_text": "#ffffff",
        "user_border": "#cb7700",
        "assistant_text": "#44bb77",
        "assistant_border": "#336699",
        "thinking_text": "#666677",
        "thinking_border": "#665588",
        "thinking_background": "#110e18",
        "tool_text": "#555555",
        "tool_border": "#444444",
        "tool_background": "#0a0a0a",
        "system_text": "#88bbcc",
        "system_border": "#448899",
        "status_bar": "#888888",
    },
    "light": {
        "user_text": "#1a1a1a",
        "user_border": "#cc6600",
        "assistant_text": "#006633",
        "assistant_border": "#4488aa",
        "thinking_text": "#888888",
        "thinking_border": "#9988bb",
        "thinking_background": "#f0eef5",
        "tool_text": "#666666",
        "tool_border": "#aaaaaa",
        "tool_background": "#f5f5f5",
        "system_text": "#337788",
        "system_border": "#66aabb",
        "status_bar": "#555555",
    },
    "solarized": {
        "user_text": "#fdf6e3",
        "user_border": "#b58900",
        "assistant_text": "#859900",
        "assistant_border": "#268bd2",
        "thinking_text": "#657b83",
        "thinking_border": "#6c71c4",
        "thinking_background": "#002b36",
        "tool_text": "#586e75",
        "tool_border": "#073642",
        "tool_background": "#002b36",
        "system_text": "#2aa198",
        "system_border": "#2aa198",
        "status_bar": "#839496",
    },
}

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
  system_text: "#88bbcc"         # teal - slash command output
  system_border: "#448899"       # teal left bar
  status_bar: "#888888"          # bottom status text

notifications:
  enabled: true                  # notify when a response completes
  min_seconds: 3.0               # only notify if processing took longer than this
"""


@dataclass
class NotificationPreferences:
    """Settings for terminal completion notifications."""

    enabled: bool = True
    min_seconds: float = 3.0  # Only notify if processing took longer than this


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
    system_text: str = "#88bbcc"
    system_border: str = "#448899"
    status_bar: str = "#888888"


@dataclass
class Preferences:
    """Top-level TUI preferences."""

    colors: ColorPreferences = field(default_factory=ColorPreferences)
    notifications: NotificationPreferences = field(
        default_factory=NotificationPreferences
    )

    def apply_theme(self, name: str) -> bool:
        """Apply a built-in theme by name. Returns False if unknown."""
        theme = THEMES.get(name)
        if theme is None:
            return False
        for key, value in theme.items():
            if hasattr(self.colors, key):
                setattr(self.colors, key, value)
        return True


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
            if isinstance(data.get("notifications"), dict):
                ndata = data["notifications"]
                if "enabled" in ndata:
                    prefs.notifications.enabled = bool(ndata["enabled"])
                if "min_seconds" in ndata:
                    prefs.notifications.min_seconds = float(ndata["min_seconds"])
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
