#!/usr/bin/env python3
"""serving_census_check(): a Search Console impression credited to a URL Google
says it has never indexed is not that page ranking.

Shipped 2026-10-10. The brand split added on 2026-09-12 argued the sitelink
case from query data — zero clicks, position 1.1, the site's own name. That is
inference: a page genuinely ranking #1 for the brand reads identically. This
cross-check argues it from the URL Inspection census instead, which knows
nothing about queries, and the three ways it could go wrong are all ways of
over-claiming:

  * calling a page contradicted on a census verdict older than the Search
    Console window, when the page could have been indexed then and dropped since;
  * calling a page contradicted because it is missing from the census sample,
    which is 442 of 1,704 advertised URLs and silent about the rest;
  * returning a confident zero when index_status.json could not be read at all.

Each of those has its own test below.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import searchconsole as sc  # noqa: E402

WINDOW_END = "2026-10-08"

# The real 2026-10-10 reading, trimmed: the homepage, three sitelink URLs the
# census says Google has never fetched, and one it crawled in July and declined.
PAGES = [
    {"url": "https://findacrib.com/", "clicks": 148, "impressions": 201, "position": 1.9},
    {"url": "https://findacrib.com/dc/", "clicks": 0, "impressions": 106, "position": 1.0},
    {"url": "https://findacrib.com/la/", "clicks": 0, "impressions": 106, "position": 1.0},
    {"url": "https://findacrib.com/marketing-agents/", "clicks": 0,
     "impressions": 135, "position": 1.1},
    {"url": "https://findacrib.com/sf/", "clicks": 0, "impressions": 135, "position": 1.1},
    {"url": "https://findacrib.com/alerts/?src=menu", "clicks": 0,
     "impressions": 135, "position": 1.1},
]

COHORT = {
    "https://findacrib.com/": {
        "bucket": "indexed", "checked": "2026-10-09", "crawled": "2026-10-08",
        "state": "Submitted and indexed"},
    "https://findacrib.com/dc/": {
        "bucket": "unknown_to_google", "checked": "2026-10-10", "crawled": None,
        "state": "URL is unknown to Google"},
    "https://findacrib.com/la/": {
        "bucket": "unknown_to_google", "checked": "2026-10-10", "crawled": None,
        "state": "URL is unknown to Google"},
    "https://findacrib.com/marketing-agents/": {
        "bucket": "unknown_to_google", "checked": "2026-10-09", "crawled": None,
        "state": "URL is unknown to Google"},
    "https://findacrib.com/sf/": {
        "bucket": "crawled_not_indexed", "checked": "2026-10-10",
        "crawled": "2026-07-28", "state": "Crawled - currently not indexed"},
    # /alerts/?src=menu is deliberately absent: no sitemap carries a tracking
    # parameter, so the cohort cannot hold that URL and must not guess.
}


class ServingCensusCheck(unittest.TestCase):

    def check(self, pages=None, cohort=None, end=WINDOW_END):
        return sc.serving_census_check(pages if pages is not None else PAGES,
                                       cohort=COHORT if cohort is None else cohort,
                                       window_end=end)

    # ---------------------------------------------------------- the real split
    def test_the_real_reading(self):
        out = self.check()
        self.assertEqual(out[sc.CENSUS_INDEXED], 1)
        self.assertEqual(out[sc.CENSUS_CONTRADICTED], 4)
        self.assertEqual(out[sc.CENSUS_STALE], 0)
        self.assertEqual(out[sc.CENSUS_UNSAMPLED], 1)

    def test_the_four_classes_sum_to_the_serving_count(self):
        """The invariant serving_brand_split() holds, for the same reason: a
        split that does not sum can lose a page without anyone noticing."""
        out = self.check()
        self.assertEqual(
            sum(out[k] for k in (sc.CENSUS_INDEXED, sc.CENSUS_CONTRADICTED,
                                 sc.CENSUS_STALE, sc.CENSUS_UNSAMPLED)),
            len(PAGES))

    def test_the_homepage_is_the_indexed_one(self):
        out = self.check()
        self.assertNotIn("https://findacrib.com/",
                         [u["url"] for u in out["contradicted_urls"]])

    def test_contradicted_urls_carry_their_evidence(self):
        """The report names these URLs, so each one has to carry the state and
        the inspection date that justify naming it."""
        out = self.check()
        self.assertEqual(len(out["contradicted_urls"]), 4)
        for u in out["contradicted_urls"]:
            self.assertTrue(u["state"])
            self.assertTrue(u["checked"] >= WINDOW_END)
            self.assertEqual(u["clicks"], 0)
        # Sorted by impressions so the report's first five are the biggest.
        imps = [u["impressions"] for u in out["contradicted_urls"]]
        self.assertEqual(imps, sorted(imps, reverse=True))

    # ------------------------------------------------- the three over-claims
    def test_a_census_verdict_older_than_the_window_is_stale_not_proof(self):
        """A "not indexed" stamped before the window closed cannot contradict
        impressions earned during it — the page could have been dropped after."""
        cohort = dict(COHORT)
        cohort["https://findacrib.com/dc/"] = dict(
            cohort["https://findacrib.com/dc/"], checked="2026-09-01")
        out = self.check(cohort=cohort)
        self.assertEqual(out[sc.CENSUS_STALE], 1)
        self.assertEqual(out[sc.CENSUS_CONTRADICTED], 3)
        self.assertNotIn("https://findacrib.com/dc/",
                         [u["url"] for u in out["contradicted_urls"]])

    def test_a_verdict_dated_exactly_the_window_end_still_counts(self):
        """The boundary: the census looked on the last day of the window, so
        its answer describes the window. Inclusive on purpose."""
        cohort = dict(COHORT)
        cohort["https://findacrib.com/dc/"] = dict(
            cohort["https://findacrib.com/dc/"], checked=WINDOW_END)
        self.assertEqual(self.check(cohort=cohort)[sc.CENSUS_CONTRADICTED], 4)

    def test_missing_from_the_cohort_is_unsampled_never_contradicted(self):
        """The census samples 442 of 1,704 advertised URLs. Absence from a
        sample is not a verdict, and reading it as one would turn every
        building page that ever serves into fake evidence of a sitelink."""
        out = self.check(cohort={"https://findacrib.com/": COHORT["https://findacrib.com/"]})
        self.assertEqual(out[sc.CENSUS_UNSAMPLED], 5)
        self.assertEqual(out[sc.CENSUS_CONTRADICTED], 0)

    def test_a_cohort_row_with_no_inspection_yet_is_unsampled(self):
        """A URL topped into the cohort but not yet inspected carries no
        bucket and no checked date — it is queued, not judged."""
        cohort = dict(COHORT)
        cohort["https://findacrib.com/dc/"] = {}
        out = self.check(cohort=cohort)
        self.assertEqual(out[sc.CENSUS_UNSAMPLED], 2)
        self.assertEqual(out[sc.CENSUS_CONTRADICTED], 3)

    def test_an_unreadable_census_is_none_not_zero(self):
        """ledger reads a missing row as "not measured". A confident zero here
        would say "nothing is contradicted" on a night the file failed to load."""
        self.assertIsNone(self.check(cohort={}))
        self.assertIsNone(self.check(cohort=None if False else {}))
        self.assertIsNone(sc.serving_census_check([], cohort=COHORT))

    def test_no_window_end_means_no_freshness_test_can_be_applied(self):
        """Without a window end there is nothing to compare `checked` against.
        Every not-indexed verdict then counts, which is the only option left —
        and _save_pages always writes the window, so this is the degraded path."""
        out = self.check(end=None)
        self.assertEqual(out[sc.CENSUS_CONTRADICTED], 4)
        self.assertEqual(out[sc.CENSUS_STALE], 0)

    # ----------------------------------------------------------- URL matching
    def test_a_tracking_parameter_falls_back_to_the_bare_url(self):
        """/alerts/?src=menu is how the site's own nav links to /alerts/. If
        the sitemap-built cohort holds the bare URL, the join should find it."""
        cohort = dict(COHORT)
        cohort["https://findacrib.com/alerts/"] = {
            "bucket": "unknown_to_google", "checked": "2026-10-10",
            "state": "URL is unknown to Google"}
        out = self.check(cohort=cohort)
        self.assertEqual(out[sc.CENSUS_CONTRADICTED], 5)
        self.assertEqual(out[sc.CENSUS_UNSAMPLED], 0)

    def test_the_exact_url_wins_over_the_bare_one(self):
        """?src=menu and the bare path are different URLs to Google. When the
        cohort happens to hold both, the exact match is the right answer."""
        cohort = dict(COHORT)
        cohort["https://findacrib.com/alerts/?src=menu"] = {
            "bucket": "indexed", "checked": "2026-10-10",
            "state": "Submitted and indexed"}
        cohort["https://findacrib.com/alerts/"] = {
            "bucket": "unknown_to_google", "checked": "2026-10-10",
            "state": "URL is unknown to Google"}
        out = self.check(cohort=cohort)
        self.assertEqual(out[sc.CENSUS_INDEXED], 2)

    def test_bare_url_strips_query_and_fragment(self):
        self.assertEqual(sc._bare_url("https://x/a/?b=c#d"), "https://x/a/")
        self.assertEqual(sc._bare_url("https://x/a/"), "https://x/a/")
        self.assertEqual(sc._bare_url(None), "")

    # ------------------------------------------- against the committed files
    def test_saved_reading_matches_the_committed_snapshot(self):
        """The 6am review and the report both read this without a token, off
        growth/gsc_pages.json and growth/index_status.json. Skips in a clone
        that carries neither."""
        try:
            out = sc.saved_serving_census_check()
        except Exception as e:                       # pragma: no cover
            self.skipTest(f"snapshot unreadable: {e}")
        if out is None:
            self.skipTest("no serving pages in the committed snapshot")
        snap = sc.load_pages() or {}
        self.assertEqual(
            sum(out[k] for k in (sc.CENSUS_INDEXED, sc.CENSUS_CONTRADICTED,
                                 sc.CENSUS_STALE, sc.CENSUS_UNSAMPLED)),
            len(snap.get("pages") or []))
        for u in out["contradicted_urls"]:
            self.assertNotEqual(u["state"], "Submitted and indexed")


if __name__ == "__main__":
    unittest.main()
