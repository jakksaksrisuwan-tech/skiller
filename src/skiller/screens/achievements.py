"""Dedicated Achievements panel — F3 from typing screen.

Locked achievements hide the trophy name (mystery is part of the reward);
unlocked achievements display the full punny name + tier glyph + earned date.
"""
from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from ..achievements import TIER_GLYPH, progress_view
from ..ui import progress_bar as _bar


class AchievementsScreen(Screen):
    BINDINGS = [
        Binding("escape,q,f3", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(" ", id="ach-summary"),
            DataTable(id="ach-grid", zebra_stripes=True),
            id="ach-box",
        )
        yield Footer()

    def on_mount(self) -> None:
        t: DataTable = self.query_one("#ach-grid", DataTable)
        t.add_columns("", "name", "goal", "progress", "earned")
        store = self.app.store  # type: ignore[attr-defined]
        rows = progress_view(store, {"chain": 0, "session_best_chain": 0})
        unlocked = [r for r in rows if r["unlocked"]]
        locked = [r for r in rows if not r["unlocked"]]
        self.query_one("#ach-summary", Static).update(
            f"[b]🏆 Achievements[/b]   "
            f"{len(unlocked)}/{len(rows)} unlocked   "
            f"[dim](locked names hidden — earn them to reveal)[/dim]"
        )
        # show unlocked first (most recent at top), then locked by closeness
        unlocked.sort(key=lambda r: r.get("ts", 0), reverse=True)
        for r in unlocked + locked:
            tier = r["tier"]
            glyph = TIER_GLYPH.get(tier, "·")
            if r["unlocked"]:
                mark = glyph
                name = f"[b]{r['name']}[/b]"
                desc = r["desc"]
                progress = "[green]✓[/green]"
                earned_ts = r.get("ts", 0)
                earned = (
                    datetime.fromtimestamp(earned_ts).strftime("%Y-%m-%d")
                    if earned_ts else "—"
                )
            else:
                mark = "[dim]·[/dim]"
                name = "[dim italic]???[/dim italic]"
                desc = f"[dim]{r['desc']}[/dim]"
                if r["target"]:
                    cur, tgt = r["current"], r["target"]
                    bar = _bar(min(1.0, cur / tgt) if tgt else 0.0, 10)
                    progress = f"[dim]{bar} {cur:.0f}/{tgt:.0f}[/dim]"
                else:
                    progress = "[dim]—[/dim]"
                earned = ""
            t.add_row(mark, name, desc, progress, earned)

    def action_back(self) -> None:
        self.app.pop_screen()
