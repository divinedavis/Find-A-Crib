"""The per-building comparison block: the tautology it must refuse, and the
open/lifetime split it must keep straight.

Why these exist (2026-10-20). T046's whole hypothesis is that the building tier
was "a template with six variable tokens ... and every other word is identical
47,165 times over", and that a computed comparison block undoes that. Measured
against the real corpus on 2026-10-20, two of its five sentences were doing the
opposite in homogeneous neighborhoods: in Bushwick (West) — 1,197 tracked
buildings, median year 1931, median size 6 — "Its 1931 construction date sits
close to the 1931 median" was emitted on 975 of them and "With about 6
apartments it sits near the middle ... where the median building has 6" on 791,
each one word-for-word identical to the last. A comparison whose two numbers are
the SAME number is a number held up against itself: it tells the reader nothing
and it spends one of FACTS_MAX_SENTENCES slots doing it.

So the exact tie now emits nothing, and the freed slot goes to facts that
actually differ between neighbours — how much of the class-C record is still
open, and how many violations HPD issued in the last twelve months. Three of
those changes are the kind that read fine and mean something false:

  * saying "none of them are still open" about a single violation, which reads
    as a claim about a set when it is a claim about one row;
  * letting the open class-C count exceed the class-C record it is drawn from,
    which puts arithmetic on the page that cannot be true;
  * referring back to the lifetime sentence with "of them" when that sentence is
    independently suppressed and either can be cut by the sentence cap, so the
    pronoun sooner or later points at nothing.

A docstring cannot fail a build, so each of those is a test. The suppression is
pinned in BOTH directions on purpose: withholding a true comparison to flatter a
duplication metric would be the same defect as publishing a tautology to hit a
sentence count, so a near miss of one or two years must still earn its sentence.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_seo as B  # noqa: E402

GRADE = "class C — HPD's immediately hazardous grade"


def mk(u=None, yr=None, total=0, c=0, oc=0, open_v=0, last_12mo=0,
       ctotal=0, clast=0):
    """One building row in buildings.min.json's shape."""
    b = {"bbl": "x", "a": "1 MAIN ST", "b": "Bk", "nb": "Testville"}
    if u is not None:
        b["u"] = u
    if yr is not None:
        b["yr"] = yr
    b["h"] = {"violations": {"open": open_v, "total": total, "c": c, "oc": oc,
                             "last_12mo": last_12mo},
              "complaints": {"total": ctotal, "last_12mo": clast}}
    return b


def norms(n=40, unit_med=6, year_med=1931, rate_med=0.0, clean=10, units=None):
    """A neighborhood base big enough to clear FACTS_MIN_BASE."""
    return {"n": n, "units": units if units is not None else sorted([unit_med] * n),
            "unit_med": unit_med, "year_med": year_med,
            "rate_med": rate_med, "rate_n": n, "clean": clean,
            "rec_n": n, "clean_rec": clean}


def facts(b, nm=None):
    return B.building_facts(b, "Testville", nm or norms())


def joined(b, nm=None):
    return " ".join(facts(b, nm))


class TheDegenerateComparisonSaysNothing(unittest.TestCase):
    """The measured defect: a comparison between a number and itself."""

    def test_year_equal_to_the_median_emits_no_age_sentence(self):
        got = joined(mk(yr=1931), norms(year_med=1931))
        self.assertNotIn("construction date", got)
        self.assertNotIn("1931 median", got)

    def test_size_equal_to_the_median_emits_no_size_sentence(self):
        # units == unit_med, so "the median building has 6" would restate the
        # page's own 6 apartments.
        got = joined(mk(u=6), norms(unit_med=6))
        self.assertNotIn("sits near the middle", got)

    def test_a_near_miss_still_earns_its_age_sentence(self):
        # The guard is the exact tie, not a band. Suppressing 1931 +/- a few
        # years would start withholding true comparisons to flatter a metric.
        for yr in (1929, 1930, 1932, 1933):
            got = joined(mk(yr=yr), norms(year_med=1931))
            self.assertIn(f"Its {yr} construction date sits close to the 1931 median", got)

    def test_a_near_miss_still_earns_its_size_sentence(self):
        got = joined(mk(u=7), norms(unit_med=6, units=sorted([6] * 20 + [7] * 20)))
        self.assertIn("sits near the middle", got)
        self.assertIn("median building has 6", got)

    def test_the_far_comparisons_are_untouched(self):
        self.assertIn("It went up in 1900, 31 years before the 1931 median",
                      joined(mk(yr=1900), norms(year_med=1931)))
        self.assertIn("It went up in 1970, 39 years after the 1931 median",
                      joined(mk(yr=1970), norms(year_med=1931)))

    def test_suppressing_the_size_sentence_moves_the_place_name_onward(self):
        # _name_place spells the neighborhood out on its FIRST appearance. If
        # the size sentence is gone, the next sentence has to carry the name or
        # the block opens with a bare "the neighborhood".
        got = joined(mk(u=6, yr=1900), norms(unit_med=6, year_med=1931))
        self.assertIn("tracked in Testville", got)
        self.assertNotIn("tracked in the neighborhood.", got.split(".")[0] + ".")


