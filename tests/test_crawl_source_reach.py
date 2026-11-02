"""t_crawl_paths: an inbound link from a page Google has never fetched is not a crawl path.

2026-11-02. The binary _crawl_link_audit answers — does SOMETHING link into
this section — has read green on every published section for weeks (16 of 16
this morning) while the index census held `index_fetched` FLAT at 186 of 442
cohort URLs for four consecutive nights. 15 crawls in 14 days, and the
per-family counts sum to exactly 15 across four families, so every one of them
was a RE-crawl: not one first fetch, while ten families covering 79 cohort URLs
sit at 0 fetched with last_crawl "never".

So "16 of 16 published sections have an inbound internal link" is a true
sentence whose implication its evidence does not support, which is the same
defect logged on 2026-08-25, 08-26, 08-27, 10-31 and 11-01.

THE READING THESE TESTS ARE CALIBRATED AGAINST, out of growth/index_status.json
for 2026-11-02: (root) read 1 fetched 1 crawled 2026-10-29 and indexed; guide
read 10 fetched 0 with every URL "unknown to Google"; dc 20/0; la 20/0; sf 20/1
(last 2026-07-28); borough 10/5; building 250/158; neighborhood 40/15; zip 40/4;
buildings 1/1; developers 1/1.

EVERY TEST HERE DRIVES A CONSTRUCTED CENSUS READING, not the live census, for
the lesson of 2026-11-01: the only test of a branch's wording reached it through
whichever technique satisfied four live conditions that night, and it went red
with nothing in the guard changed when a traffic series moved. The one test that
does read the live corpus SKIPS rather than fails when today's census does not
put anything on the branch.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from growth import indexstatus, review, techniques as T  # noqa: E402

# The six words that must appear when a section's whole link supply is unfetched,
# and the five that must appear when a link SOURCE family is. Pinned as constants
# so a reworded clause fails loudly here instead of silently passing an
# `assertIn` someone relaxed.
SECTION_CLAUSE = "linked ONLY from page families Googlebot has never fetched"
SOURCE_CLAUSE = "link-source families this audit reads FROM have never been fetched"

# The live families, verbatim, so a test reads like the morning it describes.
LIVE = {
    "(root)": {"read": 1, "fetched": 1},
    "guide": {"read": 10, "fetched": 0},
    "dc": {"read": 20, "fetched": 0},
    "la": {"read": 20, "fetched": 0},
    "sf": {"read": 20, "fetched": 1},
    "borough": {"read": 10, "fetched": 5},
    "zip": {"read": 40, "fetched": 4},
    "neighborhood": {"read": 40, "fetched": 15},
    "building": {"read": 250, "fetched": 158},
    "buildings": {"read": 1, "fetched": 1},
    "developers": {"read": 1, "fetched": 1},
}

ALL_FETCHED = {fam: {"read": 50, "fetched": 9}
               for fam in {T._source_family(p) for _, p, _ in T._crawl_sources()}}


def note(found, reach):
    return T._crawl_source_reach_note(found, sorted(found), reach=reach)


class TheFamilyMapping(unittest.TestCase):
    """_source_family must agree with the census's own stratification."""

    def test_every_crawl_source_maps_to_the_family_its_urls_belong_to(self):
        # The glob is a docroot-relative path, the census strata are URL first
        # path segments, and the two must name the same thing or the clause
        # judges one family and reports another.
        for label, pattern, _cap in T._crawl_sources():
            # The URL a glob serves, not the file path: index.html is served as
            # its directory, and the homepage's URL is "/" — which is the whole
            # reason the root family is named "(root)" rather than "index.html".
            url = ("https://findacrib.com/"
                   + pattern.replace("index.html", "").replace("*", "x"))
            self.assertEqual(T._source_family(pattern), indexstatus.family(url),
                             f"{label} ({pattern}) -> {url}")

    def test_the_home_shell_is_the_root_family_and_not_a_segment_called_index(self):
        self.assertEqual(T._source_family("index.html"), "(root)")

    def test_a_city_sub_hub_maps_to_its_city_not_to_its_own_directory(self):
        # Deliberate coarseness, and the census docstring's: /dc/buildings/ may
        # hold no inspected URL at all, so asking about it would get read=0 —
        # silence misreported as evidence.
        self.assertEqual(T._source_family("dc/buildings/index.html"), "dc")
        self.assertEqual(T._source_family("sf/neighborhood/*/index.html"), "sf")


