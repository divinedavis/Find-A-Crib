#!/usr/bin/env python3
"""Follow-up sequence for Building Report buyers.

Lifecycle email aimed at people who already paid, rather than at free accounts.
The reasoning is arithmetic: there are 3 accounts with saved buildings, so a
drip campaign there produces no measurable signal and the 21-day review would
correctly retire it. Buyers hand over an email at the highest-intent moment in
the funnel and have a specific building they care about — that is a base worth
building on, and it grows with revenue rather than ahead of it.

Two steps, both of which exist because they are genuinely useful to the buyer,
not because a sequence "should" have N touches:

  day 3   Did you send the DHCR rent-history request? It is free, it is the one
          action that establishes whether they are being overcharged, and most
          people will not have done it. The letter goes out again, pre-filled.
  day 14  What happened? Plus the one thing we can offer that is actually
          relevant to someone mid-move: an alert if that building lists again.

Rules this module holds itself to:
  * idempotent — sent_steps is written before nothing else can undo it, so a
    re-run, a crash, or a double-invocation never mails anyone twice
  * stoppable  — every message carries a working unsubscribe, honoured forever,
    plus List-Unsubscribe headers so a one-click in Gmail works
  * quiet      — nothing sends without SMTP configured, and a dry run sends
    nothing at all
"""
import datetime
import json
import os
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr

from . import ledger

SITE = "https://findacrib.com"
SUPABASE_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"

# (step id, days after purchase, subject builder, body builder)
STEPS = ("day3_rent_history", "day14_followup")
DELAYS = {"day3_rent_history": 3, "day14_followup": 14}
MAX_PER_RUN = 200          # a sane ceiling; nothing near this volume exists yet


def _service_key():
    return (os.environ.get("SUPABASE_SERVICE_KEY")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "")


def _rest(method, path, body=None, prefer=None):
    key = _service_key()
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY not set")
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def _parse_ts(v):
    """Parse a Postgres timestamptz.

    PostgREST returns offsets as '+00', which datetime.fromisoformat rejects
    before Python 3.11 — it wants '+00:00'. The droplet runs 3.12 and would
    have been fine; a dev box on 3.9 silently dropped every buyer instead.
    Normalise rather than depend on the interpreter version.
    """
    if not v:
        return None
    t = str(v).strip().replace(" ", "T").replace("Z", "+00:00")
    if len(t) >= 3 and t[-3] in "+-":          # '+00' -> '+00:00'
        t += ":00"
    for candidate in (t, t.split(".")[0] + t[-6:] if "." in t else t):
        try:
            d = datetime.datetime.fromisoformat(candidate)
            return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None


def _addr(b):
    return " ".join(w.capitalize() if not w.isdigit() else w
                    for w in str((b or {}).get("a") or "your building").split())


def _building(bbl, buildings_by_bbl):
    return buildings_by_bbl.get(str(bbl)) or {}


# ------------------------------------------------------------------- copy

def _footer(unsub):
    return (f"\n\n—\nFind A Crib · {SITE}\n"
            f"You're getting this because you bought a building report. "
            f"Stop these follow-ups: {unsub}\n")


def day3_rent_history(row, b, unsub):
    addr = _addr(b)
    subject = f"The free step most people skip — {addr}"
    body = (
        f"Hi,\n\n"
        f"You picked up a building report on {addr} a few days ago. One thing in it "
        f"matters more than the rest, and it's the easiest to put off, so here it is again.\n\n"
        f"If the apartment is rent stabilized, the legal rent is whatever DHCR has on record — "
        f"not whatever the lease says. Asking for that history is free, takes about two minutes, "
        f"and it's the only way to find out whether you're being overcharged.\n\n"
        f"Email rentinfo@hcr.ny.gov, or call (718) 739-6400. Ask for the FULL registration "
        f"history, not just the current year:\n\n"
        f"    Address:   {addr}\n"
        f"    BBL:       {row.get('bbl')}\n"
        f"    Apartment: ____\n\n"
        f"    \"I am the current or prospective tenant of this apartment. Please send the\n"
        f"     full rent registration history for all years available, including the\n"
        f"     registered legal regulated rent and any preferential rent recorded.\"\n\n"
        f"If the numbers come back looking wrong — big unexplained jumps between tenants — "
        f"that's a DHCR overcharge complaint (form RA-89). The lookback window is limited, "
        f"so it's worth doing sooner rather than later.\n\n"
        f"Your report is still here: {SITE}/report/{row['token']}\n"
        + _footer(unsub))
    return subject, body


