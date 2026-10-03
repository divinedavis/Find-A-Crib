#!/usr/bin/env python3
"""Xcode Organizer numbers before a ship (2026-10-02): what real phones on the
App Store / TestFlight builds reported to Apple — the same data as Xcode >
Organizer > Hangs, Disk Writes, Launches, Memory — read from the App Store
Connect API (read-only; the freeze does not apply).

  * diagnosticSignatures per recent build: the top hang / disk-write / launch
    signatures and how much of the build's reports each one is.
  * perfPowerMetrics for the app: launch time, hang rate, memory, by version.

Report only: a ship is never blocked on data Apple has not collected yet (a new
build needs days of real use before anything shows). ship.sh prints it so a
regression is seen before the next build goes out. Exit 0 always, unless the
API itself cannot be reached (exit 2), so a broken key is still noticed.

  ~/.venvs/spendcap/bin/python scripts/organizer_report.py [--builds 3]
"""
from __future__ import annotations
import argparse, sys
import requests
from asc_metadata import ASC, API, load_config

METRICS_ACCEPT = {"Accept": "application/vnd.apple.xcode-metrics+json"}
WANT = ("LAUNCH", "HANG", "MEMORY", "DISK", "TERMINATION")


def perf_metrics(asc, app_id):
    r = asc.s.get(f"{API}/apps/{app_id}/perfPowerMetrics", headers=METRICS_ACCEPT, timeout=60)
    if r.status_code != 200:
        return f"perfPowerMetrics: HTTP {r.status_code}"
    body = r.json()
    lines = [f"  REGRESSION: {i.get('summaryString') or i}" for i in body.get("insights", {}).get("regressions", [])]
    for prod in body.get("productData", []):
        for cat in prod.get("metricCategories", []):
            if not any(w in cat.get("identifier", "") for w in WANT):
                continue
            for m in cat.get("metrics", []):
                unit = (m.get("unit") or {}).get("displayName", "")
                for ds in m.get("datasets", [])[:1]:   # first dataset = all devices, typical percentile
                    pts = ds.get("points", [])[-3:]
                    vals = ", ".join(f"{p.get('version')}: {p.get('value')}" for p in pts)
                    if vals:
                        lines.append(f"  {cat['identifier']:<12} {m.get('identifier', ''):<28} {vals} {unit}")
    return "\n".join(lines) or "  (no field data yet — Apple needs days of real use per version)"


def signatures(asc, build_id):
    r = asc.s.get(f"{API}/builds/{build_id}/diagnosticSignatures", params={"limit": 10}, timeout=60)
    if r.status_code == 404:   # Apple has no reports for this build (yet)
        return ["    no reports yet"]
    if r.status_code != 200:
        return [f"    diagnosticSignatures: HTTP {r.status_code}"]
    rows = r.json().get("data", [])
    return [f"    {a['attributes'].get('diagnosticType', ''):<12} {a['attributes'].get('weight', 0):>5.1f}%  "
            f"{(a['attributes'].get('signature') or '')[:110]}" for a in rows] or ["    no hang/disk/launch signatures"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", type=int, default=3)
    a = ap.parse_args()
    cfg = load_config()
    try:
        asc = ASC(cfg)
        app_id = cfg["ASC_APP_ID"]
        builds = asc.get("/builds", **{"filter[app]": app_id, "sort": "-uploadedDate", "limit": a.builds,
                                        "fields[builds]": "version,uploadedDate"}).get("data", [])
    except (requests.RequestException, SystemExit, KeyError) as e:
        print(f"organizer report: App Store Connect unreachable ({e})", file=sys.stderr)
        return 2
    print("Xcode Organizer — field metrics (last 3 versions):")
    print(perf_metrics(asc, app_id))
    print("Xcode Organizer — diagnostic signatures by build:")
    for b in builds:
        print(f"  build {b['attributes']['version']} (uploaded {b['attributes']['uploadedDate'][:10]})")
        print("\n".join(signatures(asc, b["id"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
