#!/usr/bin/env python3
"""Email users when a building they saved was just advertised for rent.

Runs nightly on the caprecruiting droplet (167.71.170.219, next to
traffic_report.py, cron ~05:00 UTC — after the rent-map droplet's nightly
AffordableHousing scrape and the monthly Zumper refresh). Stdlib only.

How it decides "just advertised":
  1. Fetch the two public listing blobs from findacrib.com:
       listings.json  -> Zumper/StreetEasy ("zumper" source; sticky master)
       s8.json        -> AffordableHousing.com voucher listings ("s8" source)
  2. Diff each source's advertised-BBL set against the previous run's
     snapshot (alert_snapshot.json beside this script). Only BBLs that are
     advertised NOW but weren't LAST RUN count — so users who save an
     already-advertised building are not told it was "just" advertised.
  3. For each newly advertised BBL, email every user who saved it, unless
     they unsubscribed or were already notified for that (bbl, source) in
     the last 60 days (listing_alert_state in Supabase).

First run (no snapshot file) only seeds the snapshot and sends nothing.

Env: SUPABASE_ACCESS_TOKEN (management API; falls back to the macOS keychain
     locally), SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD.

Usage:
    python3 notify_saved_listings.py                # normal nightly run
    python3 notify_saved_listings.py --dry-run      # print, no email/DB writes
    python3 notify_saved_listings.py --test-email you@x.com --force-bbl <bbl>
                                                    # send one sample alert
"""
import argparse
import json
import os
import re
import smtplib
import subprocess
import sys
import time
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

SITE = "https://findacrib.com"
PROJECT_REF = "dbaifotzwlxjvsxjohjt"
QUERY_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
HERE = Path(__file__).parent
SNAPSHOT = HERE / "alert_snapshot.json"
BUILDINGS_CACHE = HERE / "buildings_cache.json"
BUILDINGS_CACHE_DAYS = 7
COOLDOWN_DAYS = 60
MAX_PER_EMAIL = 10

BORO_NAME = {"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens",
             "Bx": "the Bronx", "SI": "Staten Island"}
BORO_SLUG = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens",
             "Bx": "bronx", "SI": "staten-island"}
SOURCE_NAME = {"zumper": "Zumper", "s8": "AffordableHousing.com (Section 8)"}


# ---------- shared helpers (kept in sync with build_seo.py) ----------
def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
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
    return f"{SITE}/building/{BORO_SLUG.get(rec['b'], 'nyc')}/{slugify(rec.get('a'))}-{rec['bbl']}/"


def keychain(service):
    try:
        return subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""


