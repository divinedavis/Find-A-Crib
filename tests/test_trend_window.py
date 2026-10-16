#!/usr/bin/env python3
"""A trailing window published as "14d" has to be fourteen days, not fourteen rows.

WHY THIS FILE EXISTS. growth/review.py's _trend took `vals[-WINDOW:]` — the last
fourteen READINGS — and every verdict string built on it then described the
result as "the trailing 14d median". Those are the same number only while the
engine writes a row every night. The moment a night is missed the slice
silently reaches further back in calendar time while still being published as
fourteen days.

That is not hypothetical on this site. growth/results.jsonl already carries two
holes in the site-wide series (2026-07-16 -> 07-19 and 2026-07-26 -> 07-28), and
#PAUSED-20261012 has stopped the engine outright: the series ends 2026-10-12,
and on whatever night it resumes the trailing "14d" window will span fourteen
readings across three weeks or more.

The damage is specific, and it is why this was worth fixing while the engine is
still off rather than after it comes back:

  * `falling` (recent < prior) and the site-wide "no measurable lift" flag are
    COMPARISONS between the two windows. A median over 14 days against a median
    over 21 is not a direction, and on resume both windows straddle the gap.
  * The retirement gate reads `recent < MIN_RECENT_MEDIAN`. A median of 0 over a
    window the engine spent mostly not running is a fact about the engine. A
    technique must not be retired for a pause it did not cause.

The same reasoning is already settled one module over: indexstatus
.crawl_rate_report refuses a crawl-count comparison when its denominator moved
and says so in words, and the journal's standing rule is never to quote those
counts without `crawl_rate.comparable`. This file asserts that rule for the
window that retires techniques.

The contract pinned here:

  * windows are cut by DATE from an anchor, are adjacent, and do not overlap;
  * a window states how many of its days hold a reading, and is `comparable`
    only when both windows clear TREND_MIN_COVERAGE_PCT;
  * no prior window reads as None, not as False — "no baseline" and "a baseline
    that disagrees" must not render the same;
  * no direction is asserted across a hole, on either the owned-prefix or the
    site-wide path;
  * nothing is retired on a window that is mostly missing days;
  * a complete series behaves exactly as it did before.
"""
from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from growth import review as R  # noqa: E402

TODAY = datetime.date.today()


def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def series(values_by_age):
    """[(date, value)] oldest first, from {days_ago: value}."""
    return [(days_ago(n), v) for n, v in sorted(values_by_age.items(), reverse=True)]


def full_series(n_days, value=5, skip=()):
    """A reading every day for n_days back from today, minus `skip` ages."""
    return series({n: value for n in range(n_days) if n not in skip})


class WindowIsCutByDate(unittest.TestCase):
    def test_in_window_is_inclusive_at_both_ends(self):
        pairs = full_series(40, value=1)
        vals = R._in_window(pairs, TODAY, 14)
        self.assertEqual(len(vals), 14, "14 calendar days back from today is 14 readings")

    def test_in_window_ignores_an_unparseable_date(self):
        pairs = [("not-a-date", 99)] + full_series(5, value=1)
        self.assertEqual(R._in_window(pairs, TODAY, 14), [1] * 5)

    def test_the_two_windows_are_adjacent_and_do_not_overlap(self):
        # Distinct values per day so membership is identifiable.
        pairs = [(days_ago(n), n) for n in range(40)][::-1]
        recent = set(R._in_window(pairs, TODAY, 14))
        prior = set(R._in_window(pairs, TODAY - datetime.timedelta(days=14), 14))
        self.assertEqual(recent, set(range(0, 14)))
        self.assertEqual(prior, set(range(14, 28)))
        self.assertFalse(recent & prior, "the windows must not share a day")

    def test_a_complete_series_is_comparable(self):
        r, p, c = R._trend(full_series(40, value=7))
        self.assertEqual((r, p), (7, 7))
        self.assertTrue(c["comparable"])
        self.assertEqual((c["recent_readings"], c["prior_readings"]), (14, 14))

    def test_no_prior_window_reads_as_none_not_false(self):
        r, p, c = R._trend(full_series(10, value=3))
        self.assertIsNone(c["comparable"], "no baseline is None, never False")
        self.assertIsNone(p)
        self.assertIn("not yet a direction", c["note"])

    def test_coverage_threshold_boundary(self):
        # 60% of 14 days is 8.4, so 9 readings clear it and 8 do not.
        self.assertTrue(R._covered([1] * 9, 14))
        self.assertFalse(R._covered([1] * 8, 14))


