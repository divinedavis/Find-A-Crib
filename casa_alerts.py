#!/usr/bin/env python3
"""Your Crib alerts: tell a Plus member about each new 311 call on the one
building they watch (owner, 2026-10-15).

Every 30 minutes (deploy/cron-rentmap-casa) this reads casa_watches, asks NYC
Open Data's 311 dataset (erm2-nwe9) for calls on each watched BBL created
after the row's last_seen, and sends what is new as one push to every phone
on the account plus one email. last_seen then moves to the newest call
announced, so nothing is sent twice.

"Real time" means as soon as the City publishes: the 311 dataset refreshes
about once a day (around 10:30 PM), and alerts go out from 8 AM (SEND_HOURS).

Crime alerts (owner, 2026-10-15): a watch can also pick kinds of crime
(CRIME_KINDS). The NYPD publishes complaints and shootings every three
months, so when a release moves the newest complaint date past the watch's
crime_seen, the watch gets one message counting each chosen kind within half
a mile over the newly published dates. The first release after a watch
starts only sets crime_seen — the lookup already showed the chart.

Plus is re-checked here (has_plus) on every run: a watch whose owner has let
Plus lapse is skipped, not deleted, so it resumes if they come back.

    python3 casa_alerts.py              # the cron run
    python3 casa_alerts.py --dry-run    # print, send and write nothing
"""
import argparse
import datetime
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apns                                      # noqa: E402
import lottery_alerts as la                      # noqa: E402  rpc, SUPABASE_URL, SITE

SITE = la.SITE
NY = ZoneInfo("America/New_York")
DATASET = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
MIN_GAP = datetime.timedelta(hours=3)            # at most one alert per watch per 3 h
# Alerts go out from 8 AM, like the lottery alerts (owner, 2026-10-15: "when
# will we alert users? 8AM?"). The City publishes 311 around 10:30 PM, so a
# night's new calls wait for the 8:07 run; anything later in the day goes on
# the next half-hour run until 9 PM.
SEND_HOURS = range(8, 21)
MAX_PER_ALERT = 20
COMPLAINTS = "https://data.cityofnewyork.us/resource/5uac-w243.json"
SHOOTINGS = "https://data.cityofnewyork.us/resource/5ucz-vwe8.json"
RADIUS_M = 800
# Casa's crime keys -> (label, NYPD ofns_desc values). api_server.CASA_CRIME_KINDS
# and the app's chips must list the same keys.
CRIME_KINDS = {
    "shootings": ("shooting", "shootings", None),
    "robbery": ("robbery", "robberies", ["ROBBERY"]),
    "burglary": ("burglary", "burglaries", ["BURGLARY"]),
    "assault": ("assault", "assaults", ["FELONY ASSAULT", "ASSAULT 3 & RELATED OFFENSES"]),
    "theft": ("theft", "thefts", ["PETIT LARCENY", "GRAND LARCENY"]),
    "car_theft": ("car theft", "car thefts", ["GRAND LARCENY OF MOTOR VEHICLE"]),
    "weapons": ("weapons offense", "weapons offenses", ["DANGEROUS WEAPONS"]),
    "drugs": ("drug offense", "drug offenses", ["DANGEROUS DRUGS"]),
    "vandalism": ("vandalism report", "vandalism reports", ["CRIMINAL MISCHIEF & RELATED OF"]),
    "harassment": ("harassment report", "harassment reports", ["HARRASSMENT 2"]),
}
PESTS = ("PEST", "RODENT", "RAT", "MICE", "MOUSE", "ROACH", "BED BUG", "BEDBUG", "VERMIN")


def rest(path, key, method="GET", body=None, prefer=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "User-Agent": "fac-casa-alerts"}
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(f"{la.SUPABASE_URL}/rest/v1/{path}", method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def soql_time(iso):
    """Socrata wants a floating timestamp without zone: 2026-10-15T08:00:00."""
    t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    # 311 created_date is New York local time.
    t = t.astimezone(NY)
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def new_calls(bbl, since_iso):
    return socrata(DATASET, {"$select": "unique_key,created_date,complaint_type,descriptor,status,incident_address",
         "$where": f"bbl='{bbl}' AND created_date > '{soql_time(since_iso)}'",
         "$order": "created_date ASC", "$limit": "200"})


def socrata(url, q):
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(q), timeout=90) as r:
        return json.loads(r.read())


