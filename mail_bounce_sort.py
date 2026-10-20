"""Move bounce notices out of the findacrib.com mailbox INBOX into "Bounces".

Every alert, digest and nudge goes out from divine@findacrib.com, so every
dead address, full inbox or Apple relay rejection lands back in that INBOX as
a "Mail Delivery Subsystem" (or "Mail Delivery System" / MAILER-DAEMON)
notice: 109 of them between 9/10 and 10/16, burying the real mail. Private
Email's ManageSieve never answers (see the Marracat mail sorter), so a
server-side filter isn't possible; this runs from cron every 10 minutes
instead. Nothing else reads this INBOX, so moving is safe.

Since 2026-10-20 it also COUNTS each notice before moving it (owner: "im
seeing a lot of delivery status notification (delay) emails, why?" — the
alert jobs kept mailing the same dead addresses every day). The bounced
address and why go to email_suppressions (db/0068) via email_bounce_record;
growth/emailkit.send() then skips suppressed addresses. A counted notice gets
the IMAP keyword $FacCounted, so nothing is counted twice.

  python3 mail_bounce_sort.py            # count + move
  python3 mail_bounce_sort.py --dry-run  # count only, write nothing
  python3 mail_bounce_sort.py --backfill # also count what is already in Bounces
"""
import argparse
import email
import imaplib
import json
import os
import re
import urllib.request

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


COUNTED = "$FacCounted"
OURS = re.compile(r"@findacrib\.com$", re.I)
# Gone for good: no such mailbox, no such domain, or full AND abandoned.
HARD = re.compile(r"\b5\.1\.\d+|\b5\.4\.4\b|does not exist|no such user|user unknown|unknown user|"
                  r"recipient address rejected|address rejected|DNS error|domain not found|"
                  r"no mx|nxdomain|does not accept mail|null mx|out of storage space and inactive|account (?:is )?disabled", re.I)


def classify(subject, status, diag):
    """'hard' (stop now), 'soft' (count; stop at 3) or None (not about one recipient)."""
    text = f"{status} {diag}"
    # About US, not them: Apple's Hide My Email relay refused divine@findacrib
    # ("unauthorized sender", 9/10-10/3, fixed since). Those people are fine.
    if re.search(r"unauthori[sz]ed sender|sender (?:address )?(?:rejected|denied|not (?:allowed|authori[sz]ed))|SPF|DMARC|DKIM", text, re.I):
        return None
    if HARD.search(text):
        return "hard"
    if re.search(r"\(delay\)", subject or "", re.I) or status.startswith("4") or re.search(r"\b4\.\d+\.\d+", text):
        return "soft"
    if status.startswith("5") or re.search(r"\b5\.\d+\.\d+", text):
        return "soft"   # a refusal we can't read as permanent: three strikes
    return None


def parse_bounce(raw):
    """(recipient, kind, reason) from one notice, or None."""
    msg = email.message_from_bytes(raw)
    subject = str(msg.get("Subject") or "")
    rcpt = status = diag = ""
    body = ""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "message/delivery-status":
            for block in part.get_payload() or []:
                rcpt = rcpt or re.sub(r"^rfc822;\s*", "", str(block.get("Final-Recipient") or block.get("Original-Recipient") or ""), flags=re.I)
                status = status or str(block.get("Status") or "")
                diag = diag or str(block.get("Diagnostic-Code") or "")
        elif ct == "text/plain":
            pl = part.get_payload(decode=True)
            if pl:
                body += pl.decode("utf-8", "replace")
    if not rcpt:
        found = [a for a in re.findall(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+", body) if not OURS.search(a)]
        rcpt = found[0] if found else ""
    if not diag:
        m = re.search(r"((?:[45]\d\d[ -])?[45]\.\d+\.\d+.{0,200})", body)
        diag = m.group(1) if m else body[:200]
    rcpt = rcpt.strip().strip("<>").lower()
    if not re.fullmatch(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+", rcpt) or OURS.search(rcpt):
        return None
    kind = classify(subject, status.strip(), diag)
    return (rcpt, kind, " ".join(f"{status} {diag}".split())[:300]) if kind else None


def record(rcpt, kind, reason):
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        return None
    req = urllib.request.Request(f"{url}/rest/v1/rpc/email_bounce_record", method="POST",
                                 data=json.dumps({"p_email": rcpt, "p_kind": kind, "p_reason": reason}).encode(),
                                 headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def count(M, uids, dry):
    """Record each not-yet-counted notice; returns how many were counted."""
    n = 0
    for uid in uids:
        typ, d = M.uid("FETCH", uid, "(FLAGS BODY.PEEK[])")
        if typ != "OK" or not d or not isinstance(d[0], tuple):
            continue
        if COUNTED.encode() in d[0][0]:
            continue
        b = parse_bounce(d[0][1])
        if b:
            if dry:
                local, _, dom = b[0].partition("@")
                print("would count", f"{local[:1]}***@{dom}", b[1])
            else:
                stopped = record(*b)
                if stopped:
                    local, _, dom = b[0].partition("@")   # masked like emailkit.mask_email
                    print(f"suppressed {local[:1]}***@{dom} ({b[1]}): {b[2][:120].replace(b[0], '***')}")
        if not dry:
            M.uid("STORE", uid, "+FLAGS", f"({COUNTED})")
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    a = ap.parse_args()
    M = imaplib.IMAP4_SSL(imap_host())
    M.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
    if not a.dry_run:
        M.create(FOLDER)  # NO when it already exists; that's fine
        M.subscribe(FOLDER)
    if a.backfill:
        M.select(FOLDER, readonly=a.dry_run)
        typ, d = M.uid("SEARCH", None, "ALL")
        old = d[0].split() if typ == "OK" and d and d[0] else []
        print("backfill: counted %d old notice(s)" % count(M, old, a.dry_run))
    M.select("INBOX", readonly=a.dry_run)
    uids = bounce_uids(M)
    count(M, uids, a.dry_run)
    if uids and not a.dry_run:
        typ, d = M.uid("MOVE", b",".join(uids).decode(), FOLDER)
        if typ != "OK":
            raise SystemExit("MOVE failed: %r" % d)
    if uids:
        print("%s %d bounce notice(s) -> %s" % ("would move" if a.dry_run else "moved", len(uids), FOLDER))
    M.logout()


if __name__ == "__main__":
    main()
