#!/usr/bin/env python3
"""Replace the App Store header VIDEO on Find A Crib's live product page.

asc_creative_assets.py handles images only. The header video needs its own
upload (appAssetLibraryVideos), its own review item, and a swap: Apple only
places APPROVED assets on a live version, and a placement can't be updated
(create and delete only), so `swap` waits for approval, deletes the old
header placement and creates the new one, putting the old video back if the
create fails.

    ~/.venvs/dhcr-map/bin/python scripts/asc_header_video.py upload FILE --ref REF
    ~/.venvs/dhcr-map/bin/python scripts/asc_header_video.py submit --ref REF --yes
    ~/.venvs/dhcr-map/bin/python scripts/asc_header_video.py swap --ref REF --yes [--wait]

REF is the Asset Library reference name, e.g.
fac-2026-10c/default/header-video-3840x1646.mp4. `submit` and `swap` are
outward-facing and need --yes.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from asc_creative_assets import API, _cfg, call

APP = _cfg()["ASC_APP_ID"]
HEADER = "PRODUCT_PAGE_HEADER_ASSET"


def log(*a):
    print(datetime.now().isoformat(timespec="seconds"), *a, flush=True)


def videos():
    out, path = [], f"/v1/appAssetLibraries/{APP}/videos?limit=200&filter[category]=CREATIVE_ASSETS"
    while path:
        d = call("GET", path)
        out += d["data"]
        n = d.get("links", {}).get("next")
        path = n[len(API):] if n else None
    return [v for v in out if v["attributes"].get("state") != "ARCHIVED"]


def find(ref):
    hits = [v for v in videos() if v["attributes"].get("referenceName") == ref]
    return hits[0] if hits else None


def upload(path, ref):
    if find(ref):
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


def submit(ref):
    v = find(ref)
    # An uploaded video's draft state is COMPLETE (images say PREPARE_FOR_SUBMISSION).
    if not v or v["attributes"].get("state") not in ("COMPLETE", "PREPARE_FOR_SUBMISSION"):
        sys.exit(f"{ref}: no draft to submit ({v and v['attributes'].get('state')})")
    open_subs = call("GET", f"/v1/reviewSubmissions?filter[app]={APP}"
                            "&filter[state]=READY_FOR_REVIEW,WAITING_FOR_REVIEW,IN_REVIEW,UNRESOLVED_ISSUES")["data"]
    if open_subs:
        sys.exit(f"app has an open review submission ({open_subs[0]['id']}); not mixing the video into it")
    sub = call("POST", "/v1/reviewSubmissions", {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
        "relationships": {"app": {"data": {"type": "apps", "id": APP}}}}})["data"]
    try:
        call("POST", "/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
            "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}},
            "appAssetLibraryVideo": {"data": {"type": "appAssetLibraryVideos", "id": v["id"]}}}}})
    except SystemExit:
        # An empty READY_FOR_REVIEW submission blocks every other session's
        # submit. Apple refuses DELETE on reviewSubmissions; cancel it instead.
        # (A fresh upload can 409 here for a minute while Apple finishes it.)
        call("PATCH", f"/v1/reviewSubmissions/{sub['id']}", {"data": {
            "type": "reviewSubmissions", "id": sub["id"], "attributes": {"canceled": True}}})
        raise
    done = call("PATCH", f"/v1/reviewSubmissions/{sub['id']}", {"data": {
        "type": "reviewSubmissions", "id": sub["id"], "attributes": {"submitted": True}}})["data"]
    log("submission", sub["id"], done["attributes"].get("state"))


def live_localizations():
    vs = call("GET", f"/v1/apps/{APP}/appStoreVersions?filter[appStoreState]=READY_FOR_SALE&filter[platform]=IOS")["data"]
    if not vs:
        sys.exit("no live iOS version")
    return call("GET", f"/v1/appStoreVersions/{vs[0]['id']}/appStoreVersionLocalizations")["data"]


def place(asset_kind, asset_id, loc_id):
    typ = "appAssetLibraryVideos" if asset_kind == "video" else "appAssetLibraryImages"
    return call("POST", "/v1/appAssetLibraryPlacements", {"data": {"type": "appAssetLibraryPlacements",
        "attributes": {"placementType": HEADER, "placementGroup": "DEFAULT_PROFILE"},
        "relationships": {asset_kind: {"data": {"type": typ, "id": asset_id}},
                          "appStoreVersionLocalization": {"data": {"type": "appStoreVersionLocalizations", "id": loc_id}}}}})["data"]


def swap(ref):
    """None while waiting on review, 0 when placed, 1 if Apple rejected it."""
    v = find(ref)
    state = v and v["attributes"].get("state")
    if state == "REJECTED":
        log("rejected", ref)
        return 1
    if state != "APPROVED":
        log("waiting", ref, state)
        return None
    for loc in live_localizations():
        heads = [p for p in call("GET", f"/v1/appStoreVersionLocalizations/{loc['id']}/placements"
                                        "?limit=200&include=image,video")["data"]
                 if p["attributes"]["placementType"] == HEADER]
        for p in heads:   # only localizations that already carry a header are swapped
            r = p["relationships"]
            old_kind = "video" if (r.get("video", {}).get("data")) else "image"
            old_id = (r.get(old_kind, {}).get("data") or {}).get("id")
            if old_id == v["id"]:
                log("already", loc["attributes"]["locale"])
                continue
            call("DELETE", f"/v1/appAssetLibraryPlacements/{p['id']}")
            try:
                n = place("video", v["id"], loc["id"])
                log("placed", loc["attributes"]["locale"], n["id"], n["attributes"].get("state"))
            except BaseException:
                log("create failed, restoring the old header on", loc["attributes"]["locale"])
                place(old_kind, old_id, loc["id"])
                raise
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["upload", "submit", "swap"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--wait", action="store_true", help="swap: poll every 15 min for up to 4 days")
    a = ap.parse_args()
    if a.cmd == "upload":
        return upload(a.file, a.ref)
    if not a.yes:
        sys.exit(f"{a.cmd} is outward-facing; pass --yes")
    if a.cmd == "submit":
        return submit(a.ref)
    deadline = time.time() + 4 * 86400
    while True:
        try:
            rc = swap(a.ref)
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
