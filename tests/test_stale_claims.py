"""error_report.stale_claims: a live page promising a nightly refresh that
stopped is reported, and an honestly-dated stale page is not.

The condition this covers is invisible to every other instrument on the box at
once (see the stale_claims docstring): dead_crons() stands down on the
deliberate 2026-10-12 pause, stale_feeds() stays green because the scrape cron
is not paused, and t_frozen_pages measures a page against the newest page in
the docroot, so a uniform freeze reads as no freeze.

No pytest in the venv (see tests/run_unit.py), so these are unittest classes
with real temp directories rather than tmp_path/monkeypatch fixtures.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import error_report as er  # noqa: E402

HOUR = 3600.0
NOW = 1792000000.0

# The two wordings t_fresh_section8 chooses between. FRESH is only ever emitted
# when the feed is current; STALE stays true however old the page gets.
FRESH = ("<h1>Section 8 &amp; voucher-friendly apartments in NYC — updated October 12, 2026</h1>"
         "<div class='stat'><b>289</b><span>rent-stabilized buildings with live listings</span></div>"
         "<p class='sub'>Rebuilt daily from the overnight feed.</p>")
STALE = ("<h1>Section 8 &amp; voucher-friendly apartments in NYC — listings as of October 12, 2026</h1>"
         "<div class='note'><b>These listings are from October 12, 2026 and have not been "
         "refreshed since.</b></div>"
         "<div class='stat'><b>289</b><span>rent-stabilized buildings listed as of October 12, 2026"
         "</span></div>")


class Docroot(unittest.TestCase):
    """A throwaway docroot with section8 pages of a chosen age and a dated feed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel, body=FRESH, age_h=120.0):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        os.utime(p, (NOW - age_h * HOUR, NOW - age_h * HOUR))
        return p

    def feed(self, age_h=6.0):
        p = self.root / "s8.json"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (NOW - age_h * HOUR, NOW - age_h * HOUR))

    def run_check(self):
        return er.stale_claims(docroot=str(self.root), now=NOW)


class TheFinding(Docroot):
    def test_frozen_fresh_claim_is_reported(self):
        self.write("section8/index.html")
        self.feed()
        out = self.run_check()
        self.assertIn("/section8/", out)
        self.assertIn("5.0 days ago", out["/section8/"])

    def test_a_fresh_feed_behind_a_frozen_page_is_named_as_the_contrast(self):
        self.write("section8/index.html")
        self.feed(age_h=6.0)
        detail = self.run_check()["/section8/"]
        self.assertIn("refreshed 6h ago", detail)
        self.assertIn("The scrape is running and the pages built from it are not", detail)

    def test_a_stale_feed_is_deferred_to_the_feeds_table(self):
        self.write("section8/index.html")
        self.feed(age_h=200.0)
        detail = self.run_check()["/section8/"]
        self.assertIn("see Feeds", detail)
        self.assertNotIn("The scrape is running", detail)

    def test_every_borough_page_is_counted(self):
        for rel in ("section8/index.html", "section8/brooklyn/index.html",
                    "section8/queens/index.html"):
            self.write(rel)
        self.feed()
        self.assertIn("3 pages still say", self.run_check()["/section8/"])

    def test_one_page_reads_in_the_singular(self):
        self.write("section8/index.html")
        self.feed()
        self.assertTrue(self.run_check()["/section8/"].startswith("1 page still says"))


class TheStandDowns(Docroot):
    def test_an_honestly_dated_stale_page_is_never_reported(self):
        """The whole point: the stale path's wording is still true at any age."""
        self.write("section8/index.html", body=STALE, age_h=1000.0)
        self.feed()
        self.assertEqual(self.run_check(), {})

    def test_a_fresh_page_within_the_allowance_is_fine(self):
        self.write("section8/index.html", age_h=12.0)
        self.feed()
        self.assertEqual(self.run_check(), {})

    def test_a_box_that_does_not_publish_the_section_says_nothing(self):
        self.feed()
        self.assertEqual(self.run_check(), {})

    def test_a_missing_feed_still_reports_the_page(self):
        """The verdict is about the page. A missing s8.json is stale_feeds()' finding."""
        self.write("section8/index.html")
        detail = self.run_check()["/section8/"]
        self.assertIn("5.0 days ago", detail)
        self.assertNotIn("s8.json", detail)

    def test_a_page_with_no_index_html_is_skipped(self):
        self.write("section8/brooklyn/listings.html")
        self.feed()
        self.assertEqual(self.run_check(), {})


class TheBoundary(Docroot):
    def test_just_under_the_allowance_is_silent(self):
        self.write("section8/index.html", age_h=47.9)
        self.feed()
        self.assertEqual(self.run_check(), {})

    def test_just_over_the_allowance_reports(self):
        self.write("section8/index.html", age_h=48.1)
        self.feed()
        self.assertNotEqual(self.run_check(), {})

    def test_the_allowance_is_the_pages_own_48h(self):
        self.assertEqual(er.CADENCE_CLAIM_HOURS, 48)

    def test_age_comes_from_the_freshest_claiming_page(self):
        """One forgotten corner of the tier must not create the finding alone."""
        self.write("section8/index.html", age_h=2.0)
        self.write("section8/bronx/index.html", age_h=400.0)
        self.feed()
        self.assertEqual(self.run_check(), {})


class ThePhrasesAreReal(unittest.TestCase):
    def test_every_phrase_still_exists_in_the_template(self):
        """If the template is reworded, fail here rather than match nothing forever."""
        src = (Path(__file__).resolve().parent.parent / "growth" / "techniques.py").read_text()
        for phrase in er.CADENCE_PHRASES:
            self.assertIn(phrase, src)

    def test_the_stale_wording_carries_no_phrase(self):
        self.assertEqual([p for p in er.CADENCE_PHRASES if p in STALE], [])


class TheWiring(Docroot):
    CLAIMS = {"/section8/":
              '4 pages still say "Updated daily" but the freshest was built 5.0 days ago'}

    def test_the_finding_reaches_both_parts_of_the_email(self):
        html, text = er.build("last 24 hours", {}, {}, {}, er.Counter(), er.Counter(), {},
                              set(), claims=self.CLAIMS)
        self.assertIn("Pages promising a refresh that stopped", html)
        self.assertIn("/section8/", html)
        self.assertIn("Pages promising a refresh that stopped:", text)
        self.assertIn("5.0 days ago", text)

    def test_no_finding_renders_no_section(self):
        html, text = er.build("last 24 hours", {}, {}, {}, er.Counter(), er.Counter(), {}, set())
        self.assertNotIn("promising a refresh", html)
        self.assertNotIn("promising a refresh", text)

    def test_default_docroot_is_resolved_at_call_time(self):
        """Overridable rather than frozen at import, per the growth_paused() lesson."""
        self.write("section8/index.html")
        self.feed()
        old = os.environ.get("GROWTH_DOCROOT")
        os.environ["GROWTH_DOCROOT"] = str(self.root)
        try:
            self.assertIn("/section8/", er.stale_claims(now=NOW))
        finally:
            if old is None:
                os.environ.pop("GROWTH_DOCROOT", None)
            else:
                os.environ["GROWTH_DOCROOT"] = old
