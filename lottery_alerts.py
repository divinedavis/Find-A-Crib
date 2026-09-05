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
domain ceiling at Namecheap.

Nobody gets more than ONE Find A Crib email a day, from any job (owner rule,
2026-09-05; growth/mailcap.py is the shared ledger). The first new item of
the day goes out the minute it appears; anything after that is HELD per
subscriber (state["held"]) and rides the next day's first email, so nothing
is dropped and nothing arrives twice.

Two more entry points share the list, the sender and the opt-out:

  --nudge    first-week round-up. A subscriber who signed up 2–8 days ago and
             has had nothing but the welcome gets "open right now in your
             boroughs" once, so the first week is never silent.
  --weekly   fixed-day digest (Tuesday mornings, deploy/cron-rentmap-alerts):
             what opened this week in their boroughs and what closes in the
             next seven days. Its own opt-out (digest_off) so stopping it
             never stops the alerts.

    python3 lottery_alerts.py               # normal run
    python3 lottery_alerts.py --dry-run     # print who would get what
    python3 lottery_alerts.py --seed        # (re)build state, send nothing
    python3 lottery_alerts.py --test-email you@x.com
                                            # one sample from today's feeds
    python3 lottery_alerts.py --nudge [--dry-run]
    python3 lottery_alerts.py --weekly [--dry-run] [--test-email you@x.com]
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
SEEN_TTL_DAYS = 240
HELD_MAX = 30             # per subscriber; older held items fall off the front
NUDGE_MIN_DAYS, NUDGE_MAX_DAYS = 2, 8
WEEK_DAYS = 7

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


def iso_date(v):
    """'2026-09-08' or '9/7/2026' -> '2026-09-08'; anything else -> None."""
    if not v:
        return None
    v = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.datetime.strptime(v[:10] if fmt == "%Y-%m-%d" else v, fmt).date().isoformat()
        except ValueError:
            continue
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
                    "sub": " · ".join(bits), "url": l.get("href"),
                    "closes": iso_date(l.get("closes")),
                    "rent_low": l.get("rent_low"),
                    "income_min": l.get("income_min"), "income_max": l.get("income_max")})
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
                    "sub": " · ".join(bits), "url": l.get("url"),
                    "closes": iso_date(l.get("due")),
                    "rent_low": None,
                    "income_min": l.get("min_income"), "income_max": l.get("max_income")})
    return out


def rerental_items(d):
    out = []
    for e in (d or {}).get("items") or []:
        if not e.get("key") or not e.get("agent"):
            continue
        rent = money(e["rent_low"]) + "/mo" if e.get("rent_low") else None
        bits = [b for b in (
            " · ".join(x for x in (e.get("hood"), e.get("boro")) if x),
            rent, f"listed by {e['agent']}") if b]
        out.append({"id": f"rr:{e['agent']}|{e['key']}", "kind": "rerental",
                    "boro": boro_code(e.get("boro")), "label": "re-rental",
                    "text": e.get("label") or e["key"],
                    "sub": " · ".join(bits),
                    "url": e.get("url") or f"{SITE}/marketing-agents/",
                    "rent_low": e.get("rent_low"),
                    "income_min": None, "income_max": e.get("income_max")})
    return out


BBL_BORO = {"1": "M", "2": "Bx", "3": "Bk", "4": "Q", "5": "SI"}


def voucher_items(d):
    """s8.json `avail`: one entry per building where a landlord is currently
    soliciting Section 8 / voucher tenants on AffordableHousing.com. The
    borough is the BBL's first digit; the address comes from the listing URL's
    slug ("/140-w-133rd-st-1029236/") so the dispatcher need not load the
    17MB building file every ten minutes."""
    out = []
    for bbl, e in ((d or {}).get("avail") or {}).items():
        if not isinstance(e, dict) or not str(bbl).isdigit():
            continue
        url = e.get("url") or f"{SITE}/?s8=1"
        slug = url.rstrip("/").split("/")[-1]
        words = [w for w in slug.split("-") if not w.isdigit() or slug.startswith(w + "-")]
        addr = " ".join(w.upper() if w in ("w", "e", "n", "s", "ne", "nw", "se", "sw") else w.capitalize()
                        for w in words) or "Voucher listing"
        n = e.get("n") or 1
        rent = money(e["p"]) + "/mo" if e.get("p") else None
        boro = BBL_BORO.get(str(bbl)[0])
        bits = [b for b in (BORO_NAME.get(boro, "").replace("the ", ""), rent,
                            f"{n} unit{'' if n == 1 else 's'}", "on AffordableHousing.com") if b]
        out.append({"id": f"s8:{bbl}", "kind": "voucher", "boro": boro,
                    "label": "voucher listing", "text": addr,
                    "sub": " · ".join(bits), "url": url,
                    "rent_low": e.get("p"), "income_min": None, "income_max": None})
    return out


