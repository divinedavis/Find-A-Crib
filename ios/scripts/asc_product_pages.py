#!/usr/bin/env python3
"""Custom product pages through the ASC API (spec 4.5.1).

    ~/.venvs/dhcr-map/bin/python scripts/asc_product_pages.py cpp APP_ID PLAN.json --prefix NAME

PLAN.json is the creative-assets plan (~/Downloads/ASC-creative-assets/<app>/
plan.json): {"cpps": [{"slug", "name", "promo_text"}, ...]}. Each page is
copied from the live iOS version (screenshots, search asset), gets its own
promotional text, and its header is swapped for the APPROVED
`<prefix>/cpp-<slug>/header-*` asset. Pages that already exist (same name)
are left alone, so a rerun is a no-op. Nothing is submitted: the pages
stay PREPARE_FOR_SUBMISSION until asc_creative_assets.py-style review.
"""
import argparse
import json
import sys

from asc_creative_assets import call, images


def live_version(app_id):
    v = call("GET", f"/v1/apps/{app_id}/appStoreVersions?filter[platform]=IOS"
                    "&filter[appStoreState]=READY_FOR_SALE&limit=1")["data"]
    if not v:
        sys.exit("app has no live iOS version")
    return v[0]["id"]


def create_page(app_id, version_id, name, promo):
    d = call("POST", "/v1/appCustomProductPages", {
        "data": {"type": "appCustomProductPages", "attributes": {"name": name},
                 "relationships": {
                     "app": {"data": {"type": "apps", "id": app_id}},
                     "appStoreVersionTemplate": {"data": {"type": "appStoreVersions", "id": version_id}},
                     "appCustomProductPageVersions": {"data": [{"type": "appCustomProductPageVersions", "id": "${v1}"}]}}},
        "included": [
            {"type": "appCustomProductPageVersions", "id": "${v1}", "relationships": {
                "appCustomProductPageLocalizations": {"data": [{"type": "appCustomProductPageLocalizations", "id": "${l1}"}]}}},
            {"type": "appCustomProductPageLocalizations", "id": "${l1}",
             "attributes": {"locale": "en-US", "promotionalText": promo}}]})
    return d["data"], d["included"][0]["id"]


def swap_header(cpp_version_id, image_id):
    for loc in call("GET", f"/v1/appCustomProductPageVersions/{cpp_version_id}/appCustomProductPageLocalizations")["data"]:
        for p in call("GET", f"/v1/appCustomProductPageLocalizations/{loc['id']}/placements?limit=200")["data"]:
            if p["attributes"].get("placementType") == "PRODUCT_PAGE_HEADER_ASSET":
                call("DELETE", f"/v1/appAssetLibraryPlacements/{p['id']}")
        call("POST", "/v1/appAssetLibraryPlacements", {"data": {
            "type": "appAssetLibraryPlacements",
            "attributes": {"placementType": "PRODUCT_PAGE_HEADER_ASSET", "placementGroup": "DEFAULT_PROFILE"},
            "relationships": {
                "image": {"data": {"type": "appAssetLibraryImages", "id": image_id}},
                "appCustomProductPageLocalization": {"data": {"type": "appCustomProductPageLocalizations", "id": loc["id"]}}}}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cpp"])
    ap.add_argument("app_id")
    ap.add_argument("plan")
    ap.add_argument("--prefix", required=True)
    # A header still in draft can be placed on a page that hasn't been
    # submitted; it is then reviewed with the page (one review, not two).
    ap.add_argument("--allow-draft", action="store_true")
    a = ap.parse_args()

    plan = json.load(open(a.plan))
    headers = {}
    for i in images(a.app_id):
        ref = i["attributes"].get("referenceName") or ""
        if ref.startswith(f"{a.prefix}/cpp-") and "/header-" in ref and (i["attributes"].get("state") == "APPROVED"
                                                                       or (a.allow_draft and i["attributes"].get("state") == "PREPARE_FOR_SUBMISSION")):
            headers[ref.split("/")[1][4:]] = i["id"]
    existing = {p["attributes"]["name"]: p for p in
                call("GET", f"/v1/apps/{a.app_id}/appCustomProductPages?limit=50")["data"]}
    version_id = live_version(a.app_id)
    for page in plan["cpps"]:
        if page["name"] in existing:
            print(f"skip     {page['name']} (exists: {existing[page['name']]['attributes'].get('url')})")
            continue
        if page["slug"] not in headers:
            print(f"skip     {page['name']} (no APPROVED {a.prefix}/cpp-{page['slug']}/header asset)")
            continue
        cpp, cpp_version = create_page(a.app_id, version_id, page["name"], page["promo_text"])
        swap_header(cpp_version, headers[page["slug"]])
        print(f"created  {page['name']}  {cpp['attributes'].get('url')}")


if __name__ == "__main__":
    main()
