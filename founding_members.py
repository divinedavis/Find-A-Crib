#!/usr/bin/env python3
"""Grant Find A Crib Plus to every account that doesn't have it, and tell them.

A one-off: 27 accounts exist, 17 have no Plus, and the whole product has 6 saves
across 4 users. The question this answers is not "will they pay" — it is "does
anyone use the paid features at all", which no amount of pricing work can tell
you while the features sit behind a wall nobody has walked through.

Grants are written as `plan='founding'` with `current_period_end = NULL`
(permanent). The plan tag matters: `subscriptions` already mixes 'comp',
'referral' and real 'plus' rows, and exactly ONE row is a paying Stripe
customer. Tagging these 'founding' keeps a comped account from ever being
counted as revenue. has_plus() only looks at status and period end, so the tag
costs nothing functionally.

If a founding member later subscribes for real, the Stripe webhook upserts on
user_id and overwrites the row — which is the behaviour we want.

    python3 founding_members.py --dry-run          # who would get it, no writes
    python3 founding_members.py --test-email me@x  # one real email to me, no grants
    python3 founding_members.py --send             # grant + email for real

Credentials: SMTP password from the macOS keychain (`findacrib-smtp`), Supabase
management token from `supabase-pat-clockin`. Neither is ever in this file.
"""
import argparse
import json
import smtplib
import subprocess
import sys
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Who has already been mailed, so a re-run or a crash mid-batch can't send the
# same person a second free membership. Beside the script, not in the DB: this
# is a record of what this tool did, not product state.
SENT_LOG = Path(__file__).with_name("founding_sent.json")

PROJECT_REF = "dbaifotzwlxjvsxjohjt"
QUERY_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
SMTP_HOST, SMTP_PORT = "mail.privateemail.com", 587
FROM_ADDR = "divine@findacrib.com"
FROM_NAME = "Divine at Find A Crib"
SITE = "https://findacrib.com"


