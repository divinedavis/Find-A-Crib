"""A Plus alert is emailed at the same moment it is pushed, even after the
day's one email (owner, 2026-11-17: 180 W. 20th St. was pushed at 10 AM but
the email was held because a 2 AM alert had used the day's slot)."""
import os
import sys
from contextlib import ExitStack
from unittest import mock

import lottery_alerts as L
from growth import emailkit, mailcap

RR1 = {"id": "rr:1", "kind": "rerental", "boro": "Bk", "text": "12 Example Ave.", "url": "https://x/1", "sub": ""}
RR2 = {"id": "rr:2", "kind": "rerental", "boro": "M", "text": "34 Sample St.", "url": "https://x/2", "sub": ""}
SUB = {"id": 7, "email": "o@x.com", "kinds": ["rerental"], "boroughs": ["Bk", "M"], "token": "t"}


def run(feeds, state, log, *, plus=True, claim_ok=False, send_fails=False):
    rpcs = {"lottery_alerts_recipients": [SUB], "plus_emails": [SUB["email"]] if plus else [],
            "device_tokens_for_emails": [{"email": SUB["email"], "token": "a" * 64, "env": "production"}]}

    def push(tok, env, title, body, **kw):
        log.append(("push", [i["id"] for i in kw["extra"]["items"]]))
        return {"ok": True, "status": 200, "reason": "", "refile": None, "remove": False}

    def send(to, subject, html, text, **kw):
        if send_fails:
            raise OSError("smtp down")
        log.append(("email", subject))

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
        s.enter_context(mock.patch.object(mailcap, "claim", lambda email, kind, dry=False: claim_ok))
        s.enter_context(mock.patch.object(mailcap, "release", lambda email, dry=False: log.append(("release", email))))
        s.enter_context(mock.patch.object(emailkit, "send", send))
        L.main()


def fresh():
    return {"seen": {}, "sends": [], "held": {}}


def test_plus_gets_email_with_push_after_days_slot_is_used():
    state, log = fresh(), []
    run([RR1], state, log)                      # slot already used today (claim False)
    assert [k for k, _ in log] == ["email", "push"], log
    assert "7" not in state["held"]            # nothing left for tomorrow
    run([RR1, RR2], state, log)
    assert [k for k, _ in log] == ["email", "push", "email", "push"], log
    assert log[-1] == ("push", ["rr:2"])


def test_plus_ceiling_falls_back_to_push_only():
    state, log = fresh(), []
    feeds = []
    for n in range(L.PLUS_EMAILS_PER_DAY + 1):
        feeds.append(dict(RR1, id=f"rr:{n}"))
        run(list(feeds), state, log)
    kinds = [k for k, _ in log]
    assert kinds.count("email") == L.PLUS_EMAILS_PER_DAY
    assert kinds.count("push") == L.PLUS_EMAILS_PER_DAY + 1
    assert [h["id"] for h in state["held"]["7"]] == [f"rr:{L.PLUS_EMAILS_PER_DAY}"]


def test_without_plus_still_waits_for_digest():
    state, log = fresh(), []
    run([RR1], state, log, plus=False, claim_ok=True)
    assert log == []
    assert [h["id"] for h in state["held"]["7"]] == ["rr:1"]


def test_failed_send_past_slot_does_not_release_someone_elses_claim():
    state, log = fresh(), []
    run([RR1], state, log, send_fails=True)
    assert not any(k == "release" for k, _ in log)
    run([RR2], fresh(), log, claim_ok=True, send_fails=True)
    assert ("release", SUB["email"]) in log


def test_counter_resets_on_a_new_new_york_day():
    state = {"plus_mail": {"7": {"day": "2000-01-01", "n": 99}}}
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    assert L.plus_emails_today(state, "7", now) == 0
    L.count_plus_email(state, "7", now)
    assert L.plus_emails_today(state, "7", now) == 1
