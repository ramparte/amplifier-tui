#!/usr/bin/env bash
# Launch Amplifier TUI from WSL or any Unix shell.
# Usage: ./run.sh [args...]
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    uv venv
    uv pip install -e .
fi

source .venv/bin/activate
exec amplifier-tui "$@"
