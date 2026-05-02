"""Structure-driven typing drill — keybr-style picker, snippet-level scoring."""
from __future__ import annotations

import time

from rich.markup import escape as _escape_markup
from rich.text import Text

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ..achievements import TIER_GLYPH, check_unlocks
from ..content import load_snippets, pick_snippet
from ..models import TypingSnippet
from ..ui import progress_bar as _bar


# 7-segment LCD style digits, 3 lines tall, 3 chars wide.
_LCD = {
    "0": (" _ ", "| |", "|_|"),
    "1": ("   ", "  |", "  |"),
    "2": (" _ ", " _|", "|_ "),
    "3": (" _ ", " _|", " _|"),
    "4": ("   ", "|_|", "  |"),
    "5": (" _ ", "|_ ", " _|"),
    "6": (" _ ", "|_ ", "|_|"),
    "7": (" _ ", "  |", "  |"),
    "8": (" _ ", "|_|", "|_|"),
    "9": (" _ ", "|_|", " _|"),
    " ": ("   ", "   ", "   "),
    "-": ("   ", " _ ", "   "),
}


def _lcd(s: str) -> str:
    """Compact 7-seg digits: 3 chars wide, 3 lines tall, no separator.
    Rows are kept exactly equal length (no rstrip) so alignment doesn't drift
    on digits whose lower row ends in a non-space char (e.g. '5' → '_|')."""
    rows = ["", "", ""]
    for ch in s:
        for i, line in enumerate(_LCD.get(ch, _LCD[" "])):
            rows[i] += line
    return "\n".join(rows)


class TypingScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("f1", "toggle_scoreboard", "Scoreboard"),
        Binding("f2", "next", "Skip"),
        Binding("f3", "achievements", "Achievements"),
        Binding("f4", "toggle_correction", "Correction mode"),
    ]

    QUEUE_DEPTH = 3  # snippets shown below current as upcoming preview

    def __init__(self, language: str = "python") -> None:
        super().__init__()
        self.language = language
        self.snippets = load_snippets(language)
        self.current = None      # type: ignore[var-annotated]
        self.queue: list = []    # type: ignore[var-annotated]
        self.target: str = ""
        self.cursor: int = 0
        self.wrong_at: dict[int, int] = {}  # position → wrong-attempt count (1 or 2)
        self.errors_this_run: int = 0
        self.corrections_this_run: int = 0       # wrong_at marks cleared in this snippet
        self.skipped_recoveries_this_run: int = 0  # subset: cleared after auto-advance
        self.started_at: float = 0.0
        self.last_keystroke_at: float = 0.0
        self.session_completions: int = 0
        self.session_chars: int = 0
        self.session_errors: int = 0
        self.session_ms: float = 0.0
        self.last_completion_wpm: float = 0.0
        self.last_completion: dict | None = None  # persistent pill data
        self.flash_style: str | None = None        # transient colour for done line
        self.session_chain: int = 0     # consecutive ≥40 wpm completions
        self.session_best_chain: int = 0
        self.session_clean_streak: int = 0          # consecutive 100% acc drills
        self.session_best_clean_streak: int = 0
        self.session_distinct_structures: set[str] = set()
        self.session_started_real: float = 0.0       # set on first keystroke
        # Rolling WPM window: list of per-completion wpm values (last 10).
        self.recent_wpm: list[float] = []
        self.correction_mode: bool = False  # F4 toggle
        self._drill_cursor: int = 0  # round-robin index for correction drills
        self.show_scoreboard: bool = False  # collapsed by default

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Horizontal(
                Static(" ", id="typing-meta"),
                Static(" ", id="typing-lcd"),
                id="typing-top",
            ),
            Static(" ", id="typing-done"),
            Static(" ", id="typing-description"),
            Static(" ", id="typing-snippet"),
            Static(" ", id="typing-upcoming"),
            Static(" ", id="typing-stats"),
            Static(" ", id="typing-scoreboard"),
            Static(
                "[dim]Type the snippet exactly. "
                "Backspace corrects (errors stay counted).\n"
                "Esc back · F1 scoreboard · F2 skip · F3 achievements · F4 correction.[/dim]",
                id="typing-help",
            ),
            id="typing-box",
        )
        yield Footer()

    def on_mount(self) -> None:
        if not self.snippets:
            self.notify("No typing snippets found.", severity="error")
            self.app.pop_screen()
            return
        self._apply_scoreboard_visibility()
        self._next_snippet()

    def _apply_scoreboard_visibility(self) -> None:
        try:
            self.query_one("#typing-scoreboard", Static).display = self.show_scoreboard
        except Exception:
            pass

    def action_toggle_scoreboard(self) -> None:
        self.show_scoreboard = not self.show_scoreboard
        self._apply_scoreboard_visibility()
        if self.show_scoreboard:
            self._refresh_scoreboard()

    # ---- snippet lifecycle ----

    def _fill_queue(self) -> None:
        """Top up the upcoming-snippets queue. In correction mode, queue is
        filled with synthetic bigram drills instead of real snippets."""
        store = self.app.store  # type: ignore[attr-defined]
        if self.correction_mode:
            drills = self._build_correction_drills(store)
            if not drills:
                # No struggle data yet — fall back to normal sampling.
                self.correction_mode = False
            else:
                while len(self.queue) < self.QUEUE_DEPTH:
                    self.queue.append(drills[self._drill_cursor % len(drills)])
                    self._drill_cursor += 1
                return
        for _ in range(20):
            if len(self.queue) >= self.QUEUE_DEPTH:
                return
            snip = pick_snippet(self.snippets, store)
            if snip is None:
                return
            visible_ids = {q.id for q in self.queue}
            if self.current is not None:
                visible_ids.add(self.current.id)
            if snip.id in visible_ids:
                continue
            self.queue.append(snip)

    def _build_correction_drills(self, store) -> list:
        """Synthesize drill snippets from the user's *currently* slow bigrams.
        Bigrams whose EMA avg_ms drops below the graduation threshold are
        excluded — as the user gets faster, drills disappear, and when none
        remain, correction mode auto-exits with a celebration."""
        graduation = store.typing_graduation_ms()
        top = store.top_struggle_bigrams(n=6, graduation_ms=graduation)
        if not top:
            return []
        drills = []
        for bg, _avg_ms, _err in top:
            drills.append(TypingSnippet(
                id=f"drill-spaced-{bg}",
                structure=f"drill[{bg}]",
                text=" ".join([bg] * 8),
                language=self.language,
                difficulty=1,
            ))
            drills.append(TypingSnippet(
                id=f"drill-tight-{bg}",
                structure=f"drill[{bg}]",
                text=bg * 8,
                language=self.language,
                difficulty=1,
            ))
        return drills

    def _next_snippet(self) -> None:
        # Pull next from queue; refill behind it so preview stays full.
        self._fill_queue()
        if not self.queue:
            self.app.pop_screen()
            return
        snip = self.queue.pop(0)
        self._fill_queue()
        self.current = snip
        self.target = snip.text
        self._reset_run_state()
        self._refresh_view()

    def _reset_run_state(self) -> None:
        self.cursor = 0
        self.wrong_at = {}
        self.errors_this_run = 0
        self.corrections_this_run = 0
        self.skipped_recoveries_this_run = 0
        self.started_at = 0.0
        self.last_keystroke_at = 0.0

    def _refresh_view(self) -> None:
        snip = self.current
        if snip is None:
            return
        store = self.app.store  # type: ignore[attr-defined]
        stat = store.structures.get(snip.structure)
        # Structure names can contain markup-special chars (e.g. drill bigrams
        # like '/e' or ']'), so escape before interpolating into a markup string.
        struct = _escape_markup(snip.structure)
        if stat and stat.completions:
            head = (
                f"[b]{struct}[/b]   "
                f"[dim]wpm {stat.wpm:.0f}  acc {stat.accuracy:.0%}  "
                f"runs {stat.completions}[/dim]"
            )
        else:
            head = f"[b]{struct}[/b]   [dim]new structure[/dim]"
        if self.correction_mode:
            head += "   [yellow]🎯 correction[/yellow]"
        self.query_one("#typing-meta", Static).update(head)
        self.query_one("#typing-lcd", Static).update(self._render_lcd())
        self.query_one("#typing-done", Static).update(self._render_done())
        # Description annotates the just-typed snippet shown above (done line),
        # not the current one — explanation lands AFTER you read the command.
        last_desc = (
            self.last_completion.get("description", "")
            if self.last_completion else ""
        )
        self.query_one("#typing-description", Static).update(
            Text.assemble(("↳ ", "dim italic"), (last_desc, "dim italic"))
            if last_desc else " "  # never pass "" to Static.update — see above
        )
        self.query_one("#typing-snippet", Static).update(self._render_target())
        self.query_one("#typing-upcoming", Static).update(self._render_upcoming())
        self.query_one("#typing-stats", Static).update(self._render_stats())
        # Scoreboard / lcd / description / done / upcoming all change only at
        # snippet boundaries — they're already covered above for the snippet-
        # swap path. Per-keystroke updates use `_refresh_live` instead.

    def _refresh_live(self) -> None:
        """Per-keystroke refresh — only widgets that change with the cursor."""
        if self.current is None:
            return
        self.query_one("#typing-snippet", Static).update(self._render_target())
        self.query_one("#typing-stats", Static).update(self._render_stats())

    def _refresh_scoreboard(self) -> None:
        if self.show_scoreboard:
            self.query_one("#typing-scoreboard", Static).update(
                self._render_scoreboard()
            )

    def _render_target(self) -> Text:
        """Per-position colouring:
        - typed correctly + clean         → green
        - typed but had ≥1 wrong attempt  → red (mistake kept visible)
        - cursor + no wrong yet           → reverse yellow
        - cursor + wrong attempt(s) here  → reverse red (warn before second try)
        - upcoming                        → dim
        """
        text = Text()
        for i, ch in enumerate(self.target):
            wrong_count = self.wrong_at.get(i, 0)
            if i < self.cursor:
                style = "red" if wrong_count > 0 else "green"
                text.append(" " if ch == " " and wrong_count else ch, style=style)
                # whitespace at error positions: keep it — terminal still shows the gap
                continue
            if i == self.cursor:
                glyph = "·" if ch == " " else (ch or "↵")
                if wrong_count >= 1:
                    text.append(glyph, style="reverse red")
                else:
                    text.append(glyph, style="reverse yellow")
                continue
            # rest
            text.append(ch, style="dim")
        return text

    def _render_lcd(self) -> str:
        """Rolling-average WPM in 7-segment style (3 lines, 9 cols).
        Label dropped — context implies WPM. '---' when no data yet."""
        if not self.recent_wpm:
            digits = "---"
        else:
            avg = sum(self.recent_wpm) / len(self.recent_wpm)
            digits = f"{int(round(min(999, avg))):03d}"
        return _lcd(digits)

    def _render_done(self) -> Text:
        if not self.last_completion:
            return Text(" ")  # single space — Textual 8.2 has a render-None
                              # bug on completely empty Text content
        lc = self.last_completion
        body = lc.get("text", "")
        marker = lc.get("marker", "")
        text = Text()
        if self.flash_style and "on " in self.flash_style:
            # Strobe state: render as a full-width attention bar.
            chevrons = "▶ "
            content = chevrons + marker + body
            text.append(content, style=self.flash_style)
            # pad to a generous width so the bg color spans the visible line
            text.append(" " * max(0, 120 - len(content)), style=self.flash_style)
        else:
            if marker:
                text.append(marker, style=self.flash_style or "dim green")
            text.append(body, style=self.flash_style or "dim grey50")
        return text

    def _render_upcoming(self) -> Text:
        if not self.queue:
            return Text(" ")  # avoid Textual 8.2 empty-content render bug
        text = Text()
        # graduated dimming: closer = brighter, further = more subdued
        styles = ["dim", "dim grey50", "dim grey39"]
        for i, snip in enumerate(self.queue[: self.QUEUE_DEPTH]):
            style = styles[i] if i < len(styles) else "dim grey39"
            text.append(snip.text, style=style)
            if i < min(len(self.queue), self.QUEUE_DEPTH) - 1:
                text.append("\n")
        return text

    def _render_stats(self) -> str:
        elapsed = (
            time.monotonic() - self.started_at if self.started_at else 0.0
        )
        chars_done = self.cursor
        wpm = (chars_done / 5) / (elapsed / 60) if elapsed > 0 and chars_done else 0
        acc = chars_done / (chars_done + self.errors_this_run) if (chars_done + self.errors_this_run) else 1.0
        return (
            f"wpm [b]{wpm:.0f}[/b]   "
            f"acc [b]{acc:.0%}[/b]   "
            f"errors [b]{self.errors_this_run}[/b]   "
            f"⏱ {elapsed:.1f}s"
        )

    def _render_scoreboard(self) -> str:
        store = self.app.store  # type: ignore[attr-defined]
        # Floating personal target — grows as user improves.
        target_wpm = store.typing_personal_target()
        # Session
        session_avg = (
            (self.session_chars / 5) / (self.session_ms / 1000 / 60)
            if self.session_ms > 0 and self.session_chars > 0 else 0
        )
        session_acc = (
            self.session_chars / (self.session_chars + self.session_errors)
            if (self.session_chars + self.session_errors) else 1.0
        )
        session_best = self.last_completion_wpm  # peak single drill this session
        chain_part = (
            f"   chain [b]{self.session_chain}[/b]"
            f"[dim]/best {self.session_best_chain}[/dim]"
            f"{' 🔥' if self.session_chain >= 3 else ''}"
        )
        session_line = (
            f"[b]session[/b]   "
            f"drills [b]{self.session_completions}[/b]   "
            f"avg [b]{session_avg:.0f}[/b] wpm   "
            f"best [b]{session_best:.0f}[/b] wpm   "
            f"acc [b]{session_acc:.0%}[/b]"
            f"{chain_part}"
        )
        # All-time PR + total
        pr_struct, pr_wpm = store.typing_personal_record()
        total = store.typing_total_drills()
        overall = store.typing_overall_wpm()
        if total == 0:
            pr_line = "[dim]no completions yet — first drill = your PR[/dim]"
        else:
            pr_line = (
                f"[b]all-time[/b]   "
                f"total [b]{total}[/b]   "
                f"overall [b]{overall:.0f}[/b] wpm   "
                f"PR [green]{pr_wpm:.0f}[/green] wpm on [b]{pr_struct}[/b]"
            )
        # Focus
        focus = store.typing_focus_structure(target_wpm)
        if focus is None:
            focus_line = (
                "[b]focus[/b]   "
                "[dim]complete a drill to surface your weakest structure[/dim]"
            )
        else:
            name, wpm = focus
            gap = max(0, target_wpm - wpm)
            bar = _bar(min(1.0, wpm / target_wpm))
            focus_line = (
                f"[b]focus[/b]   "
                f"weakest [yellow]{_escape_markup(name)}[/yellow] "
                f"[dim]{bar}[/dim] "
                f"[b]{wpm:.0f}[/b]/{target_wpm:.0f} wpm "
                f"([yellow]+{gap:.0f}[/yellow] to target)"
            )
        # User tier indicator (1=basics, 2=intermediate, 3=advanced)
        user_tier = store.typing_user_tier()
        tier_glyph = "▮" * user_tier + "▯" * (3 - user_tier)
        # Today vs yesterday + streak
        today_min = store.typing_minutes_on(0)
        yesterday_min = store.typing_minutes_on(1)
        streak = store.typing_streak_days()
        if today_min > yesterday_min and yesterday_min > 0:
            arrow = "[green]↑[/green]"
        elif today_min < yesterday_min:
            arrow = "[yellow]↓[/yellow]"
        else:
            arrow = "—"
        streak_glyph = "🔥" if streak >= 3 else "·"
        today_line = (
            f"[b]today[/b]   "
            f"{today_min:.1f} min   "
            f"[dim](yest {yesterday_min:.1f})[/dim] {arrow}   "
            f"streak [b]{streak}[/b]d {streak_glyph}   "
            f"[dim]tier[/dim] [b]{tier_glyph}[/b]"
        )
        # Struggle bigrams — surface the user's slowest 2-char sequences.
        top_bg = store.top_struggle_bigrams(n=5)
        if top_bg:
            parts = [
                f"[b]{_escape_markup(repr(bg))}[/b] {ms:.0f}ms"
                + (f"+{err}e" if err else "")
                for bg, ms, err in top_bg
            ]
            mode_tag = (
                " [yellow]🎯 ON[/yellow]" if self.correction_mode else " [dim](F4 to drill)[/dim]"
            )
            struggle_line = "[b]struggle[/b]   " + "  ".join(parts) + mode_tag
        else:
            struggle_line = (
                "[b]struggle[/b]   "
                "[dim]not enough data yet — keep typing[/dim]"
            )
        return "\n".join([session_line, pr_line, focus_line, today_line, struggle_line])

    # ---- key handling ----

    async def on_key(self, event: events.Key) -> None:
        # Handle bindings first by letting Textual process them, then snipe printable.
        if event.key in ("escape", "f1", "f2", "f3", "f4"):
            return  # let bindings handle
        # Modifier-only / nav keys must NOT count as wrong keystrokes —
        # users hit Tab to switch panes, Ctrl/Alt for IDE shortcuts, etc.
        # Shift+letter is allowed (it's how you type capitals); the prefix
        # filter below catches "shift+tab" / "shift+enter" / etc., which
        # arrive with explicit modifier names.
        key = event.key
        if (
            key in ("tab", "shift+tab", "enter", "left", "right", "up", "down",
                    "home", "end", "pageup", "pagedown", "insert", "delete")
            or key.startswith(("ctrl+", "alt+", "meta+", "super+", "cmd+"))
        ):
            return
        now = time.monotonic()
        if event.key == "backspace":
            # First-wrong: red mark sits at cursor — clear it, cursor stays.
            # Second-wrong: cursor auto-advanced past the red mark; first
            # backspace pulls back onto the red and clears it.
            # No nearby red: fall through to plain cursor-1 navigation.
            if self.cursor in self.wrong_at:
                del self.wrong_at[self.cursor]
            elif (self.cursor - 1) in self.wrong_at:
                self.cursor -= 1
                del self.wrong_at[self.cursor]
            elif self.cursor > 0:
                self.cursor -= 1
            self._refresh_live()
            event.stop()
            return
        ch = event.character
        if ch is None or len(ch) != 1:
            return
        # Treat enter as completing a snippet only if cursor is at end.
        # But our snippets are single-line — Enter while still typing = error.
        if self.started_at == 0.0:
            self.started_at = now
            self.last_keystroke_at = now
            if self.session_started_real == 0.0:
                self.session_started_real = now

        expected = self.target[self.cursor : self.cursor + 1]
        if expected == "":
            return
        if ch == expected:
            dt_ms = max(0.0, (now - self.last_keystroke_at) * 1000)
            if dt_ms > 3000:
                dt_ms = 3000
            self.session_ms += dt_ms
            self.session_chars += 1
            # Bigram timing: how long to type the 2nd char of (prev, current)?
            # Only count when prev was also typed within this snippet (cursor>=1).
            if self.cursor >= 1:
                bigram = self.target[self.cursor - 1 : self.cursor + 1]
                self.app.store.record_bigram_time(bigram, dt_ms)  # type: ignore[attr-defined]
            prior_wrong = self.wrong_at.pop(self.cursor, 0)
            if prior_wrong >= 1:
                self.corrections_this_run += 1
                if prior_wrong >= 2:
                    self.skipped_recoveries_this_run += 1
            self.cursor += 1
            self.last_keystroke_at = now
            if self.cursor >= len(self.target):
                self._complete(now)
            else:
                self._refresh_live()
        else:
            self.errors_this_run += 1
            self.session_errors += 1
            self.wrong_at[self.cursor] = self.wrong_at.get(self.cursor, 0) + 1
            if self.cursor >= 1:
                bigram = self.target[self.cursor - 1 : self.cursor + 1]
                self.app.store.record_bigram_error(bigram)  # type: ignore[attr-defined]
            # First wrong: stay put, mark red — user can retry.
            # Second wrong: auto-advance past this char so user isn't stuck.
            #   The position stays red as a permanent record. Backspace returns.
            if self.wrong_at[self.cursor] >= 2:
                self.cursor += 1
                if self.cursor >= len(self.target):
                    self._complete(now)
                    event.stop()
                    return
            self._refresh_live()
        event.stop()

    def _complete(self, now: float) -> None:
        snip = self.current
        if snip is None:
            return
        chars = len(self.target)
        elapsed = now - self.started_at
        elapsed_ms = max(1.0, elapsed * 1000)
        wpm = (chars / 5) / (elapsed / 60) if elapsed > 0 else 0.0
        store = self.app.store  # type: ignore[attr-defined]
        prior = store.structures.get(snip.structure)
        prior_struct_pr = prior.best_wpm if prior else 0.0
        prior_overall_pr_pair = store.typing_personal_record()
        prior_overall_pr = prior_overall_pr_pair[1] if prior_overall_pr_pair else 0.0
        # Synthetic correction drills should not pollute per-structure stats;
        # the bigram-level data they generate (recorded per keystroke) is the
        # actual learning signal for those.
        if snip.is_synthetic_drill:
            store.total_drill_completions += 1
        else:
            store.record_typing(
                structure=snip.structure,
                item_id=snip.id,
                chars=chars,
                errors=self.errors_this_run,
                ms=elapsed_ms,
            )
        store.total_corrections += self.corrections_this_run
        store.total_skipped_recoveries += self.skipped_recoveries_this_run
        self.session_completions += 1
        self.last_completion_wpm = wpm
        self.session_distinct_structures.add(snip.structure)
        if self.errors_this_run == 0:
            self.session_clean_streak += 1
            if self.session_clean_streak > self.session_best_clean_streak:
                self.session_best_clean_streak = self.session_clean_streak
        else:
            self.session_clean_streak = 0
        # rolling window of last 10 completions for the LCD display
        self.recent_wpm.append(wpm)
        if len(self.recent_wpm) > 10:
            self.recent_wpm = self.recent_wpm[-10:]
        # Chain threshold floats with user's personal target. Threshold = 80%
        # of their current target wpm, never below 40 (the absolute floor).
        target_wpm = store.typing_personal_target()
        chain_threshold = max(40.0, target_wpm * 0.8)
        if wpm >= chain_threshold:
            self.session_chain += 1
            if self.session_chain > self.session_best_chain:
                self.session_best_chain = self.session_chain
        else:
            self.session_chain = 0
        # tier the celebration on realistic ranges
        clean = self.errors_this_run == 0
        is_exceptional = wpm >= 60       # 60+ wpm is exceptional
        is_target = 40 <= wpm < 60       # 40-60 is target
        struct_pr = wpm > prior_struct_pr and prior_struct_pr > 0
        overall_pr = wpm > prior_overall_pr and prior_overall_pr > 0
        chain_suffix = (
            f"  🔥 {self.session_chain} in a row"
            if self.session_chain >= 3 else ""
        )
        # 3-cycle full-width strobe for clean target+ runs; gentle one-shot otherwise.
        strobe = False
        strobe_cycles = 3
        if overall_pr and clean:
            marker = f"★ NEW PR!{chain_suffix}  "
            flash_style = "bold black on bright_yellow"
            flash_ms = 600
            strobe = True
            strobe_cycles = 4  # extra-loud
        elif is_exceptional and clean:
            marker = f"★ EXCEPTIONAL{chain_suffix}  "
            flash_style = "bold black on yellow"
            flash_ms = 500
            strobe = True
        elif struct_pr and clean:
            marker = f"★ structure PR{chain_suffix}  "
            flash_style = "bold black on green"
            flash_ms = 400
            strobe = True
        elif is_target and clean:
            marker = f"✓ on target{chain_suffix}  "
            flash_style = "bold black on green"
            flash_ms = 250
            strobe = True
        elif clean:
            marker = "✓ clean  "
            flash_style = "dim green"
            flash_ms = 150
        elif self.errors_this_run <= 2:
            marker = ""
            flash_style = "dim green"
            flash_ms = 100
        else:
            marker = ""
            flash_style = "grey50"
            flash_ms = 80
        self.last_completion = {
            "structure": snip.structure,
            "text": snip.text,
            "description": snip.description,
            "wpm": wpm,
            "acc": chars / (chars + self.errors_this_run)
                if (chars + self.errors_this_run) else 1.0,
            "errors": self.errors_this_run,
            "marker": marker,
        }
        if strobe:
            self._begin_strobe(flash_style, cycles=strobe_cycles, period_s=0.13)
        else:
            self.flash_style = flash_style
            self.set_timer(flash_ms / 1000, self._end_flash)
        # Scoreboard depends on lifetime/today data — recompute only here.
        self._refresh_scoreboard()
        # If we were drilling and the user has now graduated every slow bigram,
        # exit correction mode with a celebration.
        pool_just_cleared = False
        if self.correction_mode:
            graduation = store.typing_graduation_ms()
            remaining = store.top_struggle_bigrams(n=1, graduation_ms=graduation)
            if not remaining:
                self.correction_mode = False
                store.total_pool_clears += 1
                pool_just_cleared = True
                self.notify(
                    "🏁 every struggle bigram graduated! "
                    "correction mode off — back to weakness sampling.",
                    timeout=5,
                )
                self.queue.clear()
                self._fill_queue()
        # check achievements; toast each newly unlocked
        session_minutes = (
            (time.monotonic() - self.session_started_real) / 60
            if self.session_started_real else 0.0
        )
        unlocked = check_unlocks(
            store,
            {
                "chain": self.session_chain,
                "session_best_chain": self.session_best_chain,
                "session_completions": self.session_completions,
                "session_clean_streak": self.session_clean_streak,
                "session_best_clean_streak": self.session_best_clean_streak,
                "session_distinct_structures": len(self.session_distinct_structures),
                "session_minutes": session_minutes,
                "brave_soul_session": self.errors_this_run >= 5,
                "corrections_this_run": self.corrections_this_run,
                "skipped_recovery_this_run": self.skipped_recoveries_this_run >= 1,
                "is_drill_completion": snip.is_synthetic_drill,
                "pool_just_cleared": pool_just_cleared,
            },
        )
        for ach in unlocked:
            glyph = TIER_GLYPH.get(ach.tier, "🏆")
            self.notify(
                f"{glyph} [b]{ach.name}[/b] — {ach.desc}",
                title="Achievement unlocked",
                timeout=4,
            )
        self._next_snippet()

    def _end_flash(self) -> None:
        self.flash_style = None
        self._refresh_view()

    def _begin_strobe(self, on_style: str, cycles: int = 3, period_s: float = 0.13) -> None:
        """Strobe the done line N cycles. Each cycle = on→off pair."""
        self._strobe_step(cycles * 2, on_style, period_s)

    def _strobe_step(self, phases_left: int, on_style: str, period_s: float) -> None:
        if phases_left <= 0:
            self.flash_style = None
            try:
                self._refresh_view()
            except Exception:
                pass
            return
        self.flash_style = on_style if (phases_left % 2 == 1) else None
        try:
            self._refresh_view()
        except Exception:
            return
        self.set_timer(period_s, lambda: self._strobe_step(
            phases_left - 1, on_style, period_s))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_next(self) -> None:
        self._next_snippet()

    def action_achievements(self) -> None:
        from .achievements import AchievementsScreen
        self.app.push_screen(AchievementsScreen())

    def action_toggle_correction(self) -> None:
        store = self.app.store  # type: ignore[attr-defined]
        if not self.correction_mode:
            # Turning ON — verify there's struggle data, otherwise refuse.
            top = store.top_struggle_bigrams(n=5)
            if not top:
                self.notify(
                    "Need more typing data first — top struggle bigrams "
                    "appear after ~5 samples each.",
                    timeout=3,
                )
                return
            self.correction_mode = True
            self._drill_cursor = 0
            store.correction_mode_enters += 1
            store.save()
            bigrams_str = " · ".join(_escape_markup(repr(bg)) for bg, _, _ in top)
            self.notify(
                f"🎯 correction mode ON — drilling: {bigrams_str}",
                timeout=3,
            )
            # Fire achievement check now so Self-Aware unlocks on entry, not
            # on the first drill completion.
            for ach in check_unlocks(store, {"chain": 0, "session_best_chain": 0}):
                self.notify(
                    f"{TIER_GLYPH.get(ach.tier, '🏆')} [b]{ach.name}[/b] — {ach.desc}",
                    title="Achievement unlocked",
                    timeout=4,
                )
        else:
            self.correction_mode = False
            self.notify("correction mode OFF — back to weakness sampling.", timeout=2)
        # Swap immediately: clear queue + jump to a fresh snippet from the new mode.
        self.queue.clear()
        self._fill_queue()
        if self.queue:
            self.current = self.queue.pop(0)
            self.target = self.current.text
            self._reset_run_state()
            self._fill_queue()
            self._refresh_view()
        self._refresh_scoreboard()


