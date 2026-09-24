#!/usr/bin/env python3
"""Unit tests for build_lihtc_states.py — the per-state income-restricted maps. No network.

    python3 tests/test_build_lihtc_states.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_lihtc_states as L  # noqa: E402


def feat(hid, yr="2012", x=-74.1, y=40.7, **a):
    base = {"HUD_ID": hid, "PROJECT": "LITC#0755 FRANKLIN SENIOR HOUSING", "PROJ_ADD": "1 mill st",
            "PROJ_CTY": "NEWARK CITY", "PROJ_ST": "NJ", "PROJ_ZIP": "7102", "N_UNITS": 95, "LI_UNITS": 90,
            "N_0BR": 0, "N_1BR": 40, "N_2BR": 50, "N_3BR": 0, "N_4BR": 0, "INC_CEIL": "2", "YR_PIS": yr,
            "TRGT_ELD": "1", "TRGT_FAM": "2"}
    base.update(a)
    return {"attributes": base, "geometry": {"x": x, "y": y} if x is not None else {}}


class Rows(unittest.TestCase):
    def test_row_and_record(self):
        slim, recs, _ = L.rows_for([feat("NJA20120412")])
        r = slim[0]
        self.assertEqual((r["bbl"], r["b"], r["a"], r["z"], r["nb"], r["yr"], r["u"]),
                         ("LIHTC-NJA20120412", "NJ", "1 MILL ST", "07102", "Newark City", 2012, 95))
        rec = recs["LIHTC-NJA20120412"]
        self.assertEqual(rec["name"], "Franklin Senior Housing", "the allocation-number prefix is dropped")
        self.assertEqual(rec["mix"], {"1": 40, "2": 50})
        self.assertEqual(rec["inc"], "60% of area median income")
        self.assertEqual(rec["serves"], ["seniors"])
        self.assertNotIn("contact", rec, "no individual's name is published")

    def test_pre_1990_and_pointless_rows_dropped_unknown_year_kept(self):
        slim, _, skipped = L.rows_for([feat("A", yr="1988"), feat("B", x=None), feat("C", yr="8888")])
        self.assertEqual([r["bbl"] for r in slim], ["LIHTC-C"])
        self.assertNotIn("yr", slim[0], "8888 means unknown, not a year")
        self.assertEqual((skipped["old"], skipped["nopoint"]), (1, 1))

    def test_contact_merge_needs_matching_words(self):
        good = {L.hud_key("NJA2012412"): ("ACME HOUSING LLC", "Jane Doe", "(609) 656-4205", L.words("FRANKLIN SENIOR", "1 MILL ST"))}
        _, recs, _ = L.rows_for([feat("NJA20120412")], good)
        self.assertEqual((recs["LIHTC-NJA20120412"]["mgr"], recs["LIHTC-NJA20120412"]["tel"]), ("Acme Housing Llc", "609-656-4205"))
        bad = {L.hud_key("NJA2012412"): ("OTHER LP", None, "609-000-0000", L.words("AKABE VILLAGE", "57 WYCKOFF ROAD"))}
        _, recs, _ = L.rows_for([feat("NJA20120412")], bad)
        self.assertNotIn("tel", recs["LIHTC-NJA20120412"], "an id match on a different development is ignored")

    def test_hud_key_bridges_padding(self):
        self.assertEqual(L.hud_key("NJA2012412"), L.hud_key("NJA20120412"))
        self.assertEqual(L.hud_key("NJA0000X041"), ("NJA", "0000", "X041"))

    def test_phone(self):
        self.assertEqual(L.phone("1 (516) 487-5444"), "516-487-5444")
        self.assertIsNone(L.phone(" "))


if __name__ == "__main__":
    unittest.main()
