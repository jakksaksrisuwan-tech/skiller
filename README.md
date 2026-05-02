# skiller

Terminal app to prep for DevSkiller-style technical exercises:
**Linux MCQ · Python MCQ · Python coding tasks · Typing drills (Python + Linux)**
with adaptive difficulty, SM-2 spaced repetition, bigram struggle tracking,
and 47 achievements.

```
$ ./start.sh
```

Hot-reload supervisor watches `src/skiller/`, `content/`, and `pyproject.toml`
for `.py / .yaml / .toml / .tcss` changes. Edit any file → app respawns,
state restored.

## Modes

### Linux Basics MCQ
**31 multiple-choice + 24 dropdown questions** drawn together (~12 per session)
covering: `find`, `grep`, `awk`, `sed`, permissions, signals, processes,
archives, networking (`ss`/`curl`), systemd, cron, `apt`, shell scripting
(`set -euo pipefail`, `$(...)`, here-docs, `2>&1`).

Choice order shuffles per presentation. Confidence rated 1-5 after each
answer; calibration (Brier score) surfaced in the stats screen.

### Python MCQ
**25 MCQ + 12 dropdown questions** covering: stdlib, typing, decorators,
GIL, asyncio, dataclasses, slots, walrus, MRO, contextlib, pathlib,
regex, f-strings.

Both pools use the same screen — multiple-choice and dropdown questions
interleave by SM-2 weakness. False-confidence (sure but wrong) is the
hardest grade penalty.

### Python Coding Tasks
4 tasks. Vim-launching editor (`e` suspends Textual), pytest runner with
visible + hidden test suites.

| Task | Difficulty | Targets |
|---|---|---|
| `sum_even` | practice | environment warmup |
| `parse_syslog` | easy (~30 min) | log line parsing |
| `csv_aggregate` | medium | **20 min first pass · 40 min complete** |
| `TaskScheduler` | hard (~40 min) | topo-sort with cycle detection |

Press `e` to edit, `t` to run visible tests, `s` to submit (visible + hidden).
First-pass and complete times recorded vs per-task targets; stats screen
shows your best (fastest) milestone per task.

### Typing Drills (Python + Linux)
Keybr-style structure-driven typing with adaptive difficulty.

- **285 snippets** total — 93 Python (23 structures) + **192 Linux**
  (64 structures: `find`, `grep`, `awk`, `chmod`, `tar`, `ssh`, `systemctl`,
  `apt`, `git rebase -i`, `git bisect`, `tmux`, `fzf`, `rg`/`fd`/`bat`,
  `lsof`, `pmap`, `/proc`, `gdb -p`, `py-spy`, `perf record`, shell loops,
  pipes, redirects, parameter expansion, …)
- Picker weights snippets by *structure-weakness* — your slow structures
  surface more often
- Difficulty tier `1/2/3` filters by lifetime average WPM
  - `<30 wpm` → tier 1 (short, simple)
  - `30-50` → tier 1+2
  - `≥50` → all tiers + 15% stretch chance into next
- Floating personal target = `max(40, lifetime_avg × 1.15)`. Chain threshold
  scales accordingly.
- **Per-snippet description** above the bordered typing area annotates the
  *just-typed* snippet — you read the command, type it, the explanation
  lands as feedback

#### Live UI

```
   @functools.lru_cache(maxsize=128)        ← last completed (dim grey)
   ↳ memoise expensive pure function         ← description of done line
╭──────────────────────────────────────╮     _   _    _
│   f'{pi:8.3f}'                       │    | |  _|  |_   ← LCD: rolling avg wpm
╰──────────────────────────────────────╯    |_|  _|   _|
   re.findall(r'\b\w+\b', text)              ← upcoming queue (dim)
   sum(x * x for x in nums)
   ...

wpm 45  acc 95%  errors 1  ⏱ 2.3s
```

#### Wrong-key behaviour

