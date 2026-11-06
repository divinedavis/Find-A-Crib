#!/usr/bin/env python3
"""Your Crib alerts: tell a Plus member about each new 311 call on the one
building they watch (owner, 2026-10-15), and anyone watching about the crime
kinds they picked (free since 2026-10-19).

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

Crime alerts are free (owner, 2026-10-19: "crime alerts should be free").
Plus is re-checked here (has_plus) on every run for the 311 part only: a
watch whose owner has let Plus lapse keeps its crime alerts, and its 311
alerts resume if they come back.

    python3 casa_alerts.py              # the cron run
    python3 casa_alerts.py --dry-run    # print, send and write nothing
"""
import argparse
import datetime
import json
import math
import os
import re
import sys
import urllib.parse
import time
import urllib.error
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


def socrata(url, q, tries=3):
    # NYC Open Data answers a stray 503 now and then (the app and web page
    # retry too): a busy moment gets two more tries.
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(q), timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if attempt == tries - 1 or not (e.code == 429 or e.code >= 500):
                raise
        except urllib.error.URLError:
            if attempt == tries - 1:
                raise
        time.sleep(1.5 * (attempt + 1))


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


# Each report the alert counted, listed (owner, 2026-11-06: "i dont think i
# actually see the listing of these robberies"). Suspect and victim fields
# are left out on purpose: they are in the NYPD file, but not what a tenant
# asked for, and a list of them reads as profiling.
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def tidy(s):
    s = (s or "").strip()
    return s[:1] + s[1:].lower() if s.isupper() else s


# Parts of the NYPD's pd_desc that say nothing to a tenant: the time-of-day
# split ("BURGLARY,RESIDENCE,NIGHT"), its own truncated "unclassified" and
# bare degree numbers ("ASSAULT 2,1,UNCLASSIFIED").
DETAIL_NOISE = {"DAY", "NIGHT", "UNKNOWN TIM", "UNKNOWN TIME", "UNCL", "UNCLASSIFIE", "UNCLASSIFIED", "UNCLASSIFI"}


# Only these kinds carry a detail worth reading; the rest are statute
# shorthand ("HARASSMENT 2,SUBD 3", "CRIMINAL MISCHIEF 4TH, UNCL").
DETAIL_KINDS = {"robbery", "burglary", "theft", "car_theft"}


def detail(kind, ofns, pd_desc):
    """"BURGLARY,RESIDENCE,UNKNOWN TIM" -> "residence"; "ROBBERY,BEGIN AS
    SHOPLIFTING" -> "begin as shoplifting"; FELONY ASSAULT -> "felony"."""
    if kind == "assault":
        return "felony" if ofns == "FELONY ASSAULT" else ""
    if kind not in DETAIL_KINDS:
        return ""
    parts = []
    for x in (pd_desc or "").split(",")[1:]:
        x = re.sub(r"\s+(DAY|NIGHT)$", "", x.strip())
        x = re.sub(r"^((PETIT|GRAND)\s+)?(OF\s+)?", "", x)
        if x and x.upper() not in DETAIL_NOISE and not x.isdigit():
            parts.append(x)
    return ", ".join(parts).lower()


def bearing(a_lat, a_lng, b_lat, b_lng):
    """Compass point from the building to the report: "NE"."""
    x = math.radians(b_lng - a_lng) * math.cos(math.radians((a_lat + b_lat) / 2))
    y = math.radians(b_lat - a_lat)
    return COMPASS[round((math.degrees(math.atan2(x, y)) % 360) / 45) % 8]


