#!/usr/bin/env python3
"""Split buildings.min.json into the part the map needs at boot and the rest.

Measured 2026-08-27: buildings.min.json is 17.4 MB raw / 2.30 MB gzipped, and
the whole of it is fetched and parsed before the map can draw a single pin —
DOMContentLoaded 5.6 s on a mobile viewport. Roughly half of that weight is the
`h` blob, and almost none of `h` is needed until somebody opens a building.

Four fields are read on the eager path — the violation/complaint filters, the
list sort, the card line, the health badge and the agent card:

    h.violations.open   h.violations.c   h.complaints.open   h.op

Everything else (all-time totals, the a/b/c and oa/ob/oc class breakdowns,
last_12mo, lastregistration, bid) is only ever read by the detail sheet, which
already lazy-loads its operator contacts. So it can arrive the same way.

Writes, next to the source:
    buildings.slim.json  — every field except the unused half of `h`  (~1.1 MB gz)
    buildings.hpd.json   — {bbl: full h}, fetched on the first detail open

buildings.min.json is left exactly as it is: refresh_hpd_counts.py rewrites it
weekly in place and must keep working untouched, and it stays the fallback the
app boots from if these two files are ever missing.

Usage:  python3 split_hpd.py [--docroot DIR]
"""
import argparse, gzip, json, os, shutil, tempfile
from pathlib import Path

EAGER_VIOL = ("open", "c")
EAGER_COMP = ("open",)


def slim_h(h):
    if not h:
        return None
    v, c = h.get("violations") or {}, h.get("complaints") or {}
    out = {}
    sv = {k: v[k] for k in EAGER_VIOL if k in v}
    sc = {k: c[k] for k in EAGER_COMP if k in c}
    if sv:
        out["violations"] = sv
    if sc:
        out["complaints"] = sc
    if h.get("op"):
        out["op"] = h["op"]
    return out or None


def write_atomic(path, payload, mode_from=None):
    path = Path(path)
    st = os.stat(mode_from) if mode_from and os.path.exists(mode_from) else None
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".split-")
    with os.fdopen(fd, "w") as f:
        f.write(payload)
    if st:
        os.chown(tmp, st.st_uid, st.st_gid)
        os.chmod(tmp, st.st_mode & 0o777)
    os.replace(tmp, path)
    # nginx serves .gz via gzip_static; a stale .gz beside a fresh .json is the
    # worst outcome, because the compressed copy is the one that ships.
    gz = Path(str(path) + ".gz")
    fd, tmpgz = tempfile.mkstemp(dir=str(path.parent), prefix=".splitgz-")
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
    ap.add_argument("--docroot", default=os.path.dirname(os.path.abspath(__file__)),
                    help="directory holding buildings.min.json")
    args = ap.parse_args()
    src = Path(args.docroot) / "buildings.min.json"
    if not src.exists():
        raise SystemExit(f"no buildings.min.json in {args.docroot}")
    recs = json.loads(src.read_text())

    slim, full = [], {}
    for b in recs:
        h = b.get("h")
        if h:
            full[b["bbl"]] = h
        nb = {k: v for k, v in b.items() if k != "h"}
        sh = slim_h(h)
        if sh:
            nb["h"] = sh
        slim.append(nb)

    a, ag = write_atomic(Path(args.docroot) / "buildings.slim.json",
                         json.dumps(slim, separators=(",", ":")), src)
    b_, bg = write_atomic(Path(args.docroot) / "buildings.hpd.json",
                          json.dumps(full, separators=(",", ":")), src)
    orig = src.stat().st_size
    origgz = os.path.getsize(str(src) + ".gz") if os.path.exists(str(src) + ".gz") else 0
    print(f"buildings.min.json   {orig/1e6:6.2f} MB raw"
          + (f" / {origgz/1e6:5.2f} MB gz" if origgz else ""))
    print(f"buildings.slim.json  {a/1e6:6.2f} MB raw / {ag/1e6:5.2f} MB gz   <- boot payload")
    print(f"buildings.hpd.json   {b_/1e6:6.2f} MB raw / {bg/1e6:5.2f} MB gz   <- on first detail open")
    if origgz:
        print(f"boot payload is {(1 - ag/origgz)*100:.0f}% smaller gzipped")


if __name__ == "__main__":
    main()
