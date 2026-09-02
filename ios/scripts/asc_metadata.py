#!/usr/bin/env python3
"""Write the App Store listing for Find A Crib through the API.

Everything App Store Connect accepts over its API lives here, so the listing
is a file in the repo rather than a memory of which boxes were ticked:
categories, subtitle, description, keywords, promo text, URLs, copyright, the
age-rating questionnaire, the review contact + notes, the free price, and the
6.9" screenshots from marketing/asc-screenshots/. Idempotent.

    python3 scripts/asc_metadata.py            # apply everything
    python3 scripts/asc_metadata.py --show     # print what is there now

Browser-only (no API): the App Privacy questionnaire and Submit for Review.
"""
from __future__ import annotations
import hashlib, os, pathlib, sys, time
import jwt, requests

HERE = pathlib.Path(__file__).resolve().parent
API = "https://api.appstoreconnect.apple.com/v1"
SHOTS = HERE.parent / "marketing" / "asc-screenshots"

SUBTITLE = "Rent-stabilized NYC, mapped"                       # <= 30 chars
KEYWORDS = "rent stabilized,nyc apartments,brooklyn,manhattan,bronx,queens,affordable housing,section 8,lottery"  # <=100
PROMO = ("Every rent-stabilized building in New York City on one map — what's for rent this "
         "week, who runs the building, and the lotteries you can apply for today.")
SITE = "https://findacrib.com/"
SUPPORT = "https://findacrib.com/support/"
PRIVACY = "https://findacrib.com/privacy/"
COPYRIGHT = "2026 Divine Davis"
PRIMARY_CATEGORY = "LIFESTYLE"
SECONDARY_CATEGORY = "REFERENCE"

DESCRIPTION = """Find A Crib puts every rent-stabilized building in New York City on a map — all 47,000 of them, from the state's own register — and tells you what you can't see from the sidewalk.

WHAT'S FOR RENT RIGHT NOW
Tick "Available now" and the map narrows to buildings with an apartment advertised in the last five days, with the asking rent on the pin. Filter by price and bedrooms, draw your own map area, and save the search.

KNOW THE BUILDING FIRST
Every building page shows its HPD record — open violations by class, complaints, the last registration — alongside the typical rent for the ZIP from HUD, a street-level Look Around view, and the nearest stabilized buildings on the same blocks.

WHO RUNS IT
Sign in to see the managing agent, owner and head officer the building has registered with HPD.

LOTTERIES, WAITLISTS AND VOUCHERS
Open lotteries and waitlists from New York State's HousingSearch portal — income limits, deadlines and a direct link to apply — plus buildings that take Section 8 and other vouchers.

SAVE AND SYNC
Heart a building and it's in My Activity; sign in with Apple or Google and your saves follow you to findacrib.com.

Find A Crib is an independent, informational tool. It is not a broker, does not list apartments, and takes no fee. Data: NYS Homes and Community Renewal rent-stabilization register (2024), NYC HPD open data, HUD FY2026 Fair Market Rents, HousingSearch.ny.gov, and advertised rents from Zumper.
"""

REVIEW_NOTES = """WHAT THE APP DOES
Find A Crib is an informational map of New York City's ~47,000 rent-stabilized buildings (public NYS/NYC records) with advertised rents, HPD violation records, and affordable-housing lotteries. It is not a marketplace and does not take applications or payments.

SIGN-IN
No account is needed to use the app. Sign in with Apple or Google is optional; it syncs saved buildings with our website and reveals the building's registered managing agent (public HPD registration data). There is no email/password login and no demo account is required — use any Apple ID or Google account. Account deletion is under Profile → Delete account.

LOCATION
The app never requests location permission. The map is Apple Maps; the "Search this area" button uses the visible map region, not the device location.

DATA REFRESH
On launch the app refreshes five public JSON files from findacrib.com; without a network it falls back to the copy bundled in the app, so every screen works offline in review.

CONTACT
Any question at all: the email and phone above.
"""

AGE_RATING = {
    "alcoholTobaccoOrDrugUseOrReferences": "NONE", "contests": "NONE", "gamblingSimulated": "NONE",
    "gunsOrOtherWeapons": "NONE", "horrorOrFearThemes": "NONE", "matureOrSuggestiveThemes": "NONE",
    "medicalOrTreatmentInformation": "NONE", "profanityOrCrudeHumor": "NONE",
    "sexualContentGraphicAndNudity": "NONE", "sexualContentOrNudity": "NONE",
    "violenceCartoonOrFantasy": "NONE", "violenceRealistic": "NONE",
    "violenceRealisticProlongedGraphicOrSadistic": "NONE",
    "advertising": False, "ageAssurance": False, "gambling": False, "healthOrWellnessTopics": False,
    "lootBox": False, "messagingAndChat": False, "parentalControls": False,
    "unrestrictedWebAccess": False, "userGeneratedContent": False,
    "ageRatingOverride": "NONE",
}
EDITABLE = ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED")


