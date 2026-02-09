#!/usr/bin/env python3
"""Interactive test runner for amplifier-tui slash commands.

Uses Textual's Pilot to drive the app headlessly, type slash commands,
capture SVGs after each command, and produce a structured test report.

Usage:
    python tools/interactive_test_runner.py [--batch N] [--output-dir DIR]
    python tools/interactive_test_runner.py --batch 1   # Core & display
    python tools/interactive_test_runner.py --batch 2   # Content & files
    python tools/interactive_test_runner.py --batch 3   # Theme, tokens, tabs
    python tools/interactive_test_runner.py --batch 4   # Keybindings
    python tools/interactive_test_runner.py --batch all  # Everything
"""

import argparse
import asyncio
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Ensure we can import the app
sys.path.insert(0, str(Path(__file__).parent.parent))

from amplifier_tui.app import AmplifierChicApp

# Lazy imports for tools
svg_parser = None


def get_svg_parser():
    global svg_parser
    if svg_parser is None:
        sys.path.insert(0, str(Path(__file__).parent))
        import svg_parser as _sp

        svg_parser = _sp
    return svg_parser


# ---------------------------------------------------------------------------
# Test definitions: each is (test_id, command_or_action, description, checks)
# checks is a list of (check_name, check_fn) where check_fn(app, svg_data) -> (pass, detail)
# ---------------------------------------------------------------------------


def check_system_message_appeared(app, svg_data):
    """Check that at least one SystemMessage widget appeared."""
    msgs = app.query("SystemMessage")
    if len(msgs) > 0:
        return True, f"{len(msgs)} SystemMessage(s) rendered"
    return False, "No SystemMessage widgets found in DOM"


def check_no_error_message(app, svg_data):
    """Check that no ErrorMessage widgets appeared."""
    errs = app.query("ErrorMessage")
    if len(errs) == 0:
        return True, "No errors"
    texts = [e.renderable if hasattr(e, "renderable") else str(e) for e in errs]
    return False, f"{len(errs)} ErrorMessage(s): {texts[:3]}"


def check_no_crash(app, svg_data):
    """Basic check that the app is still responsive."""
    try:
        _ = app.query_one("#chat-input")
        return True, "App responsive, chat-input found"
    except Exception as e:
        return False, f"App unresponsive: {e}"


def check_svg_has_content(app, svg_data):
    """Check that the SVG capture has meaningful content."""
    if svg_data and svg_data.get("lines"):
        n = len(svg_data["lines"])
        if n > 5:
            return True, f"SVG has {n} text lines"
        return False, f"SVG has only {n} text lines (too few)"
    return False, "SVG data empty or missing lines"


def check_modal_appeared(app, svg_data):
    """Check that a modal screen is showing."""
    if app.screen and app.screen.__class__.__name__ != "Screen":
        return True, f"Modal screen: {app.screen.__class__.__name__}"
    # Check if any overlay-type widget is visible
    for cls_name in ["ShortcutOverlay", "HistorySearchScreen"]:
        try:
            w = app.query(cls_name)
            if len(w) > 0:
                return True, f"Modal found: {cls_name}"
        except Exception:
            pass
    return False, "No modal screen detected"


def check_sidebar_hidden(app, svg_data):
    """Check that sidebar is not visible (focus mode)."""
    try:
        sidebar = app.query_one("#session-sidebar")
        if not sidebar.display:
            return True, "Sidebar hidden"
        if hasattr(sidebar, "styles") and sidebar.styles.display == "none":
            return True, "Sidebar display:none"
        return False, "Sidebar still visible"
    except Exception:
        return True, "No sidebar found (hidden)"


def check_sidebar_visible(app, svg_data):
    """Check that sidebar is visible."""
    try:
        sidebar = app.query_one("#session-sidebar")
        if sidebar.display:
            return True, "Sidebar visible"
        return False, "Sidebar hidden"
    except Exception:
        return False, "Sidebar not found"


# Standard checks applied to every command
STANDARD_CHECKS = [
    ("no_crash", check_no_crash),
    ("no_error", check_no_error_message),
    ("svg_content", check_svg_has_content),
]


# ---------------------------------------------------------------------------
# Test batches
# ---------------------------------------------------------------------------

