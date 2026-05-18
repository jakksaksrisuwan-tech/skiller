"""Live state probe — driver-facing introspection API.

The tmux test driver triggers Ctrl-Y on the app, then reads PROBE_PATH to
assert on screen state without parsing TUI output. Each Screen subclass
optionally exposes ``dev_state() -> dict``; this module composes the
payload (always includes ``screen``) and writes it atomically.

Hot-reload state save reuses the same schema, so the live probe and the
SIGTERM snapshot stay in lockstep.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PROBE_PATH = Path(os.environ.get("SKILLER_PROBE_PATH", "/tmp/skiller_probe.json"))
SCREEN_PATH = Path(os.environ.get("SKILLER_PROBE_SCREEN", "/tmp/skiller_screen.txt"))
TMUX_TARGET_ENV = "SKILLER_PROBE_TMUX_TARGET"


def collect(app: Any) -> dict[str, Any]:
    screen = getattr(app, "screen", None)
    out: dict[str, Any] = {"screen": screen.__class__.__name__ if screen else None}
    fn = getattr(screen, "dev_state", None)
    if callable(fn):
        try:
            out.update(fn())
        except Exception as e:  # never crash the app over a probe
            out["dev_state_error"] = repr(e)
    return out


def write(payload: dict[str, Any], path: Path = PROBE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def capture_screen(path: Path = SCREEN_PATH) -> bool:
    """Capture the visible terminal pane via tmux to ``path``.

    No-op (returns False) if ``SKILLER_PROBE_TMUX_TARGET`` isn't set or the
    tmux call fails — keeps the probe usable when running outside tmux.
    """
    target = os.environ.get(TMUX_TARGET_ENV)
    if not target:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True, text=True, timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if out.returncode != 0:
        return False
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(out.stdout)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        return False
    return True