class WhenItStaysSilent(unittest.TestCase):
    """Four distinctions, each a real one rather than a convenience."""

    def test_an_empty_census_says_nothing(self):
        self.assertEqual(note({"/dc/neighborhood/": {"dc browse hub"}}, {}), "")

    def test_reach_none_falls_back_to_the_census_file_and_never_raises(self):
        # reach=None is the production path. It must return a string whatever
        # index_status.json holds — including absent, which is what a fresh
        # clone with no census looks like.
        out = T._crawl_source_reach_note({"/x/": {"guide hub"}}, ["/x/"])
        self.assertIsInstance(out, str)

    def test_a_census_that_never_ran_is_not_read_as_zeros(self):
        # The whole point of returning None: a census that did not run and a
        # census that looked and found nothing fetched are different facts.
        self.assertEqual(note({"/x/": {"guide hub"}}, {}), "")

    def test_an_orphan_is_not_also_reported_here(self):
        # It has no inbound source at all; the ORPHANED branches of
        # t_crawl_paths own that finding and saying it twice double-counts it.
        # The SOURCE sentence still fires, and must: it is a fact about the
        # families this audit reads from, not about any destination.
        out = note({"/x/": set()}, LIVE)
        self.assertNotIn(SECTION_CLAUSE, out)
        self.assertNotIn("/x/", out)
        self.assertIn(SOURCE_CLAUSE, out)

    def test_an_orphan_on_a_fully_fetched_site_says_nothing_at_all(self):
        self.assertEqual(note({"/x/": set()}, ALL_FETCHED), "")

    def test_a_healthy_site_produces_no_clause(self):
        self.assertEqual(note({"/x/": {"building page"}}, ALL_FETCHED), "")

    def test_a_section_with_one_fetched_source_is_not_flagged(self):
        # One real crawl path is enough; the clause is about sections with none.
        out = note({"/x/": {"la browse hub", "building page"}}, LIVE)
        self.assertNotIn(SECTION_CLAUSE, out)

    def test_a_non_integer_reading_is_silence_not_zero(self):
        for bad in (None, "0", 0.0, [], {}):
            self.assertEqual(note({"/x/": {"guide hub"}},
                                  {"guide": {"read": 10, "fetched": bad}}), "",
                             f"fetched={bad!r}")
            self.assertEqual(note({"/x/": {"guide hub"}},
                                  {"guide": {"read": bad, "fetched": 0}}), "",
                             f"read={bad!r}")

    def test_a_family_missing_from_the_census_entirely_is_silence(self):
        self.assertEqual(note({"/x/": {"guide hub"}}, {"building": {"read": 9, "fetched": 9}}), "")


class TheFloorIsAsymmetricOnPurpose(unittest.TestCase):
    """A fetch is a positive fact and needs no floor; a zero does.

    This is the mutation that a symmetric `read >= MIN_CENSUS_READ` guard would
    pass while breaking the clause in the field: the home shell is 1 of 1
    inspected and was fetched 2026-10-29, so a symmetric floor makes it
    permanently unjudgeable and every section linked from the homepage silently
    drops out of the audit.
    """

    def test_one_inspected_url_that_was_fetched_counts_as_a_crawl_path(self):
        found = {"/x/": {"home shell", "guide hub"}}
        out = note(found, {"(root)": {"read": 1, "fetched": 1},
                           "guide": {"read": 10, "fetched": 0}})
        # The section is judged (the root is readable) and NOT flagged, because
        # one of its two sources is demonstrably fetched.
        self.assertNotIn(SECTION_CLAUSE, out)
        # ...and the unfetched SOURCE is still named, which is the other half.
        self.assertIn(SOURCE_CLAUSE, out)

    def test_a_homepage_linked_section_stays_IN_the_judged_denominator(self):
        # THE TEST THAT CLOSES THE MUTATION THAT SURVIVED THE FIRST ROUND on
        # 2026-11-02. Asserting only that the clause does not NAME the section
        # cannot tell "judged and clean" from "silently dropped": a symmetric
        # `read >= MIN_CENSUS_READ` floor drops every homepage-linked section
        # out of the audit entirely, and both readings print no name for it.
        # The denominator is the only place the difference is visible.
        reach = {"(root)": {"read": 1, "fetched": 1}, "dc": {"read": 20, "fetched": 0}}
        out = note({"/clean/": {"home shell"}, "/flagged/": {"dc browse hub"}}, reach)
        self.assertIn("1 of 2 linked sections", out)
        self.assertIn("/flagged/ ←", out)
        self.assertNotIn("/clean/", out)

    def test_the_source_half_also_keeps_a_one_of_one_fetched_family(self):
        # Same mutation, the other half: a symmetric floor would make the root
        # unjudgeable and shrink the source denominator with it.
        reach = {"(root)": {"read": 1, "fetched": 1}, "guide": {"read": 10, "fetched": 0}}
        out = note({"/x/": {"guide hub"}}, reach)
        self.assertIn("1 of 2 link-source families", out)

    def test_one_inspected_url_with_no_fetch_is_silence(self):
        self.assertEqual(note({"/x/": {"developers portal"}},
                              {"developers": {"read": 1, "fetched": 0}}), "")

    def test_the_section_leg_and_the_silent_leg_partition_every_read_fetched_pair(self):
        # The threshold closed over its whole input space rather than at one
        # point, which is how the 10-31 tail-swap mutation was caught.
        for read in range(0, 8):
            for fetched in range(0, 8):
                if fetched > read:
                    continue
                reach = {"guide": {"read": read, "fetched": fetched}}
                out = note({"/x/": {"guide hub"}}, reach)
                fired = SECTION_CLAUSE in out
                _, expected = review.never_fetched((), crawl={"read": read, "fetched": fetched})
                self.assertEqual(fired, expected, f"read={read} fetched={fetched}")
                if not fired and not fetched:
                    self.assertEqual(out, "", f"read={read} fetched={fetched}")

    def test_it_borrows_the_judges_threshold_rather_than_keeping_its_own(self):
        # If review.MIN_CENSUS_READ moves, this clause must move with it. A
        # second copy of the answer in techniques.py is the drift this guards.
        at = review.MIN_CENSUS_READ
        self.assertEqual(SECTION_CLAUSE in note({"/x/": {"guide hub"}},
                                                {"guide": {"read": at, "fetched": 0}}), True)
        self.assertEqual(note({"/x/": {"guide hub"}},
                              {"guide": {"read": at - 1, "fetched": 0}}), "")


