#!/usr/bin/env python3
"""serving_persistence(): `days_seen` counts readings of a rolling window, so
it is not a residence time, and only one direction of the inference survives.

Shipped 2026-11-06. collect() asks Search Console for a TRAILING window —
d(days + 2) .. d(2), which at the default days=7 is 8 dates inclusive — and
_churn() adds 1 to a URL's `days_seen` once per distinct date the measurement
ran on which that URL came back. A URL that earned one impression on a single
day therefore comes back in every window still containing that day, up to W
consecutive nights, and scores days_seen up to W while Google showed it once.

The stored record on the shipping date proves this was the normal case and not
a corner: 194 of the 296 URLs in gsc_pages.json sat at days_seen 7 or 8 against
a window of 8, a spike at the window boundary. serving_tiers()' `median_days`
was 7 for the /building/ tier, the daily report published it as "the median run
of distinct days a URL kept its place", and a pre-registered prediction written
2026-11-02 priced Google's rotation on it.

So the three ways this can go wrong are all ways of handing back a residence
time the data cannot support:

  * counting a URL as having held when its day count is inside the window and
    therefore explainable by overlap alone;
  * reading the threshold off the wrong window width, which silently turns
    window drag back into a duration;
  * reporting the cannot-tell bucket as a failure count — "shown once and
    dropped" — which is the inference this split exists to refuse.

Each has its own test below, plus the arithmetic guarantee the whole split
rests on: a measurement GAP can only reduce how many readings one impression-
day produces, so days_seen > W cannot be manufactured by a paused engine.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import searchconsole as sc  # noqa: E402

W = 8  # the real window: 2026-10-28..2026-11-04
WINDOW = "2026-10-28..2026-11-04"


def hist(**kw):
    """{url: [first_seen, last_seen, days_seen]} — only days_seen matters here."""
    return {u: ["2026-09-01", "2026-11-06", d] for u, d in kw.items()}


class WindowWidth(unittest.TestCase):
    def test_span_is_inclusive(self):
        self.assertEqual(sc.window_span_days("2026-10-28..2026-11-04"), 8)
        self.assertEqual(sc.window_span_days("2026-11-04..2026-11-04"), 1)

    def test_documented_default_matches_collect(self):
        # collect(days=7) asks d(days + 2) .. d(2): days + 1 dates inclusive.
        # If the default ever drifts from the constant, the threshold silently
        # moves and every count below it changes meaning.
        self.assertEqual(sc.SC_WINDOW_DAYS, 8)

    def test_unparseable_window_is_none_not_a_guess(self):
        # A threshold quietly defaulted to the wrong width would reintroduce
        # the whole defect without saying so, so this must refuse rather than
        # guess. The caller falls back explicitly and reports window_source.
        for bad in (None, "", "garbage", "2026-10-28", "x..y",
                    "2026-11-04..2026-10-28"):   # reversed -> non-positive
            self.assertIsNone(sc.window_span_days(bad), bad)

    def test_falls_back_to_the_default_and_says_so(self):
        p = sc.serving_persistence(history=hist(a=99), window=None)
        self.assertEqual(p["window_days"], sc.SC_WINDOW_DAYS)
        self.assertEqual(p["window_source"], "default")
        p = sc.serving_persistence(history=hist(a=99), window=WINDOW)
        self.assertEqual(p["window_source"], "measured")
        p = sc.serving_persistence(history=hist(a=99), window_days=3)
        self.assertEqual(p["window_source"], "caller")
        self.assertEqual(p["window_days"], 3)


class TheThreshold(unittest.TestCase):
    def test_at_and_below_the_window_proves_nothing(self):
        # The whole gap, not just its ends: every one of these is explainable
        # by a single impression-day dragged through the window.
        for d in range(1, W + 1):
            p = sc.serving_persistence(history=hist(a=d), window=WINDOW)
            self.assertEqual(p["proven_multi_day"], 0, d)
            self.assertEqual(p["single_day_possible"], 1, d)

    def test_above_the_window_proves_a_second_day(self):
        for d in range(W + 1, W + 20):
            p = sc.serving_persistence(history=hist(a=d), window=WINDOW)
            self.assertEqual(p["proven_multi_day"], 1, d)
            self.assertEqual(p["single_day_possible"], 0, d)

    def test_the_boundary_is_strictly_greater(self):
        # days_seen == W is the single-day case at its maximum, NOT the first
        # proven one. Off by one here is the defect, re-shipped.
        self.assertEqual(
            sc.serving_persistence(history=hist(a=W), window=WINDOW)["proven_multi_day"], 0)
        self.assertEqual(
            sc.serving_persistence(history=hist(a=W + 1), window=WINDOW)["proven_multi_day"], 1)

    def test_threshold_moves_with_the_window_not_with_the_constant(self):
        # Same history, two window widths: a 14-day window makes 10 readings
        # explainable that an 8-day window does not. Reading the width off the
        # stored window is the point of window_span_days().
        h = hist(a=10)
        self.assertEqual(sc.serving_persistence(history=h, window=WINDOW)["proven_multi_day"], 1)
        self.assertEqual(sc.serving_persistence(
            history=h, window="2026-10-22..2026-11-04")["proven_multi_day"], 0)


class TheBuckets(unittest.TestCase):
    def test_the_two_buckets_partition_what_was_counted(self):
        h = hist(**{f"u{i}": i for i in range(1, 30)})
        p = sc.serving_persistence(history=h, window=WINDOW)
        self.assertEqual(p["proven_multi_day"] + p["single_day_possible"], p["counted"])
        self.assertEqual(p["counted"], 29)

    def test_unreadable_records_are_excluded_from_both(self):
        # A URL whose day count cannot be read is not evidence either way, so
        # it must not land in a bucket — least of all in the cannot-tell one,
        # which would inflate the count this split is read for.
        h = {"ok": ["2026-09-01", "2026-11-06", 20],
             "short": ["2026-09-01", "2026-11-06"],
             "nonint": ["2026-09-01", "2026-11-06", "7"],
             "none": None,
             "zero": ["2026-09-01", "2026-11-06", 0],
             "negative": ["2026-09-01", "2026-11-06", -3]}
        p = sc.serving_persistence(history=h, window=WINDOW)
        self.assertEqual(p["counted"], 1)
        self.assertEqual(p["proven_multi_day"], 1)
        self.assertEqual(p["single_day_possible"], 0)

    def test_no_history_returns_none_not_a_zero(self):
        # The ledger reads a missing metric as "not measured" and a zero as
        # "measured, and it was zero". An empty record is the former.
        self.assertIsNone(sc.serving_persistence(history={}, window=WINDOW))
        self.assertIsNone(sc.serving_persistence(
            history={"a": None}, window=WINDOW))   # nothing countable

    def test_per_tier_split_sums_to_the_site_wide_split(self):
        h = {"https://findacrib.com/": ["2026-07-30", "2026-11-06", 81],
             "https://findacrib.com/building/queens/a-1/": ["2026-11-01", "2026-11-06", 6],
             "https://findacrib.com/building/queens/b-2/": ["2026-09-01", "2026-11-06", 39],
             "https://findacrib.com/zip/11356/": ["2026-10-01", "2026-11-06", 7],
             "https://findacrib.com/guide/x/": ["2026-10-01", "2026-11-06", 14]}
        p = sc.serving_persistence(history=h, window=WINDOW)
        t = p["by_tier"]
        self.assertEqual(sum(v["proven_multi_day"] for v in t.values()),
                         p["proven_multi_day"])
        self.assertEqual(sum(v["single_day_possible"] for v in t.values()),
                         p["single_day_possible"])
        self.assertEqual(t["home"]["proven_multi_day"], 1)
        self.assertEqual(t["building"]["proven_multi_day"], 1)
        self.assertEqual(t["building"]["single_day_possible"], 1)
        self.assertEqual(t["nyc_hub"]["single_day_possible"], 1)
        self.assertEqual(t["guide"]["proven_multi_day"], 1)

    def test_every_tier_is_present_even_at_zero(self):
        # "Google has never once served this family" is the finding, not a gap
        # — the same rule serving_tiers() follows.
        p = sc.serving_persistence(history=hist(a=20), window=WINDOW)
        for name, _ in sc.SERVING_TIERS:
            self.assertIn(name, p["by_tier"], name)
        self.assertIn(sc.TIER_OTHER, p["by_tier"])

    def test_max_days_is_per_tier_and_survives_the_split(self):
        h = {"https://findacrib.com/building/q/a-1/": ["2026-09-01", "2026-11-06", 39],
             "https://findacrib.com/building/q/b-2/": ["2026-11-01", "2026-11-06", 6]}
        p = sc.serving_persistence(history=h, window=WINDOW)
        self.assertEqual(p["by_tier"]["building"]["max_days"], 39)
        self.assertIsNone(p["by_tier"]["guide"]["max_days"])


class TheClaimItRefuses(unittest.TestCase):
    def test_single_day_possible_is_not_a_dropped_count(self):
        # The regression this guards: naming the cannot-tell bucket as a
        # failure. There is no key anywhere in the payload that asserts a URL
        # was shown once and dropped, because the record cannot support it.
        p = sc.serving_persistence(history=hist(a=3, b=20), window=WINDOW)
        flat = " ".join(p.keys()) + " " + " ".join(
            k for v in p["by_tier"].values() for k in v)
        for banned in ("dropped", "lost", "once", "held", "residence"):
            self.assertNotIn(banned, flat, banned)

    def test_proven_is_a_floor_so_pct_never_implies_the_remainder_failed(self):
        p = sc.serving_persistence(history=hist(**{f"u{i}": 1 for i in range(9)},
                                                **{"held": 99}), window=WINDOW)
        self.assertEqual(p["proven_multi_day"], 1)
        self.assertEqual(p["counted"], 10)
        self.assertEqual(p["proven_pct"], 10.0)
        # and the two counts are both published, so a reader cannot take
        # proven_pct for "90% were dropped" without the denominator contradicting.
        self.assertEqual(p["single_day_possible"], 9)

    def test_a_measurement_gap_cannot_manufacture_a_proven_day(self):
        # The guarantee the threshold rests on. A skipped night only ever
        # REDUCES how many readings one impression-day can produce, so the
        # engine's pauses (2026-10-13 onward) cannot push a single-day URL
        # above the window width. Stated as the arithmetic it is: the bucket
        # depends only on days_seen vs W, never on the span of dates, so no
        # arrangement of first/last_seen can move a URL across the boundary.
        for first, last in (("2026-01-01", "2026-11-06"),
                            ("2026-11-06", "2026-11-06"),
                            ("2026-07-01", "2026-07-02")):
            p = sc.serving_persistence(
                history={"u": [first, last, W]}, window=WINDOW)
            self.assertEqual(p["proven_multi_day"], 0, (first, last))
            p = sc.serving_persistence(
                history={"u": [first, last, W + 1]}, window=WINDOW)
            self.assertEqual(p["proven_multi_day"], 1, (first, last))


class AgainstTheCommittedRecord(unittest.TestCase):
    """The reading that produced the finding, pinned so it cannot silently move."""

    def test_the_shipping_day_reading(self):
        p = sc.serving_persistence()
        if p is None:
            self.skipTest("no committed serving history in this checkout")
        self.assertEqual(p["window_days"], 8)
        self.assertEqual(p["window_source"], "measured")
        # 296 URLs ever served; 41 of them provably on more than one day.
        self.assertEqual(p["counted"], 296)
        self.assertEqual(p["proven_multi_day"], 41)
        self.assertEqual(p["single_day_possible"], 255)
        # The /building/ tier is the one the 2026-11-02 prediction was priced
        # on: serving_tiers() reported median_days 7 for it against a window
        # of 8, and only 30 of its 279 URLs clear the threshold.
        b = p["by_tier"]["building"]
        self.assertEqual(b["proven_multi_day"], 30)
        self.assertEqual(b["single_day_possible"], 249)

    def test_the_median_it_replaced_sits_inside_the_window(self):
        # Why the old column could not mean what it said: the median for the
        # largest tier is at or under the window width, i.e. entirely
        # explainable by overlap. If this ever rises above the window, the
        # median becomes informative again and this test should be revisited
        # rather than deleted.
        snap = sc.load_pages() or {}
        if not snap.get("history"):
            self.skipTest("no committed serving history in this checkout")
        tiers = sc.serving_tiers(history=snap["history"])
        med = tiers["building"]["median_days"]
        self.assertIsNotNone(med)
        self.assertLessEqual(med, sc.window_span_days(snap.get("window")) or 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
