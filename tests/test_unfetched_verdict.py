"""A zero-impression verdict must say whether Google ever looked — on BOTH branches.

Why these exist (2026-10-31). "This technique's pages earned 0 search
impressions" has two causes that read identically in the number and call for
opposite work: Google looked and declined the pages (rewrite or retire them),
or Google never requested one (go get them crawled). growth/review.py has
asked which since 2026-08-29 — but only inside the branch a technique reaches
when its traffic is BELOW the retirement floor, the branch that was destroying
T002, T013 and T023 on never-fetched URLs.

A technique ABOVE the floor cannot reach that branch. It takes the `unseen`
path instead, which had no census guard, so it carried "its pages earned 0
search impressions ... none of those visitors arrived from a search" forever
with no way to say whether Google looked. That was live on T001 /section8/ on
2026-10-31: 33 owned visitors in 67d, 0 impressions, and 6 of 6 inspected URLs
never fetched. The ACTION was right both before and after this change — the
technique is kept, works stays None — so what these tests pin is the REASON,
which is the half that is read six months later and acted on.

The guard is deliberately narrow and three of these tests are about its edges
rather than its hit: below MIN_CENSUS_READ inspected URLs is silence and must
not fire it, a technique that declares no prefixes must fall through, and a
technique whose URLs Google HAS fetched must keep the old wording, because for
that one the zero really is a fact about the pages.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import indexstatus, ledger, review  # noqa: E402

# The two tails, keyed off the clause each is supposed to appear beside. Pinned
# as substrings rather than whole strings so rewording the prose does not fail
# these, while swapping which branch gets which does.
CRAWL_REACH = "measure crawl reach and not these pages"
NEVER_FETCHED = "Google has never fetched any of the"
OLD_WORDING = "its pages earned 0 search impressions over the same window"
GET_CRAWLED = "get them crawled rather than to rewrite or retire them"
TRAFFIC_IS_REAL = "the traffic is real and above"


class _Fake:
    """review.evaluate() reads a technique dict; only `prefixes` matters here."""


def _ev(slug):
    t = next((x for x in ledger.active() if x.get("slug") == slug), None)
    if t is None:
        raise unittest.SkipTest(f"{slug} is not active in this checkout")
    return t, review.evaluate(t)


class TheGuardFiresWhereGoogleNeverLooked(unittest.TestCase):
    """T001 /section8/ is the live case this change was written for."""

    def test_t001_names_the_crawl_and_not_the_pages(self):
        t, r = _ev("fresh_section8")
        self.assertIn(NEVER_FETCHED, r["why"])
        self.assertIn(CRAWL_REACH, r["why"])

    def test_t001_no_longer_says_the_pages_earned_nothing(self):
        # The sentence this change removes. It is true and it is the wrong
        # fact: it reads as Google declining pages it never requested.
        t, r = _ev("fresh_section8")
        self.assertNotIn(OLD_WORDING, r["why"])

    def test_t001_points_the_next_run_at_the_crawl_not_a_rewrite(self):
        t, r = _ev("fresh_section8")
        self.assertIn(GET_CRAWLED, r["why"])
        # "the traffic is real and above the floor" belongs to the other leg.
        # Beside a never-fetched tier it invites a content verdict.
        self.assertNotIn(TRAFFIC_IS_REAL, r["why"])

    def test_t001_quotes_its_own_denominator(self):
        # A guard that fires on an absence must print the count it fired on,
        # or a later reader cannot tell evidence from silence. Same rule the
        # 2026-10-28 entry drew about absence-shaped conditions.
        t, r = _ev("fresh_section8")
        ev = indexstatus.crawl_evidence(t.get("prefixes"))
        self.assertGreaterEqual(ev["read"], review.MIN_CENSUS_READ)
        self.assertEqual(ev["fetched"], 0)
        # In context, not anywhere in the string: a bare `str(read) in why`
        # passes on the digit inside "67d" and proved it on 2026-10-31.
        self.assertIn(f"any of the {ev['read']} of its URLs", r["why"])


class TheActionIsUnchanged(unittest.TestCase):
    """This is a change to a reason, not to a decision. If it ever starts
    retiring or passing something, it has outgrown its own rationale."""

    def test_t001_is_still_kept_and_still_unproven(self):
        t, r = _ev("fresh_section8")
        self.assertIsNone(r["works"])
        self.assertNotEqual(r.get("action"), "retire")

    def test_the_guard_never_produces_a_works(self):
        # works=True requires `not unseen`; both legs set unseen non-empty, so
        # neither can launder a never-crawled tier into the WORKS list that
        # scout.py feeds the model as ALREADY MEASURED AS WORKING.
        for slug in ("fresh_section8",):
            t, r = _ev(slug)
            self.assertIsNot(r["works"], True)


class TheGuardIsNarrow(unittest.TestCase):
    """Its edges, which are the whole reason it is safe."""

    def test_a_fetched_tier_keeps_the_old_wording(self):
        # T019's hubs: 24 of 90 inspected URLs HAVE been fetched, so its zero
        # really is Google looking and not showing them. The old sentence is
        # the correct one here and must survive.
        t, r = _ev("hub_direct_answers")
        ev = indexstatus.crawl_evidence(t.get("prefixes"))
        self.assertGreater(ev["fetched"], 0)
        self.assertIn(OLD_WORDING, r["why"])
        self.assertNotIn(NEVER_FETCHED, r["why"])

    def test_below_the_read_threshold_is_silence(self):
        # Fewer than MIN_CENSUS_READ inspected URLs is a statement about
        # nothing. Built as a prefix the census holds almost none of.
        ev = indexstatus.crawl_evidence(("/embed/",))
        self.assertLess(ev["read"], review.MIN_CENSUS_READ)
        self.assertEqual(ev["fetched"], 0)

    def test_no_prefixes_reads_zero_and_cannot_fire(self):
        # The documented hole, shared with the retirement guard: a technique
        # declaring no prefixes gets read=0 and falls through unchanged. It
        # must not be laundered into "never fetched".
        ev = indexstatus.crawl_evidence(None)
        self.assertEqual(ev["read"], 0)
        self.assertLess(ev["read"], review.MIN_CENSUS_READ)

    def test_the_brand_leg_is_untouched(self):
        # T046 /building/ earns impressions, all branded. That is a different
        # finding with its own wording and this change must not reach it.
        t, r = _ev("derived_building_facts")
        self.assertIn("came from branded queries", r["why"])
        self.assertNotIn(NEVER_FETCHED, r["why"])


class TheEvidenceIsRecorded(unittest.TestCase):
    """The counts go into res['measured'], not only into the prose, so a later
    run can read them without re-parsing a sentence."""

    def test_census_counts_are_exposed_on_this_path(self):
        t, r = _ev("fresh_section8")
        self.assertEqual(r["measured"].get("census_fetched"), 0)
        self.assertGreaterEqual(r["measured"].get("census_read"),
                                review.MIN_CENSUS_READ)

    def test_counts_are_recorded_even_when_the_guard_does_not_fire(self):
        # T019 takes the same branch and does not fire. The numbers that
        # decided that should still be readable.
        t, r = _ev("hub_direct_answers")
        self.assertGreater(r["measured"].get("census_fetched"), 0)


class ThePredicateItself(unittest.TestCase):
    """review.never_fetched(), tested without going through evaluate().

    These exist because of a 2026-10-31 miss. The threshold was reachable only
    through evaluate(), so it was exercised by whichever techniques happened to
    be active — and deleting the `>= MIN_CENSUS_READ` term changed no live
    verdict and failed no test. The guard's narrowness is the only reason it is
    safe to fire, so it needs tests that do not depend on tonight's ledger.
    """

    def test_fires_on_a_tier_read_enough_and_never_fetched(self):
        crawl, fired = review.never_fetched(("/section8/",))
        self.assertGreaterEqual(crawl["read"], review.MIN_CENSUS_READ)
        self.assertEqual(crawl["fetched"], 0)
        self.assertTrue(fired)

    def test_does_not_fire_below_the_read_threshold(self):
        # /embed/ is one inspected URL, never fetched. Same shape as the tier
        # above and must NOT fire: one URL is a statement about nothing.
        crawl, fired = review.never_fetched(("/embed/",))
        self.assertLess(crawl["read"], review.MIN_CENSUS_READ)
        self.assertEqual(crawl["fetched"], 0)
        self.assertFalse(fired)

    def test_does_not_fire_where_google_has_fetched(self):
        crawl, fired = review.never_fetched(("/building/",))
        self.assertGreater(crawl["fetched"], 0)
        self.assertFalse(fired)

    def test_does_not_fire_without_prefixes(self):
        for empty in (None, (), []):
            crawl, fired = review.never_fetched(empty)
            self.assertEqual(crawl["read"], 0)
            self.assertFalse(fired)

    def test_the_threshold_is_the_boundary_it_claims(self):
        # Pins the comparison as >=, not >. A prefix read exactly
        # MIN_CENSUS_READ times with nothing fetched is evidence, per
        # MIN_CENSUS_READ's own rationale ("three is deliberately low").
        crawl, fired = review.never_fetched(
            ("/guide/is-my-apartment-rent-controlled-",))
        self.assertEqual(crawl["read"], review.MIN_CENSUS_READ)
        self.assertEqual(crawl["fetched"], 0)
        self.assertTrue(fired)


class TheRealCorpus(unittest.TestCase):
    """Every active technique the census can speak for, checked against the
    committed index_status.json — so this does not pass on a fixture alone."""

    def test_every_zero_impression_verdict_says_which_cause(self):
        for t in ledger.active():
            if not t.get("prefixes"):
                continue
            ev = indexstatus.crawl_evidence(t["prefixes"])
            r = review.evaluate(t)
            why = r.get("why") or ""
            if NEVER_FETCHED not in why:
                continue
            # If it claims never-fetched, the census must actually say so.
            self.assertGreaterEqual(ev["read"], review.MIN_CENSUS_READ, t.get("slug"))
            self.assertEqual(ev["fetched"], 0, t.get("slug"))

    def test_no_technique_gets_both_wordings(self):
        for t in ledger.active():
            why = review.evaluate(t).get("why") or ""
            self.assertFalse(NEVER_FETCHED in why and OLD_WORDING in why,
                             t.get("slug"))

    def test_guard_eligible_techniques_are_never_retired_on_a_zero(self):
        # The point of the whole family of guards: a tier Google has never
        # fetched must not be retired for earning no impressions, on either
        # branch.
        for t in ledger.active():
            if not t.get("prefixes"):
                continue
            ev = indexstatus.crawl_evidence(t["prefixes"])
            if ev["read"] >= review.MIN_CENSUS_READ and ev["fetched"] == 0:
                r = review.evaluate(t)
                self.assertNotEqual(r.get("action"), "retire", t.get("slug"))
                self.assertIsNot(r.get("works"), False, t.get("slug"))


if __name__ == "__main__":
    unittest.main()
