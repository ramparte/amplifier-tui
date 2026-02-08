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
        "user_text": "#e0e0e0",
        "user_border": "#cb7700",
        "assistant_text": "#999999",
        "assistant_border": "#333344",
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
  user_text: "#e0e0e0"           # bright white - your messages
  user_border: "#cb7700"         # orange left bar
  assistant_text: "#999999"      # dim gray - model speaking to you
  assistant_border: "#333344"    # subtle border for assistant
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
  sound_enabled: false            # terminal bell when response completes (opt-in)

display:
  show_timestamps: true          # show HH:MM timestamps on messages

model:
  preferred: ""                   # preferred model for new sessions (empty = use default)
"""


@dataclass
class NotificationPreferences:
    """Settings for terminal completion notifications."""

    enabled: bool = True
    min_seconds: float = 3.0  # Only notify if processing took longer than this
    sound_enabled: bool = False  # Terminal bell on response completion (opt-in)


@dataclass
class ColorPreferences:
    """Color values for chat message types."""

    user_text: str = "#e0e0e0"
    user_border: str = "#cb7700"
    assistant_text: str = "#999999"
    assistant_border: str = "#333344"
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
class DisplayPreferences:
    """Display settings for the chat view."""

    show_timestamps: bool = True


@dataclass
class Preferences:
    """Top-level TUI preferences."""

    colors: ColorPreferences = field(default_factory=ColorPreferences)
    notifications: NotificationPreferences = field(
        default_factory=NotificationPreferences
    )
    display: DisplayPreferences = field(default_factory=DisplayPreferences)
    preferred_model: str = ""  # Empty means use default from bundle config

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
                if "sound_enabled" in ndata:
                    prefs.notifications.sound_enabled = bool(ndata["sound_enabled"])
            if isinstance(data.get("display"), dict):
                ddata = data["display"]
                if "show_timestamps" in ddata:
                    prefs.display.show_timestamps = bool(ddata["show_timestamps"])
            if isinstance(data.get("model"), dict):
                mdata = data["model"]
                if "preferred" in mdata:
                    prefs.preferred_model = str(mdata["preferred"] or "")
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


def save_colors(colors: ColorPreferences, path: Path | None = None) -> None:
    """Persist color preferences to the preferences file.

    Surgically updates each color value, preserving user comments and
    other sections as-is.
    """
    import re

    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        color_keys = [
            "user_text",
            "user_border",
            "assistant_text",
            "assistant_border",
            "thinking_text",
            "thinking_border",
            "thinking_background",
            "tool_text",
            "tool_border",
            "tool_background",
            "system_text",
            "system_border",
            "status_bar",
        ]
        for key in color_keys:
            value = getattr(colors, key)
            # Replace existing key line, preserving trailing comments
            pattern = rf'^(\s+{key}:)\s*(?:"[^"]*"|\S+)(.*?)$'
            if re.search(rf"^\s+{key}:", text, re.MULTILINE):
                text = re.sub(
                    pattern,
                    rf'\1 "{value}"\2',
                    text,
                    count=1,
                    flags=re.MULTILINE,
                )
            elif re.search(r"^colors:", text, re.MULTILINE):
                # colors section exists but this key is missing — append it
                text = re.sub(
                    r"^(colors:.*?)$",
                    rf'\1\n  {key}: "{value}"',
                    text,
                    count=1,
                    flags=re.MULTILINE,
                )

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_preferred_model(model: str, path: Path | None = None) -> None:
    """Persist the preferred model to the preferences file.

    Surgically updates only the model section, preserving the rest of the
    file (including user comments) as-is.
    """
    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        # Try to find and replace existing model/preferred line
        import re

        value = f'"{model}"' if model else '""'
        if re.search(r"^\s+preferred:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+preferred:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^model:", text, re.MULTILINE):
            # model: section exists but no preferred key
            text = re.sub(
                r"^(model:.*)$",
                f"\\1\n  preferred: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No model section at all — append it
            text = text.rstrip() + f"\n\nmodel:\n  preferred: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_show_timestamps(enabled: bool, path: Path | None = None) -> None:
    """Persist the show_timestamps display preference to the preferences file.

    Surgically updates only the show_timestamps value, preserving the rest of the
    file (including user comments) as-is.
    """
    import re

    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        value = "true" if enabled else "false"
        if re.search(r"^\s+show_timestamps:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+show_timestamps:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no show_timestamps key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  show_timestamps: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  show_timestamps: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_notification_sound(enabled: bool, path: Path | None = None) -> None:
    """Persist the notification sound preference to the preferences file.

    Surgically updates only the sound_enabled value, preserving the rest of the
    file (including user comments) as-is.
    """
    import re

    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        value = "true" if enabled else "false"
        if re.search(r"^\s+sound_enabled:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+sound_enabled:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^notifications:", text, re.MULTILINE):
            # notifications section exists but no sound_enabled key
            text = re.sub(
                r"^(notifications:.*)$",
                f"\\1\n  sound_enabled: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No notifications section at all — append it
            text = text.rstrip() + f"\n\nnotifications:\n  sound_enabled: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence
