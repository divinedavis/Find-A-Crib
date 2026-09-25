#!/usr/bin/env python3
"""Unit tests for scrape_nj_lotteries.py — the Lotteries tab's NJ pane. No network.

    python3 tests/test_scrape_nj_lotteries.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scrape_nj_lotteries as N  # noqa: E402

# The live box as of 2026-09-24, trimmed.
PAGE = """<h3 class="widget-title">WHAT&#8217;S NEW?</h3><div class="textwidget">
<p><span data-contrast="auto"><strong>RENTALS:</strong>  Join the following waiting lists</span></p>
<ul><li><span class="css-13whmom">Washington Township &#8211; Bergen by 9/28/2026</span></li>
<li>South Brunswick by 10/5/2026</li><li>Paramus Rental by 11/19/2026</li></ul>
<p><span><strong>SALES:</strong>  Join the following waiting lists</span></p>
<ul><li>Wayne &#8211; COMING SOON</li><li>Wall by 9/21/2026</li><li>Something odd</li></ul>"""

MUNIS = {"washington township": ["Bergen", "Gloucester", "Morris", "Warren"],
         "south brunswick township": ["Middlesex"], "paramus borough": ["Bergen"],
         "wayne township": ["Passaic"], "wall township": ["Monmouth"]}


class Parse(unittest.TestCase):
    def setUp(self):
        links = {"paramus": {"tenure": "rent", "lid": "a0JUq000008DDFlMAO", "development": "Vermella Paramus"},
                 "wall": {"tenure": "rent", "lid": "WRONGTENURE"}}
        self.items = {i["id"]: i for i in N.parse(PAGE, MUNIS, links)}

    def test_every_item_parsed_and_odd_one_skipped(self):
        self.assertEqual(sorted(self.items), ["buy-wall", "buy-wayne", "rent-paramus",
                                              "rent-south-brunswick", "rent-washington-township-bergen"])

    def test_tenure_and_dates(self):
        self.assertEqual(self.items["rent-south-brunswick"]["tenure"], "rent")
        self.assertEqual(self.items["rent-south-brunswick"]["closes"], "2026-10-05")
        self.assertEqual(self.items["buy-wall"]["tenure"], "buy")

    def test_coming_soon_has_no_date(self):
        w = self.items["buy-wayne"]
        self.assertTrue(w["coming_soon"]); self.assertIsNone(w["closes"])
        self.assertEqual(w["county"], "Passaic")

    def test_county_hint_resolves_ambiguous_town(self):
        w = self.items["rent-washington-township-bergen"]
        self.assertEqual((w["town"], w["county"], w["region"]), ("Washington Township", "Bergen", 1))

    def test_rental_word_dropped_from_town(self):
        self.assertEqual(self.items["rent-paramus"]["town"], "Paramus")

    def test_ambiguous_town_without_hint_has_no_county(self):
        self.assertIsNone(N.county_for("Washington Township", "", MUNIS))

    def test_no_box_means_nothing(self):
        self.assertEqual(N.parse("<html>maintenance</html>", MUNIS, {}), [])

    def test_links_go_to_listings_never_the_home_page(self):
        p = self.items["rent-paramus"]
        self.assertEqual(p["href"], "https://www.affordablehomesnewjersey.com/rental-opportunities/current-listings/?lid=a0JUq000008DDFlMAO")
        self.assertEqual(p["development"], "Vermella Paramus")
        # no curated link: the tenure's listings page; a rent link never serves a sale
        self.assertEqual(self.items["rent-south-brunswick"]["href"], N.LISTINGS["rent"])
        self.assertEqual(self.items["buy-wall"]["href"], N.LISTINGS["buy"])
        self.assertTrue(all(i["href"] != N.URL for i in self.items.values()))

    def test_town_key(self):
        self.assertEqual(N.town_key("Washington Township – Bergen"), N.town_key("Washington Township - Bergen"))
        self.assertEqual(N.town_key("Paramus Rental"), N.town_key("Paramus Borough"))


if __name__ == "__main__":
    unittest.main()
