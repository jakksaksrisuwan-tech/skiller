from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, ListItem, ListView, Static

MENU = [
    ("linux_mcq", "Linux Basics MCQ"),
    ("python_mcq", "Python MCQ"),
    ("typing_drill", "Typing Drill — Python structures"),
    ("typing_linux", "Typing Drill — Linux basics"),
    ("python_task_practice", "Python Task — Practice"),
    ("python_task_easy", "Python Task — Easy (~30 min)"),
    ("python_task_csv", "Python Task — CSV Aggregate (20/40 min targets)"),
    ("python_task_hard", "Python Task — Hard (~40 min)"),
    ("stats", "Stats / Proficiency"),
    ("quit", "Quit"),
]


class MenuScreen(Screen):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("enter", "select", "Select", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Center(
            Vertical(
                Static(
                    "[b]skiller[/b] — DevSkiller-style technical exercise prep",
                    id="title",
                ),
                ListView(
                    *[
                        ListItem(Static(label), id=f"item-{key}")
                        for key, label in MENU
                    ],
                    id="menu",
                ),
                id="menu-box",
            )
        )
        yield Footer()

    def dev_state(self) -> dict:
        try:
            lv = self.query_one("#menu", ListView)
        except Exception:
            return {}
        idx = lv.index if lv.index is not None else 0
        key = MENU[idx][0] if 0 <= idx < len(MENU) else None
        return {"menu_index": idx, "menu_key": key}

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id is None:
            return
        key = event.item.id.removeprefix("item-")
        self.app.dispatch_menu(key)  # type: ignore[attr-defined]

    def action_quit(self) -> None:
        self.app.exit()
