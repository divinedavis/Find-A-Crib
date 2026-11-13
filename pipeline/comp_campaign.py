#!/usr/bin/env python3
"""Comp campaign: tell a hand-picked set of account holders that Find A Crib
Plus has been switched on for them, with a per-recipient tracked link.

The comp itself (subscriptions rows) is applied separately in the DB; this
script only sends the notification email.

CAN-SPAM (rewritten 2026-11-08). This is promotional mail, so every message:
  * carries a working one-click unsubscribe (List-Unsubscribe +
    List-Unsubscribe-Post headers and a footer link), using the account's
    alert_prefs token with k=lifecycle, the same opt-out as the account emails
    and founding_members.py;
  * ends with the postal address (emailkit.postal_text());
  * is never sent to anyone who has opted out, or to an address with no
    account token (no token = no working unsubscribe link = no send).
The September version sent from Gmail with a mailto unsubscribe pointing at a
caprecruiting.com address and no postal address. It also hard-coded customer
emails in the source. Recipients now come from a file that stays out of git.

Click tracking: each recipient's link is
  https://findacrib.com/?c=plus_comp&r=<token>
where token = sha256(email)[:10], so no state is stored. The pageview tracker
logs pathname+search, so a click shows up as a row whose path contains
r=<token>.

Usage:
    python3 pipeline/comp_campaign.py --recipients FILE --dry-run    # who would get it; sends nothing
    python3 pipeline/comp_campaign.py --test-email you@x.com         # one sample; unsubscribes nobody
    python3 pipeline/comp_campaign.py --recipients FILE --send       # send for real
FILE holds one email address per line (# comments allowed). Keep it out of
git: comp_recipients*.txt is gitignored.
"""
import argparse
import hashlib
import json
import smtplib
import subprocess
import sys
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # growth/ lives at the repo root
from growth import emailkit

SITE = "https://findacrib.com"
CAMPAIGN = "plus_comp"
SUBJECT = "Find A Crib Plus is on for your account"

# Who has already been mailed, so a re-run or a crash mid-batch can't send the
# same person the same note twice. A record of what this tool did, not product
# state, so it lives beside the script (gitignored).
# The repo root, not pipeline/: the log predates the move and stays where it was.
_ROOT = Path(__file__).resolve().parent
SENT_LOG = (_ROOT.parent if _ROOT.name == "pipeline" else _ROOT) / "comp_sent.json"

PROJECT_REF = "dbaifotzwlxjvsxjohjt"
QUERY_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
SMTP_HOST, SMTP_PORT = "mail.privateemail.com", 587
FROM_ADDR = "divine@findacrib.com"
FROM_NAME = "Divine at Find A Crib"
# A well-formed token that matches no account: the sample's unsubscribe link
# works and unsubscribes nobody.
SAMPLE_ACCOUNT_TOKEN = "00000000-0000-0000-0000-000000000000"

TEXT = """Hi there,

We noticed you've been back to Find A Crib a few times this week. Thanks for
that! As a thank-you, Find A Crib Plus is now switched on for your account, on
us. Nothing to enter, no card needed.

Plus gets you:

  * Rent alerts when a building you saved hits the market
  * Managing-agent phone numbers
  * Folders and saved searches
  * Owner research

It's already on. Just sign in: {link}

-- Divine, Find A Crib

--
You're getting this because you have a Find A Crib account.
Unsubscribe: {unsub}
{postal}
"""

HTML = """<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px 16px;color:#1a1f36">
  <div style="font-weight:800;font-size:18px;color:#1a63d6;margin-bottom:8px">Find A Crib</div>
  <h2 style="font-size:22px;margin:0 0 6px">You've got Plus, on us</h2>
  <p style="color:#5b6472;font-size:15px;margin:0 0 16px">
    We noticed you've been back a few times this week. Thanks for that!
    As a thank-you, <strong>Find A Crib Plus</strong> is now switched on for
    your account. Nothing to enter, no card needed.
  </p>
  <div style="border:1px solid #e3e8ef;border-radius:10px;padding:14px 16px;margin:0 0 18px">
    <div style="font-weight:700;font-size:15px;margin-bottom:8px">Plus gets you</div>
    <div style="font-size:14px;line-height:1.9;color:#1a1f36">
      Rent alerts when a building you saved hits the market<br>
      Managing-agent phone numbers<br>
      Folders and saved searches<br>
      Owner research
    </div>
  </div>
  <a href="{link}" style="display:inline-block;background:#1a63d6;color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:12px 22px;border-radius:10px">
    Open Find A Crib &rarr;
  </a>
  <p style="color:#5b6472;font-size:13px;margin:16px 0 0">It's already on. Just sign in.</p>
  <p style="color:#5b6472;font-size:13px;margin:22px 0 0">&mdash; Divine, Find A Crib</p>
  <p style="margin-top:26px;padding-top:12px;border-top:1px solid #e3e8ef;color:#9aa3af;font-size:12px">
    You&rsquo;re getting this because you have a Find A Crib account.
    <a href="{unsub}" style="color:#9aa3af">Unsubscribe</a><br>{postal}</p>
</div>"""


