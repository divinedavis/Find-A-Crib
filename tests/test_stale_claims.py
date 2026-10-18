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
import re
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


# ---------------------------------------------------------------------------
# The referring claim: pages OUTSIDE /section8/ promising that section is
# rebuilt nightly. Judged on /section8/'s own build age, never on theirs —
# every one of these tiers reaches the docroot through refresh_seo.sh, whose
# only live cron is the 1st of each month, so an honest /methodology/ is
# routinely 30 days old while the voucher build runs faithfully every night.
HUB = ("<h1>Rent-stabilized buildings in Bushwick, Brooklyn</h1>"
       "<h2>Renting with a housing voucher?</h2>"
       "<p>Find A Crib rebuilds a list every night of the DHCR-registered "
       "rent-stabilized buildings that have an apartment listed for Section 8 and "
       "other housing vouchers, from the overnight AffordableHousing.com feed — "
       "<a href='/section8/'>see the current voucher listings</a>.</p>")
CITY_HUB = ("<h1>Rent-controlled buildings in San Francisco by neighborhood</h1>"
            "<h2>New York City: apartments listed for housing vouchers</h2>"
            "<p>Find A Crib's voucher feed covers New York City only — every night it "
            "rebuilds the list of DHCR-registered rent-stabilized buildings with an "
            "apartment listed for Section 8 and other housing vouchers, from the "
            "overnight AffordableHousing.com feed. There is no equivalent feed for "
            "San Francisco yet.</p>")
METHODOLOGY = ("<h1>How Find A Crib compiles its rent-regulation data</h1>"
               "<table class='facts'>"
               "<tr><td class='k'>Housing-voucher listings (/section8/)</td>"
               "<td>Rebuilt nightly</td></tr>"
               "<tr><td class='k'>DC Rent Registry</td>"
               "<td>The source publishes nightly export files</td></tr></table>")
# A hub page that carries no promise about the voucher build at all.
PLAIN_HUB = ("<h1>Rent-stabilized buildings in ZIP 11221</h1>"
             "<p>ZIP code 11221 in Brooklyn contains 1,204 buildings registered as "
             "rent stabilized with New York State DHCR.</p>")

REFERRING = "pages citing /section8/"