def gather():
    """{source: [items] or None}. None = feed unreadable, leave its seen-set."""
    hc = load_json("housing_connect.json")
    hcr = load_json("hcr.json")
    rr = load_json("rerental_new.json")
    s8 = load_json("s8.json")
    return {"hc": hc_items(hc) if hc is not None else None,
            "hcr": hcr_items(hcr) if hcr is not None else None,
            "rr": rerental_items(rr) if rr is not None else None,
            "s8": voucher_items(s8) if s8 is not None else None}


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
    st.pop("per_sub", None)          # pre-ledger daily counter, superseded
    st.setdefault("held", {})


def prune_held(st, feeds):
    """Drop held items whose record has left its feed (a lottery that closed
    while it waited is not news). A feed that was unreadable this run keeps
    its held items — absence of data is not absence of the listing."""
    live, readable = set(), set()
    for src, items in feeds.items():
        if items is None:
            continue
        readable.add(src)
        live.update(i["id"] for i in items)
    for sid, items in list(st.get("held", {}).items()):
        keep = [i for i in items if i["id"] in live or i["id"].split(":", 1)[0] not in readable]
        if keep:
            st["held"][sid] = keep[-HELD_MAX:]
        else:
            st["held"].pop(sid, None)


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


def filter_words(sub):
    bits = []
    if sub.get("max_rent"):
        bits.append(f"rent up to {money(sub['max_rent'])}/mo")
    if sub.get("income"):
        bits.append(f"household income {money(sub['income'])}/yr")
    return (", " + ", ".join(bits)) if bits else ""


def render_alert(items, sub, emailkit):
    lot = [i for i in items if i["kind"] == "lottery"]
    rr = [i for i in items if i["kind"] == "rerental"]
    vo = [i for i in items if i["kind"] == "voucher"]
    shown = items[:MAX_ITEMS_PER_EMAIL]
    more = len(items) - len(shown)
    where = boro_phrase(sub["boroughs"])

    if len(items) == 1:
        it = items[0]
        subject = (f"New {it['label']} in {BORO_NAME.get(it['boro'], 'NYC')}: {it['text']}"
                   if it["kind"] == "lottery" else
                   f"New voucher listing in {BORO_NAME.get(it['boro'], 'NYC')}: {it['text']}"
                   if it["kind"] == "voucher" else
                   f"New re-rental in {BORO_NAME.get(it['boro'], 'NYC')}: {it['text']}")
    else:
        parts = []
        if lot:
            parts.append(f"{len(lot)} new lotter{'y' if len(lot) == 1 else 'ies'}")
        if rr:
            parts.append(f"{len(rr)} new re-rental{'' if len(rr) == 1 else 's'}")
        if vo:
            parts.append(f"{len(vo)} new voucher listing{'' if len(vo) == 1 else 's'}")
        subject = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + f" in {where}"

    blocks = []

    def rows(group):
        return [{"text": i["text"], "sub": i["sub"], "url": i["url"]} for i in group]
    lot_shown = [i for i in shown if i["kind"] == "lottery"]
    rr_shown = [i for i in shown if i["kind"] == "rerental"]
    vo_shown = [i for i in shown if i["kind"] == "voucher"]
    if lot_shown:
        blocks.append({"type": "callout", "tone": "good",
                       "heading": f"{len(lot)} new lotter{'y' if len(lot) == 1 else 'ies'} — apply by the deadline",
                       "items": rows(lot_shown)})
    if rr_shown:
        blocks.append({"type": "callout", "tone": "info",
                       "heading": f"{len(rr)} new re-rental{'' if len(rr) == 1 else 's'} — usually first-come, first-served",
                       "items": rows(rr_shown)})
    if vo_shown:
        blocks.append({"type": "callout", "tone": "info",
                       "heading": f"{len(vo)} landlord{'' if len(vo) == 1 else 's'} now accepting vouchers — first come, first served",
                       "items": rows(vo_shown)})
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
        footer_note=f"You are subscribed at {sub['email']} for {where}{filter_words(sub)}. "
                    f"Change boroughs or filters at {SITE}/alerts/. Never more than one email a day.",
        unsub_url=page_unsub)
    return subject, html, text, post_unsub


