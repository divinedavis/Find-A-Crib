#!/usr/bin/env python3
"""Write the App Store listing for Find A Crib through the API.

Everything App Store Connect accepts over its API lives here, so the listing
is a file in the repo rather than a memory of which boxes were ticked:
categories, subtitle, description, keywords, promo text, URLs, copyright, the
age-rating questionnaire, the review contact + notes, the free price, territory
availability (every territory, and new ones as Apple adds them), and the 6.9"
screenshots from marketing/asc-screenshots/, and the What's New text on any
version after 1.0 (Apple rejects a whatsNew on the first version). Idempotent.

An app created over the API has NO availability record, so even a version in
READY_FOR_SALE shows "removed from sale" and never reaches the store until one
is created (that is what happened to 1.0 on 2026-09-09).

    python3 scripts/asc_metadata.py            # apply everything
    python3 scripts/asc_metadata.py --show     # print what is there now

Browser-only (no API): the App Privacy questionnaire and Submit for Review.
"""
from __future__ import annotations
import hashlib, os, pathlib, sys, time
import jwt, requests

HERE = pathlib.Path(__file__).resolve().parent
HOST = "https://api.appstoreconnect.apple.com"
API = HOST + "/v1"
SHOTS = HERE.parent / "marketing" / "asc-screenshots"

SUBTITLE = "NYC, LA, SF & DC rent maps"                       # <= 30 chars
KEYWORDS = "rent stabilized,rent control,los angeles,san francisco,washington dc,apartments,rso,brooklyn,nyc"  # <=100 — cities carry the search demand; the title already says Find A Crib
PROMO = ("Rent-stabilized and rent-controlled buildings on one map — New York, Los Angeles, "
         "San Francisco and Washington DC, from each city's own public register.")
SITE = "https://findacrib.com/"
SUPPORT = "https://findacrib.com/support/"
PRIVACY = "https://findacrib.com/privacy/"
COPYRIGHT = "2026 Divine Davis"
PRIMARY_CATEGORY = "LIFESTYLE"
SECONDARY_CATEGORY = "REFERENCE"

DESCRIPTION = """Find A Crib maps the buildings where the rent is legally limited — in New York City, Los Angeles, San Francisco and Washington DC — using each city's own public register, and tells you what you can't see from the sidewalk.

FOUR CITIES, FOUR REGISTERS
Pick a city, then narrow it the way that city is actually divided: by borough in New York, by neighborhood in San Francisco and Washington DC, by area in Los Angeles.

- New York City: all 47,000 rent-stabilized buildings on the NYS HCR register
- Los Angeles: parcels meeting the city's RSO criteria (2+ units, built on or before Oct 1, 1978)
- San Francisco: rent-controlled units reported to the SF Rent Board, at block level
- Washington DC: units registered with DHCD under the Rental Housing Act

Each city says plainly where its data comes from and what it does not prove.

IN NEW YORK, THERE IS MORE
The New York map adds what only that city publishes: what's for rent this week, the building's HPD record, who runs it, and the lotteries you can apply for today.

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

FIND A CRIB PLUS
Plus unlocks the registered managing agent's phone number on every building page and the landlord directory. Find A Crib Plus Monthly is an auto-renewable subscription at $4.99 per month, charged to your Apple Account and renewed automatically unless cancelled at least 24 hours before the end of the period. Manage or cancel in Settings › Apple Account › Subscriptions.
Terms of Use (EULA): https://www.apple.com/legal/internet-services/itunes/dev/stdeula/
Privacy Policy: https://findacrib.com/privacy/

Find A Crib is an independent, informational tool. It is not a broker, does not list apartments, and takes no fee. Data: NYS Homes and Community Renewal rent-stabilization register (2024), NYC HPD open data, HUD FY2026 Fair Market Rents, HousingSearch.ny.gov, advertised rents from Zumper, LA County Assessor parcel data under LAHD's RSO criteria, the SF Rent Board Housing Inventory via DataSF, and the DC DHCD RentRegistry.
"""

WHATS_NEW = """Alerts on your phone. Turn on alerts and the minute a housing lottery or re-rental opens in your borough, it arrives as a notification on your iPhone, alongside the email. Tap it to go straight to the listing.

Re-rentals in your results. Income-restricted apartments that HPD-approved marketing agents are re-renting right now appear in the list, marked Rerental, with a button to apply on the agent's site. They go fast and are not on the big listing sites.

The map follows you. Pan or zoom and the count shows how many buildings are in view; tap List to see just those.

A skyline for every city. Pull down on your results for New York, San Francisco, Washington DC and Los Angeles landmarks under a night sky.

Faster launch, smoother map, quicker filters, and the header now names the city you are searching in.
"""

