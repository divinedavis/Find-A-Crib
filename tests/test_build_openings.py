#!/usr/bin/env python3
"""Unit tests for build_openings.py — openings outside New York. No network.

    python3 tests/test_build_openings.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_openings as O  # noqa: E402

TODAY = "2026-09-24"


class Build(unittest.TestCase):
    def test_closed_dropped_undated_kept(self):
        good = lambda: [{"src": "A", "id": "1", "closes": "2026-09-23"}, {"src": "A", "id": "2", "closes": "2026-09-24"},
                        {"src": "A", "id": "3"}]
        got, status = O.build(None, {"A": good}, TODAY)
        self.assertEqual([o["id"] for o in got], ["2", "3"], "closed yesterday dropped; today and undated kept")
        self.assertTrue(status["A"]["ok"])

    def test_failed_source_keeps_its_last_openings_only(self):
        prev = {"openings": [{"src": "B", "id": "old", "closes": "2026-10-01"},
                             {"src": "B", "id": "gone", "closes": "2026-09-01"},
                             {"src": "A", "id": "a-old"}]}
        def boom(): raise OSError("down")
        got, status = O.build(prev, {"A": lambda: [{"src": "A", "id": "a-new"}], "B": boom}, TODAY)
        self.assertEqual(sorted(o["id"] for o in got), ["a-new", "old"], "B keeps its still-open rows; A is replaced")
        self.assertFalse(status["B"]["ok"])

    def test_bloom_row(self):
        item = {"id": "x1", "status": "active", "name": "2137 Dwight", "reviewOrderType": "waitlistLottery",
                "applicationDueDate": "2026-09-26T00:00:00.000Z", "unitsAvailable": 6, "urlSlug": "slug",
                "listingsBuildingAddress": {"city": "berkeley", "state": "CA", "street": "2137 Dwight Way", "zipCode": "94704",
                                            "latitude": 37.86, "longitude": -122.27},
                "unitsSummarized": {"byUnitTypeAndRent": [
                    {"unitTypes": {"name": "twoBdrm", "numBedrooms": 2}, "rentRange": {"min": "$1,340", "max": "$2,066"},
                     "minIncomeRange": {"min": "$4,020"}},
                    {"unitTypes": {"name": "studio"}, "rentRange": {"min": "t.n/a", "max": "t.n/a"}, "minIncomeRange": {"min": "$0"}}]}}
        closed = dict(item, id="x2", status="closed")
        [o] = O.bloom([item, closed], "https://housingbayarea.mtc.ca.gov", "Doorway Bay Area")
        self.assertEqual((o["kind"], o["closes"], o["city"], o["beds"]), ("lottery", "2026-09-26", "Berkeley", ["Studio", "2-bed"]))
        self.assertEqual((o["rent_low"], o["rent_high"], o["income_min_mo"]), (1340, 2066, 4020))
        self.assertNotIn("income_min", o, "Bloom's figure is monthly and must not pass as yearly")
        self.assertEqual(o["href"], "https://housingbayarea.mtc.ca.gov/listing/x1/slug")

    def test_money_and_day(self):
        self.assertEqual(O.money("$1,900"), 1900); self.assertIsNone(O.money("t.n/a")); self.assertIsNone(O.money(0))
        self.assertEqual(O.day("2026-10-16T00:00:00.000+0000"), "2026-10-16"); self.assertIsNone(O.day(None))


if __name__ == "__main__":
    unittest.main()
