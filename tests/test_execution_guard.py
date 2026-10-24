#!/usr/bin/env python3
"""The execution guard: a flat conversion counter is not a verdict on its own.

Shipped 2026-10-19. growth/review.py's _judge_stock flat branch used to hand the
reader an unresolved disjunction — "either nothing reaches this technique or
nothing it does converts" — on every technique whose cumulative metric had not
moved. Two live techniques carried that identical sentence on 2026-10-19 and
they are opposite cases: T011 lifecycle_email had sent 0 emails in its life, so
the second disjunct is impossible; T017 one_time_building_report_product had had
its $9 ask put to 15 people, so the FIRST one is. See EXECUTION_SERIES.

The other half of the change is the series itself: lifecycle.run() and
accounts.run() recorded their send counts only on the path that sent something,
so "due nobody" and "job never ran" were the same reading. Those are pinned here
too, because the guard is only as honest as the zeros underneath it.
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import accounts as A      # noqa: E402
from growth import lifecycle as L     # noqa: E402
from growth import review as R        # noqa: E402


class FakeSeries:
    """Stands in for ledger.series for one (technique, metric) pair."""

    def __init__(self, rows):
        self.rows = rows
        self.asked = []

    def __call__(self, technique, metric, since=None):
        self.asked.append((technique, metric))
        return list(self.rows.get((technique, metric), []))


class TheWindowIsTheVerdictsOwnSpan(unittest.TestCase):
    """_executions reads the span the verdict is about, not a wider one."""

    def setUp(self):
        self.orig = R.ledger.series

    def tearDown(self):
        R.ledger.series = self.orig

    def test_readings_outside_the_window_are_not_counted(self):
        # The real T011 shape: readings at activation, then silence across the
        # window the verdict speaks about. Counting the 2026-07-27 rows would
        # report the technique as having acted during a span it did not.
        R.ledger.series = FakeSeries({("lifecycle_email", "emails_sent"): [
            ("2026-07-27", 1), ("2026-07-27", 1)]})
        acted, readings = R._executions("lifecycle_email",
                                        ("2026-08-26", "2026-10-12"))
        self.assertIsNone(acted)
        self.assertEqual(readings, 0)

    def test_both_window_edges_are_inclusive(self):
        R.ledger.series = FakeSeries({("lifecycle_email", "emails_sent"): [
            ("2026-08-25", 5), ("2026-08-26", 1), ("2026-10-12", 2),
            ("2026-10-13", 9)]})
        acted, readings = R._executions("lifecycle_email",
                                        ("2026-08-26", "2026-10-12"))
        self.assertEqual((acted, readings), (3, 2))

    def test_an_unmapped_technique_reads_unknown_and_asks_nothing(self):
        # The guard must need positive evidence, like MIN_CENSUS_READ, and must
        # not invent a zero for a technique it has no series for.
        #
        # This used to be asserted of b2b_outreach, which was the live example
        # of an unmapped technique until 2026-10-24, when T008's revisit gave it
        # growth/outreach.py's emails_sent series. The example moved; the rule
        # did not. Taking the slug from the ledger rather than naming one keeps
        # it true the next time a technique gets mapped.
        fake = FakeSeries({})
        R.ledger.series = fake
        from growth import ledger
        unmapped = [t["slug"] for t in ledger.load_techniques()
                    if t.get("status") == "active" and t["slug"] not in R.EXECUTION_SERIES]
        self.assertTrue(unmapped, "every active technique is mapped — update this test")
        for slug in unmapped[:3] + ["no-such-technique-slug"]:
            self.assertEqual(R._executions(slug, ("2026-08-26", "2026-10-12")),
                             (None, 0), slug)
        self.assertEqual(fake.asked, [])

    def test_no_window_reads_unknown(self):
        R.ledger.series = FakeSeries({("lifecycle_email", "emails_sent"): [
            ("2026-09-01", 3)]})
        self.assertEqual(R._executions("lifecycle_email", None), (None, 0))

    def test_a_recorded_zero_is_a_reading_and_not_an_absence(self):
        # The whole point of the lifecycle/accounts half of this change.
        R.ledger.series = FakeSeries({("lifecycle_email", "emails_sent"): [
            ("2026-09-01", 0), ("2026-09-02", 0)]})
        acted, readings = R._executions("lifecycle_email",
                                        ("2026-08-26", "2026-10-12"))
        self.assertEqual(acted, 0)
        self.assertEqual(readings, 2)
        self.assertIsNotNone(acted)

    def test_an_unreadable_value_is_skipped_not_counted_as_a_reading(self):
        R.ledger.series = FakeSeries({("lifecycle_email", "emails_sent"): [
            ("2026-09-01", None), ("2026-09-02", "x")]})
        self.assertEqual(R._executions("lifecycle_email",
                                       ("2026-08-26", "2026-10-12")), (None, 0))

    def test_t017_reads_the_series_the_account_sequence_writes(self):
        # The $9 ask is put by accounts.py, not by T017, so T017's execution
        # series lives under another technique's slug. A mutation pointing it at
        # its own slug would read nothing and silently report "unrecorded".
        fake = FakeSeries({("account_lifecycle", "sent_saved_paid_ask"): [
            ("2026-10-11", 2), ("2026-10-12", 0)]})
        R.ledger.series = fake
        acted, readings = R._executions("one_time_building_report_product",
                                        ("2026-08-26", "2026-10-12"))
        self.assertEqual((acted, readings), (2, 2))
        self.assertEqual(fake.asked, [("account_lifecycle", "sent_saved_paid_ask")])


class TheFlatVerdictSaysWhich(unittest.TestCase):
    """_judge_stock's flat branch, the three states."""

    def setUp(self):
        self.orig = R.ledger.series

    def tearDown(self):
        R.ledger.series = self.orig

    # A flat reading on every one of the 48 days 2026-08-26..2026-10-12 — the
    # real shape of T011's and T017's reports_sold series. _judge_stock needs at
    # least GRACE_DAYS // 2 readings before it will look at a stock at all, so a
    # two-point fixture never reaches the flat branch.
    FLAT = [((datetime.date(2026, 8, 26) + datetime.timedelta(days=i)).isoformat(), 0)
            for i in range((datetime.date(2026, 10, 12)
                            - datetime.date(2026, 8, 26)).days + 1)]

    def _flat(self, slug, rows, after=None):
        R.ledger.series = FakeSeries(rows)
        res = {"id": "T0", "slug": slug, "name": slug, "days_active": 47,
               "action": "keep", "why": "", "measured": {}, "works": None}
        return R._judge_stock(res, "reports_sold", after or self.FLAT, [], 47)

    def test_never_acted_is_not_reported_as_not_converting(self):
        res = self._flat("lifecycle_email",
                         {("lifecycle_email", "emails_sent"):
                          [("2026-09-%02d" % d, 0) for d in range(1, 13)]})
        self.assertIn("acted 0 times", res["why"])
        self.assertIn("its own execution and not its effect", res["why"])
        self.assertIn("unmeasurable by construction", res["why"])
        self.assertNotIn("nothing it does converts", res["why"])
        self.assertEqual(res["measured"]["executions"], 0)
        self.assertEqual(res["measured"]["execution_readings"], 12)

    def test_having_acted_rules_out_the_other_disjunct(self):
        res = self._flat("one_time_building_report_product",
                         {("account_lifecycle", "sent_saved_paid_ask"):
                          [("2026-10-11", 15)]})
        self.assertIn("DID act 15 time(s)", res["why"])
        self.assertIn("nothing-reaches-it is ruled out", res["why"])
        self.assertNotIn("nothing it does converts", res["why"])
        self.assertEqual(res["measured"]["executions"], 15)

    def test_an_unrecorded_count_keeps_the_disjunction_and_names_the_gap(self):
        # T008's case. The old sentence survives, because it is the honest one
        # when nothing was measured — but it now says so out loud.
        res = self._flat("b2b_outreach", {})
        self.assertIn("either nothing reaches this technique or nothing it "
                      "does converts", res["why"])
        self.assertIn("action count is unrecorded", res["why"])
        self.assertIsNone(res["measured"]["executions"])
        self.assertEqual(res["measured"]["execution_readings"], 0)

    def test_every_branch_flags_and_none_of_them_credits_or_retires(self):
        for slug, rows in (
                ("lifecycle_email", {("lifecycle_email", "emails_sent"):
                                     [("2026-09-01", 0)]}),
                ("one_time_building_report_product",
                 {("account_lifecycle", "sent_saved_paid_ask"): [("2026-09-01", 4)]}),
                ("b2b_outreach", {})):
            res = self._flat(slug, rows)
            self.assertEqual(res["action"], "flag", slug)
            self.assertIsNone(res["works"], slug)

    def test_the_moved_clause_and_the_raw_measurements_survive(self):
        res = self._flat("b2b_outreach", {})
        self.assertIn("reports_sold went 0 → 0 (0) over 47d", res["why"])
        self.assertEqual(res["measured"]["kind"], "stock")
        self.assertEqual(res["measured"]["delta_after"], 0)
        self.assertEqual(res["measured"]["span_days_after"], 47)

    def test_a_counter_that_moved_never_reaches_the_guard(self):
        R.ledger.series = FakeSeries({})
        res = {"id": "T0", "slug": "lifecycle_email", "name": "x",
               "days_active": 47, "action": "keep", "why": "", "measured": {},
               "works": None}
        after = self.FLAT[:-1] + [("2026-10-12", 3)]
        out = R._judge_stock(res, "reports_sold", after, [], 47)
        self.assertNotIn("executions", out["measured"])
        self.assertNotIn("acted", out["why"])


