#!/usr/bin/env bash
# Start skiller in hot-reload mode via the dev.py supervisor.
# Edit any .py / .yaml / .toml under src/skiller or content/ → child respawns.
set -euo pipefail

cd "$(dirname "$0")"

# First-run: ensure the venv exists and editable install is current.
if [[ ! -d .venv ]]; then
  echo "[start] no .venv — bootstrapping with uv…"
  uv venv
  uv pip install -e ".[dev]"
fi

exec uv run python dev.py "$@"
