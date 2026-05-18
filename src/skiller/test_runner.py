"""Run the bundled stdlib-only test driver in a subprocess and parse its
JSON output. No third-party deps; works on any platform with Python ≥3.11."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_DRIVER = Path(__file__).with_name("_test_driver.py")
_RESULT_PREFIX = "__SKILLER_RESULT__"


@dataclass
class TestResult:
    passed: int
    failed: int
    errors: int
    duration: float
    failures: list[dict]  # [{nodeid, message}]
    raw_stdout: str
    raw_stderr: str

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors

    @property
    def all_green(self) -> bool:
        return self.failed == 0 and self.errors == 0 and self.passed > 0


def _extract_payload(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            try:
                return json.loads(line[len(_RESULT_PREFIX):])
            except json.JSONDecodeError:
                return None
    return None


def run_pytest(task_dir: Path, test_files: list[str], timeout: int = 30) -> TestResult:
    """Run the bundled driver inside `task_dir`. Adds task_dir to PYTHONPATH so
    `from solution import …` works. Name kept for backward compatibility — the
    driver does not depend on pytest being installed."""
    task_dir = Path(task_dir).resolve()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(task_dir) + os.pathsep + env.get("PYTHONPATH", "")
    # Avoid stale .pyc surprises across platforms.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    cmd = [sys.executable, str(_DRIVER), str(task_dir), *test_files]
    try:
        proc = subprocess.run(
            cmd, cwd=task_dir, env=env, capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return TestResult(
            0, 0, 1, float(timeout),
            [{"nodeid": "<timeout>",
              "message": f"tests timed out after {timeout}s"}],
            (e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")),
            (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")),
        )

    payload = _extract_payload(proc.stdout)
    if payload is None:
        return TestResult(
            0, 0, 1, 0.0,
            [{"nodeid": "<no result>",
              "message": (proc.stdout + "\n" + proc.stderr)[:2000]}],
            proc.stdout, proc.stderr,
        )

    summary = payload.get("summary", {})
    passed = int(summary.get("passed", 0))
    failed = int(summary.get("failed", 0))
    errors = int(summary.get("errors", 0))
    duration = float(payload.get("duration", 0.0))

    failures: list[dict] = []
    for t in payload.get("tests", []):
        if t.get("outcome") in ("failed", "error"):
            failures.append({
                "nodeid": t.get("nodeid", "?"),
                "message": str(t.get("longrepr") or "(no detail)"),
            })

    return TestResult(passed, failed, errors, duration, failures,
                      proc.stdout, proc.stderr)
