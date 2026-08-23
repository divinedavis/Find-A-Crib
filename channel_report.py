#!/usr/bin/env python3
"""Where visitors actually came from, for channels a referrer cannot see.

A comment on TikTok reading "use findacrib.com" is untrackable by construction:
the reader types the domain into their own browser, so document.referrer is empty
and the visit is indistinguishable from someone who had the site bookmarked. Of
2,825 recorded visits, 2,023 already carry no referrer at all.

Two signals do survive, and this reports both:

  1. Tagged entry (reliable). nginx serves /tt, /ig, /yt, /rd as 302s to
     /?src=<channel>, and the tracking snippet records location.search, so the
     tag lands in visits.path. Post the tagged short link, not the bare domain.

  2. In-app browser (partial). If TikTok linkifies the domain and the reader taps
     it, the page opens inside TikTok's own webview, whose User-Agent carries
     AppName/aweme + BytedanceWebview. Only nginx sees the UA, so this half comes
     from the access log. It catches taps and misses typed visits, which makes it
     a floor, never a total. Bytespider — ByteDance's crawler — is excluded; it
     is a bot, and it is most of what matches a naive grep for "bytedance".

    python3 channel_report.py                    # both halves, last 30 days
    python3 channel_report.py --days 7
    python3 channel_report.py --log /var/log/nginx/findacrib.access.log
"""
import argparse
import datetime
import glob
import gzip
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter

# TikTok's in-app webview. aweme is the app's internal name; musical_ly is the
# legacy one and still appears. Bytespider is deliberately absent — crawler.
INAPP = {
    "tiktok": re.compile(r"aweme|musical_ly|BytedanceWebview|TTWebView", re.I),
    "instagram": re.compile(r"\bInstagram\b", re.I),
    "facebook": re.compile(r"\bFB(AN|AV|_IAB)\b", re.I),
    "snapchat": re.compile(r"\bSnapchat\b", re.I),
    "linkedin": re.compile(r"\bLinkedInApp\b", re.I),
}
BOT = re.compile(r"Bytespider|bot|crawler|spider|slurp|headless", re.I)
# host ip - - [23/Aug/2026:21:45:46 +0000] "GET /path HTTP/1.1" 200 162 "ref" "ua" ...
LINE = re.compile(r'^(\S+) (\S+) .*?\[([^\]]+)\] "(\w+) (\S+)[^"]*" (\d{3}) \S+ "([^"]*)" "([^"]*)"')


def env_from(path):
    """Read KEY=value pairs out of a shell env file without sourcing it."""
    out = {}
    if os.path.exists(path):
        for line in open(path):
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m:
                out[m.group(1)] = m.group(2).strip('"\'')
    return out


def tagged_visits(url, key, since):
    """Visits whose path carries a ?src= tag, grouped by channel."""
    q = (f"{url}/rest/v1/visits?select=path,visitor_id,created_at"
         f"&path=like.*src%3D*&created_at=gte.{since}&limit=10000")
    req = urllib.request.Request(q, headers={"apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=45) as resp:
        rows = json.loads(resp.read())
    by = {}
    for r in rows:
        m = re.search(r"[?&]src=([\w-]+)", r["path"] or "")
        if not m:
            continue
        c = by.setdefault(m.group(1), {"visits": 0, "visitors": set()})
        c["visits"] += 1
        c["visitors"].add(r["visitor_id"])
    return by


def read_log(paths, since_dt):
    for p in paths:
        opener = gzip.open if p.endswith(".gz") else open
        try:
            with opener(p, "rt", errors="replace") as f:
                for line in f:
                    m = LINE.match(line)
                    if not m:
                        continue
                    _, ip, ts, _, path, status, ref, ua = m.groups()
                    try:
                        when = datetime.datetime.strptime(ts.split()[0], "%d/%b/%Y:%H:%M:%S")
                    except ValueError:
                        continue
                    if when < since_dt:
                        continue
                    yield ip, path, status, ref, ua
        except OSError:
            continue


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--log", default="/var/log/nginx/findacrib.access.log")
    ap.add_argument("--env", default="/root/Find-A-Crib/growth.env")
    args = ap.parse_args()

    since_dt = datetime.datetime.utcnow() - datetime.timedelta(days=args.days)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"Since {since} ({args.days} days)\n")

    env = {**env_from(args.env), **os.environ}
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_KEY")
    print("TAGGED ENTRY  (/tt, /ig, /yt, /rd -> ?src=) — reliable")
    if not (url and key):
        print("  ! no SUPABASE_URL / SUPABASE_SERVICE_KEY; skipping")
    else:
        try:
            by = tagged_visits(url, key, since)
        except Exception as e:
            print(f"  ! query failed: {e}")
            by = {}
        if not by:
            print("  nothing yet — post the tagged link (findacrib.com/tt) rather than the")
            print("  bare domain, and every visit through it shows up here")
        for c, v in sorted(by.items(), key=lambda kv: -kv[1]["visits"]):
            print(f"  {c:<12} {v['visits']:>5} visits   {len(v['visitors']):>4} people")

    print("\nIN-APP BROWSER  (User-Agent, from nginx) — a floor, not a total")
    paths = sorted(glob.glob(args.log + "*"))
    if not paths:
        print(f"  ! no logs matching {args.log}*")
        return
    hits, people, bots = Counter(), {}, 0
    for ip, path, status, ref, ua in read_log(paths, since_dt):
        if BOT.search(ua):
            bots += 1
            continue
        for channel, pat in INAPP.items():
            if pat.search(ua):
                hits[channel] += 1
                people.setdefault(channel, set()).add(ip)
    if not hits:
        print("  no in-app browser sessions")
    for c, n in hits.most_common():
        print(f"  {c:<12} {n:>5} requests  {len(people[c]):>4} device(s)")
    print(f"  ({bots:,} bot requests excluded, Bytespider among them)")


if __name__ == "__main__":
    main()
