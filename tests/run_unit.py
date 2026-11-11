#!/usr/bin/env python3
"""Run every tests/test_*.py — the gate deploy_app.sh, deploy_api.sh and CI
call before anything is copied anywhere.

    python3 tests/run_unit.py        # exit 0 only if every test passes

The repo mixes two styles and there is no pytest in the venv: unittest
TestCase classes, and bare pytest-style `def test_*()` functions
(e.g. test_error_report_shadow). `unittest discover`
silently runs zero of the second kind, so this loads both.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def main() -> int:
    suite = unittest.TestSuite()
    bare: list[tuple[str, callable]] = []
    unloadable: list[tuple[str, str]] = []
    for path in sorted(HERE.glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        # A module that cannot be imported is still a failure — it is counted
        # as one below and the exit code stays non-zero, so no deploy slips
        # through. But it must not take the other 98 files down with it.
        # 2026-11-11: this container's system `cryptography` panics on import
        # (pyo3 PanicException, not ImportError), webpush.py imports it at
        # module load, and four tests/ modules import webpush — so this gate
        # died on the FIRST of them having run zero tests, and printed a Rust
        # backtrace naming no test. BaseException, not Exception, because that
        # panic is not an Exception subclass.
        try:
            spec.loader.exec_module(mod)
        except BaseException as exc:  # noqa: BLE001 - see above
            unloadable.append((path.stem, f"{type(exc).__name__}: {exc}".splitlines()[0]))
            continue
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(mod))
        for name, fn in vars(mod).items():
            if name.startswith("test_") and inspect.isfunction(fn) and fn.__module__ == mod.__name__:
                bare.append((f"{path.stem}.{name}", fn))

    result = unittest.TextTestRunner(verbosity=0, stream=sys.stderr).run(suite)
    failed = len(result.failures) + len(result.errors)
    for label, fn in bare:
        try:
            fn()
        except BaseException:  # noqa: BLE001 - a pyo3 PanicException is not an
            # Exception, and one of these raised it on 2026-11-11 (see above):
            # the whole gate then died HERE, after the TestCase suite had
            # already passed, having printed no summary and no exit status a
            # deploy script could read. A test that takes the process down is
            # a failed test, whatever it raises.
            failed += 1
            print(f"FAIL {label}\n{traceback.format_exc()}", file=sys.stderr)
    for label, why in unloadable:
        failed += 1
        print(f"WILL NOT IMPORT {label}: {why}", file=sys.stderr)
    total = result.testsRun + len(bare) + len(unloadable)
    print(f"unit tests: {total - failed}/{total} passed"
          + (f" ({len(unloadable)} file(s) would not import)" if unloadable else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
