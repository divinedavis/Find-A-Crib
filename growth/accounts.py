#!/usr/bin/env python3
"""Free-account lifecycle sequence.

A new account currently receives nothing: Supabase auth here runs with
mailer_autoconfirm and no SMTP host, so signup produces no confirmation and no
welcome. People sign up, hear silence, and don't come back — week-over-week
retention is 6%. This is the smallest sequence that plausibly changes that.

Three steps, each gated on behaviour so most accounts get one or two:

  welcome   day 0-1   the account exists and here is what saving does
  activate  day 3     skipped if they have already saved a building
  lapsed    day 21    skipped if they have visited in the last 14 days

CUTOVER is the important safety rail. The owner chose "new signups only", and
gating just the welcome on age would still have fired `activate` and `lapsed`
at 17 existing cold accounts on the first run — a backfill blast arriving by
the back door, to people who signed up weeks ago and would reasonably read it
as spam. Accounts created before CUTOVER are excluded from the sequence
entirely, forever.

Reads through SECURITY DEFINER RPCs (migration 0004) rather than the Supabase
management PAT, so the web droplet never holds a project-wide admin token.
"""
import datetime
import json
import os
import urllib.request

from . import emailkit, ledger, mailcap

SITE = "https://findacrib.com"
SUPABASE_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"

# Accounts created before this date never enter the sequence. See the module
# docstring — this is what makes "new signups only" true rather than nominal.
CUTOVER = datetime.date(2026, 7, 27)

OWNER_USER_ID = "af2629f7-1121-4bee-8a2b-cede9318c864"

STEPS = ("welcome", "activate", "lapsed")
MAX_PER_RUN = 50
LAPSED_QUIET_DAYS = 14

FOOTER_NOTE = "You're getting this because you made a free Find A Crib account."


def _service_key():
    return (os.environ.get("SUPABASE_SERVICE_KEY")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "")


def _rpc(name, body=None):
    key = _service_key()
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY not set")
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/{name}",
        data=json.dumps(body or {}).encode(),
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def _parse_ts(v):
    """Postgres returns '+00' offsets, which fromisoformat rejects before 3.11.
    Same trap as growth/lifecycle.py — normalise instead of trusting the
    interpreter version."""
    if not v:
        return None
    t = str(v).strip().replace(" ", "T").replace("Z", "+00:00")
    if len(t) >= 3 and t[-3] in "+-":
        t += ":00"
    for candidate in (t, t.split(".")[0] + t[-6:] if "." in t else t):
        try:
            d = datetime.datetime.fromisoformat(candidate)
            return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None


def _unsub(token):
    # Reuses the site's existing #unsub handler, with k=lifecycle so it stops
    # only this sequence and leaves saved-building alerts working.
    return f"{SITE}/#unsub={token}&k=lifecycle"


# -------------------------------------------------------------------- copy

def welcome(row, ctx):
    html, text = emailkit.render(
        title="Your Find A Crib account is ready",
        intro="You can now save buildings across devices — here's the part worth knowing.",
        blocks=[
            {"type": "paragraph",
             "text": "Find A Crib maps every building registered rent-stabilized with "
                     "DHCR — all 47,000 of them across the five boroughs, plus San "
                     "Francisco, Los Angeles and Washington DC."},
            {"type": "card",
             "heading": "Save a building, and we'll watch it for you",
             "body": "When an apartment in a building you saved gets advertised — "
                     "including listings that explicitly accept housing vouchers — you "
                     "get an email that night. It's the single most useful thing an "
                     "account does.",
             "link": ("Open the map", f"{SITE}/")},
            {"type": "paragraph",
             "text": "One caveat we'd rather say up front: a building being registered "
                     "doesn't guarantee a particular apartment is stabilized. Only the "
                     "DHCR rent history for that unit settles it, and it's free to request."},
        ],
        footer_note=FOOTER_NOTE, unsub_url=_unsub(row["token"]),
        unsub_label="Stop these emails")
    return "Your Find A Crib account is ready", html, text


def activate(row, ctx):
    html, text = emailkit.render(
        title="Checking one specific address?",
        intro="Your account is set up but nothing's saved yet — so here's the thing "
              "the map is actually for.",
        blocks=[
            {"type": "paragraph",
             "text": "Before signing a lease, search the exact address. If it comes up, "
                     "the building is registered rent-stabilized, which means the rent is "
                     "capped by the Rent Guidelines Board every year rather than set by "
                     "whatever the market will bear."},
            {"type": "steps", "items": [
                "Search the address on the map.",
                "Open the building to see its owner, managing agent, and open HPD "
                "violations.",
                "Save it — you'll get an email the night anything there is advertised.",
            ]},
            {"type": "card",
             "heading": "Apartments listed for voucher holders right now",
             "meta": "Updated every night",
             "body": "Rent-stabilized buildings with an apartment currently listed on "
                     "AffordableHousing.com, cheapest first.",
             "link": ("See what's listed", f"{SITE}/section8/")},
        ],
        cta=("Search an address", f"{SITE}/"),
        footer_note=FOOTER_NOTE, unsub_url=_unsub(row["token"]),
        unsub_label="Stop these emails")
    return "Checking one specific address?", html, text


