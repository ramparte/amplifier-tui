"""Environment detection and validation for Amplifier TUI.

Checks whether Amplifier is installed, configured, and ready to use.
Provides friendly diagnostic messages when something is missing so
that first-time users on unconfigured machines get clear guidance.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .log import logger
from .platform import amplifier_home


@dataclass
class EnvironmentStatus:
    """Snapshot of the current Amplifier environment."""

    amplifier_installed: bool  # amplifier_core + amplifier_foundation importable
    amplifier_cli_path: str  # path to `amplifier` binary, or ""
    amplifier_home_exists: bool  # ~/.amplifier directory exists
    active_bundle: str  # active bundle name, or ""
    workspace: str  # configured workspace directory, or ""
    workspace_exists: bool  # workspace path resolves to an existing directory

    @property
    def ready(self) -> bool:
        """True when the environment is fully functional."""
        return (
            self.amplifier_installed
            and self.amplifier_home_exists
            and bool(self.active_bundle)
        )

    @property
    def issues(self) -> list[str]:
        """Return a list of human-readable issues (empty when everything is fine)."""
        problems: list[str] = []
        if not self.amplifier_installed:
            problems.append(
                "Amplifier libraries not found.\n"
                "  Install:  uv tool install git+https://github.com/microsoft/amplifier\n"
                "  Docs:     https://github.com/microsoft/amplifier#readme"
            )
        if not self.amplifier_cli_path:
            problems.append(
                "The `amplifier` CLI is not on your PATH.\n"
                "  If you just installed it, open a new terminal or run:\n"
                '    export PATH="$HOME/.local/bin:$PATH"'
            )
        if self.amplifier_installed and not self.amplifier_home_exists:
            problems.append(
                f"Amplifier home directory not found at {amplifier_home()}.\n"
                "  Run `amplifier` once to initialise it, or start a session here\n"
                "  and it will be created automatically."
            )
        if (
            self.amplifier_installed
            and self.amplifier_home_exists
            and not self.active_bundle
        ):
            problems.append(
                "No active bundle configured.\n"
                "  Choose one with:  amplifier bundle use <name>\n"
                "  List available:   amplifier bundle list"
            )
        if self.workspace and not self.workspace_exists:
            problems.append(
                f"Configured workspace directory does not exist: {self.workspace}\n"
                "  Update it with:  /workspace <path>"
            )
        return problems


def check_environment(workspace_pref: str = "") -> EnvironmentStatus:
    """Probe the local system and return an EnvironmentStatus snapshot.

    Parameters
    ----------
    workspace_pref:
        The workspace path from user preferences (may be empty).
    """
    # --- Amplifier libraries ---
    installed = False
    try:
        import amplifier_core  # noqa: F401  # type: ignore[import-not-found]
        import amplifier_foundation  # noqa: F401  # type: ignore[import-not-found]

        installed = True
    except ImportError:
        logger.debug("Amplifier libraries not importable", exc_info=True)

    # --- CLI binary ---
    cli_path = shutil.which("amplifier") or ""

    # --- ~/.amplifier ---
    home = amplifier_home()
    home_exists = home.is_dir()

    # --- Active bundle ---
    active_bundle = ""
    settings_path = home / "settings.yaml"
    if settings_path.exists():
        try:
            import yaml

            data = yaml.safe_load(settings_path.read_text()) or {}
            bundle_cfg = data.get("bundle", {})
            if isinstance(bundle_cfg, dict):
                active_bundle = str(bundle_cfg.get("active") or "")
        except Exception:
            logger.debug(
                "Failed to read Amplifier settings for bundle info", exc_info=True
            )

    # --- Workspace ---
    ws = workspace_pref.strip()
    ws_exists = bool(ws) and Path(ws).expanduser().resolve().is_dir()

    return EnvironmentStatus(
        amplifier_installed=installed,
        amplifier_cli_path=cli_path,
        amplifier_home_exists=home_exists,
        active_bundle=active_bundle,
        workspace=ws,
        workspace_exists=ws_exists,
    )


def format_status(status: EnvironmentStatus) -> str:
    """Format an EnvironmentStatus into a human-readable diagnostic string."""
    ok = "ok"
    missing = "MISSING"

    lines = ["Environment\n"]

    # Amplifier install
    if status.amplifier_installed:
        lines.append(f"  Amplifier libraries:  {ok}")
    else:
        lines.append(f"  Amplifier libraries:  {missing}")

    # CLI
    if status.amplifier_cli_path:
        lines.append(f"  Amplifier CLI:        {status.amplifier_cli_path}")
    else:
        lines.append(f"  Amplifier CLI:        {missing} (not on PATH)")

    # Home directory
    home = amplifier_home()
    if status.amplifier_home_exists:
        lines.append(f"  Amplifier home:       {home}")
    else:
        lines.append(f"  Amplifier home:       {missing} ({home})")

    # Bundle
    if status.active_bundle:
        lines.append(f"  Active bundle:        {status.active_bundle}")
    else:
        lines.append(
            f"  Active bundle:        {missing} (run: amplifier bundle use <name>)"
        )

    # Workspace
    if status.workspace:
        tag = ok if status.workspace_exists else "NOT FOUND"
        lines.append(f"  Workspace:            {status.workspace} [{tag}]")
    else:
        lines.append("  Workspace:            not set (use /workspace <path>)")

    # Issues summary
    issues = status.issues
    if issues:
        lines.append("")
        lines.append(f"  {len(issues)} issue(s) found:\n")
        for issue in issues:
            for i, line in enumerate(issue.splitlines()):
                prefix = "  - " if i == 0 else "    "
                lines.append(f"{prefix}{line}")

    return "\n".join(lines)