def load_config() -> dict:
    p = HERE / "asc-config.env"
    if not p.exists():
        raise SystemExit("missing scripts/asc-config.env")
    cfg = {}
    for line in p.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            k, _, v = s.partition("=")
            cfg[k.strip()] = os.path.expandvars(v.strip().strip('"').strip("'"))
    return cfg


class ASC:
    def __init__(self, cfg):
        key = pathlib.Path(cfg["ASC_KEY_PATH"]).expanduser().read_text()
        now = int(time.time())
        tok = jwt.encode({"iss": cfg["ASC_ISSUER_ID"], "iat": now, "exp": now + 15 * 60, "aud": "appstoreconnect-v1"},
                         key, algorithm="ES256", headers={"kid": cfg["ASC_KEY_ID"], "typ": "JWT"})
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})

    def _ok(self, r, ok=(200, 201, 204)):
        if r.status_code not in ok:
            raise SystemExit(f"{r.request.method} {r.url} -> {r.status_code}\n{r.text[:800]}")
        return r.json() if r.text else {}

    def get(self, path, **params):
        return self._ok(self.s.get(API + path, params=params, timeout=30), ok=(200, 404)) if path.endswith("appStoreReviewDetail") or path.endswith("/build") \
            else self._ok(self.s.get(API + path, params=params, timeout=30))

    def patch(self, path, body): return self._ok(self.s.patch(API + path, json=body, timeout=30))
    def post(self, path, body): return self._ok(self.s.post(API + path, json=body, timeout=30))
    def delete(self, path): return self._ok(self.s.delete(API + path, timeout=30))


def resolve(asc, app_id):
    info = asc.get(f"/apps/{app_id}/appInfos")["data"][0]
    versions = asc.get(f"/apps/{app_id}/appStoreVersions", limit=10)["data"]
    editable = [v for v in versions if v["attributes"]["appStoreState"] in EDITABLE]
    if not editable:
        raise SystemExit("no editable App Store version")
    v = editable[0]
    return {"info": info["id"],
            "info_loc": asc.get(f"/appInfos/{info['id']}/appInfoLocalizations")["data"][0]["id"],
            "version": v["id"], "version_string": v["attributes"]["versionString"],
            "version_loc": asc.get(f"/appStoreVersions/{v['id']}/appStoreVersionLocalizations")["data"][0]["id"]}


