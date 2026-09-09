#!/usr/bin/env python3
"""Pull Find A Crib's App Store numbers into appstore.json for the dashboard.

Reads the App Store Connect analytics reports (an ONGOING report request was
created 2026-09-09, id in REQUEST_ID): daily downloads/redownloads from
"App Downloads Standard", impressions and product page views from "App Store
Discovery and Engagement Standard", installs/deletions from "App Store
Installation and Deletion Standard". Apple produces one instance per day, one
to two days behind, so the file carries an "as of" date and the dashboard shows
it. A brand-new request has no instances for a day or two: the script then
writes an empty file with the reason rather than failing.

    ~/.venvs/dhcr-map/bin/python scripts/asc_downloads.py            # writes appstore.json next to this script
    ~/.venvs/dhcr-map/bin/python scripts/asc_downloads.py --deploy   # …and scp's it to the dashboard API

Runs from the Mac (the ASC key lives here, not on a public droplet) — see
launchd plist com.findacrib.asc-downloads.
"""
from __future__ import annotations
import csv, gzip, io, json, os, subprocess, sys, time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asc_metadata as m

REQUEST_ID = "2374db2c-d96b-49aa-ba66-8fe960e5e80f"
REPORTS = {
    "downloads":  "App Downloads Standard",
    "discovery":  "App Store Discovery and Engagement Standard",
    "installs":   "App Store Installation and Deletion Standard",
}
OUT = Path(__file__).resolve().parent / "appstore.json"
DEPLOY = "root@104.236.120.144:/root/findacrib-api/appstore.json"
DAYS = 60


def instances(asc, report_id):
    rows, url, params = [], f"{m.API}/analyticsReports/{report_id}/instances", {"limit": 200, "filter[granularity]": "DAILY"}
    while url:
        r = asc.s.get(url, params=params, timeout=30); params = None
        r.raise_for_status(); j = r.json(); rows += j["data"]; url = j.get("links", {}).get("next")
    return rows


def segments(asc, instance_id):
    r = asc.s.get(f"{m.API}/analyticsReportInstances/{instance_id}/segments", timeout=30); r.raise_for_status()
    return [d["attributes"]["url"] for d in r.json()["data"]]


def read_tsv(url):
    raw = requests.get(url, timeout=120).content
    try: raw = gzip.decompress(raw)
    except OSError: pass
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")), delimiter="\t"))


def pull(asc):
    reps = {d["attributes"]["name"]: d["id"] for d in asc.get(f"/analyticsReportRequests/{REQUEST_ID}/reports", limit=200)["data"]}
    daily = defaultdict(lambda: defaultdict(int)); latest = None; used = {}
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).date().isoformat()
    for key, name in REPORTS.items():
        rid = reps.get(name)
        if not rid: continue
        inst = [i for i in instances(asc, rid) if i["attributes"]["processingDate"] >= since]
        inst.sort(key=lambda i: i["attributes"]["processingDate"])
        used[key] = len(inst)
        for i in inst:
            for url in segments(asc, i["id"]):
                for row in read_tsv(url):
                    d = row.get("Date") or row.get("date")
                    if not d: continue
                    latest = max(latest or d, d)
                    # column names per Apple's report schema
                    if key == "downloads":
                        kind = (row.get("Download Type") or "").lower()
                        n = int(float(row.get("Counts") or 0))
                        daily[d]["downloads_total"] += n
                        if "first" in kind: daily[d]["downloads_first"] += n
                        elif "redownload" in kind: daily[d]["redownloads"] += n
                        elif "auto" in kind or "update" in kind: daily[d]["updates"] += n
                    elif key == "discovery":
                        ev = (row.get("Event") or "").lower(); n = int(float(row.get("Counts") or 0))
                        if "impression" in ev: daily[d]["impressions"] += n
                        elif "page view" in ev: daily[d]["page_views"] += n
                        elif "tap" in ev or "download" in ev: daily[d]["taps"] += n
                    elif key == "installs":
                        ev = (row.get("Event") or "").lower(); n = int(float(row.get("Counts") or 0))
                        if "install" in ev and "uninstall" not in ev and "delet" not in ev: daily[d]["installs"] += n
                        elif "delet" in ev or "uninstall" in ev: daily[d]["deletions"] += n
    return daily, latest, used


def summarise(daily, latest):
    def window(n):
        if not latest: return {}
        end = datetime.fromisoformat(latest).date(); start = end - timedelta(days=n - 1)
        s = defaultdict(int)
        for d, v in daily.items():
            dd = datetime.fromisoformat(d).date()
            if start <= dd <= end:
                for k, x in v.items(): s[k] += x
        s = dict(s)
        pv, imp, dl = s.get("page_views", 0), s.get("impressions", 0), s.get("downloads_first", 0) + s.get("redownloads", 0)
        s["downloads"] = dl
        s["conv_page_view"] = round(100.0 * dl / pv, 1) if pv else None
        s["conv_impression"] = round(100.0 * dl / imp, 1) if imp else None
        return s
    return {"d7": window(7), "d28": window(28), "all": window(DAYS)}


def main():
    cfg = m.load_config(); asc = m.ASC(cfg)
    try:
        daily, latest, used = pull(asc)
        payload = {"as_of": latest, "days": {d: dict(v) for d, v in sorted(daily.items())}, "summary": summarise(daily, latest),
                   "reports_used": used, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "note": None if latest else "Apple has not produced the first daily report yet (new request 2026-09-09; usually 1–2 days)."}
    except Exception as e:
        payload = {"as_of": None, "days": {}, "summary": {}, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": f"pull failed: {e}"[:300]}
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print("wrote", OUT, "as_of", payload["as_of"], payload.get("note") or "")
    if "--deploy" in sys.argv:
        p = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(OUT), DEPLOY], capture_output=True, text=True)
        print("deployed" if p.returncode == 0 else "scp failed: " + p.stderr[:200])


if __name__ == "__main__":
    main()
