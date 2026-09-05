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
import urllib.parse
import urllib.request

from . import emailkit, ledger, mailcap

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

FOOTER_NOTE = "You're getting this because you bought a building report."


def day3_rent_history(row, b, unsub):
    addr = _addr(b)
    subject = f"The free step most people skip — {addr}"
    html, text = emailkit.render(
        title="One thing in your report matters more than the rest",
        intro=f"You picked up a report on {addr} a few days ago. This is the part that's "
              f"easiest to put off, so here it is again.",
        blocks=[
            {"type": "paragraph",
             "text": "If the apartment is rent stabilized, the legal rent is whatever DHCR "
                     "has on record — not whatever the lease says. Asking for that history "
                     "is free, takes about two minutes, and it's the only way to find out "
                     "whether you're being overcharged."},
            {"type": "steps", "items": [
                "Email rentinfo@hcr.ny.gov, or call (718) 739-6400.",
                "Ask for the FULL registration history, not just the current year.",
                "Compare it to the rent you were quoted — big unexplained jumps between "
                "tenants are the classic overcharge pattern.",
            ]},
            {"type": "quote", "text":
                f"Address:   {addr}\n"
                f"BBL:       {row.get('bbl')}\n"
                f"Apartment: ____\n\n"
                f"\"I am the current or prospective tenant of this apartment.\n"
                f" Please send the full rent registration history for all years\n"
                f" available, including the registered legal regulated rent and\n"
                f" any preferential rent recorded.\""},
            {"type": "paragraph",
             "text": "If the numbers come back looking wrong, that's a DHCR overcharge "
                     "complaint (form RA-89). The lookback window is limited, so it's worth "
                     "doing sooner rather than later."},
        ],
        cta=("Open your report", f"{SITE}/report/{row['token']}"),
        footer_note=FOOTER_NOTE, unsub_url=unsub,
        unsub_label="Stop these follow-ups")
    return subject, html, text


def day14_followup(row, b, unsub):
    addr = _addr(b)
    subject = f"How did it go with {addr}?"
    html, text = emailkit.render(
        title=f"How did it go with {addr}?",
        intro="However it turned out — signed, walked away, still deciding — one thing "
              "might still be useful.",
        blocks=[
            {"type": "paragraph",
             "text": "If you make a free account and save that building, we'll email you "
                     "when an apartment there is advertised again, including listings that "
                     "explicitly accept housing vouchers. It's the same nightly feed your "
                     "report was built from, and it costs nothing."},
            {"type": "paragraph",
             "text": "And if the rent history came back looking off, the overcharge route "
                     "is still open — DHCR form RA-89. Reply to this email if you want a "
                     "hand reading what they sent you; a real person will answer."},
        ],
        cta=("Save the building", f"{SITE}/"),
        footer_note=FOOTER_NOTE, unsub_url=unsub,
        unsub_label="Stop these follow-ups")
    return subject, html, text


BUILDERS = {"day3_rent_history": day3_rent_history, "day14_followup": day14_followup}


# ------------------------------------------------------------------- send

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
        subject, html, text = BUILDERS[step](row, b, unsub)
        if dry_run:
            print(f"  [dry-run] {step} -> {row['email']} ({age}d) — {subject}")
            sent.append(step)
            continue
        try:
            if not mailcap.claim(row["email"], "report"):
                print(f"  {step} -> {row['email']}: already emailed today, still due")
                continue
        except Exception as e:
            failed.append(f"{step}->{row['email']}: ledger {e}")
            continue
        try:
            emailkit.send(row["email"], subject, html, text, unsub_url=unsub)
        except Exception as e:
            mailcap.release(row["email"])
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
