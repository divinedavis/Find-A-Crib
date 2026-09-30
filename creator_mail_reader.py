#!/usr/bin/env python3
"""Read creator replies in each product mailbox (hello@marracat.com) and put
the rate they quote on their row in /dashboard/creators/. Runs from cron every
5 minutes as the `findacrib` user (deploy/cron-creator-mail-reader).

Owner, 2026-09-30: "read emails that come to marracat and update the dashboard
with their rate". This replaced creator_mail_forward.py the same day, because
the owner also said "stop forwarding emails from marracat to my gmail"; they
read the mailbox in Outlook now.

- Reads INBOX only, read-only, with BODY.PEEK: nothing is marked read or moved.
- Only replies from an email already on a creator's row count; everything else
  is skipped. A rate is only taken from mail that passed DMARC or DKIM for the
  sender's domain (authentic()), so a forged From: can't set one. A rate the owner typed on the page is never overwritten.
- The rate is found by pattern (a money amount in the sentence that says rate,
  charge, fee, price...), not by an LLM: $0 a run, and the email text never
  reaches a model.
- Remembers the last UID read per mailbox (UIDVALIDITY-aware) in STATE; the
  first run starts at FIRST_DAY.

Credentials: CONFIG (JSON list of {"product","host","user","password"}), 0600
and owned by findacrib. Never in this repo, which is public.
"""
import email, email.policy, email.utils, fcntl, html, imaplib, json, os, pathlib, re, ssl, sys, time

import creator_outreach

BASE = creator_outreach.CREATOR_DIR
CONFIG = BASE / "mail_forward.json"
STATE = BASE / "mail_reader_state.json"
FIRST_DAY = "28-Sep-2026"      # first creator pitches went out that day
MAX_PER_RUN = 50


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def text_of(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    body = part.get_content()
    if part.get_content_type() == "text/html":
        body = re.sub(r"(?is)<(script|style).*?</\1>", "", body)
        body = html.unescape(re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", body))
        body = re.sub(r"<[^>]+>", " ", body)
    return body[:20000]


# Where the quoted pitch starts in a reply: Gmail/Apple "On ... wrote:",
# Outlook "-----Original Message-----" or "From: ...", or "> " lines.
QUOTE_START = re.compile(r"(?im)^(on\b.{0,300}?\bwrote:|-{2,}\s*original message|from:\s.+@|>)")
CUR = r"(?:USD|CAD|GBP|EUR|AUD|dollars?)"
MONEY = re.compile(
    r"(?:(?P<sym>(?:US|CA|C|A)?\$|£|€)\s?(?P<a>\d[\d,]*(?:\.\d+)?)\s?(?P<ka>k\b)?(?:\s*(?P<ca>" + CUR + r"))?"
    r"|(?P<b>\d[\d,]*(?:\.\d+)?)\s?(?P<kb>k\b)?\s*(?P<cb>" + CUR + r"))", re.I)
RATE_WORDS = re.compile(r"(?i)\b(rate|charge|fee|price|pricing|cost|quote|invest|budget|per (video|post|tiktok|reel))")


def own_words(body):
    m = QUOTE_START.search(body)
    return (body[:m.start()] if m else body).strip()


def _fmt(m):
    raw = (m.group("a") or m.group("b")).replace(",", "")
    try:
        n = float(raw)
    except ValueError:
        return None
    if m.group("ka") or m.group("kb"):
        n *= 1000
    if not 10 <= n <= 100000:
        return None
    sym = (m.group("sym") or "").upper()
    cur = (m.group("ca") or m.group("cb") or "").upper()
    if cur.startswith("DOLLAR"):
        cur = ""
    if not cur:
        cur = {"CA$": "CAD", "C$": "CAD", "A$": "AUD", "£": "GBP", "€": "EUR"}.get(sym, "")
    amount = f"{n:,.0f}" if n == int(n) else f"{n:,.2f}"
    lead = {"GBP": "£", "EUR": "€"}.get(cur, "$")
    return f"{lead}{amount}" + (f" {cur}" if cur not in ("", "USD", "GBP", "EUR") else "")


def find_rate(body):
    """(rate, sentence) from the creator's own words, or (None, None). Takes
    the first amount in the first sentence that talks about a rate; with no
    such sentence, a lone amount in the whole reply."""
    words = own_words(body)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n\s*\n", words) if s.strip()]
    for s in sentences:
        if RATE_WORDS.search(s):
            for m in MONEY.finditer(s):
                r = _fmt(m)
                if r:
                    return r, " ".join(s.split())
    found = [(r, s) for s in sentences for r in map(_fmt, MONEY.finditer(s)) if r]
    if len({r for r, _ in found}) == 1:
        return found[0][0], " ".join(found[0][1].split())
    return None, None


def authentic(m, sender):
    """True when Private Email's own check (the topmost Authentication-Results,
    added by its inbound relay) passed DMARC, or DKIM for the sender's domain.
    Anyone can put a creator's address in From:, so a rate is only taken from
    mail that proves it."""
    ar = " ".join(str(m.get("Authentication-Results") or "").split()).lower()
    dom = sender.rsplit("@", 1)[-1].lower()
    return "dmarc=pass" in ar or f"dkim=pass header.d={dom}" in ar


def read_one(cfg, state):
    key = cfg["user"].lower()
    st = state.setdefault(key, {})
    ctx = ssl.create_default_context()
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
        for uid in uids[:MAX_PER_RUN]:
            typ, msg = i.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in msg if isinstance(p, tuple)), None) if typ == "OK" else None
            if raw is None:
                log(f"{key} uid {uid}: could not fetch, will retry")
                break
            m = email.message_from_bytes(raw, policy=email.policy.default)
            sender = email.utils.parseaddr(str(m.get("From", "")))[1]
            try:
                when = email.utils.parsedate_to_datetime(str(m.get("Date"))).astimezone().isoformat(timespec="seconds")
            except (TypeError, ValueError):
                when = creator_outreach._now()
            rate, quote = (None, None)
            if sender.lower() != key and authentic(m, sender):
                rate, quote = find_rate(text_of(m))
            cid = creator_outreach.record_reply(sender, when, str(m.get("Subject", "")), rate, quote)
            if cid:
                log(f"{key} uid {uid}: reply from @{cid}" + (f", rate {rate}" if rate else ", no rate found"))
            st["last_uid"] = uid
        if len(uids) > MAX_PER_RUN:
            log(f"{key}: {len(uids) - MAX_PER_RUN} more waiting for the next run")


def main():
    lock = open(BASE / "mail_reader.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return                      # the previous run is still going
    cfgs = json.loads(CONFIG.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    failed = False
    for cfg in cfgs:
        try:
            read_one(cfg, state)
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
