#!/usr/bin/env python3
"""The welcome step must survive a night the job did not run, and no later step
may become an account's first contact.

2026-10-15. growth/accounts.py gated its welcome on `days <= 1` — a CLOSED
WINDOW, where every other step in the sequence uses a FLOOR (activate >= 3,
lapsed >= 21, saved >= 5). One nightly cron line drives the whole sequence, so
any night the job did not run carried that night's signups past the window with
no way back: they never received a welcome, and at day 3 with no saves the next
run offered them `activate` — an email written for somebody who has already
read the welcome — as the first thing Find A Crib ever sent them.

Two outages had already hit it when this was found. The dead-cron nights of
2026-09-25..27 read sent_welcome 5, 2, then 11 against 4-15 on ordinary days,
and #PAUSED-20261012 had held three nights at a trailing ~9 welcomes/day.

Nothing recorded any of it, which is the second half of the fix: every series
this job writes counts SENDS, so an account that was missed leaves no trace in
one. `welcome_aged_out` is the count of accounts in the sequence that have had
nothing and can no longer be welcomed, recorded on every path including the
early "nothing due" return — the path a long outage actually produces.

The rail is deliberately NOT "send the welcome whenever it was missed". An
unbounded catch-up mails a welcome to somebody who signed up a month ago and
moved on, which is the backfill blast CUTOVER exists to prevent. Past the grace
window an uncontacted account leaves the sequence entirely.
"""
from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from growth import accounts as A  # noqa: E402

NOW = datetime.datetime(2026, 10, 15, 10, 0, tzinfo=datetime.timezone.utc)


def row(days, sent=(), saves=0, last_seen_days=0):
    """An account `days` old. last_seen_days=None means never seen (reads quiet)."""
    seen = None if last_seen_days is None else (
        (NOW - datetime.timedelta(days=last_seen_days)).isoformat())
    return {"user_id": f"u{days}", "email": f"a{days}@example.com", "token": "t",
            "days_old": days, "sent_steps": list(sent), "save_count": saves,
            "last_seen": seen, "created_at": (NOW - datetime.timedelta(days=days)).isoformat()}


def old_gate(r):
    """The pre-2026-10-15 welcome gate, for the mutation tests below."""
    return "welcome" not in set(r.get("sent_steps") or []) and (r.get("days_old") or 0) <= 1


class WelcomeSurvivesAnOutage(unittest.TestCase):
    def test_same_day_signup_still_welcomed(self):
        self.assertEqual(A._step_for(row(0), NOW), "welcome")

    def test_day_one_still_welcomed_as_before(self):
        self.assertEqual(A._step_for(row(1), NOW), "welcome")

    def test_the_three_night_pause_no_longer_costs_the_welcome(self):
        # The live case on 2026-10-15: signed up 10-13, engine paused since
        # 10-12, so 2 days old and never contacted. The old gate lost these.
        r = row(2)
        self.assertTrue(old_gate(r) is False, "fixture must be past the OLD window")
        self.assertEqual(A._step_for(r, NOW), "welcome")

    def test_welcome_still_reachable_at_the_grace_boundary(self):
        self.assertEqual(A._step_for(row(A.WELCOME_GRACE_DAYS), NOW), "welcome")

    def test_welcome_precedes_activate_even_when_both_would_qualify(self):
        # 5 days old, no saves: activate's floor (>= 3) is met too. The welcome
        # must win, or the catch-up would deliver the nag instead.
        self.assertEqual(A._step_for(row(5, saves=0), NOW), "welcome")

    def test_welcome_precedes_the_paid_ask(self):
        # Engaged saver, 6 days old, never welcomed. SAVED_MIN_DAYS is met, but
        # a $9 ask must not arrive before the welcome.
        self.assertEqual(A._step_for(row(6, saves=2, last_seen_days=0), NOW), "welcome")

    def test_welcome_not_resent_once_sent(self):
        self.assertNotEqual(A._step_for(row(1, sent=("welcome",)), NOW), "welcome")


