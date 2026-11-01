"""T010's stored verdict must not present "unknown" as "zero".

Why these exist (2026-11-01). Search Console answers two different questions
with two different dimensions, and growth/searchconsole.py is careful about it
in both directions: collect() records gsc_impressions and gsc_page_impressions
side by side and says "Two metrics, two meanings"; branded_split() warns that
"Both halves are QUERY-dimension numbers ... the non-branded half is a floor,
not a census"; and serving_brand_split() returns THREE page counts, the third
being `unattributed` — "NOT branded, NOT non-branded — unknown. On a corpus of
single-address pages almost every query is anonymized away, so on a big
serving day this is the bulk of it."

review._gsc_reading, which writes the T010 verdict stored in techniques.json,
printed by `status` and quoted by every later review, then threw both caveats
away. It read:

    10 pages served in search (0 census-contradicted, 1 census-indexed,
    0 non-branded); 0 non-branded of 202 page impressions

On the night that was written, 9 of those 10 pages were unattributed — the
committed gsc_pages.json has `[]` query rows for every one of them — and 57 of
the 202 page impressions had no query attribution, because the non-branded 0
was computed over the 145 query-dimension impressions and divided into the
page-dimension total. Both numbers were right; the sentence said more than
either carried, in the direction of "we checked and found nothing".

It mattered that night specifically: gsc_serving_entered went 0 -> 9 for the
first time since the engine resumed, and all nine newcomers landed inside
exactly the blind spot this sentence was hiding. The daily report had been
wording the same fact correctly for weeks ("Search Console gave no query for N
of them, so that first number is a floor"), so this was two renderers
disagreeing about one fact, with the honest copy in the email and the
misleading copy in the durable record.

Every test here drives the reading off a CONSTRUCTED record. The one live-corpus
test skips rather than fails when the field it needs is absent, because the
lesson of tests/test_unfetched_verdict.py on this same date is that a test whose
fixture is tonight's numbers reports a failure the next time the numbers move.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import ledger, review  # noqa: E402

FLOOR_PAGES = "so the non-branded count is a floor and not a census"
FLOOR_IMPS = "carry no query attribution at all, so that 0 is a floor"
# The sentence this change removes: a query-dimension numerator over a
# page-dimension denominator.
MIXED_DIMENSIONS = "non-branded of 202 page impressions"


def _rec(**kw):
    """A searchconsole last_run record with the night of 2026-11-01's shape."""
    base = {"serving_pages": 10, "serving_census_contradicted": 0,
            "serving_census_indexed": 1, "serving_nonbranded": 0,
            "serving_unattributed": 9, "impressions": 145,
            "page_impressions": 202, "share_pct": 0.0, "tracked_ranking": 0,
            "window": "2026-10-23..2026-10-30"}
    base.update(kw)
    return base


def _detail(**kw):
    return review._gsc_reading(_rec(**kw))["detail"]


class TheUnknownPagesAreNamed(unittest.TestCase):
    """0 non-branded out of 10 must not read as "all ten were checked"."""

    def test_the_unattributed_count_is_in_the_sentence(self):
        d = _detail()
        self.assertIn("9 unattributed", d)

    def test_it_says_why_that_makes_the_zero_a_floor(self):
        # The count alone is not enough: a reader has to be told that an
        # unattributed page is unknown rather than counted against us.
        self.assertIn(FLOOR_PAGES, _detail())

    def test_a_measured_zero_says_nothing_extra(self):
        # Every serving page attributable is a real statement and needs no
        # caveat. The sentence must not grow a "0 unattributed" clause.
        d = _detail(serving_unattributed=0)
        self.assertNotIn("unattributed", d)
        self.assertIn("0 non-branded", d)

    def test_a_missing_split_does_not_become_a_zero(self):
        # zero-because-absent and a measured zero are different facts — the
        # rule serving_brand_split() itself applies when it returns None
        # rather than three zeros.
        d = _detail(serving_unattributed=None)
        self.assertNotIn("unattributed", d)

    def test_the_whole_serving_set_unattributed_still_reads_honestly(self):
        d = _detail(serving_pages=9, serving_nonbranded=0, serving_unattributed=9)
        self.assertIn("9 unattributed", d)
        self.assertIn(FLOOR_PAGES, d)


