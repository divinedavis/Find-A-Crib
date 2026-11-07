#!/usr/bin/env python3
"""serving_coappearance(): aggregated by page, ONE result page listing ten of
this site's URLs is ten rows and ten impressions — so gsc_serving_pages counts
result slots as pages.

Shipped 2026-11-07. Google's documentation for the performance report says the
two aggregations differ exactly this way: by PROPERTY, all the results for one
query that point to this site count once; by PAGE, each unique URL is its own
impression. collect() reads gsc_serving_pages off the PAGE pull, and every
review since 2026-07-27 has been told that number is "how many of the ~47,600
published pages earned a Search Console impression".

The reading that produced it: ten serving pages, the homepage at position 1.5
with 147 impressions and NINE building pages at EXACTLY 3 impressions each,
holding positions 2, 3, 4, 5, 6, 7, 8, 9 and 10 — each integer once, no gaps,
no repeats. Both existing qualifiers were silent on all nine: Search Console
returned no query row for any of them (serving_brand `unattributed` 9) and the
index census has never sampled one (serving_census `unsampled` 9).

So the ways this can go wrong are the ways it could hand back a bolder claim
than the geometry supports:

  * grouping rows that cannot be one result page — a URL whose average
    position is fractional held more than one rank, and two URLs at the same
    rank cannot both be that slot;
  * naming a run so short it is coincidence;
  * losing a page across the split, or reporting `standalone` as a count of
    pages that rank rather than as the ceiling it is.

Each has its own test below.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import review  # noqa: E402
from growth import searchconsole as sc  # noqa: E402

HOME = "https://findacrib.com/"
B = "https://findacrib.com/building/manhattan/%d-main-st-100%04d/"


def rows(*spec):
    """(impressions, position) pairs -> page rows, one synthetic URL each."""
    return [{"url": B % (i, i), "impressions": imp, "position": pos,
             "clicks": 0} for i, (imp, pos) in enumerate(spec, start=1)]


def block(n, imp=3, start=2):
    """n rows sharing one impression count on consecutive ranks from `start`."""
    return rows(*[(imp, start + i) for i in range(n)])


class TheSignature(unittest.TestCase):
    def test_a_run_of_nine_is_one_group(self):
        c = sc.serving_coappearance(block(9))
        self.assertEqual(c["largest_group"], 9)
        self.assertEqual(len(c["groups"]), 1)
        g = c["groups"][0]
        self.assertEqual(g["impressions_each"], 3)
        self.assertEqual(g["impressions_total"], 27)
        self.assertEqual(g["positions"], [2, 10])
        self.assertEqual(len(g["urls"]), 9)

    def test_urls_come_back_in_rank_order(self):
        # The block is handed in shuffled, as Search Console hands it over:
        # _page_rows() sorts by impressions, which says nothing about rank.
        r = block(5)
        c = sc.serving_coappearance(list(reversed(r)))
        self.assertEqual([x["url"] for x in r], c["groups"][0]["urls"])

    def test_the_homepage_above_the_block_is_not_in_it(self):
        # The real shape: one row with its own much larger impression count at
        # a fractional position, plus the block underneath.
        r = [{"url": HOME, "impressions": 147, "position": 1.5,
              "clicks": 107}] + block(9)
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 9)
        self.assertEqual(c["standalone"], 1)
        self.assertNotIn(HOME, c["groups"][0]["urls"])

    def test_tiers_are_named(self):
        c = sc.serving_coappearance(block(4))
        self.assertEqual(c["groups"][0]["tiers"], ["building"])


class WhatCannotBeOneResultPage(unittest.TestCase):
    def test_a_fractional_position_is_never_grouped(self):
        # An average position of 4.5 means the URL held more than one rank in
        # the window, so it cannot have come from a single result page alone.
        # It also must not break the rest of the run silently into nothing:
        # here it sits outside the run entirely.
        r = block(4) + rows((3, 7.5))
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 4)
        self.assertEqual(c["standalone"], 1)

    def test_a_fractional_position_inside_the_span_splits_the_run(self):
        # ranks 2,3,4 then 5.5 then 6,7,8 at the same impression count: two
        # runs of three, neither long enough to name. The grouped count must
        # be 0 and not 6 — the fractional row is evidence AGAINST one page.
        r = block(3, start=2) + rows((3, 5.5)) + block(3, start=6)
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 0)
        self.assertEqual(c["groups"], [])

    def test_a_different_impression_count_is_a_different_event(self):
        # Four consecutive ranks, but the third row carries 9 impressions
        # where the others carry 3. One result page shown N times gives every
        # slot the SAME count, so this is at most two runs of two.
        r = rows((3, 2), (3, 3), (9, 4), (3, 5), (3, 6))
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 0)

    def test_a_gap_in_the_ranks_breaks_the_run(self):
        r = rows((3, 2), (3, 3), (3, 4), (3, 6), (3, 7), (3, 8))
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 0)
        c = sc.serving_coappearance(rows(*[(3, p) for p in (2, 3, 4, 5, 7, 8)]))
        self.assertEqual(c["coappearing"], 4)
        self.assertEqual(c["groups"][0]["positions"], [2, 5])

    def test_two_urls_at_one_rank_break_the_run_rather_than_extend_it(self):
        # Both cannot be the same slot of the same result page. Flushing is
        # the conservative direction: it can only make `coappearing` smaller,
        # which is the direction this metric is required to err in.
        r = rows((3, 2), (3, 3), (3, 4), (3, 4), (3, 5), (3, 6))
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 0)

    def test_zero_and_negative_impressions_are_not_rows(self):
        r = block(4) + rows((0, 6), (-1, 7))
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 4)

    def test_a_true_impression_count_is_a_corrupt_row_not_a_one(self):
        # bool is an int in Python, so True reads as 1 impression unless it is
        # refused. Placed where it would EXTEND a genuine run of four at one
        # impression each, so the guard is observable: with it the group is
        # four, without it five.
        r = block(4, imp=1, start=2) + [{"url": B % (99, 99),
                                         "impressions": True,
                                         "position": 6, "clicks": 0}]
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 4)
        self.assertEqual(c["groups"][0]["positions"], [2, 5])
        self.assertEqual(c["standalone"], 1)

    def test_a_true_position_is_not_rank_one(self):
        # Same trap on the other field, placed the same way: True would read
        # as rank 1 and extend a run that starts at 2.
        r = block(4) + [{"url": B % (98, 98), "impressions": 3,
                         "position": True, "clicks": 0}]
        c = sc.serving_coappearance(r)
        self.assertEqual(c["coappearing"], 4)
        self.assertEqual(c["groups"][0]["positions"], [2, 5])

    def test_rank_zero_or_below_is_not_a_rank(self):
        c = sc.serving_coappearance(rows(*[(3, p) for p in (0, 1, 2, 3, 4)]))
        # 1..4 is a run of four; 0 is not a position Search Console reports.
        self.assertEqual(c["coappearing"], 4)
        self.assertEqual(c["groups"][0]["positions"], [1, 4])


class TheThreshold(unittest.TestCase):
    def test_three_is_not_evidence_and_four_is_the_shortest_named(self):
        self.assertEqual(sc.COAPPEARANCE_MIN_GROUP, 4)
        self.assertEqual(sc.serving_coappearance(block(3))["coappearing"], 0)
        self.assertEqual(sc.serving_coappearance(block(4))["coappearing"], 4)

    def test_the_threshold_is_a_parameter_and_is_reported(self):
        # A caller that wants a stricter reading can have one, and the value
        # used travels with the result so a count can never be read against
        # the wrong threshold.
        c = sc.serving_coappearance(block(5), min_group=6)
        self.assertEqual(c["min_group"], 6)
        self.assertEqual(c["coappearing"], 0)


class TheSplitCannotLoseAPage(unittest.TestCase):
    def test_coappearing_plus_standalone_is_every_row(self):
        for r in (block(9), block(4) + rows((7, 1.5), (3, 20)),
                  rows((1, 1)), block(3)):
            c = sc.serving_coappearance(r)
            self.assertEqual(c["coappearing"] + c["standalone"], len(r))
            self.assertEqual(c["rows"], len(r))

    def test_no_rows_is_none_and_not_a_measured_zero(self):
        self.assertIsNone(sc.serving_coappearance([]))
        self.assertIsNone(sc.serving_coappearance(None))

    def test_rows_with_nothing_usable_are_a_measured_zero(self):
        # Rows exist and none of them can be grouped: that IS a reading, and
        # it must not come back as None, which the ledger stores as absent.
        c = sc.serving_coappearance(rows((3, 1.5), (4, 2.5)))
        self.assertEqual(c["coappearing"], 0)
        self.assertEqual(c["standalone"], 2)
        self.assertEqual(c["groups"], [])

    def test_two_blocks_are_both_reported_biggest_first(self):
        r = block(4, imp=3, start=2) + block(6, imp=5, start=10)
        c = sc.serving_coappearance(r)
        self.assertEqual([g["size"] for g in c["groups"]], [6, 4])
        self.assertEqual(c["coappearing"], 10)
        self.assertEqual(c["coappearing_impressions"], 4 * 3 + 6 * 5)


class AgainstTheCommittedRecord(unittest.TestCase):
    """The reading that produced the finding, pinned so it cannot silently move.

    These numbers come out of the committed gsc_pages.json and WILL move as
    the record grows. A failure here is a fixture moving, not a defect: read
    the new numbers and update it.
    """

    def test_the_shipping_day_reading(self):
        c = sc.saved_serving_coappearance()
        if c is None:
            self.skipTest("no committed serving page rows in this checkout")
        self.assertEqual(c["rows"], 10)
        self.assertEqual(c["coappearing"], 9)
        self.assertEqual(c["standalone"], 1)
        self.assertEqual(c["largest_group"], 9)
        g = c["groups"][0]
        self.assertEqual(g["impressions_each"], 3)
        self.assertEqual(g["positions"], [2, 10])
        self.assertEqual(g["tiers"], ["building"])
        # 27 of the window's 174 page impressions are that one block.
        self.assertEqual(c["coappearing_impressions"], 27)

    def test_the_block_is_exactly_what_the_other_two_checks_missed(self):
        # The whole reason this check exists: on the shipping day the brand
        # split and the census both had nothing to say about these nine. If a
        # later record gives either of them evidence, that is worth knowing —
        # it does not make this check wrong, it makes it no longer the only one.
        snap = sc.load_pages() or {}
        if not snap.get("pages"):
            self.skipTest("no committed serving page rows in this checkout")
        brand = sc.saved_serving_brand_split()
        self.assertIsNotNone(brand)
        self.assertEqual(brand["unattributed"], 9)
        self.assertEqual(brand["nonbranded"], 0)
        cx = sc.saved_serving_census_check()
        self.assertIsNotNone(cx)
        self.assertEqual(cx[sc.CENSUS_UNSAMPLED], 9)
        self.assertEqual(cx[sc.CENSUS_CONTRADICTED], 0)


class TheVerdictCanSayIt(unittest.TestCase):
    """The reading has to reach the verdict, not just the ledger.

    This loop's recurring defect is a measurement taken, stored, and read by
    nobody: 2026-11-04 found a census reading reported by one verdict branch of
    four, and 2026-11-01 found "0 non-branded" printed as a census when nine of
    ten pages were unattributed. So the tail on T010's audit reading is tested
    the same way _unattributed_pages is.
    """

    def rec(self, **kw):
        base = {"serving_pages": 10, "serving_census_contradicted": 0,
                "serving_census_indexed": 1, "serving_nonbranded": 0,
                "serving_unattributed": 9, "impressions": 120,
                "nonbranded_impressions": 0, "page_impressions": 174,
                "share_pct": 0.0, "tracked_ranking": 0,
                "window": "2026-10-29..2026-11-05"}
        base.update(kw)
        return base

    def test_the_block_is_named_in_the_stored_reading(self):
        d = review._gsc_reading(self.rec(
            serving_coappearing=9, serving_standalone=1,
            serving_coappearing_largest=9))["detail"]
        self.assertIn("shown TOGETHER on one result page", d)
        self.assertIn("block of 9", d)

    def test_it_says_the_standalone_count_is_a_ceiling(self):
        d = review._gsc_reading(self.rec(
            serving_coappearing=9, serving_standalone=1,
            serving_coappearing_largest=9))["detail"]
        self.assertIn("at most 1", d)
        self.assertIn("holding a ranking of its own", d)

    def test_a_measured_zero_says_nothing_extra(self):
        d = review._gsc_reading(self.rec(serving_coappearing=0,
                                         serving_standalone=10))["detail"]
        self.assertNotIn("TOGETHER", d)

    def test_a_missing_check_does_not_become_a_zero(self):
        # The droplet writes this record; a checkout from before the check
        # shipped carries none of these keys and must read as "not measured",
        # never as "no block found".
        d = review._gsc_reading(self.rec())["detail"]
        self.assertNotIn("TOGETHER", d)
        self.assertNotIn("at most", d)

    def test_the_rest_of_the_reading_survives(self):
        d = review._gsc_reading(self.rec(
            serving_coappearing=9, serving_standalone=1,
            serving_coappearing_largest=9))["detail"]
        for frag in ("10 pages served in search", "1 census-indexed",
                     "9 unattributed", "window 2026-10-29..2026-11-05"):
            self.assertIn(frag, d)


class TheReportSaysIt(unittest.TestCase):
    """emailkit renders the HTML and the plain text from ONE block list, so the
    two cannot drift — but the block still has to be there in both."""

    def _render(self, coap):
        from growth import report
        from growth import searchconsole as scm
        orig = scm.saved_serving_coappearance
        try:
            scm.saved_serving_coappearance = lambda *a, **k: coap
            return report.build()[1:]
        finally:
            scm.saved_serving_coappearance = orig

    def test_a_block_is_announced_once_in_each_part(self):
        html, text = self._render(sc.serving_coappearance(
            [{"url": HOME, "impressions": 147, "position": 1.5, "clicks": 107}]
            + block(9)))
        for part in (html, text):
            self.assertEqual(part.count("were shown together, not separately"), 1)
            # the arithmetic, not just the heading
            self.assertIn("ranks 2 to 10", part)
            self.assertIn("one query's result set", part)

    def test_no_block_means_no_claim(self):
        html, text = self._render(sc.serving_coappearance(block(3)))
        for part in (html, text):
            self.assertNotIn("were shown together", part)

    def test_a_missing_reading_is_not_rendered_as_zero(self):
        html, text = self._render(None)
        for part in (html, text):
            self.assertNotIn("were shown together", part)


if __name__ == "__main__":
    unittest.main(verbosity=2)
