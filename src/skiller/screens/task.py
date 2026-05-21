from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static, TextArea

from ..models import Attempt
from ..test_runner import TestResult, run_pytest
from ..ui import StopwatchLabel


class TaskScreen(Screen):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+t", "run_visible", "Test (visible)", priority=True),
        Binding("ctrl+r", "run_main", "Run solution.py", priority=True),
        Binding("ctrl+g", "submit", "Submit (visible+hidden)", priority=True),
        Binding("ctrl+f", "focus_editor", "Edit", show=False),
        Binding("escape", "back", "Back", priority=True),
        Binding("ctrl+q", "back", "Quit", show=False),
        Binding("pageup", "scroll_output('page_up')", "Scroll output ↑", priority=True),
        Binding("pagedown", "scroll_output('page_down')", "Scroll output ↓", priority=True),
        Binding("ctrl+up", "scroll_output('up')", "Output line ↑", show=False, priority=True),
        Binding("ctrl+down", "scroll_output('down')", "Output line ↓", show=False, priority=True),
        Binding("f5", "resize_split(5)", "wider prompt", priority=True),
        Binding("f6", "resize_split(-5)", "wider editor", priority=True),
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
        # Probe-visible mirrors of #output-title / #output (Static.renderable
        # isn't reliably introspectable across Textual versions).
        self._output_title_text: str = ""
        self._output_text: str = ""
        self._prompt_pct: int = 50  # split ratio, adjustable via F5/F6
        self._initial_solution = (
            self.solution_path.read_text(encoding="utf-8")
            if self.solution_path.exists() else ""
        )

    def dev_state(self) -> dict:
        out: dict = {
            "task_dir": str(self.task_dir),
            "task_id": self.task_dir.name,
            "submitted": self.submitted,
            "started": self.started > 0,
        }
        try:
            ed = self.query_one("#editor", TextArea)
            out["editor_text"] = ed.text
            out["editor_chars"] = len(ed.text)
        except Exception:
            out["editor_text"] = None
            out["editor_chars"] = None
        out["output_title"] = self._output_title_text
        out["output_text"] = self._output_text
        if self.last_result is not None:
            r = self.last_result
            out["last_result"] = {
                "passed": r.passed,
                "failed": r.failed,
                "errors": r.errors,
                "duration": r.duration,
                "ok": r.all_green,
            }
        return out

    @staticmethod
    def _make_editor(text: str) -> TextArea:
        """Build a TextArea, degrading gracefully if syntax highlighting deps
        (`textual[syntax]` / tree-sitter) aren't installed."""
        # 1) Best: code_editor with python highlighting + dark theme.
        for theme in ("monokai", "dracula", "vscode_dark", None):
            try:
                kwargs = {"language": "python", "id": "editor"}
                if theme:
                    kwargs["theme"] = theme
                return TextArea.code_editor(text, **kwargs)
            except Exception:
                continue
        # 2) code_editor without language (line numbers + indent behaviour).
        try:
            return TextArea.code_editor(text, id="editor")
        except Exception:
            pass
        # 3) Plain TextArea — works on any Textual version.
        return TextArea(text, id="editor")

    def compose(self) -> ComposeResult:
        yield Header()
        editor = self._make_editor(self._initial_solution)
        yield Vertical(
            Static(" ", id="task-meta"),
            StopwatchLabel("⏱  00:00", id="task-watch"),
            Horizontal(
                Vertical(
                    Markdown(
                        (self.task_dir / "prompt.md").read_text(encoding="utf-8"),
                        id="prompt-md",
                    ),
                    id="prompt-pane",
                ),
                Vertical(
                    editor,
                    id="editor-pane",
                ),
                id="task-split",
            ),
            Static(" ", id="output-title"),
            VerticalScroll(Static(" ", id="output"), id="output-scroll"),
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
        self._set_output_title(
            "[dim][b]ctrl+s[/b] save · [b]ctrl+t[/b] run visible · "
            "[b]ctrl+r[/b] run solution.py · [b]ctrl+g[/b] submit · "
            "[b]esc[/b] back[/dim]"
        )
        self._set_output(f"[b]solution.py[/b] — {self.solution_path}")
        self.query_one("#editor", TextArea).focus()

    def _set_output_title(self, text: str) -> None:
        self._output_title_text = text
        self.query_one("#output-title", Static).update(text)

    def _set_output(self, text: str) -> None:
        self._output_text = text
        self.query_one("#output", Static).update(text)

    # ---- actions ----

    def _save_editor(self) -> None:
        text = self.query_one("#editor", TextArea).text
        self.solution_path.write_text(text, encoding="utf-8")

    def action_save(self) -> None:
        self._save_editor()
        self.notify("Saved.", timeout=1.2)

    def action_focus_editor(self) -> None:
        self.query_one("#editor", TextArea).focus()

    def action_run_main(self) -> None:
        self._save_editor()
        self._set_output_title("[b]Running solution.py…[/b]")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.task_dir) + os.pathsep + env.get("PYTHONPATH", "")
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        try:
            proc = subprocess.run(
                [sys.executable, str(self.solution_path)],
                cwd=self.task_dir, env=env, capture_output=True, text=True,
                timeout=10,
            )
            rc = proc.returncode
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            rc = -1
            stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = (
                (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""))
                + "\n[timeout after 10s]"
            )
        self._render_run_main(rc, stdout, stderr)

    def _render_run_main(self, rc: int, stdout: str, stderr: str) -> None:
        verdict = "[green]exit 0[/green]" if rc == 0 else f"[red]exit {rc}[/red]"
        self._set_output_title(f"[b]run solution.py[/b]  {verdict}")
        sections: list[str] = []
        out_lines = [ln for ln in stdout.splitlines() if True]
        while out_lines and not out_lines[-1].strip():
            out_lines.pop()
        err_lines = [ln for ln in stderr.splitlines() if ln.strip()]
        if out_lines:
            sections.append("[dim]── stdout ──[/dim]\n" + "\n".join(out_lines[-30:]))
        if err_lines:
            sections.append("[dim]── stderr ──[/dim]\n" + "\n".join(err_lines[-30:]))
        if not sections:
            sections.append("[dim](no output)[/dim]")
        self._set_output("\n\n".join(sections))

    def action_run_visible(self) -> None:
        self._save_editor()
        result = self._run(self.manifest.get("visible_tests", []), label="visible")
        if (
            result is not None
            and result.all_green
            and not self.first_pass_recorded
        ):
            self._record_milestone("task_first_pass", "first_pass")

    def action_submit(self) -> None:
        self._save_editor()
        all_files = list(self.manifest.get("visible_tests", [])) + list(
            self.manifest.get("hidden_tests", [])
        )
        if not all_files:
            self._set_output_title("[yellow]No tests defined.[/yellow]")
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
            self._set_output_title("[yellow]No tests to run.[/yellow]")
            return None
        self._set_output_title(f"[b]Running {label}…[/b]")
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
        self._set_output_title(head)

        stdout_tail = [
            ln for ln in (r.raw_stdout or "").splitlines()
            if not ln.startswith("__SKILLER_RESULT__")
        ]
        while stdout_tail and not stdout_tail[-1].strip():
            stdout_tail.pop()
        stderr_tail = [ln for ln in (r.raw_stderr or "").splitlines() if ln.strip()]

        sections: list[str] = []
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
            sections.append(body)
        if stdout_tail:
            sections.append("[dim]── stdout ──[/dim]\n" + "\n".join(stdout_tail[-15:]))
        if stderr_tail:
            sections.append("[dim]── stderr ──[/dim]\n" + "\n".join(stderr_tail[-15:]))
        if not sections:
            sections.append("[dim](no output)[/dim]")
        self._set_output("\n\n".join(sections))

    def action_resize_split(self, delta: int) -> None:
        # delta < 0: shrink prompt (editor grows). Clamp to [20, 80].
        new_pct = max(20, min(80, self._prompt_pct + delta))
        if new_pct == self._prompt_pct:
            return
        self._prompt_pct = new_pct
        self.query_one("#prompt-pane").styles.width = f"{new_pct}%"
        self.query_one("#editor-pane").styles.width = f"{100 - new_pct}%"

    def action_scroll_output(self, mode: str) -> None:
        try:
            sv = self.query_one("#output-scroll", VerticalScroll)
        except Exception:
            return
        if mode == "page_up":
            sv.scroll_page_up(animate=False)
        elif mode == "page_down":
            sv.scroll_page_down(animate=False)
        elif mode == "up":
            sv.scroll_up(animate=False)
        elif mode == "down":
            sv.scroll_down(animate=False)

    def action_back(self) -> None:
        self.app.pop_screen()
