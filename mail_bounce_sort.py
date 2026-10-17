"""Move bounce notices out of the findacrib.com mailbox INBOX into "Bounces".

Every alert, digest and nudge goes out from divine@findacrib.com, so every
dead address, full inbox or Apple relay rejection lands back in that INBOX as
a "Mail Delivery Subsystem" (or "Mail Delivery System" / MAILER-DAEMON)
notice: 109 of them between 9/10 and 10/16, burying the real mail. Private
Email's ManageSieve never answers (see the Marracat mail sorter), so a
server-side filter isn't possible; this runs from cron every 10 minutes
instead. Nothing else reads this INBOX, so moving is safe.

  python3 mail_bounce_sort.py            # move
  python3 mail_bounce_sort.py --dry-run  # count only
"""
import argparse
import imaplib
import os
import re

FOLDER = "Bounces"
# IMAP FROM matches the display name and the address, case-insensitively.
SENDERS = ("Mail Delivery", "MAILER-DAEMON", "postmaster@")


def imap_host():
    h = os.environ.get("IMAP_HOST") or os.environ["SMTP_HOST"]
    return re.sub(r"^smtp\.", "mail.", h)


def bounce_uids(M):
    uids = set()
    for s in SENDERS:
        typ, d = M.uid("SEARCH", None, "FROM", '"%s"' % s)
        if typ == "OK" and d and d[0]:
            uids.update(d[0].split())
    return sorted(uids, key=int)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    M = imaplib.IMAP4_SSL(imap_host())
    M.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
    if not a.dry_run:
        M.create(FOLDER)  # NO when it already exists; that's fine
        M.subscribe(FOLDER)
    M.select("INBOX", readonly=a.dry_run)
    uids = bounce_uids(M)
    if uids and not a.dry_run:
        typ, d = M.uid("MOVE", b",".join(uids).decode(), FOLDER)
        if typ != "OK":
            raise SystemExit("MOVE failed: %r" % d)
    if uids:
        print("%s %d bounce notice(s) -> %s" % ("would move" if a.dry_run else "moved", len(uids), FOLDER))
    M.logout()


if __name__ == "__main__":
    main()
