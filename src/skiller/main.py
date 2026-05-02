from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from textual.app import App

from .hot_reload import HotReloadable
from .screens.mcq import MCQScreen
from .screens.menu import MenuScreen
from .screens.stats import StatsScreen
from .screens.task import TaskScreen
from .screens.typing import TypingScreen
from .store import Store

TASK_DIRS = {
    "python_task_practice": Path("content/python_tasks/01_practice"),
    "python_task_easy":     Path("content/python_tasks/02_easy"),
    "python_task_hard":     Path("content/python_tasks/03_hard"),
    "python_task_csv":      Path("content/python_tasks/04_csv_aggregate"),
}


class SkillerApp(HotReloadable, App):
    CSS = """
    #title { padding: 1 2; content-align: center middle; }
    #menu-box { width: 60%; max-width: 80; padding: 2; }
    #menu { border: round $accent; padding: 1 2; }
    ListView > ListItem { padding: 0 1; }
    #mcq-box { padding: 1 3; height: 1fr; }
    #meta { color: $accent; }
    #watch { color: $warning; }
    #choices { padding: 1 2; }
    #feedback { padding-top: 1; }
    #stats-box { padding: 1 2; height: 1fr; }
    #stats-title { padding: 0 0 1 0; }
    #recent-title { padding: 1 0 1 0; }
    #tag-title { padding: 1 0 1 0; }
    DataTable { height: auto; }
    #task-title { padding: 1 0 1 0; }
    #ach-title { padding: 1 0 1 0; }
    #ach-box { padding: 2 4; height: 1fr; }
    #ach-summary { padding-bottom: 1; }
    #task-box { padding: 1 2; height: 1fr; }
    #task-meta { color: $accent; height: auto; }
    #task-watch { color: $warning; height: 1; }
    #task-split { height: 1fr; }
    #prompt-pane { width: 50%; height: 1fr; padding: 0 2 0 0; }
    #output-pane { width: 50%; height: 1fr; padding: 0 0 0 1; }
    #output-title { height: auto; padding-bottom: 1; }
    #output { height: 1fr; padding: 0; }
    #prompt-md { height: 1fr; }
    #typing-box { padding: 2 4; height: 1fr; }
    #typing-top { height: 3; }
    #typing-meta { color: $accent; width: 1fr; height: 3; content-align: left middle; }
    #typing-lcd { color: $warning; width: 10; height: 3; content-align: right top; }
    #typing-done { padding: 0 3; height: 1; }
    #typing-description { padding: 0 3; height: 1; color: $text-muted; }
    #typing-snippet { padding: 1 2; border: round $accent; height: auto; min-height: 3; }
    #typing-upcoming { padding: 0 3; height: auto; }
    #typing-stats { padding-top: 1; }
    #typing-help { color: $text-muted; padding-top: 1; height: 3; }
    """
    TITLE = "skiller"

    def __init__(self) -> None:
        super().__init__()
        self.store = Store()
        self._pending_route: str | None = None

    # ---- hot-reload state ----

    def save_dev_state(self) -> dict[str, Any]:
        """Snapshot which screen is open + lightweight cursor state."""
        screen = self.screen.__class__.__name__ if self.screen else None
        snap: dict[str, Any] = {"screen": screen}
        if screen == "MCQScreen":
            mcq: MCQScreen = self.screen  # type: ignore[assignment]
            snap["mcq"] = {
                "category": mcq.category,
                "n": mcq.n,
                "idx": mcq.idx,
                "correct_count": mcq.correct_count,
            }
        return snap

    def load_dev_state(self, state: dict[str, Any]) -> None:
        # remember; apply after on_mount has pushed default screen
        self._pending_route = state.get("screen") or None
        self._pending_payload = state

    def cleanup_dev_state(self) -> None:
        try:
            self.store.save()
        except Exception:
            pass

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())
        self.setup_hot_reload(Path(".dev_state.json"))
        self._restore_screen()

    def _restore_screen(self) -> None:
        if not self._pending_route:
            return
        route = self._pending_route
        payload = getattr(self, "_pending_payload", {}) or {}
        self._pending_route = None
        if route == "MCQScreen":
            mcq = payload.get("mcq", {})
            cat = mcq.get("category")
            if cat:
                self.push_screen(MCQScreen(category=cat, n=mcq.get("n", 25)))
        elif route == "StatsScreen":
            self.push_screen(StatsScreen())

    # ---- menu routing ----

    def dispatch_menu(self, key: str) -> None:
        if key == "quit":
            self.exit()
            return
        if key == "linux_mcq":
            self.push_screen(MCQScreen(category="linux", n=12))
            return
        if key == "python_mcq":
            self.push_screen(MCQScreen(category="python", n=25))
            return
        if key == "stats":
            self.push_screen(StatsScreen())
            return
        if key == "typing_drill":
            self.push_screen(TypingScreen(language="python"))
            return
        if key == "typing_linux":
            self.push_screen(TypingScreen(language="linux"))
            return
        if key in TASK_DIRS:
            d = TASK_DIRS[key]
            if not d.exists():
                self.notify(f"Task dir missing: {d}", severity="error")
                return
            self.push_screen(TaskScreen(d))
            return
        self.notify(f"Unknown action: {key}", severity="warning")


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, help="Optional state file to load.")
    args, _ = parser.parse_known_args()
    # The mixin reads from the path passed to setup_hot_reload (`.dev_state.json`).
    # If user passes --snapshot pointing elsewhere, copy to that path.
    if args.snapshot and args.snapshot.exists() and args.snapshot != Path(".dev_state.json"):
        Path(".dev_state.json").write_text(args.snapshot.read_text())
    SkillerApp().run()


if __name__ == "__main__":
    run()
