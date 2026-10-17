#!/usr/bin/env python3
"""Building chat reports: mail each new one to the owner, and act on them.

The chat is end-to-end encrypted, so a report is the only way a message's
text reaches Find A Crib: the reporter's phone sends the plaintext of the one
message they flagged (db/0063_building_chat.sql). Apple's guideline 1.2 asks
that reports get a response within 24 hours; this runs every 15 minutes on
the droplet (deploy/cron-rentmap-chat-reports) and mails only new reports.

    python3 chat_reports.py                     # mail new reports
    python3 chat_reports.py --dry-run           # print them, send nothing
    python3 chat_reports.py --list              # every unhandled report
    python3 chat_reports.py --remove 123        # delete message 123, mark its reports handled
    python3 chat_reports.py --ban USER_ID --reason "harassment"   # out of every chat, can't rejoin
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dbaifotzwlxjvsxjohjt.supabase.co")
STATE = Path(os.environ.get("CHAT_REPORT_STATE", "/var/lib/scraper/chat_reports_state.json"))   # scraper's home


def key():
    for k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY"):
        if os.environ.get(k):
            return os.environ[k]
    sys.exit("no SUPABASE_SERVICE_ROLE_KEY in the environment")


def rest(method, path, body=None, prefer=None):
    k = key()
    h = {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read()
        return json.loads(t) if t else None


def unhandled():
    q = urllib.parse.urlencode({"select": "id,message_id,bbl,reporter,sender,plaintext,reason,created_at",
                                "handled_at": "is.null", "order": "id.asc"})
    return rest("GET", f"chat_reports?{q}")


def mail_new(dry):
    rows = unhandled()
    try:
        seen = int(json.loads(STATE.read_text()).get("last_id", 0))
    except Exception:
        seen = 0
    new = [r for r in rows if r["id"] > seen]
    if not new:
        print("no new chat reports")
        return
    lines = []
    for r in new:
        lines.append(f"Report {r['id']} · building {r['bbl']} · {r['created_at'][:16]} · {r['reason']}\n"
                     f"  message {r['message_id']} from {r['sender']}:\n  \"{(r['plaintext'] or '(no text)')[:800]}\"\n"
                     f"  remove: python3 chat_reports.py --remove {r['message_id']}\n"
                     f"  ban:    python3 chat_reports.py --ban {r['sender']} --reason \"...\"\n")
    text = ("New building chat reports. Apple expects action within 24 hours.\n"
            "Run the commands on the findacrib droplet in /root/Find-A-Crib.\n\n" + "\n".join(lines))
    if dry or not os.environ.get("ERROR_REPORT_EMAIL"):
        print(text)
        return
    from growth import emailkit
    html = "<pre style='font:14px/1.4 ui-monospace,monospace;white-space:pre-wrap'>" + \
        text.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
    emailkit.send(os.environ["ERROR_REPORT_EMAIL"], f"Building chat: {len(new)} new report{'s' if len(new) > 1 else ''}",
                  html, text, from_name="Find A Crib alerts")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_id": max(r["id"] for r in new)}))
    print(f"mailed {len(new)} report(s)")


def remove(message_id):
    rest("PATCH", f"chat_reports?message_id=eq.{int(message_id)}", {"handled_at": __import__("datetime").datetime.utcnow().isoformat() + "Z"})
    rest("DELETE", f"chat_messages?id=eq.{int(message_id)}")
    print(f"removed message {message_id}; its reports are handled")


def ban(user_id, reason):
    uid = str(user_id).strip().lower()
    rest("POST", "chat_bans", {"user_id": uid, "reason": reason}, prefer="resolution=merge-duplicates")
    rest("DELETE", f"chat_members?user_id=eq.{uid}")
    rest("PATCH", f"chat_reports?sender=eq.{uid}&handled_at=is.null",
         {"handled_at": __import__("datetime").datetime.utcnow().isoformat() + "Z"})
    print(f"banned {uid}: removed from every chat, can't rejoin or post")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove", type=int)
    ap.add_argument("--ban")
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    if a.remove:
        remove(a.remove)
    elif a.ban:
        ban(a.ban, a.reason)
    elif a.list:
        for r in unhandled():
            print(json.dumps(r))
    else:
        mail_new(a.dry_run)


if __name__ == "__main__":
    main()