def keychain(service):
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def sb_query(token, sql):
    req = urllib.request.Request(
        QUERY_URL, data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "fac-founding"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


SUBJECT = "Free Find A Crib Paid Tier"

TEXT = """Hi,

You signed up for Find A Crib early. I've turned on Plus on your account -- free,
permanently, as a founding member. Nothing to enter, nothing to cancel, no card
on file.

Plus unlocks:

  * Email alerts when a building you saved gets advertised for rent
  * Managing-agent phone numbers, the ones HPD has on file
  * Owner and managing-agent portfolios -- every other building they run, with
    violation counts
  * Folders and saved searches

Two things worth doing while you're here:

  1. Save a building you actually care about -- https://findacrib.com
  2. Switch on email alerts in your profile

I'm giving these away because I want to know whether they're worth anything. If
you try Plus and it does nothing for you, hit reply and tell me -- that's worth
more to me than the $4.99.

-- Divine, Find A Crib
https://findacrib.com
"""

HTML = """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
            font-size:15px;line-height:1.6;color:#0a0a23;max-width:520px">
  <p>Hi,</p>
  <p>You signed up for Find A Crib early. I&rsquo;ve turned on <strong>Plus</strong> on your
     account &mdash; free, permanently, as a founding member. Nothing to enter, nothing to
     cancel, no card on file.</p>
  <p>Plus unlocks:</p>
  <ul style="padding-left:20px">
    <li>Email alerts when a building you saved gets advertised for rent</li>
    <li>Managing-agent phone numbers, the ones HPD has on file</li>
    <li>Owner and managing-agent portfolios &mdash; every other building they run, with
        violation counts</li>
    <li>Folders and saved searches</li>
  </ul>
  <p>Two things worth doing while you&rsquo;re here:</p>
  <ol style="padding-left:20px">
    <li><a href="https://findacrib.com" style="color:#2f57ff">Save a building</a> you
        actually care about</li>
    <li>Switch on email alerts in your profile</li>
  </ol>
  <p>I&rsquo;m giving these away because I want to know whether they&rsquo;re worth
     anything. If you try Plus and it does nothing for you, hit reply and tell me &mdash;
     that&rsquo;s worth more to me than the $4.99.</p>
  <p style="margin-top:22px">&mdash; Divine, Find A Crib<br>
     <a href="https://findacrib.com" style="color:#2f57ff">findacrib.com</a></p>
</div>"""


def send_email(to_addr, pw, dry=False):
    if dry:
        print(f"  [dry-run] would email {to_addr}")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = SUBJECT
    msg["From"] = f"{FROM_NAME} <{FROM_ADDR}>"
    msg["To"] = to_addr
    # A real Reply-To, because the mail asks for a reply and means it.
    msg["Reply-To"] = FROM_ADDR
    msg.attach(MIMEText(TEXT, "plain"))
    msg.attach(MIMEText(HTML, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo(); s.starttls(); s.ehlo()
        s.login(FROM_ADDR, pw)
        s.sendmail(FROM_ADDR, [to_addr], msg.as_string())
    print(f"  emailed {to_addr}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="grant Plus and email for real")
    ap.add_argument("--grant-only", action="store_true",
                    help="write the grants but send nothing — lets deliverability be "
                         "checked before 17 strangers get mail from a day-old domain")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-email", default="", help="send one sample to this address, no grants")
    args = ap.parse_args()
    if not (args.send or args.grant_only or args.dry_run or args.test_email):
        sys.exit("pass --dry-run, --test-email, --grant-only, or --send")

    pw = keychain("findacrib-smtp")
    if not pw and not args.dry_run:
        sys.exit("no findacrib-smtp in keychain")

    if args.test_email:
        send_email(args.test_email, pw)
        return 0

    token = keychain("supabase-pat-clockin")
    if not token:
        sys.exit("no supabase-pat-clockin in keychain")

    # Who gets the mail. Granting and sending were split so deliverability could
    # be checked first, which broke the obvious query: once the grants are in,
    # "accounts without Plus" is empty and the send would reach nobody. The
    # cohort is therefore defined by the tag the grant wrote, not by its absence.
    rows = sb_query(token, """
        select u.id::text as id, u.email
        from auth.users u
        left join public.subscriptions s on s.user_id = u.id
        where u.email is not null and u.email <> ''
          and (s.user_id is null                      -- never had a row: still to grant
               or not public.has_plus(u.id)           -- lapsed
               or s.plan = 'founding')                -- already granted by this script
        order by u.created_at
    """)
    already = set()
    if SENT_LOG.exists():
        already = set(json.loads(SENT_LOG.read_text()))
    fresh = [r for r in rows if r["email"] not in already]
    print(f"{len(rows)} in the founding cohort · {len(already)} already mailed · "
          f"{len(fresh)} to mail now")
    for r in fresh:
        print("  ", r["email"])
    rows_to_mail = fresh

    if args.dry_run:
        print("\n(dry run — no grants written, no email sent)")
        return 0

    # Grant first, so the email is true by the time it lands. Upsert, because a
    # user may hold a lapsed row from an earlier comp or a cancelled Stripe sub.
    ids = ",".join("'%s'::uuid" % r["id"] for r in rows)
    sb_query(token, f"""
        insert into public.subscriptions (user_id, status, plan, current_period_end, updated_at)
        select id, 'active', 'founding', null, now() from auth.users where id in ({ids})
        on conflict (user_id) do update
          set status = 'active', plan = 'founding',
              current_period_end = null, updated_at = now()
    """)
    check = sb_query(token, f"""
        select count(*) as n from auth.users u
        where u.id in ({ids}) and public.has_plus(u.id)
    """)
    print(f"granted: {check[0]['n']}/{len(rows)} now pass has_plus()")
    if check[0]["n"] != len(rows):
        sys.exit("grant did not take for every account — not sending")
    if args.grant_only:
        print("(--grant-only: no email sent)")
        return 0

    # Record each success as it happens, not at the end: a crash halfway through
    # must not make a re-run mail the first half a second time. A duplicate
    # "here's your free membership" is the one mistake this send can't take back.
    sent = failed = 0
    for r in rows_to_mail:
        try:
            send_email(r["email"], pw)
            sent += 1
            already.add(r["email"])
            SENT_LOG.write_text(json.dumps(sorted(already), indent=1))
        except Exception as e:
            failed += 1
            print(f"  FAILED {r['email']}: {type(e).__name__}: {str(e)[:100]}")
    print(f"\nsent {sent}, failed {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