class TheZerosUnderneathAreRecorded(unittest.TestCase):
    """lifecycle.run / accounts.run write a count from every path that LOOKED."""

    def test_lifecycle_records_a_zero_when_nothing_was_due(self):
        seen = []
        orig_r, orig_s, orig_due = (L.ledger.record_result, L.ledger.set_state, L.due)
        L.ledger.record_result = lambda d, t, m, v: seen.append((t, m, v))
        L.ledger.set_state = lambda *a, **k: None
        L.due = lambda now=None: []
        try:
            out = L.run()
        finally:
            L.ledger.record_result, L.ledger.set_state, L.due = orig_r, orig_s, orig_due
        self.assertEqual(out["detail"], "nothing due")
        self.assertIn(("lifecycle_email", "emails_sent", 0), seen)

    def test_lifecycle_records_nothing_when_it_could_not_look(self):
        # An exception reading building_reports means the run never established
        # that nobody was due. A 0 here would be the false zero one layer down.
        seen = []
        orig_r, orig_s, orig_due = (L.ledger.record_result, L.ledger.set_state, L.due)
        L.ledger.record_result = lambda d, t, m, v: seen.append((t, m, v))
        L.ledger.set_state = lambda *a, **k: None

        def boom(now=None):
            raise RuntimeError("no network")

        L.due = boom
        try:
            out = L.run()
        finally:
            L.ledger.record_result, L.ledger.set_state, L.due = orig_r, orig_s, orig_due
        self.assertFalse(out["ok"])
        self.assertEqual(seen, [])

    def test_accounts_records_the_full_set_when_nothing_was_due(self):
        seen = []
        orig_r, orig_s, orig_due = (A.ledger.record_result, A.ledger.set_state, A.due)
        A.ledger.record_result = lambda d, t, m, v: seen.append((t, m, v))
        A.ledger.set_state = lambda *a, **k: None
        A.due = lambda now=None: ([], 0)
        try:
            out = A.run()
        finally:
            A.ledger.record_result, A.ledger.set_state, A.due = orig_r, orig_s, orig_due
        self.assertEqual(out["detail"], "nothing due")
        self.assertIn(("account_lifecycle", "emails_sent", 0), seen)
        self.assertIn(("account_lifecycle", "sent_saved_paid_ask", 0), seen)
        self.assertIn(("account_lifecycle", "welcome_aged_out", 0), seen)
        for step in A.STEPS:
            self.assertIn(("account_lifecycle", f"sent_{step}", 0), seen)

    def test_accounts_records_nothing_when_it_could_not_look(self):
        seen = []
        orig_r, orig_s, orig_due = (A.ledger.record_result, A.ledger.set_state, A.due)
        A.ledger.record_result = lambda d, t, m, v: seen.append((t, m, v))
        A.ledger.set_state = lambda *a, **k: None

        def boom(now=None):
            raise RuntimeError("no network")

        A.due = boom
        try:
            out = A.run()
        finally:
            A.ledger.record_result, A.ledger.set_state, A.due = orig_r, orig_s, orig_due
        self.assertFalse(out["ok"])
        self.assertEqual(seen, [])

    def test_the_accounts_total_still_equals_the_sum_of_its_steps(self):
        # _record_sent derives the total from by_step rather than len(sent); a
        # drift between the two would make emails_sent disagree with sent_*.
        seen = []
        orig = A.ledger.record_result
        A.ledger.record_result = lambda d, t, m, v: seen.append((t, m, v))
        try:
            A._record_sent({"welcome": 3, "saved": 2}, 2)
        finally:
            A.ledger.record_result = orig
        total = dict((m, v) for _, m, v in seen)["emails_sent"]
        steps = sum(v for _, m, v in seen
                    if m.startswith("sent_") and m != "sent_saved_paid_ask")
        self.assertEqual(total, 5)
        self.assertEqual(total, steps)


class TheMappingPointsAtRealSeries(unittest.TestCase):
    """EXECUTION_SERIES names series the jobs actually write."""

    def test_every_mapped_series_is_recorded_somewhere_in_the_code(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = ""
        # outreach.py joined these on 2026-10-24 with T008's emails_sent series.
        for name in ("lifecycle.py", "accounts.py", "outreach.py"):
            with open(os.path.join(root, "growth", name), encoding="utf-8") as f:
                src += f.read()
        for slug, (tech, metric) in R.EXECUTION_SERIES.items():
            self.assertIn(f'"{tech}"', src, slug)
            self.assertIn(f'"{metric}"', src, slug)

    def test_the_mapped_slugs_are_live_techniques(self):
        from growth import ledger
        slugs = {t["slug"] for t in ledger.load_techniques()}
        for slug in R.EXECUTION_SERIES:
            self.assertIn(slug, slugs)

    def test_t017_is_not_mapped_to_its_own_slug(self):
        # Pins the asymmetry that makes this worth a mapping at all.
        self.assertEqual(R.EXECUTION_SERIES["one_time_building_report_product"][0],
                         "account_lifecycle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
