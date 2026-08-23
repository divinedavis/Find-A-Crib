#!/usr/bin/env python3
"""Watch for a newer DHCR rent-stabilized building list and say so once it lands.

The building set under this whole site — all 47,165 of them — comes from one
annual publication, and nothing on the site would notice a new one. The lists are
named for the registration year, not the publication year: the file called "2024"
covers 2024 registrations "as of November 2025" and was posted that December. So
the 2025 list is due around November-December 2026, and the only way to catch it
without remembering is to look.

Source is the NYC Rent Guidelines Board, which republishes what DHCR issues.
hcr.ny.gov itself sits behind a Cloudflare challenge that answers a plain client
with 403, and RGB does not, so RGB is the practical source.

    python3 check_dhcr_list.py                  # report, exit 0
    python3 check_dhcr_list.py --email a@b.com  # email ONLY if a newer year exists
    python3 check_dhcr_list.py --have 2024      # override the year on disk
"""
import argparse
import datetime
import os
import re
import smtplib
import sys
import urllib.request
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).parent
PAGE = "https://rentguidelinesboard.cityofnewyork.us/resources/rent-stabilized-building-lists/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "Chrome/126 Safari/537.36")
BOROUGHS = ["Manhattan", "Brooklyn", "Bronx", "Queens", "Staten-Island"]


def have_year():
    """Newest year among the building-list PDFs sitting next to this script."""
    years = [int(m.group(1))
             for p in HERE.glob("*-DHCR-Bldg-File-*.pdf")
             if (m := re.match(r"(\d{4})-DHCR-Bldg-File-", p.name))]
    return max(years) if years else None


def published():
    """{year: {borough: url}} for every building-list PDF linked on the RGB page."""
    req = urllib.request.Request(PAGE, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", "replace")
    out = {}
    for url in re.findall(r'https://[^"\']+?\d{4}-DHCR-Bldg-File-[^"\']+?\.pdf', html):
        m = re.search(r"(\d{4})-DHCR-Bldg-File-([A-Za-z-]+)\.pdf", url)
        if m:
            out.setdefault(int(m.group(1)), {})[m.group(2)] = url
    return out


def send(to, subject, body):
    host = os.environ.get("SMTP_HOST")
    if not host:
        print("  ! no SMTP_HOST; printing instead of emailing")
        print(body)
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_USER", "findacrib@localhost")
    msg["To"] = to
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=30) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)
    print(f"  emailed {to}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", help="address to notify when a newer list is published")
    ap.add_argument("--have", type=int, help="override the newest year detected on disk")
    args = ap.parse_args()

    mine = args.have or have_year()
    if mine is None:
        sys.exit("no *-DHCR-Bldg-File-*.pdf next to this script; pass --have")

    try:
        avail = published()
    except Exception as e:
        # A source that has gone unreachable is not the same as no new list, and
        # must not read as "nothing to do" — exit non-zero so cron mail fires.
        sys.exit(f"could not read {PAGE}: {e}")
    if not avail:
        sys.exit(f"no building-list PDFs found on {PAGE} — the page layout probably changed")

    newest = max(avail)
    print(f"on disk: {mine}   published: {sorted(avail)}   newest: {newest}")
    if newest <= mine:
        print(f"Nothing newer. The {newest} list is the current one "
              f"(it covers {newest} registrations and is published the following December).")
        return

    missing = [b for b in BOROUGHS if b not in avail[newest]]
    lines = [
        f"DHCR has published the {newest} rent-stabilized building list.",
        f"The site is built from the {mine} list, so the building set is a year behind.",
        "",
        "Files:",
    ] + [f"  {b}: {u}" for b, u in sorted(avail[newest].items())]
    if missing:
        lines += ["", f"Not yet posted: {', '.join(missing)} — wait for the full set."]
    lines += [
        "",
        "To take it (from the repo, in order):",
        f"  curl -O <each url>            # into ~/projects/dhcr-map/",
        "  python3 parse_pdfs.py         # -> buildings.json",
        "  python3 geocode.py            # -> buildings_geo.json",
        "  python3 assign_nta.py         # -> buildings_geo_nta.json",
        "  python3 fetch_hpd.py          # full pull, the BBL set has changed",
        "  python3 slim.py               # -> buildings.min.json",
        "  python3 build_council.py      # re-join districts",
        "  python3 build_hpd_contacts.py && python3 build_research.py",
        "",
        "Expect the building count to move. Buildings leave the list as well as join it,",
        "so check the delta before publishing rather than assuming it only grows.",
    ]
    body = "\n".join(lines)
    print("\n" + body)
    if args.email:
        send(args.email, f"DHCR {newest} rent-stabilized building list is out", body)


if __name__ == "__main__":
    main()
