#!/usr/bin/env python3
"""
Find A Crib traffic dashboard.

Reads the page-view log (public.visits) and interaction log (public.events) in
the Supabase project and prints a traffic report: today's numbers, a
month-to-month table, the last 14 days, new-vs-returning, and week-over-week
retention (shown once at least two weeks of history exist).

The owner (divinejdavis@gmail.com) is always excluded -- both his signed-in
rows and any anonymous visitor_id he ever used while signed in.

Tracking began 2026-06-24 (rebrand day), so anything before that is empty.
"Visitor" = anonymous first-party localStorage id (fac_vid); a new
device/browser or cleared storage counts as a new visitor.

Usage:
  python3 traffic_report.py                 # full dashboard
  python3 traffic_report.py --json          # raw JSON (all sections)
"""
import argparse, json, subprocess, sys, urllib.request, urllib.error

PROJECT_REF = "dbaifotzwlxjvsxjohjt"
QUERY_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
OWNER = "af2629f7-1121-4bee-8a2b-cede9318c864"
TZ = "America/New_York"

# Common CTE: `v` = all visits minus the owner; `mine` = owner's visitor_ids.
CLEAN = (
    "with mine as (select distinct visitor_id from public.visits "
    f"where user_id = '{OWNER}'), "
    "v as (select * from public.visits "
    f"where user_id is distinct from '{OWNER}' "
    "and visitor_id not in (select visitor_id from mine))"
)
# Same idea for the events table.
CLEAN_E = (
    "with mine as (select distinct visitor_id from public.visits "
    f"where user_id = '{OWNER}'), "
    "e as (select * from public.events "
    f"where user_id is distinct from '{OWNER}' "
    "and visitor_id not in (select visitor_id from mine))"
)


def keychain(service):
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL).decode().strip()
    except subprocess.CalledProcessError:
        return None


def run_sql(token, sql):
    body = json.dumps({"query": sql}).encode()
    req = urllib.request.Request(
        QUERY_URL, data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 # Cloudflare 403s default scripting User-Agents.
                 "User-Agent": "curl/8.7.1"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"query failed ({e.code}): {e.read().decode()[:300]}")


def queries():
    today = f"(now() at time zone '{TZ}')::date"
    day_of = f"(created_at at time zone '{TZ}')::date"
    return {
        "today": f"{CLEAN} select count(*) as total_views, "
                 f"count(distinct visitor_id) as unique_visitors from v "
                 f"where {day_of} = {today};",
        "month_to_month": f"{CLEAN} select "
                 f"to_char((created_at at time zone '{TZ}'),'YYYY-MM') as month, "
                 f"count(*) as total_views, count(distinct visitor_id) as unique_visitors "
                 f"from v group by 1 order by 1;",
        "last_14_days": f"{CLEAN} select {day_of} as day, count(*) as total_views, "
                 f"count(distinct visitor_id) as unique_visitors from v "
                 f"where {day_of} >= {today} - 13 group by 1 order by 1;",
        "new_vs_returning_today": f"{CLEAN}, today_v as "
                 f"(select distinct visitor_id from v where {day_of} = {today}) "
                 f"select count(*) as total, count(*) filter (where exists "
                 f"(select 1 from v p where p.visitor_id = today_v.visitor_id "
                 f"and {day_of.replace('created_at','p.created_at')} < {today})) "
                 f"as returning_visitors from today_v;",
        "retention_wow": f"{CLEAN}, d as (select distinct visitor_id, "
                 f"{day_of} as day from v), "
                 f"prev as (select distinct visitor_id from d "
                 f"where day < {today} - 6 and day >= {today} - 13), "
                 f"cur as (select distinct visitor_id from d where day >= {today} - 6) "
                 f"select (select count(*) from prev) as prev_cohort, "
                 f"(select count(*) from prev p where exists "
                 f"(select 1 from cur c where c.visitor_id = p.visitor_id)) as returned;",
        "events_today": f"{CLEAN_E} select event, count(*) as n, "
                 f"count(distinct visitor_id) as visitors from e "
                 f"where {day_of} = {today} group by 1 order by n desc;",
    }


def pct(part, whole):
    return f"{(100.0 * part / whole):.0f}%" if whole else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="dump raw JSON")
    args = ap.parse_args()

    token = keychain("supabase-pat-clockin")
    if not token:
        sys.exit("missing keychain item supabase-pat-clockin")

    data = {name: run_sql(token, sql) for name, sql in queries().items()}

    if args.json:
        print(json.dumps(data, indent=2))
        return

    t = data["today"][0]
    nr = data["new_vs_returning_today"][0]
    ret = data["retention_wow"][0]

    print("=" * 52)
    print("  FIND A CRIB — TRAFFIC REPORT")
    print("=" * 52)

    print("\nTODAY")
    print(f"  Unique visitors : {t['unique_visitors']}")
    print(f"  Page views      : {t['total_views']}")
    print(f"  Returning       : {nr['returning_visitors']} "
          f"({pct(nr['returning_visitors'], nr['total'])} of today's visitors)")

    print("\nMONTH TO MONTH")
    print(f"  {'Month':<9}{'Visitors':>10}{'Views':>9}")
    for r in data["month_to_month"]:
        print(f"  {r['month']:<9}{r['unique_visitors']:>10}{r['total_views']:>9}")

    print("\nLAST 14 DAYS")
    print(f"  {'Day':<12}{'Visitors':>10}{'Views':>9}")
    for r in data["last_14_days"]:
        print(f"  {r['day']:<12}{r['unique_visitors']:>10}{r['total_views']:>9}")

    print("\nWEEK-OVER-WEEK RETENTION")
    if ret["prev_cohort"]:
        print(f"  Of last week's {ret['prev_cohort']} visitors, "
              f"{ret['returned']} returned this week "
              f"({pct(ret['returned'], ret['prev_cohort'])}).")
    else:
        print("  Not enough history yet (need a full prior week of data).")

    if data["events_today"]:
        print("\nTODAY'S ACTIVITY")
        for r in data["events_today"]:
            print(f"  {r['event']:<16}{r['n']:>5} events "
                  f"({r['visitors']} visitors)")
    print()


if __name__ == "__main__":
    main()
