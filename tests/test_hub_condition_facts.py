"""The hub conditions block: what it may say, and what it must refuse to say.

Why these exist (2026-10-09). This block makes aggregate claims about housing
conditions on the tier Google still re-crawls, and tenants make housing
decisions with them. Three of the claims are the kind that read fine and mean
something false:

  * counting "HPD holds no violation record" as "HPD lists no open violation",
    which turns silence into a clean bill of health;
  * a "median" over a sample of one or two buildings, which is one building's
    number wearing the authority of a statistic (3 of 198 NYC neighborhoods
    hold exactly one building and 26 hold fewer than 20);
  * an FAQPage answer for a split the rendered page does not show, which is
    structured data describing content that is not there.

A docstring cannot fail a build, so each of those is a test. The grammar cases
are here too: the block is reader-facing on 203 pages and "all 2 buildings" is
the tell that a template is filling itself in, which is the impression the
whole block exists to undo.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_seo as B  # noqa: E402


def mk(u=None, open_v=None, has_record=True, yr=None):
    """One building row in buildings.min.json's shape.

    has_record=False means HPD holds no violations record for the address at
    all, which is a different thing from a record showing zero.
    """
    b = {"bbl": "x", "a": "1 MAIN ST"}
    if u is not None:
        b["u"] = u
    if yr is not None:
        b["yr"] = yr
    if has_record:
        b["h"] = {"violations": {"open": open_v or 0, "total": open_v or 0}}
    return b


def facts(items, place="Testville"):
    return B.hub_condition_facts(place, B.neighborhood_norms(items))


def text(items, place="Testville"):
    return " ".join(facts(items, place))


class SilenceIsNotACleanRecord(unittest.TestCase):
    def test_no_record_buildings_are_excluded_from_the_clean_count(self):
        # 10 buildings: 4 clean records, 1 with an open violation, 5 with no
        # HPD record at all. The honest numbers are 5 records and 4 clean.
        items = ([mk(u=10)] * 4 + [mk(u=10, open_v=3)]
                 + [mk(u=10, has_record=False)] * 5)
        n = B.neighborhood_norms(items)
        self.assertEqual(n["rec_n"], 5)
        self.assertEqual(n["clean_rec"], 4)
        # `clean` — the base building_facts() uses — counts 9, which is exactly
        # why the hub block may not use it.
        self.assertEqual(n["clean"], 9)
        self.assertIn("record for 5 of the 10 buildings", text(items))
        self.assertIn("no open violation at 4 of those", text(items))
        self.assertNotIn("at 9 of", text(items))

    def test_a_place_with_no_hpd_records_at_all_says_nothing_about_hpd(self):
        items = [mk(u=10, has_record=False)] * 30
        self.assertIsNone(B._hpd_record_sentence(30, 0, 0))
        self.assertFalse(any("HPD" in s for s in facts(items)))

    def test_and_that_place_loses_the_block_rather_than_padding_it(self):
        # One surviving sentence is a caption, not a block.
        items = [mk(u=10, has_record=False)] * 30
        self.assertEqual(len(facts(items)), 1)
        html, faq = B.hub_conditions_html("Testville", B.neighborhood_norms(items))
        self.assertEqual((html, faq), ("", []))


class AMedianNeedsABase(unittest.TestCase):
    def test_one_building_gets_no_median_of_any_kind(self):
        got = text([mk(u=180, open_v=11)])
        self.assertNotIn("median", got)
        self.assertIn("The one building here has about 180 apartments", got)

    def test_under_the_base_reports_totals_and_no_median(self):
        items = [mk(u=10, open_v=5)] * (B.HUB_MEDIAN_MIN_BASE - 1)
        got = text(items)
        self.assertNotIn("median", got)
        # The total is still an exact fact about those buildings.
        self.assertIn(f"about {10 * (B.HUB_MEDIAN_MIN_BASE - 1):,} apartments", got)

    def test_at_the_base_the_medians_appear(self):
        items = [mk(u=10, open_v=5)] * B.HUB_MEDIAN_MIN_BASE
        got = text(items)
        self.assertIn("a median of 10 per building", got)
        self.assertIn("the median across the 20 with an apartment count", got)

    def test_the_constant_drives_the_behaviour(self):
        # Otherwise HUB_MEDIAN_MIN_BASE is decoration: move it, and the verdict
        # for the same 25 buildings has to move with it.
        items = [mk(u=10, open_v=5)] * 25
        self.assertIn("median", text(items))
        old = B.HUB_MEDIAN_MIN_BASE
        try:
            B.HUB_MEDIAN_MIN_BASE = 500
            self.assertNotIn("median", text(items))
        finally:
            B.HUB_MEDIAN_MIN_BASE = old

    def test_a_zero_median_rate_is_not_phrased_as_a_rate(self):
        # Majority clean: rate_med is 0.0, and _rate_phrase() promises its
        # caller a positive rate. The sentence must be dropped, not rendered
        # as "one for every 2 apartments" off a zero.
        items = [mk(u=10)] * 30 + [mk(u=10, open_v=4)] * 5
        n = B.neighborhood_norms(items)
        self.assertEqual(n["rate_med"], 0)
        self.assertNotIn("Counting the buildings with no open violation", text(items))
        # the per-building median still shows: it has a base and a value
        self.assertIn("a median of 10 per building", text(items))


class TheRateSentenceSaysWhatItCounted(unittest.TestCase):
    def test_it_declares_that_clean_buildings_count_as_zero(self):
        # A median that silently dropped the zeroes would read identically and
        # describe a materially worse place.
        items = [mk(u=10)] * 10 + [mk(u=10, open_v=20)] * 15
        got = text(items)
        self.assertIn("Counting the buildings with no open violation as zero", got)
        self.assertIn("across the 25 with an apartment count", got)

    def test_it_names_its_own_denominator_not_the_building_count(self):
        # 40 buildings, only 25 with an apartment count: the rate is over 25.
        items = ([mk(u=10, open_v=20)] * 25 + [mk(open_v=20)] * 15)
        n = B.neighborhood_norms(items)
        self.assertEqual(n["n"], 40)
        self.assertEqual(n["rate_n"], 25)
        self.assertIn("across the 25 with an apartment count", text(items))


class TheFaqMatchesTheRenderedPage(unittest.TestCase):
    def test_no_faq_pair_without_the_block(self):
        items = [mk(u=10, has_record=False)] * 30
        _, faq = B.hub_conditions_html("Testville", B.neighborhood_norms(items))
        self.assertEqual(faq, [])

    def test_no_faq_pair_when_there_is_no_split_to_report(self):
        # All clean, and all dirty: the block already says so in words, and the
        # pair would be the same fact asked as a question.
        for items in ([mk(u=10)] * 30, [mk(u=10, open_v=2)] * 30):
            html, faq = B.hub_conditions_html("Testville", B.neighborhood_norms(items))
            self.assertTrue(html)
            self.assertEqual(faq, [])

    def test_the_split_case_answers_with_the_blocks_own_numbers(self):
        items = [mk(u=10)] * 12 + [mk(u=10, open_v=3)] * 18 + [mk(u=10, has_record=False)] * 5
        html, faq = B.hub_conditions_html("Testville", B.neighborhood_norms(items))
        self.assertEqual(len(faq), 1)
        q, a = faq[0]
        self.assertIn("Testville", q)
        self.assertIn("record for 30 of the 35", a)
        self.assertIn("18 of those have at least one open violation", a)
        self.assertIn("12 have none", a)
        # the hedge the number needs, in the answer and not only in the block
        self.assertIn("no HPD violation record is not counted either way", a)
        # and the rendered block carries the same pair of numbers
        self.assertIn("record for 30 of the 35 buildings", html)
        self.assertIn("no open violation at 12 of those", html)


class GrammarOnThePagesPeopleRead(unittest.TestCase):
    def test_singular(self):
        got = text([mk(u=1, open_v=2)])
        self.assertIn("about 1 apartment on file", got)
        self.assertNotIn("1 apartments", got)
        self.assertIn("the one building tracked here, and it has at least one open", got)

    def test_two(self):
        got = text([mk(u=5, open_v=1)] * 2)
        self.assertIn("Both of them hold", got)
        self.assertIn("for both buildings tracked here", got)
        self.assertNotIn("All 2", got)
        self.assertNotIn("all 2", got)

    def test_all_clean_singular_and_plural(self):
        self.assertIn("no open violation against it",
                      B._hpd_record_sentence(1, 1, 1))
        self.assertIn("no open violation at any of them",
                      B._hpd_record_sentence(9, 9, 9))

    def test_partial_coverage_says_n_of_m(self):
        self.assertIn("for 7 of the 9 buildings", B._hpd_record_sentence(9, 7, 3))

    def test_every_sentence_ends_in_a_period(self):
        for items in ([mk(u=180, open_v=11)],
                      [mk(u=5, open_v=1)] * 2,
                      [mk(u=10)] * 12 + [mk(u=10, open_v=3)] * 18):
            for s in facts(items):
                self.assertTrue(s.endswith("."), s)


class ItIsTheSameDictTheBuildingPagesUse(unittest.TestCase):
    def test_new_keys_do_not_disturb_building_facts(self):
        # neighborhood_norms() gained rec_n/clean_rec for this block. The
        # building-page comparison block reads the same dict and must be
        # unaffected.
        items = [mk(u=10, open_v=2, yr=1920) for _ in range(40)]
        norms = B.neighborhood_norms(items)
        for k in ("n", "units", "unit_med", "year_med", "rate_med", "rate_n", "clean"):
            self.assertIn(k, norms)
        out = B.building_facts(items[0], "Testville", norms)
        self.assertTrue(out)
        self.assertTrue(all(isinstance(s, str) and s for s in out))

    def test_empty_place_returns_nothing_rather_than_dividing_by_zero(self):
        self.assertEqual(B.hub_condition_facts("Nowhere", B.neighborhood_norms([])), [])
        self.assertEqual(B.hub_condition_facts("Nowhere", {}), [])
        self.assertEqual(B.hub_conditions_html("Nowhere", {}), ("", []))


class RealDataRenders(unittest.TestCase):
    """Against buildings.min.json itself, because the shapes above are mine.

    Skipped rather than failed where the corpus is not in the checkout: this
    file has to be runnable in a bare clone.
    """

    @classmethod
    def setUpClass(cls):
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "buildings.min.json")
        if not os.path.exists(path):
            raise unittest.SkipTest("buildings.min.json not in this checkout")
        with open(path) as fh:
            cls.blds = json.load(fh)

    def test_every_nyc_neighborhood_either_renders_or_is_omitted_cleanly(self):
        from collections import defaultdict
        by = defaultdict(list)
        for b in self.blds:
            if b.get("nb"):
                by[(b["b"], b["nb"])].append(b)
        rendered = 0
        for (boro, nb), items in by.items():
            html, faq = B.hub_conditions_html(nb, B.neighborhood_norms(items))
            if not html:
                continue
            rendered += 1
            self.assertIn("<h2>", html)
            self.assertNotIn("None", html)
            self.assertNotIn("{", html)
            self.assertNotIn("all 2 ", html)
            # a median only ever appears above the base
            if "median" in html:
                self.assertGreaterEqual(len(items), B.HUB_MEDIAN_MIN_BASE)
            for _q, a in faq:
                self.assertNotIn("None", a)
        # all 198 of them have unit counts and HPD records; if this ever drops
        # sharply the corpus changed shape, which is worth a failure.
        self.assertGreater(rendered, 190)

    def test_the_five_borough_hubs_render(self):
        for boro in ("M", "Bk", "Q", "Bx", "SI"):
            items = [b for b in self.blds if b["b"] == boro]
            html, faq = B.hub_conditions_html(B.BORO_NAME[boro],
                                              B.neighborhood_norms(items))
            self.assertIn("HPD holds a violation record", html)
            self.assertEqual(len(faq), 1)


if __name__ == "__main__":
    unittest.main()