def crime_reports(lat, lng, kinds, after, through):
    """Every report behind crime_counts, newest first: dicts with kind (the
    CRIME_KINDS key), title, detail, date (YYYY-MM-DD), time ("20:00"),
    place, metres, dir and attempted."""
    out = []
    by_offense = {o: k for k in kinds if CRIME_KINDS[k][2] for o in CRIME_KINDS[k][2]}
    if by_offense:
        listed = ",".join("'" + o.replace("'", "''") + "'" for o in sorted(by_offense))
        rows = socrata(COMPLAINTS, {
            "$select": "cmplnt_num, cmplnt_fr_dt, cmplnt_fr_tm, ofns_desc, pd_desc, prem_typ_desc, crm_atpt_cptd_cd, latitude, longitude",
            "$where": (f"within_circle(lat_lon, {lat}, {lng}, {RADIUS_M}) AND cmplnt_fr_dt > '{after}T23:59:59'"
                       f" AND cmplnt_fr_dt <= '{through}T23:59:59' AND ofns_desc in ({listed})"),
            "$order": "cmplnt_fr_dt DESC, cmplnt_fr_tm DESC", "$limit": "2000"})
        for r in rows:
            k = by_offense.get(r.get("ofns_desc"))
            if not k or not r.get("latitude"):
                continue
            b_lat, b_lng = float(r["latitude"]), float(r["longitude"])
            place = tidy(r.get("prem_typ_desc") if r.get("prem_typ_desc") not in (None, "(null)") else "")
            out.append({"kind": k, "title": CRIME_KINDS[k][0].capitalize(), "detail": detail(k, r.get("ofns_desc"), r.get("pd_desc")),
                        "date": (r.get("cmplnt_fr_dt") or "")[:10], "time": (r.get("cmplnt_fr_tm") or "")[:5],
                        "place": place.lower() if place else "",
                        "metres": round(metres(lat, lng, b_lat, b_lng)), "dir": bearing(lat, lng, b_lat, b_lng),
                        "attempted": (r.get("crm_atpt_cptd_cd") or "") == "ATTEMPTED"})
    if "shootings" in kinds:
        dlat, dlng = RADIUS_M / 111_000, RADIUS_M / (111_000 * math.cos(math.radians(lat)))
        rows = socrata(SHOOTINGS, {
            "$select": "incident_key, occur_date, occur_time, location_desc, latitude, longitude",
            "$where": (f"latitude between {lat - dlat} and {lat + dlat} AND longitude between {lng - dlng} and {lng + dlng}"
                       f" AND occur_date > '{after}T23:59:59' AND occur_date <= '{through}T23:59:59'"),
            "$limit": "500"})
        seen = set()
        for r in rows:
            if not (r.get("latitude") and r.get("longitude")):
                continue
            b_lat, b_lng = float(r["latitude"]), float(r["longitude"])
            m = metres(lat, lng, b_lat, b_lng)
            # One incident can be several rows (one per victim).
            if m > RADIUS_M or r.get("incident_key") in seen:
                continue
            seen.add(r.get("incident_key"))
            loc = r.get("location_desc")
            out.append({"kind": "shootings", "title": "Shooting", "detail": "",
                        "date": (r.get("occur_date") or "")[:10], "time": (r.get("occur_time") or "")[:5],
                        "place": tidy(loc).lower() if loc and loc not in ("(null)", "NONE") else "",
                        "metres": round(m), "dir": bearing(lat, lng, b_lat, b_lng), "attempted": False})
    out.sort(key=lambda r: (r["date"], r["time"]), reverse=True)
    return out


def report_line(r):
    """("Robbery — personal electronic device", "Aug 14 · 8:00 PM · chain store · 0.4 mi S")."""
    title = r["title"] + (f" — {r['detail']}" if r["detail"] else "") + (" (attempted)" if r["attempted"] else "")
    try:
        day = datetime.date.fromisoformat(r["date"]).strftime("%b %-d")
    except ValueError:
        day = r["date"]
    bits = [day]
    if r["time"]:
        try:
            bits.append(datetime.datetime.strptime(r["time"], "%H:%M").strftime("%-I:%M %p"))
        except ValueError:
            pass
    if r["place"]:
        bits.append(r["place"])
    bits.append(f"{r['metres'] / 1609.34:.1f}\u00a0mi\u00a0{r['dir']}")
    return title, " · ".join(bits)


EMAIL_REPORTS = 8


