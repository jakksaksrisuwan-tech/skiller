from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Difficulty = Literal["practice", "easy", "medium", "hard"]


def wpm(chars: int, ms: float) -> float:
    """Words-per-minute from char count and elapsed milliseconds.
    1 word = 5 chars (industry convention). Returns 0 on degenerate input."""
    if chars <= 0 or ms <= 0:
        return 0.0
    return 60.0 / (5 * (ms / 1000) / chars)
Kind = Literal[
    "mcq", "freeform", "task", "task_first_pass", "task_complete", "typing"
]


@dataclass(frozen=True)
class MCQ:
    id: str
    skill: str
    prompt: str
    choices: list[str]
    answer: int
    explain: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "mcq"


@dataclass(frozen=True)
class Freeform:
    """User types answer; matched against any of `patterns` (regex, case-insensitive)."""
    id: str
    skill: str
    prompt: str
    patterns: list[str]
    canonical: str  # shown in explain as the canonical answer
    explain: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "freeform"


@dataclass(frozen=True)
class TypingSnippet:
    """Single-line Python snippet for the structure-driven typing drill.

    `structure` is the primary Python construct the snippet exercises,
    e.g. 'lambda', 'list_comp', 'with_as', 'fstring', 'decorator'.

    `difficulty` is 1 (short/simple), 2 (medium), or 3 (long/dense punctuation).
    The picker filters by the user's adaptive tier (≤ avg_wpm/25, clamped 1-3).
    """
    id: str
    structure: str
    text: str
    difficulty: int = 2
    tags: list[str] = field(default_factory=list)


@dataclass
class StructureStat:
    """Per-structure typing performance, aggregated across runs."""
    structure: str
    completions: int = 0
    errors: int = 0          # wrong keystrokes summed across runs
    total_ms: float = 0.0    # cumulative time on correct keystrokes
    total_chars: int = 0     # cumulative correct characters
    best_wpm: float = 0.0    # personal record on a single completed drill
    first_wpm: float = 0.0   # very first measured wpm (never updated after) — for Rust Remover
    last_seen: float = 0.0   # epoch seconds of last completion

    @property
    def wpm(self) -> float:
        return wpm(self.total_chars, self.total_ms)

    @property
    def accuracy(self) -> float:
        total = self.total_chars + self.errors
        return self.total_chars / total if total else 0.0

    def record(self, *, chars: int, errors: int, ms: float, now: float) -> None:
        self.completions += 1
        self.total_chars += chars
        self.errors += errors
        self.total_ms += ms
        self.last_seen = now
        run_wpm = wpm(chars, ms)
        if run_wpm > 0:
            if self.first_wpm == 0.0:
                self.first_wpm = run_wpm
            if run_wpm > self.best_wpm:
                self.best_wpm = run_wpm


@dataclass(frozen=True)
class Task:
    id: str
    skill: str
    difficulty: Difficulty
    title: str
    prompt_path: str
    solution_path: str
    test_path: str
    suggested_minutes: int = 30
    target_first_pass_minutes: int | None = None
    target_complete_minutes: int | None = None


@dataclass
class Attempt:
    item_id: str
    kind: Kind
    skill: str
    correct: bool
    seconds: float
    ts: float
    confidence: int = 3  # 1-5
    grade: int = 3  # 0-5 SM-2 grade


@dataclass
class SRSState:
    """SM-2 state per item."""
    item_id: str
    interval_days: float = 0.0  # days until next review
    ease: float = 2.5  # SM-2 ease factor; min 1.3
    reps: int = 0  # consecutive correct (>= grade 3)
    last_seen: float = 0.0  # epoch seconds
    due_at: float = 0.0  # epoch seconds


@dataclass
class SkillStat:
    skill: str
    attempts: int = 0
    correct: int = 0
    total_seconds: float = 0.0
    rolling: list[bool] = field(default_factory=list)
    brier_sum: float = 0.0  # sum (conf/5 - correct)^2
    brier_n: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.attempts if self.attempts else 0.0

    @property
    def rolling_accuracy(self) -> float:
        return sum(self.rolling) / len(self.rolling) if self.rolling else 0.0

    @property
    def avg_seconds(self) -> float:
        return self.total_seconds / self.attempts if self.attempts else 0.0

    @property
    def calibration(self) -> float:
        """Brier score; lower is better. 0 = perfect, 1 = terrible."""
        return self.brier_sum / self.brier_n if self.brier_n else 0.0

    def record(
        self, correct: bool, seconds: float, confidence: int, window: int = 20
    ) -> None:
        self.attempts += 1
        self.correct += int(correct)
        self.total_seconds += seconds
        self.rolling.append(correct)
        if len(self.rolling) > window:
            self.rolling = self.rolling[-window:]
        # Brier: confidence/5 vs correct(0/1)
        p = max(0.0, min(1.0, confidence / 5.0))
        self.brier_sum += (p - (1.0 if correct else 0.0)) ** 2
        self.brier_n += 1


def grade_from(correct: bool, confidence: int) -> int:
    """Map (correct, confidence 1-5) → SM-2 grade 0-5.

    False confidence (sure but wrong) penalised hardest.
    """
    confidence = max(1, min(5, confidence))
    if correct:
        return max(3, confidence)
    # wrong:
    return {1: 2, 2: 2, 3: 1, 4: 1, 5: 0}[confidence]


def sm2_update(state: SRSState, grade: int, now: float) -> SRSState:
    """Apply SM-2 update to state. Returns new state (mutates in place too)."""
    if grade < 3:
        state.reps = 0
        state.interval_days = 1.0
    else:
        state.reps += 1
        if state.reps == 1:
            state.interval_days = 1.0
        elif state.reps == 2:
            state.interval_days = 6.0
        else:
            state.interval_days = round(state.interval_days * state.ease, 2)
        # ease update
        delta = 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)
        state.ease = max(1.3, state.ease + delta)
    state.last_seen = now
    state.due_at = now + state.interval_days * 86400
    return state