# Each test: (test_id, action_type, action_data, description, extra_checks)
# action_type: "command" (type + enter), "key" (press key), "sequence" (list of actions)
# extra_checks: additional checks beyond STANDARD_CHECKS

BATCH_1_CORE_DISPLAY = [
    (
        "T5.1",
        "command",
        "/help",
        "Show help - list available commands",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T2.5a",
        "command",
        "/fold",
        "Toggle message folding",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T2.5b",
        "command",
        "/unfold",
        "Unfold all messages",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T2.4",
        "command",
        "/ts",
        "Toggle timestamps",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T6.2",
        "command",
        "/compact",
        "Toggle compact mode",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T6.3",
        "command",
        "/wrap",
        "Toggle word wrap",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T6.1a",
        "command",
        "/focus",
        "Toggle focus mode",
        [("sidebar_hidden", check_sidebar_hidden)],
    ),
    (
        "T6.1b",
        "command",
        "/focus",
        "Toggle focus mode OFF (restore)",
        [("sidebar_visible", check_sidebar_visible)],
    ),
    ("T5.2", "command", "/clear", "Clear chat display", []),
    (
        "T18.1",
        "command",
        "/progress",
        "Toggle progress label detail",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T3.1a",
        "command",
        "/multiline",
        "Toggle multiline input mode",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T3.1b",
        "command",
        "/multiline",
        "Toggle multiline OFF",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T14.3a",
        "command",
        "/modes",
        "List available modes",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T2.3",
        "command",
        "/stream",
        "Toggle streaming display",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T2.6",
        "command",
        "/scroll",
        "Toggle auto-scroll",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T5.7",
        "command",
        "/info",
        "Show session info",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T6.5a",
        "command",
        "/sort date",
        "Sort sessions by date",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T6.5b",
        "command",
        "/sort name",
        "Sort sessions by name",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T13.1",
        "command",
        "/notify",
        "Show notification settings",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T13.2",
        "command",
        "/sound",
        "Show sound settings",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.2a",
        "command",
        "/stats",
        "Show session statistics",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.1a",
        "command",
        "/tokens",
        "Show token usage",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.1b",
        "command",
        "/context",
        "Show context usage bar",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T14.1",
        "command",
        "/model",
        "Show current model",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T6.4a",
        "command",
        "/search",
        "Search (no args - should show usage or results)",
        [("system_msg", check_system_message_appeared)],
    ),
]

BATCH_2_CONTENT_FILES = [
    (
        "T7.3a",
        "command",
        "/snippet list",
        "List snippets",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.3b",
        "command",
        "/snippet save test-snip Hello, this is a test snippet",
        "Save a snippet",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.3c",
        "command",
        "/snippet list",
        "List snippets (should show test-snip)",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.3d",
        "command",
        "/snippet cat test-snip",
        "Show snippet content",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.3e",
        "command",
        "/snippet search test",
        "Search snippets",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.5a",
        "command",
        "/alias list",
        "List aliases (empty at start)",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.5b",
        "command",
        "/alias h /help",
        "Create alias h -> /help",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.5c",
        "command",
        "/alias list",
        "List aliases (should show h)",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.4a",
        "command",
        "/template list",
        "List templates",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.4b",
        "command",
        "/template save greeting Hello {name}, welcome!",
        "Save template",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.4c",
        "command",
        "/template list",
        "List templates (should show greeting)",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T12.3a",
        "command",
        "/note This is a test annotation",
        "Add a note",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T12.3b",
        "command",
        "/note list",
        "List notes",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T12.4a",
        "command",
        "/ref add https://example.com",
        "Add reference",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T12.4b",
        "command",
        "/ref list",
        "List references",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T12.1a",
        "command",
        "/bookmark list",
        "List bookmarks",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T12.2a",
        "command",
        "/pin list",
        "List pins",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T8.3",
        "command",
        "/run echo hello-from-test",
        "Run shell command",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T8.4a",
        "command",
        "/git status",
        "Git status",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T8.4b",
        "command",
        "/git log",
        "Git log",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T8.4c",
        "command",
        "/git branches",
        "Git branches",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T8.5a",
        "command",
        "/diff",
        "Git diff",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T7.2a",
        "command",
        "/export",
        "Export conversation (default markdown)",
        [("system_msg", check_system_message_appeared)],
    ),
    ("T7.1a", "command", "/copy", "Copy last response (may fail with no messages)", []),
    (
        "T14.2a",
        "command",
        "/system",
        "Show system prompt info",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T14.2b",
        "command",
        "/system presets",
        "List system prompt presets",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T6.4b",
        "command",
        "/grep test",
        "Grep in conversation",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T3.6",
        "command",
        "/suggest",
        "Toggle suggestions",
        [("system_msg", check_system_message_appeared)],
    ),
]

