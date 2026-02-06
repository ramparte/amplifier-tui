"""Theme definitions for Amplifier TUI (adapted from Claude Chic)."""

from textual.theme import Theme

# Amplifier TUI theme - orange accent, dark background
CHIC_THEME = Theme(
    name="chic",
    primary="#cc7700",        # Orange for user messages
    secondary="#5599dd",      # Blue for assistant messages
    accent="#445566",         # Gray-blue for tools
    background="black",
    surface="#111111",
    panel="#555555",          # Borders and subtle UI
    success="#5599dd",        # Same as secondary
    warning="#aaaa00",        # Yellow for warnings
    error="#cc3333",          # Red for errors
    dark=True,
)