def sb_query(token, sql):
    req = urllib.request.Request(
        QUERY_URL, data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "fac-alerts"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fac-alerts"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def load_buildings():
    """bbl -> {a, b, nb} map, cached because buildings.min.json is ~38 MB."""
    if BUILDINGS_CACHE.exists() and (
            time.time() - BUILDINGS_CACHE.stat().st_mtime
            < BUILDINGS_CACHE_DAYS * 86400):
        return json.loads(BUILDINGS_CACHE.read_text())
    recs = fetch_json(f"{SITE}/buildings.min.json")
    slim = {r["bbl"]: {"a": r.get("a"), "b": r.get("b"), "nb": r.get("nb")}
            for r in recs}
    BUILDINGS_CACHE.write_text(json.dumps(slim, separators=(",", ":")))
    return slim


def advertised_now():
    """Return {source: {bbl: {price, url}}} for both listing feeds."""
    out = {"zumper": {}, "s8": {}}
    listings = fetch_json(f"{SITE}/listings.json")
    for bbl, n in (listings.get("counts") or {}).items():
        if n and n > 0:
            out["zumper"][bbl] = {
                "price": (listings.get("prices") or {}).get(bbl),
                "url": (listings.get("urls") or {}).get(bbl),
            }
    s8 = fetch_json(f"{SITE}/s8.json")
    for bbl, av in (s8.get("avail") or {}).items():
        out["s8"][bbl] = {"price": av.get("p"), "url": av.get("url")}
    return out


# ---------- email rendering ----------
def render_email(items, token):
    """items: [{addr, boro, nb, price, url, bld_url, source}]. Returns (subj, text, html)."""
    first = items[0]
    if len(items) == 1:
        subject = f"{first['addr']} was just advertised for rent"
    else:
        subject = f"{len(items)} buildings you saved were just advertised"

    unsub = f"{SITE}/#unsub={token}"
    lines, rows = [], []
    for it in items[:MAX_PER_EMAIL]:
        price = f" — ${it['price']:,}/mo" if it.get("price") else ""
        where = f"{it['nb']}, {it['boro']}" if it.get("nb") else it["boro"]
        lines.append(f"* {it['addr']} ({where}){price}\n"
                     f"  Building: {it['bld_url']}"
                     + (f"\n  Listing:  {it['url']}" if it.get("url") else ""))
        rows.append(f"""
          <div style="border:1px solid #e3e8ef;border-radius:10px;padding:14px 16px;margin:0 0 10px">
            <div style="font-weight:700;font-size:16px;color:#1a1f36">{it['addr']}{price}</div>
            <div style="color:#5b6472;font-size:13px;margin:2px 0 8px">{where} · rent-stabilized building · via {SOURCE_NAME[it['source']]}</div>
            <a href="{it['bld_url']}" style="color:#1a63d6;font-weight:600;font-size:14px">View building →</a>
            {f'&nbsp;&nbsp;<a href="{it["url"]}" style="color:#1a63d6;font-size:14px">View the listing ↗</a>' if it.get('url') else ''}
          </div>""")
    more = len(items) - MAX_PER_EMAIL
    if more > 0:
        lines.append(f"...and {more} more — see your saved buildings: {SITE}/")
        rows.append(f'<div style="color:#5b6472;font-size:13px">…and {more} more — '
                    f'<a href="{SITE}/" style="color:#1a63d6">see all your saved buildings</a></div>')

    text = (
        f"Good news — {'a building you saved on Find A Crib was' if len(items) == 1 else 'buildings you saved on Find A Crib were'} "
        f"just advertised for rent:\n\n" + "\n\n".join(lines) +
        "\n\nRent-stabilized units move fast — reach out early.\n\n"
        f"—— Find A Crib · {SITE}\n"
        f"You get these alerts because you saved buildings on Find A Crib.\n"
        f"Unsubscribe: {unsub}\n")

    html = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px 16px;color:#1a1f36">
      <div style="font-weight:800;font-size:18px;color:#1a63d6;margin-bottom:4px">Find A Crib</div>
      <h2 style="font-size:20px;margin:0 0 6px">{'A building you saved was just advertised 🏠' if len(items) == 1 else f'{len(items)} buildings you saved were just advertised 🏠'}</h2>
      <p style="color:#5b6472;font-size:14px;margin:0 0 16px">Rent-stabilized units move fast — reach out early.</p>
      {''.join(rows)}
      <p style="color:#9aa3af;font-size:12px;margin-top:20px">
        You get these alerts because you saved buildings on
        <a href="{SITE}/" style="color:#9aa3af">Find A Crib</a>.
        <a href="{unsub}" style="color:#9aa3af">Unsubscribe</a>
      </p>
    </div>"""
    return subject, text, html


def send_email(to_addr, subject, text, html, dry=False):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASSWORD", "")
    if dry:
        print(f"[dry-run] would email {to_addr}: {subject}")
        return
    if not (user and pwd):
        sys.exit("missing SMTP_USER / SMTP_PASSWORD in environment")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Find A Crib <{user}>"
    msg["To"] = to_addr
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, pwd)
        server.sendmail(user, [to_addr], msg.as_string())
    print(f"emailed {to_addr}: {subject}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-email", default="",
                    help="send one sample alert to this address and exit")
    ap.add_argument("--force-bbl", default="",
                    help="with --test-email: pretend this bbl was just advertised")
    args = ap.parse_args()

    token = os.environ.get("SUPABASE_ACCESS_TOKEN") or keychain("supabase-pat-clockin")
    if not token:
        sys.exit("no SUPABASE_ACCESS_TOKEN (env) or supabase-pat-clockin (keychain)")

    current = advertised_now()
    buildings = load_buildings()

    def make_item(bbl, source):
        rec = buildings.get(bbl)
        if not rec:
            return None
        info = current[source].get(bbl, {})
        return {
            "addr": titlecase_addr(rec.get("a")),
            "boro": BORO_NAME.get(rec.get("b"), "New York"),
            "nb": rec.get("nb"),
            "price": info.get("price"),
            "url": info.get("url"),
            "bld_url": building_url({**rec, "bbl": bbl}),
            "source": source,
        }

    # ---------- test mode: one sample email, no snapshot/state writes ----------
    if args.test_email:
        bbl = args.force_bbl or next(iter(current["zumper"] or current["s8"]), None)
        source = "zumper" if bbl in current["zumper"] else "s8"
        item = make_item(bbl, source)
        if not item:
            sys.exit(f"bbl {bbl} not found in buildings blob")
        subject, text, html = render_email([item], token="test-token")
        send_email(args.test_email, subject, text, html, dry=args.dry_run)
        return

    # ---------- diff vs snapshot ----------
    current_sets = {s: sorted(current[s].keys()) for s in current}
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current_sets, separators=(",", ":")))
        print("no snapshot — seeded baseline, no emails sent "
              f"(zumper {len(current_sets['zumper'])}, s8 {len(current_sets['s8'])})")
        return
    prev = json.loads(SNAPSHOT.read_text())
    newly = {s: sorted(set(current_sets[s]) - set(prev.get(s, [])))
             for s in current_sets}
    n_new = sum(len(v) for v in newly.values())
    print(f"newly advertised: zumper {len(newly['zumper'])}, s8 {len(newly['s8'])}")
    if n_new == 0:
        SNAPSHOT.write_text(json.dumps(current_sets, separators=(",", ":")))
        return

    all_new_bbls = sorted(set(newly["zumper"]) | set(newly["s8"]))
    bbl_list = ",".join(f"'{b}'" for b in all_new_bbls if re.fullmatch(r"\d{10}", b))
    if not bbl_list:
        SNAPSHOT.write_text(json.dumps(current_sets, separators=(",", ":")))
        return

    # ---------- who saved these buildings ----------
    rows = sb_query(token, f"""
        select sb.user_id, sb.bbl, u.email
        from saved_buildings sb
        join auth.users u on u.id = sb.user_id
        where sb.bbl in ({bbl_list})
          and u.email not like '%@example.com'
          and public.has_plus(sb.user_id)  -- alerts are a Plus ($4.99/mo) feature
    """)
    if not rows:
        print("no saved buildings match the newly advertised set")
        SNAPSHOT.write_text(json.dumps(current_sets, separators=(",", ":")))
        return

    user_ids = sorted({r["user_id"] for r in rows})
    uid_list = ",".join(f"'{u}'" for u in user_ids)

    # ensure every user has an unsubscribe token, then load prefs + state
    if not args.dry_run:
        sb_query(token, f"""
            insert into alert_prefs (user_id)
            select unnest(array[{uid_list}]::uuid[])
            on conflict (user_id) do nothing
        """)
    prefs = {p["user_id"]: p for p in sb_query(token, f"""
        select user_id, token, unsubscribed_at from alert_prefs
        where user_id in ({uid_list})
    """)}
    state = {(s["user_id"], s["bbl"], s["source"]) for s in sb_query(token, f"""
        select user_id, bbl, source from listing_alert_state
        where notified_at > now() - interval '{COOLDOWN_DAYS} days'
          and user_id in ({uid_list})
    """)}

    # ---------- build per-user digests ----------
    per_user = {}  # user_id -> {"email":, "items": [...]}
    for r in rows:
        uid, bbl, email = r["user_id"], r["bbl"], r["email"]
        pref = prefs.get(uid, {})
        if pref.get("unsubscribed_at"):
            continue
        for source in ("zumper", "s8"):
            if bbl not in newly[source]:
                continue
            if (uid, bbl, source) in state:
                continue
            item = make_item(bbl, source)
            if not item:
                continue
            per_user.setdefault(uid, {"email": email, "items": []})["items"].append(item)

    sent, state_rows = 0, []
    for uid, d in per_user.items():
        tok = prefs.get(uid, {}).get("token", "")
        subject, text, html = render_email(d["items"], tok)
        try:
            send_email(d["email"], subject, text, html, dry=args.dry_run)
            sent += 1
            for it in d["items"]:
                price = it["price"] if it.get("price") else "null"
                # bld_url ends with .../<slug>-<bbl>/ — recover the bbl
                bbl = it["bld_url"].rstrip("/").rsplit("-", 1)[-1]
                state_rows.append(f"('{uid}','{bbl}','{it['source']}',{price})")
        except Exception as e:
            print(f"FAILED emailing {d['email']}: {e}")

    if state_rows and not args.dry_run:
        sb_query(token, f"""
            insert into listing_alert_state (user_id, bbl, source, price)
            values {','.join(state_rows)}
            on conflict (user_id, bbl, source)
            do update set notified_at = now(), price = excluded.price
        """)
    if not args.dry_run:
        SNAPSHOT.write_text(json.dumps(current_sets, separators=(",", ":")))
    print(f"done: {sent} email(s) sent, {len(state_rows)} state row(s) recorded")


if __name__ == "__main__":
    main()
