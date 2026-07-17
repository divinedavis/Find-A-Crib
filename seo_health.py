#!/usr/bin/env python3
"""
Weekly SEO site-health crawl for Find A Crib.

Walks the sitemap and checks every URL for problems that quietly waste crawl
budget or drop pages from the index: non-200 status, redirect chains, and
missing canonical/title/h1. Checks ALL non-building pages (guides, hubs,
boroughs, neighborhoods, zips, listicles — a few thousand) plus a random
sample of building pages, so it's thorough without hammering all 47k weekly.

Emails a report ONLY when something is wrong (quiet weeks stay quiet), using
the same SMTP_* env vars as traffic_report.py.

  python3 seo_health.py                 # print report
  python3 seo_health.py --email a@b.com  # email only if issues found
  python3 seo_health.py --sample 800     # building-page sample size (default 500)
"""
import argparse, concurrent.futures, os, smtplib, sys, urllib.request, urllib.error, xml.etree.ElementTree as ET
from email.mime.text import MIMEText

SITE = "https://findacrib.com"
SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
UA = "findacrib-health/1.0 (+https://findacrib.com)"


def fetch(url, method="GET"):
    """Return (status, final_url, redirect_count, body_or_None). No auto-follow
    so we can count redirect hops ourselves."""
    hops = 0
    cur = url
    while hops < 6:
        req = urllib.request.Request(cur, method=method, headers={"User-Agent": UA})
        try:
            # opener that does NOT follow redirects
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k): return None
            opener = urllib.request.build_opener(NoRedirect)
            r = opener.open(req, timeout=20)
            body = r.read().decode("utf-8", "replace") if method == "GET" else None
            return r.status, cur, hops, body
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308):
                loc = e.headers.get("Location")
                if not loc:
                    return e.code, cur, hops, None
                cur = loc if loc.startswith("http") else SITE + loc
                hops += 1
                continue
            return e.code, cur, hops, None
        except Exception as e:
            return 0, cur, hops, f"ERR {e}"
    return 599, cur, hops, None  # redirect loop


def all_sitemap_urls():
    """Return {shard_name: [urls]} from the sitemap index."""
    _, _, _, idx = fetch(SITE + "/sitemap.xml")
    shards = {}
    if not idx:
        return shards
    root = ET.fromstring(idx)
    for sm in root.findall(f"{SM_NS}sitemap"):
        loc = sm.find(f"{SM_NS}loc").text
        name = loc.rsplit("/", 1)[-1]
        _, _, _, body = fetch(loc)
        urls = [u.find(f"{SM_NS}loc").text for u in ET.fromstring(body).findall(f"{SM_NS}url")] if body else []
        shards[name] = urls
    return shards


def check(url):
    status, final, hops, body = fetch(url)
    issues = []
    if status != 200:
        issues.append(f"HTTP {status}")
    if hops > 0:
        issues.append(f"{hops} redirect hop(s) -> {final}")
    # The homepage is the JS map app (an SPA) — it has a title but no static
    # <h1>, which is expected. Only run content-quality checks on the static
    # SEO pages, not the SPA.
    is_spa_home = url.rstrip("/") == SITE
    if body and not is_spa_home:
        if "<title>" not in body:
            issues.append("missing <title>")
        if "<h1" not in body:
            issues.append("missing <h1>")
        if 'rel="canonical"' not in body and "rel='canonical'" not in body:
            issues.append("missing canonical")
    return url, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="")
    ap.add_argument("--sample", type=int, default=500)
    args = ap.parse_args()

    shards = all_sitemap_urls()
    if not shards:
        sys.exit("could not read sitemap index")

    # Check ALL non-building pages; sample building pages (they're near-identical templates).
    to_check, building_pool = [], []
    for name, urls in shards.items():
        for u in urls:
            (building_pool if "/building/" in u else to_check).append(u)
    # deterministic sample (no random import — every Nth) so results are comparable week to week
    if building_pool:
        step = max(1, len(building_pool) // args.sample)
        to_check.extend(building_pool[::step])

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(check, to_check))

    broken = [(u, iss) for u, iss in results if iss]
    lines = [
        "=" * 52, "  FIND A CRIB — SEO SITE HEALTH", "=" * 52,
        f"\nChecked {len(to_check):,} URLs "
        f"({len(building_pool):,} building pages in pool, sampled every {max(1, len(building_pool)//args.sample)})",
        f"Non-building pages checked in full: {len(to_check) - min(len(building_pool), args.sample):,}",
        f"\nIssues found: {len(broken)}",
    ]
    if broken:
        lines.append("")
        for u, iss in broken[:200]:
            lines.append(f"  ⚠️  {u}\n        {'; '.join(iss)}")
    else:
        lines.append("\n✅ All checked pages are healthy (200, no redirect chains, title/h1/canonical present).")
    report = "\n".join(lines) + "\n"

    if args.email and broken:
        host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        user, pwd = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
        if not (user and pwd):
            sys.exit("missing SMTP creds")
        msg = MIMEText(report, "plain")
        msg["Subject"] = f"Find A Crib — SEO health: {len(broken)} issue(s)"
        msg["From"], msg["To"] = f"Find A Crib <{user}>", args.email
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
            s.starttls(); s.login(user, pwd)
            s.sendmail(user, [a.strip() for a in args.email.split(",")], msg.as_string())
        print(f"Emailed SEO health report ({len(broken)} issues) to {args.email}")
    else:
        print(report)
        if args.email:
            print("(no email sent — no issues found)")


if __name__ == "__main__":
    main()
