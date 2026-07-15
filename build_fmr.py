#!/usr/bin/env python3
"""
Build fmr.json: HUD Small-Area Fair Market Rents for every ZIP that has a
building, as {zip: [studio, 1BR, 2BR, 3BR]}. Cards/detail show an
"Est. $studio–$2BR/mo" range when a building has no active listing.

HUD refreshes SAFMRs each fiscal year (~October) — bump the URL and re-run:
  python3 build_fmr.py && scp fmr.json root@104.236.120.144:/var/www/rent-map/
"""
import json, urllib.request

URL = "https://www.huduser.gov/portal/datasets/fmr/fmr2026/fy2026_safmrs.xlsx"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"

import openpyxl, io

req = urllib.request.Request(URL, headers={"User-Agent": UA})
xlsx = urllib.request.urlopen(req).read()
zips_needed = {r["zip"] for r in json.load(open("buildings_geo_nta.json")) if r.get("zip")}
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
open("fmr.json", "w").write(json.dumps(out, separators=(",", ":")))
print(f"wrote fmr.json: {len(out)} zips, {len(zips_needed - set(out))} missing")