BATCH_3_THEME_TABS = [
    (
        "T9.1a",
        "command",
        "/theme",
        "Show current theme",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.1b",
        "command",
        "/theme gruvbox",
        "Switch to gruvbox theme",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.1c",
        "command",
        "/theme catppuccin",
        "Switch to catppuccin",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.1d",
        "command",
        "/theme midnight",
        "Switch to midnight",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.1e",
        "command",
        "/theme solarized",
        "Switch to solarized",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.1f",
        "command",
        "/theme preview",
        "Preview theme colors",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.1g",
        "command",
        "/theme revert",
        "Revert theme change",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.1h",
        "command",
        "/theme dark",
        "Switch back to dark",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.2a",
        "command",
        "/colors",
        "Show color settings",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T9.2b",
        "command",
        "/colors presets",
        "List color presets",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.2b",
        "command",
        "/stats tools",
        "Tool usage stats",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.2c",
        "command",
        "/stats tokens",
        "Token analytics",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.2d",
        "command",
        "/stats time",
        "Timing analytics",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.1c",
        "command",
        "/showtokens",
        "Toggle token display",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T10.1d",
        "command",
        "/contextwindow",
        "Toggle context window display",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T11.1a",
        "command",
        "/tab list",
        "List tabs",
        [("system_msg", check_system_message_appeared)],
    ),
    ("T11.1b", "command", "/tab new", "Create new tab", []),
    (
        "T11.1c",
        "command",
        "/tab list",
        "List tabs (should show 2)",
        [("system_msg", check_system_message_appeared)],
    ),
    ("T11.1d", "command", "/tab goto 1", "Switch to tab 1", []),
    (
        "T5.4",
        "command",
        "/name Test Session Name",
        "Set session name",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T5.6a",
        "command",
        "/undo",
        "Undo last exchange",
        [("system_msg", check_system_message_appeared)],
    ),
    ("T11.3a", "command", "/split", "Enter split view", []),
    ("T11.3b", "command", "/split off", "Exit split view", []),
    (
        "T17.1a",
        "command",
        "/watch list",
        "List watched files",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T19.1",
        "command",
        "/prefs",
        "Show preferences",
        [("system_msg", check_system_message_appeared)],
    ),
    (
        "T5.3a",
        "command",
        "/sessions",
        "List sessions",
        [("system_msg", check_system_message_appeared)],
    ),
    ("T1.2", "command", "/new", "Create new session", []),
    (
        "T3.2a",
        "command",
        "/history search test",
        "Search history",
        [("system_msg", check_system_message_appeared)],
    ),
]

BATCH_4_KEYBINDINGS = [
    ("T15.1", "key", "f1", "F1 - Shortcut overlay", [("modal", check_modal_appeared)]),
    (
        "T15.1b",
        "key",
        "escape",
        "Escape - dismiss overlay",
        [("no_crash", check_no_crash)],
    ),
    ("T15.2a", "key", "ctrl+b", "Ctrl+B - Toggle sidebar", []),
    (
        "T15.2b",
        "key",
        "ctrl+b",
        "Ctrl+B - Toggle sidebar back",
        [("sidebar_visible", check_sidebar_visible)],
    ),
    ("T15.3", "key", "ctrl+p", "Ctrl+P - Command palette", []),
    (
        "T15.3b",
        "key",
        "escape",
        "Escape - dismiss palette",
        [("no_crash", check_no_crash)],
    ),
    (
        "T2.6a",
        "key",
        "ctrl+a",
        "Ctrl+A - Toggle auto-scroll",
        [("no_crash", check_no_crash)],
    ),
    # Tab creation/switching via keybindings
    ("T11.1e", "key", "ctrl+t", "Ctrl+T - New tab", [("no_crash", check_no_crash)]),
    ("T6.1c", "key", "f11", "F11 - Toggle focus mode", [("no_crash", check_no_crash)]),
    (
        "T6.1d",
        "key",
        "f11",
        "F11 - Toggle focus mode back",
        [("no_crash", check_no_crash)],
    ),
    # Ctrl+L clear
    ("T5.2b", "key", "ctrl+l", "Ctrl+L - Clear screen", [("no_crash", check_no_crash)]),
]

