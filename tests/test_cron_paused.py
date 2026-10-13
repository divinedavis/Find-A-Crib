#!/usr/bin/env python3
"""`status` must tell a deliberate pause apart from a dead cron.

2026-10-13. The owner paused Find A Crib's growth engine on 2026-10-12 (commit
7182da1, "pause seo for FAC") by prefixing every growth_run.sh cron line with
#PAUSED-20261012. The morning after, `growth_daily.py status` led with

    cron: NO RUN FOR 1.1 DAYS — cron, the host or the checkout.

which is failure-shaped and names three causes that are all wrong. The review
agent that reads that line is instructed to raise a cron-failure concern only
when the engine is genuinely stale, so the misattribution is a standing trap.

These tests pin both halves: a pause reads as a pause, and — the half that
actually protects the alarm — anything that is NOT a provable pause still reads
as staleness. A cron file that is unreadable, truncated, or empty must never be
able to silence it.
"""
from __future__ import annotations

import datetime
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import growth_daily  # noqa: E402

LIVE = """SHELL=/bin/bash
40 5 * * * scraper fac-run supabase -- /root/Find-A-Crib/growth_run.sh build --deploy
0 5 * * * scraper fac-run supabase -- /root/Find-A-Crib/growth_run.sh daily
"""

PAUSED = """SHELL=/bin/bash
#PAUSED-20261012 40 5 * * * scraper fac-run supabase -- /root/Find-A-Crib/growth_run.sh build --deploy
#PAUSED-20261012 0 5 * * * scraper fac-run supabase -- /root/Find-A-Crib/growth_run.sh daily
# PAUSED 2026-10-12 (owner: "pause seo for FAC"). To resume, drop the prefix.
"""

# The real failure mode the pause must not be allowed to impersonate.
NO_JOBS = """SHELL=/bin/bash
# every job line has been deleted or the file was truncated
"""


class PauseDetection(unittest.TestCase):
    def _cron(self, text):
        p = Path(self.tmp) / "cron-rentmap-growth"
        p.write_text(text)
        return str(p)

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_live_cron_is_not_paused(self):
        self.assertEqual(growth_daily.growth_paused(self._cron(LIVE)), (False, ""))

    def test_commented_out_cron_is_paused_and_names_the_marker(self):
        paused, marker = growth_daily.growth_paused(self._cron(PAUSED))
        self.assertTrue(paused)
        self.assertEqual(marker, "#PAUSED-20261012")

    def test_a_file_with_no_growth_run_line_is_unknown_not_paused(self):
        # The load-bearing one. If a truncated cron read as "paused", the
        # staleness alarm could be silenced by the very breakage it exists to
        # catch.
        self.assertEqual(growth_daily.growth_paused(self._cron(NO_JOBS)), (False, ""))

    def test_missing_file_is_unknown_not_paused(self):
        self.assertEqual(
            growth_daily.growth_paused(str(Path(self.tmp) / "nope")), (False, ""))

    def test_a_pause_marker_alone_does_not_pause_a_live_engine(self):
        # One line paused, one still live: the engine runs, so it is not paused.
        mixed = PAUSED + (
            "0 6 * * 5 scraper fac-run supabase -- /root/Find-A-Crib/growth_run.sh report\n")
        self.assertEqual(growth_daily.growth_paused(self._cron(mixed)), (False, ""))


class LivenessWording(unittest.TestCase):
    """cron_liveness() headline, which is what the review reads first."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name
        self.now = datetime.datetime(2026, 10, 13, 9, 0, tzinfo=datetime.timezone.utc)
        hb = Path(self.tmp) / "cron_heartbeat.jsonl"
        hb.write_text(json.dumps({
            "at": "2026-10-12T05:40:22Z", "job": "build --deploy",
            "phase": "finish", "rc": 0, "pull": "ok"}) + "\n")
        self.hb = str(hb)

    def tearDown(self):
        self._td.cleanup()

    def _summary(self, cron_text):
        cron = Path(self.tmp) / "cron-rentmap-growth"
        cron.write_text(cron_text)
        real = growth_daily.GROWTH_CRON_PATH
        growth_daily.GROWTH_CRON_PATH = str(cron)
        try:
            summary, _ = growth_daily.cron_liveness(path=self.hb, now=self.now)
        finally:
            growth_daily.GROWTH_CRON_PATH = real
        return summary

    def test_paused_says_so_and_never_blames_cron_or_the_host(self):
        s = self._summary(PAUSED)
        self.assertIn("PAUSED ON PURPOSE", s)
        self.assertIn("#PAUSED-20261012", s)
        self.assertNotIn("cron, the host or the checkout", s)
        self.assertNotIn("NO RUN FOR", s)

    def test_paused_still_reports_how_long_it_has_been_quiet(self):
        # A pause left running for a month must not read like a fresh one.
        s = self._summary(PAUSED)
        self.assertIn("1.1 days", s)
        self.assertIn("nothing pushed here reaches production", s)
        self.assertIn("deploy_jobs.sh", s)

    def test_paused_still_carries_the_last_real_outcome(self):
        self.assertIn("last run ok (build --deploy)", self._summary(PAUSED))

    def test_stale_with_a_live_cron_still_reads_as_a_failure(self):
        s = self._summary(LIVE)
        self.assertIn("NO RUN FOR 1.1 DAYS", s)
        self.assertIn("cron, the host or the checkout", s)
        self.assertNotIn("PAUSED", s)

    def test_truncated_cron_still_reads_as_a_failure(self):
        s = self._summary(NO_JOBS)
        self.assertIn("NO RUN FOR 1.1 DAYS", s)
        self.assertNotIn("PAUSED ON PURPOSE", s)

    def test_a_fresh_run_says_nothing_about_pausing_either_way(self):
        # Inside 26h nothing about staleness or pausing should appear at all,
        # so 364 ordinary mornings gain no new line.
        fresh = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=datetime.timezone.utc)
        cron = Path(self.tmp) / "cron-rentmap-growth"
        cron.write_text(PAUSED)
        real = growth_daily.GROWTH_CRON_PATH
        growth_daily.GROWTH_CRON_PATH = str(cron)
        try:
            s, _ = growth_daily.cron_liveness(path=self.hb, now=fresh)
        finally:
            growth_daily.GROWTH_CRON_PATH = real
        self.assertNotIn("PAUSED", s)
        self.assertNotIn("NO RUN FOR", s)
        self.assertIn("last run ok", s)


class TrackedCronMatchesReality(unittest.TestCase):
    def test_the_repos_own_cron_is_currently_paused(self):
        # Pins today's actual state, so resuming the engine without dropping
        # this test's expectation is a visible decision rather than a silent
        # drift. Companion to tests/test_job_sandbox.py's pause pins.
        paused, marker = growth_daily.growth_paused()
        self.assertTrue(paused, "deploy/cron-rentmap-growth has a live growth_run line")
        self.assertEqual(marker, "#PAUSED-20261012")


if __name__ == "__main__":
    unittest.main()
