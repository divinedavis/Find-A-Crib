#!/usr/bin/env python3
"""In-App Events through the ASC API (spec 4.5.1).

    ~/.venvs/dhcr-map/bin/python scripts/asc_app_events.py create APP_ID EVENT.json

EVENT.json:
    {"referenceName", "badge", "purpose", "priority", "territories": ["USA"],
     "publishStart", "eventStart", "eventEnd",          # ISO 8601, UTC
     "deepLink": required by App Review (a link the app actually routes),
     "purchaseRequirement": required by App Review,
     "name" (<=30), "shortDescription" (<=50), "longDescription" (<=120),
     "card": "<asset referenceName>", "details": "<asset referenceName>"}

The card and details art must already be in the app's Asset Library
(asc_creative_assets.py upload). An event with the same referenceName is
left alone, so a rerun is a no-op. Nothing is submitted: the event stays
in draft until it goes into a review submission.
"""
import argparse
import json
import sys

from asc_creative_assets import call, images

LIMITS = {"name": 30, "shortDescription": 50, "longDescription": 120}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create"])
    ap.add_argument("app_id")
    ap.add_argument("spec")
    a = ap.parse_args()

    e = json.load(open(a.spec))
    for k in ("deepLink", "purchaseRequirement"):
        if not e.get(k):
            sys.exit(f"{k} is required: App Review refuses an event without it")
    for k, n in LIMITS.items():
        if len(e[k]) > n:
            sys.exit(f"{k} is {len(e[k])} characters; Apple allows {n}")
    if any(e["referenceName"] == x["attributes"].get("referenceName") for x in
           call("GET", f"/v1/apps/{a.app_id}/appEvents?limit=200")["data"]):
        print(f"skip     {e['referenceName']} (exists)")
        return
    art = {}
    for i in images(a.app_id):
        ref = i["attributes"].get("referenceName")
        if ref in (e["card"], e["details"]) and i["attributes"].get("state") != "ARCHIVED":
            art[ref] = i["id"]
    missing = [r for r in (e["card"], e["details"]) if r not in art]
    if missing:
        sys.exit(f"not in the Asset Library: {missing}")

    attrs = {"referenceName": e["referenceName"], "badge": e["badge"], "purpose": e["purpose"],
             "priority": e.get("priority", "NORMAL"), "primaryLocale": "en-US",
             "deepLink": e["deepLink"], "purchaseRequirement": e["purchaseRequirement"],
             "territorySchedules": [{"territories": e["territories"], "publishStart": e["publishStart"],
                                     "eventStart": e["eventStart"], "eventEnd": e["eventEnd"]}]}
    ev = call("POST", "/v1/appEvents", {"data": {"type": "appEvents", "attributes": attrs,
              "relationships": {"app": {"data": {"type": "apps", "id": a.app_id}}}}})["data"]
    loc = call("POST", "/v1/appEventLocalizations", {"data": {"type": "appEventLocalizations",
               "attributes": {"locale": "en-US", "name": e["name"], "shortDescription": e["shortDescription"],
                              "longDescription": e["longDescription"]},
               "relationships": {"appEvent": {"data": {"type": "appEvents", "id": ev["id"]}}}}})["data"]
    for ptype, ref in (("EVENT_CARD_ASSET", e["card"]), ("EVENT_DETAILS_PAGE_ASSET", e["details"])):
        call("POST", "/v1/appAssetLibraryPlacements", {"data": {
            "type": "appAssetLibraryPlacements",
            "attributes": {"placementType": ptype, "placementGroup": "DEFAULT_PROFILE"},
            "relationships": {
                "image": {"data": {"type": "appAssetLibraryImages", "id": art[ref]}},
                "appEventLocalization": {"data": {"type": "appEventLocalizations", "id": loc["id"]}}}}})
    print(f"created  {e['referenceName']}  event {ev['id']}  ({ev['attributes'].get('eventState')})")


if __name__ == "__main__":
    main()
