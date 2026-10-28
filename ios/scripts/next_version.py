#!/usr/bin/env python3
"""Moves MARKETING_VERSION in project.yml to the next version once Apple has
approved the current one (scripts/ship.sh runs this before the bump).

An approved version is a closed train: an upload to it fails with 90062 ("must
contain a higher version than that of the previously approved version") and
90186 ("the train version is closed"). The daily build of 2026-10-27 lost its
upload that way after 1.3.6 was approved. So: when the App Store version
matching project.yml is approved, released or replaced, 1.3.6 becomes 1.3.7.
A version waiting for or in review still takes builds and is left alone, as is
one that isn't in App Store Connect yet. Same rule as Marracat's.

    ~/.venvs/spendcap/bin/python scripts/next_version.py [--dry-run]
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import asc_metadata as m  # noqa: E402

PROJECT = pathlib.Path(__file__).resolve().parent.parent / "project.yml"
CLOSED = {"PENDING_DEVELOPER_RELEASE", "PENDING_APPLE_RELEASE", "PROCESSING_FOR_APP_STORE",
          "READY_FOR_DISTRIBUTION", "READY_FOR_SALE", "REPLACED_WITH_NEW_VERSION",
          "DEVELOPER_REMOVED_FROM_SALE", "REMOVED_FROM_SALE"}
LINE = re.compile(r'(MARKETING_VERSION: ")(\d+(?:\.\d+)*)(")')


def bumped(version: str) -> str:
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def main() -> int:
    text = PROJECT.read_text()
    found = LINE.search(text)
    if not found:
        print("next_version: no MARKETING_VERSION in project.yml", file=sys.stderr)
        return 1
    current = found.group(2)
    cfg = m.load_config()
    try:
        versions = m.ASC(cfg).get(f"/apps/{cfg['ASC_APP_ID']}/appStoreVersions", limit=10,
                                  **{"filter[platform]": "IOS"})["data"]
    except SystemExit as e:  # ASC._ok raises SystemExit on a non-2xx
        print(f"next_version: App Store Connect refused ({e}); keeping {current}", file=sys.stderr)
        return 0
    states = {v["attributes"]["versionString"]: v["attributes"].get("appStoreState") for v in versions}
    state = states.get(current)
    if state not in CLOSED:
        print(f"version {current} ({state or 'not in App Store Connect yet'}): keeping it")
        return 0
    nxt = bumped(current)
    print(f"version {current} is {state}, a closed train: moving to {nxt}")
    if "--dry-run" not in sys.argv:
        PROJECT.write_text(LINE.sub(lambda x: f"{x.group(1)}{nxt}{x.group(3)}", text, count=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
