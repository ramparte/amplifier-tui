"""Environment detection and validation for Amplifier TUI.

Checks the full chain: libraries installed -> CLI on PATH -> home dir exists
-> distro config loadable -> active bundle set -> bundle actually loadable.
Provides a numbered setup checklist so users on unconfigured machines get
clear, actionable guidance instead of raw exceptions.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .log import logger
from .platform_info import amplifier_home


@dataclass
class SetupStep:
    """One step in the setup checklist."""

    label: str
    ok: bool
    detail: str  # shown when ok
    fix: str  # shown when not ok (multi-line guidance)


@dataclass
class EnvironmentStatus:
    """Snapshot of the current Amplifier environment."""

    # Core checks (ordered by dependency chain)
    cli_installed: bool = False  # `amplifier` binary on PATH
    cli_path: str = ""  # resolved path to the binary
    libraries_importable: bool = False  # amplifier_core importable
    distro_importable: bool = False  # amplifier_distro importable (the app layer)
    foundation_importable: bool = False  # amplifier_foundation importable
    home_exists: bool = False  # ~/.amplifier directory exists
    settings_readable: bool = False  # settings.yaml exists and parses
    active_bundle: str = ""  # bundle name from settings, or ""
    bundle_loadable: bool = False  # load_bundle() succeeds for active bundle
    bundle_error: str = ""  # error message if bundle load failed

    # User preferences
    workspace: str = ""
    workspace_exists: bool = False

    # Collected steps (populated by check_environment)
    steps: list[SetupStep] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True when the environment can create sessions."""
        return (
            self.libraries_importable
            and self.distro_importable
            and self.foundation_importable
            and self.home_exists
            and bool(self.active_bundle)
            and self.bundle_loadable
        )

    @property
    def first_problem_step(self) -> int | None:
        """Return the 0-based index of the first failing step, or None."""
        for i, step in enumerate(self.steps):
            if not step.ok:
                return i
        return None


