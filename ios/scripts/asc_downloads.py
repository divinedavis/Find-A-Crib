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
        # Each DAILY instance carries TWO days: its own, and a revision of the
        # day before. So every date except the first and last appears in two
        # instances, and adding them up counted almost every day twice —
        # 86 first-time downloads where Apple showed 49 (2026-09-16).
        # Keep the newest instance's numbers for each date instead: the later
        # instance is Apple's revised figure, not an increment on the earlier
        # one. Instances are sorted ascending, so a later one simply wins.
        by_date = {}
        for i in inst:
            fresh = defaultdict(lambda: defaultdict(int))
            for url in segments(asc, i["id"]):
                for row in read_tsv(url):
                    d = row.get("Date") or row.get("date")
                    if not d: continue
                    latest = max(latest or d, d)
                    daily_row = fresh[d]
                    # column names per Apple's report schema
                    if key == "downloads":
                        kind = (row.get("Download Type") or "").lower()
                        n = int(float(row.get("Counts") or 0))
                        daily_row["downloads_total"] += n
                        if "first" in kind: daily_row["downloads_first"] += n
                        elif "redownload" in kind: daily_row["redownloads"] += n
                        elif "auto" in kind or "update" in kind: daily_row["updates"] += n
                    elif key == "discovery":
                        ev = (row.get("Event") or "").lower(); n = int(float(row.get("Counts") or 0))
                        if "impression" in ev: daily_row["impressions"] += n
                        elif "page view" in ev: daily_row["page_views"] += n
                        elif "tap" in ev or "download" in ev: daily_row["taps"] += n
                    elif key == "installs":
                        ev = (row.get("Event") or "").lower(); n = int(float(row.get("Counts") or 0))
                        if "install" in ev and "uninstall" not in ev and "delet" not in ev: daily_row["installs"] += n
                        elif "delet" in ev or "uninstall" in ev: daily_row["deletions"] += n
            for d, vals in fresh.items():
                by_date[d] = vals          # a later instance replaces an earlier one
        # merge this report's de-duplicated days in; the three reports
        # contribute different keys to the same date, so this stays additive
        for d, vals in by_date.items():
            for k, v in vals.items(): daily[d][k] += v
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
        # First-time downloads ONLY, so this equals the "App Units" figure on
        # App Store Connect's own home page. Apple's App Units exclude updates,
        # re-downloads, and a second device on the same Apple Account; adding
        # redownloads here made the dashboard read 1-2 higher than ASC and
        # invited exactly the "which number is right?" question (2026-09-16).
        pv, imp = s.get("page_views", 0), s.get("impressions", 0)
        dl = s.get("downloads_first", 0)
        s["downloads"] = dl
        s["conv_page_view"] = round(100.0 * dl / pv, 1) if pv else None
        s["conv_impression"] = round(100.0 * dl / imp, 1) if imp else None
        return s
    return {"d7": window(7), "d28": window(28), "all": window(DAYS)}


def live_build(asc, app_id):
    """(highest build on the App Store, every build that ever reached it).

    error_report.py on the droplet reads this: a failure on a NEWER build came
    from TestFlight, App Review or Apple's own post-upload launch — the owner
    and Apple, not users — and must not wake anyone up.
    """
    j = asc.get(f"/apps/{app_id}/appStoreVersions", include="build", limit="20")
    builds = {b["id"]: b["attributes"].get("version") for b in j.get("included", []) if b["type"] == "builds"}
    live = [builds.get((v["relationships"]["build"].get("data") or {}).get("id"))
            for v in j["data"] if v["attributes"].get("appStoreState") == "READY_FOR_SALE"]
    live = sorted({int(b) for b in live if b and str(b).isdigit()})
    return (max(live) if live else None), live


def main():
    cfg = m.load_config(); asc = m.ASC(cfg)
    try:
        daily, latest, used = pull(asc)
        payload = {"as_of": latest, "days": {d: dict(v) for d, v in sorted(daily.items())}, "summary": summarise(daily, latest),
                   "reports_used": used, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "note": None if latest else "Apple has not produced the first daily report yet (new request 2026-09-09; usually 1–2 days)."}
    except Exception as e:
        payload = {"as_of": None, "days": {}, "summary": {}, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": f"pull failed: {e}"[:300]}
    try:
        # live_build: the newest. released_builds: every build any App Store
        # version ever shipped — dashboard_metrics counts app users from these
        # builds only, so simulators and TestFlight never read as users.
        payload["live_build"], payload["released_builds"] = live_build(asc, cfg["ASC_APP_ID"])
    except Exception as e:
        payload["live_build"], payload["released_builds"] = None, []
        print("live_build lookup failed:", str(e)[:200])
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print("wrote", OUT, "as_of", payload["as_of"], payload.get("note") or "")
    if "--deploy" in sys.argv:
        p = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(OUT), DEPLOY], capture_output=True, text=True)
        print("deployed" if p.returncode == 0 else "scp failed: " + p.stderr[:200])


if __name__ == "__main__":
    main()
