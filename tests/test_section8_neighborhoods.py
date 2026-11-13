"""_nb_breakdown: the neighborhood answer block on /section8/<boro>/ pages.

2026-11-08. The borough pages carried no answer block of any kind — the hub has
SECTION8_FAQ and _faq_jsonld, they had neither — and the Neighborhood column of
a 161-row table does not tell a reader that 17 of the Bronx's voucher-listed
buildings sit in Williamsbridge-Olinville. This block answers that from each
borough's own rows and links each neighborhood to its hub page.

Two things these tests exist to hold, because both are ways to be wrong rather
than merely ugly:

  * A LINK THAT 404s. 198 neighborhood hubs are published and NYC has more NTAs
    than that, so every link is gated on ctx.live_or_staged() and the slug has
    to match the one build_seo.py's nb_url() publishes under. SlugAgreement
    imports build_seo and compares the real functions, so the day one of them
    changes the test fails rather than the site growing dead links.

  * "Belmont (16)" READ AS SIXTEEN STABILIZED BUILDINGS IN BELMONT. It is
    sixteen buildings on that page; the neighborhood hub shows hundreds. The
    note under the list is the only thing standing between those two readings,
    so its clauses are pinned here and not left to review.
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
DATA = os.path.join(REPO, "data")  # the committed data files (2026-11-13)
FRESH = 2_000_000_000.0

BLOCK_RE = re.compile(
    r"<h2>Which neighborhoods these are in</h2>"
    r"<p class='sub'>(?P<lead>.*?)</p>"
    r"<div class='cols'>(?P<items>.*?)</div>"
    r"<div class='note'>(?P<note>.*?)</div>", re.S)


def _row(boro, i, nb="Testville"):
    return {"addr": f"{i} Test St", "b8": False, "bbl": f"500000{i:04d}",
            "boro": boro, "boro_name": T.BORO_NAME[boro], "boro_slug": T.BORO_SLUG[boro],
            "n": 1, "nb": nb, "price": 1800 + i, "units": 10, "oc": 0,
            "url": "https://example.com/l", "zip": "10301"}


class Render(unittest.TestCase):
    """t_fresh_section8 over a controlled borough/neighborhood mix."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _run(self, si_rows, hubs=(), stale=False):
        """Render with `si_rows` on Staten Island and `hubs` neighborhood pages.

        `hubs` are (boro, neighborhood-name) pairs that exist in the docroot.
        The Bronx and Brooklyn rows are only there to keep the hub honest; the
        assertions are all about Staten Island.
        """
        docroot = tempfile.mkdtemp(dir=self.tmp)
        out = tempfile.mkdtemp(dir=self.tmp)
        for boro, nb in hubs:
            d = os.path.join(docroot, "neighborhood", T.BORO_SLUG[boro], T._slugify(nb))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<p>hub</p>")
        ctx = T.Context(REPO, docroot)
        ctx.out = out
        ctx._s8 = {"avail_updated": None if stale else FRESH}
        rows = ([_row("Bx", i) for i in range(40)]
                + [_row("Bk", i) for i in range(100, 120)] + list(si_rows))
        with mock.patch.object(T, "_live_listings", lambda c: rows), \
             mock.patch.object(T, "_feed_freshness",
                               lambda c: (True, "July 11, 2026", "<b>old</b>") if stale
                               else (False, "November 8, 2026", None)), \
             mock.patch.object(ledger, "set_state"), \
             mock.patch.object(ledger, "get_state", lambda k, d=None: d):
            T.t_fresh_section8(ctx)
        with open(os.path.join(out, "section8", "staten-island", "index.html")) as f:
            si = f.read()
        with open(os.path.join(out, "section8", "index.html")) as f:
            hub = f.read()
        return si, hub

    # ---- when it renders at all

    def test_two_neighborhoods_render_a_block(self):
        si = [_row("SI", 200, "St. George-New Brighton"),
              _row("SI", 201, "St. George-New Brighton"),
              _row("SI", 202, "Tompkinsville")]
        page, _ = self._run(si)
        m = BLOCK_RE.search(page)
        self.assertIsNotNone(m, "no block rendered for two neighborhoods")
        self.assertIn("These 3 buildings sit in 2 neighborhoods", m.group("lead"))

    def test_one_neighborhood_renders_nothing(self):
        """The table's Neighborhood column already says it; a one-item list adds noise."""
        si = [_row("SI", 200, "St. George"), _row("SI", 201, "St. George"),
              _row("SI", 202, "St. George")]
        page, _ = self._run(si)
        self.assertNotIn("Which neighborhoods these are in", page)

    def test_no_named_neighborhood_renders_nothing(self):
        si = [_row("SI", 200, ""), _row("SI", 201, "   "), _row("SI", 202, "")]
        page, _ = self._run(si)
        self.assertNotIn("Which neighborhoods these are in", page)

    def test_the_hub_does_not_get_the_block(self):
        """It has borough links; 76 neighborhoods across 5 boroughs is a wall."""
        si = [_row("SI", 200, "A"), _row("SI", 201, "B"), _row("SI", 202, "C")]
        _, hub = self._run(si)
        self.assertNotIn("Which neighborhoods these are in", hub)

    # ---- the counts

    def test_counts_are_buildings_on_this_page(self):
        si = [_row("SI", 200, "Stapleton"), _row("SI", 201, "Stapleton"),
              _row("SI", 202, "Stapleton"), _row("SI", 203, "Tottenville")]
        page, _ = self._run(si)
        items = BLOCK_RE.search(page).group("items")
        self.assertIn("Stapleton (3)", items)
        self.assertIn("Tottenville (1)", items)

    def test_order_is_busiest_then_alphabetical(self):
        """A tie must not reshuffle night to night and read as the data moving."""
        si = [_row("SI", 200, "Zebra"), _row("SI", 201, "Zebra"),
              _row("SI", 202, "Beta"), _row("SI", 203, "Beta"),
              _row("SI", 204, "Alpha")]
        page, _ = self._run(si)
        items = BLOCK_RE.search(page).group("items")
        self.assertEqual(re.findall(r">([A-Za-z]+) \(\d+\)<", items),
                         ["Beta", "Zebra", "Alpha"])

    def test_top_clause_suppressed_when_nothing_leads(self):
        """'the most in X (1)' would invent a concentration the data lacks."""
        si = [_row("SI", 200, "A"), _row("SI", 201, "B"), _row("SI", 202, "C")]
        page, _ = self._run(si)
        lead = BLOCK_RE.search(page).group("lead")
        self.assertIn("sit in 3 neighborhoods.", lead)
        self.assertNotIn("the most in", lead)

    def test_top_clause_names_only_the_leaders(self):
        si = ([_row("SI", 200 + i, "Belmont") for i in range(4)]
              + [_row("SI", 210 + i, "Tremont") for i in range(2)]
              + [_row("SI", 220, "Soundview")])
        page, _ = self._run(si)
        lead = BLOCK_RE.search(page).group("lead")
        self.assertIn("the most in Belmont (4) and Tremont (2).", lead)
        self.assertNotIn("Soundview", lead)

    def test_a_runner_up_of_one_is_not_named_as_a_leader(self):
        """The real Staten Island and Queens shape: a 2 and then a tail of 1s.

        "the most in St. George-New Brighton (2) and Tompkinsville (1)" names a
        second leader that is only the first of the tail, which overstates how
        concentrated three listings are.
        """
        si = [_row("SI", 200, "St. George"), _row("SI", 201, "St. George"),
              _row("SI", 202, "Tompkinsville")]
        page, _ = self._run(si)
        lead = BLOCK_RE.search(page).group("lead")
        self.assertIn("the most in St. George (2).", lead)
        self.assertNotIn("Tompkinsville", lead)

    def test_unplaced_buildings_are_counted_out_loud(self):
        """Never assert a total and then quietly break down a smaller set."""
        si = [_row("SI", 200, "A"), _row("SI", 201, "A"), _row("SI", 202, "B"),
              _row("SI", 203, ""), _row("SI", 204, "")]
        page, _ = self._run(si)
        self.assertIn("3 of these 5 buildings sit in 2 neighborhoods",
                      BLOCK_RE.search(page).group("lead"))

    # ---- the links

    def test_links_only_where_the_hub_page_exists(self):
        si = [_row("SI", 200, "Has Hub"), _row("SI", 201, "Has Hub"),
              _row("SI", 202, "No Hub")]
        page, _ = self._run(si, hubs=[("SI", "Has Hub")])
        items = BLOCK_RE.search(page).group("items")
        self.assertIn("<a href='/neighborhood/staten-island/has-hub/'>Has Hub (2)</a>", items)
        self.assertNotIn("no-hub", items)
        self.assertIn("No Hub (1)", items)

    def test_the_unlinked_name_still_carries_its_own_styling(self):
        """Inline, so no CSS selector is added: CSS is embedded in every page
        _page() renders, and one new rule restamps all ~49k growth pages."""
        si = [_row("SI", 200, "Has Hub"), _row("SI", 201, "Has Hub"),
              _row("SI", 202, "No Hub")]
        page, _ = self._run(si, hubs=[("SI", "Has Hub")])
        items = BLOCK_RE.search(page).group("items")
        self.assertRegex(items, r"<span style='[^']+'>No Hub \(1\)</span>")
        self.assertNotIn(".cols span", T.CSS)

    def test_no_link_points_outside_the_boroughs_own_hub_tier(self):
        si = [_row("SI", 200, "A"), _row("SI", 201, "A"), _row("SI", 202, "B")]
        page, _ = self._run(si, hubs=[("SI", "A"), ("SI", "B")])
        items = BLOCK_RE.search(page).group("items")
        for href in re.findall(r"href='([^']+)'", items):
            self.assertTrue(href.startswith("/neighborhood/staten-island/"), href)
            self.assertTrue(href.endswith("/"), href)

    # ---- the note, which is the accuracy guard

    def test_the_note_says_which_reading_is_right(self):
        si = [_row("SI", 200, "Belmont"), _row("SI", 201, "Belmont"),
              _row("SI", 202, "Tremont")]
        page, _ = self._run(si)
        note = BLOCK_RE.search(page).group("note")
        self.assertIn("how many buildings <b>on this page</b> are in", note)
        self.assertIn("<b>not</b> how many rent-stabilized buildings the neighborhood has",
                      note)

    def test_the_note_degrades_with_the_feed(self):
        si = [_row("SI", 200, "Belmont"), _row("SI", 201, "Belmont"),
              _row("SI", 202, "Tremont")]
        fresh, _ = self._run(si, stale=False)
        stale, _ = self._run(si, stale=True)
        self.assertIn("have an apartment listed for voucher holders right now",
                      BLOCK_RE.search(fresh).group("note"))
        self.assertIn("had an apartment listed for voucher holders as of July 11, 2026",
                      BLOCK_RE.search(stale).group("note"))
        self.assertNotIn("right now", BLOCK_RE.search(stale).group("note"))

    def test_names_are_escaped(self):
        si = [_row("SI", 200, 'A & <b>B</b>'), _row("SI", 201, 'A & <b>B</b>'),
              _row("SI", 202, "C")]
        page, _ = self._run(si)
        items = BLOCK_RE.search(page).group("items")
        self.assertIn("A &amp; &lt;b&gt;B&lt;/b&gt; (2)", items)
        self.assertNotIn("<b>B</b>", items)