BATCHES = {
    "1": BATCH_1_CORE_DISPLAY,
    "2": BATCH_2_CONTENT_FILES,
    "3": BATCH_3_THEME_TABS,
    "4": BATCH_4_KEYBINDINGS,
}


# ---------------------------------------------------------------------------
# Test runner engine
# ---------------------------------------------------------------------------


class TestResult:
    def __init__(self, test_id: str, description: str, command: str):
        self.test_id = test_id
        self.description = description
        self.command = command
        self.passed = True
        self.checks: list[dict] = []
        self.error: str | None = None
        self.svg_path: str | None = None
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def add_check(self, name: str, passed: bool, detail: str):
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.passed = False

    def to_dict(self):
        return {
            "test_id": self.test_id,
            "description": self.description,
            "command": self.command,
            "passed": self.passed,
            "checks": self.checks,
            "error": self.error,
            "svg_path": self.svg_path,
            "timestamp": self.timestamp,
        }


async def inject_mock_messages(app, pilot):
    """Inject sample messages so commands that operate on messages have something to work with."""
    from amplifier_tui.app import UserMessage, AssistantMessage

    try:
        chat_view = app.query_one("#chat-view")

        # Add a few mock messages
        await chat_view.mount(UserMessage("What is the capital of France?"))
        await pilot.pause(delay=0.05)
        await chat_view.mount(AssistantMessage("The capital of France is **Paris**."))
        await pilot.pause(delay=0.05)
        await chat_view.mount(UserMessage("Tell me about Python programming."))
        await pilot.pause(delay=0.05)
        await chat_view.mount(
            AssistantMessage(
                "Python is a high-level, interpreted programming language.\n\n"
                "```python\ndef hello():\n    print('Hello, World!')\n```\n\n"
                "It's known for its clean syntax and readability."
            )
        )
        await pilot.pause(delay=0.05)
    except Exception as e:
        print(f"  [warn] Could not inject mock messages: {e}")


async def run_single_test(app, pilot, test_def, output_dir: Path) -> TestResult:
    """Run a single test and return the result."""
    test_id, action_type, action_data, description, extra_checks = test_def
    result = TestResult(test_id, description, f"{action_type}:{action_data}")

    try:
        # Execute the action
        if action_type == "command":
            # Inject text directly into ChatInput (fast, reliable)
            try:
                chat_input = app.query_one("#chat-input")
                chat_input.clear()
                chat_input.insert(action_data)
            except Exception:
                # Fallback: press each char (slower)
                try:
                    await pilot.click("#chat-input")
                    await pilot.pause(delay=0.05)
                except Exception:
                    pass
                for ch in action_data:
                    await pilot.press("space" if ch == " " else ch)

            await pilot.pause(delay=0.05)
            await pilot.press("enter")
            await pilot.pause(delay=0.3)

        elif action_type == "key":
            await pilot.press(action_data)
            await pilot.pause(delay=0.3)

        elif action_type == "sequence":
            for step_type, step_data in action_data:
                if step_type == "type":
                    try:
                        chat_input = app.query_one("#chat-input")
                        chat_input.clear()
                        chat_input.insert(step_data)
                    except Exception:
                        for ch in step_data:
                            await pilot.press("space" if ch == " " else ch)
                elif step_type == "press":
                    await pilot.press(step_data)
                elif step_type == "pause":
                    await pilot.pause(delay=float(step_data))
                elif step_type == "click":
                    await pilot.click(step_data)
                await pilot.pause(delay=0.05)
            await pilot.pause(delay=0.3)

        # Capture SVG
        svg_string = app.export_screenshot(title=f"Test {test_id}: {description}")
        svg_path = output_dir / f"{test_id.replace('.', '_')}.svg"
        svg_path.write_text(svg_string)
        result.svg_path = str(svg_path)

        # Parse SVG for analysis
        svg_data = None
        try:
            parser = get_svg_parser()
            svg_data = parser.parse_tui_svg(str(svg_path))
        except Exception as e:
            result.add_check("svg_parse", False, f"SVG parse failed: {e}")

        # Run standard checks
        for check_name, check_fn in STANDARD_CHECKS:
            try:
                passed, detail = check_fn(app, svg_data)
                result.add_check(check_name, passed, detail)
            except Exception as e:
                result.add_check(check_name, False, f"Check crashed: {e}")

        # Run extra checks
        for check_name, check_fn in extra_checks:
            try:
                passed, detail = check_fn(app, svg_data)
                result.add_check(check_name, passed, detail)
            except Exception as e:
                result.add_check(check_name, False, f"Check crashed: {e}")

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        result.passed = False

    return result


