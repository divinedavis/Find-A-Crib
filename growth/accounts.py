#!/usr/bin/env python3
"""Free-account lifecycle sequence.

A new account currently receives nothing: Supabase auth here runs with
mailer_autoconfirm and no SMTP host, so signup produces no confirmation and no
welcome. People sign up, hear silence, and don't come back — week-over-week
retention is 6%. This is the smallest sequence that plausibly changes that.

Four steps, each gated on behaviour so most accounts get one or two:

  welcome   day 0-1   the account exists and here is what saving does
  activate  day 3     skipped if they have already saved a building
  lapsed    day 21    skipped if they have visited in the last 14 days
  saved     day 5+    only for an ACTIVE account that has saved a building

`saved` was added 2026-09-11 and is the only step that asks for money. The
reason is arithmetic, and it is the same argument build_seo.py made on
2026-08-27 when it put the $9 ask on building pages: accounts_with_saves has
gone 6 -> 21 since 2026-08-25 and rises most days, while reports_sold,
paying_subs and mrr_usd have been 0 for the product's entire life. Before
today this sequence never made a paid offer at all — an engaged saver received
`welcome` on day 0 and then nothing, ever, because `activate` is skipped once
they save and `lapsed` is skipped while they keep visiting. So the one
audience with proven intent was the one audience never asked. That is not
evidence the $9 ask fails; it is evidence it was never made here.

What keeps it honest rather than merely promotional:
  * it leads with the free action (the DHCR rent history) that actually
    settles the reader's question, and says outright that the report does not
    contain it;
  * the offer is only made when we can name a real building from the corpus
    with an HPD record behind it — the same refusal build_seo.py makes, for
    the same reason: selling a $9 report on a building we can say nothing
    about trades the site's credibility for revenue;
  * anyone who already bought a report is suppressed, and if that check
    cannot be read the step is held rather than guessed;
  * it goes only to accounts that have been on the site in the last 14 days,
    which also makes it mutually exclusive with `lapsed` — nobody can be due
    both, so the sequence still cannot burst.

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

STEPS = ("welcome", "activate", "lapsed", "saved")
MAX_PER_RUN = 50
LAPSED_QUIET_DAYS = 14
SAVED_MIN_DAYS = 5          # long enough that `welcome` is not still in the inbox

FOOTER_NOTE = "You're getting this because you made a free Find A Crib account."

# WORD-FOR-WORD the description shipped beside the live Stripe button in
# index.html and in the CTA build_seo.py writes onto every building page. Three
# surfaces now describe one product, and they must not drift into making
# different claims about it. If this sentence changes, change it in all three.
REPORT_PROMISE = (
    "How this building's violation record compares citywide, who owns it and "
    "what else they own, and a pre-filled DHCR rent-history request. One-time, "
    "no account needed. The report also states plainly what the data cannot "
    "tell you.")


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


def _rest(path):
    """One GET against PostgREST with the service key. Used for the single
    table this module reads directly — building_reports, to suppress people who
    have already bought. Everything about *accounts* still goes through the
    SECURITY DEFINER RPCs, which is what keeps auth.users out of reach."""
    key = _service_key()
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY not set")
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else []


def report_buyer_emails():
    """Lower-cased emails that have already paid for a Building Report.

    Raises on failure on purpose. Offering a $9 report to somebody who already
    bought one is the one version of the `saved` email that is simply wrong, so
    the caller drops the step for the run instead of guessing; it is still due
    tomorrow. A buyer is not left empty-handed either way — growth/lifecycle.py
    is their sequence.
    """
    rows = _rest("building_reports?select=email&status=eq.paid&limit=5000")
    return {str(r.get("email") or "").strip().lower()
            for r in (rows or []) if r.get("email")}


def saved_context():
    """{user_id: {"bbls": [...newest first...], "home_bbl": ...}}.

    saved_watchers() (db/0025_home_bbl.sql) is the saved-building alert
    dispatcher's RPC — already deployed, already granted to service_role — so
    the `saved` step can name a real building without a new migration and
    without this module gaining a read on saved_buildings. If it is ever
    missing or fails, the step degrades to copy that names no building and
    makes no offer, which is the correct failure: we never say "your building
    at X" unless we actually read X.
    """
    out = {}
    try:
        for r in _rpc("saved_watchers") or []:
            home = str(r.get("home_bbl") or "").strip()
            out[str(r.get("user_id"))] = {
                "bbls": [str(b) for b in (r.get("bbls") or []) if b],
                "home_bbl": home or None}
    except Exception as e:
        print(f"  saved_watchers unavailable ({e}) — the saved step will name no building")
    return out


def _addr(b):
    """Title-case a corpus address. Same helper, same rule, as lifecycle.py."""
    return " ".join(w.capitalize() if not w.isdigit() else w
                    for w in str((b or {}).get("a") or "").split())


def report_target(row, buildings):
    """The one building this account's report offer is about, or (None, None).

    Preference order is the reader's own: the apartment they pinned as theirs
    ("My apartment", auth metadata home_bbl) beats the most recently saved
    building. Both must resolve in buildings.min.json AND carry an HPD record
    ("h"), because that record is what sections 1 and 2 of the report are built
    from. 64 of the 47,165 buildings in the corpus have no HPD block; on those
    the report would be thin and we do not offer it. Same gate, same reason, as
    the building-page CTA in build_seo.py.
    """
    if not buildings:
        return None, None
    seen = set()
    for bbl in [row.get("home_bbl")] + list(row.get("saved_bbls") or []):
        if not bbl or bbl in seen:
            continue
        seen.add(bbl)
        b = buildings.get(str(bbl))
        if b and b.get("h"):
            return str(bbl), b
    return None, None


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


def saved(row, ctx):
    """Day 5+, to an active account that has saved at least one building.

    The lead is the free thing, not the paid thing, and that ordering is the
    point rather than a courtesy: the DHCR rent history is what actually
    settles the reader's question, it costs nothing, and this sequence would
    rather be the thing that told them so. The $9 report is offered second, for
    the case the free route does not cover — somebody still looking, who cannot
    request a history for an apartment they do not rent yet.
    """
    bbl, b = report_target(row, ctx.get("buildings"))
    addr = _addr(b)
    n = row.get("save_count") or 0

    # The two DHCR facts are lifted from growth/lifecycle.py's day-3 email so
    # the two sequences cannot tell people different things about the same
    # request. Phrased for a tenant of record: DHCR sends a unit's rent history
    # to the tenant who rents it, not to whoever asks about it.
    dhcr_steps = {"type": "steps", "items": [
        "Email rentinfo@hcr.ny.gov, or call (718) 739-6400.",
        "Ask for the FULL registration history, not just the current year.",
        "Compare it to the rent you pay or were quoted — big unexplained jumps "
        "between tenants are the classic overcharge pattern.",
    ]}

    if not bbl:
        # We could not name a building we can stand behind, so we name none and
        # ask for nothing. An email that says "your saved building" while
        # knowing nothing about it is the kind of thing this site does not send.
        subject = "The free step that settles whether an apartment is stabilized"
        html, text = emailkit.render(
            title="What the map can't tell you",
            intro=f"You've saved {n} building{'s' if n != 1 else ''} on Find A Crib. "
                  f"Here's the part the map deliberately doesn't claim to know.",
            blocks=[
                {"type": "paragraph",
                 "text": "A building being registered rent-stabilized doesn't guarantee a "
                         "particular apartment in it is — a registered building can hold "
                         "deregulated units, and the map cannot see inside one. The DHCR "
                         "rent history for the specific apartment is the only thing that "
                         "settles it, and if you rent there it's free to request."},
                dhcr_steps,
                {"type": "card",
                 "heading": "Meanwhile, we'll watch the buildings you saved",
                 "body": "When an apartment in one of them is advertised — including "
                         "listings that explicitly accept housing vouchers — you get an "
                         "email that night.",
                 "link": ("Open the map", f"{SITE}/")},
            ],
            footer_note=FOOTER_NOTE, unsub_url=_unsub(row["token"]),
            unsub_label="Stop these emails")
        return subject, html, text

    subject = f"What the map can't tell you about {addr}"
    html, text = emailkit.render(
        title=f"What we can't tell you about {addr}",
        intro="You saved it, so here's the honest limit of what's on the page — and the "
              "free way past it.",
        blocks=[
            {"type": "paragraph",
             "text": f"We can tell you {addr} is registered rent-stabilized with DHCR. We "
                     f"cannot tell you whether a particular apartment in it is: a "
                     f"registered building can hold deregulated units, and we cannot see "
                     f"inside one. The DHCR rent history for that apartment settles both "
                     f"that and the legal rent — and if you rent there, it's free and "
                     f"it's yours to ask for."},
            dhcr_steps,
            {"type": "paragraph",
             "text": "If you're still looking rather than already living there, DHCR won't "
                     "send you a history for someone else's apartment. What you can check "
                     "before signing is the building itself: who owns it, what else they "
                     "own, and how its violation record compares with the rest of the "
                     "stabilized stock."},
            {"type": "card",
             "heading": "Full building report — $9",
             "body": REPORT_PROMISE,
             "link": (f"Get the report for {addr}", f"{SITE}/#d={bbl}")},
            {"type": "note",
             "text": "To be clear about what you'd be buying: the report does not contain "
                     "the DHCR rent history. DHCR sends that, free, to the apartment's "
                     "tenant — the report just arrives with the request already filled in."},
        ],
        footer_note=FOOTER_NOTE, unsub_url=_unsub(row["token"]),
        unsub_label="Stop these emails")
    return subject, html, text


BUILDERS = {"welcome": welcome, "activate": activate, "lapsed": lapsed, "saved": saved}


# --------------------------------------------------------------------- due

def _step_for(row, now):
    """Which step, if any, this account is due. One per run, never a burst."""
    sent = set(row.get("sent_steps") or [])
    days = row.get("days_old") or 0
    saves = row.get("save_count") or 0
    last_seen = _parse_ts(row.get("last_seen"))

    quiet = last_seen is None or (now - last_seen).days >= LAPSED_QUIET_DAYS

    if "welcome" not in sent and days <= 1:
        return "welcome"
    if "activate" not in sent and days >= 3 and saves == 0:
        return "activate"
    if "lapsed" not in sent and days >= 21 and quiet:
        return "lapsed"
    # `saved` requires the opposite of `lapsed`'s quiet test, so no account can
    # ever be due both, and the ordering between them cannot matter. An account
    # with no last_seen at all reads as quiet and is never asked for money.
    if "saved" not in sent and days >= SAVED_MIN_DAYS and saves >= 1 and not quiet:
        return "saved"
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

    if any(step == "saved" for _, step in out):
        ctx = saved_context()
        for r, step in out:
            if step != "saved":
                continue
            s = ctx.get(str(r.get("user_id"))) or {}
            r["saved_bbls"] = s.get("bbls") or []
            r["home_bbl"] = s.get("home_bbl")
        try:
            buyers = report_buyer_emails()
        except Exception as e:
            # Held, not guessed, and not silent: the alternative is asking a
            # paying customer to buy the thing they already own.
            print(f"  could not read report buyers ({e}) — holding the saved step, still due tomorrow")
            out = [(r, s) for r, s in out if s != "saved"]
        else:
            kept = []
            for r, s in out:
                if s == "saved" and str(r.get("email") or "").strip().lower() in buyers:
                    print(f"  saved -> {r.get('email')}: already bought a report, skipped for good")
                    continue
                kept.append((r, s))
            out = kept
    return out


def run(dry_run=False, now=None, voucher_buildings=None, buildings_by_bbl=None):
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

    ctx = {"voucher_buildings": voucher_buildings,
           "buildings": buildings_by_bbl or {}}
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
    # Per-step series, so a later review can ask "how many times was the paid
    # ask actually made?" instead of inferring it from a total that four
    # different emails contribute to. Zeros are recorded deliberately: a step
    # that is due nobody and a step that is broken look identical otherwise.
    for step in STEPS:
        ledger.record_result(ledger.today(), "account_lifecycle",
                             f"sent_{step}", by_step.get(step, 0))
    return {"ok": not failed, "sent": len(sent), "by_step": by_step,
            "failed": failed, "detail": detail}
