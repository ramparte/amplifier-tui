"""Theme definitions for Amplifier TUI.

Each color theme has a corresponding Textual Theme that controls the base UI
colors ($background, $surface, $panel, $primary, $secondary, etc.) used by
styles.tcss.  Chat-message inline styles (user_text, assistant_border, etc.)
are handled separately via ColorPreferences in preferences.py.
"""

from textual.theme import Theme

# Textual Theme objects for each built-in preset.
# Keys match the theme names in preferences.THEMES / THEME_DESCRIPTIONS.
TEXTUAL_THEMES: dict[str, Theme] = {
    "dark": Theme(
        name="tui-dark",
        primary="#cc7700",
        secondary="#5599dd",
        accent="#445566",
        background="black",
        surface="#111111",
        panel="#555555",
        success="#5599dd",
        warning="#aaaa00",
        error="#cc3333",
        dark=True,
    ),
    "light": Theme(
        name="tui-light",
        primary="#cc6600",
        secondary="#4488aa",
        accent="#667788",
        background="#fafafa",
        surface="#f0f0f0",
        panel="#cccccc",
        success="#338855",
        warning="#aa8800",
        error="#cc3333",
        dark=False,
    ),
    "solarized": Theme(
        name="tui-solarized",
        primary="#b58900",
        secondary="#268bd2",
        accent="#6c71c4",
        background="#002b36",
        surface="#073642",
        panel="#586e75",
        success="#859900",
        warning="#cb4b16",
        error="#dc322f",
        dark=True,
    ),
    "monokai": Theme(
        name="tui-monokai",
        primary="#fd971f",
        secondary="#66d9ef",
        accent="#ae81ff",
        background="#272822",
        surface="#2d2a2e",
        panel="#3e3d32",
        success="#a6e22e",
        warning="#e6db74",
        error="#f92672",
        dark=True,
    ),
    "high-contrast": Theme(
        name="tui-high-contrast",
        primary="#ffff00",
        secondary="#00ff00",
        accent="#00ffff",
        background="#000000",
        surface="#0a0a0a",
        panel="#333333",
        success="#00ff00",
        warning="#ffff00",
        error="#ff0000",
        dark=True,
    ),
    "nord": Theme(
        name="tui-nord",
        primary="#ebcb8b",
        secondary="#88c0d0",
        accent="#b48ead",
        background="#2e3440",
        surface="#3b4252",
        panel="#4c566a",
        success="#a3be8c",
        warning="#ebcb8b",
        error="#bf616a",
        dark=True,
    ),
    "dracula": Theme(
        name="tui-dracula",
        primary="#ffb86c",
        secondary="#8be9fd",
        accent="#bd93f9",
        background="#282a36",
        surface="#44475a",
        panel="#6272a4",
        success="#50fa7b",
        warning="#f1fa8c",
        error="#ff5555",
        dark=True,
    ),
    "gruvbox": Theme(
        name="tui-gruvbox",
        primary="#d65d0e",
        secondary="#689d6a",
        accent="#b16286",
        background="#282828",
        surface="#3c3836",
        panel="#504945",
        success="#98971a",
        warning="#d79921",
        error="#cc241d",
        dark=True,
    ),
    "catppuccin": Theme(
        name="tui-catppuccin",
        primary="#fab387",
        secondary="#89b4fa",
        accent="#cba6f7",
        background="#1e1e2e",
        surface="#313244",
        panel="#45475a",
        success="#a6e3a1",
        warning="#f9e2af",
        error="#f38ba8",
        dark=True,
    ),
    "midnight": Theme(
        name="tui-midnight",
        primary="#536dfe",
        secondary="#64b5f6",
        accent="#7c4dff",
        background="#0a0e27",
        surface="#121640",
        panel="#1a237e",
        success="#69f0ae",
        warning="#ffd740",
        error="#ff5252",
        dark=True,
    ),
    "solarized-light": Theme(
        name="tui-solarized-light",
        primary="#b58900",
        secondary="#268bd2",
        accent="#6c71c4",
        background="#fdf6e3",
        surface="#eee8d5",
        panel="#93a1a1",
        success="#859900",
        warning="#cb4b16",
        error="#dc322f",
        dark=False,
    ),
}

# Backward-compat alias: the default theme object used before multi-theme support.
DEFAULT_THEME = TEXTUAL_THEMES["dark"]


def make_custom_textual_theme(name: str, base: str = "dark") -> Theme:
    """Create a Textual Theme for a custom color theme, inheriting from a built-in.

    The custom theme gets a unique ``tui-<name>`` identifier and copies all
    design tokens (primary, secondary, accent, background, etc.) from *base*.
    """
    source = TEXTUAL_THEMES.get(base, TEXTUAL_THEMES["dark"])
    return Theme(
        name=f"tui-{name}",
        primary=source.primary,
        secondary=source.secondary,
        accent=source.accent,
        background=source.background,
        surface=source.surface,
        panel=source.panel,
        success=source.success,
        warning=source.warning,
        error=source.error,
        dark=source.dark,
    )
