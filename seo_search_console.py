#!/usr/bin/env python3
"""
Search Console SEO report for Find A Crib (automations #1, #2, #5).

Pulls Google Search Console data via the Search Analytics API and emails a
report covering:
  #1  Weekly performance  — clicks, impressions, avg position, CTR, and the
                            week-over-week change; top queries and top pages.
  #2  Index coverage      — how many URLs are getting impressions (a proxy for
                            "indexed and serving"), flagged if it drops sharply.
  #5  Content-gap / trend — queries ranking on page 2 (positions 11-20): the
                            "almost there" pages worth expanding, plus the
                            month-over-month move in average position.

Auth: a Google Cloud service account with the Search Console API enabled, added
as a user on the findacrib.com property in Search Console. Point SC_KEY_FILE at
its JSON key (or store the JSON in keychain `rent-map-gsc-service-account`).

  python3 seo_search_console.py                 # print the report
  python3 seo_search_console.py --email a@b.com  # email it
  python3 seo_search_console.py --weekly|--monthly

Requires the `cryptography` package (for the service-account JWT signature):
  pip3 install cryptography
"""
import argparse, base64, datetime, json, os, smtplib, subprocess, sys
import urllib.request, urllib.error, urllib.parse
from email.mime.text import MIMEText

SITE_URL = "https://findacrib.com/"           # URL-prefix property in Search Console
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
TOKEN_URI = "https://oauth2.googleapis.com/token"
API = "https://searchconsole.googleapis.com/webmasters/v3/sites/" + urllib.parse.quote(SITE_URL, safe="") + "/searchAnalytics/query"


def load_key():
    """Service account JSON from SC_KEY_FILE, keychain, or env."""
    path = os.environ.get("SC_KEY_FILE")
    if path and os.path.exists(path):
        return json.load(open(path))
    try:
        blob = subprocess.check_output(
            ["security", "find-generic-password", "-s", "rent-map-gsc-service-account", "-w"],
            stderr=subprocess.DEVNULL).decode().strip()
        return json.loads(blob)
    except Exception:
        pass
    if os.environ.get("SC_KEY_JSON"):
        return json.loads(os.environ["SC_KEY_JSON"])
    sys.exit("no service-account key (set SC_KEY_FILE, keychain rent-map-gsc-service-account, or SC_KEY_JSON)")


def _b64(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=")


def access_token(key):
    """Sign a service-account JWT (RS256) and exchange it for an access token."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": key["client_email"], "scope": SCOPE, "aud": TOKEN_URI,
              "iat": now, "exp": now + 3600}
    signing_input = _b64(json.dumps(header).encode()) + b"." + _b64(json.dumps(claims).encode())
    priv = serialization.load_pem_private_key(key["private_key"].encode(), password=None)
    sig = priv.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = signing_input + b"." + _b64(sig)
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt.decode()}).encode()
    req = urllib.request.Request(TOKEN_URI, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urllib.request.urlopen(req).read())["access_token"]


def query(token, start, end, dimensions, row_limit=25, filters=None):
    body = {"startDate": start, "endDate": end, "dimensions": dimensions, "rowLimit": row_limit}
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req).read()).get("rows", [])
    except urllib.error.HTTPError as e:
        sys.exit(f"Search Console API error ({e.code}): {e.read().decode()[:300]}")


def totals(rows):
    c = sum(r["clicks"] for r in rows)
    i = sum(r["impressions"] for r in rows)
    p = (sum(r["position"] * r["impressions"] for r in rows) / i) if i else 0
    return c, i, p


def d(days_ago):
    return (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()


def build_report(token, monthly=False):
    out = ["=" * 52, "  FIND A CRIB — SEARCH CONSOLE SEO REPORT", "=" * 52]
    # GSC data lags ~2-3 days; use a window that ends 3 days ago.
    end, prev_end = d(3), d(10)
    span = 30 if monthly else 7
    start, prev_start = d(3 + span), d(10 + span)

    # #1 Weekly (or monthly) performance + WoW change
    cur = query(token, start, end, ["date"], row_limit=1000)
    prev = query(token, prev_start, prev_end, ["date"], row_limit=1000)
    cc, ci, cp = totals(cur)
    pc, pi, pp = totals(prev)
    def delta(a, b): return f"{'+' if a>=b else ''}{a-b:,}" + (f" ({'+' if a>=b else ''}{100*(a-b)/b:.0f}%)" if b else "")
    out.append(f"\n{'LAST 30 DAYS' if monthly else 'LAST 7 DAYS'} (vs prior period)")
    out.append(f"  Clicks       : {cc:,}   ({delta(cc, pc)})")
    out.append(f"  Impressions  : {ci:,}   ({delta(ci, pi)})")
    out.append(f"  Avg position : {cp:.1f}   (prev {pp:.1f})")
    out.append(f"  CTR          : {(100*cc/ci if ci else 0):.1f}%")

    # Top queries + pages
    tq = query(token, start, end, ["query"], row_limit=15)
    out.append("\nTOP QUERIES")
    out.append(f"  {'Query':<34}{'Clk':>5}{'Impr':>7}{'Pos':>6}")
    for r in tq:
        out.append(f"  {r['keys'][0][:33]:<34}{r['clicks']:>5}{r['impressions']:>7}{r['position']:>6.1f}")
    tp = query(token, start, end, ["page"], row_limit=10)
    out.append("\nTOP PAGES")
    for r in tp:
        out.append(f"  {r['keys'][0].replace(SITE_URL,'/')[:40]:<42}{r['clicks']:>4} clk  {r['impressions']:>6} impr")

    # #2 Index coverage proxy: distinct pages receiving impressions
    pages = query(token, start, end, ["page"], row_limit=25000)
    out.append("\nINDEX COVERAGE (proxy)")
    out.append(f"  Pages receiving impressions: {len(pages):,} of ~47,600 published")
    if len(pages) < 100:
        out.append("  ⚠️  Very few pages are serving — check indexing in Search Console (Pages report).")

    # #5 Content-gap: queries stuck on page 2 (positions 11-20) = quick wins
    gap = [r for r in query(token, start, end, ["query"], row_limit=200)
           if 10.5 <= r["position"] <= 20.5 and r["impressions"] >= 5]
    gap.sort(key=lambda r: -r["impressions"])
    out.append("\nPAGE-2 OPPORTUNITIES (rank 11-20 — worth a content boost)")
    if gap:
        for r in gap[:12]:
            out.append(f"  {r['keys'][0][:38]:<40}pos {r['position']:.1f}  {r['impressions']} impr")
    else:
        out.append("  None yet (need more impression history).")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="")
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--monthly", action="store_true")
    args = ap.parse_args()
    token = access_token(load_key())
    report = build_report(token, monthly=args.monthly)
    if args.email:
        host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        user, pwd = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
        if not (user and pwd):
            sys.exit("missing SMTP creds")
        msg = MIMEText(report, "plain")
        msg["Subject"] = f"Find A Crib — {'monthly' if args.monthly else 'weekly'} Search Console SEO report"
        msg["From"], msg["To"] = f"Find A Crib <{user}>", args.email
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
            s.starttls(); s.login(user, pwd)
            s.sendmail(user, [a.strip() for a in args.email.split(",")], msg.as_string())
        print(f"Emailed Search Console report to {args.email}")
    else:
        print(report)


if __name__ == "__main__":
    main()
