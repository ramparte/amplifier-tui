"""Entry point for Amplifier TUI CLI."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from .log import logger

# ---------------------------------------------------------------------------
# Environment health checks
# ---------------------------------------------------------------------------

_REQUIRED_LIBS = [
    ("amplifier_core", "amplifier-core"),
    ("amplifier_foundation", "amplifier-foundation"),
    ("amplifier_distro", "amplifier-distro"),
]


def _check_amplifier() -> bool:
    """Return True if amplifier_core and amplifier_foundation are importable."""
    try:
        import amplifier_core  # noqa: F401  # type: ignore[import-not-found]
        import amplifier_foundation  # noqa: F401  # type: ignore[import-not-found]

        return True
    except ImportError:
        return False


def _try_auto_repair() -> bool:
    """Attempt to fix a broken environment with ``uv sync``.

    Returns True if the repair succeeded (imports now work).
    """
    uv = shutil.which("uv")
    if not uv:
        return False

    print(
        "Amplifier libraries missing -- attempting auto-repair (uv sync)...",
        file=sys.stderr,
    )
    try:
        subprocess.run(
            [uv, "sync", "--quiet"],
            check=True,
            timeout=120,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("Auto-repair uv sync failed: %s", exc)
        return False

    # Re-check after sync
    return _check_amplifier()


def _run_doctor() -> None:
    """Print a detailed environment health report and exit."""

    print("Amplifier TUI -- Environment Doctor\n")

    # 1. Python
    print(f"  Python:   {sys.executable} ({sys.version.split()[0]})")

    # 2. uv
    uv = shutil.which("uv")
    print(f"  uv:       {uv or 'NOT FOUND'}")

    # 3. Required libraries
    print()
    all_ok = True
    for mod_name, pkg_name in _REQUIRED_LIBS:
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, "__version__", "installed")
            print(f"  [ok] {pkg_name:30s}  {ver}")
        except ImportError:
            print(f"  [!!] {pkg_name:30s}  NOT IMPORTABLE")
            all_ok = False

    # 4. Bridge
    print()
    try:
        from amplifier_distro.bridge import LocalBridge  # type: ignore[import-not-found]

        print(f"  [ok] {'distro Bridge':30s}  {LocalBridge.__module__}")
    except Exception as exc:
        print(f"  [!!] {'distro Bridge':30s}  {exc}")
        all_ok = False

    # 5. Bundle
    print()
    try:
        from pathlib import Path
        import yaml  # type: ignore[import-untyped]

        distro_cfg = Path.home() / ".amplifier" / "distro.yaml"
        if distro_cfg.exists():
            with open(distro_cfg) as f:
                cfg = yaml.safe_load(f)
            bundle = cfg.get("bundle", {}).get("active", "(not set)")
            print(f"  [ok] {'Active bundle':30s}  {bundle}")
        else:
            print(f"  [--] {'Active bundle':30s}  no distro.yaml")
    except Exception as exc:
        print(f"  [!!] {'Active bundle':30s}  {exc}")

    # 6. Sessions directory
    from pathlib import Path

    projects = Path.home() / ".amplifier" / "projects"
    if projects.exists():
        count = sum(1 for p in projects.iterdir() if p.is_dir())
        print(f"  [ok] {'Projects directory':30s}  {count} project(s)")
    else:
        print(f"  [--] {'Projects directory':30s}  not found")

    # Summary
    print()
    if all_ok:
        print("  All checks passed.")
    else:
        print("  Some checks failed.  Try:")
        print("    cd <amplifier-tui-dir> && uv sync")
        print("  or reinstall:")
        print("    uv tool install git+https://github.com/microsoft/amplifier")

    sys.exit(0 if all_ok else 1)


def main():
    """Run Amplifier TUI."""
    parser = argparse.ArgumentParser(description="Amplifier TUI")
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version="amplifier-tui 0.1.0",
    )
    parser.add_argument(
        "--resume",
        "-r",
        action="store_true",
        help="Resume the most recent session",
    )
    parser.add_argument(
        "--session",
        "-s",
        type=str,
        help="Resume a specific session ID",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check environment health and exit",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch web interface instead of TUI",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Web server port (default: 8765)",
    )
    parser.add_argument(
        "--tmux-mode",
        action="store_true",
        default=None,
        help="Launch in tmux mode (single-session, no tabs/sidebar)",
    )
    parser.add_argument(
        "--no-tmux-mode",
        action="store_true",
        default=False,
        help="Force standard TUI even when inside tmux",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Initial prompt to send",
    )

    args = parser.parse_args()

    # --doctor: print diagnostics and exit
    if args.doctor:
        _run_doctor()
        return

    # Pre-flight: if libraries are missing, try auto-repair before falling
    # back to limited mode.  This handles the common case where an upstream
    # dependency reshuffle (e.g. distro moving core behind an optional extra)
    # broke the environment -- a simple ``uv sync`` usually fixes it.
    if not _check_amplifier():
        if not _try_auto_repair():
            print(
                "Note: Amplifier libraries not detected.  The TUI will launch\n"
                "in limited mode.  Run 'amplifier-tui --doctor' for details,\n"
                "or try:\n"
                "\n"
                "  cd <amplifier-tui-dir> && uv sync\n",
                file=sys.stderr,
            )

    # Determine session to resume
    resume_session_id = None
    if args.session:
        resume_session_id = args.session
    elif args.resume:
        resume_session_id = "__most_recent__"

    initial_prompt = " ".join(args.prompt) if args.prompt else None

    # --web: launch web interface instead of TUI
    if args.web:
        try:
            from amplifier_tui.web import main as web_main

            web_main(port=args.port, resume_session_id=resume_session_id)
        except ImportError as exc:
            print(
                f"Web dependencies not installed: {exc}\n"
                "Install with:  pip install amplifier-tui[web]\n"
                "Or:  pip install fastapi uvicorn websockets",
                file=sys.stderr,
            )
            sys.exit(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        return

    # Resolve tmux mode: explicit flag > auto-detect via $TMUX env var
    import os

    use_tmux_mode = False
    if args.no_tmux_mode:
        use_tmux_mode = False
    elif args.tmux_mode:
        use_tmux_mode = True
    else:
        # Auto-detect: if $TMUX is set, default to tmux mode
        use_tmux_mode = bool(os.environ.get("TMUX"))

    if use_tmux_mode:
        try:
            from amplifier_tui.tmux_app import run_tmux_app

            run_tmux_app(
                resume_session_id=resume_session_id,
                initial_prompt=initial_prompt,
            )
        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception:
            logger.debug("Fatal error in amplifier-tui (tmux mode)", exc_info=True)
            import traceback

            traceback.print_exc()
            sys.exit(1)
        return

    try:
        from amplifier_tui.app import run_app

        run_app(resume_session_id=resume_session_id, initial_prompt=initial_prompt)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:
        logger.debug("Fatal error in amplifier-tui", exc_info=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
