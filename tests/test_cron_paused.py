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
from unittest import mock

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
        self.assertIn("deploy_jobs.sh", s)

    def test_paused_names_the_growth_code_a_live_cron_still_runs(self):
        # This test used to pin "nothing pushed here reaches production", which
        # was true when it was written on 2026-10-13 and false from 2026-10-21,
        # when growth/section8_refresh.py went onto cron-rentmap-scrape. The
        # headline is read every morning and that sentence had already talked
        # nine reviews out of shipping a page change, so it is derived from the
        # cron files now and this pins the derivation, not the sentence.
        # The stand-in was removed when the engine resumed (2026-10-29), so the
        # real deploy dir no longer has one; pin the derivation with a stub.
        from unittest import mock
        with mock.patch.object(growth_daily, "growth_live_paths",
                               lambda *a, **k: [("cron-rentmap-scrape", "growth/section8_refresh.py")]):
            s = self._summary(PAUSED)
        self.assertIn("the growth build publishes nothing", s)
        self.assertIn("growth/section8_refresh.py is live on cron-rentmap-scrape", s)
        self.assertIn("DOES reach readers", s)
        self.assertNotIn("nothing pushed here reaches production", s)

    def test_paused_with_no_live_growth_script_says_nothing_gets_through(self):
        # The old sentence is still the right one when it is true, so it has to
        # remain makeable: a deploy dir with no live growth/ script restores it.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, "cron-rentmap-scrape").write_text(
                "15 4 * * * scraper python3 scrape_affordablehousing.py\n")
            with mock.patch.object(growth_daily, "DEPLOY_DIR", d):
                s = self._summary(PAUSED)
        self.assertIn("nothing pushed here reaches production", s)
        self.assertNotIn("DOES reach readers", s)

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
    def test_the_repos_own_cron_is_running_again(self):
        # Pins today's actual state. Paused 2026-10-12, resumed 2026-10-29
        # (owner: get AI answer engines to find and cite the site), so a
        # re-pause has to drop this expectation on purpose.
        paused, _ = growth_daily.growth_paused()
        self.assertFalse(paused, "deploy/cron-rentmap-growth has no live growth_run line")


if __name__ == "__main__":
    unittest.main()


class LivePathsOutsideThePause(unittest.TestCase):
    """growth_live_paths(): growth code a NON-growth cron still runs.

    2026-10-22. The pause headline asserted "nothing pushed here reaches
    production" from 2026-10-12. On 2026-10-21 the owner put
    growth/section8_refresh.py on cron-rentmap-scrape (5ceeb4d) so /section8/
    keeps being rebuilt while the engine is off, which made that sentence false
    — and nine reviews had already deferred page changes on the strength of it.
    """

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _deploy(self, files):
        d = Path(self.tmp) / "deploy"
        d.mkdir(exist_ok=True)
        for name, text in files.items():
            (d / name).write_text(text)
        return str(d)

    def test_the_real_deploy_dir_no_longer_runs_the_section8_stand_in(self):
        # Removed 2026-10-29 when the engine's own 05:40 build resumed.
        found = growth_daily.growth_live_paths()
        self.assertNotIn(("cron-rentmap-scrape", "growth/section8_refresh.py"), found)

    def test_a_commented_out_line_is_not_live(self):
        d = self._deploy({"cron-rentmap-x":
                          "#40 5 * * * scraper python3 growth/section8_refresh.py\n"})
        self.assertEqual(growth_daily.growth_live_paths(d), [])

    def test_growth_run_is_excluded_because_growth_paused_reports_it(self):
        # The engine's own line carries no growth/<x>.py token, so the token
        # filter alone would drop it. The guard earns its place only on a line
        # that runs growth_run.sh AND a growth/ script, which is what this pins:
        # a live growth_run line means the engine is not paused, and
        # growth_paused() is what reports that.
        d = self._deploy({"cron-rentmap-growth":
                          "40 5 * * * scraper cd /root/Find-A-Crib && "
                          "./growth_run.sh build && python3 growth/section8_refresh.py\n"})
        self.assertEqual(growth_daily.growth_live_paths(d), [])

    def test_a_live_growth_script_is_reported_with_its_cron_file(self):
        d = self._deploy({"cron-rentmap-scrape":
                          "# a comment naming growth/other.py\n"
                          "40 5 * * * scraper python3 growth/section8_refresh.py >> /l 2>&1\n"})
        self.assertEqual(growth_live := growth_daily.growth_live_paths(d),
                         [("cron-rentmap-scrape", "growth/section8_refresh.py")])
        self.assertEqual(len(growth_live), 1)

    def test_a_missing_deploy_dir_reports_nothing_rather_than_raising(self):
        self.assertEqual(
            growth_daily.growth_live_paths(str(Path(self.tmp) / "nope")), [])

