"""Tests for the plugin system (F4.3).

Covers:
- Plugin API (slash_command decorator, registry)
- PluginCommand dataclass
- LoadedPlugin dataclass
- PluginLoader (discover, load, reload, execute, format)
- PluginCommandsMixin
- Integration (real plugin files, error isolation)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amplifier_tui.plugin import (
    PluginCommand,
    clear_registry,
    get_registry,
    slash_command,
)
from amplifier_tui.features.plugin_loader import LoadedPlugin, PluginLoader


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the global plugin registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture()
def loader(tmp_path: Path) -> PluginLoader:
    """A PluginLoader with only a tmp_path plugin directory."""
    return PluginLoader(extra_dirs=[tmp_path])


# ── Plugin API ───────────────────────────────────────────────────────────────


class TestSlashCommandDecorator:
    """Test the @slash_command decorator and registry."""

    def test_registers_command(self):
        @slash_command("hello", description="Say hello")
        def cmd_hello(app, args: str):
            pass

        reg = get_registry()
        assert "hello" in reg
        assert reg["hello"].name == "hello"
        assert reg["hello"].description == "Say hello"
        assert reg["hello"].callback is cmd_hello

    def test_returns_original_function(self):
        @slash_command("noop")
        def cmd_noop(app, args: str):
            pass

        # Decorator should return the original function
        assert callable(cmd_noop)
        assert cmd_noop.__name__ == "cmd_noop"

    def test_empty_description_default(self):
        @slash_command("bare")
        def cmd_bare(app, args: str):
            pass

        assert get_registry()["bare"].description == ""

    def test_multiple_registrations(self):
        @slash_command("a")
        def cmd_a(app, args: str):
            pass

        @slash_command("b")
        def cmd_b(app, args: str):
            pass

        reg = get_registry()
        assert "a" in reg
        assert "b" in reg

    def test_overwrite_same_name(self):
        @slash_command("dup")
        def cmd_first(app, args: str):
            pass

        @slash_command("dup")
        def cmd_second(app, args: str):
            pass

        assert get_registry()["dup"].callback is cmd_second


class TestClearRegistry:
    def test_clears_all(self):
        @slash_command("temp")
        def cmd_temp(app, args: str):
            pass

        assert len(get_registry()) == 1
        clear_registry()
        assert len(get_registry()) == 0


class TestGetRegistry:
    def test_returns_dict(self):
        assert isinstance(get_registry(), dict)

    def test_returns_same_object(self):
        """get_registry returns the actual global dict (not a copy)."""
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2


# ── PluginCommand dataclass ──────────────────────────────────────────────────


class TestPluginCommand:
    def test_fields(self):
        cmd = PluginCommand(
            name="test",
            description="A test command",
            callback=lambda app, args: None,
            source_file="/tmp/test.py",
            plugin_name="test",
        )
        assert cmd.name == "test"
        assert cmd.description == "A test command"
        assert cmd.source_file == "/tmp/test.py"
        assert cmd.plugin_name == "test"
        assert callable(cmd.callback)

    def test_defaults(self):
        cmd = PluginCommand(name="x", description="", callback=lambda a, b: None)
        assert cmd.source_file == ""
        assert cmd.plugin_name == ""


# ── LoadedPlugin dataclass ───────────────────────────────────────────────────


class TestLoadedPlugin:
    def test_is_loaded_when_no_error(self):
        p = LoadedPlugin(name="good", path="/tmp/good.py")
        assert p.is_loaded is True

    def test_not_loaded_when_error(self):
        p = LoadedPlugin(name="bad", path="/tmp/bad.py", error="SyntaxError: ...")
        assert p.is_loaded is False

    def test_defaults(self):
        p = LoadedPlugin(name="x", path="/tmp/x.py")
        assert p.commands == []
        assert p.error == ""
        assert p.loaded_at is not None


# ── PluginLoader ─────────────────────────────────────────────────────────────


class TestPluginLoaderInit:
    def test_empty_initial_state(self, loader: PluginLoader):
        assert loader.plugins == {}
        assert loader.plugin_commands == {}


class TestPluginLoaderDiscover:
    def test_finds_py_files(self, tmp_path: Path):
        (tmp_path / "hello.py").write_text("# plugin")
        (tmp_path / "world.py").write_text("# plugin")
        loader = PluginLoader(extra_dirs=[tmp_path])

        found = loader.discover()
        names = {f.stem for f in found}
        assert "hello" in names
        assert "world" in names

    def test_skips_underscore_prefixed(self, tmp_path: Path):
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "_private.py").write_text("")
        (tmp_path / "public.py").write_text("# plugin")
        loader = PluginLoader(extra_dirs=[tmp_path])

        found = loader.discover()
        names = [f.stem for f in found]
        assert "public" in names
        assert "__init__" not in names
        assert "_private" not in names

    def test_skips_non_py_files(self, tmp_path: Path):
        (tmp_path / "readme.md").write_text("# readme")
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "actual.py").write_text("# plugin")
        loader = PluginLoader(extra_dirs=[tmp_path])

        found = loader.discover()
        assert len(found) == 1
        assert found[0].stem == "actual"

    def test_project_overrides_user(self, tmp_path: Path):
        """First directory wins when same filename exists."""
        project_dir = tmp_path / "project"
        user_dir = tmp_path / "user"
        project_dir.mkdir()
        user_dir.mkdir()

        (project_dir / "shared.py").write_text("# project version")
        (user_dir / "shared.py").write_text("# user version")

        # project_dir listed first in extra_dirs
        loader = PluginLoader(extra_dirs=[project_dir, user_dir])
        found = loader.discover()

        shared_files = [f for f in found if f.stem == "shared"]
        assert len(shared_files) == 1
        assert str(project_dir) in str(shared_files[0])

    def test_empty_dir(self, tmp_path: Path):
        loader = PluginLoader(extra_dirs=[tmp_path])
        assert loader.discover() == []

    def test_nonexistent_dir(self, tmp_path: Path):
        loader = PluginLoader(extra_dirs=[tmp_path / "nonexistent"])
        assert loader.discover() == []


class TestPluginLoaderLoad:
    def test_load_valid_plugin(self, tmp_path: Path):
        plugin_file = tmp_path / "hello.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("hello", description="Say hello")\n'
            "def cmd_hello(app, args):\n"
            "    pass\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        result = loader.load_plugin(plugin_file)

        assert result.is_loaded
        assert result.name == "hello"
        assert "hello" in result.commands
        assert result.error == ""

    def test_load_plugin_tags_source(self, tmp_path: Path):
        plugin_file = tmp_path / "tagged.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("tagged")\n'
            "def cmd_tagged(app, args):\n"
            "    pass\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_plugin(plugin_file)

        cmd = get_registry()["tagged"]
        assert cmd.source_file == str(plugin_file)
        assert cmd.plugin_name == "tagged"

    def test_load_invalid_plugin_syntax_error(self, tmp_path: Path):
        plugin_file = tmp_path / "bad.py"
        plugin_file.write_text("def broken(\n")

        loader = PluginLoader(extra_dirs=[tmp_path])
        result = loader.load_plugin(plugin_file)

        assert not result.is_loaded
        assert "SyntaxError" in result.error

    def test_load_plugin_runtime_error(self, tmp_path: Path):
        plugin_file = tmp_path / "crasher.py"
        plugin_file.write_text("raise RuntimeError('boom')\n")

        loader = PluginLoader(extra_dirs=[tmp_path])
        result = loader.load_plugin(plugin_file)

        assert not result.is_loaded
        assert "RuntimeError" in result.error
        assert "boom" in result.error

    def test_load_plugin_no_commands(self, tmp_path: Path):
        plugin_file = tmp_path / "empty.py"
        plugin_file.write_text("# A plugin that registers nothing\nx = 42\n")

        loader = PluginLoader(extra_dirs=[tmp_path])
        result = loader.load_plugin(plugin_file)

        assert result.is_loaded
        assert result.commands == []

    def test_load_plugin_multiple_commands(self, tmp_path: Path):
        plugin_file = tmp_path / "multi.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("multi_a")\n'
            "def cmd_a(app, args): pass\n"
            '@slash_command("multi_b")\n'
            "def cmd_b(app, args): pass\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        result = loader.load_plugin(plugin_file)

        assert result.is_loaded
        assert set(result.commands) == {"multi_a", "multi_b"}


class TestPluginLoaderLoadAll:
    def test_loads_discovered_plugins(self, tmp_path: Path):
        (tmp_path / "one.py").write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("one")\n'
            "def cmd(app, args): pass\n"
        )
        (tmp_path / "two.py").write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("two")\n'
            "def cmd(app, args): pass\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        results = loader.load_all()

        assert len(results) == 2
        assert all(r.is_loaded for r in results)
        assert "one" in get_registry()
        assert "two" in get_registry()

    def test_load_all_empty(self, tmp_path: Path):
        loader = PluginLoader(extra_dirs=[tmp_path])
        results = loader.load_all()
        assert results == []

    def test_load_all_partial_failure(self, tmp_path: Path):
        (tmp_path / "good.py").write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("good")\n'
            "def cmd(app, args): pass\n"
        )
        (tmp_path / "bad.py").write_text("raise Exception('fail')\n")

        loader = PluginLoader(extra_dirs=[tmp_path])
        results = loader.load_all()

        assert len(results) == 2
        loaded = [r for r in results if r.is_loaded]
        failed = [r for r in results if not r.is_loaded]
        assert len(loaded) == 1
        assert len(failed) == 1
        assert "good" in get_registry()


class TestPluginLoaderReload:
    def test_reload_clears_and_reloads(self, tmp_path: Path):
        plugin_file = tmp_path / "reloadme.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("reloadme")\n'
            "def cmd(app, args): pass\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()
        assert "reloadme" in get_registry()

        # Modify the plugin
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("reloadme_v2")\n'
            "def cmd(app, args): pass\n"
        )

        results = loader.reload_all()
        assert len(results) == 1
        assert "reloadme_v2" in get_registry()
        assert "reloadme" not in get_registry()  # old command gone

    def test_reload_clears_plugins_dict(self, tmp_path: Path):
        (tmp_path / "x.py").write_text("# empty plugin\n")

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()
        assert "x" in loader.plugins

        # Remove the file
        (tmp_path / "x.py").unlink()
        loader.reload_all()
        assert "x" not in loader.plugins


class TestPluginLoaderExecute:
    def test_execute_known_command(self, tmp_path: Path):
        plugin_file = tmp_path / "echo.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("echo")\n'
            "def cmd_echo(app, args):\n"
            "    app.received = args\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()

        mock_app = MagicMock()
        result = loader.execute_command("echo", mock_app, "test input")

        assert result is True
        assert mock_app.received == "test input"

    def test_execute_unknown_command(self, loader: PluginLoader):
        mock_app = MagicMock()
        result = loader.execute_command("nonexistent", mock_app, "")
        assert result is False

    def test_execute_error_isolation(self, tmp_path: Path):
        """A crashing plugin command doesn't raise, and shows error message."""
        plugin_file = tmp_path / "crashcmd.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("crashcmd")\n'
            "def cmd_crash(app, args):\n"
            "    raise ValueError('plugin boom')\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()

        mock_app = MagicMock()
        # Should not raise
        result = loader.execute_command("crashcmd", mock_app, "")

        assert result is True
        # Should have called _add_system_message with error info
        mock_app._add_system_message.assert_called_once()
        error_msg = mock_app._add_system_message.call_args[0][0]
        assert "Plugin error" in error_msg
        assert "ValueError" in error_msg
        assert "plugin boom" in error_msg

    def test_execute_error_isolation_no_add_system_message(self, tmp_path: Path):
        """Error isolation still works when app lacks _add_system_message."""
        plugin_file = tmp_path / "crash2.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("crash2")\n'
            "def cmd_crash(app, args):\n"
            "    raise RuntimeError('fail')\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()

        # An app object without _add_system_message
        class BareApp:
            pass

        result = loader.execute_command("crash2", BareApp(), "")
        assert result is True  # Still returns True (command was found)


