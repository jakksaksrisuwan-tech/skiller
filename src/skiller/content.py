from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Union

import yaml

from .models import MCQ, Freeform, Task, TypingSnippet
from .store import Store

CONTENT_DIR = Path("content")

QuizItem = Union[MCQ, Freeform]


def load_mcqs(category: str | None = None) -> list[MCQ]:
    out: list[MCQ] = []
    for f in CONTENT_DIR.glob("*_basics.yaml"):
        if category and category not in f.stem:
            continue
        out.extend(_parse_mcq(f))
    for f in CONTENT_DIR.glob("*_mcq.yaml"):
        if category and category not in f.stem:
            continue
        out.extend(_parse_mcq(f))
    return out


def _parse_mcq(path: Path) -> list[MCQ]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [MCQ(**q) for q in data.get("questions", [])]


def load_freeforms(category: str | None = None) -> list[Freeform]:
    out: list[Freeform] = []
    for f in CONTENT_DIR.glob("*_freeform.yaml"):
        if category and category not in f.stem:
            continue
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        out.extend(Freeform(**q) for q in data.get("questions", []))
    return out


def load_quiz_items(category: str) -> list[QuizItem]:
    """All MCQ + Freeform for a category."""
    return [*load_mcqs(category), *load_freeforms(category)]


def all_item_tags() -> dict[str, list[str]]:
    """Item-id → tag list, used by stats rollup."""
    tags: dict[str, list[str]] = {}
    for q in load_mcqs():
        tags[q.id] = list(q.tags)
    for q in load_freeforms():
        tags[q.id] = list(q.tags)
    return tags


def load_snippets(language: str | None = None) -> list[TypingSnippet]:
    """Load typing snippets, optionally filtered by language.
    Reads any file matching `typing_*.yaml` in the content dir so adding a new
    pool (e.g. typing_linux.yaml) requires no loader changes."""
    out: list[TypingSnippet] = []
    for path in sorted(CONTENT_DIR.glob("typing_*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for s in data.get("snippets", []):
            snip = TypingSnippet(**s)
            if language is None or snip.language == language:
                out.append(snip)
    return out


def structure_weakness(stat) -> float:
    """Higher = drill more. Untested structures get baseline=1.0."""
    if stat is None or stat.completions < 2:
        return 1.0
    acc_part = (1.0 - stat.accuracy) * 1.5
    wpm_target = 50.0  # midpoint of realistic 40-60 wpm range
    wpm_part = max(0.0, (wpm_target - stat.wpm) / wpm_target)
    return 0.2 + acc_part + wpm_part


def pick_snippet(
    snippets: list[TypingSnippet],
    store: Store,
    *,
    stretch_chance: float = 0.15,
    focus_bigrams: list[str] | None = None,
) -> TypingSnippet | None:
    """Adaptive picker. Filters to user's tier; with `stretch_chance` reaches
    one tier above. Structure-weakness weighting picks within the eligible pool.

    If `focus_bigrams` is given (correction mode), snippets containing those
    sequences get a multiplicative weight boost (1 + 0.5 per occurrence)."""
    if not snippets:
        return None
    user_tier = store.typing_user_tier()
    cap = user_tier + (1 if random.random() < stretch_chance else 0)
    eligible = [s for s in snippets if s.difficulty <= cap]
    if not eligible:
        eligible = snippets
    weights = [
        structure_weakness(store.structures.get(s.structure)) for s in eligible
    ]
    if focus_bigrams:
        for i, s in enumerate(eligible):
            hits = sum(1 for bg in focus_bigrams if bg and bg in s.text)
            if hits:
                weights[i] = weights[i] * (1.0 + 0.5 * hits)
    return random.choices(eligible, weights=weights, k=1)[0]


def load_tasks() -> list[Task]:
    out: list[Task] = []
    root = CONTENT_DIR / "python_tasks"
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        manifest = d / "task.yaml"
        if not manifest.exists():
            continue
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        out.append(
            Task(
                id=data["id"],
                skill=data["skill"],
                difficulty=data["difficulty"],
                title=data["title"],
                prompt_path=str(d / "prompt.md"),
                solution_path=str(d / "solution.py"),
                test_path=str(d / "test_solution.py"),
                suggested_minutes=data.get("suggested_minutes", 30),
                target_first_pass_minutes=data.get("target_first_pass_minutes"),
                target_complete_minutes=data.get("target_complete_minutes"),
            )
        )
    return out


def schedule_session(
    items: list[QuizItem],
    store: Store,
    n: int,
    new_ratio: float = 0.25,
    interleave: bool = True,
) -> list[QuizItem]:
    """Pick session via SM-2 due-priority + sprinkle of new items.

    - Take all items past due, ranked by priority desc.
    - Reserve `new_ratio` of slots for never-seen items if any.
    - If still short, fill from due-soon (lowest interval next).
    - Interleave skills (alternate) to avoid blocking same category.
    """
    if not items:
        return []
    now = time.time()

    seen_ids = set(store.srs.keys())
    new_items = [i for i in items if i.id not in seen_ids]
    due_items = [i for i in items if i.id in seen_ids and store.is_due(i.id, now)]
    not_due = [
        i for i in items if i.id in seen_ids and not store.is_due(i.id, now)
    ]

    due_items.sort(key=lambda i: store.priority(i.id, now), reverse=True)
    random.shuffle(new_items)
    not_due.sort(key=lambda i: store.srs[i.id].due_at)

    # Reserve at least one new slot when fresh items exist; cap at new_ratio.
    new_quota = (
        min(len(new_items), max(1, int(n * new_ratio))) if new_items else 0
    )

    selected: list[QuizItem] = []
    selected.extend(due_items[: n - new_quota])
    selected.extend(new_items[:new_quota])
    # Backfill remaining slots with leftover new items, then not-due items.
    if len(selected) < n:
        unused_new = new_items[new_quota:]
        selected.extend(unused_new[: n - len(selected)])
    if len(selected) < n:
        selected.extend(not_due[: n - len(selected)])

    if interleave:
        selected = _interleave(selected)
    return selected[:n]


def _interleave(items: list[QuizItem]) -> list[QuizItem]:
    """Interleave by skill to avoid blocked runs."""
    by_skill: dict[str, list[QuizItem]] = {}
    for it in items:
        by_skill.setdefault(it.skill, []).append(it)
    out: list[QuizItem] = []
    skills = list(by_skill.keys())
    while any(by_skill[s] for s in skills):
        for s in skills:
            if by_skill[s]:
                out.append(by_skill[s].pop(0))
    return out
