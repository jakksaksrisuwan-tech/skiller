from __future__ import annotations

import random
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ..content import load_freeforms, load_quiz_items, schedule_session
from ..models import MCQ, Freeform
from ..ui import StopwatchLabel


# Question state machine. (Freeform now renders as MCQ-style with auto-
# generated distractors; the typing/Input flow has been retired.)
S_PICKING = "picking"
S_CONFIDENCE = "confidence"
S_REVEALED = "revealed"

DISTRACTORS_PER_QUESTION = 3  # total choices = 1 canonical + 3 distractors


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
        self.cursor = 0  # display-position cursor
        self.state = S_PICKING
        self.user_correct = False
        self.q_started: float = 0.0
        self.correct_count = 0
        self.session_grades: list[int] = []
        # Per-question rendering data — populated in _show_question. For MCQ:
        # comes straight from the item. For Freeform: built from canonical +
        # distractors sampled from sibling Freeforms.
        self._choices: list[str] = []
        self._answer_idx: int = 0  # index of correct answer in self._choices
        # Distractor pool = ALL freeforms in this category (not just the
        # ~12 sampled for the session — that pool is too small to fill 3
        # distractors when only a handful are freeforms).
        self._distractor_pool: list[Freeform] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(" ", id="meta"),
            StopwatchLabel("⏱  00:00", id="watch", tick_seconds=0.5),
            Static(" ", id="prompt"),
            Static(" ", id="answer-area"),
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
        self._distractor_pool = load_freeforms(self.category)
        self.idx = 0
        self._show_question()

    # ------- rendering -------

    def _show_question(self) -> None:
        if self.idx >= len(self.items):
            self._finish()
            return
        item = self.items[self.idx]
        self.q_started = time.monotonic()
        self.state = S_PICKING
        self.cursor = 0

        srs = self.app.store.srs.get(item.id)  # type: ignore[attr-defined]
        if srs and srs.last_seen:
            sched = f"interval {srs.interval_days:.0f}d, ease {srs.ease:.2f}, reps {srs.reps}"
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
        self.set_focus(None)
        self._build_choices_for(item)
        self._render_choices()

    def _build_choices_for(self, item) -> None:
        """Populate `self._choices` + `self._answer_idx` for the current item.
        MCQ: shuffle the original choices. Freeform: take the canonical plus
        N distractors sampled from sibling Freeform canonicals in the session,
        then shuffle. Result: rendering and validation are identical for both
        kinds — no Input widget, no regex matching."""
        if isinstance(item, MCQ):
            pairs = list(enumerate(item.choices))
            random.shuffle(pairs)
            self._choices = [c for _, c in pairs]
            self._answer_idx = next(
                i for i, (orig_i, _) in enumerate(pairs) if orig_i == item.answer
            )
            return
        # Freeform — synthesize choices from the FULL category pool (not just
        # the session items — that pool is too small to reliably fill 3
        # distractors when only a few of the 12 sampled items are Freeforms).
        sibling_canonicals = [
            q.canonical for q in self._distractor_pool
            if q.id != item.id and q.canonical != item.canonical
        ]
        # Dedupe while preserving sample integrity.
        sibling_canonicals = list(dict.fromkeys(sibling_canonicals))
        k = min(DISTRACTORS_PER_QUESTION, len(sibling_canonicals))
        distractors = random.sample(sibling_canonicals, k=k) if k else []
        choices = [item.canonical] + distractors
        random.shuffle(choices)
        self._choices = choices
        self._answer_idx = choices.index(item.canonical)

    def _render_choices(self) -> None:
        lines = []
        for i, choice in enumerate(self._choices):
            marker = "▶" if i == self.cursor and self.state == S_PICKING else " "
            tag = ""
            if self.state == S_REVEALED:
                if i == self._answer_idx:
                    tag = "[green]✓[/green] "
                elif i == self.cursor and self.cursor != self._answer_idx:
                    tag = "[red]✗[/red] "
                else:
                    tag = "  "
            elif self.state == S_CONFIDENCE:
                tag = "[yellow]●[/yellow] " if i == self.cursor else "  "
            lines.append(f"{marker} [b]{i + 1}.[/b] {tag}{choice}")
        self.query_one("#answer-area", Static).update("\n".join(lines))

    def _ask_confidence(self) -> None:
        self.state = S_CONFIDENCE
        self._render_choices()
        self.query_one("#feedback", Static).update(
            "[b]How sure?[/b] press [b]1[/b]=guess … [b]5[/b]=certain"
        )

    # ------- input handlers -------

    def action_move(self, delta: int) -> None:
        if self.state != S_PICKING or not self._choices:
            return
        self.cursor = (self.cursor + delta) % len(self._choices)
        self._render_choices()

    def action_key(self, k: str) -> None:
        n = int(k)
        if self.state == S_PICKING:
            if 1 <= n <= len(self._choices):
                self.cursor = n - 1
                self._render_choices()
        elif self.state == S_CONFIDENCE:
            if 1 <= n <= 5:
                self._reveal(n)

    def action_confirm(self) -> None:
        if self.state == S_PICKING:
            self._lock_pick()
        elif self.state == S_REVEALED:
            self.idx += 1
            self._show_question()

    def _lock_pick(self) -> None:
        self.user_correct = self.cursor == self._answer_idx
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
        self._render_choices()

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
        self.query_one("#feedback", Static).update(
            "Press [b]Esc[/b] to return to menu."
        )

    def action_back(self) -> None:
        self.app.pop_screen()