def nypd_newest():
    """Newest complaint date the NYPD has published, as YYYY-MM-DD."""
    rows = socrata(COMPLAINTS, {"$select": "max(cmplnt_fr_dt) as newest"})
    return (rows[0].get("newest") or "")[:10] if rows else ""


def crime_counts(lat, lng, kinds, after, through):
    """{kind: n} within RADIUS_M for dates after `after` up to `through` (YYYY-MM-DD)."""
    out = {}
    offenses = sorted({o for k in kinds if CRIME_KINDS[k][2] for o in CRIME_KINDS[k][2]})
    if offenses:
        listed = ",".join("'" + o.replace("'", "''") + "'" for o in offenses)
        rows = socrata(COMPLAINTS, {
            "$select": "ofns_desc, count(*) as n",
            "$where": (f"within_circle(lat_lon, {lat}, {lng}, {RADIUS_M}) AND cmplnt_fr_dt > '{after}T23:59:59'"
                       f" AND cmplnt_fr_dt <= '{through}T23:59:59' AND ofns_desc in ({listed})"),
            "$group": "ofns_desc"})
        by_offense = {r.get("ofns_desc"): int(r.get("n") or 0) for r in rows}
        for k in kinds:
            if CRIME_KINDS[k][2]:
                out[k] = sum(by_offense.get(o, 0) for o in CRIME_KINDS[k][2])
    if "shootings" in kinds:
        # This file has plain latitude/longitude, no location column: a box
        # first, then the true distance.
        dlat, dlng = RADIUS_M / 111_000, RADIUS_M / (111_000 * math.cos(math.radians(lat)))
        rows = socrata(SHOOTINGS, {
            "$select": "latitude, longitude",
            "$where": (f"latitude between {lat - dlat} and {lat + dlat} AND longitude between {lng - dlng} and {lng + dlng}"
                       f" AND occur_date > '{after}T23:59:59' AND occur_date <= '{through}T23:59:59'"),
            "$limit": "500"})
        out["shootings"] = sum(1 for r in rows if r.get("latitude") and r.get("longitude")
                               and metres(lat, lng, float(r["latitude"]), float(r["longitude"])) <= RADIUS_M)
    return out


def metres(a_lat, a_lng, b_lat, b_lng):
    x = math.radians(b_lng - a_lng) * math.cos(math.radians((a_lat + b_lat) / 2))
    return 6_371_000 * math.hypot(x, math.radians(b_lat - a_lat))


def crime_text(address, counts, after, through):
    """Push title and body: "Apr 1 – Jun 30, within half a mile: 3 robberies, 1 shooting"."""
    parts = [f"{n} {CRIME_KINDS[k][0] if n == 1 else CRIME_KINDS[k][1]}"
             for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n]
    day = lambda d: datetime.date.fromisoformat(d).strftime("%b %-d")
    first = (datetime.date.fromisoformat(after) + datetime.timedelta(days=1)).isoformat()
    title = f"New NYPD reports near {address}" if address else "New NYPD reports near your building"
    return title[:110], (f"{day(first)} – {day(through)}, within half a mile: " + ", ".join(parts))[:178]


def is_pest(c):
    t = f"{c.get('complaint_type', '')} {c.get('descriptor', '')}".upper()
    return any(w in t for w in PESTS)


def label(c):
    kind = (c.get("complaint_type") or "311 call").strip()
    d = (c.get("descriptor") or "").strip()
    return f"{kind.title() if kind.isupper() else kind}" + (f" — {d.capitalize() if d.isupper() else d}" if d else "")


