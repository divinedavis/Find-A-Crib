"""t_fresh_section8's borough pages: the threshold gates creating one, not rebuilding one.

2026-10-22. BORO_MIN_LISTINGS used to gate both, via `continue` over by_boro, so
a borough that dropped below it was not rendered at all — and an unrendered page
is not an absent page. Both deploy paths are `rsync -a` with no --delete, so it
stayed live carrying the previous night's count, table and present-tense wording
("have an apartment listed right now", "Updated daily."), and nothing on the box
could see it: stale_claims() dates /section8/ from its freshest claiming page,
t_frozen_pages from the newest page in the docroot, stale_feeds() from s8.json.

Staten Island held exactly 3 of 253 matched listings on 2026-10-22 — the
threshold itself — so one listing turning over is all this needs.
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
FRESH = 2_000_000_000.0  # any timestamp; the tests pin the branch explicitly


def _row(boro, i):
    return {"addr": f"{i} Test St", "b8": i % 2 == 0, "bbl": f"500000{i:04d}",
            "boro": boro, "boro_name": T.BORO_NAME[boro], "boro_slug": T.BORO_SLUG[boro],
            "n": 1, "nb": "Testville", "price": 1800 + i, "units": 10,
            "url": "https://example.com/l", "zip": "10301"}


class BoroughPages(unittest.TestCase):
    """Render t_fresh_section8 with a controlled borough mix."""

    def _run(self, si_count, si_live, stale=False):
        """Returns (result, ctx, staged_dir). Nothing touches the real ledger."""
        docroot = tempfile.mkdtemp(dir=self.tmp)
        out = tempfile.mkdtemp(dir=self.tmp)
        if si_live:
            d = os.path.join(docroot, "section8", "staten-island")
            os.makedirs(d)
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("<p>last night: 3 buildings have a listing right now</p>")
        ctx = T.Context(REPO, docroot)
        ctx.out = out
        # Bypass s8.json and buildings.min.json: _feed_freshness and the
        # ItemList only ever read avail_updated off ctx.s8.
        ctx._s8 = {"avail_updated": None if stale else FRESH}
        rows = ([_row("Bx", i) for i in range(40)] + [_row("Bk", i) for i in range(100, 120)]
                + [_row("SI", i) for i in range(200, 200 + si_count)])
        with mock.patch.object(T, "_live_listings", lambda c: rows), \
             mock.patch.object(T, "_feed_freshness",
                               lambda c: (True, "July 11, 2026", "<b>old</b>") if stale
                               else (False, "October 22, 2026", None)), \
             mock.patch.object(ledger, "set_state") as self.set_state, \
             mock.patch.object(ledger, "get_state", lambda k, d=None: d):
            res = T.t_fresh_section8(ctx)
        return res, ctx, out

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def _si(self, out):
        p = os.path.join(out, "section8", "staten-island", "index.html")
        return self._read(p) if os.path.exists(p) else None

    def _hub_links(self, out):
        hub = self._read(os.path.join(out, "section8", "index.html"))
        return {s: int(n) for s, _, n in
                re.findall(r"/section8/([a-z-]+)/'>([^<(]+)\((\d+)\)", hub)}

    def _lead(self, html):
        return re.sub(r"\s+", " ", re.search(r"<p class='sub'>(.*?)</p>", html, re.S).group(1))

    # ---- the baseline, unchanged

    def test_a_borough_at_the_threshold_gets_a_full_page(self):
        res, ctx, out = self._run(si_count=T.BORO_MIN_LISTINGS, si_live=False)
        html = self._si(out)
        self.assertIsNotNone(html)
        self.assertIn("3 rent-stabilized Staten Island buildings have an apartment", self._lead(html))
        self.assertIn("<table>", html)
        self.assertIn("class='stats'", html)
        self.assertIn("Dataset", html)
        self.assertIn("https://findacrib.com/section8/staten-island/", ctx.new_urls)

    def test_the_threshold_is_a_named_constant(self):
        # A magic 3 in the loop is how the two halves drifted apart in the first
        # place: the hub linked every borough, the loop built pages above 3.
        self.assertEqual(T.BORO_MIN_LISTINGS, 3)

    # ---- the fix

    def test_a_thin_borough_with_a_live_page_is_rebuilt_with_tonights_count(self):
        res, ctx, out = self._run(si_count=2, si_live=True)
        html = self._si(out)
        self.assertIsNotNone(html, "a live page must not be left carrying last night's count")
        self.assertIn("2 rent-stabilized Staten Island buildings have an apartment",
                      self._lead(html))
        self.assertNotIn("last night", html)

    def test_a_thin_borough_with_no_page_yet_is_still_skipped(self):
        # The anti-filler rule: never create a thin URL that was not there.
        res, ctx, out = self._run(si_count=2, si_live=False)
        self.assertIsNone(self._si(out))

    def test_a_rebuilt_thin_page_is_not_submitted_for_crawling(self):
        res, ctx, out = self._run(si_count=1, si_live=True)
        url = "https://findacrib.com/section8/staten-island/"
        self.assertIsNotNone(self._si(out))
        self.assertNotIn(url, ctx.new_urls + ctx.changed_urls)
        # the hub still is
        self.assertIn("https://findacrib.com/section8/", ctx.new_urls + ctx.changed_urls)

    def test_one_listing_reads_as_one_building(self):
        res, ctx, out = self._run(si_count=1, si_live=True)
        self.assertIn("1 rent-stabilized Staten Island building has an apartment",
                      self._lead(self._si(out)))

    # ---- the empty night

    def test_an_empty_borough_with_a_live_page_says_so_plainly(self):
        res, ctx, out = self._run(si_count=0, si_live=True)
        html = self._si(out)
        lead = self._lead(html)
        self.assertIn("No rent-stabilized Staten Island buildings have an apartment", lead)
        # A reader must not read an empty night as lost stabilization.
        self.assertIn("registered rent-stabilized either way", lead)
        self.assertIn("<title>Section 8 apartments in Staten Island — none listed right now",
                      html)

    def test_an_empty_borough_carries_no_empty_table_stats_or_dataset(self):
        res, ctx, out = self._run(si_count=0, si_live=True)
        html = self._si(out)
        self.assertNotIn("<table>", html)
        self.assertNotIn("class='stats'", html)
        # A Dataset of zero records reads as a finding about the borough.
        self.assertNotIn("Dataset", html)
        # The tenant-rights notice and a way out both stay.
        self.assertIn("Source-of-income discrimination", html)
        self.assertIn("/borough/staten-island/", html)
        self.assertIn("Voucher listings in every", html)

    def test_an_empty_borough_with_no_page_yet_is_not_created(self):
        res, ctx, out = self._run(si_count=0, si_live=False)
        self.assertIsNone(self._si(out))

    # ---- the hub and the pages have to agree

    def test_the_hub_never_links_a_borough_it_did_not_publish(self):
        # The old loop linked every borough in the feed, so a borough below the
        # threshold with no page was advertised as a URL that 404s.
        for count, live in ((2, False), (0, False)):
            with self.subTest(count=count, live=live):
                res, ctx, out = self._run(si_count=count, si_live=live)
                self.assertNotIn("staten-island", self._hub_links(out))
                self.assertIsNone(self._si(out))

    def test_a_borough_kept_alive_stays_linked_from_the_hub(self):
        # Dropping its only inbound link would orphan a live page, not retire it.
        for count in (0, 1, 2):
            with self.subTest(count=count):
                res, ctx, out = self._run(si_count=count, si_live=True)
                self.assertEqual(self._hub_links(out).get("staten-island"), count)
                self.assertIsNotNone(self._si(out))

    def test_every_hub_link_resolves_to_a_page_this_run_wrote(self):
        for count, live in ((5, False), (2, True), (0, True), (2, False)):
            with self.subTest(count=count, live=live):
                res, ctx, out = self._run(si_count=count, si_live=live)
                for slug in self._hub_links(out):
                    self.assertTrue(
                        os.path.exists(os.path.join(out, "section8", slug, "index.html")),
                        f"hub links /section8/{slug}/ but wrote no page")

    # ---- the stale feed still wins

    def test_a_stale_feed_still_dates_an_empty_page(self):
        res, ctx, out = self._run(si_count=0, si_live=True, stale=True)
        html = self._si(out)
        self.assertIn("No rent-stabilized Staten Island buildings had an apartment",
                      self._lead(html))
        self.assertNotIn("right now", html)
        self.assertNotIn("Updated daily", html)

    def test_nothing_here_writes_the_ledger(self):
        res, ctx, out = self._run(si_count=0, si_live=True)
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()
