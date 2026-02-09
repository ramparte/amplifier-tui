"""Entry point for Amplifier TUI CLI."""

import argparse
import sys

from .log import logger


def main():
    """Run Amplifier TUI TUI."""
    parser = argparse.ArgumentParser(description="Amplifier TUI TUI")
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
        "prompt",
        nargs="*",
        help="Initial prompt to send",
    )
    args = parser.parse_args()

    # Determine session to resume
    resume_session_id = None
    if args.session:
        resume_session_id = args.session
    elif args.resume:
        resume_session_id = "__most_recent__"

    initial_prompt = " ".join(args.prompt) if args.prompt else None

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