class TheOpenAndLifetimeCountsStayStraight(unittest.TestCase):
    """`oc` is the still-open class-C rows; `c` is the whole lifetime record."""

    def test_one_class_c_violation_still_open_is_singular(self):
        got = joined(mk(u=6, total=16, c=1, oc=1, open_v=9))
        self.assertIn(f"1 is {GRADE}, and it is still open.", got)

    def test_one_class_c_violation_closed_is_singular(self):
        got = joined(mk(u=6, total=16, c=1, oc=0, open_v=9))
        self.assertIn(f"1 is {GRADE}, and it is no longer open.", got)
        # "none of them" about a single row reads as a claim about a set.
        self.assertNotIn("none of them", got)

    def test_every_class_c_violation_still_open(self):
        got = joined(mk(u=6, total=33, c=5, oc=5, open_v=33))
        self.assertIn(f"5 are {GRADE}, and all of them are still open.", got)

    def test_no_class_c_violation_still_open(self):
        got = joined(mk(u=6, total=12, c=4, oc=0, open_v=0))
        self.assertIn(f"4 are {GRADE}, and none of them are still open.", got)

    def test_some_still_open(self):
        got = joined(mk(u=6, total=104, c=20, oc=5, open_v=6))
        self.assertIn(f"20 are {GRADE}, and 5 of them are still open.", got)

    def test_exactly_one_still_open_of_many_is_singular(self):
        got = joined(mk(u=6, total=104, c=20, oc=1, open_v=6))
        self.assertIn("and 1 of them is still open.", got)

    def test_the_whole_record_being_class_c_keeps_its_own_shape(self):
        got = joined(mk(u=6, total=4, c=4, oc=2, open_v=4))
        self.assertIn("All 4 violations on record at the address are", got)
        self.assertIn("and 2 of them are still open.", got)

    def test_a_single_row_record_keeps_its_own_shape(self):
        got = joined(mk(u=6, total=1, c=1, oc=0, open_v=0))
        self.assertIn(f"The one violation on record at the address is {GRADE}, "
                      f"and it is no longer open.", got)

    def test_it_never_names_more_open_rows_than_the_record_holds(self):
        """The invariant, swept over inconsistent oc/c pairs.

        oc > c is a data inconsistency, not a real state, and "7 are class C, 9
        of them still open" is arithmetic that cannot be true. Note what this
        does and does not pin: the `ocv >= cv` branch catches every such pair
        and renders "all of them", so this passes on branch order alone and
        would pass with the min() clamp deleted. It is the OUTPUT invariant that
        matters to a reader, and it is pinned here so a future reordering of
        those branches cannot break it quietly.
        """
        for c, oc in ((7, 9), (7, 8), (1, 5), (2, 40), (20, 21)):
            got = joined(mk(u=6, total=40, c=c, oc=oc, open_v=20))
            self.assertNotIn(f"{oc:,} of them", got)
            self.assertNotIn(f"{oc:,} are still open", got)

    def test_no_class_c_record_means_no_grade_sentence_at_all(self):
        got = joined(mk(u=6, total=12, c=0, oc=0, open_v=3))
        self.assertNotIn("class C", got)
        self.assertNotIn("still open.", got)

    def test_the_grade_clause_is_never_said_twice_in_one_block(self):
        # A nine-word clause repeated in one paragraph reads as a template and
        # hands t_page_uniqueness a shingle every sibling shares.
        got = joined(mk(u=6, total=104, c=20, oc=5, open_v=6, last_12mo=3,
                        ctotal=40, clast=2))
        self.assertEqual(1, got.count(GRADE))


