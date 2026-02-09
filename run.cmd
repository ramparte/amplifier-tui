@echo off
REM Launch Amplifier TUI from Windows CMD (goes through WSL).
REM Usage: run.cmd [args...]
wsl -e bash -c "./run.sh %*"
