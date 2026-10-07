#!/usr/bin/env python3
"""App Store Server Notifications V2 for Find A Crib (2026-10-07, audit L13).

    python3 ios/scripts/asc_server_notifications.py show
    python3 ios/scripts/asc_server_notifications.py set      # Production + Sandbox URL, V2
    python3 ios/scripts/asc_server_notifications.py test     # ask Apple for a TEST notification

`set` changes the app's notification URLs, not a version, build or review
submission, so ios/ASC_FREEZE does not apply (no App Store release happens).
`test` uses the App Store Server API (POST /inApps/v1/notifications/test,
Sandbox), then polls its delivery status: Apple reports whether OUR endpoint
answered 200.
"""
from __future__ import annotations

import sys
import time
import pathlib

import jwt
import requests

import asc_metadata as m

URL = "https://dbaifotzwlxjvsxjohjt.supabase.co/functions/v1/apple-notifications"
BUNDLE_ID = "com.divinedavis.findacrib"
FIELDS = ("subscriptionStatusUrl", "subscriptionStatusUrlVersion",
          "subscriptionStatusUrlForSandbox", "subscriptionStatusUrlVersionForSandbox")


def show(asc, app_id):
    a = asc.get(f"/apps/{app_id}")["data"]["attributes"]
    for k in FIELDS:
        print(f"  {k:42s} {a.get(k)}")
    return a


def set_urls(asc, app_id):
    asc.patch(f"/apps/{app_id}", {"data": {"type": "apps", "id": app_id, "attributes": {
        "subscriptionStatusUrl": URL, "subscriptionStatusUrlVersion": "V2",
        "subscriptionStatusUrlForSandbox": URL, "subscriptionStatusUrlVersionForSandbox": "V2"}}})
    a = show(asc, app_id)
    assert a.get("subscriptionStatusUrl") == URL and a.get("subscriptionStatusUrlForSandbox") == URL


def server_api_token(cfg):
    key = pathlib.Path(cfg["ASC_KEY_PATH"]).expanduser().read_text()
    now = int(time.time())
    return jwt.encode({"iss": cfg["ASC_ISSUER_ID"], "iat": now, "exp": now + 15 * 60,
                       "aud": "appstoreconnect-v1", "bid": BUNDLE_ID},
                      key, algorithm="ES256", headers={"kid": cfg["ASC_KEY_ID"], "typ": "JWT"})


def test(cfg):
    base = "https://api.storekit-sandbox.itunes.apple.com/inApps/v1/notifications/test"
    # A URL just set in App Store Connect takes a while to reach the Server
    # API, which answers 4040007 ("No ... URL found") until it does.
    for attempt in range(40):
        h = {"Authorization": f"Bearer {server_api_token(cfg)}"}
        r = requests.post(base, headers=h, timeout=30)
        if not (r.status_code == 404 and "4040007" in r.text):
            break
        print(f"  URL not visible to the Server API yet ({attempt + 1}/40), waiting 60s", flush=True)
        time.sleep(60)
    print("  request:", r.status_code, r.text[:200])
    r.raise_for_status()
    token = r.json()["testNotificationToken"]
    for _ in range(12):
        time.sleep(5)
        s = requests.get(f"{base}/{token}", headers=h, timeout=30)
        if s.status_code == 200:
            body = s.json()
            sends = body.get("sendAttempts") or []
            print("  delivery:", [(a.get("attemptDate"), a.get("sendAttemptResult")) for a in sends])
            if any(a.get("sendAttemptResult") == "SUCCESS" for a in sends):
                return 0
        else:
            print("  status:", s.status_code, s.text[:120])
    return 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    cfg = m.load_config()
    asc = m.ASC(cfg)
    app_id = cfg["ASC_APP_ID"]
    if cmd == "show":
        show(asc, app_id)
    elif cmd == "set":
        set_urls(asc, app_id)
    elif cmd == "test":
        sys.exit(test(cfg))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
