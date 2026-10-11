#!/usr/bin/env python3
"""Product page optimization (A/B) tests through the ASC API (spec 4.5.1).

    ~/.venvs/dhcr-map/bin/python scripts/asc_experiments.py create APP_ID "NAME" "TREATMENT" \
        [--header ASSET_REF] [--lead FILENAME] [--traffic 50]

One treatment against the live page. The treatment starts as a copy of the
live iOS version (screenshots, header, search asset); then
  --header  swaps its header for that Asset Library image, and/or
  --lead    moves the iPhone screenshot whose file name contains FILENAME
            to the front.
An experiment with the same name is left alone, so a rerun is a no-op.
Nothing is submitted or started: Apple reviews it, then it has to be started.
"""
import argparse
import sys

from asc_creative_assets import call, images


def placements(loc_id):
    return call("GET", f"/v1/appStoreVersionExperimentTreatmentLocalizations/{loc_id}/placements?limit=200&include=image")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create"])
    ap.add_argument("app_id")
    ap.add_argument("name")
    ap.add_argument("treatment")
    ap.add_argument("--header")
    ap.add_argument("--lead")
    ap.add_argument("--traffic", type=int, default=50)
    a = ap.parse_args()
    if not (a.header or a.lead):
        sys.exit("give --header and/or --lead, or the treatment is the control")

    if any(x["attributes"].get("name") == a.name for x in
           call("GET", f"/v1/apps/{a.app_id}/appStoreVersionExperimentsV2?limit=50")["data"]):
        print(f"skip     {a.name} (exists)")
        return
    header_id = None
    if a.header:
        header_id = next((i["id"] for i in images(a.app_id)
                          if i["attributes"].get("referenceName") == a.header
                          and i["attributes"].get("state") == "APPROVED"), None)
        if not header_id:
            sys.exit(f"{a.header} is not an APPROVED Asset Library image")

    x = call("POST", "/v2/appStoreVersionExperiments", {"data": {
        "type": "appStoreVersionExperiments",
        "attributes": {"name": a.name, "platform": "IOS", "trafficProportion": a.traffic},
        "relationships": {"app": {"data": {"type": "apps", "id": a.app_id}}}}})["data"]
    t = call("POST", "/v1/appStoreVersionExperimentTreatments", {"data": {
        "type": "appStoreVersionExperimentTreatments", "attributes": {"name": a.treatment},
        "relationships": {"appStoreVersionExperimentV2": {"data": {"type": "appStoreVersionExperiments", "id": x["id"]}}}}})["data"]
    loc = call("POST", "/v1/appStoreVersionExperimentTreatmentLocalizations", {"data": {
        "type": "appStoreVersionExperimentTreatmentLocalizations", "attributes": {"locale": "en-US"},
        "relationships": {"appStoreVersionExperimentTreatment": {"data": {"type": "appStoreVersionExperimentTreatments", "id": t["id"]}}}}})["data"]

    d = placements(loc["id"])
    if header_id:
        for p in d["data"]:
            if p["attributes"]["placementType"] == "PRODUCT_PAGE_HEADER_ASSET":
                call("DELETE", f"/v1/appAssetLibraryPlacements/{p['id']}")
        call("POST", "/v1/appAssetLibraryPlacements", {"data": {
            "type": "appAssetLibraryPlacements",
            "attributes": {"placementType": "PRODUCT_PAGE_HEADER_ASSET", "placementGroup": "DEFAULT_PROFILE"},
            "relationships": {
                "image": {"data": {"type": "appAssetLibraryImages", "id": header_id}},
                "appStoreVersionExperimentTreatmentLocalization": {"data": {
                    "type": "appStoreVersionExperimentTreatmentLocalizations", "id": loc["id"]}}}}})
    if a.lead:
        names = {i["id"]: (i["attributes"].get("fileName") or "") + " " + (i["attributes"].get("referenceName") or "")
                 for i in d.get("included", [])}
        shots = [p for p in d["data"] if p["attributes"]["placementType"] == "APP_SCREENSHOT"
                 and p["attributes"]["placementGroup"].startswith("IPHONE")]
        group = shots[0]["attributes"]["placementGroup"]
        shots = [p for p in shots if p["attributes"]["placementGroup"] == group]
        lead = [p for p in shots if a.lead in names.get(p["relationships"]["image"]["data"]["id"], "")]
        if len(lead) != 1:
            sys.exit(f"--lead {a.lead!r} matched {len(lead)} of: {[names.get(p['relationships']['image']['data']['id']) for p in shots]}")
        # placements come back unordered; the legacy screenshot set keeps
        # the page's display order, so rank the rest by its file names
        shown = []
        for s in call("GET", f"/v1/appStoreVersionExperimentTreatmentLocalizations/{loc['id']}/appScreenshotSets?limit=50")["data"]:
            if "IPHONE" in s["attributes"]["screenshotDisplayType"]:
                shown = [i["attributes"].get("fileName") for i in
                         call("GET", f"/v1/appScreenshotSets/{s['id']}/appScreenshots")["data"]]
                break
        rank = {f: n for n, f in enumerate(shown)}
        fname = lambda p: names.get(p["relationships"]["image"]["data"]["id"], " ").split(" ")[0]
        order = lead + sorted((p for p in shots if p is not lead[0]), key=lambda p: rank.get(fname(p), 99))
        call("POST", "/v1/appAssetLibraryPlacementOrderingRequests", {"data": {
            "type": "appAssetLibraryPlacementOrderingRequests", "attributes": {"placementGroup": group},
            "relationships": {
                "orderedPlacements": {"data": [{"type": "appAssetLibraryPlacements", "id": p["id"]} for p in order]},
                "appStoreVersionExperimentTreatmentLocalization": {"data": {
                    "type": "appStoreVersionExperimentTreatmentLocalizations", "id": loc["id"]}}}}})
    print(f"created  {a.name}  experiment {x['id']}  ({x['attributes'].get('state')})")


if __name__ == "__main__":
    main()
