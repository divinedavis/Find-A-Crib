"""t_frozen_pages: a mostly-frozen corpus is a stopped build, not a retired section.

2026-10-23, from T090's revisit. The audit measures every page against the
NEWEST page in the docroot rather than against today, so that a night the whole
pipeline failed reports no freezes instead of 49,000 of them. That guard assumes
one whole-corpus writer. Commit 5ceeb4d (2026-10-21) added a second, narrow one:
growth/section8_refresh.py writes six URLs under /section8/ every night from a
live cron while the growth build carries #PAUSED-20261012. Six fresh pages hold
`newest` at tonight by themselves, so the corpus the main build stopped writing
is measured against them and returned as tens of thousands of frozen pages —
with ok True, abandoned_tiers 0, and a label naming "retired tiers and the app
shells this loop cannot deploy", a cause the audit had never checked.

THE REAL BASELINE THESE TESTS ARE CALIBRATED AGAINST, read out of
growth/last_run.json for 2026-10-12, the last night the engine ran: 23 frozen
pages of 49,323 across 7 of 32 tiers (brief/ retired, plus six one-off shells),
building/ absent. 0.05% against the ~96% a stopped corpus build produces.
"""
import datetime
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from growth import techniques as T  # noqa: E402


def _page(root, rel, day):
    """Write <root>/<rel>/index.html with its mtime pinned to `day`."""
    p = os.path.join(root, rel, "index.html")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("<html><body>x</body></html>")
    ts = time.mktime(datetime.datetime.strptime(day, "%Y-%m-%d").timetuple())
    os.utime(p, (ts, ts))


class _Ctx:
    def __init__(self, docroot):
        self.docroot = docroot


class FrozenCorpus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _docroot(self, corpus_day, section8_day=None, extra_frozen=()):
        """The corpus as a build leaves it, optionally beside fresher /section8/."""
        root = tempfile.mkdtemp(dir=self.tmp)
        for i in range(1200):
            _page(root, f"building/b{i}", corpus_day)
        for i in range(40):
            _page(root, f"neighborhood/n{i}", corpus_day)
        for name, day in extra_frozen:
            _page(root, name, day)
        for b in ("", "bronx", "brooklyn", "manhattan", "queens", "staten-island"):
            _page(root, os.path.join("section8", b), section8_day or corpus_day)
        return root

    # ── the defect ──────────────────────────────────────────────────────────
    def test_a_narrow_writer_does_not_make_the_corpus_look_retired(self):
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-12", "2026-10-23")))
        self.assertFalse(r["ok"])
        self.assertTrue(r["corpus_stopped"])
        self.assertIn("THE BUILD THAT WRITES THIS CORPUS HAS STOPPED", r["detail"])

    def test_it_names_the_day_the_build_stopped_and_the_gap(self):
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-12", "2026-10-23")))
        self.assertIn("last written 2026-10-12", r["detail"])
        self.assertIn("11d before the newest page", r["detail"])

    def test_it_names_the_writer_still_running(self):
        """Identified from the docroot, not from knowledge of section8_refresh.py."""
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-12", "2026-10-23")))
        self.assertIn("Still written since: section8/", r["detail"])

    def test_it_does_not_call_a_stopped_corpus_a_set_of_retired_sections(self):
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-12", "2026-10-23")))
        self.assertIn("NOT because these are retired sections", r["detail"])
        self.assertNotIn("app shells this loop cannot deploy", r["detail"])

    # ── the behaviour that must not regress ─────────────────────────────────
    def test_the_healthy_night_stays_green_with_its_old_label(self):
        """2026-10-12's shape: a handful of genuinely retired one-off tiers."""
        extra = [("brief/2026-07-27", "2026-07-27"), ("alerts", "2026-10-06"),
                 ("brand", "2026-09-09"), ("directory", "2026-10-06"),
                 ("report-ready", "2026-07-27"), ("reset", "2026-09-09"),
                 ("support", "2026-10-06")]
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-12", extra_frozen=extra)))
        self.assertTrue(r["ok"])
        self.assertFalse(r["corpus_stopped"])
        self.assertEqual(r["frozen"], len(extra))
        self.assertIn("app shells this loop cannot deploy", r["detail"])
        self.assertLess(r["frozen_pct"], T.FROZEN_CORPUS_PCT)

    def test_a_night_the_whole_pipeline_failed_still_reports_no_freezes(self):
        """The original guard. Nothing wrote, so nothing is newer than anything."""
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-12")))
        self.assertTrue(r["ok"])
        self.assertFalse(r["corpus_stopped"])
        self.assertEqual(r["frozen"], 0)
        self.assertIn("every published page was written within the grace window",
                      r["detail"])

    def test_one_skipped_night_is_still_not_a_freeze(self):
        """FROZEN_GRACE_DAYS=2 keeps a build that missed a night out of this."""
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-22", "2026-10-23")))
        self.assertTrue(r["ok"])
        self.assertFalse(r["corpus_stopped"])

    def test_a_bare_checkout_is_still_not_measured(self):
        root = tempfile.mkdtemp(dir=self.tmp)
        _page(root, "building/b0", "2026-10-12")
        r = T.t_frozen_pages(_Ctx(root))
        self.assertTrue(r["ok"])
        self.assertIn("NOT MEASURED", r["detail"])
        self.assertNotIn("corpus_stopped", r)

    # ── the threshold itself ────────────────────────────────────────────────
    def test_the_threshold_is_a_named_constant_with_room_either_side(self):
        self.assertIsInstance(T.FROZEN_CORPUS_PCT, int)
        # Clear of the 0.05% a healthy night produces and of the ~96% a stopped
        # corpus build produces, so neither sits near the edge.
        self.assertGreater(T.FROZEN_CORPUS_PCT, 1)
        self.assertLess(T.FROZEN_CORPUS_PCT, 90)

    def test_frozen_pct_is_reported_so_the_call_is_checkable(self):
        r = T.t_frozen_pages(_Ctx(self._docroot("2026-10-12", "2026-10-23")))
        self.assertGreater(r["frozen_pct"], 90)
        self.assertEqual(r["frozen_pct"],
                         round(100.0 * r["frozen"] / r["pages"], 1))


if __name__ == "__main__":
    unittest.main()
