"""The class-C aggregate on the NYC hub tier: what it may say and what it must not.

Why these exist (2026-10-30). This block states, on 365 pages, how many
buildings in a place carry a violation still open at HPD's immediately
hazardous grade. Tenants decide whether to pursue an address with it, and three
of its possible readings are wrong in ways that read perfectly well:

  * counting the whole TRACKED set as the denominator, which folds in every
    building HPD holds no record for and so understates the share;
  * emitting the sentence at zero, which is an aggregate clean bill of health
    for a whole neighborhood that HPD's record does not support — a closed
    class-C history is still a class-C history;
  * naming more open class-C rows than the lifetime class-C record they are
    drawn from, which is the arithmetic that costs a reader every other number
    on the page.

The pronoun is tested too. The sentence opens "N of those records", so it is
only true beside _hpd_record_sentence — a run that reorders the block or emits
this one without it leaves a pronoun pointing at nothing.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_seo as B  # noqa: E402


def mk(u=10, open_v=0, c=0, oc=0, has_record=True):
    """One building row in buildings.min.json's shape.

    `c` is the lifetime class-C count and `oc` how many of those are still
    open — HPD's own fields, the same pair the building sentence reads.
    has_record=False means HPD holds no violations record at all, which is a
    different thing from a record showing zero.
    """
    b = {"bbl": "x", "a": "1 MAIN ST", "u": u}
    if has_record:
        b["h"] = {"violations": {"open": open_v, "total": open_v, "c": c, "oc": oc}}
    return b


def facts(items, place="Testville"):
    return B.hub_condition_facts(place, B.neighborhood_norms(items))


def text(items, place="Testville"):
    return " ".join(facts(items, place))


def c_line(items, place="Testville"):
    """The class-C sentence alone, or None when the block did not emit one."""
    return next((s for s in facts(items, place) if "class C" in s), None)


class TheDenominatorIsTheRecord(unittest.TestCase):
    def test_buildings_with_no_hpd_record_are_not_in_the_base(self):
        # 10 buildings: 3 with an open class C, 2 with a clean record, 5 with
        # no HPD record at all. The honest sentence is 3 of 5 records — not
        # 3 of 10 buildings.
        items = ([mk(open_v=2, c=2, oc=2)] * 3 + [mk()] * 2
                 + [mk(has_record=False)] * 5)
        n = B.neighborhood_norms(items)
        self.assertEqual((n["n"], n["rec_n"], n["oc_n"]), (10, 5, 3))
        self.assertIn("3 of those records carry", c_line(items))

    def test_the_sentence_never_quotes_the_tracked_total(self):
        items = [mk(open_v=1, c=1, oc=1)] + [mk(has_record=False)] * 99
        self.assertNotIn("100", c_line(items))

    def test_all_of_them_says_so_rather_than_repeating_the_count(self):
        items = [mk(open_v=1, c=1, oc=1)] * 4
        self.assertIn("Every one of those records carries", c_line(items))

    def test_one_record_takes_the_singular_and_no_count(self):
        items = [mk(open_v=1, c=1, oc=1)] + [mk(has_record=False)] * 3
        self.assertEqual(c_line(items),
                         "That record carries a violation still open at class C — "
                         "HPD's immediately hazardous grade.")

    def test_a_single_hit_among_many_reads_as_one_not_as_a_digit(self):
        items = [mk(open_v=1, c=1, oc=1)] + [mk()] * 9
        self.assertIn("One of those records carries", c_line(items))


class SilenceIsNotAHazardFreeRecord(unittest.TestCase):
    def test_nothing_is_said_when_no_record_has_an_open_class_c(self):
        """The suppression this whole sentence is written around."""
        items = [mk(open_v=3, c=0, oc=0)] * 10
        self.assertIsNone(c_line(items))
        self.assertNotIn("class C", text(items))

    def test_a_closed_class_c_history_still_emits_nothing(self):
        # Every building here has had a class-C violation and none is open.
        # "0 with an open class C" would be the clean bill of health.
        items = [mk(open_v=0, c=4, oc=0)] * 10
        self.assertEqual(B.neighborhood_norms(items)["oc_n"], 0)
        self.assertIsNone(c_line(items))

    def test_no_record_at_all_emits_nothing(self):
        items = [mk(has_record=False)] * 10
        self.assertEqual(B.neighborhood_norms(items)["oc_n"], 0)
        self.assertIsNone(c_line(items))


class TheClamp(unittest.TestCase):
    def test_more_open_than_the_lifetime_record_is_not_counted(self):
        """oc > c is a data inconsistency, not a building to count."""
        items = [mk(open_v=9, c=0, oc=9)] * 10
        self.assertEqual(B.neighborhood_norms(items)["oc_n"], 0)

    def test_the_clamp_does_not_drop_a_consistent_row(self):
        items = [mk(open_v=9, c=2, oc=9)] * 10
        self.assertEqual(B.neighborhood_norms(items)["oc_n"], 10)

    def test_missing_class_fields_are_zero_and_not_a_crash(self):
        items = [{"bbl": "x", "u": 5, "h": {"violations": {"open": 3}}}] * 10
        self.assertEqual(B.neighborhood_norms(items)["oc_n"], 0)


class ThePronounHasAnAntecedent(unittest.TestCase):
    def test_the_record_sentence_always_precedes_it(self):
        items = [mk(open_v=2, c=2, oc=2)] * 10 + [mk()] * 10
        f = facts(items)
        rec = next(i for i, s in enumerate(f) if "HPD holds a violation record" in s)
        c = next(i for i, s in enumerate(f) if "class C" in s)
        self.assertEqual(c, rec + 1)

    def test_an_open_class_c_implies_the_record_sentence_reports_a_split(self):
        """oc_n > 0 cannot coexist with 'lists no open violation at any of them'."""
        items = [mk(open_v=2, c=2, oc=2)] * 3 + [mk()] * 7
        t = text(items)
        self.assertIn("class C", t)
        self.assertNotIn("lists no open violation at any of them", t)


class NoSecondFaqPair(unittest.TestCase):
    """Dropped on measurement — see the note in hub_conditions_html."""

    def test_the_faq_is_only_ever_the_open_violation_split(self):
        items = [mk(open_v=2, c=2, oc=2)] * 5 + [mk()] * 5
        html, faq = B.hub_conditions_html("Testville", B.neighborhood_norms(items))
        self.assertIn("class C", html)
        self.assertEqual(len(faq), 1)
        self.assertNotIn("class C", faq[0][0])

    def test_markup_never_answers_a_question_the_page_does_not_show(self):
        """faq_html's rule: a pair returned without its html is markup over nothing."""
        items = [mk(has_record=False)] * 10
        html, faq = B.hub_conditions_html("Testville", B.neighborhood_norms(items))
        self.assertEqual((html, faq), ("", []))


