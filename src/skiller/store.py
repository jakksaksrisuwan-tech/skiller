from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from .models import Attempt, SRSState, SkillStat, StructureStat, grade_from, sm2_update, wpm

STATE_PATH = Path(".skiller_state.json")


class Store:
    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path
        self.skills: dict[str, SkillStat] = {}
        self.attempts: list[Attempt] = []
        self.srs: dict[str, SRSState] = {}
        self.structures: dict[str, StructureStat] = {}
        self.achievements: dict[str, float] = {}  # id → unlocked_ts
        # Self-correction lifetime counters: incremented when a wrong_at mark is
        # cleared by typing the correct char (via retry or backspace+correct).
        self.total_corrections: int = 0
        self.total_skipped_recoveries: int = 0  # subset: correction after auto-advance
        # Bigram-level keystroke timing — EMA so recent timings dominate
        # (otherwise an old slow attempt would drag the average forever).
        # bigram_avg_ms[bg] = EMA-smoothed time to type the 2nd char of bg.
        # bigram_count[bg]  = sample count (capped via natural growth).
        # bigram_errors[bg] = wrong-key count when typing 2nd char of bg.
        self.bigram_avg_ms: dict[str, float] = {}
        self.bigram_count: dict[str, int] = {}
        self.bigram_errors: dict[str, int] = {}
        # Per-snippet cache; invalidated in `record_typing`. Avoids a full
        # walk of `self.structures` on every keystroke via `record_bigram_time`.
        self._cached_graduation_ms: float | None = None
        # Correction-drill lifetime counters.
        self.correction_mode_enters: int = 0   # F4 ON activations
        self.total_drill_completions: int = 0  # synthetic drill snippets typed
        self.total_graduations: int = 0        # bigrams crossing threshold downward
        self.total_pool_clears: int = 0        # times all bigrams graduated → exit
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self.skills = {
            k: SkillStat(**v) for k, v in data.get("skills", {}).items()
        }
        self.attempts = [Attempt(**a) for a in data.get("attempts", [])]
        self.srs = {k: SRSState(**v) for k, v in data.get("srs", {}).items()}
        self.structures = {
            k: StructureStat(**v) for k, v in data.get("structures", {}).items()
        }
        self.achievements = dict(data.get("achievements", {}))
        self.total_corrections = int(data.get("total_corrections", 0))
        self.total_skipped_recoveries = int(data.get("total_skipped_recoveries", 0))
        self.bigram_count = dict(data.get("bigram_count", {}))
        self.bigram_avg_ms = dict(data.get("bigram_avg_ms", {}))
        self.bigram_errors = dict(data.get("bigram_errors", {}))
        self.correction_mode_enters = int(data.get("correction_mode_enters", 0))
        self.total_drill_completions = int(data.get("total_drill_completions", 0))
        self.total_graduations = int(data.get("total_graduations", 0))
        self.total_pool_clears = int(data.get("total_pool_clears", 0))
        # Migrate from earlier sum-based schema if encountered.
        legacy_total = data.get("bigram_total_ms")
        if legacy_total and not self.bigram_avg_ms:
            for bg, total in legacy_total.items():
                cnt = self.bigram_count.get(bg, 0)
                if cnt > 0:
                    self.bigram_avg_ms[bg] = total / cnt

    def save(self) -> None:
        data = {
            "skills": {k: asdict(v) for k, v in self.skills.items()},
            "attempts": [asdict(a) for a in self.attempts[-500:]],
            "srs": {k: asdict(v) for k, v in self.srs.items()},
            "structures": {k: asdict(v) for k, v in self.structures.items()},
            "achievements": dict(self.achievements),
            "total_corrections": self.total_corrections,
            "total_skipped_recoveries": self.total_skipped_recoveries,
            "bigram_count": dict(self.bigram_count),
            "bigram_avg_ms": dict(self.bigram_avg_ms),
            "bigram_errors": dict(self.bigram_errors),
            "correction_mode_enters": self.correction_mode_enters,
            "total_drill_completions": self.total_drill_completions,
            "total_graduations": self.total_graduations,
            "total_pool_clears": self.total_pool_clears,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.path)

    def record_typing(
        self,
        structure: str,
        *,
        item_id: str = "",
        chars: int,
        errors: int,
        ms: float,
    ) -> None:
        import time as _t
        now = _t.time()
        s = self.structures.setdefault(structure, StructureStat(structure=structure))
        s.record(chars=chars, errors=errors, ms=ms, now=now)
        self._cached_graduation_ms = None  # lifetime stats changed; recompute on next read
        # Append to attempts log so the stats screen can roll up time-series.
        self.attempts.append(
            Attempt(
                item_id=item_id or structure,
                kind="typing",  # type: ignore[arg-type]
                skill="typing",
                correct=errors == 0,
                seconds=ms / 1000,
                ts=now,
                confidence=3,
                grade=3,
            )
        )
        self.save()

    # ---- typing helpers used by the drill scoreboard ----

    def typing_total_drills(self) -> int:
        return sum(s.completions for s in self.structures.values())

    def typing_overall_wpm(self) -> float:
        total_chars = sum(s.total_chars for s in self.structures.values())
        total_ms = sum(s.total_ms for s in self.structures.values())
        return wpm(total_chars, total_ms)

    def typing_personal_record(self) -> tuple[str, float]:
        if not self.structures:
            return "", 0.0
        best = max(self.structures.values(), key=lambda s: s.best_wpm)
        return best.structure, best.best_wpm

    BIGRAM_EMA_ALPHA = 0.18  # ~half-life of ~3.5 samples; recent dominates

    def record_bigram_time(self, bigram: str, ms: float) -> None:
        """EMA-update keystroke timing for a 2-char sequence.
        Tracks graduation events: when avg crosses the threshold downward
        AND the bigram had ≥5 samples (qualifying it as struggle data),
        increment `total_graduations`."""
        if len(bigram) != 2 or ms <= 0:
            return
        threshold = self.typing_graduation_ms()
        prior_count = self.bigram_count.get(bigram, 0)
        prior_avg = self.bigram_avg_ms.get(bigram, 0.0)
        was_struggling = prior_count >= 5 and prior_avg >= threshold
        if bigram in self.bigram_avg_ms:
            self.bigram_avg_ms[bigram] = (
                self.BIGRAM_EMA_ALPHA * ms
                + (1 - self.BIGRAM_EMA_ALPHA) * prior_avg
            )
        else:
            self.bigram_avg_ms[bigram] = ms
        self.bigram_count[bigram] = prior_count + 1
        new_avg = self.bigram_avg_ms[bigram]
        is_struggling_now = (prior_count + 1) >= 5 and new_avg >= threshold
        if was_struggling and not is_struggling_now:
            self.total_graduations += 1

    def record_bigram_error(self, bigram: str) -> None:
        if len(bigram) != 2:
            return
        self.bigram_errors[bigram] = self.bigram_errors.get(bigram, 0) + 1

    def top_struggle_bigrams(
        self,
        n: int = 5,
        min_count: int = 5,
        graduation_ms: float = 0.0,
    ) -> list[tuple[str, float, int]]:
        """Top-N slowest bigrams. Returns (bigram, avg_ms, error_count).
        Score = avg_ms × (1 + error_rate); favours slow + error-prone.
        Bigrams whose avg_ms drops below `graduation_ms` are excluded —
        they've been mastered and no longer need drilling.

        Bigrams that are PURELY whitespace are skipped — the resulting drill
        ('         ' ×8) is invisible. Mixed bigrams like ' -' or ': ' stay
        in: they exercise a real finger pattern and the visible char anchors
        the drill on screen."""
        rows = []
        for bg, count in self.bigram_count.items():
            if count < min_count:
                continue
            if not bg.strip():
                continue
            avg_ms = self.bigram_avg_ms.get(bg, 0.0)
            if graduation_ms and avg_ms < graduation_ms:
                continue
            errors = self.bigram_errors.get(bg, 0)
            score = avg_ms * (1 + errors / max(1, count))
            rows.append((bg, avg_ms, errors, score))
        rows.sort(key=lambda r: r[3], reverse=True)
        return [(bg, avg_ms, err) for bg, avg_ms, err, _ in rows[:n]]

    def typing_graduation_ms(self) -> float:
        """Per-keystroke ms threshold below which a bigram is 'mastered' and
        drops out of the correction-mode drill pool. Tracks personal target
        but never below 150ms (~80 wpm) — past that it's just signal noise.

        Cached because this is called per-keystroke via `record_bigram_time`;
        the underlying lifetime stats only change on snippet completion."""
        if self._cached_graduation_ms is None:
            target_wpm = self.typing_personal_target()
            target_ms = 60_000.0 / (5 * target_wpm)
            self._cached_graduation_ms = max(150.0, target_ms)
        return self._cached_graduation_ms

    def typing_personal_target(self, floor: float = 40.0, lift: float = 1.15) -> float:
        """Floating per-user wpm target. = max(floor, lifetime_avg * lift).
        Fresh users start at floor (40); always 15% above current lifetime avg."""
        avg = self.typing_overall_wpm()
        if avg <= 0:
            return floor
        return max(floor, avg * lift)

    def typing_user_tier(self) -> int:
        """Adaptive difficulty tier: 1, 2, or 3.
        - <30 wpm avg → tier 1 only
        - 30-50 wpm   → tier 1+2
        - ≥50 wpm     → tier 1+2+3
        New users (no completions) start at tier 1."""
        avg = self.typing_overall_wpm()
        if avg <= 0:
            return 1
        if avg < 30:
            return 1
        if avg < 50:
            return 2
        return 3

    def typing_focus_structure(self, target_wpm: float = 50.0) -> tuple[str, float] | None:
        """Pick the user's biggest opportunity: smallest non-zero wpm with ≥1 run."""
        candidates = [s for s in self.structures.values() if s.completions >= 1]
        if not candidates:
            return None
        weakest = min(candidates, key=lambda s: s.wpm if s.wpm else 9999)
        return weakest.structure, weakest.wpm

    def typing_minutes_on(self, day_offset: int = 0) -> float:
        """Minutes typing on a given day. day_offset 0=today, 1=yesterday."""
        from datetime import date, datetime, timedelta
        target = date.today() - timedelta(days=day_offset)
        total = 0.0
        for a in self.attempts:
            if a.kind != "typing":
                continue
            if datetime.fromtimestamp(a.ts).date() == target:
                total += a.seconds
        return total / 60.0

    def typing_streak_days(self) -> int:
        """Consecutive days (ending today or yesterday) with ≥1 typing run."""
        from datetime import date, datetime, timedelta
        days = {
            datetime.fromtimestamp(a.ts).date()
            for a in self.attempts
            if a.kind == "typing"
        }
        if not days:
            return 0
        today = date.today()
        # streak counts back from today; allow gap of one day (yesterday) before breaking
        cur = today
        streak = 0
        if cur not in days:
            cur = today - timedelta(days=1)
            if cur not in days:
                return 0
        while cur in days:
            streak += 1
            cur = cur - timedelta(days=1)
        return streak

    def record(
        self,
        item_id: str,
        kind: str,
        skill: str,
        correct: bool,
        seconds: float,
        confidence: int = 3,
    ) -> int:
        """Record attempt, run SM-2 update. Returns SM-2 grade."""
        grade = grade_from(correct, confidence)
        now = time.time()
        state = self.srs.setdefault(item_id, SRSState(item_id=item_id))
        sm2_update(state, grade, now)

        stat = self.skills.setdefault(skill, SkillStat(skill=skill))
        stat.record(correct, seconds, confidence)

        self.attempts.append(
            Attempt(
                item_id=item_id,
                kind=kind,  # type: ignore[arg-type]
                skill=skill,
                correct=correct,
                seconds=seconds,
                ts=now,
                confidence=confidence,
                grade=grade,
            )
        )
        self.save()
        return grade

    def is_due(self, item_id: str, now: float | None = None) -> bool:
        now = now or time.time()
        s = self.srs.get(item_id)
        if s is None:
            return True  # never seen
        return s.due_at <= now

    def priority(self, item_id: str, now: float | None = None) -> float:
        """Higher = more urgent. Used to rank items past due."""
        now = now or time.time()
        s = self.srs.get(item_id)
        if s is None:
            return 1.0  # new items get baseline priority
        if s.due_at > now:
            return 0.0  # not due
        overdue_days = (now - s.due_at) / 86400
        # weak items (low ease) overdue → highest
        return (3.0 - s.ease) + overdue_days * 0.5 + 1.0

    def tag_stats(self, item_tags: dict[str, list[str]]) -> dict[str, dict]:
        """Roll up attempts by tag. `item_tags` maps item_id → tag list."""
        agg: dict[str, dict] = {}
        for a in self.attempts:
            for tag in item_tags.get(a.item_id, []):
                t = agg.setdefault(
                    tag, {"attempts": 0, "correct": 0, "rolling": []}
                )
                t["attempts"] += 1
                t["correct"] += int(a.correct)
                t["rolling"].append(a.correct)
                if len(t["rolling"]) > 10:
                    t["rolling"] = t["rolling"][-10:]
        for tag, t in agg.items():
            t["acc"] = t["correct"] / t["attempts"] if t["attempts"] else 0.0
            t["rolling_acc"] = (
                sum(t["rolling"]) / len(t["rolling"]) if t["rolling"] else 0.0
            )
        return agg
