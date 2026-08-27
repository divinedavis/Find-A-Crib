#!/usr/bin/env python3
"""Weekly refresh of the HPD violation + complaint counts inside buildings.min.json.

The building set itself comes from DHCR and changes once a year; what moves week to
week is HPD's record against those buildings. This updates only the `h` block and
leaves every other field alone, so it can run on the droplet, where the pipeline's
geo intermediates (buildings_geo_nta.json, buildings_hpd.json) do not exist and
slim.py therefore cannot run.

Why this exists at all: fetch_hpd.py was corrected on 2026-08-18 to stop counting
dismissed violations as open, and nothing re-ran it. Two months later the site was
still serving 3,206,291 open violations against a true 1,104,222 — wrong on 45,678
of 47,165 buildings — because no schedule owned this data.

    python3 refresh_hpd_counts.py                      # rebuild in place, next to this file
    python3 refresh_hpd_counts.py --docroot /var/www/rent-map
    python3 refresh_hpd_counts.py --dry-run            # fetch and report, write nothing
"""
import argparse, subprocess
import gzip
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import fetch_hpd

HERE = Path(__file__).parent

# slim.py drops "closed" from the banked counts because the frontend never reads
# it and it is derivable; match that exactly, or a refresh would quietly change
# the shape of the blob the map loads.
DROP_KEYS = {"closed"}


def counts_for(bbls):
    """Fetch fresh violation + complaint aggregates for these BBLs."""
    by_boro = defaultdict(list)
    for bbl in bbls:
        boroid, block, lot = fetch_hpd.bbl_to_parts(bbl)
        if boroid in fetch_hpd.BORO_NAME:
            by_boro[boroid].append((block, lot))

    print("Fetching HPD violations...")
    violations = fetch_hpd.fetch_violations(by_boro)
    print(f"  -> {len(violations):,} buildings with a violation record")

    print("Fetching HPD complaints...")
    complaints = fetch_hpd.fetch_complaints(bbls)
    print(f"  -> {len(complaints):,} buildings with a complaint record")
    return violations, complaints


def merge(records, violations, complaints):
    """Update each record's h.violations / h.complaints. Returns a change summary."""
    moved = {"violations": 0, "complaints": 0, "gained_h": 0}
    for r in records:
        bbl = r["bbl"]
        h = r.get("h")
        for key, src in (("violations", violations), ("complaints", complaints)):
            fresh = src.get(bbl)
            if fresh is None:
                # No record at all now. Drop a stale block rather than keep it:
                # a building whose last violation closed should read as clean.
                if h and key in h:
                    del h[key]
                    moved[key] += 1
                continue
            fresh = {k: v for k, v in fresh.items() if k not in DROP_KEYS}
            if h is None:
                h = r["h"] = {}
                moved["gained_h"] += 1
            if h.get(key) != fresh:
                moved[key] += 1
            h[key] = fresh
    return moved


def write_blob(records, path):
    """Write buildings.min.json + its .gz, atomically, preserving ownership."""
    path = Path(path)
    payload = json.dumps(records, separators=(",", ":"))
    st = os.stat(path) if path.exists() else None

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bmj-")
    with os.fdopen(fd, "w") as f:
        f.write(payload)
    if st:
        os.chown(tmp, st.st_uid, st.st_gid)
        os.chmod(tmp, st.st_mode & 0o777)
    os.replace(tmp, path)

    # nginx serves the .gz via gzip_static; a stale .gz next to a fresh .json is
    # the worst outcome here, because the compressed copy is the one that ships.
    gz = Path(str(path) + ".gz")
    fd, tmpgz = tempfile.mkstemp(dir=str(path.parent), prefix=".bmjgz-")
    os.close(fd)
    with open(path, "rb") as src, gzip.open(tmpgz, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    if st:
        os.chown(tmpgz, st.st_uid, st.st_gid)
        os.chmod(tmpgz, st.st_mode & 0o777)
    os.replace(tmpgz, gz)
    return path.stat().st_size, gz.stat().st_size


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docroot", default=str(HERE),
                    help="directory holding buildings.min.json (default: next to this script)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    args = ap.parse_args()

    blob = Path(args.docroot) / "buildings.min.json"
    if not blob.exists():
        sys.exit(f"no buildings.min.json in {args.docroot}")
    records = json.loads(blob.read_text())
    bbls = [r["bbl"] for r in records]
    print(f"{len(records):,} buildings from {blob}")

    before = sum(((r.get("h") or {}).get("violations") or {}).get("open", 0) for r in records)
    violations, complaints = counts_for(bbls)
    moved = merge(records, violations, complaints)
    after = sum(((r.get("h") or {}).get("violations") or {}).get("open", 0) for r in records)

    print(f"\nopen violations: {before:,} -> {after:,} ({after - before:+,})")
    print(f"records whose violation block changed: {moved['violations']:,}")
    print(f"records whose complaint block changed: {moved['complaints']:,}")

    # A refresh that empties the corpus is a broken fetch, not a quiet city. Bail
    # before writing rather than publish it — every count on the site reads this.
    if after == 0 and before > 0:
        sys.exit("REFUSING TO WRITE: every open violation vanished — treat as a failed fetch")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return
    size, gzsize = write_blob(records, blob)
    print(f"\nWrote {blob} ({size / 1024 / 1024:.2f} MB) "
          f"+ .gz ({gzsize / 1024 / 1024:.2f} MB)")

    # The app boots from buildings.slim.json, which is derived from the file we
    # have just rewritten. Leaving the split to the nightly SEO refresh would
    # serve a day of stale violation counts from a file that looks current.
    # Non-fatal: a failed split leaves the previous pair in place, and the app
    # falls back to buildings.min.json if they are missing entirely.
    try:
        subprocess.run([sys.executable,
                        str(Path(__file__).resolve().parent / "split_hpd.py"),
                        "--docroot", str(blob.parent)], check=True)
    except Exception as e:
        print(f"split_hpd.py failed ({e}) — buildings.slim.json is now STALE")


if __name__ == "__main__":
    main()
