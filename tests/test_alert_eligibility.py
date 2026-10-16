"""Alerts only for lotteries the subscriber can apply to, and no re-alert when
a feed blips (2026-10-16: Housing Connect dropped 1 Gouverneur Lane from every
other answer overnight and each return pushed it again, ~13 times)."""
import os
import sys
from contextlib import ExitStack
from unittest import mock

import lottery_alerts as L
from growth import emailkit, mailcap

GOUV = {"id": "hc:7662", "kind": "lottery", "label": "Housing Connect lottery", "boro": "M", "text": "1 Gouverneur Lane", "url": "https://x/7662",
        "sub": "", "income_min": 40526, "income_max": 152700, "household_min": 1, "household_max": 5}
BECK = {"id": "hc:7652", "kind": "lottery", "label": "Housing Connect lottery", "boro": "M", "text": "664-672 Beck Street", "url": "https://x/7652",
        "sub": "", "income_min": 0, "income_max": 162008, "household_min": 1, "household_max": 7}
SUB = {"id": 7, "email": "o@x.com", "kinds": ["lottery", "rerental"], "boroughs": ["M"], "token": "t"}


def run(hc, state, pushes):
    rpcs = {"lottery_alerts_recipients": [SUB], "plus_emails": [SUB["email"]],
            "device_tokens_for_emails": [{"email": SUB["email"], "token": "a" * 64, "env": "production"}]}

    def push(tok, env, title, body, **kw):
        pushes.append([i["id"] for i in kw["extra"]["items"]])
        return {"ok": True, "status": 200, "reason": "", "refile": None, "remove": False}

    with ExitStack() as s:
        s.enter_context(mock.patch.object(sys, "argv", ["lottery_alerts.py"]))
        s.enter_context(mock.patch.dict(os.environ, {"SUPABASE_SERVICE_KEY": "k"}))
        s.enter_context(mock.patch.object(L, "gather", lambda: {"hc": list(hc), "hcr": [], "rr": [], "s8": []}))
        s.enter_context(mock.patch.object(L, "load_state", lambda: state))
        s.enter_context(mock.patch.object(L, "save_state", lambda st: None))
        s.enter_context(mock.patch.object(L, "with_households", lambda subs, key: [dict(x) for x in subs]))
        s.enter_context(mock.patch.object(L, "rpc", lambda name, body, key: rpcs.get(name)))
        s.enter_context(mock.patch.object(L, "push_items", lambda items: [{"id": i["id"]} for i in items]))
        s.enter_context(mock.patch.object(L.apns, "config", lambda: True))
        s.enter_context(mock.patch.object(L.apns, "send", push))
        s.enter_context(mock.patch.object(mailcap, "claim", lambda email, kind, dry=False: False))
        s.enter_context(mock.patch.object(emailkit, "send", lambda *a, **k: None))
        L.main()


def test_feed_blip_does_not_realert():
    state = {"seen": {}, "sends": [], "held": {}}
    pushes = []
    for feed in ([GOUV, BECK], [BECK], [GOUV, BECK], [GOUV], [GOUV, BECK]):
        run(feed, state, pushes)
    assert pushes == [["hc:7662", "hc:7652"]], pushes


def test_gone_for_days_alerts_again():
    old = "2026-01-01T00:00:00+00:00"
    state = {"seen": {"hc:7662": old}, "sends": [], "held": {}, "gone": {"hc:7662": old}}
    pushes = []
    run([], state, pushes)               # still gone, past the grace: forgotten
    assert "hc:7662" not in state["seen"]
    run([GOUV], state, pushes)           # a real re-opening alerts
    assert pushes == [["hc:7662"]]


def test_city_answer_decides_for_household_and_income():
    subs = [dict(SUB, income=150000, household_size=1), dict(SUB, income=150000), dict(SUB)]
    calls = []
    L.hc_qualified(subs, [GOUV, BECK], search=lambda hh, inc: calls.append((hh, inc)) or [7652])
    assert calls == [(1, 150000), (1, 150000)]          # one pair, asked twice
    single, no_size, nothing = subs
    assert not L.wants(single, GOUV)      # over the one-person limit, though inside the band
    assert L.wants(single, BECK)
    assert L.wants(no_size, GOUV)         # no household size: band check only
    assert L.wants(nothing, GOUV)


def test_blip_in_city_answer_is_unioned():
    answers = iter([[7652], [7662, 7652]])
    sub = dict(SUB, income=90000, household_size=2)
    L.hc_qualified([sub], [GOUV], search=lambda hh, inc: next(answers))
    assert L.wants(sub, GOUV)


def test_city_lookup_failure_keeps_band_check():
    def boom(hh, inc):
        raise OSError("down")
    sub = dict(SUB, income=150000, household_size=1)
    L.hc_qualified([sub], [GOUV], search=boom)
    assert "hc_ok" not in sub
    assert L.wants(sub, GOUV)


def test_household_outside_lottery_range():
    assert not L.wants(dict(SUB, household_size=6), GOUV)
    assert L.wants(dict(SUB, household_size=6), BECK)