class ThePauseScenario(unittest.TestCase):
    """The live case: a hole, then the engine comes back."""

    def setUp(self):
        # Eight quiet nights (ages 1..8), a reading today, full history before.
        self.resumed = full_series(40, value=5, skip=tuple(range(1, 9)))

    def test_the_trailing_window_reports_its_real_depth(self):
        _r, _p, c = R._trend(self.resumed)
        self.assertEqual(c["recent_readings"], 6,
                         "ages 0 and 9..13 are the only readings inside 14 days")
        self.assertFalse(c["comparable"])

    def test_the_old_positional_slice_would_have_reached_past_the_window(self):
        # Documents the defect this file exists for: the positional slice still
        # finds fourteen readings here, and they span three weeks.
        positional = self.resumed[-14:]
        span = (datetime.date.fromisoformat(positional[-1][0])
                - datetime.date.fromisoformat(positional[0][0])).days + 1
        self.assertEqual(len(positional), 14)
        self.assertGreater(span, 14, "fourteen rows, more than fourteen days")
        self.assertLess(len(R._in_window(self.resumed, TODAY, 14)), len(positional))

    def test_the_note_blames_the_engine_and_not_the_traffic(self):
        _r, _p, c = R._trend(self.resumed)
        self.assertIn("NOT comparable", c["note"])
        self.assertIn("missing days, not days with no traffic", c["note"])

    def test_the_window_is_still_refused_while_the_hole_sits_in_the_baseline(self):
        # A fortnight on, the outage has left the trailing window and moved into
        # the one it is compared against. Still not a direction.
        moved = full_series(45, value=5, skip=tuple(range(15, 23)))
        _r, _p, c = R._trend(moved)
        self.assertEqual(c["recent_readings"], 14)
        self.assertFalse(c["comparable"], "a hollow BASELINE breaks the pair too")

    def test_the_window_recovers_once_the_hole_has_left_both_windows(self):
        healed = full_series(45, value=5, skip=tuple(range(29, 37)))
        _r, _p, c = R._trend(healed)
        self.assertTrue(c["comparable"])


def _vis(measured=True, impressions=0, pages=0):
    return {"measured": measured, "impressions": impressions, "pages": pages,
            "best_position": None, "brand_measured": False,
            "nonbranded_pages": 0, "nonbranded_impressions": 0,
            "unattributed_pages": 0}


class _EvaluateHarness(unittest.TestCase):
    """Drives review.evaluate with the ledger and Search Console stubbed out."""

    def setUp(self):
        self._saved = (R._owned, R._global,
                       R.searchconsole.recent_visibility, R.indexstatus.crawl_evidence)
        # Default: census has inspected nothing, so the crawl-reach guard stands
        # down and the retirement path below is reachable.
        R.indexstatus.crawl_evidence = lambda prefixes, cohort=None: {"read": 0, "fetched": 0}

    def tearDown(self):
        (R._owned, R._global,
         R.searchconsole.recent_visibility, R.indexstatus.crawl_evidence) = self._saved

    def owned(self, pairs, vis=None):
        R._owned = lambda t: pairs
        R.searchconsole.recent_visibility = lambda slug, since=None, window=7: vis or _vis()

    @staticmethod
    def tech(**kw):
        base = {"id": "T999", "slug": "probe", "name": "probe", "status": "active",
                "activated": "2026-01-01", "prefixes": ["/probe/"]}
        base.update(kw)
        return base


