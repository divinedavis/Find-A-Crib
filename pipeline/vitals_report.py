#!/usr/bin/env python3
"""How fast findacrib.com was for real visits (owner, 2026-11-10).

static/platform/vitals.js sends each visit's timings as ranges to /vitals,
and nginx writes them to their own log with no address or browser details
(deploy/nginx, log_format fac_vitals): "<ISO time> p=nyc&lcp=1500-2500&...".
This prints, per measure, how many visits were good and how many poor.

    python3 pipeline/vitals_report.py                 # on the droplet: the last 7 days
    python3 pipeline/vitals_report.py --days 14 --map la
    python3 pipeline/vitals_report.py --remote        # from the Mac, over ssh
"""
from __future__ import annotations

import argparse
import glob
import gzip
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

LOGS = "/var/log/nginx/findacrib-vitals.log*"
HOST = "root@142.93.183.172"
NAMES = {"ttfb": "server answer", "fcp": "first paint", "lcp": "main content shown", "inp": "slowest tap", "cls": "layout shift"}
# At or under the first number is good, over the second is poor (web.dev/vitals).
LINES = {"ttfb": (800, 1800), "fcp": (1800, 3000), "lcp": (2500, 4000), "inp": (200, 500), "cls": (0.1, 0.25)}


def upper(rng: str) -> float:
    """A range's upper edge ("1500-2500" -> 2500); the open top range has none."""
    return float("inf") if rng.endswith("+") else float(rng.split("-")[1])


def parse(lines, since: datetime):
    """Each visit's fields, for lines written since `since`."""
    for line in lines:
        stamp, _, query = line.strip().partition(" ")
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if when < since:
            continue
        fields = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if fields:
            yield fields


def report(visits, only_map: str | None = None) -> dict:
    out = {"visits": 0, "repeat": 0, "installed": 0, "maps": Counter(), "measures": {}}
    ranges = defaultdict(Counter)
    for v in visits:
        if only_map and v.get("p") != only_map:
            continue
        out["visits"] += 1
        out["maps"][v.get("p", "?")] += 1
        out["repeat"] += v.get("r") == "1"
        out["installed"] += v.get("i") == "1"
        for k in NAMES:
            if k in v and (v[k].endswith("+") or "-" in v[k]):
                ranges[k][v[k]] += 1
    for k, counts in ranges.items():
        n = sum(counts.values())
        good, poor = LINES[k]
        out["measures"][k] = {
            "visits": n,
            "good_pct": round(100 * sum(c for r, c in counts.items() if upper(r) <= good) / n),
            "poor_pct": round(100 * sum(c for r, c in counts.items() if upper(r) > poor) / n),
            "ranges": dict(sorted(counts.items(), key=lambda kv: upper(kv[0]))),
        }
    return out


def read_logs(remote: bool) -> list[str]:
    if remote:
        cmd = f"for f in $(ls {LOGS} 2>/dev/null); do case $f in *.gz) zcat $f;; *) cat $f;; esac; done"
        return subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd], capture_output=True, text=True, check=True).stdout.splitlines()
    lines: list[str] = []
    for f in sorted(glob.glob(LOGS)):
        opener = gzip.open if f.endswith(".gz") else open
        with opener(f, "rt") as fh:
            lines.extend(fh)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--map", default=None, help="nyc, la, sf, dc, westchester, casa")
    ap.add_argument("--remote", action="store_true", help="read the droplet's log over ssh")
    a = ap.parse_args()
    since = datetime.now(timezone.utc) - timedelta(days=a.days)
    r = report(parse(read_logs(a.remote), since), a.map)
    print(f"findacrib.com speed, real visits, last {a.days} days: {r['visits']} visits · {r['repeat']} repeat · {r['installed']} from the installed site")
    if r["maps"]:
        print("  by map: " + " · ".join(f"{m} {n}" for m, n in r["maps"].most_common()))
    for k, m in r["measures"].items():
        print(f"  {NAMES[k]}: {m['good_pct']}% good · {m['poor_pct']}% poor ({m['visits']} visits; "
              + ", ".join(f"{rng}: {n}" for rng, n in m["ranges"].items()) + ")")


if __name__ == "__main__":
    main()