class TestPluginLoaderFormat:
    def test_format_list_empty(self, loader: PluginLoader):
        text = loader.format_list()
        assert "No plugins loaded" in text
        assert "Plugin directories:" in text

    def test_format_list_with_plugins(self, tmp_path: Path):
        plugin_file = tmp_path / "demo.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("demo", description="Demo command")\n'
            "def cmd_demo(app, args): pass\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()
        text = loader.format_list()

        assert "Loaded Plugins (1)" in text
        assert "demo" in text
        assert "/demo" in text
        assert "Demo command" in text

    def test_format_list_with_failed_plugin(self, tmp_path: Path):
        (tmp_path / "broken.py").write_text("raise Exception('nope')\n")

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()
        text = loader.format_list()

        assert "broken" in text
        assert "nope" in text

    def test_format_help(self, loader: PluginLoader):
        text = loader.format_help()
        assert "Plugin System Help" in text
        assert "tui-plugins" in text
        assert "slash_command" in text
        assert "/plugins" in text
        assert "/plugins reload" in text

    def test_format_help_contains_example(self, loader: PluginLoader):
        text = loader.format_help()
        assert "greet" in text
        assert "Example Plugin" in text


class TestPluginLoaderClear:
    def test_clear_empties_everything(self, tmp_path: Path):
        plugin_file = tmp_path / "clearme.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("clearme")\n'
            "def cmd(app, args): pass\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()

        assert len(loader.plugins) == 1
        assert len(get_registry()) == 1

        loader.clear()

        assert len(loader.plugins) == 0
        assert len(get_registry()) == 0


