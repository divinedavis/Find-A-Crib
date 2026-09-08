#!/usr/bin/env python3
"""Resubmit a rejected App Store version with a new build.

    scripts/resubmit.py --build 21            # wait for build 21, attach, resolve, submit
    scripts/resubmit.py --build 21 --dry-run

Flow (proved 2026-09-04, see memory reference_asc_resubmit_after_rejection):
  1. find the build by NUMBER (not "newest VALID" — a fresh upload can take
     minutes to appear and the newest valid one is then the previous build);
     wait while it is PROCESSING.
  2. PATCH the appStoreVersion's build relationship to it.
  3. PATCH the rejected reviewSubmissionItem {resolved: true} — the item and
     the version flip to READY_FOR_REVIEW. DELETE/POST of items both 409.
  4. PATCH the reviewSubmission {submitted: true} — WAITING_FOR_REVIEW.
The API has no endpoint for the App Review message thread; that reply is
pasted in App Store Connect by hand.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import register_in_asc as asc  # noqa: E402

P = lambda p: p.replace("/v1", "", 1) if asc.API_BASE.endswith("/v1") else p  # noqa: E731


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True, help="build number as uploaded (CURRENT_PROJECT_VERSION)")
    ap.add_argument("--version", default="1.0", help="app version string")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", type=int, default=1800, help="seconds to wait for processing")
    a = ap.parse_args()
    cfg = asc.load_config()
    tok = asc.make_token(cfg)
    app = cfg["ASC_APP_ID"]

    # 1. the build, by number, processed
    deadline = time.time() + a.wait
    build = None
    while time.time() < deadline:
        _, d = asc.api(tok, "GET", P("/v1/builds"), params={"filter[app]": app, "filter[version]": a.build, "limit": 5})
        rows = d.get("data", [])
        if rows:
            build = rows[0]
            state = build["attributes"]["processingState"]
            print(f"build {a.build}: {build['id']} {state}")
            if state == "VALID":
                break
            if state in ("FAILED", "INVALID"):
                raise SystemExit(f"build {a.build} is {state}")
        else:
            print(f"build {a.build}: not visible yet")
        time.sleep(30)
        tok = asc.make_token(cfg)
    if not build or build["attributes"]["processingState"] != "VALID":
        raise SystemExit("gave up waiting for the build")

    # 2. the version
    _, d = asc.api(tok, "GET", P(f"/v1/apps/{app}/appStoreVersions"), params={"filter[platform]": "IOS", "filter[versionString]": a.version})
    ver = d["data"][0]
    print(f"version {a.version}: {ver['id']} {ver['attributes']['appStoreState']}")

    # 3. the submission with the rejected item
    _, d = asc.api(tok, "GET", P("/v1/reviewSubmissions"), params={"filter[app]": app, "filter[platform]": "IOS", "limit": 5})
    subs = [s for s in d.get("data", []) if s["attributes"].get("state") == "UNRESOLVED_ISSUES"]
    if not subs:
        raise SystemExit("no submission in UNRESOLVED_ISSUES")
    sub = subs[0]
    _, items = asc.api(tok, "GET", P(f"/v1/reviewSubmissions/{sub['id']}/items"))
    rejected = [i for i in items.get("data", []) if i["attributes"].get("state") == "REJECTED"]
    print(f"submission {sub['id']}: {len(rejected)} rejected item(s)")

    if a.dry_run:
        print("dry run — would attach the build, resolve the item(s) and submit")
        return

    asc.api(tok, "PATCH", P(f"/v1/appStoreVersions/{ver['id']}/relationships/build"),
            body={"data": {"type": "builds", "id": build["id"]}})
    print("attached build to the version")
    for it in rejected:
        asc.api(tok, "PATCH", P(f"/v1/reviewSubmissionItems/{it['id']}"),
                body={"data": {"type": "reviewSubmissionItems", "id": it["id"], "attributes": {"resolved": True}}})
        print(f"resolved item {it['id'][:12]}…")
    _, d = asc.api(tok, "PATCH", P(f"/v1/reviewSubmissions/{sub['id']}"),
                   body={"data": {"type": "reviewSubmissions", "id": sub["id"], "attributes": {"submitted": True}}})
    print("submission state:", d.get("data", {}).get("attributes", {}).get("state"))


if __name__ == "__main__":
    main()
