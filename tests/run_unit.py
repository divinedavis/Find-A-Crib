#!/usr/bin/env python3
"""Run every tests/test_*.py — the gate deploy_app.sh, deploy_api.sh and CI
call before anything is copied anywhere.

    python3 tests/run_unit.py        # exit 0 only if every test passes

The repo mixes two styles and there is no pytest in the venv: unittest
TestCase classes, and bare pytest-style `def test_*()` functions
(test_creator_mail_reader, test_error_report_shadow). `unittest discover`
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
    for path in sorted(HERE.glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(mod))
        for name, fn in vars(mod).items():
            if name.startswith("test_") and inspect.isfunction(fn) and fn.__module__ == mod.__name__:
                bare.append((f"{path.stem}.{name}", fn))

    result = unittest.TextTestRunner(verbosity=0, stream=sys.stderr).run(suite)
    failed = len(result.failures) + len(result.errors)
    for label, fn in bare:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"FAIL {label}\n{traceback.format_exc()}", file=sys.stderr)
    total = result.testsRun + len(bare)
    print(f"unit tests: {total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
