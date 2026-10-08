#!/usr/bin/env python3
"""The crawl-window counts are levels over `read`, and have to say so.

WHY THIS FILE EXISTS. growth/indexstatus.py's crawls_14d / crawls_28d were
introduced as the one number in that module that is "a rate and not a level",
and the 2026-10-07 journal entry told the next reader to disregard a jump in
index_fetched and read index_crawls_14d instead on exactly that ground. The
claim is false. summarise() skips every cohort row this sampler has not yet
inspected, so the counts are levels over `read` — and `read` collapses on the
night reconcile() swaps members in and climbs back as the rotation catches up.

The evidence is in results.jsonl and it is clean, because Googlebot is held
fixed: 2026-10-07 was measured twice, by the 05:00 cron and by a second run
that afternoon, against the same 442-URL cohort on the same date.

    05:11Z   read 334   crawls_14d  6
    17:57Z   read 434   crawls_14d 10

Nothing Google did changed between those two readings; 100 more rows were
read. So the "7 → 6" published as the honest reading of that night was itself
depressed by the re-draw it was reporting, and the "7 → 10" the next morning's
series shows is the rotation finishing. The contract asserted here:

  * summarise() divides by `read` and not by `cohort`, and reports None rather
    than 0% when nothing has been read;
  * crawl_rate_report() refuses the comparison when read depth moved more than
    READ_SHIFT_PCT, says so in words, and gives the rate that does compare;
  * no baseline reads as None and not as "comparable";
  * the report renders the warning exactly once, and not at all when the read
    depth held.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from growth import indexstatus as ix  # noqa: E402

SITE = "https://findacrib.com"

# The two readings of 2026-10-07, and the night before it. These are the real
# numbers out of growth/results.jsonl, not illustrations.
OCT06 = (7, 458)        # (crawls_14d, read) — cohort fully read
OCT07_AM = (6, 334)     # 05:11Z, 108 of 442 rows not yet re-read
OCT07_PM = (10, 434)    # 17:57Z, same date, same cohort, 100 more inspections
OCT08 = (10, 442)       # rotation finished


def _cohort(read_rows, crawled_rows, unread_rows=0, crawled="2026-10-06"):
    """A cohort where `read_rows` have been inspected and `crawled_rows` of
    those carry a recent crawl date, plus `unread_rows` never inspected."""
    c = {}
    n = 0
    for i in range(read_rows):
        n += 1
        rec = {"family": "building", "checked": "2026-10-07",
               "state": "Crawled - currently not indexed"}
        if i < crawled_rows:
            rec["crawled"] = crawled
        c[f"{SITE}/building/manhattan/{n}-test-st/"] = rec
    for _ in range(unread_rows):
        n += 1
        c[f"{SITE}/building/manhattan/{n}-test-st/"] = {"family": "building"}
    return c


class SummariseDividesByRead(unittest.TestCase):
    def test_denominator_is_read_not_cohort(self):
        """10 crawled of 334 read, with 108 rows never inspected.

        The rate must be 10/334, not 10/442: an uninspected row is skipped by
        the loop and so cannot be in the denominator of a number built in it.
        """
        tot = ix.summarise(_cohort(334, 10, unread_rows=108),
                           today="2026-10-08")["total"]
        self.assertEqual(tot["read"], 334)
        self.assertEqual(tot["cohort"], 442)
        self.assertEqual(tot["crawls_14d"], 10)
        self.assertEqual(tot["crawl_rate_14d"], round(100.0 * 10 / 334, 2))
        self.assertNotEqual(tot["crawl_rate_14d"], round(100.0 * 10 / 442, 2))
        self.assertEqual(tot["read_pct"], round(100.0 * 334 / 442, 1))

    def test_same_crawls_different_read_depth_differ_in_count_not_rate(self):
        """THE WHOLE POINT, as a test rather than a comment.

        Two readings of one night: the same 10 crawled pages, read at 334 rows
        and at 434. The count a reader would quote is identical only because
        this fixture holds the crawls fixed — what moves is the rate, and it
        moves DOWN as more uncrawled rows come into view. A real sampler finds
        more crawls as it reads more rows, which is the 6 → 10 direction; both
        directions are the denominator moving and neither is Googlebot.
        """
        a = ix.summarise(_cohort(334, 10, unread_rows=108),
                         today="2026-10-08")["total"]
        b = ix.summarise(_cohort(434, 10, unread_rows=8),
                         today="2026-10-08")["total"]
        self.assertEqual(a["crawls_14d"], b["crawls_14d"])
        self.assertGreater(a["crawl_rate_14d"], b["crawl_rate_14d"])

    def test_nothing_read_is_none_and_not_zero(self):
        """A crawl rate off an empty sample is not 0% of anything."""
        tot = ix.summarise(_cohort(0, 0, unread_rows=50),
                           today="2026-10-08")["total"]
        self.assertEqual(tot["read"], 0)
        self.assertIsNone(tot["crawl_rate_14d"])
        self.assertIsNone(tot["crawl_rate_28d"])


class CrawlRateReportVerdict(unittest.TestCase):
    def test_the_redraw_night_is_refused(self):
        """2026-10-06 → 2026-10-07 05:11: read fell 27.1%, so 7 → 6 is not a fall."""
        r = ix.crawl_rate_report(OCT07_AM[0], OCT07_AM[1], OCT06[0], OCT06[1])
        self.assertFalse(r["comparable"])
        self.assertEqual(r["read_shift_pct"], -27.1)
        self.assertIn("fewer rows", r["note"])
        self.assertIn("NOT a trend", r["note"])
        # and it must hand over the comparison that IS valid
        self.assertEqual(r["rate_pct"], round(100.0 * 6 / 334, 2))
        self.assertEqual(r["rate_pct_prev"], round(100.0 * 7 / 458, 2))
        self.assertIn("1.53%", r["note"])
        self.assertIn("1.80%", r["note"])

    def test_the_rotation_catching_up_is_also_refused(self):
        """05:11 → 17:57 on the SAME DATE: read rose 29.9%, so 6 → 10 is not a rise.

        This is the pair that proves the whole case, because the two readings
        share a date and a cohort and differ only in how many rows were read.
        """
        r = ix.crawl_rate_report(OCT07_PM[0], OCT07_PM[1], OCT07_AM[0], OCT07_AM[1])
        self.assertFalse(r["comparable"])
        self.assertIn("more rows", r["note"])

    def test_a_settled_night_compares(self):
        """17:57 → 2026-10-08: read moved +1.8%, inside READ_SHIFT_PCT."""
        r = ix.crawl_rate_report(OCT08[0], OCT08[1], OCT07_PM[0], OCT07_PM[1])
        self.assertTrue(r["comparable"])
        self.assertEqual(r["read_shift_pct"], 1.8)
        self.assertIn("compare directly", r["note"])
        self.assertNotIn("NOT a trend", r["note"])

    def test_no_baseline_is_none_not_comparable(self):
        """"No earlier reading" and "a baseline that agrees" must not render alike."""
        r = ix.crawl_rate_report(OCT08[0], OCT08[1])
        self.assertIsNone(r["comparable"])
        self.assertIn("no earlier reading", r["note"])
        self.assertNotIn("compare directly", r["note"])

    def test_the_constant_actually_drives_the_verdict(self):
        """Move READ_SHIFT_PCT, the verdict moves — otherwise it is decoration."""
        pair = (OCT08[0], OCT08[1], OCT07_PM[0], OCT07_PM[1])   # +1.8%
        self.assertTrue(ix.crawl_rate_report(*pair)["comparable"])
        old = ix.READ_SHIFT_PCT
        try:
            ix.READ_SHIFT_PCT = 1.0
            self.assertFalse(ix.crawl_rate_report(*pair)["comparable"])
        finally:
            ix.READ_SHIFT_PCT = old

    def test_nothing_inspected_is_an_instrument_condition(self):
        """A denied quota leaves read=0. That is not a 0% crawl rate.

        Reachable in collect(): this record is built before the tot["read"]
        gate, so a night the API answered nothing still comes through here.
        """
        r = ix.crawl_rate_report(0, 0, 7, 458)
        self.assertIsNone(r["rate_pct"])
        self.assertIsNone(r["comparable"])          # not False: nothing was refused
        self.assertIn("instrument condition", r["note"])
        self.assertNotIn("NOT a trend", r["note"])

    def test_no_previous_read_does_not_divide_by_zero(self):
        r = ix.crawl_rate_report(0, 100, 0, 0)
        self.assertIsNone(r["comparable"])
        self.assertEqual(r["rate_pct"], 0.0)        # 0 of 100 read IS a rate


class ReportRendersTheQualifier(unittest.TestCase):
    """The warning has to reach the email, once, and only when it applies."""

    def _blocks(self, record):
        from growth import report
        orig = report._index_crawl_rate
        try:
            report._index_crawl_rate = lambda: record
            summary, html, text = report.build()
        finally:
            report._index_crawl_rate = orig
        return html, text

    def test_rendered_once_when_read_depth_moved(self):
        rec = ix.crawl_rate_report(OCT07_AM[0], OCT07_AM[1], OCT06[0], OCT06[1])
        html, text = self._blocks(rec)
        self.assertEqual(html.count("Read depth moved"), 1)
        self.assertEqual(text.count("Read depth moved"), 1)
        # the plain-text part must carry the arithmetic, not just the heading
        self.assertIn("458", text)

    def test_not_rendered_when_it_compares(self):
        rec = ix.crawl_rate_report(OCT08[0], OCT08[1], OCT07_PM[0], OCT07_PM[1])
        html, text = self._blocks(rec)
        self.assertNotIn("Read depth moved", html)
        self.assertNotIn("Read depth moved", text)

    def test_not_rendered_without_a_baseline(self):
        rec = ix.crawl_rate_report(OCT08[0], OCT08[1])
        html, text = self._blocks(rec)
        self.assertNotIn("Read depth moved", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
