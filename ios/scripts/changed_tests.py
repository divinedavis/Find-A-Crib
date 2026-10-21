#!/usr/bin/env python3
"""The tests most likely to fail on THIS ship, so ship.sh runs them first.

The full iPhone pass takes ~17 min and a failure near its end costs the whole
run: on 2026-10-21 build 153 failed twice on the accessibility audit, each time
17-20 min in, while the audit alone takes ~90 s. This prints -only-testing ids
for a quick first pass that fails in a few minutes instead:

  * every unit test (FindACribTests, ~10 s);
  * the whole AccessibilityAuditTests class (any view change can trip it);
  * every UI test whose body changed since the last shipped build;
  * every UI test that queries an identifier written in a changed app file.

"Since the last ship" = since the last commit that bumped
CURRENT_PROJECT_VERSION in project.yml, plus uncommitted changes. Capped at
MAX_UI tests, most-matched first; the full suite still runs afterwards.

  python3 scripts/changed_tests.py        # one id per line
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UI = "FindACribUITests"
ALWAYS = ["FindACribTests", f"{UI}/AccessibilityAuditTests"]
NEVER = {"PerformanceTests", "MarketingCapture"}   # perf runs on its own; capture is not a test
MAX_UI = 20

FUNC = re.compile(r"^\s*(?:override\s+)?func\s+(test\w*)\s*\(")
CLASS = re.compile(r"^\s*(?:final\s+)?class\s+(\w+)\s*:")
SUBSCRIPT = re.compile(r'\["((?:[^"\\]|\\\([^)]*\))*)"\]')
LITERAL = re.compile(r'"([a-z][a-z0-9]*-[A-Za-z0-9-]*)')   # kebab ids: "card-address", "tab-"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def changed_lines():
    """{path relative to ios/: set of changed new-side line numbers}."""
    base = git("log", "-1", "--format=%H", "-G", "CURRENT_PROJECT_VERSION", "--", "project.yml").strip()
    out = {}
    for diff in (git("diff", "-U0", "--relative", base, "--") if base else "",
                 git("diff", "-U0", "--relative", "HEAD", "--")):
        path = None
        for line in diff.splitlines():
            if line.startswith("+++ "):
                path = None if line.endswith("/dev/null") else line[6:]
            elif line.startswith("@@") and path:
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                start, n = int(m.group(1)), int(m.group(2) or 1)
                out.setdefault(path, set()).update(range(start, start + max(n, 1)))
    return out


def ui_tests():
    """[(id, file, first line, last line, body)] for every UI test function."""
    tests = []
    # Relative paths without glob(root_dir=), which needs Python 3.10; ship.sh
    # runs the system python3 (3.9).
    for f in sorted(os.path.relpath(g, ROOT) for g in glob.glob(os.path.join(ROOT, UI, "*.swift"))):
        lines = open(os.path.join(ROOT, f), encoding="utf-8").read().splitlines()
        cls, cur = None, None
        for i, line in enumerate(lines, 1):
            if (m := CLASS.match(line)):
                cls = m.group(1)
            if FUNC.match(line) or re.match(r"^\s*(?:private\s+|static\s+)*func\s", line) or CLASS.match(line):
                if cur:
                    tests.append(cur)
                    cur = None
                if (m := FUNC.match(line)) and cls and cls not in NEVER:
                    cur = [f"{UI}/{cls}/{m.group(1)}", f, i, i, []]
            if cur:
                cur[3] = i
                cur[4].append(line)
        if cur:
            tests.append(cur)
    return [(t[0], t[1], t[2], t[3], "\n".join(t[4])) for t in tests]


def main():
    os.chdir(ROOT)
    changed = changed_lines()
    tests = ui_tests()
    score = {}

    for tid, f, first, last, _ in tests:            # the test itself changed
        if any(first <= n <= last for n in changed.get(f, ())):
            score[tid] = score.get(tid, 0) + 100

    ids = set()                                      # identifiers in changed app code
    for path, nums in changed.items():
        if path.startswith("FindACrib/") and path.endswith(".swift") and os.path.exists(path):
            ids.update(m.group(1) for line in open(path, encoding="utf-8") for m in LITERAL.finditer(line))
    for tid, _, _, _, body in tests:
        refs = {r.split("\\(")[0] for r in SUBSCRIPT.findall(body)}
        hits = sum(1 for r in refs if r in ids or any(i.startswith(r) and r.endswith("-") for i in ids))
        if hits:
            score[tid] = score.get(tid, 0) + hits

    picked = sorted(score, key=lambda t: (-score[t], t))[:MAX_UI]
    for t in ALWAYS + [t for t in picked if not t.startswith(ALWAYS[1] + "/")]:
        print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
