"""scripts/ship_summary.py: the one-line account of a ship."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import ship_summary as s  # noqa: E402

T = 1_800_000_000
EVENTS = [
    (T, "note", ["tier=fast"]),
    (T, "stage", ["checks"]),
    (T + 2, "mem", ["8.0", "1600"]),
    (T + 6, "stage", ["catalog"]),
    (T + 6, "note", ["catalog=droplet"]),
    (T + 10, "mem", ["8.1", "1600"]),
    (T + 40, "mem", ["11.9", "1650"]),
    (T + 66, "stage", ["smoke test"]),
    (T + 1266, "ramwait", ["1200"]),          # logged when the wait ends
    (T + 1270, "mem", ["9.0", "1700"]),
    (T + 1300, "mem", ["12.5", "2100"]),
    (T + 1400, "stage", ["archive"]),
    (T + 1400, "note", ["build=180"]),
    (T + 1410, "mem", ["10.0", "1700"]),
]


class Summary(unittest.TestCase):
    def setUp(self):
        self.s = s.summarise(EVENTS, 0, T + 1465)

    def test_stage_times_run_to_the_next_stage_and_the_end(self):
        got = {st["name"]: st["seconds"] for st in self.s["stages"]}
        self.assertEqual(got, {"checks": 6, "catalog": 60, "smoke test": 1334, "archive": 65})
        self.assertEqual(self.s["total"], 1465)

    def test_memory_wait_is_counted_once_in_its_own_stage(self):
        waits = {st["name"]: st["ram_wait"] for st in self.s["stages"]}
        self.assertEqual(waits, {"checks": 0, "catalog": 0, "smoke test": 1200, "archive": 0})
        self.assertEqual(self.s["ram_wait"], 1200)

    def test_a_stage_rise_is_its_peak_over_where_its_work_began(self):
        by = {st["name"]: st for st in self.s["stages"]}
        self.assertEqual((by["catalog"]["peak_gb"], by["catalog"]["rise_gb"]), (11.9, 3.8))
        # The smoke stage's base is the first sample after its wait, not the
        # catalog stage's leftovers.
        self.assertEqual((by["smoke test"]["peak_gb"], by["smoke test"]["rise_gb"]), (12.5, 3.5))
        self.assertEqual((self.s["peak_gb"], self.s["swap_mb"]), (12.5, 2100))

    def test_the_line_names_result_build_tier_catalog_and_waits(self):
        line = s.line(self.s)
        self.assertTrue(line.startswith("SHIP SUMMARY ok build=180 tier=fast catalog=droplet total=24:25 ram-wait=20:00 peak=12.5GB"))
        self.assertIn("| smoke test 22:14 (20:00 waiting for memory, +3.5GB to 12.5)", line)
        self.assertIn("| checks 0:06 |", line)
        self.assertNotIn("\n", line)

    def test_a_failed_ship_says_so(self):
        self.assertTrue(s.line(s.summarise(EVENTS, 65, T + 1465)).startswith("SHIP SUMMARY FAILED(65) "))

    def test_reads_the_events_file_skips_junk_and_appends_history(self):
        with tempfile.TemporaryDirectory() as d:
            events, history = os.path.join(d, "events.tsv"), os.path.join(d, "history.jsonl")
            with open(events, "w") as f:
                for at, kind, rest in EVENTS:
                    f.write("\t".join([str(at), kind, *rest]) + "\n")
                f.write("not a line\n\tbroken\n")
            for _ in range(2):
                self.assertEqual(s.main([events, "--result", "0", "--history", history, "--now", str(T + 1465)]), 0)
            rows = [json.loads(line) for line in open(history)]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["notes"]["build"], "180")

    def test_trouble_never_fails_the_ship(self):
        self.assertEqual(s.main(["/nonexistent/events.tsv"]), 0)
        self.assertEqual(s.line(s.summarise([], 0, T))[:15], "SHIP SUMMARY ok")


if __name__ == "__main__":
    unittest.main()