def check_environment(workspace_pref: str = "") -> EnvironmentStatus:
    """Probe the full setup chain and return an EnvironmentStatus.

    Checks are ordered so that each depends on the previous one.
    We keep going past failures to give a complete picture.
    """
    status = EnvironmentStatus()

    # --- 1. CLI on PATH ---
    cli = shutil.which("amplifier") or ""
    status.cli_path = cli
    status.cli_installed = bool(cli)
    status.steps.append(
        SetupStep(
            label="Amplifier CLI installed",
            ok=status.cli_installed,
            detail=cli,
            fix=(
                "Install the Amplifier CLI:\n"
                "  uv tool install git+https://github.com/microsoft/amplifier\n"
                "\n"
                "If already installed, make sure it's on your PATH:\n"
                '  export PATH="$HOME/.local/bin:$PATH"'
            ),
        )
    )

    # --- 2. Core libraries importable ---
    try:
        import amplifier_core  # noqa: F401  # type: ignore[import-not-found]

        status.libraries_importable = True
    except ImportError:
        logger.debug("amplifier_core not importable", exc_info=True)
    status.steps.append(
        SetupStep(
            label="Amplifier libraries importable",
            ok=status.libraries_importable,
            detail="amplifier_core OK",
            fix=(
                "The amplifier-core library is not importable.\n"
                "This usually means the CLI install didn't complete.\n"
                "  Reinstall:  uv tool install git+https://github.com/microsoft/amplifier"
            ),
        )
    )

    # --- 3. Distro layer (amplifier_distro / amplifier-app-cli) ---
    try:
        import amplifier_distro  # noqa: F401  # type: ignore[import-not-found]

        status.distro_importable = True
    except ImportError:
        logger.debug("amplifier_distro not importable", exc_info=True)
    status.steps.append(
        SetupStep(
            label="Amplifier app layer (amplifier-app-cli)",
            ok=status.distro_importable,
            detail="amplifier_distro OK",
            fix=(
                "The amplifier-app-cli package is not importable.\n"
                "The TUI depends on it for session management.\n"
                "  Install:  uv tool install git+https://github.com/microsoft/amplifier"
            ),
        )
    )

    # --- 4. Foundation library ---
    try:
        import amplifier_foundation  # noqa: F401  # type: ignore[import-not-found]

        status.foundation_importable = True
    except ImportError:
        logger.debug("amplifier_foundation not importable", exc_info=True)
    status.steps.append(
        SetupStep(
            label="Amplifier foundation library",
            ok=status.foundation_importable,
            detail="amplifier_foundation OK",
            fix=(
                "amplifier-foundation is not importable.\n"
                "  Install:  pip install amplifier-foundation\n"
                "  (Usually installed automatically with the CLI)"
            ),
        )
    )

    # --- 5. Home directory ---
    home = amplifier_home()
    status.home_exists = home.is_dir()
    status.steps.append(
        SetupStep(
            label="Amplifier home directory",
            ok=status.home_exists,
            detail=str(home),
            fix=(
                f"Directory not found: {home}\n"
                "Run the CLI once to create it:\n"
                "  amplifier"
            ),
        )
    )

    # --- 6. Settings file ---
    settings_path = home / "settings.yaml"
    active_bundle = ""
    if settings_path.exists():
        try:
            import yaml

            data = yaml.safe_load(settings_path.read_text()) or {}
            bundle_cfg = data.get("bundle", {})
            if isinstance(bundle_cfg, dict):
                active_bundle = str(bundle_cfg.get("active") or "")
            status.settings_readable = True
        except Exception:
            logger.debug("Failed to read settings.yaml", exc_info=True)
    status.active_bundle = active_bundle
    status.steps.append(
        SetupStep(
            label="Active bundle configured",
            ok=bool(active_bundle),
            detail=active_bundle,
            fix=(
                "No active bundle is set in ~/.amplifier/settings.yaml.\n"
                "Choose one:\n"
                "  amplifier bundle list      # see what's available\n"
                "  amplifier bundle use <name> # select one"
            ),
        )
    )

    # --- 7. Bundle actually loadable ---
    if active_bundle and status.foundation_importable and status.distro_importable:
        try:
            from amplifier_foundation import load_bundle  # type: ignore[import-not-found]

            import asyncio

            # Use BundleRegistry (same path as the bridge)
            try:
                from amplifier_foundation import BundleRegistry  # type: ignore[import-not-found]

                registry = BundleRegistry()
            except ImportError:
                registry = None

            loop = asyncio.new_event_loop()
            try:
                if registry is not None:
                    loop.run_until_complete(
                        load_bundle(active_bundle, registry=registry)
                    )
                else:
                    loop.run_until_complete(load_bundle(active_bundle))
                status.bundle_loadable = True
            finally:
                loop.close()
        except Exception as exc:
            err = str(exc)
            # Detect the common "short name not in registry" case
            if "No handler for URI" in err:
                status.bundle_error = (
                    f"'{active_bundle}' is set as active but can't be resolved.\n"
                    "The CLI knows this name, but the bundle isn't cached yet.\n"
                    "Fix: run the CLI once to populate the cache:\n"
                    "  amplifier run 'hello'\n"
                    "Or add the bundle by full URI:\n"
                    "  amplifier bundle add <git+https://...>"
                )
            else:
                status.bundle_error = err
            logger.debug("Bundle load failed for %s", active_bundle, exc_info=True)
    elif active_bundle:
        status.bundle_error = "Cannot test (missing libraries)"
    status.steps.append(
        SetupStep(
            label=f"Bundle '{active_bundle or '?'}' loadable",
            ok=status.bundle_loadable,
            detail="loaded successfully",
            fix=(status.bundle_error or "No bundle to test (set one first)")
            + "\n\nIf the bundle can't be found, you may need to install it:\n"
            "  amplifier bundle add <source>\n"
            "  amplifier bundle use <name>",
        )
    )

    # --- Workspace (optional, not blocking) ---
    ws = workspace_pref.strip()
    status.workspace = ws
    status.workspace_exists = bool(ws) and Path(ws).expanduser().resolve().is_dir()

    return status


def format_status(status: EnvironmentStatus) -> str:
    """Format an EnvironmentStatus into a numbered setup checklist."""
    lines: list[str] = ["Amplifier Environment Check\n"]

    for i, step in enumerate(status.steps, 1):
        marker = "OK" if step.ok else "!!"
        lines.append(f"  {i}. [{marker}] {step.label}")
        if step.ok:
            lines.append(f"         {step.detail}")
        else:
            for fix_line in step.fix.splitlines():
                lines.append(f"         {fix_line}")

    # Workspace (always shown, not numbered -- it's optional)
    lines.append("")
    if status.workspace:
        tag = "OK" if status.workspace_exists else "NOT FOUND"
        lines.append(f"  Workspace: {status.workspace} [{tag}]")
    else:
        lines.append("  Workspace: not set (use /workspace <path>)")

    # Overall verdict
    lines.append("")
    if status.ready:
        lines.append("  Ready to go.")
    else:
        first = status.first_problem_step
        if first is not None:
            lines.append(f"  Start with step {first + 1} above to get things working.")

    return "\n".join(lines)
