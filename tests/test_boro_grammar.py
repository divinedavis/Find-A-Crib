"""The borough name has two grammatical positions on a /section8/<boro>/ page.

2026-11-12. Four boroughs are bare proper nouns ("Brooklyn") and read correctly
wherever they are dropped. The fifth carries an article — BORO_NAME["Bx"] is
"the Bronx" — and that is right as a noun phrase ("Section 8 apartments in the
Bronx", the breadcrumb, the Dataset's place) and wrong in front of a noun.

t_fresh_section8 built both from one variable, via

    disp = name if name.startswith("the ") else name

which tests for the leading article and then returns `name` on both branches:
the intent was recorded and the fix never written. So the Bronx page led with
"161 rent-stabilized the Bronx buildings" and its Dataset node was titled
"Rent-stabilized the Bronx buildings" — the borough holding 161 of the 253
listed buildings, on the most-visited page of this tier.

These tests pin BOTH positions, because a later edit that "simplifies" the two
spellings back into one would restore the bug silently and the four other
boroughs would not notice.
"""
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from growth import ledger, techniques as T  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRESH = 2_000_000_000.0


def _row(boro, i):
    return {"addr": f"{i} Test St", "b8": i % 2 == 0, "bbl": f"200000{i:04d}",
            "boro": boro, "boro_name": T.BORO_NAME[boro], "boro_slug": T.BORO_SLUG[boro],
            "n": 1, "nb": "Testville", "price": 1800 + i, "units": 10,
            "url": "https://example.com/l", "zip": "10451"}


class BoroAdjHelper(unittest.TestCase):

    def test_only_the_bronx_loses_an_article(self):
        self.assertEqual(T._boro_adj("the Bronx"), "Bronx")
        for b in ("M", "Bk", "Q", "SI"):
            name = T.BORO_NAME[b]
            self.assertEqual(T._boro_adj(name), name,
                             f"{name} is a bare proper noun and must pass through")

    def test_it_is_derived_from_boro_name_not_a_second_table(self):
        # A second dict of five names is a drift risk; every adjective form must
        # still be reachable from BORO_NAME alone.
        for b, name in T.BORO_NAME.items():
            self.assertTrue(T._boro_adj(name))
            self.assertFalse(T._boro_adj(name).startswith("the "))


