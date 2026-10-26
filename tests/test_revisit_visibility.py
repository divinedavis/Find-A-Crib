#!/usr/bin/env python3
"""A due revisit was invisible to the command that was supposed to act on it.

Shipped 2026-10-26, in two halves.

HALF ONE — VISIBILITY. ledger.revisit_due() had exactly one caller in the
repo: growth/report.py, the Friday email. So step three of the daily review
("handle anything due for revisit") depended on a weekly report, and that
report has not been sent since the owner paused the growth crons on
2026-10-12. `growth_daily.py status` — the command the review actually runs —
listed all 107 techniques and every verdict and said nothing about which were
due.

It cost two revisits. On 2026-10-25 the journal recorded "no revisit pushed
(none came due: the nearest is T023 on 2026-10-27)" while T011 lifecycle_email
and T018 account_lifecycle were both due THAT DAY. Nothing catches a missed
revisit up: revisit_due() is a `<= as_of` filter, so a skipped one stays due
and stays silent. Hence OVERDUE, which the weekly report never said either.

Each line also carries ledger.measured_nights_since(), because revisit_on is
thirty days of CLOCK and not thirty days of measurement. On 2026-10-26 all
five due techniques had verdicts decided 2026-10-12 and zero nights of
evidence since, so the loop was being asked to re-decide each one on exactly
the data that produced the verdict being re-decided.

HALF TWO — T010 IS AN INSTRUMENT. review._judge_audit exists for techniques
that publish nothing and cannot move what they read. T010 gsc_integration was
left out of that class and named in the judge's own rationale on the ACTOR
side, so it kept being judged on site-wide organic_visitors — a Search Console
reader credited with "median 41.5/day vs 6.0/day". Its ledger notes had
diagnosed the category error twice (2026-08-27, 2026-09-26) and both revisits
left it alone, because the only remedy either considered was repointing
`metric`, which buys nothing. judge="audit" is the third remedy and postdates
both notes.

These tests pin: the overdue arithmetic in both renderers, that a missed
revisit is still reported, the nights-measured distinction between 0 and
unknown, that T010 routes to the audit judge and reads the Search Console
record rather than build.techniques, that its detail never quotes
serving_pages without the census column that contradicts it, that `ok` is
passed through rather than synthesized, and that seed.py agrees with the
ledger so the next deploy cannot silently revert the judge.
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import growth_daily                  # noqa: E402
from growth import ledger            # noqa: E402
from growth import report as RP      # noqa: E402
from growth import review as R       # noqa: E402
from growth import seed              # noqa: E402


def rec(tid="T900", slug="synthetic", on="2026-10-20", decided="2026-10-01",
        status="active", **kw):
    t = {"id": tid, "slug": slug, "name": f"name {tid}", "kind": "content",
         "status": status, "revisit_on": on, "activated": "2026-01-01",
         "verdict": ({"decided": decided, "works": None, "why": "w"} if decided else None)}
    t.update(kw)
    return t


class OverdueIsStated(unittest.TestCase):
    """The subtraction the reader was being left to do by eye."""

    def lines(self, techs, as_of="2026-10-26", nights=0):
        self._orig = (ledger.revisit_due, ledger.measured_nights_since)
        ledger.revisit_due = lambda as_of=None: techs
        ledger.measured_nights_since = lambda d: nights
        try:
            return growth_daily.revisit_lines(as_of=as_of)
        finally:
            ledger.revisit_due, ledger.measured_nights_since = self._orig

    def test_one_day_late_is_singular(self):
        out = "\n".join(self.lines([rec(on="2026-10-25")]))
        self.assertIn("1 DAY OVERDUE", out)
        self.assertNotIn("1 DAYS OVERDUE", out)

    def test_several_days_late_is_plural(self):
        out = "\n".join(self.lines([rec(on="2026-10-20")]))
        self.assertIn("6 DAYS OVERDUE", out)

    def test_due_today_is_not_overdue(self):
        out = "\n".join(self.lines([rec(on="2026-10-26")]))
        self.assertIn("due today", out)
        self.assertNotIn("OVERDUE", out)

    def test_the_missed_ones_are_listed_first(self):
        """The whole point: a revisit already skipped must be the first thing
        read, not sorted under one that only came due this morning."""
        out = self.lines([rec(tid="T001", on="2026-10-26"),
                          rec(tid="T002", on="2026-10-24")])
        body = "\n".join(out)
        self.assertLess(body.index("T002"), body.index("T001"))
        self.assertIn("!", out[1])

    def test_nothing_due_says_so_rather_than_printing_nothing(self):
        self.assertEqual(self.lines([]), ["revisits: none due"])

    def test_count_is_in_the_header(self):
        self.assertIn("due for revisit (2)", self.lines([rec(tid="T1"), rec(tid="T2")])[0])

    def test_unreadable_date_does_not_crash_or_claim_overdue(self):
        out = "\n".join(self.lines([rec(on="not-a-date")]))
        self.assertIn("scheduled date unreadable", out)
        self.assertNotIn("OVERDUE", out)


class EvidenceBehindTheRevisitIsStated(unittest.TestCase):
    """revisit_on is thirty days of clock, not thirty days of measurement."""

    def lines(self, techs, nights, as_of="2026-10-26"):
        orig = (ledger.revisit_due, ledger.measured_nights_since)
        ledger.revisit_due = lambda as_of=None: techs
        ledger.measured_nights_since = lambda d: nights
        try:
            return growth_daily.revisit_lines(as_of=as_of)
        finally:
            ledger.revisit_due, ledger.measured_nights_since = orig

    def test_zero_nights_is_called_out_once_for_the_whole_block(self):
        out = "\n".join(self.lines([rec(tid="T1"), rec(tid="T2")], nights=0))
        self.assertIn("0 new nights of evidence", out)
        self.assertEqual(out.count("0 new nights of evidence"), 1)

    def test_real_evidence_removes_the_call_out(self):
        out = "\n".join(self.lines([rec()], nights=30))
        self.assertIn("30 nights measured since the verdict of 2026-10-01", out)
        self.assertNotIn("0 new nights of evidence", out)

    def test_one_night_is_singular(self):
        self.assertIn("1 night measured", "\n".join(self.lines([rec()], nights=1)))

    def test_unknown_evidence_is_not_reported_as_zero(self):
        """None and 0 are different answers and must not render alike."""
        out = "\n".join(self.lines([rec()], nights=None))
        self.assertIn("new evidence since it unreadable", out)
        self.assertNotIn("0 nights measured", out)

    def test_a_technique_never_judged_says_there_is_no_verdict(self):
        """The T016 shape: due for revisit with nothing to re-examine."""
        out = "\n".join(self.lines([rec(decided=None)], nights=0))
        self.assertIn("NO VERDICT EVER RECORDED", out)

    def test_retirement_before_the_booked_date_is_flagged(self):
        out = "\n".join(self.lines(
            [rec(status="retired", retired="2026-10-01", on="2026-10-20")], nights=0))
        self.assertIn("RETIRED 2026-10-01, before this date", out)
        self.assertIn("do not skip it", out)


class MeasuredNightsCountsNights(unittest.TestCase):
    def test_counts_distinct_dates_strictly_after(self):
        rows = [{"date": "2026-10-11"}, {"date": "2026-10-12"},
                {"date": "2026-10-13"}, {"date": "2026-10-13"}]
        orig = ledger.read_results
        ledger.read_results = lambda *a, **k: rows
        try:
            self.assertEqual(ledger.measured_nights_since("2026-10-12"), 1)
            self.assertEqual(ledger.measured_nights_since("2026-10-10"), 3)
            self.assertEqual(ledger.measured_nights_since("2026-10-13"), 0)
        finally:
            ledger.read_results = orig

    def test_unreadable_input_is_none_not_zero(self):
        self.assertIsNone(ledger.measured_nights_since(None))
        self.assertIsNone(ledger.measured_nights_since(""))
        self.assertIsNone(ledger.measured_nights_since("2026-13-99"))
        self.assertIsNone(ledger.measured_nights_since(20261012))

    def test_the_live_ledger_is_frozen_where_last_run_says_it_is(self):
        """Pins today's real reading: nothing has been measured since the
        pause, so every revisit coming due is asked on frozen evidence."""
        self.assertEqual(ledger.measured_nights_since("2026-10-12"), 0)


class ReportSaysItToo(unittest.TestCase):
    def test_days_late_is_never_negative(self):
        self.assertEqual(RP._days_late("2026-12-01", datetime.date(2026, 10, 26)), 0)

    def test_days_late_counts_up(self):
        self.assertEqual(RP._days_late("2026-10-20", datetime.date(2026, 10, 26)), 6)

    def test_days_late_survives_a_bad_date(self):
        self.assertEqual(RP._days_late(None), 0)
        self.assertEqual(RP._days_late("nope"), 0)

    def test_both_parts_carry_the_overdue_clause(self):
        """emailkit renders the HTML and the text from one block list, so this
        asserts they cannot drift apart on this field."""
        _s, h, t = RP.build()
        if "DUE FOR REVISIT" not in t.upper():
            self.skipTest("nothing due in the live ledger")
        self.assertEqual("OVERDUE" in h, "OVERDUE" in t)
        self.assertIn("nights measured since the verdict", t)


class T010IsJudgedAsTheInstrumentItIs(unittest.TestCase):
    def test_the_ledger_marks_it_audit(self):
        self.assertEqual(ledger.get("T010").get("judge"), "audit")

    def test_seed_agrees_so_a_deploy_cannot_revert_it(self):
        """seed.run() syncs `judge` from this file, so a ledger-only edit is
        one deploy away from being undone."""
        got = [s.get("judge") for s in seed.SEEDS if s["slug"] == "gsc_integration"]
        self.assertEqual(got, ["audit"])

    def test_it_routes_to_the_audit_judge_and_never_to_traffic(self):
        r = R.evaluate(ledger.get("T010"), ledger.load_techniques())
        self.assertEqual(r["action"], "keep")
        self.assertIsNone(r["works"])
        self.assertFalse(r["measured"]["publishes_urls"])
        self.assertNotIn("organic_visitors", r["why"])

    def test_its_reading_comes_from_the_search_console_record(self):
        self.assertEqual(R.AUDIT_READING_SOURCES.get("gsc_integration"), "searchconsole")
        rd = R._audit_reading("gsc_integration")
        self.assertIsNotNone(rd, "no reading — the fallback is not finding the record")
        self.assertIn("pages served in search", rd["detail"])

    def test_serving_pages_is_never_quoted_without_the_census_contradiction(self):
        """A standing rule of this loop: gsc_serving_pages on its own overstates
        the footprint, because Google's own census contradicts some of it."""
        d = R._gsc_reading({"serving_pages": 10, "serving_census_contradicted": 3,
                            "serving_census_indexed": 1, "window": "a..b"})["detail"]
        self.assertIn("10 pages served", d)
        self.assertIn("3 census-contradicted", d)

    def test_ok_is_passed_through_and_never_invented(self):
        """The ab747de lesson, applied in the other direction: a reader must not
        synthesize a green from a record whose job never wrote one."""
        self.assertIsNone(R._gsc_reading({"serving_pages": 1})["ok"])
        self.assertIs(R._gsc_reading({"ok": True})["ok"], True)
        self.assertIs(R._gsc_reading({"ok": False})["ok"], False)
        self.assertIsNone(R._gsc_reading(None))

    def test_a_record_with_no_ok_reads_as_not_recorded_not_as_failing(self):
        why = R.evaluate(ledger.get("T010"), ledger.load_techniques())["why"]
        self.assertIn("no pass/fail recorded", why)
        self.assertNotIn("FAILING", why)

    def test_it_stops_diluting_the_techniques_that_do_act(self):
        """_co_claimants skips an audit, so moving T010 out of the actor class
        makes T004's and T005's verdicts truer as a side effect."""
        techs = ledger.load_techniques()
        for tid in ("T004", "T005"):
            co = R.evaluate(ledger.get(tid), techs)["measured"].get("co_claimants") or []
            self.assertNotIn("T010 gsc_integration", co)

    def test_every_audit_judged_technique_publishes_nothing(self):
        """The class invariant. A technique that owns URLs must be judged on
        them, never on its own audit line."""
        for t in ledger.load_techniques():
            if t.get("judge") == "audit":
                self.assertFalse(t.get("prefixes"),
                                 f"{t['id']} {t['slug']} owns URLs but is judged as an audit")


if __name__ == "__main__":
    unittest.main()