def push_text(address, calls):
    pests = [c for c in calls if is_pest(c)]
    n = len(calls)
    title = f"{n} new 311 call{'s' if n != 1 else ''} at {address}" if address else f"{n} new 311 call{'s' if n != 1 else ''} on your building"
    lead = pests[0] if pests else calls[-1]
    body = label(lead)
    if pests and len(pests) < n:
        body += f" · {len(pests)} about pests"
    elif n > 1:
        body += f" and {n - 1} more"
    return title[:110], body[:178]


def email_parts(emailkit, watch, calls):
    address = watch.get("address") or "your building"
    rows = []
    for c in calls[-MAX_PER_ALERT:][::-1]:
        try:
            day = datetime.date.fromisoformat((c.get("created_date") or "")[:10]).strftime("%b %-d, %Y")
        except ValueError:
            day = (c.get("created_date") or "")[:10]
        rows.append({"type": "card", "heading": label(c),
                     "meta": f"{day} · {(c.get('status') or '').title()}" + (" · pests" if is_pest(c) else "")})
    n = len(calls)
    link = f"{SITE}/casa/?bbl={watch['bbl']}&src=casa_alert"
    html, text = emailkit.render(
        title=f"{n} new 311 call{'s' if n != 1 else ''} at {address}",
        intro="New calls the City published for the building you watch in Your Crib.",
        blocks=rows,
        cta=("See every call on your building", link),
        footer_note=f"You're watching {address} with Find A Crib Plus. Stop any time in Your Crib: {SITE}/casa/")
    return f"New 311 call{'s' if n != 1 else ''} at {address}", html, text


def send(w, title, body, key, collapse, subject, html, text, dry):
    """One push to every phone on the account and one email. Returns (pushed, emailed)."""
    if dry:
        print(f"   would send: {title} / {body}")
        return 0, 0
    pushed = 0
    try:
        phones = la.rpc("device_tokens_for_emails", {"p_emails": [w["email"]]}, key) or []
    except Exception:
        phones = []
    for dev in phones:
        r = apns.send(dev["token"], dev.get("env") or "production", title, body,
                      url=f"{SITE}/casa/?bbl={w['bbl']}", collapse=collapse, extra={"casa": w["bbl"]})
        pushed += bool(r["ok"])
        try:
            if r["refile"]:
                la.rpc("device_token_refile", {"p_token": dev["token"], "p_env": r["refile"]}, key)
            if r["remove"]:
                la.rpc("device_token_remove", {"p_token": dev["token"]}, key)
        except Exception as e:
            print(f"   token upkeep failed: {type(e).__name__}")
    from growth import emailkit
    try:
        emailkit.send(w["email"], subject, html, text)
        return pushed, 1
    except Exception as e:
        print(f"   email failed: {type(e).__name__}")
        return pushed, 0


def run_311(w, key, now, dry):
    calls = new_calls(w["bbl"], w.get("last_seen") or w["created_at"])
    if not calls:
        return 0, 0
    print(f"{w['bbl']}: {len(calls)} new 311 call(s)")
    from growth import emailkit
    title, body = push_text(w.get("address"), calls)
    subject, html, text = email_parts(emailkit, w, calls)
    sent = send(w, title, body, key, f"casa-{w['bbl']}", subject, html, text, dry)
    if not dry:
        # The City's local timestamp, stored as New York time so the next
        # query's "created_date >" compares like with like.
        newest = max(c["created_date"] for c in calls)
        seen = datetime.datetime.fromisoformat(newest.split(".")[0]).replace(tzinfo=NY)
        rest(f"casa_watches?user_id=eq.{w['user_id']}", key, "PATCH",
             {"last_seen": seen.isoformat(), "last_sent": now.isoformat()}, prefer="return=minimal")
    return sent