class BronxGrammar(unittest.TestCase):
    """Render t_fresh_section8 with a controlled Bronx and read both positions."""

    def _run(self, bx_count, bx_live=True, stale=False):
        docroot = tempfile.mkdtemp(dir=self.tmp)
        out = tempfile.mkdtemp(dir=self.tmp)
        if bx_live:
            d = os.path.join(docroot, "section8", "bronx")
            os.makedirs(d)
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<p>last night</p>")
        ctx = T.Context(REPO, docroot)
        ctx.out = out
        ctx._s8 = {"avail_updated": None if stale else FRESH}
        rows = ([_row("Bx", i) for i in range(bx_count)]
                + [_row("Bk", i) for i in range(100, 120)])
        with mock.patch.object(T, "_live_listings", lambda c: rows), \
             mock.patch.object(T, "_feed_freshness",
                               lambda c: (True, "July 11, 2026", "<b>old</b>") if stale
                               else (False, "November 12, 2026", None)), \
             mock.patch.object(ledger, "set_state"), \
             mock.patch.object(ledger, "get_state", lambda k, d=None: d):
            T.t_fresh_section8(ctx)
        return out

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _bx(self, out):
        p = os.path.join(out, "section8", "bronx", "index.html")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return f.read()

    def _lead(self, html):
        return re.sub(r"\s+", " ", re.search(r"<p class='sub'>(.*?)</p>", html, re.S).group(1))

    # ---- the adjective position: no article

    def test_the_lead_sentence_uses_the_bronx_as_an_adjective(self):
        lead = self._lead(self._bx(self._run(40)))
        self.assertIn("40 rent-stabilized Bronx buildings have an apartment", lead)
        self.assertNotIn("the Bronx building", lead)

    def test_an_empty_night_uses_the_adjective_too(self):
        lead = self._lead(self._bx(self._run(0)))
        self.assertIn("No rent-stabilized Bronx buildings have an apartment", lead)
        self.assertNotIn("rent-stabilized the Bronx", lead)

    def test_the_dataset_node_is_titled_with_the_adjective(self):
        html = self._bx(self._run(40))
        self.assertIn("Rent-stabilized Bronx buildings with live Section 8", html)
        self.assertIn("40 Bronx buildings registered rent-stabilized with DHCR", html)
        self.assertNotIn("Rent-stabilized the Bronx buildings", html)

    def test_no_page_ever_says_rent_stabilized_the_bronx(self):
        # The one phrase that proves the two positions have collapsed again.
        for count in (0, 1, 40):
            for stale in (False, True):
                with self.subTest(count=count, stale=stale):
                    out = self._run(count, stale=stale)
                    for root, _, files in os.walk(out):
                        for name in files:
                            with open(os.path.join(root, name)) as fh:
                                html = fh.read()
                            self.assertNotIn("rent-stabilized the Bronx", html)
                            self.assertNotIn("the Bronx building", html)

    # ---- the noun-phrase position: the article STAYS

    def test_the_heading_and_title_keep_the_article(self):
        html = self._bx(self._run(40))
        self.assertIn("<h1>Section 8 apartments in the Bronx", html)
        self.assertIn("<title>Section 8 apartments in the Bronx", html)
        self.assertIn("Rent-stabilized buildings in the Bronx with apartments", html)

    def test_the_breadcrumb_and_borough_link_keep_the_article(self):
        html = self._bx(self._run(40))
        self.assertIn("› the Bronx", html)
        self.assertIn('"name": "the Bronx"', html)
        self.assertIn("Every rent-stabilized building in the Bronx", html)

    def test_the_dataset_place_keeps_the_article(self):
        # spatialCoverage is a place name, not an adjective.
        html = self._bx(self._run(40))
        self.assertRegex(html, r'"spatialCoverage":\s*\{[^}]*"name":\s*"the Bronx"')

    # ---- the other four boroughs are untouched in either position

    def test_a_bare_proper_noun_borough_reads_the_same_as_before(self):
        with open(os.path.join(self._run(40), "section8", "brooklyn", "index.html")) as f:
            html = f.read()
        self.assertIn("20 rent-stabilized Brooklyn buildings have an apartment",
                      self._lead(html))
        self.assertIn("<h1>Section 8 apartments in Brooklyn", html)
        self.assertIn("Rent-stabilized Brooklyn buildings with live Section 8", html)

    def test_the_hub_still_names_the_borough_as_a_noun(self):
        with open(os.path.join(self._run(40), "section8", "index.html")) as f:
            hub = f.read()
        self.assertIn("the Bronx", hub)
        self.assertNotIn("rent-stabilized the Bronx", hub)


class BoroughHubSentenceStart(unittest.TestCase):
    """build_seo.py opens the /borough/<x>/ answer block with the borough name.

    Same bug class, other renderer: "the Bronx has 5,000 buildings registered as
    rent stabilized..." is the first sentence of the direct answer on
    /borough/bronx/, and it opened with a lowercase article. This tier is built
    by the monthly SEO pipeline rather than by the growth loop, so the fix lands
    when that pipeline next rebuilds the corpus.
    """

    def test_only_the_article_is_recased(self):
        import build_seo as B
        self.assertEqual(B.sentence_start("the Bronx"), "The Bronx")
        for b in ("M", "Bk", "Q", "SI"):
            name = B.BORO_NAME[b]
            self.assertEqual(B.sentence_start(name), name)

    def test_it_never_lowercases_the_rest_of_the_name(self):
        # .capitalize() would turn "the Bronx" into "The bronx".
        import build_seo as B
        self.assertEqual(B.sentence_start("Staten Island"), "Staten Island")
        self.assertIn("Bronx", B.sentence_start("the Bronx"))

    def test_it_is_safe_on_an_empty_name(self):
        import build_seo as B
        self.assertEqual(B.sentence_start(""), "")

    def test_the_borough_answer_block_opens_with_it(self):
        # Pins the call site: a later edit that drops it restores the lowercase
        # sentence on exactly one of the five borough hubs.
        import inspect
        import build_seo as B
        src = inspect.getsource(B)
        self.assertIn('f"{sentence_start(boroname)} has {total:,} buildings', src)
