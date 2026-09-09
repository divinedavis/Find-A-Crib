#!/usr/bin/env python3
"""Submit the editable App Store version to App Review.

    python3 scripts/submit_for_review.py            # preflight + submit
    python3 scripts/submit_for_review.py --dry-run  # preflight only

Preflight (everything the API can see): a build is attached and export
compliance is answered, the localization has description/keywords/support
URL/screenshots and, after 1.0, What's New, and the review contact exists.
Run scripts/asc_metadata.py first; it writes all of that.

Submission is the reviewSubmissions flow (the old appStoreVersionSubmissions
endpoint is gone): find or create the draft submission for iOS, add the
version as an item, PATCH submitted=true. A version with an existing
submission in UNRESOLVED_ISSUES is a rejection — use resubmit.py for that.

Ship a new version without a rebuild: POST /appStoreVersions with the new
versionString, then attach the newest TestFlight build. Proved 2026-09-09:
1.0.1 accepted build 24 whose CFBundleShortVersionString is still 1.0, and
Apple copied description, keywords, screenshots and the review contact from
1.0 onto it.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asc_metadata as m  # noqa: E402


def preflight(asc, ids):
    ok = True
    def row(good, label):
        nonlocal ok
        ok = ok and bool(good)
        print(("  ok   " if good else "  MISSING ") + label)
    b = asc.get(f"/appStoreVersions/{ids['version']}/build").get("data")
    row(b and b["attributes"]["processingState"] == "VALID", f"build attached ({b['attributes']['version'] if b else '-'})")
    row(b and b["attributes"].get("usesNonExemptEncryption") is not None, "export compliance answered on the build")
    loc = asc.get(f"/appStoreVersionLocalizations/{ids['version_loc']}")["data"]["attributes"]
    for k in ("description", "keywords", "supportUrl"):
        row(loc.get(k), k)
    if ids["version_string"] != "1.0":
        row(loc.get("whatsNew"), "whatsNew")
    sets = asc.get(f"/appStoreVersionLocalizations/{ids['version_loc']}/appScreenshotSets")["data"]
    n = sum(len(asc.get(f"/appScreenshotSets/{s['id']}/appScreenshots")["data"]) for s in sets)
    row(n >= 1, f"screenshots ({n})")
    det = asc.get(f"/appStoreVersions/{ids['version']}/appStoreReviewDetail").get("data")
    row(det and det["attributes"].get("contactEmail"), "review contact")
    return ok


def submit(asc, app_id, ids):
    subs = asc.get("/reviewSubmissions", **{"filter[app]": app_id, "filter[platform]": "IOS", "limit": 10})["data"]
    bad = [s for s in subs if s["attributes"]["state"] == "UNRESOLVED_ISSUES"]
    if bad:
        raise SystemExit("a submission is in UNRESOLVED_ISSUES (a rejection): use resubmit.py")
    draft = next((s for s in subs if s["attributes"]["state"] == "READY_FOR_REVIEW"), None)
    if draft:
        print("  reusing draft submission", draft["id"][:8])
    else:
        draft = asc.post("/reviewSubmissions", {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
                         "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}})["data"]
        print("  created submission", draft["id"][:8])
    items = asc.get(f"/reviewSubmissions/{draft['id']}/items", include="appStoreVersion")["data"]
    have = any((i["relationships"].get("appStoreVersion", {}).get("data") or {}).get("id") == ids["version"] for i in items)
    if not have:
        asc.post("/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
            "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": draft["id"]}},
            "appStoreVersion": {"data": {"type": "appStoreVersions", "id": ids["version"]}}}}})
        print("  added version", ids["version_string"], "to the submission")
    d = asc.patch(f"/reviewSubmissions/{draft['id']}", {"data": {"type": "reviewSubmissions", "id": draft["id"], "attributes": {"submitted": True}}})
    print("  submission state:", d["data"]["attributes"]["state"])
    v = asc.get(f"/appStoreVersions/{ids['version']}")["data"]["attributes"]
    print("  version", v["versionString"], "->", v["appStoreState"])


if __name__ == "__main__":
    cfg = m.load_config(); asc = m.ASC(cfg); app_id = cfg["ASC_APP_ID"]
    ids = m.resolve(asc, app_id)
    print(f"==> version {ids['version_string']} preflight")
    ok = preflight(asc, ids)
    if "--dry-run" in sys.argv:
        print("dry run —", "ready to submit" if ok else "NOT ready"); sys.exit(0 if ok else 1)
    if not ok:
        sys.exit("preflight failed; run scripts/asc_metadata.py and fix what is missing")
    print("==> submitting")
    submit(asc, app_id, ids)
