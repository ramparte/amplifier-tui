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

# Named color map: user-friendly names -> hex values.
# Supports standard terminal colors plus a few useful extras.
COLOR_NAMES: dict[str, str] = {
    "white": "#ffffff",
    "bright_white": "#ffffff",
    "gray": "#888888",
    "grey": "#888888",
    "dim": "#666666",
    "black": "#000000",
    "red": "#cc0000",
    "green": "#00cc00",
    "bright_green": "#00ff00",
    "blue": "#0066cc",
    "cyan": "#00cccc",
    "magenta": "#cc00cc",
    "yellow": "#cccc00",
    "orange": "#cc7700",
}


def resolve_color(value: str) -> str | None:
    """Resolve a color value to a hex string.

    Accepts:
      - Named colors (white, gray, cyan, etc.)
      - Hex codes (#RRGGBB)

    Returns the hex string, or None if the value is not recognised.
    """
    import re

    low = value.strip().lower()
    if low in COLOR_NAMES:
        return COLOR_NAMES[low]
    if re.match(r"^#[0-9a-fA-F]{6}$", value.strip()):
        return value.strip()
    return None


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
        "error_text": "#cc0000",
        "error_border": "#cc0000",
        "note_text": "#e0d080",
        "note_border": "#c0a030",
        "timestamp": "#444444",
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
        "error_text": "#cc0000",
        "error_border": "#cc0000",
        "note_text": "#806020",
        "note_border": "#a08030",
        "timestamp": "#999999",
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
        "error_text": "#dc322f",
        "error_border": "#dc322f",
        "note_text": "#b58900",
        "note_border": "#cb4b16",
        "timestamp": "#586e75",
        "status_bar": "#839496",
    },
    "monokai": {
        "user_text": "#f8f8f2",
        "user_border": "#fd971f",
        "assistant_text": "#a6e22e",
        "assistant_border": "#3e3d32",
        "thinking_text": "#75715e",
        "thinking_border": "#ae81ff",
        "thinking_background": "#1e1f1c",
        "tool_text": "#75715e",
        "tool_border": "#3e3d32",
        "tool_background": "#1e1f1c",
        "system_text": "#66d9ef",
        "system_border": "#66d9ef",
        "error_text": "#f92672",
        "error_border": "#f92672",
        "note_text": "#e6db74",
        "note_border": "#fd971f",
        "timestamp": "#75715e",
        "status_bar": "#a6a6a6",
    },
    "high-contrast": {
        "user_text": "#ffffff",
        "user_border": "#ffff00",
        "assistant_text": "#ffffff",
        "assistant_border": "#00ff00",
        "thinking_text": "#808080",
        "thinking_border": "#00ffff",
        "thinking_background": "#0a0a0a",
        "tool_text": "#808080",
        "tool_border": "#333333",
        "tool_background": "#0a0a0a",
        "system_text": "#00ff00",
        "system_border": "#00ff00",
        "error_text": "#ff0000",
        "error_border": "#ff0000",
        "note_text": "#ffff00",
        "note_border": "#ffaa00",
        "timestamp": "#808080",
        "status_bar": "#ffffff",
    },
    "nord": {
        "user_text": "#eceff4",
        "user_border": "#ebcb8b",
        "assistant_text": "#a3be8c",
        "assistant_border": "#3b4252",
        "thinking_text": "#4c566a",
        "thinking_border": "#b48ead",
        "thinking_background": "#242933",
        "tool_text": "#4c566a",
        "tool_border": "#3b4252",
        "tool_background": "#242933",
        "system_text": "#88c0d0",
        "system_border": "#88c0d0",
        "error_text": "#bf616a",
        "error_border": "#bf616a",
        "note_text": "#ebcb8b",
        "note_border": "#d08770",
        "timestamp": "#4c566a",
        "status_bar": "#9aa5b4",
    },
    "dracula": {
        "user_text": "#f8f8f2",
        "user_border": "#ffb86c",
        "assistant_text": "#50fa7b",
        "assistant_border": "#44475a",
        "thinking_text": "#6272a4",
        "thinking_border": "#bd93f9",
        "thinking_background": "#21222c",
        "tool_text": "#6272a4",
        "tool_border": "#44475a",
        "tool_background": "#21222c",
        "system_text": "#8be9fd",
        "system_border": "#8be9fd",
        "error_text": "#ff5555",
        "error_border": "#ff5555",
        "note_text": "#f1fa8c",
        "note_border": "#ffb86c",
        "timestamp": "#6272a4",
        "status_bar": "#9999bb",
    },
    "gruvbox": {
        "user_text": "#ebdbb2",
        "user_border": "#d65d0e",
        "assistant_text": "#b8bb26",
        "assistant_border": "#3c3836",
        "thinking_text": "#665c54",
        "thinking_border": "#b16286",
        "thinking_background": "#1d2021",
        "tool_text": "#665c54",
        "tool_border": "#3c3836",
        "tool_background": "#1d2021",
        "system_text": "#83a598",
        "system_border": "#83a598",
        "error_text": "#fb4934",
        "error_border": "#fb4934",
        "note_text": "#fabd2f",
        "note_border": "#d65d0e",
        "timestamp": "#665c54",
        "status_bar": "#a89984",
    },
    "catppuccin": {
        "user_text": "#cdd6f4",
        "user_border": "#fab387",
        "assistant_text": "#a6e3a1",
        "assistant_border": "#313244",
        "thinking_text": "#585b70",
        "thinking_border": "#cba6f7",
        "thinking_background": "#181825",
        "tool_text": "#585b70",
        "tool_border": "#313244",
        "tool_background": "#181825",
        "system_text": "#89dceb",
        "system_border": "#89dceb",
        "error_text": "#f38ba8",
        "error_border": "#f38ba8",
        "note_text": "#f9e2af",
        "note_border": "#fab387",
        "timestamp": "#585b70",
        "status_bar": "#9399b2",
    },
    "midnight": {
        "user_text": "#e8e8f0",
        "user_border": "#536dfe",
        "assistant_text": "#8899cc",
        "assistant_border": "#1a1f4e",
        "thinking_text": "#4455aa",
        "thinking_border": "#7c4dff",
        "thinking_background": "#080c1e",
        "tool_text": "#3d4680",
        "tool_border": "#1a1f4e",
        "tool_background": "#080c1e",
        "system_text": "#64b5f6",
        "system_border": "#42a5f5",
        "error_text": "#ff5252",
        "error_border": "#ff5252",
        "note_text": "#ffd740",
        "note_border": "#ffab40",
        "timestamp": "#3d4680",
        "status_bar": "#7788bb",
    },
    "solarized-light": {
        "user_text": "#073642",
        "user_border": "#b58900",
        "assistant_text": "#2aa198",
        "assistant_border": "#eee8d5",
        "thinking_text": "#93a1a1",
        "thinking_border": "#6c71c4",
        "thinking_background": "#eee8d5",
        "tool_text": "#93a1a1",
        "tool_border": "#eee8d5",
        "tool_background": "#fdf6e3",
        "system_text": "#268bd2",
        "system_border": "#268bd2",
        "error_text": "#dc322f",
        "error_border": "#dc322f",
        "note_text": "#b58900",
        "note_border": "#cb4b16",
        "timestamp": "#93a1a1",
        "status_bar": "#657b83",
    },
}