def render_welcome(sub, emailkit):
    where = boro_phrase(sub["boroughs"])
    kinds = sub["kinds"]
    names = [n for k, n in (("lottery", "housing lottery or waitlist"), ("rerental", "re-rental"),
                            ("voucher", "voucher-friendly listing")) if k in kinds] or ["housing lottery, waitlist or re-rental"]
    what = ", ".join(names[:-1]) + (" or " if len(names) > 1 else "") + names[-1]
    blocks = [
        {"type": "card", "heading": "What you'll get",
         "body": f"One email the minute a new {what} "
                 f"opens in {where}"
                 + (" that fits your rent cap or income" if (sub.get("max_rent") or sub.get("income")) else "")
                 + ". The feeds are checked every 10 minutes: NYC Housing "
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
        intro="Quiet until something opens — and never more than one email a day. "
              "A short Tuesday round-up of the week, which you can switch off on its own.",
        blocks=blocks,
        cta=("Open the map", f"{SITE}/?src=alert"),
        footer_note=f"Subscribed at {sub['email']} for {where}{filter_words(sub)}. "
                    f"Change boroughs or filters any time at {SITE}/alerts/.",
        unsub_url=page_unsub)
    return f"Find A Crib alerts: {where}", html, text, post_unsub


def digest_off_urls(token):
    return (f"{SITE}/alerts/#digestoff={token}",
            f"{SITE}/api/alerts/digest-off?t={token}")


def sort_for_reading(items):
    """Lotteries first, soonest deadline first; then re-rentals and voucher
    listings in feed order. Undated lotteries sink below dated ones."""
    def key(i):
        rank = {"lottery": 0, "rerental": 1, "voucher": 2}.get(i["kind"], 3)
        return (rank, i.get("closes") or "9999-99-99")
    return sorted(items, key=key)


def render_roundup(sub, emailkit, *, eyebrow, title, intro, sections, cta_label,
                   footer_extra="", digest=False):
    """One email built from named groups of items. `sections` is a list of
    (heading, tone, items); empty groups are skipped."""
    blocks = []
    shown = 0
    for heading, tone, items in sections:
        if not items:
            continue
        room = max(0, MAX_ITEMS_PER_EMAIL - shown)
        part = items[:room]
        shown += len(part)
        if not part:
            continue
        blocks.append({"type": "callout", "tone": tone, "heading": heading,
                       "items": [{"text": i["text"], "sub": i["sub"], "url": i["url"]} for i in part]})
        if len(items) > len(part):
            blocks.append({"type": "note", "text": f"…and {len(items) - len(part)} more on the map."})
    blocks.append({"type": "note",
                   "text": "A lottery is applied for on Housing Connect (or HCR) by a deadline "
                           "and picked by log number. A re-rental is a vacated affordable "
                           "apartment the agent rents directly, often to the first eligible "
                           "applicant. Details come from each source's own page; always check "
                           "there before acting."})
    where = boro_phrase(sub["boroughs"])
    page_unsub, post_unsub = unsub_urls(sub["token"])
    if digest:
        page_off, _ = digest_off_urls(sub["token"])
        blocks.append({"type": "note",
                       "text": f"Don't want the Tuesday round-up? Stop just the round-up here: {page_off} "
                               "— your the-minute-it-opens alerts keep working."})
    html, text = emailkit.render(
        title=title, eyebrow=eyebrow, intro=intro, blocks=blocks,
        cta=(cta_label, f"{SITE}/?src={'digest' if digest else 'nudge'}"),
        footer_note=f"You are subscribed at {sub['email']} for {where}{filter_words(sub)}. "
                    f"{footer_extra}Change boroughs or filters at {SITE}/alerts/. "
                    "Never more than one email a day.",
        unsub_url=page_unsub)
    return html, text, post_unsub


def subscriber_rows(key):
    subs = rpc("lottery_alerts_recipients", {}, key) or []
    for sub in subs:
        sub["boroughs"] = list(sub.get("boroughs") or [])
        sub["kinds"] = list(sub.get("kinds") or ["lottery", "rerental"])
    return subs


def parse_ts(v):
    if not v:
        return None
    t = str(v).strip().replace(" ", "T").replace("Z", "+00:00")
    if len(t) >= 3 and t[-3] in "+-":
        t += ":00"
    try:
        d = datetime.datetime.fromisoformat(t.split(".")[0] + t[-6:] if "." in t else t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def nudge(args_dry=False):
    """First-week round-up: one email to a subscriber who has had only the
    welcome, 2–8 days in, listing what is open in their boroughs right now.
    The point is that the first week is never silent. Sent once, ever."""
    from growth import emailkit, mailcap
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        sys.exit("SUPABASE_SERVICE_KEY not set (growth.env)")
    now = datetime.datetime.now(datetime.timezone.utc)
    feeds = gather()
    everything = [i for src in ("hc", "hcr", "rr", "s8") for i in (feeds[src] or [])]
    sent_ids, nudged_ids = [], []
    for sub in subscriber_rows(key):
        if sub.get("nudged_at") or not sub.get("welcomed_at") or (sub.get("sent_count") or 0) > 0:
            continue
        created = parse_ts(sub.get("created_at"))
        if not created:
            continue
        age = (now - created).days
        if age < NUDGE_MIN_DAYS or age > NUDGE_MAX_DAYS:
            continue
        mine = sort_for_reading([i for i in everything if wants(sub, i)])
        if not mine:
            nudged_ids.append(sub["id"])       # nothing to say; don't keep looking
            print(f"nudge -> {sub['email']}: nothing open that fits — marked, no email")
            continue
        lot = [i for i in mine if i["kind"] == "lottery"]
        rr = [i for i in mine if i["kind"] == "rerental"]
        vo = [i for i in mine if i["kind"] == "voucher"]
        where = boro_phrase(sub["boroughs"])
        parts = [f"{len(g)} {n}{'' if len(g) == 1 else 's'}" for g, n in
                 ((lot, "lottery"), (rr, "re-rental"), (vo, "voucher listing")) if g]
        parts = [p.replace("lotterys", "lotteries") for p in parts]
        subject = f"Open right now in {where}: " + ", ".join(parts)
        html, text, post_unsub = render_roundup(
            sub, emailkit, eyebrow="Since you signed up", title=subject,
            intro="You joined a few days ago and nothing new has opened yet — but this is "
                  "what is open today. Deadlines first.",
            sections=[("Lotteries open now — soonest deadline first", "good", lot),
                      ("Re-rentals listed now — usually first-come, first-served", "info", rr),
                      ("Landlords accepting vouchers now", "info", vo)],
            cta_label="See all of it on the map")
        print(f"nudge -> {sub['email']}: {subject}")
        if args_dry:
            continue
        try:
            if not mailcap.claim(sub["email"], "nudge"):
                print("   already emailed today — try tomorrow")
                continue
            emailkit.send(sub["email"], subject, html, text, unsub_url=post_unsub)
        except Exception as e:
            print(f"   FAILED {type(e).__name__}: {str(e)[:80]}")
            mailcap.release(sub["email"])
            continue
        sent_ids.append(sub["id"]); nudged_ids.append(sub["id"])
    if not args_dry and (sent_ids or nudged_ids):
        rpc("lottery_alerts_mark", {"p_sent": sent_ids, "p_welcomed": [], "p_nudged": nudged_ids}, key)
    print(f"nudged {len(sent_ids)}")


def weekly(args_dry=False, test_email=None):
    """The Tuesday digest: what opened in the last seven days in the
    subscriber's boroughs (first-seen stamps in the state file) and what closes
    in the next seven. Skipped for anyone with nothing in either list, and for
    anyone who already had today's one email."""
    from growth import emailkit, mailcap
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key and not test_email:
        sys.exit("SUPABASE_SERVICE_KEY not set (growth.env)")
    now = datetime.datetime.now(datetime.timezone.utc)
    feeds = gather()
    st = load_state() or {"seen": {}}
    week_ago = (now - datetime.timedelta(days=WEEK_DAYS)).isoformat()
    horizon = (now + datetime.timedelta(days=WEEK_DAYS)).date().isoformat()
    today = now.date().isoformat()
    everything = [i for src in ("hc", "hcr", "rr", "s8") for i in (feeds[src] or [])]
    new_week = [i for i in everything if (st["seen"].get(i["id"]) or "") >= week_ago]
    closing = [i for i in everything
               if i["kind"] == "lottery" and i.get("closes") and today <= i["closes"] <= horizon]

    def build(sub):
        mine_new = sort_for_reading([i for i in new_week if wants(sub, i)])
        mine_close = sort_for_reading([i for i in closing if wants(sub, i)
                                       and i["id"] not in {n["id"] for n in mine_new}])
        if not mine_new and not mine_close:
            return None
        where = boro_phrase(sub["boroughs"])
        bits = []
        if mine_new:
            bits.append(f"{len(mine_new)} new this week")
        if mine_close:
            bits.append(f"{len(mine_close)} closing soon")
        subject = f"This week in {where}: " + " · ".join(bits)
        html, text, post_unsub = render_roundup(
            sub, emailkit, eyebrow="Tuesday round-up", title=subject,
            intro=f"Everything that opened in {where} in the last seven days, and the "
                  "deadlines coming up. The minute-it-opens alerts continue as usual.",
            sections=[("Opened this week", "good", mine_new),
                      ("Closing in the next seven days", "warn", mine_close)],
            cta_label="See everything open on the map", digest=True)
        return subject, html, text, post_unsub

    if test_email:
        sub = {"email": test_email, "boroughs": ["M", "Bk", "Q", "Bx", "SI"],
               "kinds": ["lottery", "rerental", "voucher"],
               "token": "00000000-0000-0000-0000-000000000000"}
        built = build(sub)
        if not built:
            sys.exit("nothing new or closing this week to build a sample from")
        subject, html, text, post_unsub = built
        emailkit.send(test_email, "[TEST] " + subject, html, text, unsub_url=post_unsub)
        print(f"sent weekly sample to {test_email}")
        return

    sent_ids, sent = [], 0
    for sub in subscriber_rows(key):
        if sub.get("digest_off") or not sub.get("welcomed_at"):
            continue
        built = build(sub)
        if not built:
            continue
        subject, html, text, post_unsub = built
        print(f"weekly -> {sub['email']}: {subject}")
        if args_dry:
            continue
        if sent >= MAX_SENDS_PER_RUN:
            print("   send budget exhausted for this run")
            break
        try:
            if not mailcap.claim(sub["email"], "weekly"):
                print("   already emailed today — skipped (they heard from us)")
                continue
            emailkit.send(sub["email"], subject, html, text, unsub_url=post_unsub)
        except Exception as e:
            print(f"   FAILED {type(e).__name__}: {str(e)[:80]}")
            mailcap.release(sub["email"])
            continue
        sent += 1
        sent_ids.append(sub["id"])
    if not args_dry and sent_ids:
        rpc("lottery_alerts_mark", {"p_sent": sent_ids, "p_welcomed": [], "p_nudged": []}, key)
    print(f"weekly sent {sent}")


def wants(sub, item):
    if item["kind"] not in sub["kinds"]:
        return False
    if item["boro"] is None:
        # Unplaced listing: only someone watching the whole city should hear
        # about it — a guess at a borough is worse than a skipped email.
        if not set(sub["boroughs"]) >= ALL_BOROS:
            return False
    elif item["boro"] not in sub["boroughs"]:
        return False
    # Optional filters. A filter only bites on a figure the source actually
    # printed: Housing Connect states rents and an income band for every
    # lottery, HCR states incomes, the re-rental boards mostly state nothing.
    # A listing with no figure still goes out — the alternative is silently
    # dropping the first-come units for exactly the people who set a cap.
    cap = sub.get("max_rent")
    if cap and item.get("rent_low") and item["rent_low"] > cap:
        return False
    inc = sub.get("income")
    if inc:
        lo, hi = item.get("income_min"), item.get("income_max")
        if lo and inc < lo:
            return False
        if hi and inc > hi:
            return False
    return True


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true", help="rebuild state, send nothing")
    ap.add_argument("--test-email", help="send one sample built from today's feeds")
    ap.add_argument("--welcome", action="store_true",
                    help="only send welcome emails to new sign-ups")
    ap.add_argument("--nudge", action="store_true",
                    help="first-week round-up for sign-ups that have heard nothing yet")
    ap.add_argument("--weekly", action="store_true",
                    help="the fixed-day digest: new this week + closing this week")
    args = ap.parse_args()
    if args.welcome:
        return welcome(args.dry_run)
    if args.nudge:
        return nudge(args.dry_run)
    if args.weekly:
        return weekly(args.dry_run, args.test_email)

    now = datetime.datetime.now(datetime.timezone.utc)
    feeds = gather()
    for src, items in feeds.items():
        print(f"{src}: {'unreadable' if items is None else str(len(items)) + ' items'}")

    from growth import emailkit, mailcap

    if args.test_email:
        items = [i for src in ("hc", "hcr", "rr", "s8") for i in (feeds[src] or [])][:6]
        if not items:
            sys.exit("no items in any feed to build a sample from")
        sub = {"email": args.test_email, "boroughs": ["M", "Bk", "Q", "Bx", "SI"],
               "kinds": ["lottery", "rerental", "voucher"], "token": "00000000-0000-0000-0000-000000000000"}
        subject, html, text, post_unsub = render_alert(items, sub, emailkit)
        emailkit.send(args.test_email, "[TEST] " + subject, html, text, unsub_url=post_unsub)
        print(f"sent sample ({len(items)} items) to {args.test_email}")
        return

    st = load_state()
    first = st is None
    if first:
        st = {"seen": {}, "sends": [], "held": {}}
    st.setdefault("seen", {}); st.setdefault("sends", []); st.setdefault("held", {})
    prune(st, now)
    prune_held(st, feeds)

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
    if not new and not st["held"]:
        print("nothing new")
        if not args.dry_run:
            save_state(st)
        return
    print(f"{len(new)} new, {sum(len(v) for v in st['held'].values())} held:")
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
        sid = str(sub["id"])
        held = st["held"].get(sid, [])
        fresh = [i for i in new if wants(sub, i) and i["id"] not in {h["id"] for h in held}]
        mine = held + fresh
        if not mine:
            continue

        def hold(reason):
            st["held"][sid] = mine[-HELD_MAX:]
            print(f"  hold {sub['email']} ({len(mine)}): {reason}")

        if sent >= MAX_SENDS_PER_RUN or len(st["sends"]) >= HOURLY_CAP:
            hold("send budget exhausted — next run")
            continue
        # The day's one email. A claim that fails means another job (the
        # morning saved-building mail, the weekly digest, a welcome) already
        # wrote to this address today; the items wait for tomorrow's first send.
        try:
            ok = mailcap.claim(sub["email"], "alert", dry=args.dry_run)
        except Exception as e:
            hold(f"ledger unreachable ({type(e).__name__})")
            continue
        if not ok:
            hold("already emailed today")
            continue
        subject, html, text, post_unsub = render_alert(mine, sub, emailkit)
        print(f"  -> {sub['email']}: {subject}")
        if args.dry_run:
            continue
        try:
            emailkit.send(sub["email"], subject, html, text, unsub_url=post_unsub)
        except Exception as e:
            print(f"     FAILED {type(e).__name__}: {str(e)[:80]}")
            mailcap.release(sub["email"])
            hold("send failed")
            continue
        sent += 1
        st["sends"].append(now.isoformat())
        st["held"].pop(sid, None)
        sent_ids.append(sub["id"])

    if not args.dry_run:
        save_state(st)
        if sent_ids or welcomed_ids:
            try:
                rpc("lottery_alerts_mark", {"p_sent": sent_ids, "p_welcomed": welcomed_ids, "p_nudged": []}, key)
            except Exception as e:
                print(f"mark failed: {e}")
    print(f"sent {sent}")


def welcome(args_dry=False):
    """Welcome anyone who signed up since the last run. Separate entry point
    so the wrapper can call it even when the feeds have nothing new. Counts
    against the day's one email: someone who already heard from us today is
    welcomed tomorrow, not twice today."""
    from growth import emailkit, mailcap
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
            if not mailcap.claim(sub["email"], "welcome"):
                print("   already emailed today — welcome waits for tomorrow")
                continue
        except Exception as e:
            print(f"   ledger unreachable ({type(e).__name__}) — retry next run")
            continue
        try:
            emailkit.send(sub["email"], subject, html, text, unsub_url=post_unsub)
            done.append(sub["id"])
        except Exception as e:
            print(f"   FAILED {type(e).__name__}: {str(e)[:80]}")
            mailcap.release(sub["email"])
    if done:
        rpc("lottery_alerts_mark", {"p_sent": [], "p_welcomed": done, "p_nudged": []}, key)
    print(f"welcomed {len(done)}")


if __name__ == "__main__":
    main()
