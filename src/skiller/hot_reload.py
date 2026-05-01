"""Hot-reload mixin for Textual apps.

Subclass `HotReloadable` alongside `textual.app.App`. Override
`save_dev_state` / `load_dev_state` and call `setup_hot_reload(state_path)`
from your `on_mount` to wire up SIGTERM-driven snapshot+exit.

The supervisor (`dev.py`) sends SIGTERM on file change. This mixin:
  1. Calls save_dev_state() and writes the dict atomically to state_path.
  2. Calls cleanup_dev_state() for side-effects (sockets, lockfiles).
  3. Emits terminal-restore escape sequences directly to fd 1.
  4. os._exit(0) — bypasses Textual's shutdown machinery, which is unreliable
     when invoked from an asyncio signal handler.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any


def atomic_write(path: Path, data: str) -> None:
    """Write data to path atomically via tmp + os.replace (POSIX-atomic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


# Terminal-restore: alt-screen off, cursor on, mouse + bracketed-paste off.
_TERM_RESTORE = b"\x1b[?1049l\x1b[?25h\x1b[?1000l\x1b[?1006l\x1b[?1003l\x1b[?2004l"


class HotReloadable:
    """Mixin providing SIGTERM-driven save+exit for hot-reload supervisors.

    Override `save_dev_state`, `load_dev_state`, optionally `cleanup_dev_state`.
    """

    _hr_state_path: Path | None = None
    _hr_terminating: bool = False

    def save_dev_state(self) -> dict[str, Any]:
        """Return a JSON-serializable dict snapshotting app state to persist
        across reloads. Default = empty (no state preserved)."""
        return {}

    def load_dev_state(self, state: dict[str, Any]) -> None:
        """Restore from a state dict produced by `save_dev_state`. Called from
        `setup_hot_reload` if the state file exists at startup."""
        pass

    def cleanup_dev_state(self) -> None:
        """Side-effect cleanup before hard exit (close sockets, remove lockfiles).
        Runs after state save. Must not block."""
        pass

    def setup_hot_reload(self, state_path: Path) -> None:
        """Wire SIGTERM + SIGUSR1 + restore prior state if file exists. Call from on_mount.

        SIGUSR1 = dump-without-exit (visibility tool). External observer can
        `kill -USR1 <pid>` to force a fresh state_path write without affecting
        the running TUI."""
        self._hr_state_path = state_path
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text())
                self.load_dev_state(data)
            except Exception:
                pass
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGTERM, self._hr_on_sigterm)
            loop.add_signal_handler(signal.SIGUSR1, self._hr_on_sigusr1)
        except (NotImplementedError, RuntimeError):
            pass

    def _hr_on_sigusr1(self) -> None:
        """Dump current state to state_path without exiting. For external introspection."""
        if self._hr_state_path is None:
            return
        try:
            state = self.save_dev_state()
            atomic_write(
                self._hr_state_path,
                json.dumps(state, indent=2, default=str),
            )
        except Exception:
            pass

    def _hr_on_sigterm(self) -> None:
        if self._hr_terminating:
            return
        self._hr_terminating = True
        try:
            state = self.save_dev_state()
            if self._hr_state_path is not None:
                atomic_write(
                    self._hr_state_path,
                    json.dumps(state, indent=2, default=str),
                )
        except Exception:
            pass
        try:
            self.cleanup_dev_state()
        except Exception:
            pass
        try:
            os.write(1, _TERM_RESTORE)
        except Exception:
            pass
        os._exit(0)