class TheReferringClaim(Docroot):
    def test_hub_pages_promising_a_frozen_section_are_reported(self):
        self.write("section8/index.html", body=FRESH, age_h=150.0)
        self.write("neighborhood/brooklyn/bushwick/index.html", body=HUB, age_h=150.0)
        self.feed()
        out = self.run_check()
        self.assertIn(REFERRING, out)
        self.assertIn("rebuilds a list every night", out[REFERRING])
        self.assertIn("/neighborhood/", out[REFERRING])
        self.assertIn("last rebuilt 6.2 days ago", out[REFERRING])

    def test_it_is_judged_on_section8_and_not_on_the_hubs_own_age(self):
        """The false positive this design exists to avoid.

        refresh_seo.sh runs on the 1st of the month (deploy/cron-rentmap-seo),
        so a 30-day-old hub page is the NORMAL state. While /section8/ is
        rebuilt nightly the sentence on it is simply true, at any age.
        """
        self.write("section8/index.html", body=FRESH, age_h=6.0)
        self.write("neighborhood/brooklyn/bushwick/index.html", body=HUB, age_h=800.0)
        self.write("methodology/index.html", body=METHODOLOGY, age_h=800.0)
        self.feed()
        self.assertEqual(self.run_check(), {})

    def test_a_stale_path_section8_still_reports_the_referring_pages(self):
        """The case the self claim cannot see, and the reason for this half.

        A /section8/ that froze on its STALE path is honestly dated about
        itself — and 370 pages elsewhere are still promising it is rebuilt
        nightly. One finding, not two.
        """
        self.write("section8/index.html", body=STALE, age_h=150.0)
        self.write("buildings/index.html", body=HUB, age_h=150.0)
        self.feed()
        out = self.run_check()
        self.assertNotIn("/section8/", out)
        self.assertIn(REFERRING, out)

    def test_both_findings_fire_when_both_are_true_and_the_feed_clause_once(self):
        self.write("section8/index.html", body=FRESH, age_h=150.0)
        self.write("buildings/index.html", body=HUB, age_h=150.0)
        self.feed(age_h=6.0)
        out = self.run_check()
        self.assertEqual(sorted(out), ["/section8/", REFERRING])
        self.assertIn("refreshed 6h ago", out["/section8/"])
        self.assertNotIn("s8.json", out[REFERRING])

    def test_the_feed_clause_appears_when_only_the_referring_finding_fires(self):
        self.write("section8/index.html", body=STALE, age_h=150.0)
        self.write("buildings/index.html", body=HUB, age_h=150.0)
        self.feed(age_h=6.0)
        self.assertIn("refreshed 6h ago", self.run_check()[REFERRING])

    def test_every_section_is_named_and_every_page_counted(self):
        self.write("section8/index.html", body=STALE, age_h=150.0)
        self.write("buildings/index.html", body=HUB, age_h=150.0)
        self.write("neighborhood/brooklyn/bushwick/index.html", body=HUB, age_h=150.0)
        self.write("neighborhood/queens/astoria/index.html", body=HUB, age_h=150.0)
        self.write("zip/11221/index.html", body=HUB, age_h=150.0)
        self.write("sf/buildings/index.html", body=CITY_HUB, age_h=150.0)
        self.write("methodology/index.html", body=METHODOLOGY, age_h=150.0)
        detail = self.run_check()[REFERRING]
        self.assertIn("6 pages in 5 sections", detail)
        for where in ("/buildings/", "/neighborhood/", "/zip/", "/sf/buildings/",
                      "/methodology/"):
            self.assertIn(where, detail)

    def test_the_methodology_source_row_is_not_mistaken_for_ours(self):
        """"The source publishes nightly export files" is about DHCD, and true."""
        self.write("section8/index.html", body=STALE, age_h=150.0)
        self.write("methodology/index.html", body=METHODOLOGY.replace(
            "<td>Rebuilt nightly</td>", "<td>Rebuilt on the data build</td>"), age_h=150.0)
        self.assertEqual(self.run_check(), {})

    def test_a_hub_carrying_no_promise_is_not_counted(self):
        self.write("section8/index.html", body=STALE, age_h=150.0)
        self.write("zip/11221/index.html", body=PLAIN_HUB, age_h=150.0)
        self.assertEqual(self.run_check(), {})

    def test_a_tier_outside_the_list_is_not_walked(self):
        """The known cost of REFERRING_SECTIONS, pinned so it is not a surprise."""
        self.write("section8/index.html", body=STALE, age_h=150.0)
        self.write("building/brooklyn/123-fake-st-3012345/index.html", body=HUB, age_h=150.0)
        self.assertEqual(self.run_check(), {})

    def test_one_page_reads_in_the_singular(self):
        self.write("section8/index.html", body=STALE, age_h=150.0)
        self.write("methodology/index.html", body=METHODOLOGY, age_h=150.0)
        detail = self.run_check()[REFERRING]
        self.assertTrue(detail.startswith("1 page in 1 section"), detail)
        self.assertIn('says "Rebuilt nightly"', detail)