def keychain(service):
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def sb_query(token, sql):
    req = urllib.request.Request(
        QUERY_URL, data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "fac-comp-campaign"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def token_for(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:10]


def tracked_link(token: str) -> str:
    return f"{SITE}/?c={CAMPAIGN}&r={token}"


def build(click_token, account_token):
    """(subject, text, html, unsub_url) for one recipient."""
    link = tracked_link(click_token)
    unsub = emailkit.account_unsub_url(account_token, "lifecycle")
    postal = emailkit.postal_text()
    text = TEXT.format(link=link, unsub=unsub, postal=postal)
    html = HTML.format(link=emailkit.esc(link), unsub=emailkit.esc(unsub),
                       postal=emailkit.esc(postal))
    return SUBJECT, text, html, unsub


def send_email(to_addr, pw, click_token, account_token, dry=False):
    if dry:
        print(f"  [dry-run] would email {to_addr}")
        return
    subject, text, html, unsub = build(click_token, account_token)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_ADDR}>"
    msg["To"] = to_addr
    msg["Reply-To"] = FROM_ADDR
    msg["List-Unsubscribe"] = f"<{unsub}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo(); s.starttls(); s.ehlo()
        s.login(FROM_ADDR, pw)
        s.sendmail(FROM_ADDR, [to_addr], msg.as_string())
    print(f"  emailed {to_addr}")


def read_recipients(path):
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line and "@" in line and line not in out:
            out.append(line)
    return out


def sql_str(s):
    return "'" + s.replace("'", "''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipients", default="", help="file with one email address per line")
    ap.add_argument("--dry-run", action="store_true", help="show who would get it; send nothing")
    ap.add_argument("--test-email", default="", help="send one sample to this address")
    ap.add_argument("--send", action="store_true", help="send to the recipients for real")
    args = ap.parse_args()

    if args.test_email:
        pw = keychain("findacrib-smtp")
        if not pw:
            sys.exit("no findacrib-smtp in keychain")
        print(f"tracked link -> {tracked_link('test')}")
        send_email(args.test_email, pw, "test", SAMPLE_ACCOUNT_TOKEN)
        return 0

    if not (args.send or args.dry_run):
        sys.exit("nothing to do: pass --dry-run, --test-email, or --send")
    if not args.recipients:
        sys.exit("pass --recipients FILE (one email per line)")
    wanted = read_recipients(args.recipients)
    if not wanted:
        sys.exit(f"no email addresses in {args.recipients}")

    pat = keychain("supabase-pat-clockin")
    if not pat:
        sys.exit("no supabase-pat-clockin in keychain")
    pw = keychain("findacrib-smtp")
    if not pw and not args.dry_run:
        sys.exit("no findacrib-smtp in keychain")

    rows = sb_query(pat, f"""
        select lower(u.email) as email, p.token::text as token,
               p.lifecycle_unsubscribed_at is not null as opted_out
        from auth.users u
        left join public.alert_prefs p on p.user_id = u.id
        where lower(u.email) in ({",".join(sql_str(e) for e in wanted)})
    """)
    by_email = {r["email"]: r for r in rows}
    already = set(json.loads(SENT_LOG.read_text())) if SENT_LOG.exists() else set()

    to_mail = []
    for e in wanted:
        r = by_email.get(e)
        if r is None:
            print(f"  skip {e}: no Find A Crib account")
        elif r.get("opted_out"):
            print(f"  skip {e}: unsubscribed")
        elif not r.get("token"):
            print(f"  skip {e}: no account token, so no working unsubscribe link")
        elif e in already:
            print(f"  skip {e}: already mailed by this script")
        else:
            to_mail.append(r)
    print(f"{len(wanted)} listed · {len(to_mail)} to mail")

    for r in to_mail:
        send_email(r["email"], pw, token_for(r["email"]), r["token"], dry=args.dry_run)
        if not args.dry_run:
            already.add(r["email"])
            SENT_LOG.write_text(json.dumps(sorted(already), indent=1))
    if args.dry_run:
        print("(dry run: nothing sent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
