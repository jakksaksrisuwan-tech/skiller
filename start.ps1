# Start skiller in hot-reload mode via the dev.py supervisor.
# Edit any .py / .yaml / .toml under src/skiller or content/ → child respawns.
#
# Notes for Windows:
# - Use Windows Terminal (or Windows Terminal Preview), NOT legacy cmd.exe —
#   the TUI relies on Unicode + 24-bit colour + scrollback handling that
#   cmd.exe doesn't support.
# - State-snapshot-on-respawn is Linux/macOS only (SIGTERM-driven).
#   On Windows the child is hard-killed; the next spawn starts on the menu
#   instead of restoring the screen you were on. Hot-reload itself still
#   works — supervisor + watcher + respawn cycle is unaffected.
# - If `uv` is missing: install it via `winget install --id=astral-sh.uv`
#   or `pip install uv`.
# - First run may require relaxing the script policy once:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

if (-not (Test-Path .venv)) {
    Write-Host "[start] no .venv — bootstrapping with uv..." -ForegroundColor Cyan
    uv venv
    uv pip install -e ".[dev]"
}

uv run python dev.py @args
