#!/usr/bin/env python3
"""Swap the build on a version that is already WAITING_FOR_REVIEW, then resubmit.

    python3 scripts/replace_review_build.py --build 27 [--version 1.0.1] [--dry-run]

Apple locks a version while it waits for review, so the order is:
  1. wait for the new build to finish processing (VALID);
  2. cancel the open review submission (PATCH reviewSubmissions canceled=true)
     — the version drops back to PREPARE_FOR_SUBMISSION;
  3. attach the new build;
  4. re-apply the listing (asc_metadata.apply: notes, What's New, screenshots
     — the screenshots re-upload when their checksums changed);
  5. submit again (submit_for_review.submit).
Used 2026-09-09 to replace build 25 (old icon, blue chrome) with the teal
build on 1.0.1 without losing the review slot's metadata.
"""
import argparse, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import asc_metadata as m
import submit_for_review as sfr


def wait_for_build(asc, app_id, number, wait):
    deadline = time.time() + wait
    while time.time() < deadline:
        rows = asc.get("/builds", **{"filter[app]": app_id, "filter[version]": number, "limit": 5})["data"]
        if rows:
            st = rows[0]["attributes"]["processingState"]
            print(f"build {number}: {st}")
            if st == "VALID":
                return rows[0]
            if st in ("FAILED", "INVALID"):
                raise SystemExit(f"build {number} is {st}")
        else:
            print(f"build {number}: not visible yet")
        time.sleep(30)
    raise SystemExit("gave up waiting for the build")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True)
    ap.add_argument("--version", default="1.0.1")
    ap.add_argument("--wait", type=int, default=2400)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = m.load_config(); app_id = cfg["ASC_APP_ID"]
    asc = m.ASC(cfg)
    build = wait_for_build(asc, app_id, a.build, a.wait)
    asc = m.ASC(cfg)   # fresh token after the wait
    ver = asc.get(f"/apps/{app_id}/appStoreVersions", **{"filter[platform]": "IOS", "filter[versionString]": a.version})["data"][0]
    print(f"version {a.version}: {ver['attributes']['appStoreState']}")
    subs = asc.get("/reviewSubmissions", **{"filter[app]": app_id, "filter[platform]": "IOS", "limit": 10})["data"]
    open_ = [s for s in subs if s["attributes"]["state"] in ("WAITING_FOR_REVIEW", "IN_REVIEW", "READY_FOR_REVIEW")]
    print("open submissions:", [(s["id"][:8], s["attributes"]["state"]) for s in open_])
    if a.dry_run:
        print("dry run — would cancel, attach, re-apply the listing and submit"); return
    for s in open_:
        asc.patch(f"/reviewSubmissions/{s['id']}", {"data": {"type": "reviewSubmissions", "id": s["id"], "attributes": {"canceled": True}}})
        print("  canceled submission", s["id"][:8])
    for _ in range(20):
        state = asc.get(f"/appStoreVersions/{ver['id']}")["data"]["attributes"]["appStoreState"]
        if state in m.EDITABLE: break
        time.sleep(5)
    print("version now:", state)
    asc.patch(f"/appStoreVersions/{ver['id']}/relationships/build", {"data": {"type": "builds", "id": build["id"]}})
    print("  attached build", a.build)
    m.apply(asc, cfg)
    ids = m.resolve(asc, app_id)
    if not sfr.preflight(asc, ids):
        raise SystemExit("preflight failed after the swap")
    sfr.submit(asc, app_id, ids)


if __name__ == "__main__":
    main()
