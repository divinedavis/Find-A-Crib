#!/usr/bin/env python3
"""Record which counter plate went where, and when.

    python3 scripts/placement.py add a1 "Sunshine Laundromat" --cross "Nostrand & Fulton"
    python3 scripts/placement.py list
    python3 scripts/placement.py remove a1 "Sunshine Laundromat"   # plate taken down
    python3 scripts/placement.py deploy                            # push to the droplet

Why this file exists at all: the scan counter reads nginx's redirect log, which
has no identity in it. Visits and events exclude the owner by visitor_id; a
redirect cannot, because there is nothing to exclude by. So every time the
owner scans a proof to check it, that lands in the same column a customer
would — and it lands as a scan with no engagement, which is precisely the
number the A/B verdict divides by. On this project that failure has a name:
the Crease demand tile, which was entirely the owner's own testing.

A placement date fixes it without any tracking cleverness. A plate that is
sitting on a desk has no customers by definition, so scans before it went out
are tests. The date is a fact the owner has anyway — he was standing there.

The code identifies the ROOM, not the shop: several laundromats share a1,
because nothing would be done differently for one over another. So this file
maps one code to many shops, and attribution stays at the room level. Wanting
per-shop numbers means cutting per-shop codes (a10, a11 — nginx already allows
three digits), and accepting that a plate is then useless if it moves.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
STORE = HERE / "marketing" / "signage" / "placements.json"
HOST = "root@104.236.120.144"
REMOTE = "/root/Find-A-Crib/growth/placements.json"

# Kept in step with SIGNAGE_ARMS in api_server.py. Duplicated rather than
# imported because this script runs on a laptop and that module needs the
# server's environment; the check below is what keeps them honest.
VENUES = {
    "a1": "Laundromats",
    "a2": "Bodegas, delis and corner stores",
    "a3": "Barbershops, hair and nail salons",
    "a4": "Check cashing, money transfer and tax preparers",
    "a5": "Pharmacy pickup counters",
    "a6": "Repair counters — phone, shoe, tailoring, dry cleaning",
    "a7": "Public library branches and community centres",
    "a8": "Tenant associations, mutual-aid tables, senior centres",
    "a9": "Immigrant-serving groceries, halal butchers, bakeries",
}


def load():
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return {"placements": []}


def save(d):
    STORE.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def today():
    return datetime.date.today().isoformat()


def cmd_add(a):
    d = load()
    code = a.code.lower()
    if code not in VENUES and not a.force:
        sys.exit(f"{code} is not one of the cut plates ({', '.join(VENUES)}). "
                 "Use --force if you really cut a new one.")
    for p in d["placements"]:
        if p["code"] == code and p["store"].lower() == a.store.lower() and not p.get("removed"):
            sys.exit(f"{code} is already recorded at {p['store']} since {p['placed']}.")
    d["placements"].append({
        "code": code,
        "venue": VENUES.get(code, ""),
        "store": a.store,
        "cross": a.cross or "",
        "placed": a.date or today(),
        "removed": None,
        "notes": a.notes or "",
    })
    save(d)
    print(f"recorded: {code} -> {a.store} on {a.date or today()}")
    print("run `python3 scripts/placement.py deploy` to make the dashboard use it")


def cmd_remove(a):
    d = load()
    for p in d["placements"]:
        if p["code"] == a.code.lower() and p["store"].lower() == a.store.lower() \
                and not p.get("removed"):
            p["removed"] = a.date or today()
            save(d)
            print(f"marked down: {p['code']} at {p['store']} on {p['removed']}")
            return
    sys.exit("no live placement matches that code and store.")


def cmd_list(a):
    d = load()
    rows = d["placements"]
    if not rows:
        print("nothing placed yet — every scan in the log is a test.")
        return
    for p in sorted(rows, key=lambda r: (r["code"], r["placed"])):
        state = f"removed {p['removed']}" if p.get("removed") else "live"
        where = f"{p['store']}" + (f" ({p['cross']})" if p.get("cross") else "")
        print(f"  {p['code']:<4} {p['placed']}  {state:<16} {where}")
    live = [p for p in rows if not p.get("removed")]
    print(f"\n{len(live)} live, {len(rows) - len(live)} taken down, "
          f"{len({p['code'] for p in live})} of {len(VENUES)} rooms covered")


def cmd_deploy(a):
    subprocess.run(["scp", "-q", str(STORE), f"{HOST}:{REMOTE}"], check=True)
    print(f"copied to {HOST}:{REMOTE}")
    print("the dashboard picks it up on the next load — no restart needed")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="record a plate going onto a counter")
    p.add_argument("code"); p.add_argument("store")
    p.add_argument("--cross", help="cross streets, so you can find it again")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.add_argument("--notes"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("remove", help="record a plate coming back down")
    p.add_argument("code"); p.add_argument("store"); p.add_argument("--date")
    p.set_defaults(fn=cmd_remove)

    sub.add_parser("list", help="what is out there").set_defaults(fn=cmd_list)
    sub.add_parser("deploy", help="copy to the droplet").set_defaults(fn=cmd_deploy)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
