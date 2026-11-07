#!/usr/bin/env python3
"""Send the billing notices the law requires (2026-11-07, owner: "fix this").

Today that is one: the trial-ending reminder. California's automatic renewal
law (Bus. & Prof. Code 17602(a)(3)) and the FTC's ROSCA expect a subscriber on
a free trial to hear, before the first charge, what will be charged, when, and
how to cancel. Stripe fires customer.subscription.trial_will_end three days
before a trial ends; supabase/functions/stripe-webhook records it in
public.billing_notices, and this job (deploy/cron-rentmap-billing, every 10
min, as `scraper` with the supabase + smtp env sets) mails each unsent row
once and stamps sent_at.

Rules this job keeps on purpose:
  * It never touches the one-email-a-day ledger (growth/mailcap.py). A legal
    notice must not wait behind, or be dropped for, an alert email.
  * Transactional: no unsubscribe (CAN-SPAM doesn't require one and a person
    can't opt out of being told they're about to be charged). The postal
    address comes from emailkit's footer like every other email.
  * A row whose trial already ended, or whose subscription is no longer
    trialing, is closed without mail: telling someone they "will be charged"
    after the fact, or after they cancelled, is wrong.
  * Failures are retried on the next run, up to MAX_ATTEMPTS.

    python3 billing_notices.py                 # send what's due
    python3 billing_notices.py --dry-run       # print, send nothing, write nothing
    python3 billing_notices.py --test-email you@x.com   # one sample, no table rows
"""
import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from growth import emailkit

SITE = "https://findacrib.com"
MANAGE_URL = f"{SITE}/#manage-plus"
NY = ZoneInfo("America/New_York")
MAX_ATTEMPTS = 6
SUBJECT = "Your Find A Crib Plus trial ends {day}: {amount}/{interval} after that"


def money(cents, currency="usd"):
    sym = {"usd": "$"}.get((currency or "usd").lower(), "")
    amt = f"{cents / 100:,.2f}"
    return f"{sym}{amt}" if sym else f"{amt} {currency.upper()}"


def build(row):
    """(subject, html, text) for one billing_notices row."""
    end = datetime.datetime.fromisoformat(str(row["trial_end"]).replace("Z", "+00:00")).astimezone(NY)
    day = f"{end:%A, %B} {end.day}, {end.year}"
    short = f"{end:%b} {end.day}"
    clock = f"{end:%-I:%M %p} ET"
    amount = money(int(row["amount_cents"]), row.get("currency") or "usd")
    interval = row.get("interval") or "month"
    subject = SUBJECT.format(day=short, amount=amount, interval=interval)
    html, text = emailkit.render(
        title=f"Your first month of Plus ends {short}",
        intro=(f"On {day}, your card on file with Stripe will be charged {amount} for Find A Crib Plus, "
               f"and then {amount} every {interval} until you cancel."),
        blocks=[
            {"type": "card", "heading": "Don't want to be charged?",
             "body": (f"Cancel any time before {clock} on {day}. Sign in at findacrib.com, open Your account and tap "
                      "Manage or cancel Plus. It takes a minute, and you keep Plus until the trial ends."),
             "link": ("Manage or cancel Plus", MANAGE_URL)},
            {"type": "card", "heading": "Keeping it?",
             "body": "You don't need to do anything. Real-time alerts, no ads and the renter tools stay on."},
        ],
        cta=("Manage or cancel Plus", MANAGE_URL),
        footer_note=("You're getting this because you started a Find A Crib Plus trial on the web. "
                     "It's a billing notice, sent once before your first charge. "
                     "Questions: reply to this email."))
    return subject, html, text


def rest(path, method="GET", body=None, prefer=None):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "User-Agent": "fac-billing-notices"}
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def close(row_id, fields):
    rest(f"billing_notices?id=eq.{int(row_id)}", "PATCH", fields, prefer="return=minimal")


def still_trialing(sub_id):
    """The subscriptions row the webhook keeps current. None = unknown."""
    rows = rest("subscriptions?select=status&stripe_subscription_id=eq."
                + urllib.parse.quote(sub_id, safe="")) or []
    if not rows:
        return None
    return rows[0].get("status") == "trialing"


def run(dry):
    rows = rest("billing_notices?select=*&sent_at=is.null&attempts=lt." + str(MAX_ATTEMPTS)
                + "&order=trial_end.asc&limit=50") or []
    now = datetime.datetime.now(datetime.timezone.utc)
    sent = skipped = failed = 0
    for row in rows:
        end = datetime.datetime.fromisoformat(str(row["trial_end"]).replace("Z", "+00:00"))
        who = emailkit.mask_email(row["email"])
        if end <= now:
            print(f"skip {row['id']} {who}: trial already ended")
            skipped += 1
            if not dry:
                close(row["id"], {"last_error": "trial already ended", "attempts": MAX_ATTEMPTS})
            continue
        if still_trialing(row["stripe_subscription_id"]) is False:
            print(f"skip {row['id']} {who}: no longer trialing")
            skipped += 1
            if not dry:
                close(row["id"], {"last_error": "no longer trialing", "attempts": MAX_ATTEMPTS})
            continue
        subject, html, text = build(row)
        if dry:
            print(f"would send {row['id']} {who}: {subject}")
            continue
        try:
            # Deliberately no mailcap.claim(): a required notice never waits.
            ok = emailkit.send(row["email"], subject, html, text)
            if ok is False:
                raise RuntimeError("address is on the suppression list")
            close(row["id"], {"sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              "attempts": int(row.get("attempts") or 0) + 1, "last_error": None})
            sent += 1
            print(f"sent {row['id']} {who}: {subject}")
        except Exception as e:
            failed += 1
            print(f"FAILED {row['id']} {who}: {type(e).__name__}: {str(e)[:120]}")
            close(row["id"], {"attempts": int(row.get("attempts") or 0) + 1,
                              "last_error": f"{type(e).__name__}: {str(e)[:200]}"})
    if rows or failed:
        print(f"billing notices: {sent} sent, {skipped} closed, {failed} failed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-email", default="")
    a = ap.parse_args()
    if a.test_email:
        end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
        subject, html, text = build({"trial_end": end.isoformat(), "amount_cents": 499,
                                     "currency": "usd", "interval": "month"})
        emailkit.send(a.test_email, "[TEST] " + subject, html, text)
        print(f"test sent to {emailkit.mask_email(a.test_email)}")
        return 0
    return run(a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
