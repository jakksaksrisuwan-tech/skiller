"""Shared UI helpers used across screens."""
from __future__ import annotations

import time

from textual.reactive import reactive
from textual.widgets import Static


def progress_bar(frac: float, width: int = 12) -> str:
    """Unicode-block progress bar. `frac` is clamped to [0, 1]."""
    frac = max(0.0, min(1.0, frac))
    fill = int(round(frac * width))
    return "█" * fill + "░" * (width - fill)


def progress_fraction(current: float, target: float) -> float:
    """Safe ratio with zero-target fallback. Clamped to [0, 1]."""
    if not target:
        return 0.0
    return min(1.0, current / target)


class StopwatchLabel(Static):
    """A Static label that updates itself with elapsed monotonic time.

    Pass `tick_seconds` to control refresh rate (default 1.0).
    """
    seconds = reactive(0.0)

    def __init__(self, *args, tick_seconds: float = 1.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tick_seconds = tick_seconds

    def on_mount(self) -> None:
        self._start = time.monotonic()
        self.set_interval(self._tick_seconds, self._tick)

    def _tick(self) -> None:
        self.seconds = time.monotonic() - self._start

    def watch_seconds(self, _old: float, new: float) -> None:
        m, s = divmod(int(new), 60)
        self.update(f"⏱  {m:02d}:{s:02d}")
