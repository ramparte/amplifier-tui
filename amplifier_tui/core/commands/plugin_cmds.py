"""Plugin management commands (/plugins, /plugins reload, /plugins help)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amplifier_tui.core.features.plugin_loader import PluginLoader


class PluginCommandsMixin:
    """Mixin providing /plugins command."""

    _plugin_loader: PluginLoader

    def _cmd_plugins(self, text: str) -> None:
        """Handle /plugins subcommands."""
        args = text.strip() if text else ""

        if not args or args == "list":
            self._add_system_message(self._plugin_loader.format_list())  # type: ignore[attr-defined]
            return

        if args == "reload":
            results = self._plugin_loader.reload_all()
            loaded = sum(1 for r in results if r.is_loaded)
            failed = sum(1 for r in results if not r.is_loaded)
            msg = f"Reloaded plugins: {loaded} loaded"
            if failed:
                msg += f", [red]{failed} failed[/red]"
            self._add_system_message(msg)  # type: ignore[attr-defined]
            if failed:
                # Show failures
                for r in results:
                    if not r.is_loaded:
                        self._add_system_message(  # type: ignore[attr-defined]
                            f"  [red]\u2717[/red] {r.name}: {r.error}"
                        )
            return

        if args == "help":
            self._add_system_message(self._plugin_loader.format_help())  # type: ignore[attr-defined]
            return

        self._add_system_message(  # type: ignore[attr-defined]
            "Usage:\n"
            "  /plugins          List loaded plugins\n"
            "  /plugins reload   Reload all plugins\n"
            "  /plugins help     Show plugin authoring guide"
        )