class NoDirectionAcrossAHole(_EvaluateHarness):
    def test_a_complete_falling_series_still_reads_as_falling(self):
        # 2/day recently, 9/day before: alive, above the floor, and declining.
        pairs = series({**{n: 2 for n in range(14)}, **{n: 9 for n in range(14, 28)}})
        self.owned(pairs)
        res = R.evaluate(self.tech())
        self.assertIn("the rate is declining", res["why"])
        self.assertIn("2.0/day against 9.0/day", res["why"])
        self.assertTrue(res["measured"]["trend_comparable"])

    def test_the_same_decline_is_not_asserted_across_a_hole(self):
        pairs = series({**{n: 2 for n in range(14) if n not in range(1, 9)},
                        **{n: 9 for n in range(14, 28)}})
        self.owned(pairs)
        res = R.evaluate(self.tech())
        self.assertFalse(res["measured"]["trend_comparable"])
        # Neither the dedicated declining verdict nor the rising/falling/flat
        # suffix may appear: both are claims about two windows.
        self.assertNotIn("declining", res["why"])
        self.assertNotIn("falling", res["why"])
        self.assertNotIn("rising", res["why"])
        self.assertNotIn("and flat", res["why"])

    def test_the_comparability_note_is_recorded_for_the_journal(self):
        pairs = series({n: 2 for n in range(28) if n not in range(1, 9)})
        self.owned(pairs)
        res = R.evaluate(self.tech())
        self.assertIn("trend_note", res["measured"])
        self.assertIn("of 14 days", res["measured"]["trend_note"])


class RetirementHeldOnAHollowWindow(_EvaluateHarness):
    """The safety half: a pause must not retire a technique."""

    def test_a_dead_technique_on_a_full_window_still_retires(self):
        pairs = series({n: 0 for n in range(28)})          # nothing, every night
        self.owned(pairs, _vis(measured=True, impressions=0))
        res = R.evaluate(self.tech())
        self.assertEqual(res["action"], "retire")
        self.assertFalse(res["works"])

    def test_the_same_zeros_do_not_retire_when_the_window_is_mostly_missing(self):
        pairs = series({n: 0 for n in range(28) if n not in range(1, 9)})
        self.owned(pairs, _vis(measured=True, impressions=0))
        res = R.evaluate(self.tech())
        self.assertEqual(res["action"], "keep")
        self.assertIn("Nothing to retire on", res["why"])
        self.assertIn("6 of its 14 days", res["why"])

    def test_the_hold_says_the_median_measures_the_gap(self):
        pairs = series({n: 0 for n in range(28) if n not in range(1, 9)})
        self.owned(pairs, _vis(measured=True, impressions=0))
        res = R.evaluate(self.tech())
        self.assertIn("measures the gap and not the technique", res["why"])

    def test_a_thin_window_is_flagged_in_the_below_the_floor_verdict(self):
        # Clears the 20-visitor floor on history, but the trailing window is
        # both below the alive threshold and mostly missing.
        pairs = series({**{n: 0 for n in range(14) if n not in range(1, 9)},
                        **{n: 9 for n in range(14, 28)}})
        self.owned(pairs, _vis(measured=True, impressions=0))
        res = R.evaluate(self.tech())
        self.assertIn("nights the engine missed", res["why"])


class SiteWideNeedsTwoRealWindows(_EvaluateHarness):
    def site(self, pairs):
        R._global = lambda metric, since=None: pairs

    @staticmethod
    def site_tech(**kw):
        base = {"id": "T998", "slug": "sitewide", "name": "sitewide", "status": "active",
                "activated": None, "metric": "organic_visitors"}
        base.update(kw)
        return base

    def test_a_real_lift_over_two_full_windows_still_reads_as_works(self):
        # Activated 25d ago so it is clear of the 21d grace period; the baseline
        # window is the 14 days ending the day before that.
        act = days_ago(25)
        pairs = series({**{n: 10 for n in range(25)}, **{n: 2 for n in range(25, 50)}})
        self.site(pairs)
        res = R.evaluate(self.site_tech(activated=act))
        self.assertTrue(res["works"])
        self.assertTrue(res["measured"]["trend_comparable"])

    def test_the_same_lift_is_refused_when_the_trailing_window_is_hollow(self):
        act = days_ago(25)
        pairs = series({**{n: 10 for n in range(25) if n not in range(1, 9)},
                        **{n: 2 for n in range(25, 50)}})
        self.site(pairs)
        res = R.evaluate(self.site_tech(activated=act))
        self.assertEqual(res["action"], "flag")
        self.assertIsNone(res["works"], "works must never be True on an unreadable window")
        self.assertIn("not the same length of time", res["why"])

    def test_no_baseline_still_takes_the_existing_no_baseline_path(self):
        # Activated before every reading, so there is no pre-activation window.
        pairs = series({n: 10 for n in range(20)})
        self.site(pairs)
        res = R.evaluate(self.site_tech(activated=days_ago(30)))
        self.assertIn("baseline", res["why"])
        self.assertNotIn("not the same length of time", res["why"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
