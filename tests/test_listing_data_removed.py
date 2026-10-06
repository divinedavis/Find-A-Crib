#!/usr/bin/env python3
"""The Zumper / StreetEasy (Apify) listing feed was dropped on 2026-10-06
(Zumper's Terms forbid scraping). These pin the server side of that removal:
no scraper scripts, no alert kind, no SEO claim and no search filter built on
listing data can quietly come back."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class ListingDataRemoved(unittest.TestCase):
    def test_scrapers_and_feed_files_are_gone(self):
        for name in ("scrape_listings.py", "fetch_apify.py", "parse_apify.py", "combine_listings.py",
                     "scripts/refresh_listings.sh", "listings.json", "build_rent_report.py",
                     "rent_check.py", "deploy/cron-rentmap-report"):
            self.assertFalse(os.path.exists(os.path.join(ROOT, name)), f"{name} is back")

    def test_cron_runs_no_portal_scrape(self):
        with open(os.path.join(ROOT, "deploy", "cron-rentmap-scrape")) as f:
            jobs = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
        self.assertTrue(jobs, "the Section 8 jobs should still be scheduled")
        for line in jobs:
            for bad in ("scrape_listings", "combine_listings", "fetch_apify", "parse_apify", "refresh_listings"):
                self.assertNotIn(bad, line)

    def test_saved_alerts_has_no_listing_kind(self):
        import saved_alerts as sa
        self.assertNotIn("zumper", sa.COOLDOWN)
        rec = {"bbl": "1000010001", "h": {"violations": {"open": 1}}, "s": [], "u": 10}
        s8 = {"avail": {}}
        snap = sa.snapshot_of(rec, s8)
        for k in ("zc", "zp", "zt"):
            self.assertNotIn(k, snap)
        prev = dict(snap)
        self.assertEqual(sa.diff_building(rec, prev, sa.snapshot_of(rec, s8), s8), [])

    def test_leftover_listing_alerts_are_purged(self):
        import saved_alerts as sa
        st = {"pending": {"u1": [
                  {"kind": "zumper", "url": "https://www.zumper.com/x", "bbl": "1"},
                  {"kind": "price", "url": "https://streeteasy.com/rental/1", "bbl": "1"},
                  {"kind": "price", "url": "https://www.affordablehousing.com/x", "bbl": "1"},
                  {"kind": "violations", "url": None, "bbl": "1"}]},
              "snap": {"1": {"vo": 1, "zc": 2, "zp": 2500, "zt": 1}}}
        sa.purge_listing_items(st)
        self.assertEqual([i["kind"] for i in st["pending"]["u1"]], ["price", "violations"])
        self.assertEqual(st["snap"]["1"], {"vo": 1})

    def test_seo_promotion_reads_no_listing_feed(self):
        import build_seo
        for gone in ("load_listings", "recently_advertised_bbls", "ever_advertised_bbls", "listings_asof"):
            self.assertFalse(hasattr(build_seo, gone), f"build_seo.{gone} is back")
        self.assertTrue(build_seo.promoted_building({"bbl": "x", "u": 10 ** 6}))
        self.assertFalse(build_seo.promoted_building({"bbl": "not-a-served-bbl", "u": 1}))
        desc = build_seo.building_meta_desc("1 Main St", "Chelsea", 40, 1920, 0)
        self.assertNotIn("advertised", desc)

    def test_plain_language_search_sets_no_listed_filter(self):
        import nl_search
        with open(nl_search.__file__) as f:
            src = f.read()
        self.assertNotIn('"listed"', src)


if __name__ == "__main__":
    unittest.main()
