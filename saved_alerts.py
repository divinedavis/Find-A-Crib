#!/usr/bin/env python3
"""Email people when a building they saved changes.

Saving a building is subscribing to it (owner decision, 2026-09-05). Every
signed-in saver — free or Plus — hears when a saved building:

  zumper       is advertised for rent (Zumper/StreetEasy feed, listings.json)
  s8           gets a listing for voucher holders (AffordableHousing.com, s8.json)
  price        has its asking rent drop (either feed, vs. the last figure we saw)
  lottery      hosts a housing lottery (Housing Connect / HCR, matched by
               house number + distance to the lot)
  rerental     has a unit on an HPD marketing agent's re-rental board
               (rerental_new.json, matched by house number + street)
  violations   gains open HPD violations (weekly HPD refresh)
  cleared      goes from open violations to none
  status       has its DHCR registration change (codes or unit count; annual)

Runs every morning on the web droplet from the checkout (saved_alerts.sh,
deploy/cron-rentmap-saved), where every feed already lives, replacing the
nightly notify_saved_listings.py that ran on the other droplet and only
watched the two listing feeds for Plus members.

Semantics kept from the old job: only a CHANGE alerts — saving a building
that is already advertised says nothing; the first run seeds a snapshot and
sends nothing; one announcement per (user, building, kind) per cooldown.

New: one email a day per person, across every job (growth/mailcap.py). A
change found on a day the person already got mail is held in `pending` and
leads tomorrow's email. Tuesdays the morning email is the weekly digest
instead — the same pending changes, plus the state of everything they saved
and what opened or is closing in the boroughs they save and browse in.

    python3 saved_alerts.py                 # morning run (digest on Tuesdays)
    python3 saved_alerts.py --dry-run       # print, write nothing
    python3 saved_alerts.py --weekly        # force the digest today
    python3 saved_alerts.py --test-email you@x.com [--force-bbl <bbl>]
"""
import argparse
import datetime
import json
import math
import os
import re
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lottery_alerts as la                       # feeds, rpc, boro helpers

SITE = la.SITE
DATA_DIR = la.DATA_DIR
STATE = os.path.join(HERE, "saved_alerts_state.json")
DIGEST_WEEKDAY = int(os.environ.get("FAC_DIGEST_WEEKDAY", "1"))   # Monday=0 → Tuesday
COOLDOWN = {"zumper": 60, "s8": 60, "lottery": 90, "rerental": 60,
            "price": 14, "violations": 14, "cleared": 30, "status": 120}
PENDING_MAX = 20
MAX_CARDS = 8
MAX_SENDS_PER_RUN = 300
NUDGE_MIN_DAYS, NUDGE_MAX_DAYS = 2, 8
LOT_MATCH_M = 120.0
BORO_NAME = la.BORO_NAME
BORO_SLUG = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens",
             "Bx": "bronx", "SI": "staten-island"}
STREET_STOP = {"e", "east", "w", "west", "n", "north", "s", "south", "st", "street",
               "ave", "avenue", "pl", "place", "rd", "road", "blvd", "boulevard",
               "dr", "drive", "ln", "lane", "ct", "court", "pkwy", "parkway", "ter",
               "terrace", "apt", "unit", "the", "at"}


# ------------------------------------------------------------------ helpers

def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower())
    return re.sub(r"-+", "-", s).strip("-") or "x"


def titlecase_addr(a):
    out = []
    for tok in (a or "").split():
        if re.match(r"^\d+(ST|ND|RD|TH)$", tok):
            out.append(tok.lower())
        elif tok.isalpha():
            out.append(tok.capitalize())
        else:
            out.append(tok)
    return " ".join(out)


def building_url(rec):
    return f"{SITE}/building/{BORO_SLUG.get(rec.get('b'), 'nyc')}/{slugify(rec.get('a'))}-{rec['bbl']}/"


def money(v):
    return la.money(v)


def dist_m(lat1, lng1, lat2, lng2):
    """Equirectangular — fine at city scale."""
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return math.hypot(x, y) * 6371000.0


