#!/usr/bin/env python3
"""A <lastmod> audit must tell a shared-string restamp from a tier rewrite.

t_lastmod_integrity failed anything over LASTMOD_RESTAMP_PCT of the advertised
corpus dated today, on the argument that no honest change can move that many
pages in one night. On 2026-10-12 that argument met a counter-example the loop
had built on purpose: the night before added a visible FAQ block to the building
tier, pre-registered a ~670-URL restamp radius in the journal, and the audit
read 866 of 1,704 (50.8%) and announced

    "RESTAMP: above 50% this is a shared string that got edited, not 866 pages
     that changed ... move it into build_seo.PAGE_CHROME"

which was false in its diagnosis and actively harmful in its remedy: moving a
real content change into PAGE_CHROME hides it from every crawler, and the
pages genuinely had changed.

The discriminator is SHAPE, not size. A string in page() reaches every tier by
construction, and both recorded restamps did exactly that (47,596 of 47,596 on
2026-08-18; 4,082 of 4,105 on 2026-10-06). A tier rewrite cannot: the 10-11
change restamped 670 URLs and every one was a building page.

So: broad stays red with the PAGE_CHROME remedy, concentrated goes green and
says it is a tier-wide change. Each failure mode below is a way of getting that
call wrong — going green on a real restamp, going red on a real change, or
deciding the shape from tiers too small to carry a share.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import ledger, techniques as T  # noqa: E402

TODAY = ledger.today()
OLD = "2026-09-01"

# The advertised corpus MODELLED on the 2026-10-12 sitemaps: every tier that
# reading named, at the per-shard counts last_run.json recorded for it. The total
# is 1,874 rather than the 1,704 that reading audited, because the five borough
# shards are named by borough and not by URL tier, so how many of their URLs are
# building pages and how many are hubs is not recoverable from this checkout.
# That does not matter to anything under test: this audit decides on SHARES, and
# the shares here are the real ones to within a few points. Only the counts
# matter, so the URLs themselves are generated.
CORPUS = {
    "building": 1053,
    "landlord": 301,
    "dc/neighborhood": 103,
    "la/zip": 112,
    "neighborhood": 198,
    "council-district": 52,
    "sf/neighborhood": 37,
    "guide": 12,          # below LASTMOD_TIER_FLOOR — must not vote on the shape
    "section8": 6,        # below the floor, and 6 of 6 dated today every night
}


def write_corpus(root, dated_today):
    """One sitemap index and one shard per tier. `dated_today` maps tier -> n."""
    shards = []
    for tier, total in CORPUS.items():
        name = "sitemap-%s.xml" % tier.replace("/", "-")
        fresh = dated_today.get(tier, 0)
        urls = []
        for i in range(total):
            lm = TODAY if i < fresh else OLD
            urls.append(f"<url><loc>https://findacrib.com/{tier}/p{i}/</loc>"
                        f"<lastmod>{lm}</lastmod></url>")
        with open(os.path.join(root, name), "w") as f:
            f.write("<urlset>" + "".join(urls) + "</urlset>")
        shards.append(name)
    with open(os.path.join(root, "sitemap.xml"), "w") as f:
        f.write("<sitemapindex>" + "".join(
            f"<sitemap><loc>https://findacrib.com/{s}</loc></sitemap>" for s in shards)
            + "</sitemapindex>")


def audit(dated_today):
    root = tempfile.mkdtemp()
    try:
        write_corpus(root, dated_today)
        ctx = T.Context(build_dir=root, docroot=root, dry_run=True, log=lambda *a, **k: None)
        return T.t_lastmod_integrity(ctx)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def everything():
    """The 2026-10-06 shape: a string in page(), so every tier at once."""
    return {t: n for t, n in CORPUS.items()}


class SharedStringStillFails(unittest.TestCase):
    """The defect class this audit exists for. Red, with the one remedy."""

    def setUp(self):
        self.r = audit(everything())

    def test_fails(self):
        self.assertFalse(self.r["ok"])

    def test_says_restamp_and_names_the_remedy(self):
        self.assertIn("RESTAMP", self.r["detail"])
        self.assertIn("PAGE_CHROME", self.r["detail"])

    def test_does_not_call_it_a_tier_wide_change(self):
        self.assertNotIn("TIER-WIDE CHANGE", self.r["detail"])
        self.assertNotIn("tier_wide", self.r)

    def test_counts_the_lit_tiers_as_evidence(self):
        # 7 of the 9 tiers are above the 20-URL floor; all 7 are lit.
        self.assertEqual(self.r["tiers_measurable"], 7)
        self.assertEqual(self.r["tiers_lit"], 7)

    def test_a_restamp_that_misses_one_tier_is_still_a_restamp(self):
        # "Most of the measurable tiers", not all: a tier that happened not to
        # be rebuilt tonight must not drag the audit to green.
        partial = everything()
        partial["landlord"] = 0
        partial["council-district"] = 0
        r = audit(partial)
        self.assertFalse(r["ok"])
        self.assertIn("RESTAMP", r["detail"])


class TierRewriteGoesGreen(unittest.TestCase):
    """The 2026-10-12 counter-example: 866 of 1,704, all of it one tier."""

    def setUp(self):
        # 670 building pages from the FAQ change, plus the ordinary nightly
        # 147-277 spread over the two tiers that carry daily feeds. 51.6% of
        # this corpus, which is the real reading's 50.8% to within a point.
        self.r = audit({"building": 870, "landlord": 97})

    def test_over_the_share_threshold(self):
        # The premise of the test: without the shape test this reading failed.
        self.assertGreater(self.r["pct_today"], T.LASTMOD_RESTAMP_PCT)

    def test_passes(self):
        self.assertTrue(self.r["ok"])
        self.assertTrue(self.r["tier_wide"])

    def test_says_what_it_is_and_that_there_is_nothing_to_fix(self):
        self.assertIn("TIER-WIDE CHANGE", self.r["detail"])
        self.assertIn("nothing to fix", self.r["detail"])

    def test_never_offers_the_page_chrome_remedy_for_a_true_date(self):
        # The harmful half of the old behaviour: following this remedy on a real
        # content change hides it from every crawler.
        self.assertNotIn("PAGE_CHROME", self.r["detail"])
        self.assertNotIn("RESTAMP", self.r["detail"])

    def test_names_the_tier_and_its_share(self):
        self.assertIn("building/", self.r["detail"])
        self.assertIn("870 of 1,053", self.r["detail"])

    def test_the_numbers_survive_into_the_ledger_record(self):
        # 2026-10-06's lesson was that an unrecorded restamp is invisible for
        # days. Green must not mean unreported.
        self.assertEqual(self.r["dated_today"], 967)
        self.assertEqual(self.r["tiers_lit"], 1)
        self.assertEqual(self.r["lit_tiers"], ["building/"])


class SmallTiersDoNotVote(unittest.TestCase):
    def test_tiers_below_the_floor_are_not_measurable(self):
        # /section8/ is 6 of 6 dated today every single night and /guide/ is 12.
        # If either voted, two tiers of the nine would be permanently lit and
        # the shape test would read the corpus as broader than it is.
        r = audit({"building": 870, "landlord": 97})
        self.assertEqual(r["tiers_measurable"], 7)

    def test_a_small_tier_cannot_turn_a_tier_rewrite_red(self):
        rewrite = {"building": 870, "landlord": 97}
        with_small = dict(rewrite, section8=6, guide=12)
        self.assertTrue(audit(with_small)["ok"])
        self.assertEqual(audit(with_small)["tiers_lit"], audit(rewrite)["tiers_lit"])


class OrdinaryNightsAreQuiet(unittest.TestCase):
    def test_below_the_threshold_nothing_is_claimed_either_way(self):
        # 2026-10-11: 148 of 1,704, 8.7%. No shape line, no verdict, no noise.
        r = audit({"building": 100, "landlord": 48, "section8": 6})
        self.assertTrue(r["ok"])
        self.assertNotIn("RESTAMP", r["detail"])
        self.assertNotIn("TIER-WIDE CHANGE", r["detail"])
        self.assertNotIn("by tier", r["detail"])

    def test_the_share_is_still_reported_every_night(self):
        r = audit({"building": 100, "landlord": 48, "section8": 6})
        self.assertIn("of 1,874 advertised URLs", r["detail"])
        self.assertEqual(r["dated_today"], 154)


class BareCheckoutSaysSo(unittest.TestCase):
    def test_no_sitemap_is_not_audited(self):
        root = tempfile.mkdtemp()
        try:
            ctx = T.Context(build_dir=root, docroot=root, dry_run=True,
                            log=lambda *a, **k: None)
            r = T.t_lastmod_integrity(ctx)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertTrue(r["ok"])
        self.assertIn("NOT AUDITED", r["detail"])


class LocPath(unittest.TestCase):
    """The scheme and host have to come off, or every URL is one tier."""

    def test_absolute(self):
        self.assertEqual(T._loc_path("https://findacrib.com/building/x/"), "/building/x/")

    def test_tier_of_an_absolute_loc(self):
        self.assertEqual(T._frozen_tier(T._loc_path(
            "https://findacrib.com/building/queens/1-main-st-4051860029/")), "building/")

    def test_city_hubs_keep_two_segments(self):
        # /sf/ is the app shell and /sf/neighborhood/ is a generated tier; a
        # restamp in one says nothing about the other.
        self.assertEqual(T._frozen_tier(T._loc_path(
            "https://findacrib.com/sf/neighborhood/mission/")), "sf/neighborhood/")

    def test_host_root(self):
        self.assertEqual(T._loc_path("https://findacrib.com"), "/")
        self.assertEqual(T._loc_path("https://findacrib.com/"), "/")

    def test_relative_is_passed_through(self):
        self.assertEqual(T._loc_path("/building/x/"), "/building/x/")
        self.assertEqual(T._loc_path("building/x/"), "/building/x/")


if __name__ == "__main__":
    unittest.main()
