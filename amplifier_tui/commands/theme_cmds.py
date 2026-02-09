"""Theme and color commands."""

from __future__ import annotations

from ..preferences import (
    COLOR_NAMES,
    ColorPreferences,
    THEMES,
    THEME_DESCRIPTIONS,
    resolve_color,
    save_colors,
    save_theme_name,
)
from ..theme import TEXTUAL_THEMES


class ThemeCommandsMixin:
    """Theme and color commands."""

    def _cmd_theme(self, text: str) -> None:
        """Switch color theme or show current/available themes.

        Sub-commands:
          /theme              — list available themes
          /theme <name>       — apply and persist a theme
          /theme preview      — show color swatches for all themes
          /theme preview <n>  — temporarily preview a theme (live)
          /theme revert       — restore the saved theme after a preview
        """
        parts = text.strip().split(None, 1)

        if len(parts) < 2:
            # No argument: list themes with descriptions and active marker
            current = self._prefs.theme_name
            previewing = self._previewing_theme
            lines = ["Available themes:"]
            for name, desc in THEME_DESCRIPTIONS.items():
                if previewing and name == previewing:
                    marker = " >"
                elif name == current:
                    marker = " *"
                else:
                    marker = "  "
                lines.append(f"{marker} {name}: {desc}")
            lines.append("")
            lines.append(
                "Use: /theme <name>  |  /theme preview <name>  |  /theme revert"
            )
            if previewing:
                lines.append(f"  (previewing {previewing}, saved: {current})")
            self._add_system_message("\n".join(lines))
            return

        arg = parts[1].strip().lower()

        # /theme preview  OR  /theme preview <name>
        if arg == "preview":
            self._cmd_theme_preview()
            return
        if arg.startswith("preview "):
            preview_name = arg[8:].strip()
            self._preview_theme(preview_name)
            return

        # /theme revert — restore the saved theme after a preview
        if arg == "revert":
            self._revert_theme_preview()
            return

        # /theme <name> — apply and persist
        if not self._prefs.apply_theme(arg):
            available = ", ".join(THEMES)
            self._add_system_message(f"Unknown theme: {arg}\nAvailable: {available}")
            return

        self._prefs.theme_name = arg
        self._previewing_theme = None  # clear any active preview
        save_colors(self._prefs.colors)
        save_theme_name(arg)

        # Switch the Textual base theme (background, surface, panel, etc.)
        textual_theme = TEXTUAL_THEMES.get(arg)
        if textual_theme:
            self.theme = textual_theme.name

        self._apply_theme_to_all_widgets()
        desc = THEME_DESCRIPTIONS.get(arg, "")
        self._add_system_message(f"Theme: {arg} — {desc}" if desc else f"Theme: {arg}")

    def _cmd_theme_preview(self) -> None:
        """Show all themes with color swatches."""
        current = self._prefs.theme_name
        lines = ["Theme Preview:\n"]
        for name, colors in THEMES.items():
            active = " (active)" if name == current else ""
            desc = THEME_DESCRIPTIONS.get(name, "")
            # Build swatches for the key color roles
            user_sw = f"[{colors['user_text']}]\u2588\u2588\u2588\u2588[/]"
            asst_sw = f"[{colors['assistant_text']}]\u2588\u2588\u2588\u2588[/]"
            sys_sw = f"[{colors['system_text']}]\u2588\u2588\u2588\u2588[/]"
            border_sw = f"[{colors['user_border']}]\u2588\u2588[/]"
            think_sw = f"[{colors['thinking_border']}]\u2588\u2588[/]"
            lines.append(
                f"  {name:<16}{active:>9}  "
                f"{user_sw} {asst_sw} {sys_sw} {border_sw} {think_sw}"
                f"  {desc}"
            )
        lines.append("")
        lines.append("  Swatches: user  assistant  system  border  thinking")
        lines.append("  Apply: /theme <name>  |  Try: /theme preview <name>")
        self._add_system_message("\n".join(lines))

    def _cmd_colors(self, text: str) -> None:
        """View, change, or reset individual color preferences."""
        from dataclasses import fields

        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg:
            # Show current color settings with colored swatches
            c = self._prefs.colors

            def _swatch(hex_color: str) -> str:
                """Return a Rich-markup colored swatch block."""
                return f"[{hex_color}]\u2588\u2588\u2588\u2588[/]"

            lines = [
                "Text Colors:",
                "",
                f"  user        {c.user_text:<10} {_swatch(c.user_text)}",
                f"  assistant   {c.assistant_text:<10} {_swatch(c.assistant_text)}",
                f"  system      {c.system_text:<10} {_swatch(c.system_text)}",
                f"  error       {c.error_text:<10} {_swatch(c.error_text)}",
                f"  tool        {c.tool_text:<10} {_swatch(c.tool_text)}",
                f"  thinking    {c.thinking_text:<10} {_swatch(c.thinking_text)}",
                f"  note        {c.note_text:<10} {_swatch(c.note_text)}",
                f"  timestamp   {c.timestamp:<10} {_swatch(c.timestamp)}",
                "",
                "All keys:",
                f"  user_text           {c.user_text:<10} {_swatch(c.user_text)}",
                f"  user_border         {c.user_border:<10} {_swatch(c.user_border)}",
                f"  assistant_text      {c.assistant_text:<10} {_swatch(c.assistant_text)}",
                f"  assistant_border    {c.assistant_border:<10} {_swatch(c.assistant_border)}",
                f"  thinking_text       {c.thinking_text:<10} {_swatch(c.thinking_text)}",
                f"  thinking_border     {c.thinking_border:<10} {_swatch(c.thinking_border)}",
                f"  thinking_background {c.thinking_background:<10} {_swatch(c.thinking_background)}",
                f"  tool_text           {c.tool_text:<10} {_swatch(c.tool_text)}",
                f"  tool_border         {c.tool_border:<10} {_swatch(c.tool_border)}",
                f"  tool_background     {c.tool_background:<10} {_swatch(c.tool_background)}",
                f"  system_text         {c.system_text:<10} {_swatch(c.system_text)}",
                f"  system_border       {c.system_border:<10} {_swatch(c.system_border)}",
                f"  error_text          {c.error_text:<10} {_swatch(c.error_text)}",
                f"  error_border        {c.error_border:<10} {_swatch(c.error_border)}",
                f"  note_text           {c.note_text:<10} {_swatch(c.note_text)}",
                f"  note_border         {c.note_border:<10} {_swatch(c.note_border)}",
                f"  timestamp           {c.timestamp:<10} {_swatch(c.timestamp)}",
                f"  status_bar          {c.status_bar:<10} {_swatch(c.status_bar)}",
                "",
                "Change:  /colors <role> <color>  e.g. /colors user white",
                "         /colors <key> <color>   e.g. /colors user_border #ff8800",
                "Reset:   /colors reset",
                "Presets: /colors presets          Show available color presets",
                "         /colors use <preset>     Apply a preset",
                "Roles:   user, assistant, system, error, tool, thinking, note, timestamp",
                "Colors:  white, gray, cyan, red, green, blue, yellow, magenta, orange, dim, #RRGGBB",
            ]
            self._add_system_message("\n".join(lines))
            return

        if arg == "reset":
            self._prefs.colors = ColorPreferences()
            save_colors(self._prefs.colors)
            self._apply_theme_to_all_widgets()
            self._add_system_message("Colors reset to defaults.")
            return

        if arg == "presets":
            self._cmd_colors_presets()
            return

        # /colors use <preset>
        if arg.startswith("use "):
            preset_name = arg[4:].strip()
            self._cmd_colors_use_preset(preset_name)
            return

        # Parse: key value
        tokens = arg.split(None, 1)
        if len(tokens) != 2:
            self._add_system_message(
                "Usage: /colors <role> <color>  e.g. /colors user white\n"
                "       /colors <key> <color>   e.g. /colors user_border #ff8800\n"
                "       /colors reset           Restore defaults\n"
                "       /colors presets          Show available color presets\n"
                "       /colors use <preset>     Apply a preset\n"
                "Roles: user, assistant, system, error, tool, thinking, note, timestamp\n"
                "Colors: white, gray, cyan, red, green, blue, yellow, magenta, orange, dim, #RRGGBB"
            )
            return

        key, value = tokens
        # Resolve role shortcuts (e.g. "user" -> "user_text")
        key = self._COLOR_ROLE_ALIASES.get(key, key)

        if not hasattr(self._prefs.colors, key):
            aliases = ", ".join(sorted(self._COLOR_ROLE_ALIASES.keys()))
            valid = ", ".join(f.name for f in fields(ColorPreferences))
            self._add_system_message(
                f"Unknown color key '{key}'.\n"
                f"Role shortcuts: {aliases}\n"
                f"All keys: {valid}"
            )
            return

        # Resolve color: accept named colors (white, gray, cyan...) or hex (#RRGGBB)
        resolved = resolve_color(value)
        if resolved is None:
            names = ", ".join(sorted(COLOR_NAMES.keys()))
            self._add_system_message(
                f"Unknown color '{value}'.\n"
                f"Use a color name ({names})\n"
                f"or a hex code (#RRGGBB)."
            )
            return

        setattr(self._prefs.colors, key, resolved)
        save_colors(self._prefs.colors)
        self._apply_theme_to_all_widgets()
        self._add_system_message(
            f"Set {key} to [{resolved}]\u2588\u2588\u2588\u2588[/] {resolved}"
        )

    def _cmd_colors_presets(self) -> None:
        """Show available color presets with sample swatches."""

        def _swatch(hex_color: str) -> str:
            return f"[{hex_color}]\u2588\u2588[/]"

        lines = ["Color Presets:", ""]
        for name, theme_colors in THEMES.items():
            desc = THEME_DESCRIPTIONS.get(name, "")
            user_sw = _swatch(theme_colors.get("user_text", "#ffffff"))
            asst_sw = _swatch(theme_colors.get("assistant_text", "#999999"))
            sys_sw = _swatch(theme_colors.get("system_text", "#88bbcc"))
            note_sw = _swatch(theme_colors.get("note_text", "#e0d080"))
            err_sw = _swatch(theme_colors.get("error_text", "#cc0000"))
            active = " \u2190 active" if name == self._prefs.theme_name else ""
            lines.append(
                f"  {name:<16} "
                f"{user_sw} {asst_sw} {sys_sw} {note_sw} {err_sw}"
                f"  {desc}{active}"
            )
        lines.append("")
        lines.append("  Swatches: user  assistant  system  note  error")
        lines.append("  Apply: /colors use <preset>")
        self._add_system_message("\n".join(lines))

    def _cmd_colors_use_preset(self, preset_name: str) -> None:
        """Apply a color preset (theme colors) by name."""
        if not preset_name:
            self._add_system_message(
                "Usage: /colors use <preset>\nSee available presets: /colors presets"
            )
            return

        if preset_name not in THEMES:
            available = ", ".join(sorted(THEMES.keys()))
            self._add_system_message(
                f"Unknown preset '{preset_name}'.\n"
                f"Available: {available}\n"
                f"Preview: /colors presets"
            )
            return

        self._prefs.apply_theme(preset_name)
        save_colors(self._prefs.colors)
        self._apply_theme_to_all_widgets()
        self._add_system_message(
            f"Applied color preset '{preset_name}'. "
            f"Customize further with /colors <role> <color>."
        )

    # ------------------------------------------------------------------
    # Export formatters
    # ------------------------------------------------------------------

