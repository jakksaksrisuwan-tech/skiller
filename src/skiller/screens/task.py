from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import yaml

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static

from ..models import Attempt
from ..test_runner import TestResult, run_pytest
from ..ui import StopwatchLabel


class TaskScreen(Screen):
    BINDINGS = [
        Binding("e", "edit", "Edit (vim)"),
        Binding("t", "run_visible", "Test (visible)"),
        Binding("s", "submit", "Submit (visible+hidden)"),
        Binding("escape", "back", "Back"),
        Binding("q", "back", "Quit", show=False),
    ]

    def __init__(self, task_dir: Path) -> None:
        super().__init__()
        self.task_dir = Path(task_dir).resolve()
        self.manifest = yaml.safe_load((self.task_dir / "task.yaml").read_text(encoding="utf-8"))
        self.solution_path = self.task_dir / "solution.py"
        self.last_result: TestResult | None = None
        self.submitted = False
        self.first_pass_recorded = False
        self.started: float = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(" ", id="task-meta"),
            StopwatchLabel("⏱  00:00", id="task-watch"),
            Horizontal(
                Vertical(
                    Markdown((self.task_dir / "prompt.md").read_text(encoding="utf-8"), id="prompt-md"),
                    id="prompt-pane",
                ),
                Vertical(
                    Static(" ", id="output-title"),
                    Static(" ", id="output"),
                    id="output-pane",
                ),
                id="task-split",
            ),
            id="task-box",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.started = time.monotonic()
        first_target = self.manifest.get("target_first_pass_minutes")
        complete_target = self.manifest.get(
            "target_complete_minutes", self.manifest.get("suggested_minutes", 0)
        )
        target_str = (
            f"🎯 first pass {first_target} min · 🏁 complete {complete_target} min"
            if first_target
            else f"suggested {complete_target} min"
        )
        self.query_one("#task-meta", Static).update(
            f"[b]{self.manifest['skill'].upper()}[/b] · "
            f"{self.manifest['difficulty']}   "
            f"[b]{self.manifest['title']}[/b]   "
            f"[dim]{target_str}[/dim]"
        )
        self.query_one("#output-title", Static).update(
            "[dim]Press [b]e[/b] to edit, [b]t[/b] to run visible tests, "
            "[b]s[/b] to submit (visible + hidden).[/dim]"
        )
        self.query_one("#output", Static).update(
            f"[b]solution.py[/b] — {self.solution_path}\n"
            f"[b]editor[/b] — {os.environ.get('EDITOR', 'vim')}"
        )

    # ---- actions ----

    def action_edit(self) -> None:
        editor = os.environ.get("EDITOR", "vim")
        with self.app.suspend():  # hands TTY back; restored after editor exits
            try:
                subprocess.run([editor, str(self.solution_path)], check=False)
            except FileNotFoundError:
                pass
        self.refresh()
        self.query_one("#output-title", Static).update("[dim]Returned from editor.[/dim]")

    def action_run_visible(self) -> None:
        result = self._run(self.manifest.get("visible_tests", []), label="visible")
        if (
            result is not None
            and result.all_green
            and not self.first_pass_recorded
        ):
            self._record_milestone("task_first_pass", "first_pass")

    def action_submit(self) -> None:
        all_files = list(self.manifest.get("visible_tests", [])) + list(
            self.manifest.get("hidden_tests", [])
        )
        if not all_files:
            self.query_one("#output-title", Static).update(
                "[yellow]No tests defined.[/yellow]"
            )
            return
        result = self._run(all_files, label="submit")
        if result is None:
            return
        # First-pass on submit too: if visible part now green and not yet
        # recorded (e.g. user hit `s` straight away), capture it.
        visible = self.manifest.get("visible_tests", [])
        if (
            visible
            and not self.first_pass_recorded
            and result.failed == 0
            and result.errors == 0
        ):
            self._record_milestone("task_first_pass", "first_pass")
        # Record submit attempt (kind=task) and milestone if green.
        if not self.submitted:
            elapsed = time.monotonic() - self.started
            store = self.app.store  # type: ignore[attr-defined]
            store.record(
                item_id=self.manifest["id"],
                kind="task",
                skill=self.manifest["skill"],
                correct=result.all_green,
                seconds=elapsed,
                confidence=4,  # tasks: assume committed
            )
            self.submitted = True
            if result.all_green:
                self._record_milestone("task_complete", "complete")

    def _record_milestone(self, kind: str, label: str) -> None:
        """Append a typed attempt logging time-to-milestone vs target."""
        elapsed = time.monotonic() - self.started
        store = self.app.store  # type: ignore[attr-defined]
        store.attempts.append(
            Attempt(
                item_id=self.manifest["id"],
                kind=kind,  # type: ignore[arg-type]
                skill=self.manifest["skill"],
                correct=True,
                seconds=elapsed,
                ts=time.time(),
                confidence=4,
                grade=4,
            )
        )
        store.save()
        target_min = self.manifest.get(
            "target_first_pass_minutes" if kind == "task_first_pass"
            else "target_complete_minutes",
            0,
        )
        verdict = ""
        if target_min:
            ratio = (elapsed / 60) / target_min
            if ratio < 0.85:
                verdict = "[green]ahead of target[/green]"
            elif ratio <= 1.0:
                verdict = "[green]on target[/green]"
            elif ratio <= 1.25:
                verdict = "[yellow]over by " f"{(elapsed / 60) - target_min:.1f} min[/yellow]"
            else:
                verdict = (
                    f"[red]over by {(elapsed / 60) - target_min:.1f} min[/red]"
                )
        else:
            verdict = "[dim]no target set[/dim]"
        if kind == "task_first_pass":
            self.first_pass_recorded = True
        self.notify(
            f"{label.replace('_', ' ').title()}: "
            f"{elapsed / 60:.1f} min — {verdict}",
            timeout=4,
        )

    def _run(self, files: list[str], label: str) -> TestResult | None:
        if not files:
            self.query_one("#output-title", Static).update(
                "[yellow]No tests to run.[/yellow]"
            )
            return None
        self.query_one("#output-title", Static).update(
            f"[b]Running {label}…[/b]"
        )
        result = run_pytest(self.task_dir, files)
        self.last_result = result
        self._render_result(result, label)
        return result

    def _render_result(self, r: TestResult, label: str) -> None:
        head = (
            f"[b]{label}[/b]  "
            f"[green]{r.passed} passed[/green]  "
            f"[red]{r.failed} failed[/red]  "
            f"[yellow]{r.errors} errors[/yellow]  "
            f"[dim]({r.duration:.2f}s)[/dim]"
        )
        if r.all_green:
            head += "   [green]✓ all green[/green]"
        self.query_one("#output-title", Static).update(head)

        if r.failures:
            blocks = []
            for f in r.failures[:5]:
                msg = f["message"]
                if len(msg) > 1500:
                    msg = msg[:1500] + "…[truncated]"
                blocks.append(f"[b]{f['nodeid']}[/b]\n{msg}")
            body = "\n\n".join(blocks)
            if len(r.failures) > 5:
                body += f"\n\n[dim]…and {len(r.failures) - 5} more[/dim]"
            self.query_one("#output", Static).update(body)
        else:
            tail = (r.raw_stdout or "").strip().splitlines()
            tail_text = "\n".join(tail[-15:]) if tail else "[dim](no output)[/dim]"
            self.query_one("#output", Static).update(tail_text)

    def action_back(self) -> None:
        self.app.pop_screen()
