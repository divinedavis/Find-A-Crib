#!/usr/bin/env python3
"""Create (idempotently) the Find A Crib Plus auto-renewable subscription in
App Store Connect: subscription group, the monthly subscription, its English
localization, the group localization, and a $4.99 USD price.

Re-run safely; each step looks up the existing resource before creating.
Reads credentials from scripts/asc-config.env.

Usage:
    python3 scripts/create_subscription.py
"""
from __future__ import annotations

import os
import time
import pathlib

import jwt
import requests

CONFIG_PATH = pathlib.Path(__file__).resolve().parent / "asc-config.env"
API_ROOT = "https://api.appstoreconnect.apple.com"
API_BASE = API_ROOT + "/v1"

# Version states that still accept metadata edits (ASC API 4.4.1, July 2026).
EDITABLE_STATES = {"PREPARE_FOR_SUBMISSION", "REJECTED", "DEVELOPER_REJECTED"}

PRODUCT_ID = "com.divinedavis.findacrib.plus.monthly"
GROUP_REFERENCE = "Find A Crib Plus"
SUB_NAME = "Find A Crib Plus Monthly"          # <= 30 chars
SUB_DISPLAY_NAME = "Find A Crib Plus"           # localization name, <= 30
SUB_DESCRIPTION = "Agent phone numbers, saved searches, listing alerts."
GROUP_DISPLAY_NAME = "Find A Crib Plus"
TARGET_PRICE = "4.99"
TERRITORY = "USA"


def load_config() -> dict:
    cfg: dict = {}
    for line in CONFIG_PATH.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        k, _, v = s.partition("=")
        cfg[k.strip()] = os.path.expandvars(v.strip().strip('"').strip("'"))
    return cfg


def make_token(cfg: dict) -> str:
    private_key = pathlib.Path(cfg["ASC_KEY_PATH"]).expanduser().read_text()
    now = int(time.time())
    payload = {"iss": cfg["ASC_ISSUER_ID"], "iat": now, "exp": now + 15 * 60,
               "aud": "appstoreconnect-v1"}
    return jwt.encode(payload, private_key, algorithm="ES256",
                      headers={"kid": cfg["ASC_KEY_ID"], "typ": "JWT"})


def api(token: str, method: str, path: str, params=None, body=None) -> dict:
    base = API_ROOT if path.startswith(("/v1/", "/v2/")) else API_BASE
    r = requests.request(method, f"{base}{path}",
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"},
                         params=params or {}, json=body, timeout=30)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path} -> {r.status_code}\n{r.text}")
    return r.json() if r.text else {}


