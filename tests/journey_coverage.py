#!/usr/bin/env python3
"""Which things real visitors do are NOT covered by a user journey.

The journey suite is only as good as the list of journeys in it, and that list
was written from memory. This asks the events table what people actually did,
subtracts what tests/journeys.py declares it exercises (JOURNEY_EVENTS), and
prints the gaps ranked by how many people hit them — so the suite grows from
behaviour instead of from guesses.

    ~/.venvs/dhcr-map/bin/python tests/journey_coverage.py            # last 30 days
    ~/.venvs/dhcr-map/bin/python tests/journey_coverage.py --days 90
    ~/.venvs/dhcr-map/bin/python tests/journey_coverage.py --min-people 25

Needs SUPABASE_ACCESS_TOKEN (the PAT; ~/.zshrc exports it from the keychain).
Read-only: one aggregate query, no rows leave the database.

Exit status is the number of uncovered events above the threshold, so it can
gate a run if you ever want it to. It is NOT part of deploy_app.sh: a new event
is a prompt to write a journey, not a reason to block a deploy.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from journeys import JOURNEY_EVENTS, NON_JOURNEY_EVENTS  # noqa: E402

PROJECT = "dbaifotzwlxjvsxjohjt"


def token() -> str:
    t = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if t:
        return t
    # Same place ~/.zshrc reads it from, so this works in a bare shell too.
    p = subprocess.run(["security", "find-generic-password", "-a", os.environ.get("USER", ""),
                        "-s", "supabase-pat-clockin", "-w"], capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip()
    sys.exit("no SUPABASE_ACCESS_TOKEN and no keychain entry supabase-pat-clockin")


def query(sql: str):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{PROJECT}/database/query",
        data=json.dumps({"query": sql}).encode(),
        # Cloudflare 403s the default urllib agent — see the Supabase notes.
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json",
                 "User-Agent": "curl/8.7.1"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read() or b"null")
    if isinstance(out, dict):
        sys.exit(f"query failed: {out.get('message', out)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-people", type=int, default=5,
                    help="ignore events fewer than this many people did")
    a = ap.parse_args()

    covered = {e for evs in JOURNEY_EVENTS.values() for e in evs}
    rows = query(f"""
        select event, count(*) as n, count(distinct visitor_id) as people
          from public.events
         where created_at > now() - interval '{a.days} days'
         group by 1 order by 3 desc
    """)
    gaps = [r for r in rows
            if r["event"] not in covered
            and r["event"] not in NON_JOURNEY_EVENTS
            and int(r["people"]) >= a.min_people]

    print(f"{len(rows)} distinct events in the last {a.days} days; "
          f"{len(covered)} covered by {len(JOURNEY_EVENTS)} journeys")
    if gaps:
        print(f"\nNOT covered by any journey ({a.min_people}+ people):")
        for r in gaps:
            print(f"  {int(r['people']):6} people  {int(r['n']):8} events   {r['event']}")
        print("\nEach line is a journey worth writing. Add it to JOURNEY_EVENTS when you do.")
    else:
        print(f"\nEvery event {a.min_people}+ people did is covered by a journey.")

    # Journeys that claim an event nobody has ever fired: either the feature is
    # dead or the name drifted. Worth knowing; not a failure.
    seen = {r["event"] for r in rows}
    stale = sorted({e for e in covered if e not in seen})
    if stale:
        print(f"\nDeclared but never seen in {a.days} days (dead feature, or a renamed event):")
        for e in stale:
            print(f"  {e}")
    return len(gaps)


if __name__ == "__main__":
    sys.exit(main())
