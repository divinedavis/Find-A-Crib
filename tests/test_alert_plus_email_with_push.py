"""Plus alerts are emailed in real time, with their push, until the day's five
emails are used (owner, 2026-11-17: 180 W. 20th St. was pushed at 10 AM but
its email was held because a 2 AM alert had used the day's one email; then
"emails should come in real time for plus users" and "lets increase our email
limit to 5 a day per user", db/0078)."""
import os
import sys
from contextlib import ExitStack
from unittest import mock

import lottery_alerts as L
from growth import emailkit, mailcap

RR1 = {"id": "rr:1", "kind": "rerental", "boro": "Bk", "text": "12 Example Ave.", "url": "https://x/1", "sub": ""}
RR2 = {"id": "rr:2", "kind": "rerental", "boro": "M", "text": "34 Sample St.", "url": "https://x/2", "sub": ""}
SUB = {"id": 7, "email": "o@x.com", "kinds": ["rerental"], "boroughs": ["Bk", "M"], "token": "t"}
CAP = 5


def run(feeds, state, log, ledger, *, plus=True, send_fails=False):
    """`ledger` is today's email count for the address, like email_sends."""
    rpcs = {"lottery_alerts_recipients": [SUB], "plus_emails": [SUB["email"]] if plus else [],
            "device_tokens_for_emails": [{"email": SUB["email"], "token": "a" * 64, "env": "production"}]}

    def push(tok, env, title, body, **kw):
        log.append(("push", [i["id"] for i in kw["extra"]["items"]]))
        return {"ok": True, "status": 200, "reason": "", "refile": None, "remove": False}

    def send(to, subject, html, text, **kw):
        if send_fails:
            raise OSError("smtp down")
        log.append(("email", subject))

    def claim(email, kind, dry=False):
        if ledger["n"] >= CAP:
            return False
        ledger["n"] += 1
        return True

    def release(email, dry=False):
        ledger["n"] -= 1
        log.append(("release", email))

    with ExitStack() as s:
        s.enter_context(mock.patch.object(sys, "argv", ["lottery_alerts.py"]))
        s.enter_context(mock.patch.dict(os.environ, {"SUPABASE_SERVICE_KEY": "k"}))
        s.enter_context(mock.patch.object(L, "gather", lambda: {"hc": [], "hcr": [], "rr": list(feeds), "s8": []}))
        s.enter_context(mock.patch.object(L, "load_state", lambda: state))
        s.enter_context(mock.patch.object(L, "save_state", lambda st: None))
        s.enter_context(mock.patch.object(L, "with_households", lambda subs, key: [dict(x) for x in subs]))
        s.enter_context(mock.patch.object(L, "rpc", lambda name, body, key: rpcs.get(name)))
        s.enter_context(mock.patch.object(L, "push_items", lambda items: [{"id": i["id"]} for i in items]))
        s.enter_context(mock.patch.object(L.apns, "config", lambda: True))
        s.enter_context(mock.patch.object(L.apns, "send", push))
        s.enter_context(mock.patch.object(mailcap, "claim", claim))
        s.enter_context(mock.patch.object(mailcap, "release", release))
        s.enter_context(mock.patch.object(emailkit, "send", send))
        L.main()


def fresh():
    return {"seen": {}, "sends": [], "held": {}}


def test_plus_alert_after_a_morning_email_is_emailed_with_its_push():
    state, log, ledger = fresh(), [], {"n": 1}   # the 2 AM alert already went out
    run([RR1], state, log, ledger)
    assert [k for k, _ in log] == ["email", "push"], log
    assert "7" not in state["held"]
    run([RR1, RR2], state, log, ledger)
    assert [k for k, _ in log] == ["email", "push", "email", "push"], log
    assert log[-1] == ("push", ["rr:2"])
    assert ledger["n"] == 3


def test_past_five_the_push_goes_and_the_email_waits():
    state, log, ledger = fresh(), [], {"n": 0}
    feeds = []
    for n in range(CAP + 1):
        feeds.append(dict(RR1, id=f"rr:{n}"))
        run(list(feeds), state, log, ledger)
    kinds = [k for k, _ in log]
    assert kinds.count("email") == CAP and kinds.count("push") == CAP + 1, log
    assert [h["id"] for h in state["held"]["7"]] == [f"rr:{CAP}"]
    assert state["held"]["7"][0]["pushed"]


def test_held_pushed_item_is_emailed_once_a_slot_frees_without_a_second_push():
    state = {"seen": {"rr:1": "2026-11-17T15:00:00+00:00"}, "sends": [],
             "held": {"7": [dict(RR1, pushed=True)]}}
    log, ledger = [], {"n": 0}                  # a new day: slots free again
    run([RR1], state, log, ledger)              # nothing new in the feed this run
    assert [k for k, _ in log] == ["email"], log
    assert "7" not in state["held"]


def test_without_plus_still_waits_for_digest():
    state, log, ledger = fresh(), [], {"n": 0}
    run([RR1], state, log, ledger, plus=False)
    assert log == [] and ledger["n"] == 0
    assert [h["id"] for h in state["held"]["7"]] == ["rr:1"]


def test_failed_send_gives_its_slot_back():
    state, log, ledger = fresh(), [], {"n": 2}
    run([RR1], state, log, ledger, send_fails=True)
    assert ("release", SUB["email"]) in log and ledger["n"] == 2
    assert [h["id"] for h in state["held"]["7"]] == ["rr:1"]


def test_ledger_sql_caps_at_five_and_keeps_one_row_per_email():
    sql = open(os.path.join(os.path.dirname(__file__), "..", "db", "0078_email_cap_five.sql")).read()
    assert "v_n >= 5" in sql
    assert "primary key (email, day, seq)" in sql
    assert "pg_advisory_xact_lock" in sql
    for fn in ("email_claim(text, text)", "email_release(text)"):
        assert f"revoke all on function public.{fn} from public, anon, authenticated" in sql
