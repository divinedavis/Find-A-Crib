"""The ROSE clause must carry the size of each move, biggest mover first.

Why these exist (2026-11-01, T072's scheduled revisit). t_page_uniqueness
records dup_pct_<section> nightly and flags owned sections whose share rose by
a point or more. Until tonight the flag rendered as a bare alphabetical list of
section names — "ROSE since the last reading: /neighborhood/, /section8/,
/zip/" — while the magnitude of each move existed only in the worst-first
clause earlier in the same line, which prints at most six owned sections. A
riser ranked seventh or lower therefore had its move recorded in no readable
form at all, and even inside the top six a reader had to match a name across
two clauses to learn whether a section drifted a point or jumped five.

That cost real work twice: the 2026-10-30 and 10-31 reviews both used this
signal and both recomputed the deltas from results.jsonl in prose. The 10-31
finding — one riser a surprise, two the priced cost of a change shipped the day
before — is exactly what a bare list cannot carry.

These tests drive the two helpers directly rather than running the technique,
because t_page_uniqueness reads a deployed docroot and returns "duplicate text
NOT MEASURED" on a bare checkout. The dry-run build the cloud review uses to
verify a change cannot reach this code at all, so a unit test is the only thing
standing under it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth.techniques import _dup_rising, _dup_risen_clause  # noqa: E402

# The real readings of 2026-10-31, from growth/results.jsonl: /section8/ moved
# +4.8pp, /zip/ +2.9pp, /neighborhood/ +1.0pp, /building/ not at all.
READINGS = {"/neighborhood/": (23.7, 1004, 24, 198),
            "/section8/": (26.6, 1126, 6, 6),
            "/zip/": (23.3, 1058, 24, 165),
            "/building/": (37.7, 612, 24, 47165)}
PRIOR = {"/neighborhood/": 22.7, "/section8/": 21.8,
         "/zip/": 20.4, "/building/": 37.7}
MINE = list(READINGS)


class TheOrderIsByMagnitude(unittest.TestCase):

    def test_the_biggest_mover_comes_first(self):
        # Alphabetically /section8/ sits in the middle of the three. It is the
        # largest move and the reason the 10-31 entry had a finding at all.
        self.assertEqual(_dup_rising(MINE, READINGS, PRIOR),
                         ["/section8/", "/zip/", "/neighborhood/"])

    def test_a_section_that_did_not_move_is_not_a_riser(self):
        self.assertNotIn("/building/", _dup_rising(MINE, READINGS, PRIOR))

    def test_a_fall_is_not_a_riser(self):
        readings = dict(READINGS, **{"/zip/": (10.0, 1058, 24, 165)})
        self.assertNotIn("/zip/", _dup_rising(MINE, readings, PRIOR))

    def test_a_sub_point_drift_is_not_a_riser(self):
        # The threshold is a full point, unchanged by tonight's edit: a 0.9pp
        # wobble on a 24-page sample is noise, not news.
        readings = dict(READINGS, **{"/building/": (38.6, 612, 24, 47165)})
        self.assertNotIn("/building/", _dup_rising(MINE, readings, PRIOR))
        readings = dict(READINGS, **{"/building/": (38.7, 612, 24, 47165)})
        self.assertIn("/building/", _dup_rising(MINE, readings, PRIOR))

    def test_a_section_with_no_prior_reading_cannot_rise(self):
        # First night a section is measured there is nothing to compare to, and
        # a missing baseline must not read as a rise from zero.
        self.assertEqual(_dup_rising(["/new/"], {"/new/": (99.0, 500, 24, 10)}, {}), [])

    def test_only_owned_sections_are_considered(self):
        # `mine` is the owned list; /brief/ is retired and nothing rebuilds it,
        # so it must never become a finding however much it moves.
        readings = dict(READINGS, **{"/brief/": (90.0, 182, 17, 17)})
        prior = dict(PRIOR, **{"/brief/": 49.5})
        self.assertNotIn("/brief/", _dup_rising(MINE, readings, prior))


class TheClauseCarriesTheMove(unittest.TestCase):

    def setUp(self):
        self.rising = _dup_rising(MINE, READINGS, PRIOR)
        self.clause = _dup_risen_clause(self.rising, READINGS, PRIOR)

    def test_every_riser_shows_from_to_and_delta(self):
        self.assertIn("/section8/ 22% → 27% (+4.8pp)", self.clause)
        self.assertIn("/zip/ 20% → 23% (+2.9pp)", self.clause)
        self.assertIn("/neighborhood/ 23% → 24% (+1.0pp)", self.clause)

    def test_the_clause_is_not_just_names(self):
        # The defect this replaces, pinned so it cannot come back.
        self.assertNotEqual(self.clause, ", ".join(self.rising))
        self.assertIn("pp", self.clause)

    def test_the_delta_keeps_a_decimal(self):
        # +4.8pp and +1.0pp are different findings; rounding both to "+5pp" and
        # "+1pp" would be fine, rounding to integers that hide a 0.4 would not.
        # The point is that the tenth is retained.
        self.assertIn("+1.0pp", self.clause)

    def test_the_order_of_the_clause_follows_the_list(self):
        self.assertLess(self.clause.index("/section8/"), self.clause.index("/zip/"))
        self.assertLess(self.clause.index("/zip/"), self.clause.index("/neighborhood/"))

    def test_one_riser_renders_without_a_separator(self):
        c = _dup_risen_clause(["/zip/"], READINGS, PRIOR)
        self.assertEqual(c, "/zip/ 20% → 23% (+2.9pp)")

    def test_no_risers_is_the_empty_string(self):
        # dup_sections_rising was 0 on 2026-11-01 because nothing was rebuilt.
        # The caller only appends this clause when the list is non-empty, but
        # the helper must not invent text either way.
        self.assertEqual(_dup_risen_clause([], READINGS, PRIOR), "")


if __name__ == "__main__":
    unittest.main()