# Human-readable descriptions for each theme (displayed by /theme).
THEME_DESCRIPTIONS: dict[str, str] = {
    "dark": "Default dark theme",
    "light": "Light theme for bright environments",
    "solarized": "Solarized dark",
    "solarized-light": "Solarized light for bright environments",
    "monokai": "Monokai Pro inspired",
    "high-contrast": "Maximum readability",
    "nord": "Arctic, north-bluish",
    "dracula": "Dark theme with vibrant colors",
    "gruvbox": "Retro groove, warm earthy tones",
    "catppuccin": "Soothing pastel (Mocha)",
    "midnight": "Deep blue/navy dark theme",
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
  error_text: "#cc0000"          # red - error messages
  error_border: "#cc0000"        # red left bar
  note_text: "#e0d080"           # warm yellow - session notes
  note_border: "#c0a030"         # golden left bar
  timestamp: "#444444"           # dim timestamp labels
  status_bar: "#888888"          # bottom status text

notifications:
  enabled: true                  # notify when a response completes
  min_seconds: 3.0               # only notify if processing took longer than this
  sound_enabled: false            # terminal bell when response completes (opt-in)
  sound_on_error: true            # beep on errors (when sound_enabled is true)
  sound_on_file_change: false     # beep on /watch file changes (when sound_enabled)
  title_flash: true               # flash terminal title bar when response completes

display:
  show_timestamps: true          # show HH:MM timestamps on messages
  word_wrap: true                # wrap long lines (off = horizontal scroll)
  compact_mode: false            # dense layout with reduced spacing
  vim_mode: false                # vim-style keybindings in input area
  streaming_enabled: true        # progressive token streaming (tokens appear as they arrive)
  multiline_default: false       # start in multiline mode (Enter = newline, Ctrl+Enter = send)
  show_token_usage: true         # show token/context gauge in status bar
  context_window_size: 0         # override context window size (0 = auto-detect from model)
  fold_threshold: 20             # auto-fold messages longer than this many lines (0 = disabled)

model:
  preferred: ""                   # preferred model for new sessions (empty = use default)

theme:
  name: "dark"                    # color theme: dark, light, solarized, solarized-light, monokai,
                                  #   high-contrast, nord, dracula, gruvbox, catppuccin, midnight

sidebar:
  session_sort: "date"            # session sort order: date, name, project

autosave:
  enabled: true                   # auto-save sessions periodically and after responses
  interval: 120                   # seconds between periodic auto-saves (default 2 min)

# Custom themes: define your own color themes here.
# Each key becomes a theme name usable with /theme <name>.
# Only include the color keys you want to override; missing keys are
# filled from the 'base' built-in theme (default: dark).
#
# custom_themes:
#   my-ocean:
#     description: "Deep ocean vibes"
#     base: dark                  # inherit missing colors from this built-in
#     user_text: "#e0f0ff"
#     user_border: "#0088cc"
#     assistant_text: "#66ddaa"
#     system_text: "#44aaff"
#     system_border: "#44aaff"
"""


@dataclass
class NotificationPreferences:
    """Settings for terminal completion notifications."""

    enabled: bool = True
    min_seconds: float = 3.0  # Only notify if processing took longer than this
    sound_enabled: bool = False  # Terminal bell on response completion (opt-in)
    sound_on_error: bool = True  # Beep on errors (when sound_enabled)
    sound_on_file_change: bool = (
        False  # Beep on /watch file changes (when sound_enabled)
    )
    title_flash: bool = True  # Flash terminal title bar on response completion


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
    error_text: str = "#cc0000"
    error_border: str = "#cc0000"
    note_text: str = "#e0d080"
    note_border: str = "#c0a030"
    timestamp: str = "#444444"
    status_bar: str = "#888888"


@dataclass
class DisplayPreferences:
    """Display settings for the chat view."""

    show_timestamps: bool = True
    word_wrap: bool = True
    compact_mode: bool = False
    vim_mode: bool = False
    streaming_enabled: bool = True  # Progressive token streaming display
    editor_auto_send: bool = False  # Auto-send message after external editor closes
    multiline_default: bool = False  # Start in multiline mode
    show_token_usage: bool = True  # Show token/context gauge in status bar
    context_window_size: int = 0  # Override context window (0 = auto-detect from model)
    fold_threshold: int = 20  # Auto-fold messages longer than this (0 = disabled)
    show_suggestions: bool = True  # Show smart prompt suggestions as you type


@dataclass
class AutosavePreferences:
    """Settings for periodic session auto-save."""

    enabled: bool = True  # Auto-save sessions periodically and after responses
    interval: int = 120  # Seconds between periodic auto-saves (default 2 min)


@dataclass
class Preferences:
    """Top-level TUI preferences."""

    colors: ColorPreferences = field(default_factory=ColorPreferences)
    notifications: NotificationPreferences = field(
        default_factory=NotificationPreferences
    )
    display: DisplayPreferences = field(default_factory=DisplayPreferences)
    autosave: AutosavePreferences = field(default_factory=AutosavePreferences)
    preferred_model: str = ""  # Empty means use default from bundle config
    theme_name: str = "dark"  # Active theme name (persisted for display)
    session_sort: str = "date"  # Session sort order: date, name, project

    def apply_theme(self, name: str) -> bool:
        """Apply a built-in theme by name. Returns False if unknown."""
        theme = THEMES.get(name)
        if theme is None:
            return False
        for key, value in theme.items():
            if hasattr(self.colors, key):
                setattr(self.colors, key, value)
        return True


def _load_custom_themes(custom_data: dict) -> None:
    """Merge user-defined custom themes into the module-level THEMES dict.

    Each entry in *custom_data* is a theme name mapping to a dict of color
    overrides.  Two optional meta-keys are recognised:

    * ``description`` – human-readable label shown by ``/theme``.
    * ``base`` – name of a built-in theme whose colors fill any keys not
      explicitly provided (default: ``"dark"``).

    All other keys should be valid ``ColorPreferences`` field names with
    hex color values.
    """
    from dataclasses import fields as dc_fields

    valid_keys = {f.name for f in dc_fields(ColorPreferences)}

    for raw_name, tdata in custom_data.items():
        if not isinstance(tdata, dict):
            continue
        name = str(raw_name).lower().strip()
        if not name:
            continue

        desc = str(tdata.get("description", f"Custom: {name}"))
        base = str(tdata.get("base", "dark"))

        # Build color dict from provided keys
        color_dict: dict[str, str] = {}
        for key in valid_keys:
            if key in tdata:
                resolved = resolve_color(str(tdata[key]))
                if resolved:
                    color_dict[key] = resolved

        if not color_dict:
            continue  # Nothing useful – skip

        # Fill missing keys from the base theme
        base_colors = THEMES.get(base, THEMES.get("dark", {}))
        for key in valid_keys:
            if key not in color_dict and key in base_colors:
                color_dict[key] = base_colors[key]

        THEMES[name] = color_dict
        THEME_DESCRIPTIONS[name] = desc


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
                if "sound_on_error" in ndata:
                    prefs.notifications.sound_on_error = bool(ndata["sound_on_error"])
                if "sound_on_file_change" in ndata:
                    prefs.notifications.sound_on_file_change = bool(
                        ndata["sound_on_file_change"]
                    )
                if "title_flash" in ndata:
                    prefs.notifications.title_flash = bool(ndata["title_flash"])
            if isinstance(data.get("display"), dict):
                ddata = data["display"]
                if "show_timestamps" in ddata:
                    prefs.display.show_timestamps = bool(ddata["show_timestamps"])
                if "word_wrap" in ddata:
                    prefs.display.word_wrap = bool(ddata["word_wrap"])
                if "compact_mode" in ddata:
                    prefs.display.compact_mode = bool(ddata["compact_mode"])
                if "vim_mode" in ddata:
                    prefs.display.vim_mode = bool(ddata["vim_mode"])
                if "streaming_enabled" in ddata:
                    prefs.display.streaming_enabled = bool(ddata["streaming_enabled"])
                if "multiline_default" in ddata:
                    prefs.display.multiline_default = bool(ddata["multiline_default"])
                if "show_token_usage" in ddata:
                    prefs.display.show_token_usage = bool(ddata["show_token_usage"])
                if "context_window_size" in ddata:
                    prefs.display.context_window_size = int(
                        ddata["context_window_size"] or 0
                    )
            if isinstance(data.get("model"), dict):
                mdata = data["model"]
                if "preferred" in mdata:
                    prefs.preferred_model = str(mdata["preferred"] or "")
            if isinstance(data.get("theme"), dict):
                tdata = data["theme"]
                if "name" in tdata:
                    prefs.theme_name = str(tdata["name"] or "dark")
            if isinstance(data.get("sidebar"), dict):
                sdata = data["sidebar"]
                if "session_sort" in sdata:
                    val = str(sdata["session_sort"] or "date")
                    if val in ("date", "name", "project"):
                        prefs.session_sort = val
            if isinstance(data.get("autosave"), dict):
                adata = data["autosave"]
                if "enabled" in adata:
                    prefs.autosave.enabled = bool(adata["enabled"])
                if "interval" in adata:
                    prefs.autosave.interval = max(30, int(adata["interval"]))
            # Load user-defined custom themes into the module-level dicts
            if isinstance(data.get("custom_themes"), dict):
                _load_custom_themes(data["custom_themes"])
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
            "error_text",
            "error_border",
            "note_text",
            "note_border",
            "timestamp",
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


def save_theme_name(name: str, path: Path | None = None) -> None:
    """Persist the active theme name to the preferences file.

    Surgically updates only the theme/name value, preserving the rest of the
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

        value = f'"{name}"'
        if re.search(r"^\s+name:", text, re.MULTILINE):
            # theme/name key exists — update it
            text = re.sub(
                r"^(\s+name:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^theme:", text, re.MULTILINE):
            # theme section exists but no name key
            text = re.sub(
                r"^(theme:.*)$",
                f"\\1\n  name: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No theme section at all — append it
            text = text.rstrip() + f"\n\ntheme:\n  name: {value}\n"

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


def save_word_wrap(enabled: bool, path: Path | None = None) -> None:
    """Persist the word_wrap display preference to the preferences file.

    Surgically updates only the word_wrap value, preserving the rest of the
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
        if re.search(r"^\s+word_wrap:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+word_wrap:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no word_wrap key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  word_wrap: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  word_wrap: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_compact_mode(enabled: bool, path: Path | None = None) -> None:
    """Persist the compact_mode display preference to the preferences file.

    Surgically updates only the compact_mode value, preserving the rest of the
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
        if re.search(r"^\s+compact_mode:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+compact_mode:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no compact_mode key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  compact_mode: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  compact_mode: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_vim_mode(enabled: bool, path: Path | None = None) -> None:
    """Persist the vim_mode display preference to the preferences file.

    Surgically updates only the vim_mode value, preserving the rest of the
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
        if re.search(r"^\s+vim_mode:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+vim_mode:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no vim_mode key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  vim_mode: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  vim_mode: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_multiline_default(enabled: bool, path: Path | None = None) -> None:
    """Persist the multiline_default display preference to the preferences file.

    Surgically updates only the multiline_default value, preserving the rest of the
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
        if re.search(r"^\s+multiline_default:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+multiline_default:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no multiline_default key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  multiline_default: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  multiline_default: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_streaming_enabled(enabled: bool, path: Path | None = None) -> None:
    """Persist the streaming_enabled display preference to the preferences file.

    Surgically updates only the streaming_enabled value, preserving the rest of the
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
        if re.search(r"^\s+streaming_enabled:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+streaming_enabled:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no streaming_enabled key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  streaming_enabled: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  streaming_enabled: {value}\n"

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


def save_notification_enabled(enabled: bool, path: Path | None = None) -> None:
    """Persist the notification enabled preference to the preferences file.

    Surgically updates only the enabled value under the notifications section,
    preserving the rest of the file (including user comments) as-is.
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
        if re.search(r"^\s+enabled:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+enabled:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^notifications:", text, re.MULTILINE):
            # notifications section exists but no enabled key
            text = re.sub(
                r"^(notifications:.*)$",
                f"\\1\n  enabled: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No notifications section at all — append it
            text = text.rstrip() + f"\n\nnotifications:\n  enabled: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_notification_min_seconds(seconds: float, path: Path | None = None) -> None:
    """Persist the notification min_seconds preference to the preferences file.

    Surgically updates only the min_seconds value under the notifications section,
    preserving the rest of the file (including user comments) as-is.
    """
    import re

    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        value = f"{seconds:.1f}"
        if re.search(r"^\s+min_seconds:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+min_seconds:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^notifications:", text, re.MULTILINE):
            # notifications section exists but no min_seconds key
            text = re.sub(
                r"^(notifications:.*)$",
                f"\\1\n  min_seconds: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No notifications section at all — append it
            text = text.rstrip() + f"\n\nnotifications:\n  min_seconds: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_notification_title_flash(enabled: bool, path: Path | None = None) -> None:
    """Persist the notification title_flash preference to the preferences file.

    Surgically updates only the title_flash value under the notifications section,
    preserving the rest of the file (including user comments) as-is.
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
        if re.search(r"^\s+title_flash:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+title_flash:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^notifications:", text, re.MULTILINE):
            # notifications section exists but no title_flash key
            text = re.sub(
                r"^(notifications:.*)$",
                f"\\1\n  title_flash: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No notifications section at all — append it
            text = text.rstrip() + f"\n\nnotifications:\n  title_flash: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_session_sort(sort_mode: str, path: Path | None = None) -> None:
    """Persist the session sort preference to the preferences file.

    Surgically updates only the session_sort value, preserving the rest of the
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

        value = f'"{sort_mode}"'
        if re.search(r"^\s+session_sort:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+session_sort:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^sidebar:", text, re.MULTILINE):
            # sidebar section exists but no session_sort key
            text = re.sub(
                r"^(sidebar:.*)$",
                f"\\1\n  session_sort: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No sidebar section at all — append it
            text = text.rstrip() + f"\n\nsidebar:\n  session_sort: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_autosave_enabled(enabled: bool, path: Path | None = None) -> None:
    """Persist the autosave enabled preference to the preferences file.

    Surgically updates the enabled value under the autosave section,
    preserving the rest of the file (including user comments) as-is.
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
        # The autosave section has its own 'enabled:' key.  Since
        # notifications also has 'enabled:', we target the *last* occurrence
        # which belongs to the autosave section (it appears after sidebar).
        matches = list(re.finditer(r"^(\s+enabled:).*$", text, re.MULTILINE))
        if len(matches) >= 2:
            # Replace the last match (autosave section)
            m = matches[-1]
            text = text[: m.start()] + f"{m.group(1)} {value}" + text[m.end() :]
        elif re.search(r"^autosave:", text, re.MULTILINE):
            text = re.sub(
                r"^(autosave:.*)$",
                f"\\1\n  enabled: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            text = text.rstrip() + f"\n\nautosave:\n  enabled: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_autosave_interval(seconds: int, path: Path | None = None) -> None:
    """Persist the autosave interval preference to the preferences file.

    Surgically updates the interval value under the autosave section,
    preserving the rest of the file (including user comments) as-is.
    """
    import re

    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        value = str(max(30, seconds))
        if re.search(r"^\s+interval:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+interval:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^autosave:", text, re.MULTILINE):
            text = re.sub(
                r"^(autosave:.*)$",
                f"\\1\n  interval: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            text = text.rstrip() + f"\n\nautosave:\n  interval: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_show_token_usage(enabled: bool, path: Path | None = None) -> None:
    """Persist the show_token_usage display preference to the preferences file.

    Surgically updates only the show_token_usage value, preserving the rest of
    the file (including user comments) as-is.
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
        if re.search(r"^\s+show_token_usage:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+show_token_usage:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  show_token_usage: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            text = text.rstrip() + f"\n\ndisplay:\n  show_token_usage: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_context_window_size(size: int, path: Path | None = None) -> None:
    """Persist the context_window_size display preference to the preferences file.

    Surgically updates only the context_window_size value, preserving the rest
    of the file (including user comments) as-is.  A value of 0 means
    auto-detect from model.
    """
    import re

    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        value = str(max(0, size))
        if re.search(r"^\s+context_window_size:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+context_window_size:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  context_window_size: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            text = text.rstrip() + f"\n\ndisplay:\n  context_window_size: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_fold_threshold(threshold: int, path: Path | None = None) -> None:
    """Persist the fold_threshold display preference to the preferences file.

    Surgically updates only the fold_threshold value, preserving the rest of
    the file (including user comments) as-is.  A value of 0 means auto-fold
    is disabled.
    """
    import re

    path = path or PREFS_PATH
    try:
        if path.exists():
            text = path.read_text()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _DEFAULT_YAML

        value = str(max(0, threshold))
        if re.search(r"^\s+fold_threshold:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+fold_threshold:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  fold_threshold: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            text = text.rstrip() + f"\n\ndisplay:\n  fold_threshold: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_editor_auto_send(enabled: bool, path: Path | None = None) -> None:
    """Persist the editor_auto_send display preference to the preferences file.

    Surgically updates only the editor_auto_send value, preserving the rest of the
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
        if re.search(r"^\s+editor_auto_send:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+editor_auto_send:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no editor_auto_send key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  editor_auto_send: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  editor_auto_send: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence


def save_show_suggestions(enabled: bool, path: Path | None = None) -> None:
    """Persist the show_suggestions display preference to the preferences file.

    Surgically updates only the show_suggestions value, preserving the rest of the
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
        if re.search(r"^\s+show_suggestions:", text, re.MULTILINE):
            text = re.sub(
                r"^(\s+show_suggestions:).*$",
                f"\\1 {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"^display:", text, re.MULTILINE):
            # display section exists but no show_suggestions key
            text = re.sub(
                r"^(display:.*)$",
                f"\\1\n  show_suggestions: {value}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No display section at all — append it
            text = text.rstrip() + f"\n\ndisplay:\n  show_suggestions: {value}\n"

        path.write_text(text)
    except Exception:
        pass  # Best-effort persistence