# ── Integration tests ────────────────────────────────────────────────────────


class TestPluginIntegration:
    def test_full_lifecycle(self, tmp_path: Path):
        """Create plugin file -> load -> execute -> reload -> clear."""
        # Create plugin
        plugin_file = tmp_path / "lifecycle.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("lifecycle", description="Lifecycle test")\n'
            "def cmd_lifecycle(app, args):\n"
            "    app.result = f'lifecycle:{args}'\n"
        )

        # Load
        loader = PluginLoader(extra_dirs=[tmp_path])
        results = loader.load_all()
        assert len(results) == 1
        assert results[0].is_loaded

        # Execute
        mock_app = MagicMock()
        assert loader.execute_command("lifecycle", mock_app, "test")
        assert mock_app.result == "lifecycle:test"

        # Reload (modify file)
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("lifecycle_v2", description="V2")\n'
            "def cmd_v2(app, args):\n"
            "    app.result = f'v2:{args}'\n"
        )
        loader.reload_all()
        assert "lifecycle" not in get_registry()
        assert "lifecycle_v2" in get_registry()

        # Clear
        loader.clear()
        assert len(get_registry()) == 0

    def test_multiple_plugins_in_dir(self, tmp_path: Path):
        """Multiple plugin files coexist in the same directory."""
        (tmp_path / "alpha.py").write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("alpha")\n'
            "def cmd(app, args): app.alpha = True\n"
        )
        (tmp_path / "beta.py").write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("beta")\n'
            "def cmd(app, args): app.beta = True\n"
        )
        (tmp_path / "gamma.py").write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("gamma")\n'
            "def cmd(app, args): app.gamma = True\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        results = loader.load_all()

        assert len(results) == 3
        assert all(r.is_loaded for r in results)

        reg = get_registry()
        assert "alpha" in reg
        assert "beta" in reg
        assert "gamma" in reg

    def test_plugin_accesses_app(self, tmp_path: Path):
        """Plugin can read and write app attributes."""
        plugin_file = tmp_path / "accessor.py"
        plugin_file.write_text(
            "from amplifier_tui.plugin import slash_command\n"
            '@slash_command("accessor")\n'
            "def cmd_accessor(app, args):\n"
            "    count = getattr(app, 'call_count', 0)\n"
            "    app.call_count = count + 1\n"
            "    app._add_system_message(f'Called {app.call_count} times')\n"
        )

        loader = PluginLoader(extra_dirs=[tmp_path])
        loader.load_all()

        mock_app = MagicMock()
        mock_app.call_count = 0

        loader.execute_command("accessor", mock_app, "")
        assert mock_app.call_count == 1

        loader.execute_command("accessor", mock_app, "")
        assert mock_app.call_count == 2


