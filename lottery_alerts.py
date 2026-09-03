#!/usr/bin/env python3
"""Email subscribers the minute a new housing lottery or re-rental opens in
their borough.

Sign-ups come from /alerts/ (findacrib-api writes lottery_alert_subs). This
runs every 10 minutes on the droplet (lottery_alerts.sh, /etc/cron.d/
rentmap-alerts) and reads the three feeds the site already builds:

  housing_connect.json  NYC Housing Connect lotteries (HPD's public API — the
                        wrapper refreshes it right before this runs, so a
                        lottery that opened at 9:04 is mailed by 9:10)
  hcr.json              HousingSearch.ny.gov lotteries + Mitchell-Lama
                        waitlists (scrape_hcr.py --incremental, hourly)
  rerental_new.json     what rerental_daily.py found new on the HPD marketing
                        agents' re-rental boards (swept every 2 hours by day)

Anything not in lottery_alerts_state.json is new. No state file = seed only,
send nothing — the first run must not announce every open lottery in the
city as "just opened". A feed that is missing or unreadable is skipped and its
seen-set is left alone, so a bad morning does not re-announce it all later.

One email per subscriber per run, however many items there are, and the run
itself is capped (MAX_SENDS_PER_RUN, HOURLY_CAP) under the mailbox's 500/hour
domain ceiling at Namecheap. A subscriber gets at most DAILY_PER_SUB emails a
day.

    python3 lottery_alerts.py               # normal run
    python3 lottery_alerts.py --dry-run     # print who would get what
    python3 lottery_alerts.py --seed        # (re)build state, send nothing
    python3 lottery_alerts.py --test-email you@x.com
                                            # one sample from today's feeds
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA_DIR = os.environ.get("GROWTH_DOCROOT") or os.environ.get("DATA_DIR") or HERE
STATE = os.path.join(HERE, "lottery_alerts_state.json")
SITE = "https://findacrib.com"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dbaifotzwlxjvsxjohjt.supabase.co")

MAX_ITEMS_PER_EMAIL = 12
MAX_SENDS_PER_RUN = 300
HOURLY_CAP = 400          # Namecheap Private Email: 500/hour per domain (Starter)
DAILY_PER_SUB = 6
SEEN_TTL_DAYS = 240

BORO_CODE = {"manhattan": "M", "brooklyn": "Bk", "queens": "Q", "bronx": "Bx",
             "the bronx": "Bx", "staten island": "SI", "new york": "M"}
BORO_NAME = {"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens", "Bx": "the Bronx",
             "SI": "Staten Island"}
ALL_BOROS = set(BORO_NAME)


def boro_code(name):
    if not name:
        return None
    n = str(name).strip().lower()
    if n in BORO_CODE:
        return BORO_CODE[n]
    if n in BORO_NAME:
        return n
    for k, v in BORO_CODE.items():
        if k in n:
            return v
    return None


def money(v):
    try:
        return f"${int(v):,}"
    except (TypeError, ValueError):
        return None


def load_json(name):
    for base in (DATA_DIR, HERE):
        p = os.path.join(base, name)
        try:
            with open(p) as f:
                return json.load(f)
        except (FileNotFoundError, ValueError, OSError):
            continue
    return None


# ------------------------------------------------------------------ items
# Every item: id, kind ('lottery' | 'rerental'), boro (code or None), text,
# sub, url. `text`/`sub`/`url` are exactly what the email row shows.

def hc_items(d):
    out = []
    for l in (d or {}).get("lotteries") or []:
        if not l.get("id"):
            continue
        rent = None
        if l.get("rent_low") and l.get("rent_high") and l["rent_low"] != l["rent_high"]:
            rent = f"{money(l['rent_low'])}–{money(l['rent_high'])}/mo"
        elif l.get("rent_low"):
            rent = f"{money(l['rent_low'])}/mo"
        bits = [b for b in (
            " · ".join(x for x in (l.get("neighborhood"), l.get("borough")) if x),
            rent, " / ".join(l.get("beds") or []),
            (f"closes {l['closes']}" if l.get("closes") else None)) if b]
        out.append({"id": f"hc:{l['id']}", "kind": "lottery",
                    "boro": boro_code(l.get("borough")),
                    "label": "Housing Connect lottery",
                    "text": l.get("name") or l.get("address") or "Housing Connect lottery",
                    "sub": " · ".join(bits), "url": l.get("href")})
    return out


def hcr_items(d):
    out = []
    for l in (d or {}).get("listings") or []:
        if not l.get("id") or str(l.get("status", "")).lower() != "open":
            continue
        if str(l.get("ptype") or "Rental").lower() != "rental":
            continue
        kind = l.get("kind") or "Lottery"
        inc = None
        if l.get("min_income") and l.get("max_income"):
            inc = f"income {money(l['min_income'])}–{money(l['max_income'])}"
        street = ((l.get("buildings") or [{}])[0].get("street"))
        bits = [b for b in (
            " · ".join(x for x in (street, BORO_NAME.get(l.get("boro"), "").replace("the ", "")) if x),
            kind if kind.lower() != "lottery" else None, inc,
            (f"due {l['due']}" if l.get("due") else None)) if b]
        out.append({"id": f"hcr:{l['id']}", "kind": "lottery", "boro": l.get("boro"),
                    "label": ("Mitchell-Lama waitlist" if "mitchell" in kind.lower()
                              else "waitlist" if "wait" in kind.lower()
                              else "HCR lottery"),
                    "text": l.get("name") or "HCR listing",
                    "sub": " · ".join(bits), "url": l.get("url")})
    return out


def rerental_items(d):
    out = []
    for e in (d or {}).get("items") or []:
        if not e.get("key") or not e.get("agent"):
            continue
        bits = [b for b in (
            " · ".join(x for x in (e.get("hood"), e.get("boro")) if x),
            f"listed by {e['agent']}") if b]
        out.append({"id": f"rr:{e['agent']}|{e['key']}", "kind": "rerental",
                    "boro": boro_code(e.get("boro")), "label": "re-rental",
                    "text": e.get("label") or e["key"],
                    "sub": " · ".join(bits),
                    "url": e.get("url") or f"{SITE}/marketing-agents/"})
    return out


def gather():
    """{source: [items] or None}. None = feed unreadable, leave its seen-set."""
    hc = load_json("housing_connect.json")
    hcr = load_json("hcr.json")
    rr = load_json("rerental_new.json")
    return {"hc": hc_items(hc) if hc is not None else None,
            "hcr": hcr_items(hcr) if hcr is not None else None,
            "rr": rerental_items(rr) if rr is not None else None}


# ------------------------------------------------------------------ state

def load_state():
    try:
        return json.load(open(STATE))
    except (FileNotFoundError, ValueError):
        return None


def save_state(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"), indent=0)
    os.replace(tmp, STATE)


def prune(st, now):
    cutoff = (now - datetime.timedelta(days=SEEN_TTL_DAYS)).isoformat()
    st["seen"] = {k: v for k, v in st["seen"].items() if v >= cutoff}
    hour_ago = (now - datetime.timedelta(hours=1)).isoformat()
    st["sends"] = [t for t in st.get("sends", []) if t >= hour_ago]
    today = now.date().isoformat()
    st["per_sub"] = {k: v for k, v in st.get("per_sub", {}).items() if k.endswith(today)}


# ------------------------------------------------------------------ supabase

def rpc(name, body, key):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/{name}", data=json.dumps(body).encode(),
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "User-Agent": "fac-lottery-alerts"},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


# ------------------------------------------------------------------ email

def unsub_urls(token):
    return (f"{SITE}/alerts/#unsub={token}",
            f"{SITE}/api/alerts/unsubscribe?t={token}")


def boro_phrase(codes):
    names = [BORO_NAME[c] for c in ("M", "Bk", "Q", "Bx", "SI") if c in codes]
    if len(names) == 5:
        return "all five boroughs"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def render_alert(items, sub, emailkit):
    lot = [i for i in items if i["kind"] == "lottery"]
    rr = [i for i in items if i["kind"] == "rerental"]
    shown = items[:MAX_ITEMS_PER_EMAIL]
    more = len(items) - len(shown)
    where = boro_phrase(sub["boroughs"])

    if len(items) == 1:
        it = items[0]
        subject = (f"New {it['label']} in {BORO_NAME.get(it['boro'], 'NYC')}: {it['text']}"
                   if it["kind"] == "lottery" else
                   f"New re-rental in {BORO_NAME.get(it['boro'], 'NYC')}: {it['text']}")
    else:
        parts = []
        if lot:
            parts.append(f"{len(lot)} new lotter{'y' if len(lot) == 1 else 'ies'}")
        if rr:
            parts.append(f"{len(rr)} new re-rental{'' if len(rr) == 1 else 's'}")
        subject = " and ".join(parts) + f" in {where}"

    blocks = []

    def rows(group):
        return [{"text": i["text"], "sub": i["sub"], "url": i["url"]} for i in group]
    lot_shown = [i for i in shown if i["kind"] == "lottery"]
    rr_shown = [i for i in shown if i["kind"] == "rerental"]
    if lot_shown:
        blocks.append({"type": "callout", "tone": "good",
                       "heading": f"{len(lot)} new lotter{'y' if len(lot) == 1 else 'ies'} — apply by the deadline",
                       "items": rows(lot_shown)})
    if rr_shown:
        blocks.append({"type": "callout", "tone": "info",
                       "heading": f"{len(rr)} new re-rental{'' if len(rr) == 1 else 's'} — usually first-come, first-served",
                       "items": rows(rr_shown)})
    if more > 0:
        blocks.append({"type": "note", "text": f"…and {more} more. Everything open is on the map."})
    blocks.append({"type": "note",
                   "text": "A lottery is applied for on Housing Connect (or HCR) by a "
                           "deadline and picked by log number. A re-rental is a vacated "
                           "affordable apartment the agent rents directly, often to the "
                           "first eligible applicant — open it now, not later. Details "
                           "come from each source's own page; always check there before "
                           "acting."})
    page_unsub, post_unsub = unsub_urls(sub["token"])
    html, text = emailkit.render(
        title=subject, eyebrow="Borough alert",
        intro=f"You asked to hear the minute something opens in {where}.",
        blocks=blocks,
        cta=("See every open lottery and re-rental", f"{SITE}/?src=alert"),
        footer_note=f"You are subscribed at {sub['email']} for {where}. "
                    f"Change boroughs at {SITE}/alerts/.",
        unsub_url=page_unsub)
    return subject, html, text, post_unsub


def render_welcome(sub, emailkit):
    where = boro_phrase(sub["boroughs"])
    kinds = sub["kinds"]
    what = " or ".join(w for w, k in (("housing lottery or waitlist", "lottery"),
                                      ("re-rental", "rerental")) if k in kinds) \
        or "housing lottery or re-rental"
    blocks = [
        {"type": "card", "heading": "What you'll get",
         "body": f"One email the minute a new {what} "
                 f"opens in {where}. The feeds are checked every 10 minutes: NYC Housing "
                 "Connect, HCR's HousingSearch (lotteries and Mitchell-Lama waitlists) and the "
                 "re-rental boards of the HPD-approved marketing agents."},
        {"type": "card", "heading": "Why re-rentals matter",
         "body": "When a tenant leaves an affordable apartment it usually does not go back "
                 "into a lottery — the agent re-rents it from their own site, often "
                 "first-come, first-served. Far fewer people know to look there.",
         "link": ("See the agents' boards", f"{SITE}/marketing-agents/")},
    ]
    page_unsub, post_unsub = unsub_urls(sub["token"])
    html, text = emailkit.render(
        title=f"You're on the list for {where}",
        intro="Quiet until something opens. No digests, no weekly round-ups.",
        blocks=blocks,
        cta=("Open the map", f"{SITE}/?src=alert"),
        footer_note=f"Subscribed at {sub['email']}. Change boroughs any time at {SITE}/alerts/.",
        unsub_url=page_unsub)
    return f"Find A Crib alerts: {where}", html, text, post_unsub


def wants(sub, item):
    if item["kind"] not in sub["kinds"]:
        return False
    if item["boro"] is None:
        # Unplaced listing: only someone watching the whole city should hear
        # about it — a guess at a borough is worse than a skipped email.
        return set(sub["boroughs"]) >= ALL_BOROS
    return item["boro"] in sub["boroughs"]


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true", help="rebuild state, send nothing")
    ap.add_argument("--test-email", help="send one sample built from today's feeds")
    ap.add_argument("--welcome", action="store_true",
                    help="only send welcome emails to new sign-ups")
    args = ap.parse_args()
    if args.welcome:
        return welcome(args.dry_run)

    now = datetime.datetime.now(datetime.timezone.utc)
    feeds = gather()
    for src, items in feeds.items():
        print(f"{src}: {'unreadable' if items is None else str(len(items)) + ' items'}")

    from growth import emailkit

    if args.test_email:
        items = [i for src in ("hc", "hcr", "rr") for i in (feeds[src] or [])][:6]
        if not items:
            sys.exit("no items in any feed to build a sample from")
        sub = {"email": args.test_email, "boroughs": ["M", "Bk", "Q", "Bx", "SI"],
               "kinds": ["lottery", "rerental"], "token": "00000000-0000-0000-0000-000000000000"}
        subject, html, text, post_unsub = render_alert(items, sub, emailkit)
        emailkit.send(args.test_email, "[TEST] " + subject, html, text, unsub_url=post_unsub)
        print(f"sent sample ({len(items)} items) to {args.test_email}")
        return

    st = load_state()
    first = st is None
    if first:
        st = {"seen": {}, "sends": [], "per_sub": {}}
    st.setdefault("seen", {}); st.setdefault("sends", []); st.setdefault("per_sub", {})
    prune(st, now)

    new = []
    stamp = now.isoformat()
    for src, items in feeds.items():
        if items is None:
            continue
        ids = {i["id"] for i in items}
        # Items that left a feed (a lottery closed, an HCR waitlist closed) are
        # forgotten, so a re-opening of the same record alerts again.
        for k in [k for k in st["seen"] if k.startswith(src + ":") and k not in ids]:
            st["seen"].pop(k)
        for i in items:
            if i["id"] not in st["seen"]:
                st["seen"][i["id"]] = stamp
                new.append(i)

    if first or args.seed:
        print(f"seeded {len(st['seen'])} items — nothing sent")
        if not args.dry_run:
            save_state(st)
        return
    if not new:
        print("nothing new")
        if not args.dry_run:
            save_state(st)
        return
    print(f"{len(new)} new:")
    for i in new:
        print(f"  {i['kind']:8s} {i['boro'] or '??':3s} {i['text'][:60]}")

    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        sys.exit("SUPABASE_SERVICE_KEY not set (growth.env)")
    try:
        subs = rpc("lottery_alerts_recipients", {}, key) or []
    except urllib.error.URLError as e:
        # Do NOT save state: the items stay "new" for the next run, which is
        # what "the minute it opens" has to mean when the subscriber list is
        # briefly unreachable.
        sys.exit(f"could not load subscribers: {e}")
    print(f"{len(subs)} active subscribers")

    sent_ids, welcomed_ids = [], []
    sent = 0
    for sub in subs:
        sub["boroughs"] = list(sub.get("boroughs") or [])
        sub["kinds"] = list(sub.get("kinds") or ["lottery", "rerental"])
        mine = [i for i in new if wants(sub, i)]
        if not mine:
            continue
        day_key = f"{sub['id']}:{now.date().isoformat()}"
        if st["per_sub"].get(day_key, 0) >= DAILY_PER_SUB:
            print(f"  skip {sub['email']}: daily cap")
            continue
        if sent >= MAX_SENDS_PER_RUN or len(st["sends"]) >= HOURLY_CAP:
            print("  send budget exhausted — remaining subscribers wait for the next run")
            # Leave the unsent items out of state so they go out next run.
            for i in mine:
                st["seen"].pop(i["id"], None)
            continue
        subject, html, text, post_unsub = render_alert(mine, sub, emailkit)
        print(f"  -> {sub['email']}: {subject}")
        if args.dry_run:
            continue
        try:
            emailkit.send(sub["email"], subject, html, text, unsub_url=post_unsub)
        except Exception as e:
            print(f"     FAILED {type(e).__name__}: {str(e)[:80]}")
            continue
        sent += 1
        st["sends"].append(now.isoformat())
        st["per_sub"][day_key] = st["per_sub"].get(day_key, 0) + 1
        sent_ids.append(sub["id"])

    if not args.dry_run:
        save_state(st)
        if sent_ids or welcomed_ids:
            try:
                rpc("lottery_alerts_mark", {"p_sent": sent_ids, "p_welcomed": welcomed_ids}, key)
            except Exception as e:
                print(f"mark failed: {e}")
    print(f"sent {sent}")


def welcome(args_dry=False):
    """Welcome anyone who signed up since the last run. Separate entry point
    so the wrapper can call it even when the feeds have nothing new."""
    from growth import emailkit
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        sys.exit("SUPABASE_SERVICE_KEY not set (growth.env)")
    subs = rpc("lottery_alerts_recipients", {}, key) or []
    todo = [s for s in subs if not s.get("welcomed_at")][:50]
    done = []
    for sub in todo:
        sub["boroughs"] = list(sub.get("boroughs") or [])
        sub["kinds"] = list(sub.get("kinds") or ["lottery", "rerental"])
        subject, html, text, post_unsub = render_welcome(sub, emailkit)
        print(f"welcome -> {sub['email']}")
        if args_dry:
            continue
        try:
            emailkit.send(sub["email"], subject, html, text, unsub_url=post_unsub)
            done.append(sub["id"])
        except Exception as e:
            print(f"   FAILED {type(e).__name__}: {str(e)[:80]}")
    if done:
        rpc("lottery_alerts_mark", {"p_sent": [], "p_welcomed": done}, key)
    print(f"welcomed {len(done)}")


if __name__ == "__main__":
    main()