def lapsed(row, ctx):
    n = ctx.get("voucher_buildings")
    listed_line = (f"{n:,} rent-stabilized buildings have an apartment listed for voucher "
                   f"holders right now." if n else
                   "Rent-stabilized buildings are being listed for voucher holders daily.")
    html, text = emailkit.render(
        title="What's changed since you were last here",
        intro="The listings move constantly — here's where things stand today.",
        blocks=[
            {"type": "paragraph", "text": listed_line},
            {"type": "card",
             "heading": "Today's voucher listings",
             "meta": "Rebuilt every night from the AffordableHousing.com feed",
             "body": "Every building on this list is registered rent-stabilized AND has "
                     "an apartment listed now — the two things are rarely cross-referenced "
                     "anywhere else.",
             "link": ("Open the list", f"{SITE}/section8/")},
            {"type": "paragraph",
             "text": "If you're not looking right now, no problem — save any building you "
                     "care about and we'll email you only when something actually opens up "
                     "there. Nothing until then."},
        ],
        footer_note=FOOTER_NOTE, unsub_url=_unsub(row["token"]),
        unsub_label="Stop these emails")
    return "What's changed since you were last here", html, text


BUILDERS = {"welcome": welcome, "activate": activate, "lapsed": lapsed}


# --------------------------------------------------------------------- due

def _step_for(row, now):
    """Which step, if any, this account is due. One per run, never a burst."""
    sent = set(row.get("sent_steps") or [])
    days = row.get("days_old") or 0
    saves = row.get("save_count") or 0
    last_seen = _parse_ts(row.get("last_seen"))

    if "welcome" not in sent and days <= 1:
        return "welcome"
    if "activate" not in sent and days >= 3 and saves == 0:
        return "activate"
    if "lapsed" not in sent and days >= 21:
        quiet = last_seen is None or (now - last_seen).days >= LAPSED_QUIET_DAYS
        if quiet:
            return "lapsed"
    return None


def due(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        _rpc("lifecycle_ensure_prefs")
    except Exception:
        pass                    # a missing prefs row just means nobody is due yet
    rows = _rpc("lifecycle_accounts_due") or []
    out = []
    for r in rows:
        if str(r.get("user_id")) == OWNER_USER_ID:
            continue
        created = _parse_ts(r.get("created_at"))
        if created is None or created.date() < CUTOVER:
            continue            # pre-existing account: never enters the sequence
        step = _step_for(r, now)
        if step:
            out.append((r, step))
        if len(out) >= MAX_PER_RUN:
            break
    return out


def run(dry_run=False, now=None, voucher_buildings=None):
    try:
        pending = due(now=now)
    except Exception as e:
        detail = f"could not read accounts: {e}"
        ledger.set_state("accounts_last", {"date": ledger.today(), "ok": False, "detail": detail})
        print(f"  {detail}")
        return {"ok": False, "detail": detail}

    if not pending:
        ledger.set_state("accounts_last", {"date": ledger.today(), "ok": True, "sent": 0,
                                           "detail": "nothing due"})
        print("  nothing due")
        return {"ok": True, "sent": 0, "detail": "nothing due"}

    ctx = {"voucher_buildings": voucher_buildings}
    sent, failed = [], []
    for row, step in pending:
        subject, html, text = BUILDERS[step](row, ctx)
        if dry_run:
            print(f"  [dry-run] {step} -> {row['email']} "
                  f"({row.get('days_old')}d old, {row.get('save_count')} saves) — {subject}")
            sent.append(step)
            continue
        # One Find A Crib email a day, whichever job sends it (growth/mailcap).
        # A step that loses today's slot is simply still due tomorrow.
        try:
            if not mailcap.claim(row["email"], "lifecycle"):
                print(f"  {step} -> {row['email']}: already emailed today, still due")
                continue
        except Exception as e:
            failed.append(f"{step}->{row['email']}: ledger {e}")
            continue
        try:
            emailkit.send(row["email"], subject, html, text, unsub_url=_unsub(row["token"]))
        except Exception as e:
            mailcap.release(row["email"])
            failed.append(f"{step}->{row['email']}: {e}")
            continue
        try:
            _rpc("lifecycle_mark_sent", {"p_user_id": row["user_id"], "p_step": step})
        except Exception as e:
            failed.append(f"{step} sent but not recorded for {row['email']}: {e}")
        sent.append(step)
        print(f"  sent {step} -> {row['email']} ({row.get('days_old')}d old)")

    by_step = {s: sent.count(s) for s in set(sent)}
    detail = f"{len(sent)} sent {by_step}" + (f", {len(failed)} failed" if failed else "")
    ledger.set_state("accounts_last", {"date": ledger.today(), "ok": not failed,
                                       "sent": len(sent), "by_step": by_step,
                                       "failed": failed[:5], "detail": detail})
    ledger.record_result(ledger.today(), "account_lifecycle", "emails_sent", len(sent))
    return {"ok": not failed, "sent": len(sent), "by_step": by_step,
            "failed": failed, "detail": detail}
