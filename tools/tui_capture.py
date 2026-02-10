"""Capture TUI screenshots as PNG/SVG images for analysis and showcase.

Uses textual-capture (https://github.com/ramparte/textual-capture) for the
core headless capture, adding AmplifierTuiApp-specific mock content injection.

Usage:
    # Capture empty app state (no backend needed)
    python tools/tui_capture.py

    # Capture with mock content injected
    python tools/tui_capture.py --mock-chat

    # Custom output path and terminal size
    python tools/tui_capture.py -o /tmp/capture.png --width 120 --height 50

    # Generate full showcase gallery (SVGs only)
    python tools/tui_capture.py --showcase
    python tools/tui_capture.py --showcase --outdir screenshots
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Mock content injection
# ---------------------------------------------------------------------------


async def _inject_mock_content(app, pilot):
    """Inject mock chat messages to test rendering of various content types.

    Uses the ACTUAL widget types from the TUI app (UserMessage,
    AssistantMessage, Collapsible) so the screenshot reflects real
    rendering, not a simulation.
    """
    from textual.containers import ScrollableContainer
    from textual.widgets import Collapsible, Static

    from amplifier_tui.app import AssistantMessage, UserMessage

    # Clear welcome screen
    for w in app.query(".welcome-screen"):
        w.remove()

    chat_view = app.query_one("#chat-view", ScrollableContainer)

    # 1. User message
    chat_view.mount(UserMessage("How do I set up a Python virtual environment?"))
    await pilot.pause(delay=0.1)

    # 2. Thinking block (collapsible, same as _add_thinking_block)
    thinking_text = (
        "The user is asking about Python virtual environments. "
        "I should cover venv, the standard approach, and mention "
        "that uv is a faster modern alternative. Let me also include "
        "the activation command for different shells."
    )
    thinking = Collapsible(
        Static(thinking_text, classes="thinking-text"),
        title="Thinking: The user is asking about Python virtual environments...",
        collapsed=True,
        classes="thinking-block",
    )
    chat_view.mount(thinking)
    await pilot.pause(delay=0.1)

    # 3. Tool use block (collapsible, same as _add_tool_use)
    tool_detail = "Input:\npython3 -m venv .venv && source .venv/bin/activate"
    tool = Collapsible(
        Static(tool_detail, classes="tool-detail"),
        title="Tool: bash",
        collapsed=True,
    )
    tool.add_class("tool-use")
    chat_view.mount(tool)
    await pilot.pause(delay=0.1)

    # 4. Assistant response (markdown rendered)
    assistant_md = (
        "## Virtual Environments\n\n"
        "Create one with the built-in `venv` module:\n\n"
        "```bash\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate\n"
        "```\n\n"
        "Your prompt will show `(.venv)` when active. "
        "Install packages normally with `pip install`.\n\n"
        "**Tip:** Use `uv` for faster package management:\n"
        "```bash\n"
        "uv venv .venv\n"
        "uv pip install requests\n"
        "```"
    )
    chat_view.mount(AssistantMessage(assistant_md))
    await pilot.pause(delay=0.1)

    # 5. Second user message (to test multi-turn)
    chat_view.mount(UserMessage("What about conda?"))
    await pilot.pause(delay=0.1)

    # 6. Another thinking block (expanded this time to test both states)
    thinking2 = Collapsible(
        Static(
            "Conda is a different ecosystem. I should compare it with venv/uv.",
            classes="thinking-text",
        ),
        title="Thinking: Conda is a different ecosystem...",
        collapsed=False,  # Expanded to test rendering
        classes="thinking-block",
    )
    chat_view.mount(thinking2)
    await pilot.pause(delay=0.1)

    # 7. Second assistant response
    chat_view.mount(
        AssistantMessage(
            "**Conda** creates isolated environments with their own Python:\n\n"
            "```bash\nconda create -n myenv python=3.11\nconda activate myenv\n```\n\n"
            "Use conda when you need non-Python dependencies (C libraries, CUDA)."
        )
    )

    # Let rendering fully settle
    await pilot.pause(delay=0.5)


# ---------------------------------------------------------------------------
# Theme switching helper
# ---------------------------------------------------------------------------


def _apply_theme(app, theme_name: str) -> None:
    """Apply a named theme to the app (both Textual base and inline colors).

    This mirrors what AmplifierTuiApp._preview_theme() does, but without
    adding system messages to the chat.
    """
    from amplifier_tui.preferences import THEMES
    from amplifier_tui.theme import TEXTUAL_THEMES

    # Apply inline color overrides from THEMES dict
    theme_colors = THEMES.get(theme_name)
    if theme_colors:
        for key, value in theme_colors.items():
            if hasattr(app._prefs.colors, key):
                setattr(app._prefs.colors, key, value)

    # Switch Textual base theme
    textual_theme = TEXTUAL_THEMES.get(theme_name)
    if textual_theme:
        app.theme = textual_theme.name

    # Re-style all existing widgets with new colors
    try:
        app._apply_theme_to_all_widgets()
    except Exception:
        pass  # widgets may not exist yet during setup


# ---------------------------------------------------------------------------
# Showcase capture scenarios
# ---------------------------------------------------------------------------

# Themes to include in the gallery
SHOWCASE_THEMES = ["dark", "catppuccin", "nord", "dracula", "monokai", "gruvbox"]


async def _setup_themed_chat(theme_name: str):
    """Return a setup callback that injects mock content then switches theme."""

    async def setup(app, pilot):
        await _inject_mock_content(app, pilot)
        _apply_theme(app, theme_name)
        await pilot.pause(delay=0.3)

    return setup


async def _setup_focus_mode(app, pilot):
    """Inject mock content then enable focus mode (hides chrome)."""
    await _inject_mock_content(app, pilot)
    app._set_focus_mode(True)
    await pilot.pause(delay=0.3)


async def _setup_shortcuts_overlay(app, pilot):
    """Push the ShortcutOverlay screen onto the stack."""
    from amplifier_tui.widgets import ShortcutOverlay

    app.push_screen(ShortcutOverlay())
    await pilot.pause(delay=0.5)


async def capture_showcase(outdir: str = "screenshots") -> list[str]:
    """Generate a full gallery of SVG screenshots for different app states.

    Produces:
      - main-chat.svg          (default dark theme)
      - theme-<name>.svg       (one per SHOWCASE_THEMES)
      - focus-mode.svg         (chrome hidden)
      - shortcuts.svg          (F1 overlay)

    Returns list of paths to generated SVGs.
    """
    from textual_capture import capture_svg

    from amplifier_tui.app import AmplifierTuiApp

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    WIDTH, HEIGHT = 140, 45
    OVERLAY_HEIGHT = 50

    scenarios: list[tuple[str, int, int, object]] = []

    # 1. Main chat (dark theme - default)
    scenarios.append(("main-chat", WIDTH, HEIGHT, _inject_mock_content))

    # 2. Theme gallery — use default-arg trick to bind each theme name
    for theme in SHOWCASE_THEMES:

        def _make_theme_setup(t=theme):
            async def setup(app, pilot):
                await _inject_mock_content(app, pilot)
                _apply_theme(app, t)
                await pilot.pause(delay=0.3)

            return setup

        scenarios.append((f"theme-{theme}", WIDTH, HEIGHT, _make_theme_setup()))

    # 3. Focus mode
    scenarios.append(("focus-mode", WIDTH, HEIGHT, _setup_focus_mode))

    # 4. Shortcuts overlay
    scenarios.append(("shortcuts", WIDTH, OVERLAY_HEIGHT, _setup_shortcuts_overlay))

    # Run each scenario
    for name, w, h, setup in scenarios:
        svg_path = out / f"{name}.svg"
        print(f"Capturing {name} ({w}x{h})...", end=" ", flush=True)
        try:
            svg_string = await capture_svg(
                AmplifierTuiApp(),
                size=(w, h),
                title="Amplifier TUI",
                setup=setup,
            )
            svg_path.write_text(svg_string, encoding="utf-8")
            size_kb = svg_path.stat().st_size / 1024
            print(f"OK ({size_kb:.0f} KB)")
            generated.append(str(svg_path))
        except Exception as exc:
            print(f"FAILED: {exc}")

    print(f"\nGenerated {len(generated)}/{len(scenarios)} screenshots in {out}/")
    return generated


# ---------------------------------------------------------------------------
# Single-shot capture (original)
# ---------------------------------------------------------------------------


async def capture_screenshot(
    output_path: str = "tui_capture.png",
    width: int = 120,
    height: int = 50,
    mock_chat: bool = False,
    svg_too: bool = False,
) -> str:
    """Capture the TUI as a PNG screenshot.

    Uses textual-capture for the core capture logic, with an optional
    setup callback for injecting mock chat content.

    Args:
        output_path: Where to write the PNG.
        width: Terminal columns.
        height: Terminal rows.
        mock_chat: If True, inject sample chat messages to test rendering.
        svg_too: Also save the intermediate SVG alongside the PNG.

    Returns:
        Path to the saved PNG.
    """
    from textual_capture import capture_png, capture_svg

    from amplifier_tui.app import AmplifierTuiApp

    app = AmplifierTuiApp()

    # Build setup callback if mock content requested
    setup = _inject_mock_content if mock_chat else None

    output = Path(output_path)

    # Capture PNG
    await capture_png(
        app,
        output,
        size=(width, height),
        title="Amplifier TUI",
        setup=setup,
    )
    print(f"PNG saved: {output}")
    print(f"Dimensions: {width}x{height} cells, {width * 16}px wide")

    # Optionally save SVG alongside
    if svg_too:
        svg_path = output.with_suffix(".svg")
        svg_string = await capture_svg(
            AmplifierTuiApp(),
            size=(width, height),
            title="Amplifier TUI",
            setup=setup,
        )
        svg_path.write_text(svg_string, encoding="utf-8")
        print(f"SVG saved: {svg_path}")

    return str(output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Capture TUI screenshot as PNG")
    parser.add_argument(
        "-o",
        "--output",
        default="tui_capture.png",
        help="Output PNG path (default: tui_capture.png)",
    )
    parser.add_argument("--width", type=int, default=120, help="Terminal columns")
    parser.add_argument("--height", type=int, default=50, help="Terminal rows")
    parser.add_argument(
        "--mock-chat",
        action="store_true",
        help="Inject mock chat content for rendering tests",
    )
    parser.add_argument(
        "--svg",
        action="store_true",
        help="Also save intermediate SVG",
    )
    parser.add_argument(
        "--showcase",
        action="store_true",
        help="Generate full SVG showcase gallery (themes, focus mode, shortcuts)",
    )
    parser.add_argument(
        "--outdir",
        default="screenshots",
        help="Output directory for --showcase (default: screenshots/)",
    )

    args = parser.parse_args()

    if args.showcase:
        asyncio.run(capture_showcase(outdir=args.outdir))
    else:
        asyncio.run(
            capture_screenshot(
                output_path=args.output,
                width=args.width,
                height=args.height,
                mock_chat=args.mock_chat,
                svg_too=args.svg,
            )
        )


if __name__ == "__main__":
    main()