class TheReferringBoundary(Docroot):
    def test_just_under_the_allowance_is_silent(self):
        self.write("section8/index.html", body=STALE, age_h=47.9)
        self.write("buildings/index.html", body=HUB, age_h=900.0)
        self.assertEqual(self.run_check(), {})

    def test_just_over_the_allowance_reports(self):
        self.write("section8/index.html", body=STALE, age_h=48.1)
        self.write("buildings/index.html", body=HUB, age_h=900.0)
        self.assertIn(REFERRING, self.run_check())

    def test_the_freshest_section8_page_sets_the_age(self):
        """A nightly rebuild that reaches only the hub still keeps the promise."""
        self.write("section8/index.html", body=STALE, age_h=2.0)
        self.write("section8/bronx/index.html", body=STALE, age_h=400.0)
        self.write("buildings/index.html", body=HUB, age_h=900.0)
        self.assertEqual(self.run_check(), {})

    def test_a_box_without_the_section_judges_neither_claim(self):
        """No /section8/ at all is a different, larger problem than this one."""
        self.write("buildings/index.html", body=HUB, age_h=900.0)
        self.feed()
        self.assertEqual(self.run_check(), {})

    def test_a_section_directory_with_no_pages_judges_neither_claim(self):
        (self.root / "section8").mkdir()
        self.write("buildings/index.html", body=HUB, age_h=900.0)
        self.assertEqual(self.run_check(), {})


class TheReferringPhrasesAreReal(unittest.TestCase):
    SRC = None

    @classmethod
    def setUpClass(cls):
        src = (Path(__file__).resolve().parent.parent / "build_seo.py").read_text()
        # Adjacent string literals are joined in the rendered HTML but split
        # across source lines, so close the concatenation seams before looking
        # for a phrase as a reader of the page would see it.
        cls.SRC = re.sub(r'"\s*\n\s*"', '', src)

    def test_each_phrase_occurs_exactly_once_in_build_seo(self):
        """Three phrases, three code sites. Reword one and this fails; reuse
        one on a fourth tier and this fails too, which is the signal to extend
        REFERRING_SECTIONS. New wording on a fourth tier it cannot catch."""
        for phrase in er.REFERRING_PHRASES:
            self.assertEqual(self.SRC.count(phrase), 1, phrase)

    def test_the_two_phrase_sets_do_not_overlap(self):
        self.assertEqual(set(er.CADENCE_PHRASES) & set(er.REFERRING_PHRASES), set())

    def test_no_referring_phrase_appears_in_the_section8_template(self):
        """Otherwise a /section8/ page would be counted as referring to itself."""
        src = (Path(__file__).resolve().parent.parent / "growth" / "techniques.py").read_text()
        joined = re.sub(r'"\s*\n\s*"', '', src)
        for phrase in er.REFERRING_PHRASES:
            self.assertNotIn(phrase, joined)

    def test_the_walked_sections_exclude_section8_and_the_building_corpus(self):
        for rel in er.REFERRING_SECTIONS:
            self.assertNotIn(rel.split("/")[0], ("section8", "building"))

    def test_the_sections_cover_all_three_code_sites(self):
        for rel in ("buildings", "neighborhood", "zip", "borough",
                    "sf/buildings", "la/buildings", "dc/buildings", "methodology"):
            self.assertIn(rel, er.REFERRING_SECTIONS)


class TheReferringWiring(Docroot):
    CLAIMS = {
        "/section8/":
            '6 pages still say "Updated daily" but the freshest was built 6.2 days ago',
        REFERRING:
            '374 pages in 5 sections (/buildings/, /neighborhood/, /zip/, /sf/buildings/, '
            '/methodology/) say "rebuilds a list every night" about /section8/, which was '
            "itself last rebuilt 6.2 days ago",
    }

    def test_both_rows_reach_both_parts_of_the_email(self):
        html, text = er.build("last 24 hours", {}, {}, {}, er.Counter(), er.Counter(), {},
                              set(), claims=self.CLAIMS)
        for part in (html, text):
            self.assertIn("Pages promising a refresh that stopped", part)
            self.assertIn("/section8/", part)
            self.assertIn("374 pages in 5 sections", part)

    def test_the_column_is_a_place_rather_than_a_published_tier(self):
        html, _text = er.build("last 24 hours", {}, {}, {}, er.Counter(), er.Counter(), {},
                               set(), claims=self.CLAIMS)
        self.assertIn(">Where<", html)