class NoLaterStepBecomesAFirstContact(unittest.TestCase):
    def test_uncontacted_and_past_grace_gets_nothing(self):
        self.assertTrue(A.aged_out(row(8)))
        self.assertIsNone(A._step_for(row(8), NOW))

    def test_activate_is_not_offered_as_a_first_contact(self):
        # The old behaviour: 30 days old, never contacted, no saves -> activate.
        r = row(30, saves=0)
        self.assertIsNone(A._step_for(r, NOW),
                          "activate must not be the first email an account ever gets")

    def test_lapsed_is_not_offered_as_a_first_contact(self):
        r = row(40, saves=0, last_seen_days=30)
        self.assertIsNone(A._step_for(r, NOW))

    def test_paid_ask_is_not_offered_as_a_first_contact(self):
        r = row(40, saves=3, last_seen_days=0)
        self.assertIsNone(A._step_for(r, NOW))

    def test_already_contacted_account_stays_in_the_sequence(self):
        # Holds `activate` but no `welcome` — producible by the old closed
        # window. It has had contact, so no step of it can be a first contact
        # and the rail must not strand it.
        r = row(40, sent=("activate",), saves=2, last_seen_days=0)
        self.assertFalse(A.aged_out(r))
        self.assertEqual(A._step_for(r, NOW), "saved")

    def test_aged_out_is_scoped_to_having_had_nothing(self):
        self.assertFalse(A.aged_out(row(99, sent=("welcome",))))
        self.assertFalse(A.aged_out(row(99, sent=("lapsed",))))

    def test_grace_boundary_is_inclusive_on_welcome_exclusive_on_aged_out(self):
        g = A.WELCOME_GRACE_DAYS
        self.assertFalse(A.aged_out(row(g)))
        self.assertTrue(A.aged_out(row(g + 1)))
        # No account may be both welcomable and aged out, at any age.
        for d in range(0, 60):
            r = row(d)
            self.assertFalse(A.aged_out(r) and A._step_for(r, NOW) == "welcome",
                             f"day {d} is both welcomable and aged out")


class StepsAfterTheWelcomeAreUnchanged(unittest.TestCase):
    """The rail must not quietly re-time the rest of the sequence."""

    def test_activate_after_a_welcome(self):
        self.assertEqual(A._step_for(row(3, sent=("welcome",), saves=0), NOW), "activate")

    def test_activate_floor_still_three_days(self):
        self.assertIsNone(A._step_for(row(2, sent=("welcome",), saves=0), NOW))

    def test_activate_skipped_once_they_have_saved(self):
        self.assertNotEqual(
            A._step_for(row(4, sent=("welcome",), saves=1, last_seen_days=0), NOW), "activate")

    def test_lapsed_needs_quiet_and_twenty_one_days(self):
        self.assertEqual(
            A._step_for(row(21, sent=("welcome", "activate"), last_seen_days=20), NOW), "lapsed")
        self.assertIsNone(
            A._step_for(row(21, sent=("welcome", "activate"), last_seen_days=1), NOW))

    def test_saved_needs_a_save_and_a_recent_visit(self):
        self.assertEqual(
            A._step_for(row(5, sent=("welcome",), saves=1, last_seen_days=0), NOW), "saved")
        # No saves at 5 days is `activate`'s case, not `saved`'s — the point
        # here is only that the paid ask is not reached without a save.
        self.assertEqual(
            A._step_for(row(5, sent=("welcome",), saves=0, last_seen_days=0), NOW), "activate")
        self.assertIsNone(
            A._step_for(row(5, sent=("welcome", "activate"), saves=0, last_seen_days=0), NOW))

    def test_an_account_with_no_last_seen_is_never_asked_for_money(self):
        self.assertNotEqual(
            A._step_for(row(9, sent=("welcome",), saves=1, last_seen_days=None), NOW), "saved")

    def test_lapsed_and_saved_remain_mutually_exclusive(self):
        for d in (5, 21, 30, 60):
            for seen in (0, 1, 13, 14, 20, None):
                s = A._step_for(row(d, sent=("welcome",), saves=1, last_seen_days=seen), NOW)
                self.assertIn(s, (None, "lapsed", "saved"))


