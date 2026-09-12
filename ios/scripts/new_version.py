#!/usr/bin/env python3
"""Open the next App Store version, so the metadata and submit scripts have
something editable to write to.

    python3 scripts/new_version.py 1.2.0
    python3 scripts/new_version.py 1.2.0 --dry-run

Once a version reaches READY_FOR_SALE its record is frozen — every PATCH comes
back 409 INVALID_STATE — and `asc_metadata.py` exits with "no editable App
Store version". There is no way round that but to POST a new appStoreVersions
record; Apple then copies the description, keywords, screenshots and review
contact from the live version onto it, and asc_metadata.py overwrites whatever
of that has changed.

This is separate from the build number. `ship.sh` bumps
CURRENT_PROJECT_VERSION on every upload; MARKETING_VERSION in project.yml is
what this takes, and the two have to agree or the upload is rejected with
90062 ("must contain a higher version than the previously approved version").

Full release path, in order:

    1. edit MARKETING_VERSION in project.yml
    2. scripts/ship.sh                     build, test, upload to TestFlight
    3. scripts/new_version.py <version>    this
    4. scripts/asc_metadata.py             listing, What's New, review notes
    5. scripts/attach_build.py             once the build has processed
    6. scripts/submit_for_review.py        preflight + submit
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asc_metadata as m  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", help='the new marketing version, e.g. "1.2.0"')
    ap.add_argument("--dry-run", action="store_true", help="say what would happen")
    a = ap.parse_args()

    cfg = m.load_config()
    asc = m.ASC(cfg)
    app_id = cfg["ASC_APP_ID"]

    versions = asc.get(f"/apps/{app_id}/appStoreVersions", limit=10)["data"]
    for v in versions:
        at = v["attributes"]
        print(f"  {at['versionString']:<8} {at['appStoreState']}")
        if at["versionString"] == a.version:
            print(f"\n{a.version} already exists ({at['appStoreState']}) — nothing to do.")
            return 0
    editable = [v for v in versions if v["attributes"]["appStoreState"] in m.EDITABLE]
    if editable:
        at = editable[0]["attributes"]
        raise SystemExit(f"\n{at['versionString']} is already open for editing "
                         f"({at['appStoreState']}). Rename it or submit it before opening {a.version}.")

    if a.dry_run:
        print(f"\nwould create App Store version {a.version} (iOS)")
        return 0

    created = asc.post("/appStoreVersions", {"data": {
        "type": "appStoreVersions",
        "attributes": {"versionString": a.version, "platform": "IOS"},
        "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
    }})["data"]
    print(f"\ncreated {a.version} ({created['id']}) — {created['attributes']['appStoreState']}")
    print("next: scripts/asc_metadata.py, then attach_build.py, then submit_for_review.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
