from __future__ import annotations

import statistics
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from ..achievements import TIER_GLYPH, progress_view
from ..content import all_item_tags, load_tasks
from ..ui import progress_bar as _bar  # local alias preserves call sites


class StatsScreen(Screen):
    BINDINGS = [
        Binding("escape,q", "back", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("[b]Proficiency[/b]", id="stats-title"),
            DataTable(id="skill-table", zebra_stripes=True),
            Static(" ", id="tag-title"),
            DataTable(id="tag-table", zebra_stripes=True),
            Static(" ", id="task-title"),
            DataTable(id="task-table", zebra_stripes=True),
            Static(" ", id="typing-title"),
            DataTable(id="typing-table", zebra_stripes=True),
            Static(" ", id="ach-title"),
            DataTable(id="ach-table", zebra_stripes=True),
            Static(" ", id="recent-title"),
            DataTable(id="recent-table", zebra_stripes=True),
            id="stats-box",
        )
        yield Footer()

    def on_mount(self) -> None:
        skill_t: DataTable = self.query_one("#skill-table", DataTable)
        skill_t.add_columns(
            "skill", "n", "rolling", "overall", "avg s", "calibration"
        )
        tag_t: DataTable = self.query_one("#tag-table", DataTable)
        tag_t.add_columns("tag", "n", "rolling", "overall", "mastery")
        typ_t: DataTable = self.query_one("#typing-table", DataTable)
        typ_t.add_columns("structure", "runs", "wpm", "accuracy", "errors")
        task_t: DataTable = self.query_one("#task-table", DataTable)
        task_t.add_columns("task", "first pass", "complete", "vs target", "best run")
        ach_t: DataTable = self.query_one("#ach-table", DataTable)
        ach_t.add_columns("", "name", "description", "progress")
        recent_t: DataTable = self.query_one("#recent-table", DataTable)
        recent_t.add_columns("when", "skill", "kind", "result", "grade", "conf", "item")
        self.action_refresh()

    def action_refresh(self) -> None:
        store = self.app.store  # type: ignore[attr-defined]

        skill_t: DataTable = self.query_one("#skill-table", DataTable)
        skill_t.clear()
        if not store.skills:
            skill_t.add_row("[dim]no attempts yet — run a quiz[/dim]", "", "", "", "", "")
        else:
            for name, st in sorted(store.skills.items()):
                bar = _bar(st.rolling_accuracy)
                cal = f"{st.calibration:.2f}" if st.brier_n else "—"
                skill_t.add_row(
                    name,
                    str(st.attempts),
                    f"{bar} {st.rolling_accuracy:.0%}",
                    f"{st.accuracy:.0%}",
                    f"{st.avg_seconds:.1f}",
                    cal,
                )

        tag_t: DataTable = self.query_one("#tag-table", DataTable)
        tag_t.clear()
        tags = store.tag_stats(all_item_tags())
        if tags:
            self.query_one("#tag-title", Static).update("[b]Per tag[/b]")
            ranked = sorted(
                tags.items(),
                key=lambda kv: (kv[1]["rolling_acc"], -kv[1]["attempts"]),
            )
            for name, t in ranked:
                bar = _bar(t["rolling_acc"])
                # mastery: rolling_acc >= .8 AND attempts >= 3
                mastery = "✓" if t["rolling_acc"] >= 0.8 and t["attempts"] >= 3 else "·"
                tag_t.add_row(
                    name,
                    str(t["attempts"]),
                    f"{bar} {t['rolling_acc']:.0%}",
                    f"{t['acc']:.0%}",
                    mastery,
                )
        else:
            self.query_one("#tag-title", Static).update("[dim]No tag data yet.[/dim]")

        task_t: DataTable = self.query_one("#task-table", DataTable)
        task_t.clear()
        tasks = load_tasks()
        # Single pass over attempts: collect best (fastest) run per (kind, item_id).
        best_by: dict[tuple[str, str], float] = {}
        for a in store.attempts:
            if a.kind in ("task_first_pass", "task_complete") or (
                a.kind == "task" and a.correct
            ):
                key = (a.kind, a.item_id)
                if key not in best_by or a.seconds < best_by[key]:
                    best_by[key] = a.seconds
        if not tasks:
            self.query_one("#task-title", Static).update(
                "[dim]No task attempts yet.[/dim]"
            )
        else:
            self.query_one("#task-title", Static).update("[b]Tasks — milestones[/b]")
            for t in tasks:
                fp = best_by.get(("task_first_pass", t.id))
                cp = best_by.get(("task_complete", t.id))
                br = best_by.get(("task", t.id))
                tcomplete = t.target_complete_minutes or t.suggested_minutes
                fp_str = f"{fp / 60:.1f} min" if fp else "—"
                cp_str = f"{cp / 60:.1f} min" if cp else "—"
                vs_parts: list[str] = []
                if t.target_first_pass_minutes:
                    if fp is None:
                        vs_parts.append(f"first {t.target_first_pass_minutes}m: pending")
                    else:
                        delta = fp / 60 - t.target_first_pass_minutes
                        vs_parts.append(
                            f"first {'✓' if delta <= 0 else '+'}{abs(delta):.1f}m"
                        )
                if tcomplete:
                    if cp is None:
                        vs_parts.append(f"done {tcomplete}m: pending")
                    else:
                        delta = cp / 60 - tcomplete
                        vs_parts.append(
                            f"done {'✓' if delta <= 0 else '+'}{abs(delta):.1f}m"
                        )
                vs_str = "  ".join(vs_parts) if vs_parts else "—"
                best_str = f"{br / 60:.1f} min" if br else "—"
                task_t.add_row(t.title, fp_str, cp_str, vs_str, best_str)

        typ_t: DataTable = self.query_one("#typing-table", DataTable)
        typ_t.clear()
        if store.structures:
            self.query_one("#typing-title", Static).update("[b]Typing — by structure[/b]")
            ranked = sorted(
                store.structures.items(),
                key=lambda kv: (kv[1].wpm, kv[1].accuracy),
            )
            for name, st in ranked:
                typ_t.add_row(
                    name,
                    str(st.completions),
                    f"{st.wpm:.0f}",
                    f"{st.accuracy:.0%}",
                    str(st.errors),
                )
        else:
            self.query_one("#typing-title", Static).update(
                "[dim]No typing drills yet — try Typing Drill from menu.[/dim]"
            )

        # ── achievements ──
        ach_t: DataTable = self.query_one("#ach-table", DataTable)
        ach_t.clear()
        rows = progress_view(store, {"chain": 0, "session_best_chain": 0})
        unlocked_n = sum(1 for r in rows if r["unlocked"])
        total_n = len(rows)
        self.query_one("#ach-title", Static).update(
            f"[b]Achievements[/b]   {unlocked_n}/{total_n} unlocked"
        )
        # show 12 rows: all unlocked first, then closest-to-unlock locked
        for r in rows[:12]:
            glyph = TIER_GLYPH.get(r["tier"], "·")
            mark = glyph if r["unlocked"] else "·"
            # Locked: hide the punny name — earn it to reveal.
            name = (
                f"[b]{r['name']}[/b]" if r["unlocked"]
                else "[dim italic]???[/dim italic]"
            )
            desc = r["desc"] if r["unlocked"] else f"[dim]{r['desc']}[/dim]"
            if r["unlocked"]:
                prog = "[green]✓ done[/green]"
            elif r["target"]:
                cur = r["current"]
                tgt = r["target"]
                bar = _bar(min(1.0, cur / tgt) if tgt else 0.0, 10)
                prog = f"[dim]{bar}[/dim] {cur:.0f}/{tgt:.0f}"
            else:
                prog = "[dim]—[/dim]"
            ach_t.add_row(mark, name, desc, prog)

        # recent + medians
        recent_attempts = store.attempts[-50:]
        if recent_attempts:
            by_skill: dict[str, list[float]] = {}
            for a in recent_attempts:
                by_skill.setdefault(a.skill, []).append(a.seconds)
            medians = {k: statistics.median(v) for k, v in by_skill.items()}
            tail = "  ".join(f"{k}: {v:.1f}s" for k, v in medians.items())
            self.query_one("#recent-title", Static).update(
                f"[b]Recent activity[/b]   medians → {tail}"
            )
        else:
            self.query_one("#recent-title", Static).update("[dim]No recent activity.[/dim]")

        recent_t: DataTable = self.query_one("#recent-table", DataTable)
        recent_t.clear()
        for a in reversed(store.attempts[-20:]):
            ago = time.time() - a.ts
            when = f"{int(ago)}s ago" if ago < 60 else f"{int(ago / 60)}m ago"
            result = "[green]✓[/green]" if a.correct else "[red]✗[/red]"
            recent_t.add_row(
                when, a.skill, a.kind, result, str(a.grade), str(a.confidence), a.item_id
            )

    def action_back(self) -> None:
        self.app.pop_screen()
