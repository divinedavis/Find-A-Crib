#!/usr/bin/env python3
"""Send an app's draft product-page metadata to App Review in one
submission, with no app version in it: custom product page versions,
In-App Events, A/B tests and Asset Library images still in draft.

    ~/.venvs/dhcr-map/bin/python scripts/asc_submit_metadata.py APP_ID          # dry run
    ~/.venvs/dhcr-map/bin/python scripts/asc_submit_metadata.py APP_ID --yes    # submit

Refuses if the app already has an open iOS submission (e.g. a version
another session is shipping), because Apple allows only one at a time.
"""
import argparse
import sys

import requests

from asc_creative_assets import API, _headers, call, images


def drafts(app_id):
    out = []
    for p in call("GET", f"/v1/apps/{app_id}/appCustomProductPages?limit=50")["data"]:
        for v in call("GET", f"/v1/appCustomProductPages/{p['id']}/appCustomProductPageVersions")["data"]:
            if v["attributes"].get("state") == "PREPARE_FOR_SUBMISSION":
                out.append(("appCustomProductPageVersion", "appCustomProductPageVersions", v["id"], p["attributes"]["name"]))
    for e in call("GET", f"/v1/apps/{app_id}/appEvents?limit=50")["data"]:
        # Apple refuses an event without a deep link and purchase requirement
        if e["attributes"].get("eventState") == "DRAFT" and e["attributes"].get("deepLink"):
            out.append(("appEvent", "appEvents", e["id"], e["attributes"]["referenceName"]))
    for x in call("GET", f"/v1/apps/{app_id}/appStoreVersionExperimentsV2?limit=50")["data"]:
        if x["attributes"].get("state") == "PREPARE_FOR_SUBMISSION":
            out.append(("appStoreVersionExperimentV2", "appStoreVersionExperiments", x["id"], x["attributes"]["name"]))
    for i in images(app_id):
        if i["attributes"].get("state") == "PREPARE_FOR_SUBMISSION":
            out.append(("appAssetLibraryImage", "appAssetLibraryImages", i["id"], i["attributes"].get("referenceName")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("app_id")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--skip-prefix", action="append", default=[],
                    help="leave Asset Library drafts whose reference name starts with this out")
    a = ap.parse_args()

    items = [d for d in drafts(a.app_id)
             if not (d[0] == "appAssetLibraryImage" and any((d[3] or "").startswith(s) for s in a.skip_prefix))]
    for rel, _, iid, label in items:
        print(f"{rel:<30} {label}")
    if not items:
        sys.exit("nothing in draft")
    if not a.yes:
        print("dry run; add --yes to submit")
        return
    open_subs = call("GET", f"/v1/reviewSubmissions?filter[app]={a.app_id}&filter[platform]=IOS"
                            "&filter[state]=READY_FOR_REVIEW,WAITING_FOR_REVIEW,IN_REVIEW,UNRESOLVED_ISSUES")["data"]
    if open_subs:
        sys.exit(f"app has an open review submission ({open_subs[0]['id']}, {open_subs[0]['attributes'].get('state')}); not mixing")
    sub = call("POST", "/v1/reviewSubmissions", {"data": {
        "type": "reviewSubmissions", "attributes": {"platform": "IOS"},
        "relationships": {"app": {"data": {"type": "apps", "id": a.app_id}}}}})["data"]
    added = 0
    for rel, typ, iid, label in items:
        r = requests.post(API + "/v1/reviewSubmissionItems", headers=_headers(), timeout=60, json={"data": {
            "type": "reviewSubmissionItems", "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}},
                rel: {"data": {"type": typ, "id": iid}}}}})
        if r.ok:
            added += 1
        else:
            print(f"left out {label}: {r.text[:800]}")
    if not added:
        call("DELETE", f"/v1/reviewSubmissions/{sub['id']}")
        sys.exit("nothing could be added; submission deleted")
    done = call("PATCH", f"/v1/reviewSubmissions/{sub['id']}", {"data": {
        "type": "reviewSubmissions", "id": sub["id"], "attributes": {"submitted": True}}})["data"]
    print(f"submission {sub['id']} -> {done['attributes'].get('state')}")


if __name__ == "__main__":
    main()