def crime_email(emailkit, bbl, address, counts, reports, after, through):
    """The crime alert's (html, text): the count, then each report listed,
    newest first, and a link to the full list on Your Crib."""
    title, body = crime_text(address, counts, after, through)
    link = f"{SITE}/casa/?bbl={bbl}&src=casa_crime#crime-list"
    rows = []
    for r in reports[:EMAIL_REPORTS]:
        head, sub = report_line(r)
        rows.append({"text": head, "sub": sub, "tone": "bad"})
    n = len(reports)
    blocks = [{"type": "building", "heading": address or "Your building", "meta": "Your building", "tone": "warn"}]
    if rows:
        more = f" — newest {len(rows)} of {n}" if n > len(rows) else ""
        blocks.append({"type": "callout", "heading": f"The reports{more}", "items": rows})
    return emailkit.render_alert(
        title=title, intro=body + ". From the NYPD's newest quarterly release. Locations are rounded to the block by the NYPD.",
        tag=("Your Casa", "warn"), blocks=blocks,
        cta=(f"See all {n} on Your Crib" if n > len(rows) else "See them on Your Crib", link),
        footer_note=f"You picked these crime alerts in Your Crib on Find A Crib. Change them any time: {SITE}/casa/")


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
    link = f"{SITE}/casa/?bbl={watch['bbl']}&src=casa_alert"
    rows = []
    for c in calls[-MAX_PER_ALERT:][::-1]:
        try:
            day = datetime.date.fromisoformat((c.get("created_date") or "")[:10]).strftime("%b %-d, %Y")
        except ValueError:
            day = (c.get("created_date") or "")[:10]
        status = (c.get("status") or "").title()
        rows.append({"text": label(c), "url": link,
                     "tone": "good" if status.lower() == "closed" else "bad",
                     "sub": f"{day} · {status}" + (" · pests" if is_pest(c) else "")})
    n = len(calls)
    # The alert-card design (owner, 2026-11-05): your building, the count
    # large, then each call as a row coloured by whether it is still open.
    open_n = sum(1 for c in calls if (c.get("status") or "").lower() != "closed")
    blocks = [{"type": "building", "heading": address, "meta": "Your building", "tone": "warn"},
              {"type": "big", "value": str(n), "sub": f"new 311 call{'s' if n != 1 else ''}"},
              {"type": "pills", "items": [(f"{open_n} still open", "bad") if open_n else ("All closed", "good")]},
              {"type": "callout", "heading": "The calls", "items": rows}]
    html, text = emailkit.render_alert(
        title=f"{n} new 311 call{'s' if n != 1 else ''} at your building.",
        intro="New calls the City published for the building you watch in Your Crib.",
        tag=("Your Casa", "warn"), blocks=blocks,
        cta=("See every call on your building", link),
        link=("File your own 311 complaint", "https://portal.311.nyc.gov/"),
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
            try:
                reports = crime_reports(w["lat"], w["lng"], kinds, seen, newest)
            except Exception as e:   # the count still goes out without the list
                print(f"   report list failed: {type(e).__name__}")
                reports = []
            html, text = crime_email(emailkit, w["bbl"], w.get("address"), counts, reports, seen, newest)
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
    kinds = ["shootings", "robbery", "burglary", "car_theft"]
    counts = crime_counts(float(lat), float(lng), kinds, after, newest)
    if any(counts.values()):
        title, body = crime_text(w["address"], counts, after, newest)
        from growth import emailkit
        reports = crime_reports(float(lat), float(lng), kinds, after, newest)
        html, text = crime_email(emailkit, bbl, w["address"], counts, reports, after, newest)
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
            last_sent = w.get("last_sent")
            if la.rpc("has_plus", {"uid": w["user_id"]}, key) and (not last_sent or now - datetime.datetime.fromisoformat(last_sent.replace("Z", "+00:00")) >= MIN_GAP):
                p, e = run_311(w, key, now, args.dry_run)
                pushed += p; emailed += e
            p, e = run_crime(w, key, newest, args.dry_run)
            pushed += p; emailed += e
        except Exception as e:
            print(f"{w['bbl']}: failed ({type(e).__name__}: {str(e)[:80]})")
    print(f"casa: {len(watches)} watch(es), emailed {emailed}, pushed {pushed}")


if __name__ == "__main__":
    main()
