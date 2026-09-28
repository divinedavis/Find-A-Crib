#!/usr/bin/env python3
"""Forward creator replies from a product mailbox (hello@marracat.com) to the
owner's Gmail. Runs from cron every 5 minutes as the `findacrib` user
(deploy/cron-creator-mail-forward).

Why this exists: Private Email's own Auto forward is not available on trial
plans, and the owner chose a server-side forwarder (2026-09-28) over paying
early or forwarding from the laptop app.

- Reads INBOX only (spam stays out) with BODY.PEEK, so nothing is marked read
  and the original stays in the mailbox.
- Remembers the last forwarded UID per mailbox (UIDVALIDITY-aware) in STATE,
  so each message is forwarded once. The first run starts at FIRST_DAY.
- The forward is a readable copy with the original attached as .eml, sent
  from the mailbox itself; Reply-To is the original sender, so replying in
  Gmail answers the creator.
- Skips the mailbox's own address (no loops) and caps each run at MAX_PER_RUN.

Credentials: CONFIG (JSON list of {"host","user","password","forward_to"}),
0600 and owned by findacrib. Never in this repo, which is public.
"""
import email, email.policy, email.utils, fcntl, imaplib, json, os, pathlib, smtplib, ssl, sys, time
from email.message import EmailMessage

BASE = pathlib.Path(os.environ.get("CREATOR_DIR", "/var/lib/findacrib-api/creators"))
CONFIG = BASE / "mail_forward.json"
STATE = BASE / "mail_forward_state.json"
FIRST_DAY = "28-Sep-2026"      # first creator pitches went out that day
MAX_PER_RUN = 20


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def text_of(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    body = part.get_content()
    if part.get_content_type() == "text/html":
        import html, re
        body = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", body)))
    return body.strip()[:20000]


def forward(cfg, raw, smtp):
    orig = email.message_from_bytes(raw, policy=email.policy.default)
    sender = email.utils.parseaddr(str(orig.get("From", "")))[1]
    if sender.lower() == cfg["user"].lower():
        return "skipped (own address)"
    fwd = EmailMessage()
    fwd["From"] = email.utils.formataddr(("Marracat inbox", cfg["user"]))
    fwd["To"] = cfg["forward_to"]
    if sender:
        fwd["Reply-To"] = str(orig.get("From"))
    fwd["Subject"] = "Fwd: " + str(orig.get("Subject", "(no subject)"))
    fwd["Date"] = email.utils.formatdate(localtime=True)
    fwd["Message-ID"] = email.utils.make_msgid(domain=cfg["user"].split("@")[1])
    head = (f"Forwarded from {cfg['user']}\n"
            f"From: {orig.get('From', '')}\nDate: {orig.get('Date', '')}\nSubject: {orig.get('Subject', '')}\n"
            "Reply to this email to answer them directly (from your Gmail).\n\n")
    fwd.set_content(head + text_of(orig))
    fwd.add_attachment(raw, maintype="message", subtype="rfc822", filename="original.eml")
    smtp.send_message(fwd, to_addrs=[cfg["forward_to"]])
    return f"forwarded from {sender}"


def run_one(cfg, state):
    ctx = ssl.create_default_context()
    key = cfg["user"].lower()
    st = state.setdefault(key, {})
    with imaplib.IMAP4_SSL(cfg.get("host", "mail.privateemail.com"), 993, ssl_context=ctx, timeout=60) as i:
        i.login(cfg["user"], cfg["password"])
        typ, data = i.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError(f"select INBOX: {data}")
        uv = i.response("UIDVALIDITY")[1][0].decode()
        if st.get("uidvalidity") != uv:          # new mailbox or a server reset
            st.clear()
            st["uidvalidity"] = uv
            typ, data = i.uid("search", None, "SINCE", FIRST_DAY)
        else:
            typ, data = i.uid("search", None, f"UID {int(st.get('last_uid', 0)) + 1}:*")
        uids = sorted(int(u) for u in (data[0].split() if typ == "OK" and data[0] else [])
                      if int(u) > int(st.get("last_uid", 0)))
        if not uids:
            return 0
        n = 0
        with smtplib.SMTP_SSL(cfg.get("host", "mail.privateemail.com"), 465, context=ctx, timeout=60) as s:
            s.login(cfg["user"], cfg["password"])
            for uid in uids[:MAX_PER_RUN]:
                typ, msg = i.uid("fetch", str(uid), "(BODY.PEEK[])")
                raw = next((p[1] for p in msg if isinstance(p, tuple)), None) if typ == "OK" else None
                if raw is None:
                    log(f"{key} uid {uid}: could not fetch, will retry")
                    break
                log(f"{key} uid {uid}: {forward(cfg, raw, s)}")
                st["last_uid"] = uid
                n += 1
        if len(uids) > MAX_PER_RUN:
            log(f"{key}: {len(uids) - MAX_PER_RUN} more waiting for the next run")
        return n


def main():
    lock = open(BASE / "mail_forward.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return                      # the previous run is still going
    cfgs = json.loads(CONFIG.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    failed = False
    for cfg in cfgs:
        try:
            run_one(cfg, state)
        except Exception as e:
            failed = True
            log(f"{cfg.get('user')}: FAILED {type(e).__name__}: {e}")
        finally:
            tmp = STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            os.chmod(tmp, 0o600)
            tmp.replace(STATE)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