class TheImpressionNumeratorKeepsItsOwnDenominator(unittest.TestCase):
    """nonbranded_impressions is a query-dimension number and must be divided
    into the query-dimension total it was computed from."""

    def test_the_denominator_is_the_query_dimension(self):
        d = _detail(nonbranded_impressions=0)
        self.assertIn("0 non-branded of 145 query-attributed impressions", d)

    def test_the_old_mixed_dimension_sentence_is_gone(self):
        self.assertNotIn(MIXED_DIMENSIONS, _detail(nonbranded_impressions=0))

    def test_the_withheld_remainder_is_named_with_its_share(self):
        d = _detail(nonbranded_impressions=0)
        self.assertIn("57 of 202 page impressions", d)
        self.assertIn("28.2%", d)
        self.assertIn(FLOOR_IMPS, d)

    def test_two_agreeing_dimensions_add_no_caveat(self):
        # Nothing withheld is a real statement; do not caveat it.
        d = _detail(impressions=202, page_impressions=202)
        self.assertIn("of 202 query-attributed impressions", d)
        self.assertNotIn("carry no query attribution", d)

    def test_a_missing_dimension_adds_no_caveat_and_flags_itself(self):
        d = _detail(page_impressions=None)
        self.assertNotIn("carry no query attribution", d)
        self.assertIn("of 145 query-attributed impressions", d)
        d2 = _detail(impressions=None)
        self.assertNotIn("carry no query attribution", d2)
        self.assertIn("of ? query-attributed impressions", d2)

    def test_a_negative_gap_is_said_and_not_clamped(self):
        # The page dimension should always be the larger. If it is not, one of
        # the two collections is wrong, and that is the anomaly most worth
        # surfacing — a max(0, ...) would hide it.
        d = _detail(impressions=202, page_impressions=145)
        self.assertIn("ANOMALY", d)
        self.assertIn("exceeds the page dimension by 57", d)


class TheRestOfTheReadingIsUntouched(unittest.TestCase):
    """This change adds caveats. It must not drop or alter anything that was
    already being said, and must not synthesize an `ok`."""

    def test_the_census_columns_still_travel_with_the_serving_count(self):
        d = _detail()
        self.assertIn("10 pages served in search", d)
        self.assertIn("0 census-contradicted", d)
        self.assertIn("1 census-indexed", d)

    def test_share_ranking_and_window_survive(self):
        d = _detail()
        self.assertIn("share 0%", d)
        self.assertIn("0 tracked queries ranking", d)
        self.assertIn("window 2026-10-23..2026-10-30", d)

    def test_ok_is_passed_through_and_never_invented(self):
        self.assertIsNone(review._gsc_reading(_rec())["ok"])
        self.assertIs(review._gsc_reading(_rec(ok=True))["ok"], True)
        self.assertIs(review._gsc_reading(_rec(ok=False))["ok"], False)

    def test_no_record_is_still_no_reading(self):
        self.assertIsNone(review._gsc_reading(None))
        self.assertIsNone(review._gsc_reading({}))


class TheLiveRecord(unittest.TestCase):
    """What the committed last_run.json actually produces tonight."""

    def setUp(self):
        self.rec = (ledger.read_last_run() or {}).get("searchconsole")
        if not self.rec:
            self.skipTest("no searchconsole record in last_run.json")

    def test_the_live_reading_never_mixes_the_two_dimensions(self):
        d = review._gsc_reading(self.rec)["detail"]
        self.assertIn("query-attributed impressions", d)
        # Whatever the numbers are, the page-dimension total may only appear
        # inside the withheld caveat, never as the non-branded denominator.
        self.assertNotIn("non-branded of "
                         f"{int(self.rec['page_impressions'])} page impressions", d)

    def test_any_unattributed_pages_are_disclosed(self):
        n = self.rec.get("serving_unattributed")
        if not n:
            self.skipTest("no unattributed serving pages in tonight's record")
        d = review._gsc_reading(self.rec)["detail"]
        self.assertIn(f"{int(n)} unattributed", d)
        self.assertIn(FLOOR_PAGES, d)


if __name__ == "__main__":
    unittest.main()
