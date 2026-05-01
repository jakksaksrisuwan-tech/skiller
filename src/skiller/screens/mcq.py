from __future__ import annotations

import random
import re
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from ..content import load_quiz_items, schedule_session
from ..models import MCQ, Freeform
from ..ui import StopwatchLabel


S_PICKING = "picking"
S_TYPING = "typing"
S_CONFIDENCE = "confidence"
S_REVEALED = "revealed"


class MCQScreen(Screen):
    BINDINGS = [
        Binding("up,k", "move(-1)", "↑", show=False),
        Binding("down,j", "move(1)", "↓", show=False),
        Binding("enter", "confirm", "Confirm/Next"),
        Binding("1", "key('1')", "1", show=False),
        Binding("2", "key('2')", "2", show=False),
        Binding("3", "key('3')", "3", show=False),
        Binding("4", "key('4')", "4", show=False),
        Binding("5", "key('5')", "5", show=False),
        Binding("escape", "back", "Back"),
        Binding("q", "back", "Quit", show=False),
    ]

    def __init__(self, category: str, n: int = 25) -> None:
        super().__init__()
        self.category = category
        self.n = n
        self.items: list[MCQ | Freeform] = []
        self.idx = 0
        self.cursor = 0  # MCQ choice cursor
        self.state = S_PICKING
        self.user_text = ""
        self.user_correct = False
        self.q_started: float = 0.0
        self.correct_count = 0
        self.session_grades: list[int] = []
        self._perm: list[int] = []  # shuffled-choice permutation for current MCQ

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(" ", id="meta"),
            StopwatchLabel("⏱  00:00", id="watch", tick_seconds=0.5),
            Static(" ", id="prompt"),
            Static(" ", id="answer-area"),
            Static(" ", id="ff-slot"),
            Static(" ", id="feedback"),
            id="mcq-box",
        )
        yield Footer()

    def on_mount(self) -> None:
        items = load_quiz_items(self.category)
        if not items:
            self.notify(f"No items for skill={self.category}.", severity="error")
            self.app.pop_screen()
            return
        self.items = schedule_session(items, self.app.store, self.n)  # type: ignore[attr-defined]
        self.idx = 0
        self._show_question()

    # ------- rendering -------

    def _show_question(self) -> None:
        if self.idx >= len(self.items):
            self._finish()
            return
        item = self.items[self.idx]
        self.q_started = time.monotonic()
        self.state = S_TYPING if isinstance(item, Freeform) else S_PICKING
        self.cursor = 0
        self.user_text = ""

        srs = self.app.store.srs.get(item.id)  # type: ignore[attr-defined]
        if srs and srs.last_seen:
            days = srs.interval_days
            sched = f"interval {days:.0f}d, ease {srs.ease:.2f}, reps {srs.reps}"
        else:
            sched = "[dim]new[/dim]"
        kind_label = "FF" if isinstance(item, Freeform) else "MCQ"

        self.query_one("#meta", Static).update(
            f"[b]{item.skill.upper()}[/b] · {kind_label}   "
            f"Q {self.idx + 1}/{len(self.items)}   "
            f"score: {self.correct_count}/{self.idx}   "
            f"[dim]{sched}[/dim]"
        )
        self.query_one("#prompt", Static).update(f"[b]{item.prompt.strip()}[/b]")
        self.query_one("#feedback", Static).update(" ")
        # Remove any prior Input; mount fresh for Freeform.
        for old in self.query("Input"):
            old.remove()
        if isinstance(item, Freeform):
            self.query_one("#answer-area", Static).update(
                "[dim]Type answer. Enter when done.[/dim]"
            )
            inp = Input(placeholder="type answer...", id="ff-input")
            self.query_one("#ff-slot", Static).update(" ")
            self.mount(inp, after=self.query_one("#ff-slot"))
            self.set_focus(inp)
        else:
            self.set_focus(None)
            self._perm = list(range(len(item.choices)))
            random.shuffle(self._perm)
            self._render_choices(item)

    def _render_choices(self, q: MCQ) -> None:
        # display position i shows the original choice at index self._perm[i]
        display_answer = self._perm.index(q.answer) if self._perm else q.answer
        lines = []
        for i, orig_i in enumerate(self._perm or list(range(len(q.choices)))):
            c = q.choices[orig_i]
            marker = "▶" if i == self.cursor and self.state == S_PICKING else " "
            tag = ""
            if self.state in (S_CONFIDENCE, S_REVEALED):
                if self.state == S_REVEALED:
                    if i == display_answer:
                        tag = "[green]✓[/green] "
                    elif i == self.cursor and self.cursor != display_answer:
                        tag = "[red]✗[/red] "
                    else:
                        tag = "  "
                else:
                    if i == self.cursor:
                        tag = "[yellow]●[/yellow] "
                    else:
                        tag = "  "
            lines.append(f"{marker} [b]{i + 1}.[/b] {tag}{c}")
        self.query_one("#answer-area", Static).update("\n".join(lines))

    def _ask_confidence(self) -> None:
        self.state = S_CONFIDENCE
        item = self.items[self.idx]
        if isinstance(item, MCQ):
            self._render_choices(item)
        self.query_one("#feedback", Static).update(
            "[b]How sure?[/b] press [b]1[/b]=guess … [b]5[/b]=certain"
        )

    # ------- input handlers -------

    def action_move(self, delta: int) -> None:
        if self.state != S_PICKING:
            return
        item = self.items[self.idx]
        if not isinstance(item, MCQ):
            return
        self.cursor = (self.cursor + delta) % len(item.choices)
        self._render_choices(item)

    def action_key(self, k: str) -> None:
        n = int(k)
        if self.state == S_PICKING:
            item = self.items[self.idx]
            if isinstance(item, MCQ) and 1 <= n <= len(item.choices):
                self.cursor = n - 1
                self._render_choices(item)
        elif self.state == S_CONFIDENCE:
            if 1 <= n <= 5:
                self._reveal(n)

    def action_confirm(self) -> None:
        if self.state == S_PICKING:
            self._lock_pick()
        elif self.state == S_TYPING:
            self._lock_typed()
        elif self.state == S_REVEALED:
            self.idx += 1
            self._show_question()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.state == S_TYPING:
            self.user_text = event.value
            self._lock_typed()

    def _lock_pick(self) -> None:
        item = self.items[self.idx]
        if not isinstance(item, MCQ):
            return
        # cursor refers to display position; map back to original choice index
        chosen_orig = self._perm[self.cursor] if self._perm else self.cursor
        self.user_correct = chosen_orig == item.answer
        self._ask_confidence()

    def _lock_typed(self) -> None:
        item = self.items[self.idx]
        if not isinstance(item, Freeform):
            return
        if not self.user_text:
            try:
                self.user_text = self.query_one("#ff-input", Input).value
            except Exception:
                self.user_text = ""
        ans = self.user_text.strip()
        self.user_correct = any(
            re.match(p, ans, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            for p in item.patterns
        )
        # Remove input so digit keys reach screen bindings for confidence step.
        for old in self.query("Input"):
            old.remove()
        self.set_focus(None)
        self.query_one("#answer-area", Static).update(
            f"[b]you wrote:[/b]  {ans or '[dim](empty)[/dim]'}"
        )
        self._ask_confidence()

    def _reveal(self, confidence: int) -> None:
        item = self.items[self.idx]
        elapsed = time.monotonic() - self.q_started
        if self.user_correct:
            self.correct_count += 1
        grade = self.app.store.record(  # type: ignore[attr-defined]
            item_id=item.id,
            kind=item.kind,
            skill=item.skill,
            correct=self.user_correct,
            seconds=elapsed,
            confidence=confidence,
        )
        self.session_grades.append(grade)
        self.state = S_REVEALED
        if isinstance(item, MCQ):
            self._render_choices(item)
        else:
            ans = self.user_text.strip()
            mark = "[green]✓[/green]" if self.user_correct else "[red]✗[/red]"
            self.query_one("#answer-area", Static).update(
                f"[b]you wrote:[/b]  {ans or '[dim](empty)[/dim]'}  {mark}\n"
                f"[b]canonical:[/b]  [cyan]{item.canonical}[/cyan]"
            )

        verdict = "[green]Correct[/green]" if self.user_correct else "[red]Wrong[/red]"
        srs = self.app.store.srs[item.id]  # type: ignore[attr-defined]
        next_in = f"next review in {srs.interval_days:.0f}d (ease {srs.ease:.2f})"
        explain = item.explain or ""
        self.query_one("#feedback", Static).update(
            f"{verdict}  ({elapsed:.1f}s, conf {confidence}/5, grade {grade}/5)\n"
            f"[dim]{next_in}[/dim]\n"
            f"[dim]{explain}[/dim]\n"
            "[b]Enter[/b] for next."
        )

    # ------- exit -------

    def _finish(self) -> None:
        total = len(self.items)
        acc = self.correct_count / total if total else 0
        avg_grade = (
            sum(self.session_grades) / len(self.session_grades)
            if self.session_grades
            else 0
        )
        self.query_one("#meta", Static).update(
            f"[b]Done.[/b]  {self.correct_count}/{total}  ({acc:.0%})  avg grade {avg_grade:.1f}/5"
        )
        self.query_one("#prompt", Static).update(" ")
        self.query_one("#answer-area", Static).update(" ")
        for old in self.query("Input"):
            old.remove()
        self.query_one("#feedback", Static).update(
            "Press [b]Esc[/b] to return to menu."
        )

    def action_back(self) -> None:
        self.app.pop_screen()
