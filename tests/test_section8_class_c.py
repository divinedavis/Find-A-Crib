"""The open class-C record on the voucher listings: what it may and may not say.

2026-10-29. /section8/ is the only tier this repo can still deploy (the growth
engine has been paused since 2026-10-12; growth/section8_refresh.py rebuilds
these six pages nightly from the droplet checkout), and it now carries each
building's count of OPEN class-C HPD violations — HPD's immediately hazardous
grade. 188 of the 253 currently matched buildings have at least one.

That number is the most decision-relevant fact on the page and the easiest one
to turn into a claim the data does not support. The three failures these tests
exist to prevent, in the order they would do the most damage:

  1. A "0 open class C" badge reading as a clean bill of health. A zero means
     HPD has no OPEN class-C row on file for the building; it is a statement
     about a public record, not about the apartment being advertised, and 280
     Targee St (oc=0) has 2 lifetime class-C rows and 9 violations in total.
     So a zero renders NO TAG AT ALL, and the note says why.
  2. A count that contradicts the building page a reader clicks through to.
     build_seo.py's building-page sentence clamps open class-C to the lifetime
     class-C record because oc > c is a data inconsistency rather than a real
     state. This tier clamps it the same way, from the same fields.
  3. A freshness claim nobody can substantiate. Nothing on this site dates its
     HPD snapshot, so nothing here may either — the same refusal _dataset_jsonld
     already makes about a data licence.
"""
import os
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from growth import ledger, techniques as T  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRESH = 2_000_000_000.0


def _row(boro, i, oc=0):
    return {"addr": f"{i} Test St", "b8": True, "bbl": f"500000{i:04d}",
            "boro": boro, "boro_name": T.BORO_NAME[boro], "boro_slug": T.BORO_SLUG[boro],
            "n": 1, "nb": "Testville", "price": 1800 + i, "units": 10, "oc": oc,
            "url": "https://example.com/l", "zip": "10301"}


