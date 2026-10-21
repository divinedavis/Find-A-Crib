"""changed_tests.py finds real UI tests and always leads with the quick groups."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changed_tests as ct  # noqa: E402


def test_parses_ui_tests_and_skips_perf():
    ids = [t[0] for t in ct.ui_tests()]
    assert "FindACribUITests/FindACribUITests/testSearchTabKeepsItsScrollAfterAnotherTab" in ids
    assert "FindACribUITests/AccessibilityAuditTests/testEveryTab" in ids
    assert not any("/PerformanceTests/" in i or "/MarketingCapture/" in i for i in ids)


def test_output_starts_with_unit_tests_and_audit_and_is_capped():
    out = subprocess.run([sys.executable, ct.__file__], capture_output=True, text=True, check=True).stdout.split()
    assert out[:2] == ct.ALWAYS
    assert len(out) <= len(ct.ALWAYS) + ct.MAX_UI
    assert len(out) == len(set(out))


if __name__ == "__main__":
    test_parses_ui_tests_and_skips_perf(); test_output_starts_with_unit_tests_and_audit_and_is_capped(); print("ok")