- 1st wrong → cursor stays, char turns **red**, retry available
- 2nd wrong on same char → cursor auto-advances, char stays red as a marker
- **First backspace** clears the most recent red mark (cursor stays put if
  the red was at cursor, or pulls back if you'd auto-advanced past it)
- Correct retry **clears the red mark visually** (error stat persists)
- Multiple backspaces past clean chars work normally

#### Bigram struggle tracking + F4 correction mode

Every correct keystroke records inter-keystroke time for the 2-character
target sequence. EMA-smoothed (α = 0.18) so recent timings dominate —
improvements show up within ~5 samples.

The scoreboard's `struggle` row lists your top 5 slowest bigrams:

```
struggle   'st' 320ms+2e  '_(' 280ms  ': ' 240ms+1e  '],' 215ms  'th' 200ms 🎯 ON
```

**F4** enters correction mode:

- Queue swaps to synthetic drills built from your top struggle bigrams
  (both spaced `'st st st…'` and tight `'ststststst…'` variants)
- Press F4 again to exit, OR let auto-exit fire when all bigrams graduate
- **Graduation threshold**: when a bigram's avg drops below
  `max(150ms, 60_000 / (5 × target_wpm))`, it falls out of the drill pool
- When the entire pool empties, correction mode exits with a 🏁 celebration

#### Celebration tiers

| Result | Marker | Flash |
|---|---|---|
| Overall PR + clean | `★ NEW PR!` | 4-cycle bright_yellow strobe |
| Exceptional (60+ wpm) clean | `★ EXCEPTIONAL` | 3-cycle yellow strobe |
| Structure PR clean | `★ structure PR` | 3-cycle green strobe |
| On target (40-60 wpm) clean | `✓ on target` | 3-cycle green strobe |
| Sub-40 wpm clean | `✓ clean` | dim green |
| Few errors | (none) | dim |

Chain `🔥` count appears at 3+ consecutive `≥40` wpm runs.

#### Keys

```
Esc   back to menu
F1    toggle scoreboard (session/all-time/focus/today/streak/tier/struggle)
F2    skip current snippet (no chain credit)
F3    achievements panel (locked names hidden as ???)
F4    correction mode (drill your slow bigrams; auto-exit on graduation)
```

## Stats screen

- Per-skill rolling accuracy, overall accuracy, average seconds, calibration
- Per-tag rollup with mastery flag (≥80% rolling, ≥3 attempts)
- Tasks — milestones table: first-pass time, complete time, vs target
- Typing — per-structure runs / wpm / accuracy / errors
- Recent 20 attempts log
- Achievements: unlocked + locked-with-progress (locked names hidden as `???`)

## Achievements

47 total across 14 axes:

- **Speed (beginner)** — 15 / 20 / 30 wpm
- **Speed (target)** — 40 / 60 wpm
- **Speed (exceptional)** — 80 / 100 wpm
- **Persistence** — 1/5/10/50/100/500 drills
- **Chain** — 5/10/20 consecutive ≥40 wpm runs
- **Daily streak** — 2/3/7/14/30 days (forgiving — 1 missed day OK)
- **Coverage** — drill every Python structure (`Polly Want a Cracker`),
  drill every Linux structure (`Shell Game`)
- **Mastery (Python)** — 3 (`Trifecta Pythonica`) / all (`Snake Charmer`)
- **Mastery (Linux)** — 3 (`Three Pipe Problem`) / all (`Root of It All`)
- **Accuracy** — first clean / 10 consecutive clean / 50 drills @ 95% lifetime
- **Endurance** — 30+ drills/session, 25 min uninterrupted
- **Improvement** — 50%+ wpm gain on a structure, return after 7-day gap
- **Self-correction** — 1/50/200 mistakes corrected, recover from auto-skip
- **Correction drill** — first F4 entry, 10/50 drills, first graduation,
  clear pool once, clear pool 3× (`Zen Master`)
- **Cross-app** — engaged with typing + MCQ + task

Punny names hidden until earned.

## Setup

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

| OS | Install `uv` | Run |
|---|---|---|
| macOS | `brew install uv` | `./start.sh` |
| Linux | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `./start.sh` |
| Windows | `winget install --id=astral-sh.uv` (or `pip install uv`) | `.\start.ps1` |

Both launchers do the same thing:

1. Create `.venv` and run `uv pip install -e ".[dev]"` if missing
2. Exec `uv run python dev.py` (the hot-reload supervisor)

`dev.py` watches `src/skiller/`, `content/`, `pyproject.toml` for
`.py / .yaml / .toml / .tcss` changes. On save: SIGTERMs the child →
child snapshots state to `.dev_state.json` → supervisor respawns with
`--snapshot` → current screen restores.

### Windows notes

- **Use Windows Terminal** (or Windows Terminal Preview), not legacy
  `cmd.exe`. The TUI needs Unicode + 24-bit colour + scrollback handling
  that legacy console doesn't support.
- **Hot-reload state-snapshot is Linux/macOS only** (relies on SIGTERM signal
  handlers, which Windows kills hard). On Windows the supervisor + respawn
  cycle work fine, but each respawn drops you on the menu instead of the
  exact screen you were on. The drill itself is unaffected.
- If PowerShell blocks `start.ps1`, run once:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- Vim is not bundled. `git task` mode (the `e` key) suspends to your
  `$EDITOR`. Set it: `$env:EDITOR = "nvim"` (or `code --wait`, `vim`, …)
  before starting `.\start.ps1`.

## Offline

Once installed, the app makes **zero network calls**. Runs fully on a plane,
in airplane mode, in a network-disabled namespace. No telemetry, no analytics,
no cloud sync. State lives in `./.skiller_state.json` (gitignored).

To verify hard:
```bash
sudo lsof -i -P -n -p $(pgrep -f skiller.main)   # empty = no sockets open
```

## File layout

```
.
├── start.sh              # one-shot launcher
├── dev.py                # hot-reload supervisor
├── pyproject.toml
├── content/
│   ├── linux_basics.yaml         # 31 MCQ
│   ├── linux_freeform.yaml       # 24 dropdown (was typed answers)
│   ├── python_mcq.yaml           # 25 MCQ
│   ├── python_freeform.yaml      # 12 dropdown
│   ├── typing_snippets.yaml      # 93 Python typing
│   ├── typing_linux.yaml         # 192 Linux typing
│   └── python_tasks/
│       ├── 01_practice/
│       ├── 02_easy/
│       ├── 03_hard/
│       └── 04_csv_aggregate/
└── src/skiller/
    ├── main.py           # SkillerApp + global CSS + menu routing
    ├── models.py         # MCQ, Freeform, TypingSnippet, Task, SRSState …
    ├── store.py          # JSON-persisted .skiller_state.json + helpers
    ├── content.py        # YAML loaders, weighted samplers, tier filter
    ├── achievements.py   # 47 declarative rules + check_unlocks()
    ├── test_runner.py    # pytest --json-report wrapper
    ├── hot_reload.py     # HotReloadable mixin (SIGTERM-driven snapshot)
    ├── ui.py             # progress_bar, StopwatchLabel
    └── screens/
        ├── menu.py
        ├── mcq.py        # MCQ + freeform-as-dropdown, confidence, SM-2
        ├── task.py       # vim-suspend + pytest output + milestone tracking
        ├── typing.py     # keybr-style drill, LCD, scoreboard, F1/F2/F3/F4
        ├── stats.py      # tabular proficiency overview
        └── achievements.py  # F3 panel, locked names hidden
```

## Persistence

Single JSON at `./.skiller_state.json` (gitignored). Keys:

- `skills` — per-skill rolling stats + Brier sums
- `attempts` — last 500 of every action (mcq / freeform / task / typing)
- `srs` — SM-2 state per item (interval, ease, reps, due_at)
- `structures` — typing-structure aggregate WPM / errors / first_wpm / best_wpm
- `bigram_avg_ms`, `bigram_count`, `bigram_errors` — per-bigram timing data
  for F4 correction mode
- `achievements` — id → unlocked timestamp
- `total_corrections` / `total_skipped_recoveries` — lifetime self-correction
- `correction_mode_enters` / `total_drill_completions` /
  `total_graduations` / `total_pool_clears` — F4 correction-drill counters

## License

MIT — see [LICENSE](LICENSE).
