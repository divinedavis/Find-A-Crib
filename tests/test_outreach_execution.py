#!/usr/bin/env python3
"""T008 b2b_outreach's execution count: the human send, recorded.

Shipped 2026-10-24, on T008's revisit. The technique declares mrr_usd, and
mrr_usd is downstream of a step growth/outreach.py deliberately never takes:
it drafts and never sends, because CAN-SPAM and GDPR need a human. So its
verdict was structurally uninterpretable — "mrr_usd went 0 → 4.99 with no
comparable baseline" says nothing about whether personalised outreach converts
— and the ledger carried that caveat by hand on 2026-09-24.

review.EXECUTION_SERIES was built on 2026-10-19 to resolve exactly this
disjunction, and its own rationale named T008 as one of the two cases it was
written for, then left T008 out of the map. These tests pin the gap closed and
pin the three ways a zero here can be wrong:

  * `status_at` moving when a prospect later replies, counting one send twice;
  * an unreadable prospects.json reading as "it acted 0 times";
  * the API-capped nights recording nothing, so "did not act" and "never ran"
    stay indistinguishable — the defect lifecycle._record_sent was extracted
    to fix, in a module where the looking needs no API at all.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import outreach as O     # noqa: E402
from growth import review as R       # noqa: E402


class Recorder:
    """Stands in for ledger.record_result, keeping what was written."""

    def __init__(self):
        self.rows = []

    def __call__(self, date, technique, metric, value, meta=None):
        self.rows.append((date, technique, metric, value))
        return {}

    def values(self, metric):
        return [v for _, _, m, v in self.rows if m == metric]


class ProspectFile:
    """Points outreach.PROSPECTS_PATH at a temporary file."""

    def __init__(self, payload=None, raw=None):
        self.payload, self.raw = payload, raw

    def __enter__(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "prospects.json")
        if self.raw is not None:
            with open(self.path, "w") as f:
                f.write(self.raw)
        elif self.payload is not None:
            with open(self.path, "w") as f:
                json.dump(self.payload, f)
        self.orig = O.PROSPECTS_PATH
        O.PROSPECTS_PATH = self.path
        return self

    def __exit__(self, *a):
        O.PROSPECTS_PATH = self.orig

    def read(self):
        with open(self.path) as f:
            return json.load(f)


class TheMappingIsThere(unittest.TestCase):
    """The gap this change closes: T008 cited in the rationale, absent from the map."""

    def test_t008_is_mapped_to_its_own_send_series(self):
        self.assertEqual(R.EXECUTION_SERIES["b2b_outreach"],
                         ("b2b_outreach", "emails_sent"))

    def test_it_is_mapped_to_sends_and_not_to_drafts(self):
        # The hypothesis is that personalised outreach CONVERTS better than
        # volume. Drafting is the module acting; sending is the technique
        # acting. Mapping this to drafts_written would let a night that drafted
        # three emails nobody sent rule out "nothing reaches this technique",
        # which is the one thing it must not do.
        self.assertNotEqual(R.EXECUTION_SERIES["b2b_outreach"][1], "drafts_written")

    def test_the_flat_branch_can_now_resolve_t008(self):
        orig = R.ledger.series
        try:
            R.ledger.series = lambda t, m, since=None: (
                [("2026-10-20", 0), ("2026-10-21", 0)]
                if (t, m) == ("b2b_outreach", "emails_sent") else [])
            acted, readings = R._executions("b2b_outreach", ("2026-10-20", "2026-10-21"))
        finally:
            R.ledger.series = orig
        # Measured, and it acted nothing: the branch that says "this zero
        # measures its own execution and not its effect".
        self.assertEqual(acted, 0)
        self.assertEqual(readings, 2)


class SentAtIsStampedOnceAndNeverMoves(unittest.TestCase):
    """status_at cannot serve as the send date, which is why sent_at exists."""

    def test_marking_sent_stamps_sent_at(self):
        with ProspectFile([{"org": "Acme Legal Aid", "status": "drafted"}]) as f:
            p = O.mark("Acme Legal Aid", "sent")
            self.assertEqual(p["status"], "sent")
            self.assertEqual(p["sent_at"], O.ledger.today())

    def test_a_later_reply_moves_status_at_but_not_sent_at(self):
        # The double-count this guards: one prospect, two days, one send.
        with ProspectFile([{"org": "Acme", "status": "drafted"}]) as f:
            O.mark("Acme", "sent")
            row = f.read()[0]
            row["sent_at"] = "2026-10-01"          # sent on an earlier day
            row["status_at"] = "2026-10-01"
            with open(f.path, "w") as fh:
                json.dump([row], fh)
            O.mark("Acme", "replied")
            after = f.read()[0]
            self.assertEqual(after["sent_at"], "2026-10-01")
            self.assertEqual(after["status_at"], O.ledger.today())

    def test_every_sent_status_counts_as_a_send(self):
        # A decline and a win both presuppose that the email went out.
        for st in O.SENT_STATUSES:
            with ProspectFile([{"org": "Org", "status": "drafted"}]) as f:
                O.mark("Org", st)
                self.assertEqual(f.read()[0].get("sent_at"), O.ledger.today(), st)

    def test_drafted_is_not_a_send(self):
        self.assertNotIn("drafted", O.SENT_STATUSES)


class AZeroHasToBeEarned(unittest.TestCase):
    """_sent_today distinguishes 'none sent' from 'cannot tell'."""

    def test_no_file_is_an_honest_zero(self):
        with ProspectFile() as f:                  # nothing written
            self.assertEqual(O._sent_today(), 0)

    def test_an_unreadable_file_is_unknown_not_zero(self):
        with ProspectFile(raw="{not json at all"):
            self.assertIsNone(O._sent_today())

    def test_a_non_list_payload_is_unknown(self):
        with ProspectFile(payload={"prospects": []}):
            self.assertIsNone(O._sent_today())

    def test_only_todays_sends_are_counted(self):
        with ProspectFile([{"org": "A", "sent_at": O.ledger.today()},
                           {"org": "B", "sent_at": "2026-01-01"},
                           {"org": "C", "status": "drafted"}]):
            self.assertEqual(O._sent_today(), 1)

    def test_unknown_is_not_recorded_at_all(self):
        # An absent reading means "we never measured"; a recorded 0 would be a
        # claim the corrupt file cannot support.
        rec, orig = Recorder(), O.ledger.record_result
        try:
            O.ledger.record_result = rec
            with ProspectFile(raw="{"):
                self.assertIsNone(O._record_sent())
        finally:
            O.ledger.record_result = orig
        self.assertEqual(rec.rows, [])

    def test_dry_run_writes_nothing(self):
        rec, orig = Recorder(), O.ledger.record_result
        try:
            O.ledger.record_result = rec
            with ProspectFile([{"org": "A", "sent_at": O.ledger.today()}]):
                self.assertIsNone(O._record_sent(dry_run=True))
                self.assertIsNone(O._record_drafted(3, dry_run=True))
        finally:
            O.ledger.record_result = orig
        self.assertEqual(rec.rows, [])


class TheCappedNightsAreReadingsNotHoles(unittest.TestCase):
    """run() records the send count before anything that can fail."""

    def setUp(self):
        self.rec = Recorder()
        self.orig_rr = O.ledger.record_result
        self.orig_key = O.scout.load_key
        self.orig_state = O.ledger.set_state
        self.orig_last = O.ledger.write_last_run
        O.ledger.record_result = self.rec
        O.ledger.set_state = lambda *a, **k: None
        O.ledger.write_last_run = lambda *a, **k: None

    def tearDown(self):
        O.ledger.record_result = self.orig_rr
        O.scout.load_key = self.orig_key
        O.ledger.set_state = self.orig_state
        O.ledger.write_last_run = self.orig_last

    def test_a_night_with_no_key_still_records_the_send_count(self):
        O.scout.load_key = lambda: None
        with ProspectFile([{"org": "A", "sent_at": O.ledger.today()}]):
            out = O.run()
        self.assertFalse(out["ok"])
        self.assertEqual(self.rec.values("emails_sent"), [1])

    def test_an_api_capped_night_still_records_the_send_count(self):
        # The real 2026-09-08..2026-10-12 shape: the key is present and the
        # call raises. The old code recorded nothing at all on this path, so
        # thirty-five consecutive nights of "did not act" were indistinguishable
        # from thirty-five nights the job never ran.
        O.scout.load_key = lambda: "sk-test"
        orig_call = O.scout.call_api

        def boom(*a, **k):
            raise RuntimeError("invalid_request_error: Your credit balance is too low")
        O.scout.call_api = boom
        try:
            with ProspectFile([]):
                out = O.run()
        finally:
            O.scout.call_api = orig_call
        self.assertFalse(out["ok"])
        self.assertIn("credit balance", out["detail"])
        self.assertEqual(self.rec.values("emails_sent"), [0])

    def test_the_send_count_is_recorded_before_the_key_is_read(self):
        # Ordering, not just presence: a future edit that moves the call below
        # the key check silently restores the hole.
        order = []
        O.scout.load_key = lambda: order.append("key") or None
        self.rec.rows = []

        def rr(date, technique, metric, value, meta=None):
            order.append(metric)
            return {}
        O.ledger.record_result = rr
        with ProspectFile([]):
            O.run()
        self.assertEqual(order[0], "emails_sent")
        self.assertIn("key", order)


class DraftsAreRecordedSeparately(unittest.TestCase):
    """drafts_written tells 'API capped' apart from 'drafted and never sent'."""

    def test_drafts_written_is_recorded_even_when_zero(self):
        rec, orig = Recorder(), O.ledger.record_result
        try:
            O.ledger.record_result = rec
            O._record_drafted(0)
        finally:
            O.ledger.record_result = orig
        self.assertEqual(rec.values("drafts_written"), [0])

    def test_drafts_go_under_the_techniques_own_slug(self):
        rec, orig = Recorder(), O.ledger.record_result
        try:
            O.ledger.record_result = rec
            O._record_drafted(2)
            with ProspectFile([]):
                O._record_sent()
        finally:
            O.ledger.record_result = orig
        self.assertEqual({t for _, t, _, _ in rec.rows}, {"b2b_outreach"})


class TheOwnerCanActuallyRecordASend(unittest.TestCase):
    """mark() had no caller in the repo, so the series would read 0 forever."""

    def test_the_cli_exposes_outreach_mark(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "growth_daily.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("outreach-mark", src)
        self.assertIn("cmd_outreach_mark", src)
        self.assertIn("outreach.mark(", src)


class MovementIsNotCreditedToATechniqueThatNeverActed(unittest.TestCase):
    """The second half of the gap: T008's counter is not flat, so the flat
    branch never saw it.

    mrr_usd went 0 → 4.99 over 78d — a subscription, not an outreach sale —
    which routed T008 to _judge_stock's "no comparable baseline" branch on
    every review since activation. Safe, and silent about the recorded fact
    that the technique has sent nothing.
    """

    FLAT_BEFORE = []

    def setUp(self):
        self.orig = R.ledger.series

    def tearDown(self):
        R.ledger.series = self.orig

    def _judge(self, rows, after):
        R.ledger.series = lambda t, m, since=None: list(rows.get((t, m), []))
        res = {"id": "T008", "slug": "b2b_outreach", "name": "x", "days_active": 78,
               "action": "keep", "why": "", "measured": {}, "works": None}
        return R._judge_stock(res, "mrr_usd", after, self.FLAT_BEFORE, 78)

    # T008's real mrr_usd shape: flat at 0 for most of its life, then a single
    # 4.99 subscription. Long enough to clear _judge_stock's own
    # GRACE_DAYS // 2 floor on the number of readings, which is what makes this
    # the branch the technique actually lands on.
    AFTER = ([(f"2026-08-{d:02d}", 0.0) for d in range(1, 29)]
             + [("2026-10-12", 4.99)])

    def test_a_moved_counter_with_zero_sends_is_not_attributed(self):
        out = self._judge({("b2b_outreach", "emails_sent"):
                           [("2026-08-01", 0), ("2026-09-01", 0)]}, self.AFTER)
        self.assertIsNone(out["works"])
        self.assertIn("acted 0 times", out["why"])
        self.assertIn("this technique did not cause it", out["why"])
        self.assertEqual(out["measured"]["executions"], 0)
        self.assertEqual(out["measured"]["execution_readings"], 2)

    def test_it_still_reports_the_movement_it_refuses_to_credit(self):
        # The number stays in the sentence: the refusal is about attribution,
        # not about hiding the reading.
        out = self._judge({("b2b_outreach", "emails_sent"): [("2026-08-01", 0)]},
                          self.AFTER)
        self.assertIn("4.99", out["why"])

    def test_an_unrecorded_series_still_falls_through_to_the_baseline_branch(self):
        # Positive evidence only. "We never measured whether it acted" must not
        # become "it did not act" — the same three-state rule as _sent_today.
        out = self._judge({}, self.AFTER)
        self.assertIn("no comparable baseline", out["why"])
        self.assertNotIn("executions", out["measured"])

    def test_a_send_on_record_lets_the_normal_judgement_proceed(self):
        out = self._judge({("b2b_outreach", "emails_sent"):
                           [("2026-08-01", 1), ("2026-09-01", 0)]}, self.AFTER)
        self.assertIn("no comparable baseline", out["why"])
        self.assertNotIn("did not cause it", out["why"])

    def test_the_guard_never_promotes_a_verdict(self):
        for rows in ({("b2b_outreach", "emails_sent"): [("2026-08-01", 0)]},
                     {("b2b_outreach", "emails_sent"): [("2026-08-01", 4)]},
                     {}):
            self.assertIsNone(self._judge(rows, self.AFTER)["works"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