class OnePredicateNotTwo(unittest.TestCase):
    """Both halves must route through _family_reach, not keep a copy each."""

    def test_the_judgement_lives_in_exactly_one_place(self):
        import inspect
        src = inspect.getsource(T._crawl_source_reach_note)
        # The CODE, not the docstring: prose may name the predicate it borrows.
        code = src.split('"""')[2]
        self.assertNotIn("never_fetched", code)
        self.assertNotIn("MIN_CENSUS_READ", code)
        # A bare `_family_reach(` also matches inside `_census_family_reach(`,
        # which is a different function and is called here once. Anchor it.
        import re
        self.assertEqual(len(re.findall(r"(?<![\w])_family_reach\(", code)), 2)
        self.assertIn("never_fetched", inspect.getsource(T._family_reach))

    def test_family_reach_is_silent_on_a_zero_it_cannot_substantiate(self):
        self.assertIsNone(T._family_reach({"read": 2, "fetched": 0}))
        self.assertIsNone(T._family_reach({}))
        self.assertIsNone(T._family_reach({"read": None, "fetched": 0}))

    def test_family_reach_trusts_a_single_fetch_without_a_floor(self):
        self.assertEqual(T._family_reach({"read": 1, "fetched": 1}), (1, 1, False))

    def test_family_reach_calls_a_substantiated_zero_never_fetched(self):
        self.assertEqual(T._family_reach({"read": 10, "fetched": 0}), (10, 0, True))


