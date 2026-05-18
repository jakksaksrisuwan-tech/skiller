#!/usr/bin/env bash
# Start skiller in hot-reload mode via the dev.py supervisor.
# Edit any .py / .yaml / .toml under src/skiller or content/ → child respawns.
set -euo pipefail

cd "$(dirname "$0")"

# Inside tmux, export the pane id so the probe (Ctrl-Y) can capture the
# visible screen alongside its JSON dump.
if [[ -n "${TMUX_PANE:-}" ]]; then
  export SKILLER_PROBE_TMUX_TARGET="${TMUX_PANE}"
fi

# First-run: ensure the venv exists and editable install is current.
if [[ ! -d .venv ]]; then
  echo "[start] no .venv — bootstrapping with uv…"
  uv venv
  uv pip install -e ".[dev]"
fi

exec uv run python dev.py "$@"
