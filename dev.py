#!/usr/bin/env python3
"""Hot-reload supervisor for Textual apps using the HotReloadable mixin.

Spawns the target app, watches source dirs, sends SIGTERM on file change,
respawns with the saved state file if present.

Usage (flow_debug defaults shown):
    .venv/bin/python dev.py
    .venv/bin/python dev.py --entry tui.main --watch tui --state snapshots/_reload.json

Generalize to any Textual app:
    python dev.py --entry myapp.tui --watch myapp --state .dev_state.json
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from watchfiles import watch

DEFAULT_EXTS = {".py", ".toml", ".tcss"}
ROOT = Path(__file__).resolve().parent

# Set when the supervisor itself is killing the child (file change, shutdown).
# Cleared otherwise so a natural child exit (user pressed q) propagates as
# SIGINT to unblock the watch loop and let the supervisor exit cleanly.
_INTENTIONAL_KILL = threading.Event()
_CURRENT_PROC: list[subprocess.Popen | None] = [None]


def _monitor_natural_exit() -> None:
    """Daemon thread. Watches the current child; if it dies without the
    supervisor having requested it, SIGINT the supervisor so the watchfiles
    iterator unblocks and the main loop exits."""
    while True:
        proc = _CURRENT_PROC[0]
        if proc is not None and proc.poll() is not None and not _INTENTIONAL_KILL.is_set():
            try:
                os.kill(os.getpid(), signal.SIGINT)
            except ProcessLookupError:
                pass
            return
        time.sleep(0.3)


def spawn(python: str, entry: str, state_path: Path, snapshot_arg: str) -> subprocess.Popen:
    cmd = [python, "-m", entry]
    if state_path.exists():
        cmd += [snapshot_arg, str(state_path)]
    print(f"[dev] spawn: {' '.join(cmd)}", file=sys.stderr, flush=True)
    proc = subprocess.Popen(cmd)
    _INTENTIONAL_KILL.clear()
    _CURRENT_PROC[0] = proc
    return proc


def stop(proc: subprocess.Popen) -> None:
    _INTENTIONAL_KILL.set()
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Hot-reload supervisor for Textual apps")
    ap.add_argument("--entry", default="skiller.main",
                    help="Python module to run with -m. Default: skiller.main")
    ap.add_argument("--watch", action="append", default=None,
                    help="Path to watch (repeatable). Default: src/skiller content pyproject.toml")
    ap.add_argument("--state", default=".dev_state.json",
                    help="Where the app writes its hot-reload state on SIGTERM")
    ap.add_argument("--snapshot-arg", default="--snapshot",
                    help="CLI flag the app accepts to load state on startup")
    ap.add_argument("--ext", action="append", default=None,
                    help=f"File suffix that triggers reload (repeatable). Default: {sorted(DEFAULT_EXTS)}")
    ap.add_argument("--python", default=sys.executable, help="Python interpreter")
    ap.add_argument("--debounce", type=int, default=400, help="Watcher debounce ms")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    exts = set(args.ext) if args.ext else DEFAULT_EXTS
    state_path = (ROOT / args.state).resolve() if not Path(args.state).is_absolute() else Path(args.state)
    watch_targets = args.watch or ["src/skiller", "content", "pyproject.toml"]
    paths = []
    for w in watch_targets:
        p = (ROOT / w).resolve() if not Path(w).is_absolute() else Path(w)
        if p.exists():
            paths.append(str(p))
    if not paths:
        print(f"[dev] no watch paths exist: {watch_targets}", file=sys.stderr)
        sys.exit(2)

    print(f"[dev] watching: {paths}", file=sys.stderr, flush=True)
    proc = spawn(args.python, args.entry, state_path, args.snapshot_arg)
    spawn_history: list[tuple[float, int | None]] = [(time.monotonic(), None)]

    # daemon: detects natural child exit (user pressed q) and exits supervisor
    threading.Thread(target=_monitor_natural_exit, daemon=True).start()

    def _is_relevant(p: str) -> bool:
        path = Path(p)
        if path.suffix not in exts:
            return False
        # User-edited task files (solution.py saved by the editor on every
        # Ctrl-T / Ctrl-G) live under content/python_tasks. They are runtime
        # data, not source — don't trigger a respawn on them.
        parts = path.parts
        if "python_tasks" in parts and path.suffix == ".py":
            return False
        return True

    try:
        for changes in watch(*paths, recursive=True, debounce=args.debounce, step=200):
            relevant = [p for _, p in changes if _is_relevant(p)]
            if not relevant:
                continue
            print(f"[dev] change: {relevant[0]} → restart", file=sys.stderr, flush=True)
            stop(proc)
            spawn_history[-1] = (spawn_history[-1][0], proc.returncode)

            now = time.monotonic()
            recent = [(t, rc) for t, rc in spawn_history if now - t < 5.0]
            failed = [rc for _, rc in recent if rc not in (None, 0)]
            if len(failed) >= 3:
                print(
                    f"[dev] crash loop ({len(failed)} non-zero exits in 5s). "
                    "Halting respawn — fix and save again to retry.",
                    file=sys.stderr, flush=True,
                )
                for next_changes in watch(*paths, recursive=True, debounce=args.debounce, step=200):
                    if any(_is_relevant(p) for _, p in next_changes):
                        spawn_history.clear()
                        break

            time.sleep(0.2)
            proc = spawn(args.python, args.entry, state_path, args.snapshot_arg)
            spawn_history.append((time.monotonic(), None))
    except KeyboardInterrupt:
        # Either user pressed Ctrl-C, OR monitor thread sent SIGINT after the
        # child exited on its own. Either way: shut down cleanly.
        if proc.poll() is None:
            print("[dev] interrupt — stopping child", file=sys.stderr, flush=True)
            stop(proc)
        else:
            print("[dev] child exited — shutting down supervisor", file=sys.stderr, flush=True)
        # Belt-and-suspenders terminal restore in case the child left raw mode.
        try:
            os.write(1, b"\x1b[?1049l\x1b[?25h\x1b[?1000l\x1b[?1006l\x1b[?1003l\x1b[?2004l")
        except Exception:
            pass


if __name__ == "__main__":
    main()
