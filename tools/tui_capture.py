"""Capture TUI screenshots as PNG images for analysis.

Uses textual-capture (https://github.com/ramparte/textual-capture) for the
core headless capture, adding AmplifierTuiApp-specific mock content injection.

Usage:
    # Capture empty app state (no backend needed)
    python tools/tui_capture.py

    # Capture with mock content injected
    python tools/tui_capture.py --mock-chat

    # Custom output path and terminal size
    python tools/tui_capture.py -o /tmp/capture.png --width 120 --height 50
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


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

    args = parser.parse_args()
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