def ensure_group(token: str, app_id: str) -> str:
    res = api(token, "GET", f"/apps/{app_id}/subscriptionGroups", params={"limit": 200})
    for g in res.get("data", []):
        if g["attributes"].get("referenceName") == GROUP_REFERENCE:
            print(f"   group exists ({g['id']})")
            return g["id"]
    body = {"data": {"type": "subscriptionGroups",
                     "attributes": {"referenceName": GROUP_REFERENCE},
                     "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
    gid = api(token, "POST", "/subscriptionGroups", body=body)["data"]["id"]
    print(f"   created group ({gid})")
    return gid


def _sorted_versions(token: str, list_path: str) -> list:
    res = api(token, "GET", list_path, params={"limit": 50})
    return sorted(res.get("data", []),
                  key=lambda v: v["attributes"].get("version") or 0, reverse=True)


def _has_locale(token: str, loc_path: str, locale: str) -> bool:
    res = api(token, "GET", loc_path, params={"limit": 200})
    return any(l["attributes"].get("locale") == locale for l in res.get("data", []))


def _editable_or_new_version(token: str, versions: list, version_type: str,
                             parent_key: str, parent_type: str, parent_id: str) -> str:
    draft = next((v for v in versions if v["attributes"].get("state") in EDITABLE_STATES), None)
    if draft:
        return draft["id"]
    body = {"data": {"type": version_type,
                     "relationships": {parent_key:
                                       {"data": {"type": parent_type, "id": parent_id}}}}}
    vid = api(token, "POST", f"/v1/{version_type}", body=body)["data"]["id"]
    print(f"   created draft {version_type[:-1]} ({vid})")
    return vid


def ensure_group_localization(token: str, group_id: str) -> None:
    versions = _sorted_versions(token, f"/v1/subscriptionGroups/{group_id}/versions")
    for v in versions:
        if _has_locale(token, f"/v1/subscriptionGroupVersions/{v['id']}/localizations", "en-US"):
            print("   group localization en-US exists")
            return
    vid = _editable_or_new_version(token, versions, "subscriptionGroupVersions",
                                   "subscriptionGroup", "subscriptionGroups", group_id)
    body = {"data": {"type": "subscriptionGroupLocalizations",
                     "attributes": {"name": GROUP_DISPLAY_NAME, "locale": "en-US"},
                     "relationships": {"version":
                                       {"data": {"type": "subscriptionGroupVersions", "id": vid}}}}}
    api(token, "POST", "/v2/subscriptionGroupLocalizations", body=body)
    print("   created group localization en-US")


def ensure_subscription(token: str, group_id: str) -> str:
    res = api(token, "GET", f"/subscriptionGroups/{group_id}/subscriptions", params={"limit": 200})
    for s in res.get("data", []):
        if s["attributes"].get("productId") == PRODUCT_ID:
            print(f"   subscription exists ({s['id']})")
            return s["id"]
    body = {"data": {"type": "subscriptions",
                     "attributes": {"name": SUB_NAME, "productId": PRODUCT_ID,
                                    "subscriptionPeriod": "ONE_MONTH",
                                    "familySharable": False},
                     "relationships": {"group":
                                       {"data": {"type": "subscriptionGroups", "id": group_id}}}}}
    sid = api(token, "POST", "/subscriptions", body=body)["data"]["id"]
    print(f"   created subscription ({sid})")
    return sid


def ensure_localization(token: str, sub_id: str) -> None:
    versions = _sorted_versions(token, f"/v1/subscriptions/{sub_id}/versions")
    for v in versions:
        if _has_locale(token, f"/v1/subscriptionVersions/{v['id']}/localizations", "en-US"):
            print("   subscription localization en-US exists")
            return
    vid = _editable_or_new_version(token, versions, "subscriptionVersions",
                                   "subscription", "subscriptions", sub_id)
    body = {"data": {"type": "subscriptionLocalizations",
                     "attributes": {"name": SUB_DISPLAY_NAME, "locale": "en-US",
                                    "description": SUB_DESCRIPTION},
                     "relationships": {"version":
                                       {"data": {"type": "subscriptionVersions", "id": vid}}}}}
    api(token, "POST", "/v2/subscriptionLocalizations", body=body)
    print("   created subscription localization en-US")


def ensure_price(token: str, sub_id: str) -> None:
    # Already priced?
    existing = api(token, "GET", f"/subscriptions/{sub_id}/prices", params={"limit": 200})
    if existing.get("data"):
        print("   subscription already has a price")
        return
    # Find the USA price point matching TARGET_PRICE, else the nearest one.
    exact = None
    nearest_id, nearest_gap = None, None
    params = {"filter[territory]": TERRITORY, "limit": 200}
    path = f"/subscriptions/{sub_id}/pricePoints"
    while path and not exact:
        res = api(token, "GET", path, params=params)
        for pp in res.get("data", []):
            cp = pp["attributes"].get("customerPrice")
            if cp == TARGET_PRICE:
                exact = pp["id"]; break
            gap = abs(float(cp) - float(TARGET_PRICE))
            if nearest_gap is None or gap < nearest_gap:
                nearest_id, nearest_gap = pp["id"], gap
        nxt = res.get("links", {}).get("next")
        path, params = (nxt.replace(API_BASE, ""), None) if nxt else (None, None)
    chosen = exact or nearest_id
    if not chosen:
        print("   could not find any USA price point — set the price in App Store Connect")
        return
    label = TARGET_PRICE if exact else "nearest available"
    body = {"data": {"type": "subscriptionPrices",
                     "attributes": {"startDate": None, "preserveCurrentPrice": False},
                     "relationships": {
                         "subscription": {"data": {"type": "subscriptions", "id": sub_id}},
                         "subscriptionPricePoint": {"data": {"type": "subscriptionPricePoints", "id": chosen}}}}}
    r = requests.post(f"{API_BASE}/subscriptionPrices",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      json=body, timeout=30)
    if r.status_code < 400:
        print(f"   set price ({label}) USD (price point {chosen})")
    else:
        # Apple frequently rejects the first price on a freshly-created
        # subscription (RELATIONSHIP.INVALID) until it finishes propagating.
        # Non-fatal: everything else is created; re-run later, or set the
        # $3.99 price once in App Store Connect.
        print(f"   ⚠️  could not set price via API ({r.status_code}). Set ${TARGET_PRICE} in")
        print("      App Store Connect → Subscriptions → WorkComp+ Plus → Price, or re-run later.")


def main() -> None:
    cfg = load_config()
    app_id = cfg["ASC_APP_ID"]
    token = make_token(cfg)
    print("==> WorkComp+ Plus subscription")
    group_id = ensure_group(token, app_id)
    ensure_group_localization(token, group_id)
    sub_id = ensure_subscription(token, group_id)
    ensure_localization(token, sub_id)
    ensure_price(token, sub_id)
    print(f"==> done. Product {PRODUCT_ID} is ready in App Store Connect.")
    print("    Note: it needs a review screenshot + must be submitted with an app")
    print("    version before it goes live; sandbox/TestFlight testing works now.")


if __name__ == "__main__":
    main()
