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

A build must carry the version's own CFBundleShortVersionString. 1.0.1
once took build 24 (still 1.0) on 2026-09-09, but only because 1.0 was
never approved; 1.3.4 with build 153 (1.3.3) was rejected within a minute,
2026-10-21: ITMS-90062, "must contain a higher version than that of the
previously approved version [1.3.3]". Bump MARKETING_VERSION and rebuild.
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
    pre = asc.get(f"/builds/{b['id']}/preReleaseVersion")["data"]["attributes"]["version"] if b else None
    row(pre == ids["version_string"], f"build is stamped {pre}, the version being submitted (ITMS-90062 otherwise)")
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


def ensure_no_phased_release(asc, ids):
    """Release to everyone at once — never Apple's 7-day phased rollout, on
    any of our apps (owner, 2026-10-17). A phased release left on the version
    (dashboard, or an older run of this script) is deleted; one already
    rolling out is completed, which releases it to everyone."""
    have = asc.get(f"/appStoreVersions/{ids['version']}/appStoreVersionPhasedRelease").get("data")
    if not have:
        print("  phased release: off (releases to everyone at once)")
    elif have["attributes"]["phasedReleaseState"] in ("ACTIVE", "PAUSED"):
        asc.patch(f"/appStoreVersionPhasedReleases/{have['id']}", {"data": {"type": "appStoreVersionPhasedReleases",
                  "id": have["id"], "attributes": {"phasedReleaseState": "COMPLETE"}}})
        print("  phased release: completed (now released to everyone)")
    else:
        asc.delete(f"/appStoreVersionPhasedReleases/{have['id']}")
        print("  phased release: removed (releases to everyone at once)")

def ensure_current_creatives():
    """The version being submitted shows the current header video and search
    image. A new version copies the previous one's placements, and 1.3.4 went
    live on 2026-10-22 with the cropped header video because 1.3.3 still had
    it. Best-effort: a failure here never blocks a submission."""
    try:
        import asc_swap_creatives as cr
        rc = cr.swap(cr.CURRENT, False)
        print("  header + search placements:", {0: "current", None: "waiting (asset review or A/B test)"}.get(rc, f"problem ({rc})"))
    except BaseException as e:      # SystemExit from its API helper included
        print("  header + search placements: not checked:", str(e)[:120])


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
    ensure_current_creatives()
    # In-App Events never ride along (they did from 2026-10-16): App Review
    # judges each item separately, and one rejected event held the accepted
    # 1.3.3 back from release for days. asc_events_auto.py submits events
    # on their own.
    d = asc.patch(f"/reviewSubmissions/{draft['id']}", {"data": {"type": "reviewSubmissions", "id": draft["id"], "attributes": {"submitted": True}}})
    print("  submission state:", d["data"]["attributes"]["state"])
    v = asc.get(f"/appStoreVersions/{ids['version']}")["data"]["attributes"]
    print("  version", v["versionString"], "->", v["appStoreState"])


if __name__ == "__main__":
    import asc_metadata; asc_metadata.refuse_if_frozen()   # owner's freeze, see ios/ASC_FREEZE
    cfg = m.load_config(); asc = m.ASC(cfg); app_id = cfg["ASC_APP_ID"]
    ids = m.resolve(asc, app_id)
    print(f"==> version {ids['version_string']} preflight")
    ok = preflight(asc, ids)
    if "--dry-run" in sys.argv:
        print("dry run —", "ready to submit" if ok else "NOT ready"); sys.exit(0 if ok else 1)
    if not ok:
        sys.exit("preflight failed; run scripts/asc_metadata.py and fix what is missing")
    print("==> submitting")
    ensure_no_phased_release(asc, ids)
    submit(asc, app_id, ids)
