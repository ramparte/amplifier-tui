# Launch Amplifier TUI from PowerShell (goes through WSL).
# Usage: .\run.ps1 [args...]
wsl -e bash -c "./run.sh $($args -join ' ')"
