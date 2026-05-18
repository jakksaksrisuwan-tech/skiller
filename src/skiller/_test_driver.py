"""Stdlib-only test driver. Run by test_runner.py in a subprocess.

Discovers `test_*` functions in the given files, runs them, and prints a single
JSON line prefixed by `__SKILLER_RESULT__` to stdout. Provides a minimal
`pytest` shim (raises / fixture / mark / skip / fail / approx) so existing
tests keep working without pytest installed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
import types
from pathlib import Path


class _Skip(Exception):
    pass


def _make_pytest_stub() -> types.ModuleType:
    pytest = types.ModuleType("pytest")

    class _RaisesCtx:
        def __init__(self, expected, match=None):
            self.expected = expected
            self.match = match
            self.value = None
            self.type = None
            self.tb = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                raise AssertionError(f"DID NOT RAISE {self.expected!r}")
            expected = self.expected
            if not isinstance(expected, tuple):
                expected = (expected,)
            if not any(issubclass(exc_type, e) for e in expected):
                return False
            if self.match is not None:
                import re
                if not re.search(self.match, str(exc)):
                    raise AssertionError(
                        f"Pattern {self.match!r} not found in {str(exc)!r}"
                    )
            self.value = exc
            self.type = exc_type
            self.tb = tb
            return True

    def raises(expected, match=None):
        return _RaisesCtx(expected, match=match)

    def fixture(*args, **kwargs):
        if args and callable(args[0]) and not kwargs:
            return args[0]
        def deco(fn):
            return fn
        return deco

    def skip(reason=""):
        raise _Skip(reason)

    def fail(reason=""):
        raise AssertionError(reason)

    class _Approx:
        def __init__(self, expected, rel=None, abs=None):
            self.expected = expected
            self.rel = rel if rel is not None else 1e-6
            self.abs = abs if abs is not None else 1e-12

        def __eq__(self, other):
            try:
                return abs(other - self.expected) <= max(
                    self.abs, self.rel * abs(self.expected)
                )
            except Exception:
                return False

        def __repr__(self):
            return f"approx({self.expected!r})"

    def approx(expected, rel=None, abs=None):
        return _Approx(expected, rel=rel, abs=abs)

    class _MarkProxy:
        def __getattr__(self, name):
            def deco(*a, **kw):
                if a and callable(a[0]) and not kw:
                    return a[0]
                def inner(fn):
                    return fn
                return inner
            return deco

    pytest.raises = raises
    pytest.fixture = fixture
    pytest.skip = skip
    pytest.fail = fail
    pytest.approx = approx
    pytest.mark = _MarkProxy()
    pytest.Skipped = _Skip
    pytest._SkillerSkip = _Skip
    return pytest


def _load_module(path: Path) -> types.ModuleType:
    name = f"_skiller_test_{path.stem}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _emit(payload: dict) -> None:
    sys.stdout.write("__SKILLER_RESULT__" + json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> int:
    if len(sys.argv) < 3:
        _emit({
            "summary": {"passed": 0, "failed": 0, "errors": 1, "skipped": 0},
            "duration": 0.0,
            "tests": [{
                "nodeid": "<driver>",
                "outcome": "error",
                "longrepr": "usage: _test_driver.py <task_dir> <test_file> [...]",
            }],
        })
        return 2

    task_dir = Path(sys.argv[1]).resolve()
    test_files = sys.argv[2:]

    sys.path.insert(0, str(task_dir))
    sys.modules["pytest"] = _make_pytest_stub()

    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    tests_out: list[dict] = []
    t0 = time.perf_counter()

    for tf in test_files:
        path = (task_dir / tf).resolve()
        try:
            mod = _load_module(path)
        except Exception:
            summary["errors"] += 1
            tests_out.append({
                "nodeid": f"{tf}::<collection>",
                "outcome": "error",
                "longrepr": traceback.format_exc(),
            })
            continue

        names = sorted(
            n for n in vars(mod)
            if n.startswith("test_") and callable(getattr(mod, n))
        )
        for name in names:
            fn = getattr(mod, name)
            nodeid = f"{tf}::{name}"
            try:
                fn()
            except _Skip as e:
                summary["skipped"] += 1
                tests_out.append({
                    "nodeid": nodeid, "outcome": "skipped",
                    "longrepr": str(e),
                })
            except AssertionError:
                summary["failed"] += 1
                tests_out.append({
                    "nodeid": nodeid, "outcome": "failed",
                    "longrepr": traceback.format_exc(),
                })
            except Exception:
                summary["errors"] += 1
                tests_out.append({
                    "nodeid": nodeid, "outcome": "error",
                    "longrepr": traceback.format_exc(),
                })
            else:
                summary["passed"] += 1
                tests_out.append({"nodeid": nodeid, "outcome": "passed"})

    duration = time.perf_counter() - t0
    _emit({"summary": summary, "duration": duration, "tests": tests_out})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
