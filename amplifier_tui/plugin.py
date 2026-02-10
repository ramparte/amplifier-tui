"""Amplifier TUI Plugin API.

Plugin authors use this module to register custom slash commands:

    from amplifier_tui.plugin import slash_command

    @slash_command("greet", description="Say hello")
    def cmd_greet(app, args: str):
        app._add_system_message(f"Hello, {args or 'world'}!")

Plugins are single Python files placed in:
  - ~/.amplifier/tui-plugins/     (user-global)
  - .amplifier/tui-plugins/       (project-local)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class PluginCommand:
    """A registered plugin command."""

    name: str  # command name without /
    description: str
    callback: Callable[[Any, str], None]  # (app, args) -> None
    source_file: str = ""  # path to the plugin file
    plugin_name: str = ""  # derived from filename


# Global registry - populated by @slash_command decorators during import
_registry: dict[str, PluginCommand] = {}


def slash_command(name: str, description: str = "") -> Callable:
    """Decorator to register a function as a slash command.

    Args:
        name: Command name (without the /). E.g., "greet" for /greet
        description: Help text shown in /plugins list

    Usage:
        @slash_command("greet", description="Say hello")
        def cmd_greet(app, args: str):
            app._add_system_message(f"Hello, {args or 'world'}!")
    """

    def decorator(func: Callable[[Any, str], None]) -> Callable[[Any, str], None]:
        _registry[name] = PluginCommand(
            name=name,
            description=description,
            callback=func,
        )
        return func

    return decorator


def get_registry() -> dict[str, PluginCommand]:
    """Return the current plugin command registry."""
    return _registry


def clear_registry() -> None:
    """Clear all registered commands. Used during reload."""
    _registry.clear()
