#!/usr/bin/env python3
"""One Find A Crib email per person per day, across every job that sends.

Owner rule (2026-09-05): "don't send more than one email a day." Four jobs
send mail from this checkout — the 10-minute borough alerts, the morning
saved-building alerts, the account lifecycle sequence and the report buyer
sequence — and none of them can see the others' state, so the cap lives in
the database: public.email_sends, one row per (address, New York day),
claimed through the email_claim() RPC before a send.

    from growth import mailcap
    if mailcap.claim(addr, "alert"):
        emailkit.send(...)          # on failure: mailcap.release(addr)
    else:
        hold it for tomorrow        # never drop it, never send anyway

The claim is the reservation, not the record: a job that claims and then
fails to send must release, or the address is blocked for the day by an email
nobody received. A job that loses the claim keeps its content — the borough
dispatcher holds items per subscriber, the saved-building job keeps a pending
list per user — so the reader gets it in tomorrow's one email.

`--dry-run` callers pass dry=True and get True without touching the ledger.
Without a service key the claim raises: silently sending unmetered would be
the one failure mode this module exists to prevent.
"""
import json
import os
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dbaifotzwlxjvsxjohjt.supabase.co")


def _key():
    key = (os.environ.get("SUPABASE_SERVICE_KEY")
           or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY not set — refusing to send unmetered mail")
    return key


def _rpc(name, body):
    key = _key()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/{name}", data=json.dumps(body).encode(),
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "User-Agent": "fac-mailcap"},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def claim(email, kind, dry=False):
    """True if `email` may receive a `kind` email today. False = already had
    one; hold the content. Raises if the ledger is unreachable — the caller
    decides whether to skip the run (the right answer) or crash."""
    if dry:
        return True
    return bool(_rpc("email_claim", {"p_email": email, "p_kind": kind}))


def release(email, dry=False):
    """Give today's slot back after a failed send."""
    if dry:
        return True
    try:
        return bool(_rpc("email_release", {"p_email": email}))
    except Exception:
        return False
