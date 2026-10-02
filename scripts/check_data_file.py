#!/usr/bin/env python3
"""Refuse to ship a data file that is broken or has lost a chunk of its rows.

    scripts/check_data_file.py la/buildings.slim.json /var/www/rent-map/la/buildings.slim.json

Checks, in order: the JSON parses; it is non-empty; the .gz beside it holds
the same bytes; and the row count is not more than 10% below the copy the
site is serving now (counted on the box, so nothing large is downloaded).
A real shrink — a city dropping a source on purpose — passes with
ALLOW_SHRINK=1. Called by deploy_city_data.sh before every scp.
"""
from __future__ import annotations

import gzip
import json
import os
import shlex
import subprocess
import sys

HOST = os.environ.get("FAC_HOST", "root@104.236.120.144")
MAX_DROP = 0.10


def rows(data) -> int:
    return len(data) if isinstance(data, (list, dict)) else 0


def main(local: str, remote: str) -> int:
    with open(local, "rb") as fh:
        raw = fh.read()
    try:
        n = rows(json.loads(raw))
    except ValueError as e:
        print(f"!! {local} is not valid JSON: {e}")
        return 1
    if n == 0:
        print(f"!! {local} has no rows")
        return 1
    gz = local + ".gz"
    if os.path.exists(gz):
        with gzip.open(gz, "rb") as fh:
            if fh.read() != raw:
                print(f"!! {gz} does not match {local}")
                return 1
    probe = ("import json,sys\ntry:\n d=json.load(open(sys.argv[1]))\n"
             " print(len(d) if isinstance(d,(list,dict)) else 0)\nexcept FileNotFoundError:\n print(-1)")
    out = subprocess.run(["ssh", HOST, "python3", "-", shlex.quote(remote)],
                         input=probe, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        print(f"!! could not count the live {remote}: {out.stderr.strip()}")
        return 1
    live = int(out.stdout.strip())
    if live <= 0:
        print(f"   {local}: {n:,} rows (nothing live yet)")
        return 0
    drop = (live - n) / live
    print(f"   {local}: {n:,} rows vs {live:,} live ({-drop:+.1%})")
    if drop > MAX_DROP and os.environ.get("ALLOW_SHRINK") != "1":
        print(f"!! {local} lost {drop:.0%} of its rows — not shipping (ALLOW_SHRINK=1 if that is intended)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
