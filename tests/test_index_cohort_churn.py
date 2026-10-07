#!/usr/bin/env python3
"""The index census has to declare when its own sample moved.

WHY THIS FILE EXISTS. growth/indexstatus.py's levels — index_fetched,
index_indexed and every rate built on them — are only monotone over a FIXED
cohort, and reconcile() is allowed to replace cohort members whenever the
sitemaps change. On 2026-10-07 the advertised set fell 4,105 → 1,704 URLs
(the owner's 2026-10-06 commit dropped a sitemap promotion rule that read a
retired listings feed), 224 of 442 cohort rows were dropped and 208 drawn in,
and the night went out as index_fetched 95 → 119 and index_fetched_pct
20.8% → 35.6% after sixteen flat days. None of that was Googlebot. A docstring
cannot fail a build, so the contract is asserted here:

  * reconcile() measures what the departures took with them BEFORE popping
    them, on the same rules summarise() uses;
  * churn_report() marks the night incomparable above COHORT_CHURN_PCT and
    says so in words;
  * a quiet night still says the levels DO compare, because "no note" and
    "nothing moved" must not look the same.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from growth import indexstatus as ix  # noqa: E402

SITE = "https://findacrib.com"


def _url(n, fam="building"):
    return f"{SITE}/{fam}/manhattan/{n}-test-st-10000000{n:02d}/"


def _rec(crawled=None, state=None, first_indexed=None):
    """A cohort row as inspect() would have left it."""
    r = {"family": "building", "checked": "2026-10-01"}
    if crawled:
        r["crawled"] = crawled
    if state:
        r["state"] = state
    if first_indexed:
        r["first_indexed"] = first_indexed
    return r


class ReconcileAccountsForWhatItDrops(unittest.TestCase):

    def test_drop_is_measured_before_the_evidence_is_popped(self):
        cohort = {
            _url(1): _rec(crawled="2026-09-20", state="Submitted and indexed",
                          first_indexed="2026-09-21"),
            _url(2): _rec(crawled="2026-09-20",
                          state="Crawled - currently not indexed"),
            _url(3): _rec(),                       # never fetched
            _url(4): _rec(crawled="2026-09-22", state="Submitted and indexed"),
        }
        # Only /4/ survives into the sitemaps.
        cohort, dropped, added, took = ix.reconcile(dict(cohort), [_url(4)])
        self.assertEqual(sorted(dropped), sorted([_url(1), _url(2), _url(3)]))
        self.assertEqual(took["fetched"], 2)        # 1 and 2 carried crawl dates
        self.assertEqual(took["indexed"], 1)        # only 1 was indexed
        self.assertEqual(took["ever_indexed"], 1)   # only 1 carried first_indexed
        for u in (_url(1), _url(2), _url(3)):
            self.assertNotIn(u, cohort)

    def test_dropped_counts_agree_with_summarise_on_the_same_rows(self):
        """The two must not be able to disagree: `took` is yesterday's level
        minus today's, so it has to be counted the way summarise() counts."""
        rows = {
            _url(1): _rec(crawled="2026-09-20", state="Submitted and indexed",
                          first_indexed="2026-09-21"),
            _url(2): _rec(crawled="2026-09-20",
                          state="Crawled - currently not indexed"),
            _url(3): _rec(),
        }
        before = ix.summarise(dict(rows))["total"]
        _, _, _, took = ix.reconcile(dict(rows), [])        # drop all of them
        self.assertEqual(took["fetched"], before["fetched"])
        self.assertEqual(took["indexed"], before["indexed"])
        self.assertEqual(took["ever_indexed"], before["ever_indexed"])

    def test_an_unread_row_is_not_counted_as_indexed(self):
        """A row with a state but no reading is queue position, not a verdict —
        the same guard summarise() applies through `checked or bucket`."""
        stale = {"family": "building", "state": "Submitted and indexed"}
        _, _, _, took = ix.reconcile({_url(9): dict(stale)}, [])
        self.assertEqual(took["indexed"], 0)


