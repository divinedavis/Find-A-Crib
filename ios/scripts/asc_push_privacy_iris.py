#!/usr/bin/env python3
"""Publish Find A Crib's App Privacy labels.

The public App Store Connect API has no App Privacy resource (every
appDataUsages path 404s under an API key), so this drives the private iris
API the dashboard itself uses, with the cookie jar fastlane's Spaceship
writes after `fastlane spaceauth -u divinejdavis@gmail.com` — 2FA, so a
person runs that, and the cookie lasts only days. Run this within minutes
of it.

What the app collects, and why (2026-09-16):

  linked to the account, App Functionality
    NAME, EMAIL_ADDRESS   Sign in with Apple / Google / email
    USER_ID               the Supabase account id
    PURCHASE_HISTORY      the Find A Crib Plus subscription
  linked to the account when signed in, Analytics
    PRODUCT_INTERACTION   what was done in the app — searches by shape,
                          screens, taps on tiles and hand-off buttons
                          (Services/Analytics.swift writes public.events)
    OTHER_USAGE_DATA      launch source, session id, install age

Nothing is used for tracking (no ad network, no data broker, no
cross-app identifier), and the analytics has an in-app off switch
(Profile → Share anonymous usage).

Existing records are deleted first, then one record per (category,
purpose), then the publish PATCH. The publish state can only be UPDATEd,
never read, so a 200 there is the proof.

    ~/.venvs/spendcap/bin/python scripts/asc_push_privacy_iris.py [--probe-only]

--probe-only prints the current records plus the valid category / purpose /
protection ids, which is how the constants below get checked before a real
run. After a successful publish, flip `Analytics.privacyLabelDeclared` to
true in the same commit and ship.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from attach_build import load_config  # noqa: E402

IRIS = "https://appstoreconnect.apple.com/iris/v1"
COOKIE_FILE = pathlib.Path.home() / ".fastlane" / "spaceship" / "divinejdavis@gmail.com" / "cookie"

PROTECTION = "DATA_LINKED_TO_YOU"
# (leaf data type, purpose) — see the docstring.
USAGES = [
    ("NAME", "APP_FUNCTIONALITY"),
    ("EMAIL_ADDRESS", "APP_FUNCTIONALITY"),
    ("USER_ID", "APP_FUNCTIONALITY"),
    ("PURCHASE_HISTORY", "APP_FUNCTIONALITY"),
    ("PRODUCT_INTERACTION", "ANALYTICS"),
    ("OTHER_USAGE_DATA", "ANALYTICS"),
]


def cookies() -> list[dict]:
    """Spaceship's jar is Ruby YAML (!ruby/object:HTTP::Cookie); line-scan it."""
    if not COOKIE_FILE.exists():
        raise SystemExit(f"no cookie at {COOKIE_FILE} — run: fastlane spaceauth -u divinejdavis@gmail.com")
    out: list[dict] = []
    cur: dict | None = None
    for line in COOKIE_FILE.read_text().splitlines():
        if line.lstrip().startswith("- !ruby/object:"):
            if cur and cur.get("name") and cur.get("value"):
                out.append(cur)
            cur = {}
            continue
        if cur is None or ":" not in line:
            continue
        k, _, v = line.strip().partition(":")
        if k.strip() in ("name", "value", "domain") and v.strip():
            cur[k.strip()] = v.strip().strip('"').strip("'")
    if cur and cur.get("name") and cur.get("value"):
        out.append(cur)
    if not out:
        raise SystemExit("parsed 0 cookies from the Spaceship jar")
    return out


def session() -> requests.Session:
    s = requests.Session()
    for c in cookies():
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", "appstoreconnect.apple.com"))
    s.headers.update({
        "Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"),
        "Origin": "https://appstoreconnect.apple.com", "Referer": "https://appstoreconnect.apple.com/",
    })
    return s


def show(label: str, r: requests.Response) -> None:
    print(f"── {label}  HTTP {r.status_code}")
    try:
        print(json.dumps(r.json(), indent=1)[:1500])
    except Exception:
        print(r.text[:600])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-only", action="store_true")
    args = ap.parse_args()
    app_id = load_config()["ASC_APP_ID"]
    s = session()

    # The appDataUsages collection refuses GET (403 "does not allow
    # GET_COLLECTION"); the app's relationship path lists them.
    r = s.get(f"{IRIS}/apps/{app_id}/dataUsages", params={"limit": 50}, timeout=30)
    if r.status_code == 401:
        raise SystemExit("iris says 401: the Spaceship cookie has expired — "
                         "run `fastlane spaceauth -u divinejdavis@gmail.com` and retry")
    show("existing appDataUsages", r)
    existing = r.json().get("data", []) if r.ok else []
    if args.probe_only:
        show("categories", s.get(f"{IRIS}/appDataUsageCategories", params={"limit": 200}, timeout=30))
        show("purposes", s.get(f"{IRIS}/appDataUsagePurposes", timeout=30))
        show("dataProtections", s.get(f"{IRIS}/appDataUsageDataProtections", timeout=30))
        return 0

    for e in existing:
        d = s.delete(f"{IRIS}/appDataUsages/{e['id']}", timeout=30)
        if d.status_code >= 400:
            show(f"DELETE {e['id']} failed", d)
            return 1
    print(f"removed {len(existing)} old record(s)")

    for category, purpose in USAGES:
        body = {"data": {"type": "appDataUsages", "relationships": {
            "app": {"data": {"type": "apps", "id": app_id}},
            "category": {"data": {"type": "appDataUsageCategories", "id": category}},
            "purpose": {"data": {"type": "appDataUsagePurposes", "id": purpose}},
            "dataProtection": {"data": {"type": "appDataUsageDataProtections", "id": PROTECTION}}}}}
        r = s.post(f"{IRIS}/appDataUsages", data=json.dumps(body), timeout=30)
        if r.status_code >= 400:
            show(f"POST {category}/{purpose} failed (try --probe-only for the valid ids)", r)
            return 1
        print(f"   ✓ {category} / {PROTECTION} / {purpose}")

    r = s.patch(f"{IRIS}/appDataUsagesPublishState/{app_id}", data=json.dumps({"data": {
        "type": "appDataUsagesPublishState", "id": app_id, "attributes": {"published": True}}}), timeout=30)
    if r.status_code >= 400:
        show("publish failed", r)
        return 1
    print("App Privacy published: " + ", ".join(c for c, _ in USAGES) + " (linked, no tracking)")
    print("Now set Analytics.privacyLabelDeclared = true and ship.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