class WhatTheClauseSays(unittest.TestCase):

    def test_it_fires_on_the_live_shaped_reading_and_names_both_facts(self):
        found = {
            "/dc/neighborhood/": {"dc browse hub"},
            "/la/zip/": {"la browse hub"},
            "/sf/neighborhood/": {"sf browse hub"},
            "/building/": {"home shell", "nyc browse hub", "neighborhood hub"},
        }
        out = note(found, LIVE)
        self.assertIn(SOURCE_CLAUSE, out)
        self.assertIn(SECTION_CLAUSE, out)
        self.assertIn("/dc/neighborhood/ ← dc browse hub", out)
        self.assertIn("/la/zip/ ← la browse hub", out)
        # sf has one fetched URL, so it is judged and must NOT be named.
        self.assertNotIn("/sf/neighborhood/ ←", out)
        self.assertNotIn("/building/ ←", out)

    def test_every_fired_clause_quotes_its_own_denominator(self):
        out = note({"/dc/neighborhood/": {"dc browse hub"}}, LIVE)
        self.assertIn("0 of 20 inspected URLs ever fetched", out)
        self.assertIn("0 of 20 inspected", out)

    def test_the_section_count_is_out_of_judged_sections_not_all_sections(self):
        # A section nobody could judge must not inflate the denominator: that
        # would read as "we checked 7" when four of them were skipped.
        found = {"/a/": {"dc browse hub"},               # judged, flagged
                 "/b/": {"building page"},               # judged, clean
                 "/c/": {"developers portal"},           # unjudgeable (1 read, 0 fetched)
                 "/d/": set()}                           # orphan
        out = note(found, dict(LIVE, developers={"read": 1, "fetched": 0}))
        self.assertIn("1 of 2 linked sections", out)

    def test_the_source_sentence_fires_without_any_flagged_section(self):
        # 2026-11-02's actual finding: /guide/ is never flagged as a section
        # because the SF browse hub also links the city guides, and sf has one
        # fetched URL. The guide HUB is still never-fetched, and that fact is
        # about a source rather than a destination.
        found = {"/guide/is-my-apartment-rent-controlled-":
                 {"guide hub", "sf browse hub", "la browse hub", "dc browse hub"}}
        out = note(found, LIVE)
        self.assertNotIn(SECTION_CLAUSE, out)
        self.assertIn(SOURCE_CLAUSE, out)
        self.assertIn("guide (0 of 10 inspected)", out)

    def test_the_source_sentence_counts_families_not_source_labels(self):
        # Three of the audit's seventeen sources are dc pages; the census has
        # one dc stratum, and reporting "3 of 17" would triple-count it.
        out = note({"/a/": {"dc browse hub"}}, LIVE)
        self.assertIn("3 of 11 link-source families", out)

    def test_the_source_list_is_capped_and_says_how_many_it_withheld(self):
        # Closed a mutation that survived the 2026-11-02 round: dropping the
        # source cap left the clause correct on today's reading (3 unfetched
        # families, under the cap) and silently unbounded on a worse one.
        fams = sorted({T._source_family(p) for _, p, _ in T._crawl_sources()})
        self.assertGreater(len(fams), T.SOURCE_REACH_SHOWN + 1)
        reach = {f: {"read": 10, "fetched": 0} for f in fams}
        reach[fams[0]] = {"read": 10, "fetched": 4}          # one real crawl path
        out = note({"/x/": {"building page"}}, reach)
        self.assertIn(f"{len(fams) - 1} of {len(fams)} link-source families", out)
        self.assertIn(f"+{len(fams) - 1 - T.SOURCE_REACH_SHOWN} more", out)
        # Capped, so only SOURCE_REACH_SHOWN names are spelled out.
        self.assertEqual(sum(1 for f in fams if f"{f} (0 of 10 inspected)" in out),
                         T.SOURCE_REACH_SHOWN)

    def test_the_section_list_is_capped_and_says_how_many_it_withheld(self):
        found = {f"/s{i}/": {"dc browse hub"} for i in range(T.SOURCE_REACH_SHOWN + 3)}
        out = note(found, LIVE)
        self.assertIn(f"+{3} more", out)
        self.assertIn(f"{T.SOURCE_REACH_SHOWN + 3} of {T.SOURCE_REACH_SHOWN + 3} linked", out)


class ItIsWiredIntoTheAudit(unittest.TestCase):

    def test_the_clause_is_appended_to_every_branch_of_t_crawl_paths(self):
        # Appended to `tail`, which every return path concatenates, so an
        # orphaned section and a linked-but-unfetched one appear in one
        # sentence. Asserted on the source because reaching all five returns
        # needs a deployed docroot this checkout does not have.
        import inspect
        src = inspect.getsource(T.t_crawl_paths)
        self.assertIn("_crawl_source_reach_note(found, live)", src)
        self.assertIn("tail +=", src)

    def test_it_does_not_change_the_audits_pass_fail_semantics(self):
        # Report-only on purpose, exactly as click depth was on its first night
        # (see CRAWL_DEPTH_MAX). A check that goes red on a condition nobody can
        # act on tonight is a check that gets ignored.
        with open(T.__file__, encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("def _crawl_source_reach_note"):]
        body = body[:body.index("\ndef ", 1)]
        self.assertNotIn('"ok"', body)
        self.assertNotIn("ok=False", body)


class AgainstTonightsCensus(unittest.TestCase):
    """The one live read, and it SKIPS rather than fails when the branch is empty."""

    def test_the_live_census_is_readable_and_strata_carry_the_two_fields(self):
        reach = T._census_family_reach()
        if not reach:
            self.skipTest("no index_status.json in this checkout")
        for fam, rec in reach.items():
            if "read" in rec:
                self.assertIsInstance(rec["read"], int, fam)

    def test_tonights_reading_puts_at_least_one_source_family_on_the_branch(self):
        reach = T._census_family_reach()
        if not reach:
            self.skipTest("no index_status.json in this checkout")
        fams = {T._source_family(p) for _, p, _ in T._crawl_sources()}
        unfetched = [f for f in fams
                     if review.never_fetched((), crawl={
                         "read": (reach.get(f) or {}).get("read") or 0,
                         "fetched": (reach.get(f) or {}).get("fetched") or 0})[1]]
        if not unfetched:
            self.skipTest("no crawl-source family is census-confirmed never-fetched tonight")
        out = note({"/x/": {"dc browse hub"}}, reach)
        self.assertIn(SOURCE_CLAUSE, out)


if __name__ == "__main__":
    unittest.main()
