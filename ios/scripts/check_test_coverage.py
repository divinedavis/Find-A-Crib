#!/usr/bin/env python3
"""Keep the XCUITest suite in step with the app as features come and go
(owner, 2026-10-02: "these should be dynamic as i build features and remove
features ... check after every change and push to test flight").

Two failures, both checked from source on every ship (ship.sh) — no simulator:

  * UNCOVERED: a folder under FindACrib/Features/ that no UI test touches —
    none of its identifiers is queried by a test, and no tab test names it.
    A new feature has to come with at least one test.
  * STALE: a UI test queries an identifier that no longer exists anywhere in
    the app, i.e. the feature was removed or renamed and its test now waits
    for something that can never appear. An `XCTAssertFalse(...exists)` line
    is a deliberate "this must be gone" check and is left alone.

The accessibility audit and performance tests find screens at run time, so they
follow the app by themselves; this script is the part that needs source.
Exit 1 with a list on any failure.
"""
import glob
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
APP, FEATURES, UI = "FindACrib", "FindACrib/Features", "FindACribUITests"

# \( ... ) interpolation first (it may hold quotes of its own), then any escape.
LITERAL = re.compile(r'"((?:\\\((?:[^()]|\([^()]*\))*\)|\\.|[^"\\])*)"')
SUBSCRIPT = re.compile(r'\["((?:[^"\\]|\\\([^)]*\))*)"\]')
ID_LIKE = re.compile(r"^[a-z][a-z0-9]*-")   # kebab ids: "card-address", "tab-Profile"


def stem(s):
    """The fixed part of a literal: "tab-\\(name)" -> "tab-"."""
    return s.split("\\(")[0]


def literals(path):
    # line by line, so one odd literal cannot shift every quote after it
    with open(path, encoding="utf-8") as f:
        return [stem(m.group(1)) for line in f for m in LITERAL.finditer(line)]


def main():
    os.chdir(ROOT)
    app_files = glob.glob(f"{APP}/**/*.swift", recursive=True)
    app_lits = {s for f in app_files for s in literals(f) if s}

    refs, live_refs = set(), set()
    for f in glob.glob(f"{UI}/*.swift"):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                for m in SUBSCRIPT.finditer(line):
                    refs.add(m.group(1))
                    if "XCTAssertFalse" not in line:
                        live_refs.add(m.group(1))

    def in_app(ref):
        s = stem(ref)
        # an exact literal, a literal the ref was built from ("tab-" + name),
        # or a ref that is the fixed part of an interpolated app id
        return s in app_lits or any(s.startswith(a) and a.endswith("-") for a in app_lits) \
            or any(a.startswith(s) for a in app_lits if s.endswith("-"))

    stale = sorted(r for r in live_refs if ID_LIKE.match(r) and not in_app(r))

    ref_stems = {stem(r) for r in refs}
    uncovered = []
    for d in sorted(os.listdir(FEATURES)):
        folder = os.path.join(FEATURES, d)
        if not os.path.isdir(folder):
            continue
        ids = {s for f in glob.glob(f"{folder}/**/*.swift", recursive=True)
               for s in literals(f) if ID_LIKE.match(s)}
        hit = any(i in ref_stems or any(r.startswith(i) for r in ref_stems if i.endswith("-")) for i in ids)
        named = any(r.startswith("tab-") and d.lower() in r.lower().replace(" ", "") for r in refs)
        if not (hit or named):
            uncovered.append(d)

    print(f"test coverage: {len(os.listdir(FEATURES))} feature folders, {len(refs)} identifiers queried by UI tests")
    ok = True
    if uncovered:
        ok = False
        print("UNCOVERED features (add a UI test that queries one of their accessibilityIdentifiers):")
        for d in uncovered:
            print(f"  - {FEATURES}/{d}")
    if stale:
        ok = False
        print("STALE UI-test identifiers (in a test, nowhere in the app — remove or update the test):")
        for r in stale:
            print(f"  - {r}")
    if ok:
        print("test coverage OK: every feature has a UI test, no test points at a removed identifier")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
