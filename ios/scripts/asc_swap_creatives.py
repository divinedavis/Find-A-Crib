#!/usr/bin/env python3
"""Replace Find A Crib's live App Store creative assets with a new set.

asc_creative_assets.py uploads images and places a first set. This handles
the rest: the header VIDEO upload (appAssetLibraryVideos), one review
submission for every draft under a prefix (images and video), and the
swap. Apple only places APPROVED assets on a live version or an approved
custom product page, and a placement can't be updated (create and delete
only), so `swap` waits for approval, then for every header and search
placement on the live version and each approved custom product page,
deletes it and places the asset with the same path under the new prefix
(fac-2026-10/cpp-cities/header-3840x1646.png -> NEW/cpp-cities/...),
putting the old one back if the create fails.

    ~/.venvs/dhcr-map/bin/python scripts/asc_swap_creatives.py upload-video FILE --prefix P
    ~/.venvs/dhcr-map/bin/python scripts/asc_swap_creatives.py submit --prefix P --yes
    ~/.venvs/dhcr-map/bin/python scripts/asc_swap_creatives.py swap --prefix P --yes [--wait] [--dry-run]

The video's reference name is P/default/header-video-3840x1646.mp4.
`submit` and `swap` are outward-facing and need --yes.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from asc_creative_assets import API, _cfg, _headers, call

APP = _cfg()["ASC_APP_ID"]
TYPES = ("PRODUCT_PAGE_HEADER_ASSET", "APP_STORE_SEARCH_RESULTS_ASSET")
VIDEO_REF = "default/header-video-3840x1646.mp4"


def log(*a):
    print(datetime.now().isoformat(timespec="seconds"), *a, flush=True)


def library():
    """reference name -> (kind, id, state) for every live asset."""
    out = {}
    for kind in ("images", "videos"):
        path = f"/v1/appAssetLibraries/{APP}/{kind}?limit=200&filter[category]=CREATIVE_ASSETS"
        while path:
            d = call("GET", path)
            for i in d["data"]:
                at = i["attributes"]
                if at.get("state") != "ARCHIVED":
                    out[at.get("referenceName")] = (kind[:-1], i["id"], at.get("state"))
            n = d.get("links", {}).get("next")
            path = n[len(API):] if n else None
    return out


def upload_video(path, ref):
    if ref in library():
        sys.exit(f"{ref} is already in the library")
    f = Path(path).expanduser()
    data = f.read_bytes()
    d = call("POST", "/v1/appAssetLibraryVideos", {"data": {"type": "appAssetLibraryVideos",
        "attributes": {"category": "CREATIVE_ASSETS", "fileName": f.name, "fileSize": len(data), "referenceName": ref},
        "relationships": {"assetLibrary": {"data": {"type": "appAssetLibraries", "id": APP}}}}})["data"]
    for op in d["attributes"].get("uploadOperations") or []:
        hdrs = {h["name"]: h["value"] for h in op.get("requestHeaders") or []}
        r = requests.request(op["method"], op["url"], headers=hdrs,
                             data=data[op["offset"]:op["offset"] + op["length"]], timeout=600)
        if r.status_code >= 400:
            sys.exit(f"chunk failed {r.status_code} {r.text[:300]}")
    call("PATCH", f"/v1/appAssetLibraryVideos/{d['id']}", {"data": {
        "type": "appAssetLibraryVideos", "id": d["id"], "attributes": {"uploaded": True}}})
    for _ in range(150):
        a = call("GET", f"/v1/appAssetLibraryVideos/{d['id']}")["data"]["attributes"]
        if a.get("state") not in ("AWAITING_UPLOAD", "UPLOAD_COMPLETE", "PROCESSING"):
            break
        time.sleep(4)
    log(a.get("state"), ref, d["id"], a.get("stateDetails") or "")


def submit(prefix):
    # An uploaded video's draft state is COMPLETE; an image's is PREPARE_FOR_SUBMISSION.
    drafts = [(r, k, i) for r, (k, i, st) in library().items()
              if r.startswith(prefix + "/") and st in ("COMPLETE", "PREPARE_FOR_SUBMISSION")]
    if not drafts:
        sys.exit("no drafts under that prefix")
    open_subs = call("GET", f"/v1/reviewSubmissions?filter[app]={APP}"
                            "&filter[state]=READY_FOR_REVIEW,WAITING_FOR_REVIEW,IN_REVIEW,UNRESOLVED_ISSUES")["data"]
    if open_subs:
        sys.exit(f"app has an open review submission ({open_subs[0]['id']}); Apple allows one at a time")
    sub = call("POST", "/v1/reviewSubmissions", {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
        "relationships": {"app": {"data": {"type": "apps", "id": APP}}}}})["data"]
    bad = []
    for ref, kind, iid in sorted(drafts):
        rel = "appAssetLibraryVideo" if kind == "video" else "appAssetLibraryImage"
        for attempt in range(3):   # a just-uploaded asset can 409 for a minute
            r = requests.post(API + "/v1/reviewSubmissionItems", headers=_headers(), timeout=60, json={"data": {
                "type": "reviewSubmissionItems", "relationships": {
                    "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}},
                    rel: {"data": {"type": rel + "s", "id": iid}}}}})
            if r.ok:
                break
            time.sleep(30)
        log("added " if r.ok else "FAILED", ref, "" if r.ok else r.text[:400])
        if not r.ok:
            bad.append(ref)
    if bad:
        # Apple refuses DELETE on reviewSubmissions; cancel so it can't block other sessions.
        call("PATCH", f"/v1/reviewSubmissions/{sub['id']}", {"data": {
            "type": "reviewSubmissions", "id": sub["id"], "attributes": {"canceled": True}}})
        sys.exit(f"canceled {sub['id']}: {len(bad)} item(s) failed")
    done = call("PATCH", f"/v1/reviewSubmissions/{sub['id']}", {"data": {
        "type": "reviewSubmissions", "id": sub["id"], "attributes": {"submitted": True}}})["data"]
    log("submission", sub["id"], done["attributes"].get("state"))


def parents():
    """(label, relationship, type, id) for the live version's and each approved CPP's localizations."""
    vs = call("GET", f"/v1/apps/{APP}/appStoreVersions?filter[appStoreState]=READY_FOR_SALE&filter[platform]=IOS")["data"]
    if not vs:
        sys.exit("no live iOS version")
    out = [("v" + vs[0]["attributes"]["versionString"] + " " + loc["attributes"]["locale"],
            "appStoreVersionLocalization", "appStoreVersionLocalizations", loc["id"])
           for loc in call("GET", f"/v1/appStoreVersions/{vs[0]['id']}/appStoreVersionLocalizations")["data"]]
    for p in call("GET", f"/v1/apps/{APP}/appCustomProductPages?limit=50")["data"]:
        for v in call("GET", f"/v1/appCustomProductPages/{p['id']}/appCustomProductPageVersions")["data"]:
            if v["attributes"].get("state") != "APPROVED":
                continue
            for loc in call("GET", f"/v1/appCustomProductPageVersions/{v['id']}/appCustomProductPageLocalizations")["data"]:
                out.append((p["attributes"]["name"], "appCustomProductPageLocalization",
                            "appCustomProductPageLocalizations", loc["id"]))
    return out


def place(ptype, kind, asset_id, rel, typ, pid):
    atype = "appAssetLibraryVideos" if kind == "video" else "appAssetLibraryImages"
    return call("POST", "/v1/appAssetLibraryPlacements", {"data": {"type": "appAssetLibraryPlacements",
        "attributes": {"placementType": ptype, "placementGroup": "DEFAULT_PROFILE"},
        "relationships": {kind: {"data": {"type": atype, "id": asset_id}}, rel: {"data": {"type": typ, "id": pid}}}}})["data"]


def swap(prefix, dry):
    """None while waiting on review, 0 when done, 1 if Apple rejected something."""
    lib = library()
    mine = {r: v for r, v in lib.items() if r.startswith(prefix + "/")}
    states = {r: v[2] for r, v in mine.items()}
    if not mine or any(s == "REJECTED" for s in states.values()):
        log("rejected or missing:", states)
        return 1
    if any(s != "APPROVED" for s in states.values()) and not dry:
        log("waiting:", sorted(set(states.values())))
        return None
    by_id = {v[1]: r for r, v in lib.items()}
    for label, rel, typ, pid in parents():
        for p in call("GET", f"/v1/{typ}/{pid}/placements?limit=200&include=image,video")["data"]:
            ptype = p["attributes"]["placementType"]
            if ptype not in TYPES:
                continue
            r = p["relationships"]
            old_kind = "video" if r.get("video", {}).get("data") else "image"
            old_id = (r.get(old_kind, {}).get("data") or {}).get("id")
            old_ref = by_id.get(old_id, "")
            if old_ref.startswith(prefix + "/"):
                log("already", label, ptype)
                continue
            new_ref = prefix + "/" + old_ref.split("/", 1)[-1]
            if new_ref not in mine:
                log("no replacement for", label, ptype, old_ref)
                continue
            kind, new_id, _ = mine[new_ref]
            log("would swap" if dry else "swap", label, ptype, old_ref, "->", new_ref)
            if dry:
                continue
            call("DELETE", f"/v1/appAssetLibraryPlacements/{p['id']}")
            try:
                n = place(ptype, kind, new_id, rel, typ, pid)
                log("  placed", n["id"], n["attributes"].get("state"))
            except BaseException:
                log("  create failed, restoring", old_ref)
                place(ptype, old_kind, old_id, rel, typ, pid)
                raise
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["upload-video", "submit", "swap"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", action="store_true", help="swap: poll every 15 min for up to 4 days")
    a = ap.parse_args()
    if a.cmd == "upload-video":
        return upload_video(a.file, f"{a.prefix}/{VIDEO_REF}")
    if not (a.yes or a.dry_run):
        sys.exit(f"{a.cmd} is outward-facing; pass --yes")
    if a.cmd == "submit":
        return submit(a.prefix)
    deadline = time.time() + 4 * 86400
    while True:
        try:
            rc = swap(a.prefix, a.dry_run)
        except SystemExit as e:
            if not a.wait:
                raise
            log("poll failed:", e)
            rc = None
        if rc is not None or not a.wait or time.time() > deadline:
            return rc if rc is not None else 2
        time.sleep(900)


if __name__ == "__main__":
    sys.exit(main())