class SlugAgreement(unittest.TestCase):
    """The href has to be the URL build_seo.py actually publishes under.

    Two copies of the same two functions in two files is the whole risk: if
    either slugify or BORO_SLUG drifts, every link this block renders becomes a
    404 and nothing else in the suite would notice.
    """

    def test_slugify_and_boro_slug_agree_with_build_seo(self):
        try:
            import build_seo
        except Exception as exc:  # pragma: no cover - import-time deps
            self.skipTest(f"build_seo not importable: {exc}")
        self.assertEqual(T.BORO_SLUG, build_seo.BORO_SLUG)
        names = ["East Harlem (North)", "St. George-New Brighton",
                 "Tompkinsville-Stapleton-Clifton-Fox Hills", "Mount Hope",
                 "Breezy Point-Belle Harbor-Rockaway Park-Broad Channel",
                 "Williamsbridge-Olinville", "", "   ", "Bedford Park"]
        for nb in names:
            self.assertEqual(T._slugify(nb), build_seo.slugify(nb), nb)
        for boro in T.BORO_SLUG:
            self.assertEqual(
                f"/neighborhood/{T.BORO_SLUG[boro]}/{T._slugify('Mount Hope')}/",
                f"/neighborhood/{build_seo.BORO_SLUG.get(boro, 'nyc')}/"
                f"{build_seo.slugify('Mount Hope')}/")


