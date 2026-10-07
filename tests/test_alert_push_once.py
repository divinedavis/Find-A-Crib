"""A held item is pushed once, never again (2026-10-07: the owner, Plus with
the day's email already used, got the 570 Nostrand Ave. re-rental pushed on
three runs — every later run that found anything new re-pushed the held list)."""
import os
import sys
from contextlib import ExitStack
from unittest import mock

import lottery_alerts as L
from growth import emailkit, mailcap

RR1 = {"id": "rr:1", "kind": "rerental", "boro": "Bk", "text": "570 Nostrand Ave.", "url": "https://x/1", "sub": ""}
RR2 = {"id": "rr:2", "kind": "rerental", "boro": "M", "text": "351 East 10th St.", "url": "https://x/2", "sub": ""}
SUB = {"id": 7, "email": "o@x.com", "kinds": ["lottery", "rerental"], "boroughs": ["Bk", "M"], "token": "t"}
RPCS = {"lottery_alerts_recipients": [SUB], "plus_emails": [SUB["email"]],
        "device_tokens_for_emails": [{"email": SUB["email"], "token": "a" * 64, "env": "production"}]}


def run(feeds, state, pushes):
    def push(tok, env, title, body, **kw):
        pushes.append([i["id"] for i in kw["extra"]["items"]])
        return {"ok": True, "status": 200, "reason": "", "refile": None, "remove": False}

    def no_email(*a, **k):
        raise AssertionError("today's email slot is used — must not send")

    with ExitStack() as s:
        s.enter_context(mock.patch.object(sys, "argv", ["lottery_alerts.py"]))
        s.enter_context(mock.patch.dict(os.environ, {"SUPABASE_SERVICE_KEY": "k"}))
        s.enter_context(mock.patch.object(L, "gather", lambda: {"hc": [], "hcr": [], "rr": list(feeds), "s8": []}))
        s.enter_context(mock.patch.object(L, "load_state", lambda: state))
        s.enter_context(mock.patch.object(L, "save_state", lambda st: None))
        s.enter_context(mock.patch.object(L, "with_households", lambda subs, key: [dict(x) for x in subs]))
        s.enter_context(mock.patch.object(L, "rpc", lambda name, body, key: RPCS.get(name)))
        s.enter_context(mock.patch.object(L, "push_items", lambda items: [{"id": i["id"]} for i in items]))
        s.enter_context(mock.patch.object(L.apns, "config", lambda: True))
        s.enter_context(mock.patch.object(L.apns, "send", push))
        s.enter_context(mock.patch.object(mailcap, "claim", lambda email, kind, dry=False: False))
        s.enter_context(mock.patch.object(emailkit, "send", no_email))
        L.main()


def test_push_only_item_is_not_pushed_again():
    state = {"seen": {}, "sends": [], "held": {}}
    pushes = []
    run([RR1], state, pushes)           # 570 Nostrand appears: pushed
    run([RR1, RR2], state, pushes)      # something else new: only that one
    run([RR1, RR2], state, pushes)      # nothing new: no push at all
    assert pushes == [["rr:1"], ["rr:2"]], pushes
    held = state["held"]["7"]
    assert [h["id"] for h in held] == ["rr:1", "rr:2"]   # both still ride tomorrow's email
    assert all(h["pushed"] for h in held)
    assert "pushed" not in RR1                             # shared feed items untouched