REVIEW_NOTES = """VERSION 1.2.1 (build __BUILD__) — push alerts, re-rentals in results, map follows the viewport

WHAT CHANGED SINCE 1.2.0
1. Push notifications for borough alerts. A signed-in user who turns on alerts (Profile > Alerts, or the Alerts button on the results list) gets a notification the moment a new housing lottery, re-rental or voucher listing matching their boroughs opens. The same alert is emailed; push is an additional channel. Notifications are never required to use the app.
2. Re-rental tiles in the results list. Income-restricted apartments that HPD-approved marketing agents publish on their own websites appear in the list, labelled "Rerental" (first as the 3rd card, then every 8 to 15 cards). The button opens the agent's own page in Safari. We take no fee and do not handle applications.
3. The map's count follows the visible region and "List" opens on the buildings in view.
4. A decorative city skyline at the top of the results list.

NOTIFICATIONS — HOW THE PERMISSION IS ASKED
Once, a few seconds after launch, while the notification permission is still undetermined, the app shows its own card ("Get alerts on this phone?") explaining what notifications are used for. "Turn on" shows the iOS permission dialog; "Not now" dismisses it for a week. If the user declines the iOS dialog the app never asks again; it points to Settings instead. Notifications are only ever borough alerts the user subscribed to: no marketing, no promotional pushes.
To see a push in review: sign in (Sign in with Apple is fine), open Profile > Alerts, pick a borough, tap "Turn on alerts", allow notifications. Alerts arrive when a matching listing opens; the feeds are checked every 10 minutes.

APP STORE RATING
The app calls StoreKit's requestReview after a building is saved or alerts are turned on, at most once per app version and never within 120 days of the previous request. Profile also has a "Rate Find A Crib" link to the App Store review page.

USAGE ANALYTICS
The app records what is done in it (screens opened, searches by their filters, taps on listing links), linked to the account when signed in, declared under Product Interaction / Other Usage Data (Analytics) in App Privacy. No advertising identifier, no tracking, no third-party SDK. Profile > "Share anonymous usage" turns it off.

WHERE THE DATA COMES FROM
Every city is a public register, fetched as static JSON from findacrib.com, no key and no account: New York — NYS Homes and Community Renewal rent-stabilization register; Los Angeles — LA County Assessor parcels meeting the RSO criteria; San Francisco — SF Rent Board housing inventory, anonymised to the block; Washington DC — DHCD rental registrations. Re-rentals come from the marketing agents' public listing pages.

SIGN-IN
No account is needed to use the app. Signing in is optional; it syncs saved buildings with our website, enables alerts, and reveals the building's registered managing agent (public HPD registration data). Sign in with Apple, Google or email.

LOCATION
The app never requests location permission. The map is Apple Maps; the in-view count and List use the visible map region, not the device location.

DATA REFRESH
On launch the app refreshes public JSON files from findacrib.com; without a network it falls back to the copy bundled in the app, so New York works offline in review. The three other cities download on first selection.

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

    # Apple's API stalls on some endpoints — the build relationship PATCH timed
    # out three times running on 2026-09-09 at 30s while the same call succeeded
    # moments later. Give it room and retry the idle ones rather than leaving a
    # version half-swapped.
    TIMEOUT = 90
    RETRIES = 3

    def _send(self, method, path, **kw):
        import time as _t
        last = None
        for attempt in range(self.RETRIES):
            try:
                return self.s.request(method, path, timeout=self.TIMEOUT, **kw)
            except requests.exceptions.RequestException as e:
                last = e
                if attempt + 1 < self.RETRIES:
                    print(f"    {method} timed out, retrying ({attempt + 2}/{self.RETRIES})")
                    _t.sleep(5 * (attempt + 1))
        raise last

    def _ok(self, r, ok=(200, 201, 204)):
        if r.status_code not in ok:
            raise SystemExit(f"{r.request.method} {r.url} -> {r.status_code}\n{r.text[:800]}")
        return r.json() if r.text else {}

    def get(self, path, **params):
        soft = path.endswith("appStoreReviewDetail") or path.endswith("/build")
        return self._ok(self._send("GET", API + path, params=params), ok=(200, 404)) if soft \
            else self._ok(self._send("GET", API + path, params=params))

    def patch(self, path, body): return self._ok(self._send("PATCH", API + path, json=body))
    def post(self, path, body): return self._ok(self._send("POST", API + path, json=body))
    def delete(self, path): return self._ok(self._send("DELETE", API + path))


def resolve(asc, app_id, any_version=False):
    # An app with a live version has TWO appInfos: the live one (READY_FOR_SALE,
    # rejects every PATCH with 409 INVALID_STATE) and the editable one for the
    # version being prepared. Take the editable one, fall back to the first.
    infos = asc.get(f"/apps/{app_id}/appInfos")["data"]
    info = next((i for i in infos if i["attributes"].get("state") in EDITABLE + ("WAITING_FOR_REVIEW", "IN_REVIEW")), None) or infos[0]
    versions = asc.get(f"/apps/{app_id}/appStoreVersions", limit=10)["data"]
    editable = [v for v in versions if v["attributes"]["appStoreState"] in EDITABLE]
    if not editable and any_version:
        editable = versions  # --show: report the live version too
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


def ensure_availability(asc, app_id):
    """Create the availability record if the app has none. Without it Apple shows
    the approved version as "removed from sale". Lives at /v2, not /v1."""
    r = asc.s.get(f"{HOST}/v1/apps/{app_id}/appAvailabilityV2", timeout=30)
    if r.status_code == 200 and r.json().get("data"):
        print("    availability already set")
        return
    url, params, terr = f"{API}/territories", {"limit": 200}, []
    while url:
        j = asc._ok(asc.s.get(url, params=params, timeout=30)); params = None
        terr += [t["id"] for t in j["data"]]; url = j.get("links", {}).get("next")
    asc._ok(asc.s.post(f"{HOST}/v2/appAvailabilities", timeout=60, json={
        "data": {"type": "appAvailabilities", "attributes": {"availableInNewTerritories": True},
                 "relationships": {"app": {"data": {"type": "apps", "id": app_id}},
                                   "territoryAvailabilities": {"data": [{"type": "territoryAvailabilities", "id": f"${{{t}}}"} for t in terr]}}},
        "included": [{"type": "territoryAvailabilities", "id": f"${{{t}}}", "attributes": {"available": True},
                      "relationships": {"territory": {"data": {"type": "territories", "id": t}}}} for t in terr]}))
    print(f"    availability: {len(terr)} territories + new ones")


def availability_summary(asc, app_id):
    r = asc.s.get(f"{HOST}/v1/apps/{app_id}/appAvailabilityV2", timeout=30)
    if r.status_code != 200 or not r.json().get("data"):
        return "MISSING (shows as removed from sale)"
    url, params, rows = f"{HOST}/v2/appAvailabilities/{r.json()['data']['id']}/territoryAvailabilities", {"limit": 200}, []
    while url:
        j = asc._ok(asc.s.get(url, params=params, timeout=30)); params = None
        rows += j["data"]; url = j.get("links", {}).get("next")
    from collections import Counter
    on = sum(1 for d in rows if d["attributes"].get("available"))
    status = Counter(s for d in rows for s in (d["attributes"].get("contentStatuses") or []))
    return f"{on}/{len(rows)} territories; " + ", ".join(f"{k} {v}" for k, v in status.most_common())


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
                             "supportUrl": SUPPORT, "marketingUrl": SITE,
                             **({} if ids["version_string"] == "1.0" else {"whatsNew": WHATS_NEW})}}})
    print("    description, keywords, promo, URLs" + ("" if ids["version_string"] == "1.0" else ", what's new"))
    asc.patch(f"/appStoreVersions/{ids['version']}", {"data": {"type": "appStoreVersions", "id": ids["version"],
              "attributes": {"copyright": COPYRIGHT, "usesIdfa": False}}})
    print("    copyright, no IDFA")
    asc.patch(f"/ageRatingDeclarations/{ids['info']}", {"data": {"type": "ageRatingDeclarations", "id": ids["info"], "attributes": AGE_RATING}})
    print("    age rating (4+)")
    detail = asc.get(f"/appStoreVersions/{ids['version']}/appStoreReviewDetail").get("data")
    # The notes name the build under review; ask the version which one that is
    # rather than leaving a number in the file to go stale.
    b = asc.get(f"/appStoreVersions/{ids['version']}/build").get("data")
    notes = REVIEW_NOTES.replace("__BUILD__", (b or {}).get("attributes", {}).get("version", "?"))
    attrs = {"contactFirstName": cfg["ASC_CONTACT_FIRST_NAME"], "contactLastName": cfg["ASC_CONTACT_LAST_NAME"],
             "contactPhone": cfg["ASC_CONTACT_PHONE"], "contactEmail": cfg["ASC_CONTACT_EMAIL"],
             "demoAccountRequired": False, "notes": notes}
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
    ensure_availability(asc, app_id)
    upload_screenshots(asc, ids["version_loc"])


def show(asc, cfg):
    ids = resolve(asc, cfg["ASC_APP_ID"], any_version=True)
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
          f"\n  screenshots {n} in {len(sets)} set(s)\n  availability {availability_summary(asc, cfg['ASC_APP_ID'])}")


if __name__ == "__main__":
    cfg = load_config(); asc = ASC(cfg)
    (show if "--show" in sys.argv else apply)(asc, cfg)