class TheZipTierCarriesTheBlock(unittest.TestCase):
    """/zip/ stated nothing about its own records until 2026-10-30."""

    def test_the_zip_hub_renders_conditions_and_its_faq(self):
        items = [mk(open_v=2, c=2, oc=2)] * 30 + [mk()] * 30
        html, faq = B.hub_conditions_html("ZIP code 11221",
                                          B.neighborhood_norms(items))
        self.assertIn("What the records say about ZIP code 11221", html)
        self.assertIn("class C", html)
        self.assertEqual(len(faq), 1)
        self.assertIn("ZIP code 11221", faq[0][0])

    def test_the_block_is_wired_into_the_zip_page_source(self):
        """A rendered-page test cannot reach main(); this pins the call site."""
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "build_seo.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('hub_conditions_html(\n            f"ZIP code {z}"', src)
        self.assertIn("zip_faq += zip_cond_faq", src)
        self.assertIn("+ zip_cond_html", src)


class TheRealCorpus(unittest.TestCase):
    """Against the committed register, not a fixture."""

    @classmethod
    def setUpClass(cls):
        import collections
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "buildings.min.json")
        with open(path, encoding="utf-8") as f:
            blds = json.load(f)
        cls.by_nb = collections.defaultdict(list)
        for b in blds:
            if b.get("nb"):
                cls.by_nb[(b["b"], b["nb"])].append(b)

    def test_most_neighborhoods_have_something_to_say(self):
        said = sum(1 for items in self.by_nb.values()
                   if c_line(items) is not None)
        self.assertGreater(said, len(self.by_nb) * 0.9)

    def test_no_neighborhood_claims_more_open_than_its_record_base(self):
        for k, items in self.by_nb.items():
            n = B.neighborhood_norms(items)
            self.assertLessEqual(n["oc_n"], n["rec_n"], k)
            self.assertLessEqual(n["rec_n"], n["n"], k)

    def test_an_open_class_c_is_a_minority_of_records_citywide(self):
        """A sanity floor and ceiling: neither 0% nor 100% is a real reading."""
        oc = sum(B.neighborhood_norms(v)["oc_n"] for v in self.by_nb.values())
        rec = sum(B.neighborhood_norms(v)["rec_n"] for v in self.by_nb.values())
        self.assertGreater(oc / rec, 0.2)
        self.assertLess(oc / rec, 0.95)


if __name__ == "__main__":
    unittest.main(verbosity=2)