def run_crime(w, key, newest, dry):
    kinds = [k for k in (w.get("crime_kinds") or []) if k in CRIME_KINDS]
    if not kinds or w.get("lat") is None or not newest:
        return 0, 0
    seen = w.get("crime_seen")
    if seen and seen >= newest:
        return 0, 0
    sent = (0, 0)
    if seen:
        counts = crime_counts(w["lat"], w["lng"], kinds, seen, newest)
        if any(counts.values()):
            print(f"{w['bbl']}: crime {counts}")
            from growth import emailkit
            title, body = crime_text(w.get("address"), counts, seen, newest)
            html, text = emailkit.render(
                title=title, intro=body + ". From the NYPD's newest quarterly release.",
                cta=("See the chart for your building", f"{SITE}/casa/?bbl={w['bbl']}&src=casa_crime"),
                footer_note=f"You picked these crime alerts in Your Crib with Find A Crib Plus. Change them any time: {SITE}/casa/")
            sent = send(w, title, body, key, f"casa-crime-{w['bbl']}", title, html, text, dry)
    if not dry:
        rest(f"casa_watches?user_id=eq.{w['user_id']}", key, "PATCH", {"crime_seen": newest}, prefer="return=minimal")
    return sent


def send_test(key, email, bbl, lat, lng, address=""):
    """The owner's preview (2026-10-15): what a watcher's phone shows."""
    if not (len(bbl) == 10 and bbl.isdigit()):
        sys.exit("bad BBL")
    w = {"email": email, "bbl": bbl, "address": address or None}
    since = (datetime.datetime.now(NY) - datetime.timedelta(days=30)).isoformat()
    calls = new_calls(bbl, since)[-3:]
    if calls:
        from growth import emailkit
        title, body = push_text(w["address"], calls)
        subject, html, text = email_parts(emailkit, w, calls)
        print("311:", title, "/", body, "->", send(w, title, body, key, f"casa-{bbl}", subject, html, text, False))
    else:
        print("311: no calls on this building in the past 30 days to sample")
    newest = nypd_newest()
    after = (datetime.date.fromisoformat(newest) - datetime.timedelta(days=91)).isoformat()
    counts = crime_counts(float(lat), float(lng), ["shootings", "robbery", "burglary", "car_theft"], after, newest)
    if any(counts.values()):
        title, body = crime_text(w["address"], counts, after, newest)
        from growth import emailkit
        html, text = emailkit.render(
            title=title, intro=body + ". From the NYPD's newest quarterly release.",
            cta=("See the chart for your building", f"{SITE}/casa/?bbl={bbl}&src=casa_crime"),
            footer_note=f"You picked these crime alerts in Your Crib with Find A Crib Plus. Change them any time: {SITE}/casa/")
        print("crime:", title, "/", body, "->", send(w, title, body, key, f"casa-crime-{bbl}", title, html, text, False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", nargs=4, metavar=("EMAIL", "BBL", "LAT", "LNG"),
                    help="send one sample 311 alert and one crime alert, built from the building's real recent "
                         "data, to this account's phones and email; touches no watch")
    ap.add_argument("--address", default="")
    args = ap.parse_args()
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        sys.exit("SUPABASE_SERVICE_KEY not set (growth.env)")
    if args.test:
        return send_test(key, *args.test, address=args.address)
    if datetime.datetime.now(NY).hour not in SEND_HOURS and not args.dry_run:
        return print("casa: quiet hours, nothing sent until 8 AM")
    watches = rest("casa_watches?select=user_id,email,bbl,address,last_seen,last_sent,created_at,lat,lng,crime_kinds,crime_seen", key) or []
    now = datetime.datetime.now(datetime.timezone.utc)
    newest = ""
    if any(w.get("crime_kinds") for w in watches):
        try:
            newest = nypd_newest()
        except Exception as e:
            print(f"NYPD lookup failed ({type(e).__name__})")
    pushed = emailed = 0
    for w in watches:
        try:
            if not la.rpc("has_plus", {"uid": w["user_id"]}, key):
                continue
            last_sent = w.get("last_sent")
            if not last_sent or now - datetime.datetime.fromisoformat(last_sent.replace("Z", "+00:00")) >= MIN_GAP:
                p, e = run_311(w, key, now, args.dry_run)
                pushed += p; emailed += e
            p, e = run_crime(w, key, newest, args.dry_run)
            pushed += p; emailed += e
        except Exception as e:
            print(f"{w['bbl']}: failed ({type(e).__name__}: {str(e)[:80]})")
    print(f"casa: {len(watches)} watch(es), emailed {emailed}, pushed {pushed}")


if __name__ == "__main__":
    main()
