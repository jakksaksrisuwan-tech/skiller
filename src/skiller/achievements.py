"""Declarative achievement rules for typing drill (and beyond).

Each Achievement evaluates a predicate against (store, session_ctx).
When a previously locked achievement evaluates True, it's unlocked + toasted.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .store import Store


@dataclass(frozen=True)
class Achievement:
    id: str
    name: str
    desc: str
    tier: str  # bronze / silver / gold / platinum
    rule: Callable[[Store, dict], bool]
    progress: Callable[[Store, dict], tuple[float, float]] | None = None
    # progress(store, ctx) -> (current, target) for a progress bar on locked items.


TIER_GLYPH = {"bronze": "🥉", "silver": "🥈", "gold": "🥇", "platinum": "💎"}


def _max_best_wpm(store: Store) -> float:
    return max((s.best_wpm for s in store.structures.values()), default=0.0)


def _max_improvement_ratio(store: Store) -> float:
    """Largest (current_wpm / first_wpm) across structures with ≥3 runs."""
    best = 0.0
    for st in store.structures.values():
        if st.completions >= 3 and st.first_wpm > 0:
            ratio = st.wpm / st.first_wpm
            if ratio > best:
                best = ratio
    return best


def _phoenix_qualifies(store: Store) -> bool:
    """Returned after a 7+ day gap and matched a previous PR on any structure."""
    typing_attempts = [a for a in store.attempts if a.kind == "typing"]
    if len(typing_attempts) < 2:
        return False
    # Find longest inter-attempt gap; check if the post-gap completion is at PR-level
    typing_attempts.sort(key=lambda a: a.ts)
    for i in range(1, len(typing_attempts)):
        gap_days = (typing_attempts[i].ts - typing_attempts[i - 1].ts) / 86400
        if gap_days >= 7:
            # post-gap structure stats: did the user match prior best at any point after?
            for st in store.structures.values():
                if st.last_seen >= typing_attempts[i].ts and st.completions >= 3:
                    if st.wpm >= 0.95 * st.best_wpm and st.best_wpm > 0:
                        return True
    return False


def _has_typing_unlock(store: Store) -> bool:
    return any(
        a.id != "full_stack" and a.id in store.achievements
        for a in ACHIEVEMENTS
        if a.id.startswith(("first_drill", "drills_", "wpm_", "chain_",
                            "streak_", "polyglot", "master_"))
    )


def _has_mcq_engagement(store: Store) -> bool:
    """Has at least one correct MCQ attempt at confidence ≥3."""
    return any(
        a.kind == "mcq" and a.correct and a.confidence >= 3
        for a in store.attempts
    )


def _has_task_completion(store: Store) -> bool:
    """Has completed any python task (kind='task' correct=True)."""
    return any(a.kind == "task" and a.correct for a in store.attempts)


# Snippet structures grouped by language. Used by polyglot/mastery rules.
_PYTHON_STRUCTURES = {
    "list_comp", "dict_comp", "set_comp", "gen_expr", "lambda",
    "with_as", "try_except", "def_signature", "decorator", "fstring",
    "import_stmt", "class_def", "slicing", "regex", "async_await",
    "walrus", "match_stmt", "ternary",
    # added in the expansion
    "unpack", "dict_method", "str_method", "type_hint", "pathlib",
}
_LINUX_STRUCTURES = {
    # core
    "ls_dir", "find_basic", "find_filter", "find_exec",
    "grep_basic", "grep_recursive", "grep_regex",
    "awk_field", "sed_inplace",
    "chmod_octal", "chown_user",
    "tar_extract", "tar_create",
    "ps_grep", "kill_pid", "ss_tcp",
    "ssh_remote", "scp_copy", "curl_get", "curl_head",
    "pipe_filter", "pipe_chain", "redirect",
    "systemd_status", "journalctl",
    "git_log", "git_branch", "git_diff",
    "shell_loop", "shell_var",
    "docker_ps",
    # devskiller-aligned additions
    "apt", "shell_subst", "jq", "xargs", "rsync", "cron",
    "disk", "process", "monitoring",
    # functioning-engineer toolkit
    "ripgrep", "fast_find", "modern_view",
    "file_inspect", "binary_inspect", "diff",
    "process_inspect", "memory_inspect", "proc_fs",
    "debug_trace", "editor",
    "git_advanced", "tmux", "fzf",
    "file_watcher", "dns",
    # daily-engineer essentials
    "file_op", "paging", "text_pipeline",
    "conditional", "string_param", "user_group",
    "history", "date_seq",
}
# Backwards-compat alias used elsewhere (now equivalent to Python set)
_KNOWN_STRUCTURES = _PYTHON_STRUCTURES


# Mastery thresholds. Used in `_mastered_in` and surfaced in achievement
# descriptions ("Master 3 structures (≥50 wpm, ≥85% acc, ≥5 runs)").
MASTERY_MIN_RUNS = 5
MASTERY_MIN_WPM = 50.0
MASTERY_MIN_ACCURACY = 0.85


def _mastered_in(store: Store, structures: set[str]) -> int:
    """Count of given structures mastered against the thresholds above."""
    return sum(
        1 for k in structures
        if (st := store.structures.get(k)) is not None
        and st.completions >= MASTERY_MIN_RUNS
        and st.wpm >= MASTERY_MIN_WPM
        and st.accuracy >= MASTERY_MIN_ACCURACY
    )


ACHIEVEMENTS: list[Achievement] = [
    # ── completion counts ───────────────────────────────────────────
    Achievement("first_drill", "Hello, World!", "Drill 1 — past the boilerplate", "bronze",
        lambda s, c: s.typing_total_drills() >= 1,
        lambda s, c: (s.typing_total_drills(), 1)),
    Achievement("drills_5", "Take Five", "5 drills — `for _ in range(5)`", "bronze",
        lambda s, c: s.typing_total_drills() >= 5,
        lambda s, c: (s.typing_total_drills(), 5)),
    Achievement("drills_10", "Iter-Tot", "10 drills — barely iterable", "bronze",
        lambda s, c: s.typing_total_drills() >= 10,
        lambda s, c: (s.typing_total_drills(), 10)),
    Achievement("drills_50", "Half-Sliced Bread", "50 drills — `drills[:50]`, best invention since", "silver",
        lambda s, c: s.typing_total_drills() >= 50,
        lambda s, c: (s.typing_total_drills(), 50)),
    Achievement("drills_100", "PEP Squeak", "100 drills — fully PEP-talked", "silver",
        lambda s, c: s.typing_total_drills() >= 100,
        lambda s, c: (s.typing_total_drills(), 100)),
    Achievement("drills_500", "itertools.chain Gang", "500 drills — chained for life", "gold",
        lambda s, c: s.typing_total_drills() >= 500,
        lambda s, c: (s.typing_total_drills(), 500)),

    # ── peak WPM ────────────────────────────────────────────────────
    Achievement("wpm_15", "Pulse Check", "Hit 15 wpm — life signs detected", "bronze",
        lambda s, c: _max_best_wpm(s) >= 15,
        lambda s, c: (_max_best_wpm(s), 15)),
    Achievement("wpm_20", "Two-Oh!", "Hit 20 wpm — finding the rhythm", "bronze",
        lambda s, c: _max_best_wpm(s) >= 20,
        lambda s, c: (_max_best_wpm(s), 20)),
    Achievement("wpm_30", "Thirtysomething", "Hit 30 wpm — solid sit-com speed", "bronze",
        lambda s, c: _max_best_wpm(s) >= 30,
        lambda s, c: (_max_best_wpm(s), 30)),
    Achievement("wpm_40", "The Big Four-Oh", "Hit 40 wpm — life begins here", "bronze",
        lambda s, c: _max_best_wpm(s) >= 40,
        lambda s, c: (_max_best_wpm(s), 40)),
    Achievement("wpm_60", "Highway 60", "Hit 60 wpm — passing in the left lane", "silver",
        lambda s, c: _max_best_wpm(s) >= 60,
        lambda s, c: (_max_best_wpm(s), 60)),
    Achievement("wpm_80", "Hertz Donut", "Hit 80 wpm — `hertz_so_good = True`", "gold",
        lambda s, c: _max_best_wpm(s) >= 80,
        lambda s, c: (_max_best_wpm(s), 80)),
    Achievement("wpm_100", "Centipython", "Hit 100 wpm — many keys, much python", "platinum",
        lambda s, c: _max_best_wpm(s) >= 100,
        lambda s, c: (_max_best_wpm(s), 100)),

    # ── chain (in-session) ──────────────────────────────────────────
    Achievement("chain_5", "High Five", "5 drills ≥40 wpm in a row — slap it", "bronze",
        lambda s, c: c.get("chain", 0) >= 5,
        lambda s, c: (c.get("session_best_chain", 0), 5)),
    Achievement("chain_10", "Combo Decade", "10 drills ≥40 wpm in a row — `for _ in range(10)`", "silver",
        lambda s, c: c.get("chain", 0) >= 10,
        lambda s, c: (c.get("session_best_chain", 0), 10)),
    Achievement("chain_20", "Score!", "20 drills ≥40 wpm in a row — a literal score", "gold",
        lambda s, c: c.get("chain", 0) >= 20,
        lambda s, c: (c.get("session_best_chain", 0), 20)),

    # ── daily streak ────────────────────────────────────────────────
    Achievement("streak_2", "Two-Day Wonder", "Show up two days in a row", "bronze",
        lambda s, c: s.typing_streak_days() >= 2,
        lambda s, c: (s.typing_streak_days(), 2)),
    Achievement("streak_3", "Three's Compiled", "Practice 3 days running", "bronze",
        lambda s, c: s.typing_streak_days() >= 3,
        lambda s, c: (s.typing_streak_days(), 3)),
    Achievement("streak_7", "Week Sauce", "Practice 7 days running — savory", "silver",
        lambda s, c: s.typing_streak_days() >= 7,
        lambda s, c: (s.typing_streak_days(), 7)),
    Achievement("streak_14", "Fortnight Forge", "Practice 14 days running — tempering steel", "silver",
        lambda s, c: s.typing_streak_days() >= 14,
        lambda s, c: (s.typing_streak_days(), 14)),
    Achievement("streak_30", "Cron Job", "Practice 30 days — `0 0 * * * /drill`", "gold",
        lambda s, c: s.typing_streak_days() >= 30,
        lambda s, c: (s.typing_streak_days(), 30)),

    # ── coverage (Python) ───────────────────────────────────────────
    Achievement("polyglot", "Polly Want a Cracker", "Drill every Python structure once — pythonista parrot",
        "silver",
        lambda s, c: _PYTHON_STRUCTURES.issubset(set(s.structures.keys())),
        lambda s, c: (
            len(_PYTHON_STRUCTURES & set(s.structures.keys())),
            len(_PYTHON_STRUCTURES),
        )),

    # ── coverage (Linux) ────────────────────────────────────────────
    Achievement("linux_polyglot", "Shell Game",
        "Drill every Linux structure once — pipe to victory", "silver",
        lambda s, c: _LINUX_STRUCTURES.issubset(set(s.structures.keys())),
        lambda s, c: (
            len(_LINUX_STRUCTURES & set(s.structures.keys())),
            len(_LINUX_STRUCTURES),
        )),

    # ── mastery (Python) ────────────────────────────────────────────
    Achievement("master_3", "Trifecta Pythonica",
        "Master 3 Python structures (≥50 wpm, ≥85% acc, ≥5 runs)", "silver",
        lambda s, c: _mastered_in(s, _PYTHON_STRUCTURES) >= 3,
        lambda s, c: (_mastered_in(s, _PYTHON_STRUCTURES), 3)),

    # ── mastery (Linux) ─────────────────────────────────────────────
    Achievement("linux_master_3", "Three Pipe Problem",
        "Master 3 Linux structures (≥50 wpm, ≥85% acc, ≥5 runs)", "silver",
        lambda s, c: _mastered_in(s, _LINUX_STRUCTURES) >= 3,
        lambda s, c: (_mastered_in(s, _LINUX_STRUCTURES), 3)),
    # ── grit (beginner-friendly) ────────────────────────────────────
    Achievement("brave_soul", "Brave Soul",
        "Finish a snippet with ≥5 errors — didn't give up", "bronze",
        lambda s, c: c.get("brave_soul_session", False),
        None),

    # ── correction mode (F4 bigram drill) ───────────────────────────
    Achievement("self_aware", "Self-Aware",
        "Enter correction mode for the first time — knowing the gap is half the fix",
        "bronze",
        lambda s, c: s.correction_mode_enters >= 1,
        lambda s, c: (s.correction_mode_enters, 1)),
    Achievement("drill_sergeant", "Drill Sergeant",
        "10 correction-mode drills completed", "bronze",
        lambda s, c: s.total_drill_completions >= 10,
        lambda s, c: (s.total_drill_completions, 10)),
    Achievement("reps_reps_reps", "Reps Reps Reps",
        "50 correction-mode drills completed", "silver",
        lambda s, c: s.total_drill_completions >= 50,
        lambda s, c: (s.total_drill_completions, 50)),
    Achievement("pass_the_bar", "Pass the Bar",
        "Graduate your first struggle bigram below the speed threshold", "silver",
        lambda s, c: s.total_graduations >= 1,
        lambda s, c: (s.total_graduations, 1)),
    Achievement("clean_slate", "Clean Slate",
        "Clear every struggle bigram in one correction session — tabula rasa",
        "gold",
        lambda s, c: s.total_pool_clears >= 1 or c.get("pool_just_cleared", False),
        lambda s, c: (s.total_pool_clears, 1)),
    Achievement("zen_master", "Zen Master",
        "Clear the struggle pool 3 times — sustained mindful practice",
        "platinum",
        lambda s, c: s.total_pool_clears >= 3,
        lambda s, c: (s.total_pool_clears, 3)),

    # ── self-correction (clearing red marks) ────────────────────────
    Achievement("patch_notes", "Patch Notes",
        "Fix your first mistake — green is the new red", "bronze",
        lambda s, c: s.total_corrections >= 1,
        lambda s, c: (s.total_corrections, 1)),
    Achievement("diff_master", "Diff Master",
        "Correct 5+ mistakes in a single snippet", "bronze",
        lambda s, c: c.get("corrections_this_run", 0) >= 5,
        lambda s, c: (c.get("corrections_this_run", 0), 5)),
    Achievement("refactor_hero", "Refactor Hero",
        "Backspace to a skipped char and fix it — `git revert HEAD`", "silver",
        lambda s, c: c.get("skipped_recovery_this_run", False)
            or s.total_skipped_recoveries >= 1,
        lambda s, c: (s.total_skipped_recoveries, 1)),
    Achievement("cleanup_crew", "Cleanup Crew",
        "50 lifetime corrections — unbroken windows", "silver",
        lambda s, c: s.total_corrections >= 50,
        lambda s, c: (s.total_corrections, 50)),
    Achievement("code_reviewer", "Code Reviewer",
        "200 lifetime corrections — `LGTM` on yourself", "gold",
        lambda s, c: s.total_corrections >= 200,
        lambda s, c: (s.total_corrections, 200)),

    # ── accuracy ────────────────────────────────────────────────────
    Achievement("zero_defect", "Zero Defect", "First 0-error completion — pristine", "bronze",
        lambda s, c: any(st.errors == 0 and st.completions >= 1 for st in s.structures.values()),
        None),
    Achievement("clean_sweep", "Clean Sweep", "10 consecutive 100% accuracy drills", "silver",
        lambda s, c: c.get("session_clean_streak", 0) >= 10,
        lambda s, c: (c.get("session_best_clean_streak", 0), 10)),
    Achievement("surgical", "Surgical Strike", "50 drills at ≥95% lifetime accuracy", "gold",
        lambda s, c: (
            sum(st.completions for st in s.structures.values()) >= 50
            and (
                sum(st.total_chars for st in s.structures.values())
                / max(1, sum(st.total_chars + st.errors for st in s.structures.values()))
            ) >= 0.95
        ),
        lambda s, c: (sum(st.completions for st in s.structures.values()), 50)),

    # ── endurance ───────────────────────────────────────────────────
    Achievement("marathoner", "Marathoner", "30+ drills in one session", "silver",
        lambda s, c: c.get("session_completions", 0) >= 30,
        lambda s, c: (c.get("session_completions", 0), 30)),
    Achievement("pomodoro", "Pomodoro Pro", "25 minutes of typing in one session", "bronze",
        lambda s, c: c.get("session_minutes", 0.0) >= 25,
        lambda s, c: (c.get("session_minutes", 0.0), 25)),

    # ── exploration ─────────────────────────────────────────────────
    Achievement("mixed_bag", "Mixed Bag", "5+ different structures in one session", "bronze",
        lambda s, c: c.get("session_distinct_structures", 0) >= 5,
        lambda s, c: (c.get("session_distinct_structures", 0), 5)),

    # ── improvement / comeback ──────────────────────────────────────
    Achievement("rust_remover", "Rust Remover",
        "Improve a structure's wpm by 50%+ from your earliest measurement", "gold",
        lambda s, c: _max_improvement_ratio(s) >= 1.5,
        lambda s, c: (_max_improvement_ratio(s) * 100, 150)),
    Achievement("phoenix", "Phoenix",
        "Return after a 7+ day gap and match a previous PR (≥95%)", "gold",
        lambda s, c: _phoenix_qualifies(s),
        None),

    # ── cross-app holistic ──────────────────────────────────────────
    Achievement("full_stack", "Full Stack",
        "Engage with all three modes — typing + MCQ + task", "platinum",
        lambda s, c: (
            _has_typing_unlock(s)
            and _has_mcq_engagement(s)
            and _has_task_completion(s)
        ),
        lambda s, c: (
            int(_has_typing_unlock(s))
            + int(_has_mcq_engagement(s))
            + int(_has_task_completion(s)),
            3,
        )),

    Achievement("master_all", "Snake Charmer",
        "Master every Python structure — `from enlightenment import *`",
        "platinum",
        lambda s, c: _mastered_in(s, _PYTHON_STRUCTURES) == len(_PYTHON_STRUCTURES),
        lambda s, c: (_mastered_in(s, _PYTHON_STRUCTURES), len(_PYTHON_STRUCTURES))),

    Achievement("linux_master_all", "Root of It All",
        "Master every Linux structure — `sudo make me a sandwich`",
        "platinum",
        lambda s, c: _mastered_in(s, _LINUX_STRUCTURES) == len(_LINUX_STRUCTURES),
        lambda s, c: (_mastered_in(s, _LINUX_STRUCTURES), len(_LINUX_STRUCTURES))),
]


def check_unlocks(store: Store, ctx: dict) -> list[Achievement]:
    """Evaluate all rules. Mark newly satisfied as unlocked. Return new ones."""
    if not hasattr(store, "achievements") or store.achievements is None:
        store.achievements = {}
    newly: list[Achievement] = []
    for ach in ACHIEVEMENTS:
        if ach.id in store.achievements:
            continue
        try:
            ok = ach.rule(store, ctx)
        except Exception:
            ok = False
        if ok:
            store.achievements[ach.id] = time.time()
            newly.append(ach)
    if newly:
        store.save()
    return newly


def progress_view(store: Store, ctx: dict) -> list[dict]:
    """Build display rows: id, name, desc, tier, unlocked, current, target."""
    out: list[dict] = []
    locked = [a for a in ACHIEVEMENTS if a.id not in store.achievements]
    unlocked = [a for a in ACHIEVEMENTS if a.id in store.achievements]
    for ach in unlocked:
        out.append({
            "id": ach.id, "name": ach.name, "desc": ach.desc, "tier": ach.tier,
            "unlocked": True, "current": 0, "target": 0,
            "ts": store.achievements.get(ach.id, 0),
        })
    # locked ranked by progress fraction (closest first), then by tier
    def _frac(a):
        if a.progress is None:
            return 0.0
        try:
            cur, tgt = a.progress(store, ctx)
            return min(1.0, cur / tgt) if tgt else 0.0
        except Exception:
            return 0.0
    for ach in sorted(locked, key=_frac, reverse=True):
        cur, tgt = (0, 0)
        if ach.progress is not None:
            try:
                cur, tgt = ach.progress(store, ctx)
            except Exception:
                pass
        out.append({
            "id": ach.id, "name": ach.name, "desc": ach.desc, "tier": ach.tier,
            "unlocked": False, "current": cur, "target": tgt, "ts": 0,
        })
    return out