def addr_parts(text):
    """('262', 'sullivan') from '262-264 Sullivan Pl.' / '262 SULLIVAN PL' /
    '94 east 111'. The street word is the first token that is not a number,
    a direction or a suffix; an all-numeric street ("111" for 111th St) is
    kept as digits so '94 east 111' meets '94 E 111 ST'."""
    toks = re.split(r"[\s\-,./]+", (text or "").lower().strip())
    toks = [t for t in toks if t]
    if not toks:
        return None, None
    num = re.match(r"^(\d+)[a-z]?$", toks[0])
    if not num:
        return None, None
    street = None
    for t in toks[1:]:
        t2 = re.sub(r"(st|nd|rd|th)$", "", t) if re.match(r"^\d+(st|nd|rd|th)$", t) else t
        if t2 in STREET_STOP:
            continue
        street = t2
        break
    return num.group(1), street


def load_state():
    try:
        return json.load(open(STATE))
    except (FileNotFoundError, ValueError):
        return None


def save_state(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"), separators=(",", ":"))
    os.replace(tmp, STATE)


def parse_ts(v):
    return la.parse_ts(v)


# ------------------------------------------------------------------ data

def load_buildings():
    """bbl -> record, from the same blob the site serves."""
    d = la.load_json("buildings.min.json") or []
    return {r["bbl"]: r for r in d if r.get("bbl")}


def snapshot_of(rec, listings, s8):
    bbl = rec["bbl"]
    h = rec.get("h") or {}
    v = h.get("violations") or {}
    c = h.get("complaints") or {}
    counts = listings.get("counts") or {}
    prices = listings.get("prices") or {}
    posted = listings.get("posted") or {}
    av = (s8.get("avail") or {}).get(bbl) or {}
    if isinstance(av, str):
        try:
            av = json.loads(av)
        except ValueError:
            av = {}
    return {
        "vo": v.get("open"), "co": c.get("open"),
        "s": "|".join(sorted(rec.get("s") or [])), "u": rec.get("u"),
        "zc": counts.get(bbl) or 0, "zp": prices.get(bbl), "zt": posted.get(bbl) or 0,
        "s8n": av.get("n") or 0, "s8p": av.get("p"),
    }


def diff_building(rec, prev, cur, listings, s8):
    """Change items for one building: [{kind, text, url, price}]. `prev` None
    = never seen (seed, no items)."""
    if prev is None:
        return []
    out = []
    bbl = rec["bbl"]
    urls = listings.get("urls") or {}
    if cur["zc"] and (not prev.get("zc") or (cur["zt"] and cur["zt"] > (prev.get("zt") or 0))):
        p = f" — {money(cur['zp'])}/mo" if cur.get("zp") else ""
        out.append({"kind": "zumper", "price": cur.get("zp"),
                    "text": f"Advertised for rent{p}. Rent-stabilized units move fast — reach out early.",
                    "url": urls.get(bbl)})
    elif cur.get("zp") and prev.get("zp") and cur["zp"] < prev["zp"]:
        out.append({"kind": "price", "price": cur["zp"],
                    "text": f"Asking rent dropped: {money(prev['zp'])} → {money(cur['zp'])}/mo.",
                    "url": urls.get(bbl)})
    av = (s8.get("avail") or {}).get(bbl) or {}
    if isinstance(av, str):
        try:
            av = json.loads(av)
        except ValueError:
            av = {}
    if cur["s8n"] and not prev.get("s8n"):
        p = f" — {money(cur['s8p'])}/mo" if cur.get("s8p") else ""
        out.append({"kind": "s8", "price": cur.get("s8p"),
                    "text": f"An apartment here is listed for voucher holders on AffordableHousing.com{p}.",
                    "url": av.get("url")})
    elif cur.get("s8p") and prev.get("s8p") and cur["s8p"] < prev["s8p"]:
        out.append({"kind": "price", "price": cur["s8p"],
                    "text": f"Voucher listing rent dropped: {money(prev['s8p'])} → {money(cur['s8p'])}/mo.",
                    "url": av.get("url")})
    pv, cv = prev.get("vo"), cur.get("vo")
    if isinstance(pv, int) and isinstance(cv, int):
        if cv > pv:
            out.append({"kind": "violations", "price": None,
                        "text": f"{cv - pv} new open HPD violation{'' if cv - pv == 1 else 's'} "
                                f"({cv} open now). Worth asking the landlord about before you sign.",
                        "url": None})
        elif pv > 0 and cv == 0:
            out.append({"kind": "cleared", "price": None,
                        "text": f"All {pv} open HPD violation{'' if pv == 1 else 's'} cleared.",
                        "url": None})
    if prev.get("s") is not None and (prev.get("s") != cur.get("s") or
                                      (prev.get("u") and cur.get("u") and prev["u"] != cur["u"])):
        bits = []
        if prev.get("s") != cur.get("s"):
            bits.append("registration codes changed to " + (cur["s"].replace("|", ", ") or "none"))
        if prev.get("u") and cur.get("u") and prev["u"] != cur["u"]:
            bits.append(f"registered units {prev['u']} → {cur['u']}")
        out.append({"kind": "status", "price": None,
                    "text": "DHCR registration changed: " + "; ".join(bits) + ".", "url": None})
    return out


def lottery_hits(watched, feeds):
    """bbl -> [lottery item] for lotteries sitting on a watched lot: same house
    number where both sides state one, and within LOT_MATCH_M of the lot."""
    hits = {}
    points = []
    for it in (feeds.get("hc") or []):
        raw = it.get("_raw") or {}
        points.append((it, raw.get("lat"), raw.get("lng"), raw.get("address")))
    for it in (feeds.get("hcr") or []):
        for b in (it.get("_raw") or {}).get("buildings") or []:
            points.append((it, b.get("lat"), b.get("lng"), b.get("street")))
    if not points:
        return hits
    for bbl, rec in watched.items():
        if not rec.get("lat") or not rec.get("lng"):
            continue
        num, _ = addr_parts(rec.get("a"))
        for it, lat, lng, addr in points:
            if not lat or not lng:
                continue
            if dist_m(rec["lat"], rec["lng"], lat, lng) > LOT_MATCH_M:
                continue
            anum, _ = addr_parts(addr)
            if num and anum and num != anum:
                continue
            hits.setdefault(bbl, []).append(it)
    return hits


def rerental_hits(watched, feeds):
    """bbl -> [re-rental item] by house number + street word (+ borough when
    the board stated one)."""
    index = {}
    for bbl, rec in watched.items():
        num, street = addr_parts(rec.get("a"))
        if num and street:
            index.setdefault((num, street), []).append(bbl)
    hits = {}
    for it in (feeds.get("rr") or []):
        raw = it.get("_raw") or {}
        for text in (raw.get("label"), raw.get("key")):
            num, street = addr_parts(text)
            if not (num and street):
                continue
            for bbl in index.get((num, street), []):
                if it.get("boro") and watched[bbl].get("b") != it["boro"]:
                    continue
                hits.setdefault(bbl, []).append(it)
            break
    return hits


def gather_feeds():
    """lottery_alerts.gather() plus the raw records the matchers need."""
    feeds = la.gather()
    hc = la.load_json("housing_connect.json") or {}
    raw_hc = {f"hc:{l['id']}": l for l in hc.get("lotteries") or [] if l.get("id")}
    hcr = la.load_json("hcr.json") or {}
    raw_hcr = {f"hcr:{l['id']}": l for l in hcr.get("listings") or [] if l.get("id")}
    rr = la.load_json("rerental_new.json") or {}
    raw_rr = {f"rr:{e.get('agent')}|{e.get('key')}": e for e in rr.get("items") or []}
    for src, raw in (("hc", raw_hc), ("hcr", raw_hcr), ("rr", raw_rr)):
        for it in (feeds.get(src) or []):
            it["_raw"] = raw.get(it["id"], {})
    return feeds


# ------------------------------------------------------------------ email

def card_for(rec, change):
    where = ", ".join(x for x in (rec.get("nb"), BORO_NAME.get(rec.get("b"))) if x)
    link = ("View the listing", change["url"]) if change.get("url") else ("View building", building_url(rec))
    return {"type": "card", "heading": titlecase_addr(rec.get("a")),
            "meta": f"{where} · rent-stabilized building" if where else "rent-stabilized building",
            "body": change["text"], "link": link}


def subject_for(items, buildings):
    kinds = {i["kind"] for i in items}
    bbls = {i["bbl"] for i in items}
    first = buildings.get(next(iter(bbls)), {})
    addr = titlecase_addr(first.get("a"))
    if len(bbls) == 1:
        k = items[0]["kind"]
        return {"zumper": f"{addr} was just advertised for rent",
                "s8": f"{addr} has a listing for voucher holders",
                "price": f"Rent dropped at {addr}",
                "lottery": f"A housing lottery opened at {addr}",
                "rerental": f"A re-rental opened at {addr}",
                "violations": f"New HPD violations at {addr}",
                "cleared": f"Violations cleared at {addr}",
                "status": f"DHCR registration changed at {addr}"}.get(k, f"{addr} changed")
    if kinds <= {"zumper", "s8", "price"}:
        return f"{len(bbls)} buildings you saved were just advertised"
    return f"{len(bbls)} buildings you saved changed"


def render_changes(user, items, buildings, emailkit):
    """items: [{bbl, kind, text, url, price}] pending for this user."""
    blocks = []
    by_bbl = {}
    for it in items:
        by_bbl.setdefault(it["bbl"], []).append(it)
    for bbl, group in list(by_bbl.items())[:MAX_CARDS]:
        rec = buildings.get(bbl)
        if not rec:
            continue
        if len(group) == 1:
            blocks.append(card_for(rec, group[0]))
        else:
            merged = {"text": " ".join(g["text"] for g in group),
                      "url": next((g["url"] for g in group if g.get("url")), None)}
            blocks.append(card_for(rec, merged))
    if len(by_bbl) > MAX_CARDS:
        blocks.append({"type": "note", "text": f"…and {len(by_bbl) - MAX_CARDS} more — "
                                               f"everything you saved is on the map."})
    subject = subject_for(items, buildings)
    unsub = f"{SITE}/#unsub={user['token']}"
    html, text = emailkit.render(
        title=subject, eyebrow="A building you saved",
        intro="You saved it, so we watch it. Here is what changed.",
        blocks=blocks, cta=("Open your saved buildings", f"{SITE}/?src=saved#list"),
        footer_note="You get these because you saved buildings on Find A Crib. "
                    "Never more than one email a day.",
        unsub_url=unsub)
    return subject, html, text, unsub


def boros_for(user, buildings):
    """Adaptive: boroughs of what they saved, then of what they browsed."""
    out = []
    for bbl in user.get("bbls") or []:
        b = (buildings.get(bbl) or {}).get("b")
        if b and b not in out:
            out.append(b)
    for b in user.get("viewed_boros") or []:
        if b not in out:
            out.append(b)
    return out[:3]


def status_blocks(user, buildings, listings, s8):
    """'Your saved buildings' summary for the digest and the day-3 status."""
    bbls = [b for b in (user.get("bbls") or []) if b in buildings]
    if not bbls:
        return []
    counts = listings.get("counts") or {}
    posted = listings.get("posted") or {}
    prices = listings.get("prices") or {}
    avail = s8.get("avail") or {}
    recent = 5 * 86400
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    advertised, voucher, viol_total = [], [], 0
    for bbl in bbls:
        rec = buildings[bbl]
        if counts.get(bbl) and (not posted or now - (posted.get(bbl) or 0) < recent):
            advertised.append((rec, prices.get(bbl)))
        if bbl in avail:
            voucher.append(rec)
        viol_total += ((rec.get("h") or {}).get("violations") or {}).get("open") or 0
    items = []
    for rec, p in advertised[:5]:
        items.append({"text": titlecase_addr(rec.get("a")),
                      "sub": (f"advertised now · {money(p)}/mo" if p else "advertised now"),
                      "url": building_url(rec)})
    for rec in voucher[:3]:
        items.append({"text": titlecase_addr(rec.get("a")), "sub": "listed for voucher holders now",
                      "url": building_url(rec)})
    blocks = [{"type": "stats", "items": [
        (f"{len(bbls)}", "saved"),
        (f"{len(advertised)}", "advertised now"),
        (f"{viol_total:,}", "open HPD violations")]}]
    if items:
        blocks.append({"type": "callout", "tone": "good", "heading": "Available right now",
                       "items": items})
    else:
        blocks.append({"type": "note",
                       "text": "Nothing you saved is advertised at the moment. The morning this "
                               "changes, you'll hear about it."})
    return blocks


def borough_sections(user, buildings, feeds, seen, now):
    """(heading, tone, items) for the boroughs this person saves/browses in."""
    boros = boros_for(user, buildings)
    if not boros:
        return [], []
    sub = {"boroughs": boros, "kinds": ["lottery", "rerental", "voucher"]}
    everything = [i for src in ("hc", "hcr", "rr", "s8") for i in (feeds.get(src) or [])]
    week_ago = (now - datetime.timedelta(days=7)).isoformat()
    horizon = (now + datetime.timedelta(days=7)).date().isoformat()
    today = now.date().isoformat()
    new_week = la.sort_for_reading([i for i in everything if la.wants(sub, i)
                                    and (seen.get(i["id"]) or "") >= week_ago])
    ids = {i["id"] for i in new_week}
    closing = la.sort_for_reading([i for i in everything if la.wants(sub, i)
                                   and i["kind"] == "lottery" and i.get("closes")
                                   and today <= i["closes"] <= horizon and i["id"] not in ids])
    where = la.boro_phrase(boros)
    return boros, [(f"Opened this week in {where}", "good", new_week),
                   (f"Closing in the next seven days in {where}", "warn", closing)]


def render_digest(user, pending, buildings, listings, s8, feeds, seen, emailkit, now,
                  *, eyebrow="Tuesday round-up", day3=False):
    blocks = []
    if pending:
        blocks.append({"type": "section", "label": "Changes on buildings you saved"})
        by_bbl = {}
        for it in pending:
            by_bbl.setdefault(it["bbl"], []).append(it)
        for bbl, group in list(by_bbl.items())[:MAX_CARDS]:
            rec = buildings.get(bbl)
            if rec:
                merged = {"text": " ".join(g["text"] for g in group),
                          "url": next((g["url"] for g in group if g.get("url")), None)}
                blocks.append(card_for(rec, merged))
    st_blocks = status_blocks(user, buildings, listings, s8)
    if st_blocks:
        blocks.append({"type": "section", "label": "Your saved buildings"})
        blocks.extend(st_blocks)
    boros, sections = borough_sections(user, buildings, feeds, seen, now)
    shown = 0
    n_new = n_close = 0
    for heading, tone, items in sections:
        if not items:
            continue
        part = items[:max(0, 10 - shown)]
        shown += len(part)
        if not part:
            continue
        if tone == "good":
            n_new = len(items)
        else:
            n_close = len(items)
        blocks.append({"type": "callout", "tone": tone, "heading": heading,
                       "items": [{"text": i["text"], "sub": i["sub"], "url": i["url"]} for i in part]})
        if len(items) > len(part):
            blocks.append({"type": "note", "text": f"…and {len(items) - len(part)} more on the map."})
    if not pending and not st_blocks and not (n_new or n_close):
        return None
    where = la.boro_phrase(boros) if boros else "NYC"
    if day3:
        subject = "Your saved buildings, a few days in"
        intro = ("You saved a few buildings this week. Here is where they stand, and what "
                 f"is open around them in {where}.")
    else:
        bits = []
        if pending:
            bits.append(f"{len({p['bbl'] for p in pending})} saved building"
                        f"{'' if len({p['bbl'] for p in pending}) == 1 else 's'} changed")
        if n_new:
            bits.append(f"{n_new} new in {where}")
        if n_close:
            bits.append(f"{n_close} closing soon")
        subject = "This week: " + " · ".join(bits) if bits else f"This week on Find A Crib"
        intro = ("The week on the buildings you saved and in the boroughs you look at. "
                 "Alerts the morning something changes continue as usual.")
    tok = user["token"]
    unsub = f"{SITE}/#unsub={tok}&k=digest"
    blocks.append({"type": "note",
                   "text": "Stop just this round-up (alerts on your saved buildings keep working): "
                           f"{unsub}"})
    html, text = emailkit.render(
        title=subject, eyebrow=eyebrow, intro=intro, blocks=blocks,
        cta=("Open the map", f"{SITE}/?src=digest"),
        footer_note="You get this because you have a Find A Crib account and saved buildings. "
                    "Never more than one email a day.",
        unsub_url=unsub, unsub_label="Stop the round-up")
    return subject, html, text, unsub


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--weekly", action="store_true", help="send the digest today")
    ap.add_argument("--no-weekly", action="store_true", help="never the digest, even on Tuesday")
    ap.add_argument("--test-email", default="")
    ap.add_argument("--force-bbl", default="")
    args = ap.parse_args()
    from growth import emailkit, mailcap

    now = datetime.datetime.now(datetime.timezone.utc)
    ny_now = now.astimezone(ZoneInfo("America/New_York"))
    digest_day = args.weekly or (ny_now.weekday() == DIGEST_WEEKDAY and not args.no_weekly)

    buildings = load_buildings()
    listings = la.load_json("listings.json") or {}
    s8 = la.load_json("s8.json") or {}
    feeds = gather_feeds()
    lot_state = la.load_state() or {"seen": {}}
    seen = lot_state.get("seen") or {}
    if not buildings:
        sys.exit("buildings.min.json missing — nothing to diff")

    # ---- test: one sample, no state ----
    if args.test_email:
        bbl = args.force_bbl or next((b for b in (listings.get("counts") or {}) if b in buildings), None)
        rec = buildings.get(bbl)
        if not rec:
            sys.exit(f"bbl {bbl} not in buildings")
        user = {"email": args.test_email, "token": "00000000-0000-0000-0000-000000000000",
                "bbls": [bbl], "viewed_boros": []}
        p = (listings.get("prices") or {}).get(bbl)
        items = [{"bbl": bbl, "kind": "zumper", "price": p, "url": (listings.get("urls") or {}).get(bbl),
                  "text": f"Advertised for rent{(' — ' + money(p) + '/mo') if p else ''}."}]
        if digest_day:
            built = render_digest(user, items, buildings, listings, s8, feeds, seen, emailkit, now)
        else:
            built = render_changes(user, items, buildings, emailkit)
        subject, html, text, unsub = built
        emailkit.send(args.test_email, "[TEST] " + subject, html, text, unsub_url=unsub)
        print(f"sent sample to {args.test_email}: {subject}")
        return

    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        sys.exit("SUPABASE_SERVICE_KEY not set (growth.env)")
    try:
        la.rpc("lifecycle_ensure_prefs", {}, key)
        users = la.rpc("saved_watchers", {}, key) or []
    except Exception as e:
        sys.exit(f"could not load watchers: {e}")
    for u in users:
        u["bbls"] = [b for b in (u.get("bbls") or []) if b in buildings]
    watchers = {}
    for u in users:
        if u.get("alerts_off"):
            continue
        for b in u["bbls"]:
            watchers.setdefault(b, []).append(u)
    watched = {b: buildings[b] for b in watchers}
    print(f"{len(users)} accounts, {len(watched)} watched buildings")

    st = load_state()
    first = st is None
    if first:
        st = {"snap": {}, "lot_seen": {}, "rr_seen": {}, "pending": {}}
    for k in ("snap", "lot_seen", "rr_seen", "pending"):
        st.setdefault(k, {})

    # ---- diff every watched building ----
    changes = {}          # bbl -> [change]
    for bbl, rec in watched.items():
        cur = snapshot_of(rec, listings, s8)
        prev = st["snap"].get(bbl)
        for c in diff_building(rec, prev, cur, listings, s8):
            changes.setdefault(bbl, []).append(c)
        st["snap"][bbl] = cur
    for bbl, its in lottery_hits(watched, feeds).items():
        seen_ids = set(st["lot_seen"].get(bbl) or [])
        fresh = [i for i in its if i["id"] not in seen_ids]
        st["lot_seen"][bbl] = sorted(seen_ids | {i["id"] for i in its})[-20:]
        if fresh and bbl in st["snap"] and not first:
            i = fresh[0]
            changes.setdefault(bbl, []).append(
                {"kind": "lottery", "price": i.get("rent_low"), "url": i.get("url"),
                 "text": f"A housing lottery opened here: {i['text']}"
                         + (f" ({i['sub']})" if i.get("sub") else "") + ". Apply before the deadline."})
    for bbl, its in rerental_hits(watched, feeds).items():
        seen_ids = set(st["rr_seen"].get(bbl) or [])
        fresh = [i for i in its if i["id"] not in seen_ids]
        st["rr_seen"][bbl] = sorted(seen_ids | {i["id"] for i in its})[-20:]
        if fresh and not first:
            i = fresh[0]
            changes.setdefault(bbl, []).append(
                {"kind": "rerental", "price": i.get("rent_low"), "url": i.get("url"),
                 "text": f"A re-rental is listed here by {i['_raw'].get('agent') or 'the marketing agent'}"
                         + (f" ({i['sub']})" if i.get("sub") else "") + ". Usually first-come, first-served."})
    # Forget buildings nobody watches any more, so a re-save later re-seeds.
    for bbl in [b for b in st["snap"] if b not in watched]:
        st["snap"].pop(bbl, None); st["lot_seen"].pop(bbl, None); st["rr_seen"].pop(bbl, None)

    if first:
        print(f"no state — seeded {len(st['snap'])} buildings, nothing sent")
        if not args.dry_run:
            save_state(st)
        return
    n_changes = sum(len(v) for v in changes.values())
    print(f"{n_changes} change(s) on {len(changes)} building(s)")
    for bbl, cs in changes.items():
        for c in cs:
            print(f"  {c['kind']:10s} {titlecase_addr(buildings[bbl].get('a'))[:40]:40s} {c['text'][:60]}")

    # ---- cooldown, then queue per user ----
    uids = sorted({str(u["user_id"]) for b in changes for u in watchers.get(b, [])})
    cooled = set()
    if uids:
        try:
            for r in la.rpc("saved_alert_state", {"p_user_ids": uids, "p_days": max(COOLDOWN.values())}, key) or []:
                cooled.add((str(r["user_id"]), r["bbl"], r["source"], parse_ts(r["notified_at"])))
        except Exception as e:
            sys.exit(f"could not read cooldown state: {e}")   # state unsaved: retried next run

    def cool(uid, bbl, kind):
        for u, b, s, t in cooled:
            if u == uid and b == bbl and s == kind and t and (now - t).days < COOLDOWN[kind]:
                return True
        return False

    for bbl, cs in changes.items():
        for u in watchers.get(bbl, []):
            uid = str(u["user_id"])
            q = st["pending"].setdefault(uid, [])
            have = {(p["bbl"], p["kind"]) for p in q}
            for c in cs:
                if (bbl, c["kind"]) in have or cool(uid, bbl, c["kind"]):
                    continue
                q.append({"bbl": bbl, **c})
            st["pending"][uid] = q[-PENDING_MAX:]
    # pending for buildings no longer saved is stale
    by_uid = {str(u["user_id"]): u for u in users}
    for uid in list(st["pending"]):
        u = by_uid.get(uid)
        keep = [p for p in st["pending"][uid] if u and p["bbl"] in set(u["bbls"]) and not u.get("alerts_off")]
        if keep:
            st["pending"][uid] = keep
        else:
            st["pending"].pop(uid, None)

    # ---- send: one email per person, digest on digest day ----
    sent, marks = 0, []
    for u in users:
        uid = str(u["user_id"])
        pending = st["pending"].get(uid, [])
        created = parse_ts(u.get("created_at"))
        age = (now - created).days if created else 999
        steps = set(u.get("sent_steps") or [])
        day3 = (NUDGE_MIN_DAYS <= age <= NUDGE_MAX_DAYS and "status" not in steps
                and u["bbls"] and not u.get("lifecycle_off") and not pending)
        built, kind, step = None, None, None
        if digest_day and not u.get("digest_off") and (u["bbls"] or u.get("viewed_boros")):
            built = render_digest(u, pending, buildings, listings, s8, feeds, seen, emailkit, now)
            kind = "weekly"
        elif pending:
            built = render_changes(u, pending, buildings, emailkit)
            kind = "saved"
        elif day3:
            built = render_digest(u, [], buildings, listings, s8, feeds, seen, emailkit, now,
                                  eyebrow="A few days in", day3=True)
            kind, step = "nudge", "status"
        if not built:
            continue
        subject, html, text, unsub = built
        print(f"  {kind:6s} -> {u['email']}: {subject}")
        if args.dry_run:
            continue
        if sent >= MAX_SENDS_PER_RUN:
            print("  send budget exhausted — the rest wait for tomorrow")
            break
        try:
            if not mailcap.claim(u["email"], kind):
                print("     already emailed today — held")
                continue
        except Exception as e:
            print(f"     ledger unreachable ({type(e).__name__}) — held")
            continue
        try:
            emailkit.send(u["email"], subject, html, text, unsub_url=unsub)
        except Exception as e:
            print(f"     FAILED {type(e).__name__}: {str(e)[:80]}")
            mailcap.release(u["email"])
            continue
        sent += 1
        for p in pending:
            marks.append({"user_id": uid, "bbl": p["bbl"], "source": p["kind"], "price": p.get("price")})
        st["pending"].pop(uid, None)
        if step:
            try:
                la.rpc("lifecycle_mark_sent", {"p_user_id": uid, "p_step": step}, key)
            except Exception as e:
                print(f"     step not recorded: {e}")

    if not args.dry_run:
        if marks:
            try:
                la.rpc("saved_alert_mark", {"p_rows": marks}, key)
            except Exception as e:
                print(f"cooldown write failed: {e}")
        save_state(st)
    print(f"done: {sent} email(s) sent, {sum(len(v) for v in st['pending'].values())} change(s) held")


if __name__ == "__main__":
    main()