async def run_batch(batch_name: str, tests: list, output_dir: Path) -> list[TestResult]:
    """Run a batch of tests in a single app instance."""
    results = []
    app = AmplifierChicApp()

    print(f"\n{'=' * 60}")
    print(f"  BATCH {batch_name}: {len(tests)} tests")
    print(f"{'=' * 60}\n")

    try:
        async with app.run_test(size=(160, 50)) as pilot:
            # Let the app settle
            await pilot.pause(delay=1.0)

            # Inject mock messages for commands that need them
            await inject_mock_messages(app, pilot)
            await pilot.pause(delay=0.3)

            # Run each test
            for i, test_def in enumerate(tests):
                test_id = test_def[0]
                action = test_def[2]
                print(
                    f"  [{i + 1}/{len(tests)}] {test_id}: {action:<45} ",
                    end="",
                    flush=True,
                )

                result = await run_single_test(app, pilot, test_def, output_dir)
                results.append(result)

                failed_checks = [c for c in result.checks if not c["passed"]]
                if result.error:
                    print(f"ERROR - {result.error.split(chr(10))[0][:60]}")
                elif failed_checks:
                    reasons = ", ".join(c["name"] for c in failed_checks)
                    print(f"FAIL  - {reasons}")
                else:
                    print("PASS")

    except Exception as e:
        print(f"\n  BATCH CRASHED: {e}\n{traceback.format_exc()}")

    return results


def print_summary(all_results: list[TestResult]):
    """Print a summary table of all test results."""
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}\n")

    if failed > 0:
        print("  FAILURES:\n")
        for r in all_results:
            if not r.passed:
                failed_checks = [c for c in r.checks if not c["passed"]]
                reasons = "; ".join(
                    f"{c['name']}: {c['detail']}" for c in failed_checks
                )
                if r.error:
                    reasons = r.error.split("\n")[0]
                print(f"    {r.test_id:<8} {r.command:<45} {reasons[:80]}")
        print()


def save_results(all_results: list[TestResult], output_dir: Path):
    """Save results as JSON."""
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(all_results),
        "passed": sum(1 for r in all_results if r.passed),
        "failed": sum(1 for r in all_results if not r.passed),
        "results": [r.to_dict() for r in all_results],
    }
    path = output_dir / "test_results.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"  Results saved to {path}")


async def main():
    parser = argparse.ArgumentParser(description="Interactive TUI test runner")
    parser.add_argument("--batch", default="all", help="Batch to run: 1,2,3,4 or 'all'")
    parser.add_argument(
        "--output-dir", default=None, help="Output directory for SVGs and results"
    )
    args = parser.parse_args()

    # Set up output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(__file__).parent.parent / ".test-results" / f"run_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Output directory: {output_dir}")

    # Determine which batches to run
    if args.batch == "all":
        batch_keys = sorted(BATCHES.keys())
    else:
        batch_keys = [b.strip() for b in args.batch.split(",")]

    all_results: list[TestResult] = []

    for key in batch_keys:
        if key not in BATCHES:
            print(f"  Unknown batch: {key}")
            continue
        batch_dir = output_dir / f"batch_{key}"
        batch_dir.mkdir(exist_ok=True)
        results = await run_batch(key, BATCHES[key], batch_dir)
        all_results.extend(results)

    print_summary(all_results)
    save_results(all_results, output_dir)

    return 0 if all(r.passed for r in all_results) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