class AgainstTheCommittedRecord(unittest.TestCase):
    """What the committed s8.json + buildings.min.json actually hold on 2026-11-08.

    These pin the shape the block was designed against — 2 to 35 neighborhoods
    per borough, every row placed — so a future reader can see whether the
    data moved or the code did.
    """

    @classmethod
    def setUpClass(cls):
        ctx = T.Context(DATA, DATA)
        cls.rows = T._live_listings(ctx)

    def _counts(self, boro):
        c = {}
        for r in self.rows:
            if r["boro"] == boro and r["nb"]:
                c[r["nb"]] = c.get(r["nb"], 0) + 1
        return c

    def test_the_boroughs_as_committed(self):
        self.assertEqual(len(self.rows), 253)
        shape = {b: (sum(1 for r in self.rows if r["boro"] == b), len(self._counts(b)))
                 for b in ("Bx", "Bk", "M", "Q", "SI")}
        self.assertEqual(shape, {"Bx": (161, 35), "Bk": (73, 26), "M": (11, 9),
                                 "Q": (5, 4), "SI": (3, 2)})

    def test_every_row_carries_a_neighborhood(self):
        """So "N of these M" is the untaken branch today, not dead code."""
        self.assertEqual([r["bbl"] for r in self.rows if not (r["nb"] or "").strip()], [])

    def test_the_bronx_leaders(self):
        c = self._counts("Bx")
        self.assertEqual(sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:2],
                         [("Williamsbridge-Olinville", 17), ("Belmont", 16)])

    def test_every_borough_clears_the_two_neighborhood_floor(self):
        """Every one of the five pages gets a block with today's data."""
        for b in ("Bx", "Bk", "M", "Q", "SI"):
            self.assertGreaterEqual(len(self._counts(b)), 2, b)


if __name__ == "__main__":
    unittest.main()
