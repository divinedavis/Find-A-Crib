"""Pest counts (h.pe) for the No pests filter (owner, 2026-10-24): the nightly
refresh banks them, the boot split keeps them, and a building whose pests
age out loses the count instead of keeping a stale one."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_hpd  # noqa: E402
import refresh_hpd_counts  # noqa: E402
import split_hpd  # noqa: E402


class PestCounts(unittest.TestCase):
    def test_merge_sets_updates_and_clears_pe(self):
        recs = [{"bbl": "1"}, {"bbl": "2", "h": {"pe": 3}}, {"bbl": "3", "h": {"pe": 1}}]
        moved = refresh_hpd_counts.merge(recs, {}, {}, {"1": 2, "2": 4})
        self.assertEqual(recs[0]["h"]["pe"], 2, "a building that gained pests gets a count")
        self.assertEqual(recs[1]["h"]["pe"], 4, "a count that moved is updated")
        self.assertNotIn("pe", recs[2]["h"], "pests that aged out leave no stale count")
        self.assertEqual(moved["pests"], 3)

    def test_merge_without_pests_leaves_pe_alone(self):
        recs = [{"bbl": "2", "h": {"pe": 3}}]
        refresh_hpd_counts.merge(recs, {}, {})
        self.assertEqual(recs[0]["h"]["pe"], 3)

    def test_boot_split_keeps_pe(self):
        self.assertEqual(split_hpd.slim_h({"pe": 2})["pe"], 2, "the filter reads pe from the boot file")
        self.assertNotIn("pe", split_hpd.slim_h({"violations": {"open": 1}}))

    def test_pest_rule_matches_the_app(self):
        # Inspector citations only, not the annual bedbug paperwork notice.
        self.assertIn("CONSISTING OF", fetch_hpd.PEST_WHERE)
        for pest in ("ROACH", "MICE", "RATS", "BEDBUG"):
            self.assertIn(pest, fetch_hpd.PEST_WHERE)


if __name__ == "__main__":
    unittest.main()