class ChurnReportSaysWhetherTheLevelsCompare(unittest.TestCase):

    def test_a_half_replaced_cohort_is_not_comparable_and_says_why(self):
        cohort = {_url(i): _rec() for i in range(1, 219)}        # 218 rows
        ch = ix.churn_report(cohort, added=[_url(i) for i in range(1, 209)],
                             dropped=[f"{SITE}/gone/{i}/" for i in range(224)],
                             took={"fetched": 61, "indexed": 0, "ever_indexed": 2},
                             published=[_url(i) for i in range(1704)],
                             prev_published=4105)
        self.assertFalse(ch["comparable"])
        self.assertEqual(ch["added"], 208)
        self.assertEqual(ch["dropped"], 224)
        self.assertEqual(ch["dropped_fetched"], 61)
        self.assertEqual(ch["published"], 1704)
        self.assertEqual(ch["published_prev"], 4105)
        self.assertEqual(ch["published_shift"], -2401)
        self.assertLess(ch["published_shift_pct"], -25.0)
        self.assertIn("NOT comparable", ch["note"])
        self.assertIn("61", ch["note"])              # the arithmetic is in the words
        self.assertIn("index_crawls_14d", ch["note"])

    def test_a_quiet_night_says_the_levels_do_compare(self):
        cohort = {_url(i): _rec() for i in range(1, 51)}
        ch = ix.churn_report(cohort, added=[], dropped=[],
                             took={"fetched": 0, "indexed": 0, "ever_indexed": 0},
                             published=[_url(i) for i in range(1, 51)])
        self.assertTrue(ch["comparable"])
        self.assertEqual(ch["pct"], 0.0)
        self.assertIn("compare directly", ch["note"])
        self.assertNotIn("published_prev", ch)       # nothing to compare against

    def test_a_small_refill_stays_comparable(self):
        """Topping two families back up by a handful of URLs is routine and must
        not print a scare note every night — the threshold exists for events."""
        cohort = {_url(i): _rec() for i in range(1, 101)}
        ch = ix.churn_report(cohort, added=[_url(1), _url(2)], dropped=[_url(99)],
                             took={"fetched": 1, "indexed": 0, "ever_indexed": 0},
                             published=[_url(i) for i in range(1, 101)],
                             prev_published=101)
        self.assertTrue(ch["comparable"])
        self.assertEqual(ch["pct"], 3.0)
        self.assertNotIn("NOT comparable", ch["note"])
        self.assertIn("took", ch["note"])            # still reported, just not loud

    def test_threshold_is_the_constant_and_not_a_literal(self):
        """Moving COHORT_CHURN_PCT must move the verdict, or the constant is
        decoration and the next reviewer will edit it with no effect."""
        cohort = {_url(i): _rec() for i in range(1, 101)}
        args = dict(added=[_url(i) for i in range(1, 8)], dropped=[],
                    took={"fetched": 0, "indexed": 0, "ever_indexed": 0},
                    published=[_url(i) for i in range(1, 101)])
        self.assertTrue(ix.churn_report(cohort, **args)["comparable"])   # 7% < 10%
        old = ix.COHORT_CHURN_PCT
        try:
            ix.COHORT_CHURN_PCT = 5.0
            self.assertFalse(ix.churn_report(cohort, **args)["comparable"])
        finally:
            ix.COHORT_CHURN_PCT = old

    def test_empty_cohort_does_not_divide_by_zero(self):
        ch = ix.churn_report({}, added=[], dropped=[],
                             took={"fetched": 0, "indexed": 0, "ever_indexed": 0},
                             published=[])
        self.assertEqual(ch["pct"], 0.0)
        self.assertTrue(ch["comparable"])


class TheReportRendersTheQualifier(unittest.TestCase):

    def test_callout_appears_only_when_the_night_is_incomparable(self):
        from growth import report
        real = report._index_churn
        try:
            report._index_churn = lambda: {"comparable": False,
                                           "note": "the cohort moved by 97.7% tonight"}
            blocks = report.build_blocks()
            hit = [b for b in blocks
                   if b.get("type") == "callout" and "sample moved" in (b.get("heading") or "")]
            self.assertEqual(len(hit), 1, "exactly one churn callout expected")
            self.assertIn("97.7%", hit[0]["body"])

            report._index_churn = lambda: {"comparable": True, "note": "cohort unchanged"}
            blocks = report.build_blocks()
            self.assertFalse([b for b in blocks
                              if b.get("type") == "callout"
                              and "sample moved" in (b.get("heading") or "")])
        finally:
            report._index_churn = real


if __name__ == "__main__":
    unittest.main()
