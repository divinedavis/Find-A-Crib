#!/usr/bin/env python3
"""
Build fmr.json: HUD Small-Area Fair Market Rents for every ZIP that has a
building, as {zip: [studio, 1BR, 2BR, 3BR]}. Cards/detail show an
"Est. $studio-$2BR/mo" range when a building has no active listing.

HUD publishes SAFMRs once per federal fiscal year, which starts 1 October, so the
fiscal year is derived rather than hard-coded: a hard-coded URL is why fmr.json
sat at the 2026-07-15 copy while a monthly cron ran happily beside it. A run
before HUD posts the new year's file falls back to the year already published and
says which one it used, so the fallback is visible in a log rather than silent.

  python3 build_fmr.py                          # write fmr.json next to this script
  python3 build_fmr.py --out /var/www/rent-map  # write it where the site reads it
"""
import argparse
import datetime
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import openpyxl

HERE = Path(__file__).parent
URL = "https://www.huduser.gov/portal/datasets/fmr/fmr{fy}/fy{fy}_safmrs.xlsx"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "Chrome/126 Safari/537.36")


def fiscal_year(today=None):
    """Federal FY: FY2027 begins 1 October 2026."""
    today = today or datetime.date.today()
    return today.year + 1 if today.month >= 10 else today.year


def fetch_safmr(fy):
    req = urllib.request.Request(URL.format(fy=fy), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def load_zips():
    """ZIPs that have a building. buildings.min.json is the one input present
    everywhere — the droplet has no geo intermediates."""
    for name, key in (("buildings.min.json", "z"), ("buildings_geo_nta.json", "zip")):
        p = HERE / name
        if p.exists():
            return {r[key] for r in json.loads(p.read_text()) if r.get(key)}
    raise SystemExit("need buildings.min.json (or buildings_geo_nta.json) to know which ZIPs matter")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(HERE), help="directory to write fmr.json into")
    ap.add_argument("--fy", type=int, help="override the fiscal year")
    args = ap.parse_args()

    zips_needed = load_zips()
    want = args.fy or fiscal_year()
    for fy in ([want] if args.fy else [want, want - 1]):
        try:
            xlsx = fetch_safmr(fy)
            break
        except urllib.error.HTTPError as e:
            if e.code != 404 or fy != want:
                raise
            print(f"  ! HUD has not posted FY{fy} yet ({e.code}); falling back to FY{fy - 1}")
    else:
        raise SystemExit("no SAFMR file found")

    ws = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # header: ZIP, area code, area name, then SAFMR + 90%/110% per bedroom
    out = {}
    for r in rows:
        z = str(r[0]).zfill(5)
        if z in zips_needed:
            try:
                out[z] = [int(r[3]), int(r[6]), int(r[9]), int(r[12])]  # 0/1/2/3 BR SAFMR
            except (TypeError, ValueError):
                pass

    if not out:
        raise SystemExit(f"FY{fy} sheet matched none of the {len(zips_needed)} ZIPs — "
                         "HUD probably changed the column layout; do not publish this")

    dest = Path(args.out) / "fmr.json"
    dest.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {dest}: FY{fy}, {len(out)} zips, {len(zips_needed - set(out))} missing")


if __name__ == "__main__":
    main()