class TheRecencySentenceStandsOnItsOwn(unittest.TestCase):
    """`last_12mo` counts violations ISSUED in the last year (novissueddate)."""

    def test_it_is_said_when_there_were_any(self):
        got = joined(mk(u=6, total=40, c=0, open_v=3, last_12mo=4))
        self.assertIn("HPD issued 4 new violations at the address in the last "
                      "twelve months.", got)

    def test_one_is_singular(self):
        got = joined(mk(u=6, total=40, c=0, open_v=3, last_12mo=1))
        self.assertIn("HPD issued 1 new violation at the address in the last "
                      "twelve months.", got)

    def test_silence_rather_than_a_zero(self):
        # "HPD issued 0 new violations" invites the reader to conclude the
        # address is clean, when the record may simply be old.
        self.assertNotIn("in the last twelve months.",
                         joined(mk(u=6, total=40, c=0, open_v=3, last_12mo=0)))

    def test_it_never_refers_back_to_the_lifetime_sentence(self):
        # The grade sentence is suppressed when there is no class-C record, and
        # either sentence can be cut by the FACTS_MAX_SENTENCES slice, so a
        # pronoun here would sooner or later point at nothing.
        got = joined(mk(u=6, total=40, c=0, open_v=3, last_12mo=4))
        self.assertNotIn("issued 4 of them", got)
        self.assertIn("4 new violations at the address", got)

    def test_it_survives_without_a_grade_sentence_in_front_of_it(self):
        got = facts(mk(u=6, total=0, c=0, open_v=0, last_12mo=2))
        self.assertTrue(any("HPD issued 2 new violations" in s for s in got))


class TheBlockKeepsItsContract(unittest.TestCase):
    """The invariants the rest of build_seo.py and the $9 report rely on."""

    def test_it_never_exceeds_the_sentence_cap(self):
        b = mk(u=99, yr=1800, total=104, c=20, oc=5, open_v=6, last_12mo=3,
               ctotal=40, clast=2)
        self.assertLessEqual(len(facts(b)), B.FACTS_MAX_SENTENCES)

    def test_every_sentence_ends_in_a_full_stop(self):
        b = mk(u=99, yr=1800, total=104, c=20, oc=5, open_v=6, last_12mo=3,
               ctotal=40, clast=2)
        for s in facts(b):
            self.assertTrue(s.endswith("."), s)

    def test_no_unresolved_place_token_survives(self):
        b = mk(u=99, yr=1800, total=104, c=20, oc=5, open_v=6, last_12mo=3)
        self.assertNotIn("{PLACE}", joined(b))

    def test_a_building_with_nothing_on_file_says_nothing(self):
        self.assertEqual([], facts(mk()))

    def test_the_real_corpus_still_clears_the_audits_threshold(self):
        """t_derived_building_facts fails the build below COMPARE_MIN_PCT=90.

        Dropping the tautologies costs some blocks their third sentence, and the
        block is omitted rather than padded below FACTS_MIN_SENTENCES — so the
        suppression has to be checked against the corpus, not only a fixture.
        Measured 2026-10-20: 45,929 of 47,165 (97.4%).
        """
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "buildings.min.json")
        if not os.path.exists(path):
            self.skipTest("buildings.min.json not in this checkout")
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        by = {}
        for x in items:
            by.setdefault((x.get("b"), x.get("nb")), []).append(x)
        have = 0
        for key, its in by.items():
            nm = B.neighborhood_norms(its)
            for b in its:
                if len(B.building_facts(b, key[1], nm)) >= B.FACTS_MIN_SENTENCES:
                    have += 1
        pct = 100.0 * have / len(items)
        self.assertGreaterEqual(pct, 93.0,
                                f"only {have} of {len(items)} ({pct:.1f}%) carry a block — "
                                f"t_derived_building_facts fails below 90%")


if __name__ == "__main__":
    unittest.main()