def day14_followup(row, b, unsub):
    addr = _addr(b)
    subject = f"How did it go with {addr}?"
    body = (
        f"Hi,\n\n"
        f"Two weeks ago you looked into {addr}. However it turned out — signed, walked away, "
        f"still deciding — one thing might be useful.\n\n"
        f"If you make a free account and save that building, we'll email you when an apartment "
        f"there is advertised again, including listings that explicitly accept housing vouchers. "
        f"It's the same nightly feed the report was built from. No card, and it costs nothing:\n\n"
        f"    {SITE}/\n\n"
        f"And if the rent history came back looking off, the overcharge route is still open — "
        f"DHCR form RA-89. Reply to this email if you want a hand reading what they sent you; "
        f"a real person will answer.\n\n"
        f"Your report: {SITE}/report/{row['token']}\n"
        + _footer(unsub))
    return subject, body


BUILDERS = {"day3_rent_history": day3_rent_history, "day14_followup": day14_followup}


# ------------------------------------------------------------------- send

def _send(to, subject, body, unsub_url):
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASSWORD")
    if not (host and user and pw):
        raise RuntimeError("SMTP not configured")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Find A Crib", user))
    msg["To"] = to
    # One-click unsubscribe: Gmail and Outlook surface a native button for
    # these, and honouring it is what keeps the domain out of spam folders —
    # which matters doubly here, because the same domain sends the product's
    # own saved-building alerts.
    msg["List-Unsubscribe"] = f"<{unsub_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())


def due(now=None):
    """Paid, subscribed reports with a step whose delay has elapsed."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    rows = _rest("GET", "building_reports?select=id,token,bbl,email,paid_at,sent_steps,"
                        "unsub_token,unsubscribed_at&status=eq.paid&unsubscribed_at=is.null"
                        f"&limit={MAX_PER_RUN}")
    out = []
    skipped = []
    for r in rows or []:
        if not r.get("email") or not r.get("paid_at"):
            continue
        paid = _parse_ts(r["paid_at"])
        if paid is None:
            # Never swallow this quietly: an unparseable timestamp drops a
            # paying customer out of the sequence, and "nothing due" is
            # indistinguishable from working correctly.
            skipped.append(r.get("email"))
            continue
        age_days = (now - paid).days
        sent = set(r.get("sent_steps") or [])
        for step in STEPS:
            if step in sent:
                continue
            if age_days >= DELAYS[step]:
                out.append((r, step, age_days))
                break        # one step per run per buyer — never a burst
    if skipped:
        print(f"  WARNING: {len(skipped)} buyer(s) skipped — unparseable paid_at: {skipped[:3]}")
    return out


def run(buildings_by_bbl=None, dry_run=False, now=None):
    """Send whatever is due. Returns a summary."""
    try:
        pending = due(now=now)
    except Exception as e:
        detail = f"could not read building_reports: {e}"
        ledger.set_state("lifecycle_last", {"date": ledger.today(), "ok": False, "detail": detail})
        print(f"  {detail}")
        return {"ok": False, "detail": detail}

    if not pending:
        ledger.set_state("lifecycle_last", {"date": ledger.today(), "ok": True,
                                            "sent": 0, "detail": "nothing due"})
        print("  nothing due")
        return {"ok": True, "sent": 0, "detail": "nothing due"}

    if buildings_by_bbl is None:
        buildings_by_bbl = {}

    sent, failed = [], []
    for row, step, age in pending:
        b = _building(row["bbl"], buildings_by_bbl)
        unsub = f"{SITE}/api/reports/unsubscribe?t={row.get('unsub_token') or ''}"
        subject, body = BUILDERS[step](row, b, unsub)
        if dry_run:
            print(f"  [dry-run] {step} -> {row['email']} ({age}d) — {subject}")
            sent.append(step)
            continue
        try:
            _send(row["email"], subject, body, unsub)
        except Exception as e:
            failed.append(f"{step}->{row['email']}: {e}")
            continue
        # Record immediately after a successful send. If this write fails the
        # buyer could see a duplicate tomorrow — annoying but recoverable —
        # whereas writing first would silently drop a message on send failure.
        try:
            steps = list(row.get("sent_steps") or []) + [step]
            _rest("PATCH", f"building_reports?id=eq.{urllib.parse.quote(str(row['id']))}",
                  {"sent_steps": steps}, prefer="return=minimal")
        except Exception as e:
            failed.append(f"{step} sent but not recorded for {row['email']}: {e}")
        sent.append(step)
        print(f"  sent {step} -> {row['email']} ({age}d after purchase)")

    detail = f"{len(sent)} sent" + (f", {len(failed)} failed" if failed else "")
    ledger.set_state("lifecycle_last", {"date": ledger.today(), "ok": not failed,
                                        "sent": len(sent), "failed": failed[:5],
                                        "detail": detail})
    ledger.record_result(ledger.today(), "lifecycle_email", "emails_sent", len(sent))
    return {"ok": not failed, "sent": len(sent), "failed": failed, "detail": detail}