class TheMissIsCounted(unittest.TestCase):
    """due() returns the aged-out count; run() records it on every path."""

    def _due(self, rows, monkeypatch_rpc=True):
        calls = {}

        def fake_rpc(name, body=None):
            calls[name] = True
            return rows if name == "lifecycle_accounts_due" else None

        orig = A._rpc
        A._rpc = fake_rpc
        try:
            return A.due(now=NOW)
        finally:
            A._rpc = orig

    def test_due_returns_a_pair(self):
        pending, missed = self._due([])
        self.assertEqual((pending, missed), ([], 0))

    def test_aged_out_accounts_are_counted_not_mailed(self):
        pending, missed = self._due([row(30), row(40, saves=2, last_seen_days=0), row(1)])
        self.assertEqual(missed, 2)
        self.assertEqual([s for _, s in pending], ["welcome"])

    def test_zero_when_everyone_is_reachable(self):
        pending, missed = self._due([row(0), row(3, sent=("welcome",))])
        self.assertEqual(missed, 0)

    def test_pre_cutover_accounts_are_not_counted_as_missed(self):
        # Never in the sequence at all, so they are not a cost of an outage.
        old = row(5)
        old["created_at"] = (datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)).isoformat()
        old["days_old"] = 106
        pending, missed = self._due([old])
        self.assertEqual((pending, missed), ([], 0))

    def test_owner_account_is_not_counted_as_missed(self):
        me = row(30)
        me["user_id"] = A.OWNER_USER_ID
        pending, missed = self._due([me])
        self.assertEqual(missed, 0)

    def test_record_aged_out_writes_even_a_zero(self):
        seen = []
        orig = A.ledger.record_result
        A.ledger.record_result = lambda d, t, m, v: seen.append((t, m, v))
        try:
            A._record_aged_out(0)
            A._record_aged_out(4)
        finally:
            A.ledger.record_result = orig
        self.assertEqual(seen, [("account_lifecycle", "welcome_aged_out", 0),
                                ("account_lifecycle", "welcome_aged_out", 4)])


class TheOldGateWouldFailThese(unittest.TestCase):
    """Proves the suite discriminates: the pre-fix behaviour breaks it.

    Without this, every assertion above could be passing for reasons unrelated
    to the change.
    """

    def test_old_closed_window_loses_the_pause_signups(self):
        lost = [d for d in (2, 3, 5, 7) if not old_gate(row(d))]
        self.assertEqual(lost, [2, 3, 5, 7],
                         "the old gate must fail every one of these for the fix to mean anything")
        for d in (2, 3, 5, 7):
            self.assertEqual(A._step_for(row(d), NOW), "welcome")

    def test_without_the_rail_activate_would_be_a_first_contact(self):
        # Mutation: neuter aged_out and the day-30 uncontacted account gets the nag.
        orig = A.aged_out
        A.aged_out = lambda r: False
        try:
            self.assertEqual(A._step_for(row(30, saves=0), NOW), "activate")
        finally:
            A.aged_out = orig
        self.assertIsNone(A._step_for(row(30, saves=0), NOW))

    def test_grace_of_one_reproduces_the_old_loss(self):
        orig = A.WELCOME_GRACE_DAYS
        A.WELCOME_GRACE_DAYS = 1
        try:
            self.assertIsNone(A._step_for(row(2), NOW))
        finally:
            A.WELCOME_GRACE_DAYS = orig
        self.assertEqual(A._step_for(row(2), NOW), "welcome")


if __name__ == "__main__":
    unittest.main(verbosity=2)