# ── Command mixin ────────────────────────────────────────────────────────────


class TestPluginCommandsMixin:
    def test_mixin_has_cmd_plugins(self):
        from amplifier_tui.commands.plugin_cmds import PluginCommandsMixin

        assert hasattr(PluginCommandsMixin, "_cmd_plugins")
        assert callable(PluginCommandsMixin._cmd_plugins)

    def test_cmd_plugins_list(self, tmp_path: Path):
        """_cmd_plugins with no args shows list."""
        from amplifier_tui.commands.plugin_cmds import PluginCommandsMixin

        loader = PluginLoader(extra_dirs=[tmp_path])

        mock_app = MagicMock(spec=PluginCommandsMixin)
        mock_app._plugin_loader = loader
        mock_app._add_system_message = MagicMock()

        PluginCommandsMixin._cmd_plugins(mock_app, "")

        mock_app._add_system_message.assert_called_once()
        msg = mock_app._add_system_message.call_args[0][0]
        assert "No plugins loaded" in msg

    def test_cmd_plugins_reload(self, tmp_path: Path):
        """_cmd_plugins with 'reload' reloads plugins."""
        from amplifier_tui.commands.plugin_cmds import PluginCommandsMixin

        loader = PluginLoader(extra_dirs=[tmp_path])

        mock_app = MagicMock(spec=PluginCommandsMixin)
        mock_app._plugin_loader = loader
        mock_app._add_system_message = MagicMock()

        PluginCommandsMixin._cmd_plugins(mock_app, "reload")

        mock_app._add_system_message.assert_called_once()
        msg = mock_app._add_system_message.call_args[0][0]
        assert "Reloaded" in msg

    def test_cmd_plugins_help(self, tmp_path: Path):
        """_cmd_plugins with 'help' shows help."""
        from amplifier_tui.commands.plugin_cmds import PluginCommandsMixin

        loader = PluginLoader(extra_dirs=[tmp_path])

        mock_app = MagicMock(spec=PluginCommandsMixin)
        mock_app._plugin_loader = loader
        mock_app._add_system_message = MagicMock()

        PluginCommandsMixin._cmd_plugins(mock_app, "help")

        mock_app._add_system_message.assert_called_once()
        msg = mock_app._add_system_message.call_args[0][0]
        assert "Plugin System Help" in msg

    def test_cmd_plugins_unknown_subcommand(self, tmp_path: Path):
        """_cmd_plugins with unknown subcommand shows usage."""
        from amplifier_tui.commands.plugin_cmds import PluginCommandsMixin

        loader = PluginLoader(extra_dirs=[tmp_path])

        mock_app = MagicMock(spec=PluginCommandsMixin)
        mock_app._plugin_loader = loader
        mock_app._add_system_message = MagicMock()

        PluginCommandsMixin._cmd_plugins(mock_app, "unknown_subcommand")

        mock_app._add_system_message.assert_called_once()
        msg = mock_app._add_system_message.call_args[0][0]
        assert "Usage:" in msg


# ── Constants & exports ──────────────────────────────────────────────────────


class TestExports:
    def test_plugin_in_slash_commands(self):
        from amplifier_tui.constants import SLASH_COMMANDS

        assert "/plugins" in SLASH_COMMANDS
        assert "/plugins reload" in SLASH_COMMANDS
        assert "/plugins help" in SLASH_COMMANDS

    def test_features_export(self):
        from amplifier_tui.features import LoadedPlugin, PluginLoader

        assert PluginLoader is not None
        assert LoadedPlugin is not None

    def test_commands_export(self):
        from amplifier_tui.commands import PluginCommandsMixin

        assert PluginCommandsMixin is not None

    def test_public_api_import(self):
        from amplifier_tui.plugin import (
            PluginCommand,
            clear_registry,
            get_registry,
            slash_command,
        )

        assert callable(slash_command)
        assert callable(get_registry)
        assert callable(clear_registry)
        assert PluginCommand is not None
