"""Plugin loader for amplifier-tui.

Discovers, loads, and manages plugins from plugin directories.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from amplifier_tui.plugin import PluginCommand, clear_registry, get_registry


@dataclass
class LoadedPlugin:
    """Metadata about a loaded plugin."""

    name: str  # derived from filename (e.g., "greet" from "greet.py")
    path: str  # full path to the plugin file
    commands: list[str] = field(default_factory=list)  # command names registered
    loaded_at: datetime = field(default_factory=datetime.now)
    error: str = ""  # error message if loading failed

    @property
    def is_loaded(self) -> bool:
        return not self.error


class PluginLoader:
    """Discovers and loads plugins from plugin directories."""

    # Default plugin directories
    USER_DIR = Path.home() / ".amplifier" / "tui-plugins"
    PROJECT_DIR = Path(".amplifier") / "tui-plugins"

    def __init__(self, extra_dirs: list[Path] | None = None) -> None:
        self._plugins: dict[str, LoadedPlugin] = {}
        self._dirs: list[Path] = []
        if extra_dirs:
            self._dirs.extend(extra_dirs)
        # Add default dirs (project first for override priority)
        self._dirs.append(self.PROJECT_DIR)
        self._dirs.append(self.USER_DIR)

    @property
    def plugins(self) -> dict[str, LoadedPlugin]:
        return dict(self._plugins)

    @property
    def plugin_commands(self) -> dict[str, PluginCommand]:
        """Return all successfully registered plugin commands."""
        return dict(get_registry())

    def discover(self) -> list[Path]:
        """Find all plugin files across plugin directories.

        Returns list of .py file paths, project-local first.
        """
        found: list[Path] = []
        seen_names: set[str] = set()

        for d in self._dirs:
            if not d.exists() or not d.is_dir():
                continue
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("_"):
                    continue  # skip __init__.py, _private.py, etc.
                if f.stem in seen_names:
                    continue  # first directory wins (project overrides user)
                seen_names.add(f.stem)
                found.append(f)

        return found

    def load_plugin(self, path: Path) -> LoadedPlugin:
        """Load a single plugin file.

        Returns LoadedPlugin with error info if loading failed.
        """
        name = path.stem

        # Snapshot registry before loading
        before = set(get_registry().keys())

        try:
            # Remove old module if reloading
            mod_name = f"amplifier_tui_plugin_{name}"
            if mod_name in sys.modules:
                del sys.modules[mod_name]

            spec = importlib.util.spec_from_file_location(mod_name, str(path))
            if spec is None or spec.loader is None:
                return LoadedPlugin(
                    name=name, path=str(path), error=f"Cannot load: {path}"
                )

            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)

            # Find newly registered commands
            after = set(get_registry().keys())
            new_commands = list(after - before)

            # Tag commands with source info
            for cmd_name in new_commands:
                cmd = get_registry()[cmd_name]
                cmd.source_file = str(path)
                cmd.plugin_name = name

            plugin = LoadedPlugin(
                name=name,
                path=str(path),
                commands=new_commands,
            )
            self._plugins[name] = plugin
            return plugin

        except Exception as e:
            plugin = LoadedPlugin(
                name=name,
                path=str(path),
                error=f"{type(e).__name__}: {e}",
            )
            self._plugins[name] = plugin
            return plugin

    def load_all(self) -> list[LoadedPlugin]:
        """Discover and load all plugins.

        Returns list of LoadedPlugin (check .error for failures).
        """
        files = self.discover()
        results = []
        for f in files:
            result = self.load_plugin(f)
            results.append(result)
        return results

    def reload_all(self) -> list[LoadedPlugin]:
        """Clear registry and reload all plugins."""
        clear_registry()
        self._plugins.clear()
        return self.load_all()

    def execute_command(self, name: str, app: object, args: str) -> bool:
        """Execute a plugin command.

        Args:
            name: Command name (without /)
            app: The app instance to pass to the command
            args: Command arguments

        Returns:
            True if command was found and executed, False if not found.
        """
        registry = get_registry()
        if name not in registry:
            return False

        cmd = registry[name]
        try:
            cmd.callback(app, args)
        except Exception as e:
            # Error isolation - plugin crashes don't crash the app
            if hasattr(app, "_add_system_message"):
                app._add_system_message(  # type: ignore[attr-defined]
                    f"[red]Plugin error in /{name}:[/red] {type(e).__name__}: {e}"
                )
        return True

    def format_list(self) -> str:
        """Format loaded plugins as Rich markup."""
        if not self._plugins:
            lines = [
                "[dim]No plugins loaded.[/dim]",
                "",
                "Plugin directories:",
            ]
            for d in self._dirs:
                exists = (
                    "[green]exists[/green]" if d.exists() else "[dim]not found[/dim]"
                )
                lines.append(f"  {d} ({exists})")
            lines.append("")
            lines.append("Create a .py file in one of these directories.")
            lines.append("See /plugins help for examples.")
            return "\n".join(lines)

        lines = [f"[bold]Loaded Plugins ({len(self._plugins)}):[/bold]"]
        lines.append("")

        for name, plugin in sorted(self._plugins.items()):
            if plugin.is_loaded:
                cmd_list = (
                    ", ".join(f"/{c}" for c in plugin.commands) or "(no commands)"
                )
                lines.append(f"  [green]\u2713[/green] {name}")
                lines.append(f"    Commands: {cmd_list}")
                lines.append(f"    Source: [dim]{plugin.path}[/dim]")
            else:
                lines.append(f"  [red]\u2717[/red] {name}")
                lines.append(f"    Error: [red]{plugin.error}[/red]")
                lines.append(f"    Source: [dim]{plugin.path}[/dim]")

        # List available commands
        registry = get_registry()
        if registry:
            lines.append("")
            lines.append("[bold]Plugin Commands:[/bold]")
            for cmd_name, cmd in sorted(registry.items()):
                desc = f" - {cmd.description}" if cmd.description else ""
                lines.append(f"  /{cmd_name}{desc}")

        return "\n".join(lines)

    def format_help(self) -> str:
        """Format plugin system help."""
        return (
            "[bold]Plugin System Help[/bold]\n"
            "\n"
            "Plugins are Python files that add custom slash commands.\n"
            "\n"
            "[bold]Plugin Directories:[/bold]\n"
            "  ~/.amplifier/tui-plugins/     (user-global)\n"
            "  .amplifier/tui-plugins/       (project-local)\n"
            "\n"
            "[bold]Example Plugin:[/bold]\n"
            "  # ~/.amplifier/tui-plugins/greet.py\n"
            "  from amplifier_tui.plugin import slash_command\n"
            "\n"
            '  @slash_command("greet", description="Say hello")\n'
            "  def cmd_greet(app, args: str):\n"
            "      app._add_system_message(f\"Hello, {args or 'world'}!\")\n"
            "\n"
            "[bold]Commands:[/bold]\n"
            "  /plugins          List loaded plugins\n"
            "  /plugins reload   Reload all plugins\n"
            "  /plugins help     Show this help"
        )

    def clear(self) -> None:
        """Clear all plugins and registry."""
        clear_registry()
        self._plugins.clear()
