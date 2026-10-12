#!/usr/bin/env python3
"""Daily App Store subscription check: Apple's records vs public.subscriptions.

Why (owner, 2026-10-12): every App Store Plus purchase went unrecorded for a
month — the app's receipt sync failed on the edge runtime and Apple's own
notifications sat "unmatched" because old builds sent no appAccountToken. This
asks Apple directly, once a day, so a gap like that is found in a day:

  * every apple row in subscriptions: Apple's current status and expiry win
    (renewed, lapsed, refunded, a free month turned paid), and the row is fixed;
  * every Production original transaction Apple notified us about that no row
    holds: if it carries an appAccountToken naming a real account (builds 123+
    send it), the row is created; otherwise, if it is still paying, it is
    reported — someone pays and has no Plus on their account.

Mails ERROR_REPORT_EMAIL only when it changed something or found an unlinked
subscriber; otherwise it prints one line for the log.

    fac-run subs -- $FAC_PY apple_subs_check.py [--dry-run]

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, ASC_IAP_KEY_ID, ASC_ISSUER_ID,
ASC_IAP_KEY_PATH (the In-App Purchase key: it can read transactions, nothing
else in App Store Connect), SMTP_*, ERROR_REPORT_EMAIL.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import sys
import time
import urllib.parse

import requests

BUNDLE_ID = "com.divinedavis.findacrib"
PRODUCT_ID = "com.divinedavis.findacrib.plus.monthly"
APPLE = "https://api.storekit.itunes.apple.com"
# Apple's subscription status codes (Get All Subscription Statuses).
ACTIVE, EXPIRED, BILLING_RETRY, GRACE, REVOKED = 1, 2, 3, 4, 5


def iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat() if ms else None


def payload(jws):
    """The JSON body of a JWS Apple returned to us over TLS on our own key.
    Not re-verified: it came straight from api.storekit.itunes.apple.com."""
    part = jws.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def desired(status, tx):
    """(status, current_period_end) our row should hold, in the vocabulary
    apple-subscription and apple-notifications write."""
    end = iso(tx.get("expiresDate"))
    if status == REVOKED or tx.get("revocationDate"):
        return "canceled", end
    if status in (ACTIVE, GRACE):
        trial = tx.get("offerDiscountType") == "FREE_TRIAL" or tx.get("price") == 0
        return ("trialing" if trial else "active"), end
    return "inactive", end


def same_time(a, b):
    if not a or not b:
        return a == b
    pa = datetime.datetime.fromisoformat(str(a).replace("Z", "+00:00"))
    pb = datetime.datetime.fromisoformat(str(b).replace("Z", "+00:00"))
    return abs((pa - pb).total_seconds()) < 120


class Apple:
    def __init__(self, key_id, issuer, key_path):
        import jwt  # PyJWT[crypto], in /opt/findacrib/venv
        self._jwt, self.key_id, self.issuer = jwt, key_id, issuer
        with open(key_path) as f:
            self.key = f.read()
        self._tok, self._exp = None, 0

    def token(self):
        if time.time() > self._exp - 60:
            now = int(time.time())
            self._tok = self._jwt.encode(
                {"iss": self.issuer, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1", "bid": BUNDLE_ID},
                self.key, algorithm="ES256", headers={"kid": self.key_id})
            self._exp = now + 1200
        return self._tok

    def status(self, otid):
        """(apple status code, latest transaction payload) or (None, None)."""
        r = requests.get(f"{APPLE}/inApps/v1/subscriptions/{urllib.parse.quote(otid)}",
                         headers={"Authorization": "Bearer " + self.token()}, timeout=30)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        for group in r.json().get("data", []):
            for last in group.get("lastTransactions", []):
                if str(last.get("originalTransactionId")) == str(otid):
                    return last.get("status"), payload(last["signedTransactionInfo"])
        return None, None


class DB:
    def __init__(self, url, key):
        self.base = url.rstrip("/") + "/rest/v1/"
        self.h = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
        self.admin = url.rstrip("/") + "/auth/v1/admin/users/"

    def get(self, path):
        r = requests.get(self.base + path, headers=self.h, timeout=30)
        r.raise_for_status()
        return r.json()

    def patch(self, path, body):
        r = requests.patch(self.base + path, headers={**self.h, "Prefer": "return=minimal"}, json=body, timeout=30)
        r.raise_for_status()

    def insert(self, table, body):
        r = requests.post(self.base + table, headers={**self.h, "Prefer": "return=minimal"}, json=body, timeout=30)
        r.raise_for_status()

    def user_exists(self, uid):
        r = requests.get(self.admin + urllib.parse.quote(uid), headers=self.h, timeout=30)
        return r.status_code == 200


def check(db, apple, dry):
    """Returns (fixed, linked, unlinked, errors) lists of human-readable lines."""
    fixed, linked, unlinked, errors = [], [], [], []
    rows = db.get("subscriptions?provider=eq.apple&select=user_id,status,current_period_end,apple_original_transaction_id")
    known = {str(r["apple_original_transaction_id"]) for r in rows if r.get("apple_original_transaction_id")}
    for r in rows:
        otid = r.get("apple_original_transaction_id")
        if not otid:
            continue
        try:
            st, tx = apple.status(str(otid))
        except Exception as e:
            errors.append(f"Apple lookup failed for {otid}: {str(e)[:120]}")
            continue
        if st is None:
            errors.append(f"Apple has no subscription {otid} (account {r['user_id'][:8]})")
            continue
        want, end = desired(st, tx)
        if want != r["status"] or not same_time(end, r["current_period_end"]):
            fixed.append(f"account {r['user_id'][:8]}: {r['status']} → {want}, ends {end[:10] if end else '-'}")
            if not dry:
                db.patch("subscriptions?user_id=eq." + r["user_id"],
                         {"status": want, "current_period_end": end,
                          "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})

    # Subscriptions Apple told us about that no row holds.
    notes = db.get("apple_notifications?environment=eq.Production&original_transaction_id=not.is.null"
                   "&select=original_transaction_id")
    for otid in sorted({str(n["original_transaction_id"]) for n in notes} - known):
        try:
            st, tx = apple.status(otid)
        except Exception as e:
            errors.append(f"Apple lookup failed for {otid}: {str(e)[:120]}")
            continue
        if st is None or tx.get("productId") != PRODUCT_ID:
            continue
        want, end = desired(st, tx)
        token = (tx.get("appAccountToken") or "").strip().lower()
        if token and db.user_exists(token):
            linked.append(f"account {token[:8]}: {want}, ends {end[:10] if end else '-'} (from its appAccountToken)")
            if not dry:
                db.insert("subscriptions", {
                    "user_id": token, "provider": "apple", "plan": "plus", "status": want,
                    "current_period_end": end, "apple_original_transaction_id": otid,
                    "apple_product_id": PRODUCT_ID, "apple_environment": "Production",
                    "started_at": iso(tx.get("originalPurchaseDate")),
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        elif want in ("active", "trialing"):
            unlinked.append(f"{otid}: {want} until {end[:10] if end else '-'}, bought {iso(tx.get('originalPurchaseDate'))[:10]}"
                            " — paying, but no Find A Crib account is attached")
    return fixed, linked, unlinked, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="change nothing, mail nothing; print what it would do")
    ap.add_argument("--email", default=os.environ.get("ERROR_REPORT_EMAIL"))
    a = ap.parse_args()
    need = ["SUPABASE_URL", "ASC_IAP_KEY_ID", "ASC_ISSUER_ID", "ASC_IAP_KEY_PATH"]
    missing = [k for k in need if not os.environ.get(k)]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if missing or not key:
        sys.exit("apple_subs_check: missing env " + ", ".join(missing + ([] if key else ["SUPABASE_SERVICE_KEY"])))
    db = DB(os.environ["SUPABASE_URL"], key)
    apple = Apple(os.environ["ASC_IAP_KEY_ID"], os.environ["ASC_ISSUER_ID"], os.environ["ASC_IAP_KEY_PATH"])
    fixed, linked, unlinked, errors = check(db, apple, a.dry_run)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(json.dumps({"at": stamp, "fixed": len(fixed), "linked": len(linked), "unlinked": len(unlinked),
                      "errors": len(errors), "dry_run": a.dry_run}))
    if not (fixed or linked or unlinked or errors):
        return
    sections = [("Corrected from Apple's records", fixed), ("Linked to their account", linked),
                ("Paying, but not on any account", unlinked), ("Could not check", errors)]
    text = "\n\n".join(t + ":\n" + "\n".join("  • " + x for x in xs) for t, xs in sections if xs)
    if unlinked:
        text += ("\n\nAn unlinked subscriber pays and has no Plus on their account. Match them by the purchase"
                 " time against in-app sign-ins, then write their subscriptions row.")
    if a.dry_run or not a.email:
        print(text)
        return
    import html as _h
    body = "".join(f"<h3>{_h.escape(t)}</h3><ul>" + "".join(f"<li>{_h.escape(x)}</li>" for x in xs) + "</ul>"
                   for t, xs in sections if xs)
    bits = [f"{len(xs)} {w}" for w, xs in (("fixed", fixed), ("linked", linked), ("UNLINKED", unlinked),
                                           ("errors", errors)) if xs]
    from growth import emailkit
    emailkit.send(a.email, "Find A Crib App Store subscriptions: " + ", ".join(bits), body, text,
                  from_name="Find A Crib alerts")
    print("emailed", a.email)


if __name__ == "__main__":
    main()