class Rendered(unittest.TestCase):
    """Render t_fresh_section8 over a controlled set of open class-C counts."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _run(self, si_ocs):
        """si_ocs: the open class-C count for each Staten Island row."""
        docroot = tempfile.mkdtemp(dir=self.tmp)
        out = tempfile.mkdtemp(dir=self.tmp)
        ctx = T.Context(REPO, docroot)
        ctx.out = out
        ctx._s8 = {"avail_updated": FRESH}
        rows = ([_row("Bx", i, oc=i % 4) for i in range(40)]
                + [_row("SI", 200 + j, oc=oc) for j, oc in enumerate(si_ocs)])
        with mock.patch.object(T, "_live_listings", lambda c: rows), \
             mock.patch.object(T, "_feed_freshness",
                               lambda c: (False, "October 29, 2026", None)), \
             mock.patch.object(ledger, "set_state"), \
             mock.patch.object(ledger, "get_state", lambda k, d=None: d):
            T.t_fresh_section8(ctx)
        return out

    def _page(self, out, *parts):
        p = os.path.join(out, "section8", *parts, "index.html")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return f.read()

    # ---- 1. a zero is never a badge

    def test_a_zero_count_renders_no_tag(self):
        html = self._page(self._run([0, 0, 0]), "staten-island")
        self.assertIn("<table>", html)
        self.assertNotIn("open class C", html,
                         "a building with no OPEN class-C row must carry no tag: "
                         "a '0 open class C' badge reads as a clean bill of health")

    def test_a_nonzero_count_renders_its_own_number(self):
        html = self._page(self._run([7, 0, 0]), "staten-island")
        self.assertIn('class="tag hz">7 open class C</span>', html)
        # ...and only for the row that has one.
        self.assertEqual(html.count("open class C</span>"), 1)

    def test_the_tag_is_not_styled_as_the_voucher_tag(self):
        # The green .tag means "accepts vouchers", which is good news. An
        # enforcement record is not good news and must not borrow its palette.
        html = self._page(self._run([7, 0, 0]), "staten-island")
        self.assertIn(".tag.hz{", html)
        self.assertIn('class="tag hz"', html)

    # ---- 2. the note appears exactly where a tag does

    def test_no_tag_on_the_page_means_no_note(self):
        html = self._page(self._run([0, 0, 0]), "staten-island")
        self.assertNotIn("What &ldquo;open class C&rdquo;", html)
        self.assertNotIn("immediately hazardous", html,
                         "a standing explanation of a badge that is nowhere on "
                         "the page is filler")

    def test_a_tag_on_the_page_brings_its_explanation(self):
        html = self._page(self._run([7, 0, 0]), "staten-island")
        self.assertIn("immediately hazardous", html)
        self.assertIn("24 hours", html)

    def test_the_hub_carries_the_note_because_the_bronx_rows_are_tagged(self):
        html = self._page(self._run([0, 0, 0]))
        self.assertIn("open class C", html)       # from the Bx rows
        self.assertIn("immediately hazardous", html)

    # ---- 3. what the note must say, and must not

    def test_the_note_scopes_the_count_to_the_building(self):
        n = T.CLASS_C_NOTE
        self.assertIn("building", n)
        self.assertIn("not for the apartment", n)

    def test_the_note_denies_the_inverse_reading(self):
        # The failure this sentence exists to stop: an absent tag read as proof.
        self.assertIn("clean bill of health", T.CLASS_C_NOTE)
        self.assertIn("no open class-C record on file", T.CLASS_C_NOTE)

    def test_the_note_makes_no_freshness_claim(self):
        n = T.CLASS_C_NOTE.lower()
        for banned in ("as of", "today", "current", "nightly", "updated", "live"):
            self.assertNotIn(banned, n,
                             f"{banned!r} dates a snapshot this site has never dated")
        self.assertNotRegex(T.CLASS_C_NOTE, r"\b20\d\d\b")

    def test_the_note_uses_the_building_pages_own_vocabulary(self):
        # Two writers describing one HPD grade in two vocabularies is how a
        # reader who clicks an address gets told two different things.
        self.assertIn("immediately hazardous", T.CLASS_C_NOTE)
        self.assertIn("24 hours", T.CLASS_C_NOTE)

    # ---- 4. the stat counts buildings, not violations

    def test_the_stat_counts_buildings_with_one_not_violations(self):
        html = self._page(self._run([5, 7, 0]), "staten-island")
        stats = re.search(r"<div class='stats'>(.*?)</div></div>", html, re.S).group(1)
        self.assertIn("with an open class C violation", stats)
        pair = re.search(r"<b>(\d+)</b><span>with an open class C violation</span>", html)
        self.assertEqual(pair.group(1), "2",
                         "2 of the 3 buildings have one; 12 is the violation sum "
                         "and reads as a figure about the voucher programme")

    def test_a_zero_count_renders_no_stat_either(self):
        # Found by test_a_zero_count_renders_no_tag while this change was being
        # written: the tag was suppressed at zero and the stat cell was not, so
        # a page of buildings with no OPEN class-C row got a headline "0 — with
        # an open class C violation" and no note to qualify it. The stats block
        # still renders; only this cell is gone.
        html = self._page(self._run([0, 0, 0]), "staten-island")
        self.assertIn("class='stats'", html)
        self.assertIn("explicitly accepting vouchers", html)
        self.assertNotIn("with an open class C violation", html)

    def test_the_stat_returns_once_any_building_has_one(self):
        html = self._page(self._run([0, 0, 4]), "staten-island")
        self.assertIn("<b>1</b><span>with an open class C violation</span>", html)

    def test_an_empty_borough_page_gets_neither_stat_nor_note(self):
        out = self._run([])
        html = self._page(out, "staten-island")
        self.assertIsNone(html, "no page is created for a borough with no listings")

    # ---- 5. the FAQ, and the standards this page already held

    def test_the_hub_faq_answers_the_question_the_tag_raises(self):
        qs = [q for q, _ in T.SECTION8_FAQ]
        self.assertTrue(any("class C" in q for q in qs), qs)
        html = self._page(self._run([7, 0, 0]))
        self.assertIn("FAQPage", html)

    def test_the_faq_answer_repeats_the_two_caveats(self):
        a = next(a for q, a in T.SECTION8_FAQ if "class C" in q)
        self.assertIn("for the building, not the advertised apartment", a)
        self.assertIn("rather than a guarantee of no problems", a)

    def test_no_licence_claim_appears_anywhere(self):
        # Standing rule, re-asserted because this change added JSON-LD text.
        html = self._page(self._run([7, 0, 0]))
        self.assertNotIn('"license"', html)

    def test_no_javascript_scheme_href(self):
        html = self._page(self._run([7, 0, 0]))
        self.assertNotIn("javascript:", html.lower())


class TheClamp(unittest.TestCase):
    """_live_listings reads oc/c off the building record and clamps, like build_seo."""

    def _rows(self, oc, c):
        ctx = types.SimpleNamespace(
            s8={"avail": {"1000010001": {"n": 1, "p": 1800, "url": "u", "b8": 1}}},
            by_bbl={"1000010001": {"bbl": "1000010001", "b": "M", "a": "1 TEST ST",
                                   "z": "10001", "nb": "Testville", "u": 10,
                                   "h": {"violations": {"oc": oc, "c": c}}}})
        return T._live_listings(ctx)

    def test_the_open_count_is_read_from_the_record(self):
        self.assertEqual(self._rows(14, 184)[0]["oc"], 14)

    def test_an_open_count_above_the_lifetime_record_is_clamped(self):
        # oc > c is a data inconsistency, not a real state. "9 of the 7 class-C
        # violations are still open" is the arithmetic that costs a reader their
        # trust in every other number on the page.
        self.assertEqual(self._rows(9, 7)[0]["oc"], 7)

    def test_missing_violation_data_is_zero_not_a_crash(self):
        ctx = types.SimpleNamespace(
            s8={"avail": {"1000010001": {"n": 1, "p": 1800, "url": "u"}}},
            by_bbl={"1000010001": {"bbl": "1000010001", "b": "M", "a": "1 TEST ST"}})
        self.assertEqual(T._live_listings(ctx)[0]["oc"], 0)

    def test_a_building_with_no_open_rows_but_a_lifetime_record_is_zero(self):
        # 280 Targee St: oc=0, c=2, total=9. It gets no tag, and that is correct
        # and is also exactly why the note has to explain an absent tag.
        self.assertEqual(self._rows(0, 2)[0]["oc"], 0)


class TheRealCorpus(unittest.TestCase):
    """What the committed s8.json + buildings.min.json actually produce."""

    def test_the_join_finds_open_class_c_on_most_matched_buildings(self):
        ctx = T.Context(REPO, tempfile.mkdtemp())
        rows = T._live_listings(ctx)
        self.assertGreater(len(rows), 200)
        tagged = [r for r in rows if r["oc"]]
        # Not an assertion about a specific night's feed — a floor that shows
        # the join is wired to real data rather than returning zeros.
        self.assertGreater(len(tagged), len(rows) // 4)
        self.assertTrue(all(r["oc"] > 0 for r in tagged))

    def test_no_row_claims_more_open_than_the_lifetime_record(self):
        ctx = T.Context(REPO, tempfile.mkdtemp())
        for r in T._live_listings(ctx):
            b = ctx.by_bbl[r["bbl"]]
            c = ((b.get("h") or {}).get("violations") or {}).get("c") or 0
            self.assertLessEqual(r["oc"], c, r["addr"])


if __name__ == "__main__":
    unittest.main()
