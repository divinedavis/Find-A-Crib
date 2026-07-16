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
  python3 traffic_report.py                       # full dashboard
  python3 traffic_report.py --json                # raw JSON (all sections)
  python3 traffic_report.py --email a@b.com,c@d   # email the dashboard
  python3 traffic_report.py --yesterday           # report on yesterday
                                                  # (the 6am daily email)

Email uses SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD from the
environment (same convention as payments_report.py on the caprecruiting box).
"""
import argparse, json, subprocess, sys, urllib.request, urllib.error

PROJECT_REF = "dbaifotzwlxjvsxjohjt"
QUERY_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
OWNER = "af2629f7-1121-4bee-8a2b-cede9318c864"
TZ = "America/New_York"

# ---- Business-metric inputs -------------------------------------------------
# Revenue is computed from the subscriptions table (active subs x price). The
# rest of the startup metrics (CAC, payback, gross margin, burn, runway) need
# numbers that live outside the database — set them here and keep them current.
PLUS_PRICE = 4.99          # $/mo per Plus subscriber (list price)
STRIPE_FEE = 0.30 + 0.029 * PLUS_PRICE   # Stripe's ~2.9% + $0.30 per charge
MONTHLY_AD_SPEND = 1500.0  # Google Ads: ~$50/day. Update if you change budget.
MONTHLY_COSTS = 150.0      # hosting + APIs (droplets, Supabase, Maps, etc.) — your COGS/opex estimate
CASH_ON_HAND = 0.0         # set to your bank balance to compute burn rate & cash runway
ASSUMED_LIFETIME_MO = 12   # fallback avg subscriber lifetime when churn can't be measured yet
# -----------------------------------------------------------------------------

# Owner's visitor_ids: any anonymous id he ever used while signed in, learned
# from BOTH tables (a page load logs visits; the in-app 'signin' event logs
# events — either one is enough to map a device). visitor_id is not null guards
# the NOT IN <null> trap, which would silently drop every row.
MINE = (
    "select visitor_id from public.visits "
    f"where user_id = '{OWNER}' and visitor_id is not null "
    "union "
    "select visitor_id from public.events "
    f"where user_id = '{OWNER}' and visitor_id is not null"
)
# Common CTE: `v` = all visits minus the owner; `mine` = owner's visitor_ids.
CLEAN = (
    f"with mine as ({MINE}), "
    "v as (select * from public.visits "
    f"where user_id is distinct from '{OWNER}' "
    "and visitor_id not in (select visitor_id from mine))"
)
# Same idea for the events table.
CLEAN_E = (
    f"with mine as ({MINE}), "
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


def queries(day_offset=0):
    # day_offset=0 reports on today; 1 reports on yesterday (for the 6am
    # daily email, when "today" would be nearly empty).
    today = f"((now() at time zone '{TZ}')::date - {day_offset})"
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
        "signups": f"select count(*) as total_accounts, "
                 f"count(*) filter (where {day_of} = {today}) as new_today "
                 f"from auth.users where id != '{OWNER}';",
        # Signed-in users active on the report day who had ALSO been active on
        # an earlier day (revisit or re-login), with their activity count.
        # Activity = page views (visits) + interactions (events, incl. signin).
        "returning_users": f"{CLEAN_E}, "
                 f"acts as (select user_id, created_at from public.visits "
                 f"where user_id is not null and user_id is distinct from '{OWNER}' "
                 f"union all "
                 f"select user_id, created_at from e where user_id is not null), "
                 f"d as (select user_id, count(*) as n from acts "
                 f"where {day_of} = {today} group by 1), "
                 f"ret as (select d.user_id, d.n from d where exists "
                 f"(select 1 from acts p where p.user_id = d.user_id "
                 f"and {day_of.replace('created_at','p.created_at')} < {today})) "
                 f"select u.email, ret.n from ret "
                 f"join auth.users u on u.id = ret.user_id order by ret.n desc;",
        # Subscription state for the business metrics. active = paying now;
        # new_paying_mtd / churned_mtd bound the current calendar month so
        # churn and CAC reflect this month.
        "subs": f"select "
                 f"count(*) filter (where status in ('active','trialing')) as active, "
                 f"count(*) filter (where status = 'canceled') as canceled_total, "
                 f"count(*) filter (where status in ('active','trialing') "
                 f"and date_trunc('month', updated_at at time zone '{TZ}') "
                 f"= date_trunc('month', {today})) as new_paying_mtd, "
                 f"count(*) filter (where status = 'canceled' "
                 f"and date_trunc('month', updated_at at time zone '{TZ}') "
                 f"= date_trunc('month', {today})) as churned_mtd "
                 f"from public.subscriptions;",
    }


def pct(part, whole):
    return f"{(100.0 * part / whole):.0f}%" if whole else "n/a"


def money(x):
    return f"${x:,.2f}"


def business_metrics(data):
    """The startup/SaaS metrics: revenue from the DB, the rest from the
    config inputs at the top of this file. Returns a list of report lines."""
    s = data["subs"][0]
    total_users = data["signups"][0]["total_accounts"]
    active = s["active"]
    new_paying = s["new_paying_mtd"]
    churned = s["churned_mtd"]

    net_per_sub = PLUS_PRICE - STRIPE_FEE          # after Stripe fees
    mrr = active * PLUS_PRICE                        # gross monthly recurring revenue
    arr = mrr * 12
    arpu = (mrr / total_users) if total_users else 0.0     # revenue per signed-up user
    conv = pct(active, total_users)                  # free -> Plus
    # base at month start = active now minus those added this month, plus those churned this month
    base = max(active - new_paying + churned, 0)
    churn_rate = (churned / base) if base else None
    lifetime_mo = (1 / churn_rate) if churn_rate else ASSUMED_LIFETIME_MO
    ltv = net_per_sub * lifetime_mo                  # per paying customer, net of fees
    cac = (MONTHLY_AD_SPEND / new_paying) if new_paying else None
    gross_profit_per_sub = net_per_sub - (MONTHLY_COSTS / active if active else 0)
    payback_mo = (cac / gross_profit_per_sub) if (cac and gross_profit_per_sub > 0) else None
    gross_margin = ((mrr - MONTHLY_COSTS) / mrr) if mrr else None
    net_burn = (MONTHLY_COSTS + MONTHLY_AD_SPEND) - mrr   # cash out minus cash in, per month
    runway_mo = (CASH_ON_HAND / net_burn) if (net_burn > 0 and CASH_ON_HAND) else None
    net_new_arr = new_paying * PLUS_PRICE * 12
    burn_multiple = (net_burn / (net_new_arr / 12)) if net_new_arr else None

    def opt(v, fmt):  # format a value that may be un-computable yet
        return fmt(v) if v is not None else "n/a (need data)"

    out = ["\nBUSINESS METRICS"]
    out.append(f"  Active Plus subs   : {active}")
    out.append(f"  MRR                : {money(mrr)}   (ARR {money(arr)})")
    out.append(f"  ARPU               : {money(arpu)}/user   Free->Plus: {conv}")
    out.append(f"  New paying (MTD)   : {new_paying}     Churned (MTD): {churned}")
    out.append(f"  Churn rate (MTD)   : {opt(churn_rate, lambda v: f'{v*100:.1f}%')}")
    out.append(f"  LTV (net of fees)  : {money(ltv)}   (~{lifetime_mo:.0f} mo lifetime)")
    out.append(f"  CAC                : {opt(cac, money)}")
    out.append(f"  CAC payback        : {opt(payback_mo, lambda v: f'{v:.1f} mo')}")
    out.append(f"  Gross margin       : {opt(gross_margin, lambda v: f'{v*100:.0f}%')}")
    out.append(f"  Net burn / mo      : {money(net_burn)}")
    out.append(f"  Burn multiple      : {opt(burn_multiple, lambda v: f'{v:.2f}x')}")
    out.append(f"  Cash runway        : {opt(runway_mo, lambda v: f'{v:.1f} mo')}")
    if cac and ltv:
        out.append(f"  LTV : CAC ratio    : {ltv/cac:.1f} : 1  (>3:1 is healthy)")
    out.append(f"  [inputs: ad spend {money(MONTHLY_AD_SPEND)}/mo, costs {money(MONTHLY_COSTS)}/mo, "
               f"cash {money(CASH_ON_HAND)} — edit these in traffic_report.py]")
    return out


def render(data, day_label="TODAY"):
    """Build the plain-text dashboard from the query results."""
    t = data["today"][0]
    nr = data["new_vs_returning_today"][0]
    ret = data["retention_wow"][0]
    out = []
    out.append("=" * 52)
    out.append("  FIND A CRIB — TRAFFIC REPORT")
    out.append("=" * 52)

    out.append(f"\n{day_label}")
    out.append(f"  Unique visitors : {t['unique_visitors']}")
    out.append(f"  Page views      : {t['total_views']}")
    out.append(f"  Returning       : {nr['returning_visitors']} "
               f"({pct(nr['returning_visitors'], nr['total'])} of the day's visitors)")

    su = data["signups"][0]
    out.append("\nSIGNED-UP USERS")
    out.append(f"  Total accounts  : {su['total_accounts']}")
    out.append(f"  New this day    : {su['new_today']}")

    if data.get("subs"):
        out.extend(business_metrics(data))

    ru = data["returning_users"]
    out.append(f"\nRETURNING SIGNED-IN USERS ({len(ru)})")
    if ru:
        for r in ru:
            out.append(f"  {r['email']:<36}{r['n']:>4} actions")
    else:
        out.append("  None this day.")

    out.append("\nMONTH TO MONTH")
    out.append(f"  {'Month':<9}{'Visitors':>10}{'Views':>9}")
    for r in data["month_to_month"]:
        out.append(f"  {r['month']:<9}{r['unique_visitors']:>10}{r['total_views']:>9}")

    out.append("\nLAST 14 DAYS")
    out.append(f"  {'Day':<12}{'Visitors':>10}{'Views':>9}")
    for r in data["last_14_days"]:
        out.append(f"  {r['day']:<12}{r['unique_visitors']:>10}{r['total_views']:>9}")

    out.append("\nWEEK-OVER-WEEK RETENTION")
    if ret["prev_cohort"]:
        out.append(f"  Of last week's {ret['prev_cohort']} visitors, "
                   f"{ret['returned']} returned this week "
                   f"({pct(ret['returned'], ret['prev_cohort'])}).")
    else:
        out.append("  Not enough history yet (need a full prior week of data).")

    if data["events_today"]:
        out.append(f"\n{day_label}'S ACTIVITY")
        for r in data["events_today"]:
            out.append(f"  {r['event']:<16}{r['n']:>5} events "
                       f"({r['visitors']} visitors)")
    return "\n".join(out) + "\n"


def send_email(recipients, text):
    import os, smtplib
    from email.mime.text import MIMEText

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASSWORD", "")
    if not (user and pwd):
        sys.exit("missing SMTP_USER / SMTP_PASSWORD in environment")

    msg = MIMEText(text, "plain")
    msg["Subject"] = "Find A Crib — daily traffic report"
    msg["From"] = f"Find A Crib <{user}>"
    msg["To"] = ", ".join(recipients)
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, pwd)
        server.sendmail(user, recipients, msg.as_string())
    print(f"Emailed traffic report to: {', '.join(recipients)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="dump raw JSON")
    ap.add_argument("--email", default="", help="comma-separated recipient list")
    ap.add_argument("--yesterday", action="store_true",
                    help="report on yesterday instead of today "
                         "(for the 6am daily email)")
    args = ap.parse_args()

    # The PAT lives in the macOS keychain locally, or SUPABASE_ACCESS_TOKEN in
    # the environment (e.g. on the droplet cron).
    import os
    token = os.environ.get("SUPABASE_ACCESS_TOKEN") or keychain("supabase-pat-clockin")
    if not token:
        sys.exit("missing Supabase PAT (keychain supabase-pat-clockin "
                 "or env SUPABASE_ACCESS_TOKEN)")

    offset = 1 if args.yesterday else 0
    data = {name: run_sql(token, sql) for name, sql in queries(offset).items()}

    if args.json:
        print(json.dumps(data, indent=2))
        return

    text = render(data, "YESTERDAY" if args.yesterday else "TODAY")
    if args.email:
        recipients = [r.strip() for r in args.email.split(",") if r.strip()]
        send_email(recipients, text)
    else:
        print(text)


if __name__ == "__main__":
    main()
