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
        name="chic-dark",
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
        name="chic-light",
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
        name="chic-solarized",
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
        name="chic-monokai",
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
        name="chic-high-contrast",
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
        name="chic-nord",
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
        name="chic-dracula",
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
}

# Backward-compat alias: the default theme object used before multi-theme support.
CHIC_THEME = TEXTUAL_THEMES["dark"]
