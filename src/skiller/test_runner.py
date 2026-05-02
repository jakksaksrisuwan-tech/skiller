"""Run pytest in a task directory, parse JSON report, return tidy result."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


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


def run_pytest(task_dir: Path, test_files: list[str], timeout: int = 30) -> TestResult:
    """Run pytest with --json-report inside `task_dir`. Adds task_dir to PYTHONPATH
    so `from solution import …` works."""
    task_dir = Path(task_dir).resolve()
    rep_path = task_dir / ".report.json"
    rep_path.unlink(missing_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(task_dir) + os.pathsep + env.get("PYTHONPATH", "")
    )
    cmd = [
        sys.executable, "-m", "pytest",
        "-p", "pytest_jsonreport",  # pytest 9 doesn't auto-load this plugin
        *test_files,
        "--json-report",
        f"--json-report-file={rep_path}",
        "-q", "--tb=short", "--no-header",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=task_dir, env=env, capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return TestResult(0, 0, 1, float(timeout), [
            {"nodeid": "<timeout>", "message": f"pytest timed out after {timeout}s"}
        ], e.stdout or "", e.stderr or "")

    failures: list[dict] = []
    passed = failed = errors = 0
    duration = 0.0
    if rep_path.exists():
        try:
            data = json.loads(rep_path.read_text(encoding="utf-8"))
            summary = data.get("summary", {})
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            errors = summary.get("error", 0)
            duration = data.get("duration", 0.0)
            for t in data.get("tests", []):
                if t.get("outcome") in ("failed", "error"):
                    msg = t.get("call", {}).get("longrepr") or t.get("longrepr") or ""
                    failures.append({"nodeid": t.get("nodeid", "?"), "message": str(msg)})
            # Collection errors (e.g. SyntaxError on import) live under "collectors"
            for c in data.get("collectors", []):
                if c.get("outcome") == "failed":
                    msg = c.get("longrepr") or "(no detail)"
                    failures.append({
                        "nodeid": c.get("nodeid") or "<collection>",
                        "message": str(msg),
                    })
                    errors += 1
        except Exception as e:
            errors = 1
            failures.append({"nodeid": "<json-report parse>", "message": repr(e)})
        finally:
            rep_path.unlink(missing_ok=True)
    else:
        # report missing — pytest collection failure most likely
        errors = 1
        failures.append({"nodeid": "<no report>", "message": (proc.stdout + proc.stderr)[:2000]})

    return TestResult(passed, failed, errors, duration, failures, proc.stdout, proc.stderr)