def upload_screenshots(asc, version_loc):
    """6.9" set (APP_IPHONE_67 accepts 1320x2868). Replaces whatever is there
    so the set always mirrors marketing/asc-screenshots/ in filename order."""
    files = sorted(p for p in SHOTS.glob("*.png"))
    if not files:
        print("    no screenshots in", SHOTS); return
    sets = asc.get(f"/appStoreVersionLocalizations/{version_loc}/appScreenshotSets")["data"]
    st = next((s for s in sets if s["attributes"]["screenshotDisplayType"] == "APP_IPHONE_67"), None)
    if not st:
        st = asc.post("/appScreenshotSets", {"data": {"type": "appScreenshotSets",
              "attributes": {"screenshotDisplayType": "APP_IPHONE_67"},
              "relationships": {"appStoreVersionLocalization": {"data": {"type": "appStoreVersionLocalizations", "id": version_loc}}}}})["data"]
    existing = asc.get(f"/appScreenshotSets/{st['id']}/appScreenshots")["data"]
    have = {e["attributes"].get("fileName"): e for e in existing}
    if [e["attributes"].get("fileName") for e in existing] == [f.name for f in files] and all(
            (have[f.name]["attributes"].get("sourceFileChecksum") or "") == hashlib.md5(f.read_bytes()).hexdigest() for f in files):
        print(f"    screenshots already current ({len(files)})"); return
    for e in existing:
        asc.delete(f"/appScreenshots/{e['id']}")
    for f in files:
        data = f.read_bytes()
        res = asc.post("/appScreenshots", {"data": {"type": "appScreenshots",
               "attributes": {"fileName": f.name, "fileSize": len(data)},
               "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": st["id"]}}}}})["data"]
        for op in res["attributes"]["uploadOperations"]:
            chunk = data[op["offset"]: op["offset"] + op["length"]]
            hdrs = {h["name"]: h["value"] for h in op["requestHeaders"]}
            r = requests.request(op["method"], op["url"], headers=hdrs, data=chunk, timeout=120)
            if r.status_code >= 400:
                raise SystemExit(f"upload chunk failed {r.status_code}: {r.text[:200]}")
        asc.patch(f"/appScreenshots/{res['id']}", {"data": {"type": "appScreenshots", "id": res["id"],
                  "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})
        print("    uploaded", f.name)


def apply(asc, cfg):
    app_id = cfg["ASC_APP_ID"]; ids = resolve(asc, app_id)
    print(f"==> version {ids['version_string']}")
    asc.patch(f"/apps/{app_id}", {"data": {"type": "apps", "id": app_id,
              "attributes": {"contentRightsDeclaration": "DOES_NOT_USE_THIRD_PARTY_CONTENT"}}})
    print("    content rights")
    asc.patch(f"/appInfos/{ids['info']}", {"data": {"type": "appInfos", "id": ids["info"], "relationships": {
        "primaryCategory": {"data": {"type": "appCategories", "id": PRIMARY_CATEGORY}},
        "secondaryCategory": {"data": {"type": "appCategories", "id": SECONDARY_CATEGORY}}}}})
    print(f"    categories {PRIMARY_CATEGORY} / {SECONDARY_CATEGORY}")
    asc.patch(f"/appInfoLocalizations/{ids['info_loc']}", {"data": {"type": "appInfoLocalizations", "id": ids["info_loc"],
              "attributes": {"subtitle": SUBTITLE, "privacyPolicyUrl": PRIVACY}}})
    print("    subtitle + privacy policy URL")
    asc.patch(f"/appStoreVersionLocalizations/{ids['version_loc']}", {"data": {"type": "appStoreVersionLocalizations", "id": ids["version_loc"],
              "attributes": {"description": DESCRIPTION, "keywords": KEYWORDS, "promotionalText": PROMO,
                             "supportUrl": SUPPORT, "marketingUrl": SITE}}})
    print("    description, keywords, promo, URLs")
    asc.patch(f"/appStoreVersions/{ids['version']}", {"data": {"type": "appStoreVersions", "id": ids["version"],
              "attributes": {"copyright": COPYRIGHT, "usesIdfa": False}}})
    print("    copyright, no IDFA")
    asc.patch(f"/ageRatingDeclarations/{ids['info']}", {"data": {"type": "ageRatingDeclarations", "id": ids["info"], "attributes": AGE_RATING}})
    print("    age rating (4+)")
    detail = asc.get(f"/appStoreVersions/{ids['version']}/appStoreReviewDetail").get("data")
    attrs = {"contactFirstName": cfg["ASC_CONTACT_FIRST_NAME"], "contactLastName": cfg["ASC_CONTACT_LAST_NAME"],
             "contactPhone": cfg["ASC_CONTACT_PHONE"], "contactEmail": cfg["ASC_CONTACT_EMAIL"],
             "demoAccountRequired": False, "notes": REVIEW_NOTES}
    if detail:
        asc.patch(f"/appStoreReviewDetails/{detail['id']}", {"data": {"type": "appStoreReviewDetails", "id": detail["id"], "attributes": attrs}})
    else:
        asc.post("/appStoreReviewDetails", {"data": {"type": "appStoreReviewDetails", "attributes": attrs,
                 "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": ids["version"]}}}}})
    print("    review contact + notes")
    r = asc.s.get(f"{API}/apps/{app_id}/appPriceSchedule", timeout=30)
    if r.status_code == 200 and r.json().get("data"):
        print("    price schedule already set")
    else:
        points = asc.get(f"/apps/{app_id}/appPricePoints", **{"filter[territory]": "USA", "limit": 200})["data"]
        free = next(p for p in points if float(p["attributes"]["customerPrice"]) == 0.0)
        asc.post("/appPriceSchedules", {"data": {"type": "appPriceSchedules", "relationships": {
            "app": {"data": {"type": "apps", "id": app_id}},
            "baseTerritory": {"data": {"type": "territories", "id": "USA"}},
            "manualPrices": {"data": [{"type": "appPrices", "id": "${free}"}]}}},
            "included": [{"type": "appPrices", "id": "${free}", "attributes": {"startDate": None},
                          "relationships": {"appPricePoint": {"data": {"type": "appPricePoints", "id": free["id"]}}}}]})
        print("    price: free (USA base)")
    upload_screenshots(asc, ids["version_loc"])


def show(asc, cfg):
    ids = resolve(asc, cfg["ASC_APP_ID"])
    loc = asc.get(f"/appStoreVersionLocalizations/{ids['version_loc']}")["data"]["attributes"]
    il = asc.get(f"/appInfoLocalizations/{ids['info_loc']}")["data"]["attributes"]
    v = asc.get(f"/appStoreVersions/{ids['version']}")["data"]["attributes"]
    det = asc.get(f"/appStoreVersions/{ids['version']}/appStoreReviewDetail").get("data")
    b = asc.get(f"/appStoreVersions/{ids['version']}/build").get("data")
    sets = asc.get(f"/appStoreVersionLocalizations/{ids['version_loc']}/appScreenshotSets")["data"]
    n = sum(len(asc.get(f"/appScreenshotSets/{s['id']}/appScreenshots")["data"]) for s in sets)
    print(f"version {v['versionString']} {v['appStoreState']}\n  subtitle    {il.get('subtitle')}\n  privacy     {il.get('privacyPolicyUrl')}"
          f"\n  description {len(loc.get('description') or '')} chars\n  keywords    {loc.get('keywords')}\n  support     {loc.get('supportUrl')}"
          f"\n  copyright   {v.get('copyright')}\n  build       {b['attributes']['version'] if b else '(none)'}\n  review info {'set' if det else 'MISSING'}"
          f"\n  screenshots {n} in {len(sets)} set(s)")


if __name__ == "__main__":
    cfg = load_config(); asc = ASC(cfg)
    (show if "--show" in sys.argv else apply)(asc, cfg)
