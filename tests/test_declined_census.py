"""A fetched-and-never-indexed tier must be told its pages were judged.

Why this exists (2026-11-04). growth/indexstatus.crawl_evidence() has said in
its own docstring since 2026-08-29 that a zero-impression reading has two
causes which "call for opposite decisions — retire the pages, or go get them
crawled". Only one of the two was ever stated. review.never_fetched() fires on
`fetched == 0` and says "go get them crawled"; everything else fell to a
sentence about Search Console — "its pages earned 0 search impressions" — which
reports an absence of impressions and asserts nothing whatever about what
Google decided about the pages.

So the louder half of the finding had no sentence, and the verdict that needed
it most got the weakest wording in the file. T046 /building/ on 2026-11-03: 250
inspected URLs, 159 fetched, 0 indexed, 0 EVER indexed, all 159 first read as
fetched more than MATURE_DAYS ago. Its stored verdict ended "nothing has been
measured about whether these pages can rank". A page Google has fetched and
declined cannot rank; that is not nothing measured, it is the decisive
measurement, and it had been sitting in index_status.json for weeks.

WHAT THESE TESTS GUARD, in order of how expensive the mistake is:

 1. The guard cannot fire on a tier Google has never fetched. The two
    sentences give OPPOSITE instructions — go get crawled, versus stop getting
    crawled and fix the pages — so an overlap is not a cosmetic defect, it is
    the loop being told to do both. Held as arithmetic over the input space.
 2. The guard cannot swallow an EVICTION. A tier Google accepted and later
    dropped is a third finding with a third remedy. T019's hubs are exactly
    that (24 settled, 0 indexed, 2 ever indexed) and must fall through.
 3. A reading taken before `settled` existed must not fire it. Every
    constructed reading written before tonight carries read/fetched and no
    more, and an absent count is silence under the rule the whole module runs
    on: an absent day is honest, a zero is a claim.
 4. The clause quotes the counts it fired on — the rule the 2026-10-28 entry
    drew about absence-shaped conditions, which this one is the mirror of.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import indexstatus, ledger, review  # noqa: E402

DECLINED = "seen and declined rather than missed"
NEVER_FETCHED = "Google has never fetched any of the"
FIX_THE_PAGES = "the next move is the pages themselves"
GET_CRAWLED = "get them crawled rather than to rewrite or retire them"
NOT_MEASURED = "nothing has been measured about whether these pages can rank"


def _reading(read=250, fetched=159, settled=159, indexed=0, ever_indexed=0):
    """A census reading with the maturity counts crawl_evidence now returns."""
    return {"cohort": read, "read": read, "fetched": fetched,
            "settled": settled, "settled_indexed": 0, "indexed": indexed,
            "ever_indexed": ever_indexed, "buckets": {}}


class ThePredicate(unittest.TestCase):
    """review.seen_and_declined(), driven on constructed readings only."""

    def test_fires_on_a_settled_tier_google_kept_none_of(self):
        _, fired = review.seen_and_declined((), crawl=_reading())
        self.assertTrue(fired)

    def test_below_the_settled_threshold_is_silence(self):
        n = review.MIN_CENSUS_SETTLED
        for settled in range(0, n):
            with self.subTest(settled=settled):
                _, fired = review.seen_and_declined(
                    (), crawl=_reading(fetched=settled, settled=settled))
                self.assertFalse(fired)
        _, fired = review.seen_and_declined(
            (), crawl=_reading(fetched=n, settled=n))
        self.assertTrue(fired)

    def test_an_eviction_is_not_a_decline(self):
        # T019's live shape. Google accepted two hub pages and later dropped
        # them; "never accepted one" is a different claim with a different
        # remedy, and this guard may not file them together.
        _, fired = review.seen_and_declined(
            (), crawl=_reading(read=90, fetched=24, settled=24, ever_indexed=2))
        self.assertFalse(fired)

    def test_an_indexed_page_in_the_tier_stops_it(self):
        _, fired = review.seen_and_declined((), crawl=_reading(indexed=1))
        self.assertFalse(fired)

    def test_a_reading_that_predates_the_maturity_counts_cannot_fire(self):
        # The pre-2026-11-04 shape, which is what every older constructed
        # reading in this suite's sibling files still is.
        _, fired = review.seen_and_declined((), crawl={"read": 250,
                                                       "fetched": 159})
        self.assertFalse(fired)

    def test_the_threshold_is_what_makes_absent_and_zero_agree(self):
        # WRITTEN TWICE, AND THE FIRST VERSION WAS WORTHLESS. It asserted
        # "settled is None" appeared in inspect.getsource(seen_and_declined),
        # to pin that the predicate distinguishes an ABSENT count from a zero
        # one. The 2026-11-04 mutation round rewrote the line to `not settled`
        # and the test stayed green — because the phrase also appears in that
        # function's own DOCSTRING, where this file put it. A source-text
        # assertion over a documented function tests the documentation.
        #
        # Behaviourally the two forms are EQUIVALENT today and that is worth
        # stating rather than hiding behind a green test: absent falls through
        # to `None >= 10`, which would raise, so it must be caught — and zero
        # falls through to `0 >= 10`, which is False. Same answer, by two
        # routes. What makes them agree is the threshold being POSITIVE, so
        # that is the thing pinned here. Drop MIN_CENSUS_SETTLED to 0 and the
        # forms diverge: `settled is None` still refuses an absent reading,
        # `not settled` would start firing on a measured zero. This test is the
        # tripwire for that edit.
        self.assertGreater(review.MIN_CENSUS_SETTLED, 0)
        _, absent = review.seen_and_declined((), crawl={"read": 250,
                                                        "fetched": 159})
        _, zero = review.seen_and_declined((), crawl=_reading(fetched=0,
                                                             settled=0))
        self.assertFalse(absent)
        self.assertFalse(zero)

    def test_an_absent_count_does_not_raise_on_the_comparison(self):
        # The one thing the `is None` guard genuinely buys: without it the
        # predicate compares None to an int. Held over readings that carry
        # neither maturity key at all, which is every reading written before
        # 2026-11-04.
        for crawl in ({"read": 0, "fetched": 0}, {"read": 4000, "fetched": 1},
                      {"read": 250, "fetched": 159}, {}):
            with self.subTest(crawl=crawl):
                _, fired = review.seen_and_declined((), crawl=crawl)
                self.assertFalse(fired)

    def test_no_prefixes_reads_zero_and_cannot_fire(self):
        # The documented hole both census guards leave open, held here too.
        ev = indexstatus.crawl_evidence(None)
        self.assertEqual(ev["read"], 0)
        self.assertEqual(ev["settled"], 0)
        _, fired = review.seen_and_declined(None, crawl=ev)
        self.assertFalse(fired)


class ItCannotOverlapTheNeverFetchedLeg(unittest.TestCase):
    """The expensive mistake: two sentences giving opposite instructions."""

    def test_never_fetched_and_declined_are_disjoint_over_the_input_space(self):
        # Arithmetic, not a convention: `settled` counts a subset of
        # `fetched`, so fetched == 0 forces settled == 0, which is below any
        # positive threshold. Driven over readings that respect that
        # containment, plus the inconsistent ones, which must also not overlap.
        for read in range(0, 14):
            for fetched in range(0, read + 1):
                for settled in range(0, fetched + 1):
                    crawl = _reading(read=read, fetched=fetched,
                                     settled=settled)
                    _, nf = review.never_fetched((), crawl=crawl)
                    _, dec = review.seen_and_declined((), crawl=crawl)
                    with self.subTest(read=read, fetched=fetched,
                                      settled=settled):
                        self.assertFalse(nf and dec)
                        if fetched == 0:
                            self.assertFalse(dec)

    def test_the_two_clauses_never_share_a_sentence(self):
        crawl = _reading()
        text, fired, _ = review.unseen_clause((), crawl=crawl)
        self.assertFalse(fired)
        self.assertNotIn(NEVER_FETCHED, text)
        self.assertIn(DECLINED, review.declined_clause((), crawl=crawl))
        self.assertEqual(review.declined_clause(
            (), crawl=_reading(fetched=0, settled=0)), "")


class TheClauseQuotesItsOwnCounts(unittest.TestCase):
    """A guard that asserts a judgement must print what it judged on."""

    def test_the_three_counts_appear_in_context(self):
        for read, fetched, settled in ((250, 159, 159), (40, 31, 12),
                                       (999, 500, 400)):
            clause = review.declined_clause(
                (), crawl=_reading(read=read, fetched=fetched,
                                   settled=settled))
            with self.subTest(read=read):
                # In context, not anywhere in the string: a bare `str(n) in
                # clause` passes on a digit inside the MATURE_DAYS number and
                # proved exactly that on 2026-10-31's sibling guard.
                self.assertIn(f"fetched {fetched} of the {read} of its URLs",
                              clause)
                self.assertIn(f"{settled} of those were first read as fetched",
                              clause)

    def test_it_names_the_maturity_window_it_used(self):
        clause = review.declined_clause((), crawl=_reading())
        self.assertIn(f"more than {indexstatus.MATURE_DAYS} days ago", clause)

    def test_it_says_never_indexed_and_not_merely_not_indexed_now(self):
        # The guard turns on ever_indexed, so the sentence must claim the
        # stronger thing the guard actually checked.
        clause = review.declined_clause((), crawl=_reading())
        self.assertIn("not one has ever been indexed", clause)


class TheVerdictProse(unittest.TestCase):
    """What a reader six months from now is handed."""

    def test_the_declined_tail_points_at_the_pages_not_the_crawler(self):
        t = next((x for x in ledger.active()
                  if x.get("slug") == "derived_building_facts"), None)
        if t is None:
            self.skipTest("derived_building_facts is not active here")
        _, fired = review.seen_and_declined(t.get("prefixes"))
        if not fired:
            self.skipTest("the live /building/ census no longer declines")
        r = review.evaluate(t)
        self.assertIn(DECLINED, r["why"])
        self.assertIn(FIX_THE_PAGES, r["why"])
        # The opposite instruction, and the sentence this change removes.
        self.assertNotIn(GET_CRAWLED, r["why"])
        self.assertNotIn(NOT_MEASURED, r["why"])

    def test_the_counts_are_recorded_and_not_only_narrated(self):
        t = next((x for x in ledger.active()
                  if x.get("slug") == "derived_building_facts"), None)
        if t is None:
            self.skipTest("derived_building_facts is not active here")
        _, fired = review.seen_and_declined(t.get("prefixes"))
        if not fired:
            self.skipTest("the live /building/ census no longer declines")
        r = review.evaluate(t)
        ev = indexstatus.crawl_evidence(t.get("prefixes"))
        for key, val in (("census_read", ev["read"]),
                         ("census_fetched", ev["fetched"]),
                         ("census_settled", ev["settled"]),
                         ("census_ever_indexed", ev["ever_indexed"])):
            self.assertEqual(r["measured"].get(key), val, key)

    def test_the_guard_changes_a_reason_and_never_an_action(self):
        # Same rule as the never-fetched guard: this is a change to a reason.
        # If it ever starts retiring or passing something it has outgrown its
        # own rationale, and `works` must never become True — scout.py feeds
        # the WORKS list to the model as ALREADY MEASURED AS WORKING.
        for t in ledger.active():
            _, fired = review.seen_and_declined(t.get("prefixes"))
            if not fired:
                continue
            r = review.evaluate(t)
            with self.subTest(slug=t.get("slug")):
                self.assertIsNot(r["works"], True)
                self.assertNotEqual(r.get("action"), "retire")

    def test_the_brand_sentence_drops_its_contradicted_clause(self):
        # The half of the fix inside _owned_brand_reading: that sentence used
        # to deny a measurement the census had already taken.
        vis = {"measured": True, "brand_measured": True, "pages": 9,
               "impressions": 27, "nonbranded_pages": 0,
               "nonbranded_impressions": 0, "unattributed_pages": 9}
        _, plain = review._owned_brand_reading(vis)
        _, declined = review._owned_brand_reading(vis, declined=True)
        self.assertIn(NOT_MEASURED, plain)
        self.assertNotIn(NOT_MEASURED, declined)
        # Everything else about the sentence is unchanged.
        self.assertIn("unattributed", declined)
        self.assertIn("not measured as housing-intent", declined)


class TheCensusReadingItself(unittest.TestCase):
    """indexstatus.crawl_evidence()'s new counts."""

    def test_settled_is_a_subset_of_fetched_everywhere(self):
        for t in ledger.active():
            ev = indexstatus.crawl_evidence(t.get("prefixes"))
            with self.subTest(slug=t.get("slug")):
                self.assertLessEqual(ev["settled"], ev["fetched"])
                self.assertLessEqual(ev["fetched"], ev["read"])
                self.assertLessEqual(ev["indexed"], ev["read"])
                self.assertLessEqual(ev["settled_indexed"], ev["settled"])

    def test_the_old_keys_still_mean_what_they_meant(self):
        # Back-compat: the four pre-existing keys must be untouched by the
        # three new ones, because review.never_fetched() reads two of them.
        ev = indexstatus.crawl_evidence(("/building/",))
        for key in ("cohort", "read", "fetched", "buckets"):
            self.assertIn(key, ev)
        self.assertEqual(ev["fetched"],
                         sum(v for k, v in ev["buckets"].items()
                             if k in ("crawled_not_indexed", "indexed")))

    def test_the_acceptance_counts_are_actually_counted(self):
        # THE 2026-11-04 MUTATION ROUND FOUND NOTHING WATCHING THESE. Breaking
        # the `indexed` tally, and separately the `ever_indexed` tally, left
        # every suite green — because no live technique has an indexed URL
        # under its prefixes (site-wide the count is 1, the homepage, which no
        # technique owns), and every other test in this file passes the counts
        # in ready-made rather than deriving them. A guard whose whole job is
        # to distinguish declined from evicted was resting on an ever_indexed
        # tally nothing had ever observed being incremented.
        #
        # Constructed cohort, far-future clock, one URL per case, so each
        # count is read where it differs from the others.
        cohort = {
            "https://x/building/kept/": {
                "checked": "2026-01-01", "state": "Submitted and indexed",
                "crawled": "2026-01-01", "first_checked": "2026-01-01",
                "first_indexed": "2026-01-01"},
            "https://x/building/evicted/": {
                "checked": "2026-01-01",
                "state": "Crawled - currently not indexed",
                "crawled": "2026-01-01", "first_checked": "2026-01-01",
                "first_indexed": "2026-01-01"},
            "https://x/building/declined/": {
                "checked": "2026-01-01",
                "state": "Crawled - currently not indexed",
                "crawled": "2026-01-01", "first_checked": "2026-01-01"},
            "https://x/building/unfetched/": {
                "checked": "2026-01-01",
                "state": "URL is unknown to Google"},
        }
        ev = indexstatus.crawl_evidence(("/building/",), cohort=cohort,
                                        today="2030-01-01")
        self.assertEqual(ev["read"], 4)
        self.assertEqual(ev["fetched"], 3)
        self.assertEqual(ev["settled"], 3)
        self.assertEqual(ev["indexed"], 1, "indexed bucket not tallied")
        self.assertEqual(ev["settled_indexed"], 1)
        self.assertEqual(ev["ever_indexed"], 2,
                         "first_indexed stamps not tallied — the evicted URL "
                         "must count, which is the whole discriminator")
        # And the guard reads them: this tier has an indexed page AND an
        # eviction, so it is not a declined tier on either test.
        _, fired = review.seen_and_declined((), crawl=ev)
        self.assertFalse(fired)

    def test_the_new_counts_reach_results_jsonl_as_series(self):
        # A count that only ever appears inside a verdict STRING cannot be
        # trended, and the trend is the point: `settled` rising while
        # `census_indexed` stays flat is the finding. record_technique_reach
        # is where that happens, and dropping the census_settled write was a
        # third mutation nothing caught.
        written = []
        real = indexstatus.ledger.record_result
        indexstatus.ledger.record_result = (
            lambda day, slug, metric, value: written.append((slug, metric,
                                                             value)))
        try:
            cohort = {"https://x/building/a/": {
                "checked": "2026-01-01",
                "state": "Crawled - currently not indexed",
                "crawled": "2026-01-01", "first_checked": "2026-01-01"}}
            n = indexstatus.record_technique_reach(
                "2030-01-01", cohort,
                techs=[{"slug": "t", "prefixes": ["/building/"]}])
        finally:
            indexstatus.ledger.record_result = real
        self.assertEqual(n, 1)
        metrics = {m: v for _s, m, v in written}
        for metric in ("census_cohort", "census_read", "census_known",
                       "census_fetched", "census_settled", "census_indexed",
                       "census_ever_indexed"):
            self.assertIn(metric, metrics)
        self.assertEqual(metrics["census_settled"], 1)
        self.assertEqual(metrics["census_indexed"], 0)
        self.assertEqual(metrics["census_ever_indexed"], 0)

    def test_the_read_gate_still_holds_back_an_unread_tier(self):
        # The rule record_technique_reach already states — an absent day is
        # honest, a zero is a claim — must cover the three new series too, or
        # a tier the sampler has never reached starts publishing zeros that
        # look like measurements.
        written = []
        real = indexstatus.ledger.record_result
        indexstatus.ledger.record_result = (
            lambda day, slug, metric, value: written.append(metric))
        try:
            indexstatus.record_technique_reach(
                "2030-01-01", {},
                techs=[{"slug": "t", "prefixes": ["/nothing-here/"]}])
        finally:
            indexstatus.ledger.record_result = real
        self.assertEqual(written, ["census_cohort"])

    def test_today_is_injectable_so_maturity_is_testable(self):
        # settled is an age test, so it needs a clock that does not move under
        # the suite. A far-future `today` matures everything fetched.
        cohort = {"https://x/building/a/": {"checked": "2026-01-01",
                                            "state": "URL is unknown to Google",
                                            "crawled": "2026-01-01",
                                            "first_checked": "2026-01-01"}}
        near = indexstatus.crawl_evidence(("/building/",), cohort=cohort,
                                          today="2026-01-02")
        far = indexstatus.crawl_evidence(("/building/",), cohort=cohort,
                                         today="2030-01-01")
        self.assertEqual(near["settled"], 0)
        self.assertEqual(far["settled"], 1)
        self.assertEqual(near["fetched"], far["fetched"])


if __name__ == "__main__":
    unittest.main()
