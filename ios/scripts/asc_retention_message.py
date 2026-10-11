#!/usr/bin/env python3
"""Find A Crib Plus retention message (Apple Retention Messaging API).

The App Store shows this default message when a Plus subscriber starts to
cancel. It needs an In-App Purchase key (App Store Connect > Users and
Access > Integrations > In-App Purchase), which only the website can mint;
the team ASC API key is not accepted by this API.

    ~/.venvs/dhcr-map/bin/python scripts/asc_retention_message.py upload  --key SubscriptionKey_XXXX.p8 --key-id XXXX [--sandbox]
    ~/.venvs/dhcr-map/bin/python scripts/asc_retention_message.py status  --key ... --key-id ... [--sandbox]
    ~/.venvs/dhcr-map/bin/python scripts/asc_retention_message.py default --key ... --key-id ... [--sandbox]

`upload` sends the message (Apple reviews it: PENDING -> APPROVED; sandbox
approves at once). `default` makes it the default for Plus Monthly in en-US
and only works once the message is APPROVED.
"""
import argparse
import sys
import time
import uuid
from pathlib import Path

import jwt
import requests

from asc_creative_assets import _cfg

BUNDLE = "com.divinedavis.findacrib"
PRODUCT = "com.divinedavis.findacrib.plus.monthly"
# fixed so `upload` never makes duplicates (Apple rejects a reused id)
MESSAGE_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "findacrib/retention/plus-monthly/en-US/v1"))
# Wording mirrors the app's own Plus copy (PlusView perks, AlertsSheet).
HEADER = "Keep hearing about re-rentals the minute they open"          # <= 66
BODY = ("Re-rentals go first come, first served. Without Plus, alerts arrive once a day "
        "at 8 AM instead of the minute an apartment opens.")            # <= 144


def headers(key, key_id):
    now = int(time.time())
    tok = jwt.encode({"iss": _cfg()["ASC_ISSUER_ID"], "iat": now, "exp": now + 15 * 60,
                      "aud": "appstoreconnect-v1", "bid": BUNDLE},
                     Path(key).expanduser().read_text(), algorithm="ES256",
                     headers={"kid": key_id, "typ": "JWT"})
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["upload", "status", "default"])
    ap.add_argument("--key", required=True)
    ap.add_argument("--key-id", required=True)
    ap.add_argument("--sandbox", action="store_true")
    a = ap.parse_args()
    assert len(HEADER) <= 66 and len(BODY) <= 144
    base = ("https://api.storekit-sandbox.itunes.apple.com" if a.sandbox
            else "https://api.storekit.itunes.apple.com") + "/inApps/v1/messaging"
    h = headers(a.key, a.key_id)
    if a.cmd == "upload":
        r = requests.put(f"{base}/message/{MESSAGE_ID}", headers=h, json={"header": HEADER, "body": BODY}, timeout=60)
    elif a.cmd == "status":
        r = requests.get(f"{base}/message/list", headers=h, timeout=60)
    else:
        r = requests.put(f"{base}/default/{PRODUCT}/en-US", headers=h, json={"messageIdentifier": MESSAGE_ID}, timeout=60)
    print(r.status_code, r.text[:1500])
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
