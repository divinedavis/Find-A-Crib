#!/usr/bin/env python3
"""Unit tests for build_affordable_cities.py — Chicago, Miami, Atlanta, Philadelphia. No network.

    python3 tests/test_build_affordable_cities.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_affordable_cities as C  # noqa: E402


class Merge(unittest.TestCase):
    def test_same_address_two_spellings_is_one_building(self):
        rows = [
            {"src": "ARO", "name": "Hairpin Lofts", "addr": "3414 W. Diversey Avenue", "zip": "60647", "lat": 41.93207, "lng": -87.71287,
             "li": 5, "tel": "773-292-6360", "prog": ["ARO"]},
            {"src": "tax credit", "name": "Hairpin Lofts", "addr": "3414 WEST DIVERSEY AVE", "zip": "60647", "lat": 41.93210, "lng": -87.71290,
             "units": 25, "li": 20, "mix": {"1": 10}, "prog": ["Low-Income Housing Tax Credit"]},
        ]
        [m] = C.merge(rows)
        self.assertEqual((m["tel"], m["units"], m["li"], m["mix"]), ("773-292-6360", 25, 20, {"1": 10}),
                         "first source's phone kept, larger unit counts win, missing fields filled")
        self.assertEqual(m["prog"], ["ARO", "Low-Income Housing Tax Credit"])

    def test_same_name_nearby_merges_far_apart_does_not(self):
        base = {"src": "a", "name": "Rosa Parks Apts.", "addr": "1 A ST", "zip": "60601", "lat": 41.9, "lng": -87.7, "prog": ["a"]}
        near = dict(base, addr="99 B ST", lat=41.9005, prog=["b"])          # ~55 m
        far = dict(base, addr="500 C ST", lat=41.91, prog=["c"])            # ~1.1 km: another site
        out = C.merge([base, near, far])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["prog"], ["a", "b"])

    def test_bbox_and_bad_points_dropped(self):
        rows = [{"addr": "1 A ST", "lat": 25.7, "lng": -80.2}, {"addr": "2 B ST", "lat": 27.9, "lng": -82.4},
                {"addr": "3 C ST", "lat": 0, "lng": 0}, {"addr": "4 D ST", "lat": None, "lng": None}]
        self.assertEqual([r["addr"] for r in C.merge(rows, (25.13, 25.98, -80.88, -80.11))], ["1 A ST"])

    def test_address_helpers(self):
        self.assertEqual(C.addr_key("15-17 Lincoln Park Street", "7102"), ("15", "LINCOLN PARK ST", "07102"))
        self.assertIsNone(C.addr_key("Scattered sites", "60601"))
        self.assertEqual(C.split_city_zip("835 OGLETHORPE AVE SW, ATLANTA, GA 30310"), ("835 OGLETHORPE AVE SW", "30310"))
        self.assertEqual(C.fmt_ami([("50%", 43), ("60%", None), ("80%", 44)]), "43 at 50% AMI · 44 at 80% AMI")

    def test_rows_fill_zip_from_neighbour_and_ids_unique(self):
        merged = [{"addr": "1 A ST", "zip": "19133", "lat": 40.0, "lng": -75.13, "name": "A", "prog": ["x"]},
                  {"addr": "9 B ST", "zip": None, "lat": 40.001, "lng": -75.13, "name": "B", "prog": ["x"], "pis": 2011}]
        slim, recs = C.rows_for("phl", merged)
        self.assertEqual([r["z"] for r in slim], ["19133", "19133"], "no ZIP: the nearest building's (~110 m)")
        self.assertEqual(len({r["bbl"] for r in slim}), 2)
        self.assertTrue(all(r["bbl"].startswith("PHL-") for r in slim))
        self.assertEqual(slim[1]["yr"], 2011)


if __name__ == "__main__":
    unittest.main()
