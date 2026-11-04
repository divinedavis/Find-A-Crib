"""A tier Google accepted and later dropped must be told so — on its own branch.

Why this exists (2026-11-05). Two findings, and the second is the expensive one.

1. THE EVICTION SENTENCE. review.seen_and_declined() shipped 2026-11-04 with
   `ever_indexed == 0` as one of its three conditions, and its own docstring
   named the case it was excluding: "T019's hub tier is 24 settled / 0 indexed /
   2 ever indexed, and 'Google took two of its pages and later dropped them'
   has a different remedy from 'Google never took one'. Those fall through to
   the old wording until someone writes the eviction sentence they deserve."
   Nobody had. A tier that cleared Google's bar once and lost it is the third
   of the three findings indexstatus.crawl_evidence can distinguish, and it had
   no words at all.

2. THE CLAUSE WAS ON ONE BRANCH OF FOUR. declined_clause() was appended to the
   `unseen` string, and `unseen` is read by exactly one of the four verdicts
   review.evaluate() builds on the per-prefix path — `alive_now and not
   falling`. T019 is not alive_now: its trailing 14d median is 0.0/day, so it
   lands on the below-the-floor branch. On 2026-11-04 its stored verdict ended
   ", 0 pages serving in search" while its own `measured` record carried
   census_read 90 and census_fetched 24. The reading was taken, written into
   the ledger, and dropped on the floor by the sentence that was supposed to
   report it — so the technique the guard was designed around could never have
   received it.

   That is the harder defect to catch, because the verdict it published was
   TRUE. A verdict audit looks for a sentence that says too much; this one said
   nothing, and no amount of re-reading the string would have shown it.

WHAT THESE TESTS GUARD, in order of how expensive the mistake is:

 1. `evicted` is NOT ever_indexed - indexed. crawl_evidence excludes the
    `unknown` bucket from the eviction half exactly as summarise() has since
    2026-09-30, because `unknown` means Google returned no coverageState at
    all — an instrument condition. The subtraction cannot make that exclusion
    and therefore RISES WHEN THE INSPECTION API GOES QUIET, which would turn an
    outage into a finding about Google's behaviour. The two agreed site-wide on
    the night the wrong formula was written into a docstring (ever_indexed 3,
    indexed 1, evicted 2), which is the most dangerous way for it to read.
 2. The three findings are mutually exclusive over the whole input space. They
    give different instructions — go get crawled, fix the pages, find out what
    changed — so an overlap is the loop being told to do two of them.
 3. The clause reaches the verdict on every branch of the per-prefix path, each
    carrying the right instruction, with the declined wording unchanged.
 4. A reading taken before `evicted` existed does not fire it: absent is
    silence, not zero.
 5. The clause quotes the counts it fired on and calls its own count a floor.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import indexstatus, review  # noqa: E402

EVICTED = "accepted and later dropped rather than never taken"
DECLINED = "seen and declined rather than missed"
NEVER_FETCHED = "Google has never fetched any of the"
FLOOR = "is a floor: the census can only count a URL whose first-indexed date"


def _reading(read=90, fetched=24, settled=24, indexed=0, ever_indexed=2,
             evicted=2, last_crawl="2026-08-24"):
    """T019's live shape by default, with the counts crawl_evidence returns."""
    return {"cohort": read, "read": read, "fetched": fetched,
            "settled": settled, "settled_indexed": 0, "indexed": indexed,
            "ever_indexed": ever_indexed, "evicted": evicted,
            "evicted_last_crawl": last_crawl, "buckets": {}}


class TheEvictionCount(unittest.TestCase):
    """indexstatus.crawl_evidence()'s `evicted`, over constructed cohorts.

    Driven on cohort dicts rather than on the live file: the live census holds
    exactly two evicted URLs and neither of them is in the `unknown` bucket, so
    the one case that separates the right formula from the wrong one does not
    exist in the corpus and never has.
    """

    def _cohort(self, **states):
        return {f"https://findacrib.com/hub/{n}/": rec
                for n, rec in states.items()}

    def test_an_accepted_page_now_un_indexed_is_evicted(self):
        ev = indexstatus.crawl_evidence(
            ("/hub/",),
            cohort=self._cohort(a={"checked": "2026-11-04",
                                   "state": "Crawled - currently not indexed",
                                   "crawled": "2026-08-24",
                                   "first_checked": "2026-08-22",
                                   "first_indexed": "2026-08-18"}),
            today="2026-11-05")
        self.assertEqual(ev["ever_indexed"], 1)
        self.assertEqual(ev["evicted"], 1)
        self.assertEqual(ev["indexed"], 0)

    def test_a_page_still_indexed_is_not_evicted(self):
        ev = indexstatus.crawl_evidence(
            ("/hub/",),
            cohort=self._cohort(a={"checked": "2026-11-04",
                                   "state": "Submitted and indexed",
                                   "crawled": "2026-11-01",
                                   "first_checked": "2026-08-22",
                                   "first_indexed": "2026-08-18"}),
            today="2026-11-05")
        self.assertEqual(ev["ever_indexed"], 1)
        self.assertEqual(ev["indexed"], 1)
        self.assertEqual(ev["evicted"], 0)

    def test_an_unknown_bucket_is_an_outage_and_not_an_eviction(self):
        """THE CASE THE SUBTRACTION GETS WRONG.

        Google returned no coverageState for a page we have seen indexed.
        ever_indexed 1, indexed 0 — so `ever_indexed - indexed` says one page
        was evicted, and nothing was: the Inspection API went quiet.
        summarise() has excluded this since 2026-09-30 and crawl_evidence now
        excludes it too, so the two instruments cannot disagree about one URL.
        """
        ev = indexstatus.crawl_evidence(
            ("/hub/",),
            cohort=self._cohort(a={"checked": "2026-11-04",
                                   "state": "",
                                   "bucket": "unknown",
                                   "crawled": "2026-08-24",
                                   "first_checked": "2026-08-22",
                                   "first_indexed": "2026-08-18"}),
            today="2026-11-05")
        self.assertEqual(indexstatus.bucket(""), "unknown")
        self.assertEqual(ev["ever_indexed"], 1)
        self.assertEqual(ev["indexed"], 0)
        self.assertEqual(ev["evicted"], 0,
                         "an unknown coverage state is the instrument being "
                         "quiet, not Google dropping the page")
        self.assertEqual(ev["ever_indexed"] - ev["indexed"], 1,
                         "and the subtraction a reader would write gets it "
                         "wrong, which is why this count exists")

    def test_the_newest_fetch_among_dropped_urls_is_reported(self):
        """And it must be the NEWEST, not the last one the loop happened to see.

        Walked in both cohort orders because the first version of this test put
        the newer URL second, where "keep the newest" and "keep whichever came
        last" give the same answer — a mutation replacing the comparison with
        an unconditional assignment survived the whole suite.
        """
        dropped = {
            "a": {"checked": "2026-11-04", "crawled": "2026-08-19",
                  "state": "Crawled - currently not indexed",
                  "first_checked": "2026-08-22", "first_indexed": "2026-08-18"},
            "b": {"checked": "2026-11-04", "crawled": "2026-08-24",
                  "state": "Crawled - currently not indexed",
                  "first_checked": "2026-08-23", "first_indexed": "2026-08-19"},
            # Fetched most recently of the three and NEVER indexed, so its
            # crawl date must not leak into a count about dropped URLs.
            "c": {"checked": "2026-11-04", "crawled": "2026-11-01",
                  "state": "Crawled - currently not indexed",
                  "first_checked": "2026-08-23"},
        }
        for order in (("a", "b", "c"), ("c", "b", "a"), ("b", "a", "c")):
            with self.subTest(order=order):
                ev = indexstatus.crawl_evidence(
                    ("/hub/",),
                    cohort=self._cohort(**{k: dropped[k] for k in order}),
                    today="2026-11-05")
                self.assertEqual(ev["evicted"], 2)
                self.assertEqual(ev["evicted_last_crawl"], "2026-08-24")

    def test_no_eviction_leaves_the_date_absent(self):
        ev = indexstatus.crawl_evidence(
            ("/hub/",),
            cohort=self._cohort(a={"checked": "2026-11-04", "crawled": "2026-08-19",
                                   "state": "Crawled - currently not indexed",
                                   "first_checked": "2026-08-22"}),
            today="2026-11-05")
        self.assertEqual(ev["evicted"], 0)
        self.assertIsNone(ev["evicted_last_crawl"])

    def test_the_live_hub_tier_reads_as_t019(self):
        """The reading the whole change was written for, against the real file.

        A level, not a pin: if the sampler re-reads these two URLs and Google
        has taken them back, this goes red and the RIGHT fix is to delete the
        test and write the journal entry, which would be the best news this
        site has had. It is here so that moment cannot pass unnoticed.
        """
        ev = indexstatus.crawl_evidence(("/neighborhood/", "/borough/", "/zip/"))
        self.assertEqual(ev["indexed"], 0)
        self.assertGreaterEqual(ev["evicted"], 1)
        self.assertLessEqual(ev["evicted"], ev["ever_indexed"])


class TheNightlySeries(unittest.TestCase):
    """record_technique_reach must actually WRITE the count.

    Added because a mutation that deleted the census_evicted write left every
    suite green — the same blind spot 2026-11-03's first mutation round found
    for census_settled and census_indexed, which is a blind spot this loop has
    now walked into twice. A count that lives only inside a verdict string
    cannot be trended, and for eviction the trend is the finding: census_evicted
    rising is Google taking more pages back, and no verdict string shows that.
    """

    def _written(self, cohort, prefixes=("/hub/",)):
        written = []
        real = indexstatus.ledger.record_result
        indexstatus.ledger.record_result = (
            lambda day, slug, metric, value: written.append((metric, value)))
        try:
            n = indexstatus.record_technique_reach(
                "2030-01-01", cohort,
                techs=[{"slug": "t", "prefixes": list(prefixes)}])
        finally:
            indexstatus.ledger.record_result = real
        return n, dict(written)

    def test_census_evicted_is_recorded_with_the_other_seven(self):
        n, metrics = self._written({"https://x/hub/a/": {
            "checked": "2026-01-01",
            "state": "Crawled - currently not indexed",
            "crawled": "2026-01-01", "first_checked": "2026-01-01",
            "first_indexed": "2026-01-01"}})
        self.assertEqual(n, 1)
        for metric in ("census_cohort", "census_read", "census_known",
                       "census_fetched", "census_settled", "census_indexed",
                       "census_ever_indexed", "census_evicted"):
            self.assertIn(metric, metrics)
        self.assertEqual(metrics["census_evicted"], 1)
        self.assertEqual(metrics["census_ever_indexed"], 1)
        self.assertEqual(metrics["census_indexed"], 0)

    def test_it_is_zero_and_not_absent_on_a_tier_with_no_eviction(self):
        """A read tier with no eviction publishes a zero, which is a
        measurement; the read gate below is what withholds a non-measurement."""
        _, metrics = self._written({"https://x/hub/a/": {
            "checked": "2026-01-01",
            "state": "Crawled - currently not indexed",
            "crawled": "2026-01-01", "first_checked": "2026-01-01"}})
        self.assertEqual(metrics["census_evicted"], 0)

    def test_the_read_gate_still_covers_the_new_series(self):
        _, metrics = self._written({}, prefixes=("/nothing-here/",))
        self.assertEqual(list(metrics), ["census_cohort"])


class ThePredicate(unittest.TestCase):
    """review.seen_and_evicted(), on constructed readings only."""

    def test_fires_on_a_tier_that_lost_every_index_slot_it_held(self):
        _, fired = review.seen_and_evicted((), crawl=_reading())
        self.assertTrue(fired)

    def test_one_eviction_is_enough(self):
        self.assertEqual(review.MIN_CENSUS_EVICTED, 1)
        _, fired = review.seen_and_evicted(
            (), crawl=_reading(ever_indexed=1, evicted=1))
        self.assertTrue(fired)

    def test_zero_evictions_is_not_a_finding(self):
        _, fired = review.seen_and_evicted(
            (), crawl=_reading(ever_indexed=0, evicted=0))
        self.assertFalse(fired)

    def test_a_tier_that_still_holds_an_index_slot_falls_through(self):
        """Churn inside a partly-indexed tier is a different shape.

        A tier with a foothold is not one to rewrite, so the guard declines to
        file it under a sentence whose instruction is "find out what changed".
        """
        _, fired = review.seen_and_evicted((), crawl=_reading(indexed=3))
        self.assertFalse(fired)

    def test_a_reading_from_before_the_count_existed_is_silence(self):
        old = {"cohort": 90, "read": 90, "fetched": 24, "buckets": {}}
        _, fired = review.seen_and_evicted((), crawl=old)
        self.assertFalse(fired)
        settled_era = dict(old, settled=24, settled_indexed=0, indexed=0,
                           ever_indexed=2)
        _, fired = review.seen_and_evicted((), crawl=settled_era)
        self.assertFalse(fired, "the 2026-11-04 readings carry no `evicted`")

    def test_absent_is_distinguished_from_zero_by_the_threshold_being_positive(self):
        """The two forms are equivalent only while the threshold is positive.

        `evicted is None` must be caught or the comparison raises against an
        int; an explicit 0 falls through on 0 >= 1. What is pinned is the
        threshold being positive, which is the tripwire if anyone sets it to 0.
        Written this way after 2026-11-03's lesson that an assertion over
        inspect.getsource() can be satisfied by the docstring it is testing.
        """
        self.assertGreater(review.MIN_CENSUS_EVICTED, 0)
        _, fired = review.seen_and_evicted((), crawl=_reading(evicted=0,
                                                              ever_indexed=0))
        self.assertFalse(fired)


class TheThreeFindingsAreExclusive(unittest.TestCase):
    """Over the input space, not on the readings that happen to be live.

    The three give different instructions, so two of them firing on one
    technique is the loop being told to do two incompatible things.
    """

    def test_never_fetched_and_evicted_cannot_both_fire(self):
        for fetched in range(0, 30):
            for evicted in range(0, 4):
                # An evicted URL was necessarily crawled, so the only readings
                # worth walking are the self-consistent ones.
                if evicted and not fetched:
                    continue
                r = _reading(fetched=fetched, settled=fetched, evicted=evicted,
                             ever_indexed=max(evicted, 0))
                with self.subTest(fetched=fetched, evicted=evicted):
                    _, unfetched = review.never_fetched((), crawl=r)
                    _, ev = review.seen_and_evicted((), crawl=r)
                    self.assertFalse(unfetched and ev)

    def test_declined_and_evicted_cannot_both_fire(self):
        for ever in range(0, 5):
            for evicted in range(0, ever + 1):
                r = _reading(ever_indexed=ever, evicted=evicted)
                with self.subTest(ever=ever, evicted=evicted):
                    _, dec = review.seen_and_declined((), crawl=r)
                    _, ev = review.seen_and_evicted((), crawl=r)
                    self.assertFalse(dec and ev)

    def test_the_reading_router_returns_at_most_one_kind(self):
        for ever, evicted in ((0, 0), (2, 2), (2, 0), (1, 1)):
            r = _reading(ever_indexed=ever, evicted=evicted)
            text, kind = review._census_reading((), crawl=r)
            with self.subTest(ever=ever, evicted=evicted):
                self.assertIn(kind, ("", "declined", "evicted"))
                self.assertEqual(bool(text), bool(kind))
                if kind:
                    self.assertIn(kind, review.CENSUS_TAILS)


class TheClause(unittest.TestCase):
    """What a reader six months from now is handed."""

    def test_it_quotes_its_counts_and_calls_itself_a_floor(self):
        text = review.evicted_clause((), crawl=_reading())
        self.assertIn(EVICTED, text)
        self.assertIn("2 of its URLs were read as indexed", text)
        self.assertIn("none of the 90 it has inspected indexed now", text)
        self.assertIn(FLOOR, text)

    def test_it_names_the_newest_fetch_of_a_dropped_url(self):
        text = review.evicted_clause((), crawl=_reading())
        self.assertIn("newest fetch of any of the dropped URLs is 2026-08-24",
                      text)

    def test_it_asserts_no_fetch_date_it_does_not_have(self):
        text = review.evicted_clause((), crawl=_reading(last_crawl=None))
        self.assertIn(EVICTED, text)
        self.assertNotIn("newest fetch", text)
        self.assertNotIn("None", text)

    def test_it_reports_a_date_and_never_an_age(self):
        """A stored verdict is read months later; an age goes stale, a date
        does not. 2026-11-03's entry made the same argument about `settled`."""
        text = review.evicted_clause((), crawl=_reading())
        for stale in ("weeks ago", "days ago", "eleven weeks"):
            self.assertNotIn(stale, text)

    def test_empty_where_the_guard_does_not_fire(self):
        self.assertEqual(review.evicted_clause((), crawl=_reading(indexed=3)), "")
        self.assertEqual(review.evicted_clause((), crawl=_reading(evicted=0,
                                                                  ever_indexed=0)), "")


class TheInstruction(unittest.TestCase):
    """CENSUS_TAILS: the opposite instructions, in one place."""

    def test_the_declined_instruction_points_at_the_pages(self):
        self.assertIn("the next move is the pages themselves",
                      review.CENSUS_TAILS["declined"])
        self.assertIn("not more crawl or more URLs",
                      review.CENSUS_TAILS["declined"])

    def test_the_eviction_instruction_asks_what_changed(self):
        tail = review.CENSUS_TAILS["evicted"]
        self.assertIn("what changed", tail)
        self.assertIn("cleared Google's bar once", tail)

    def test_the_eviction_instruction_asserts_no_crawl_fact_of_its_own(self):
        """It must not claim Googlebot has stayed away.

        `evicted_last_crawl` is None on a reading that holds no crawl date, and
        a tail that asserted the absence of a fetch would then be claiming
        something the clause beside it never established. So the tail tells the
        reader to READ the date; the clause supplies it or omits it.
        """
        tail = review.CENSUS_TAILS["evicted"]
        self.assertIn("read the dropped URLs' last fetch above", tail)
        self.assertNotIn("has not been back", tail)
        self.assertNotIn("has not fetched", tail)


class TheClauseReachesEveryVerdict(unittest.TestCase):
    """THE SECOND FINDING, and it is the one no verdict audit catches.

    declined_clause() was appended to `unseen`, and `unseen` is READ by one of
    the four verdicts the per-prefix path builds. Three others took the census
    reading, recorded it in `measured`, and published a verdict with no census
    word in it — including the branch T019 sits on, which is the technique the
    guard's own docstring was written around.

    The four branches are forced here rather than found in the corpus: which
    branch a technique lands on is a property of last fortnight's traffic, so a
    corpus test exercises whichever one happens to be live tonight. That is the
    exact failure mode 2026-11-01 recorded on this same code — a test pinned
    through T019 went green-to-red with nothing in the guard changed, because
    T019's median fell and it took a different branch.
    """

    EVICTED_READING = staticmethod(_reading)

    def _run(self, recent, prior, total, vis, comparable=True):
        from unittest import mock
        t = {"id": "T999", "slug": "forced", "name": "forced",
             "prefixes": ["/hub/"], "status": "active",
             "activated": "2026-08-01", "kind": "content"}
        # Enough dated readings to clear evaluate()'s own "not enough days to
        # judge" guard, which sits above every branch here and counts
        # readings rather than days.
        pairs = [(f"2026-10-{d:02d}", total // 20) for d in range(1, 21)]
        pairs[-1] = (pairs[-1][0], total - sum(v for _, v in pairs[:-1]))
        trend = {"comparable": comparable, "recent_covered": True,
                 "prior_covered": True, "recent_readings": 14,
                 "prior_readings": 14, "note": "", "recent_span": 14,
                 "prior_span": 14}
        with mock.patch.object(review, "_owned", return_value=pairs), \
             mock.patch.object(review, "_trend",
                               return_value=(recent, prior, trend)), \
             mock.patch.object(review, "_days_active", return_value=99), \
             mock.patch.object(review, "_executions", return_value={}), \
             mock.patch.object(review.searchconsole, "recent_visibility",
                               return_value=vis), \
             mock.patch.object(review.indexstatus, "crawl_evidence",
                               return_value=_reading()):
            return review.evaluate(t, [t])

    # Every key searchconsole.recent_visibility returns, so a reading added
    # there cannot leave these silently short and send the test down a
    # KeyError instead of a branch.
    NO_SEARCH = {"measured": True, "pages": 0, "impressions": 0, "clicks": 0,
                 "best_position": None, "brand_measured": True,
                 "nonbranded_pages": 0, "nonbranded_impressions": 0,
                 "unattributed_pages": 0}
    RANKING = {"measured": True, "pages": 4, "impressions": 40, "clicks": 6,
               "best_position": 7.5, "brand_measured": True,
               "nonbranded_pages": 3, "nonbranded_impressions": 30,
               "unattributed_pages": 0}

    def test_branch_works_true_still_states_the_eviction(self):
        """A WORKS verdict is a reading of owned traffic; the clause is a
        reading of the index. Suppressing it would be the 2026-09-20 defect
        again — a verdict carrying a clause it disagreed with and saying
        nothing about it — so it is stated and the decision is untouched."""
        r = self._run(recent=5, prior=2, total=200, vis=self.RANKING)
        self.assertIs(r["works"], True)
        self.assertIn(EVICTED, r["why"])

    def test_branch_unseen_states_the_eviction_with_its_tail(self):
        r = self._run(recent=5, prior=2, total=200, vis=self.NO_SEARCH)
        self.assertIsNone(r["works"])
        self.assertIn(EVICTED, r["why"])
        self.assertIn("what changed", r["why"])

    def test_branch_falling_states_the_eviction(self):
        r = self._run(recent=2, prior=9, total=200, vis=self.RANKING)
        self.assertIsNone(r["works"])
        self.assertIn("while the rate is declining", r["why"])
        self.assertIn(EVICTED, r["why"])

    def test_branch_below_the_floor_states_the_eviction(self):
        """T019's live branch, and the one the 2026-11-04 clause could not
        reach: `unseen` is built for it and never read."""
        r = self._run(recent=0, prior=0, total=200, vis=self.NO_SEARCH)
        self.assertIsNone(r["works"])
        self.assertIn("below the 1/day that counts as alive", r["why"])
        self.assertIn(EVICTED, r["why"])

    def test_every_branch_that_states_it_also_says_what_to_do(self):
        for name, kw in (("works", dict(recent=5, prior=2, vis=self.RANKING)),
                         ("unseen", dict(recent=5, prior=2, vis=self.NO_SEARCH)),
                         ("falling", dict(recent=2, prior=9, vis=self.RANKING)),
                         ("floor", dict(recent=0, prior=0, vis=self.NO_SEARCH))):
            with self.subTest(branch=name):
                why = self._run(total=200, **kw)["why"]
                self.assertIn(EVICTED, why)
                self.assertIn("cleared Google's bar once", why)

    def test_no_branch_states_it_twice(self):
        for name, kw in (("works", dict(recent=5, prior=2, vis=self.RANKING)),
                         ("unseen", dict(recent=5, prior=2, vis=self.NO_SEARCH)),
                         ("falling", dict(recent=2, prior=9, vis=self.RANKING)),
                         ("floor", dict(recent=0, prior=0, vis=self.NO_SEARCH))):
            with self.subTest(branch=name):
                why = self._run(total=200, **kw)["why"]
                self.assertEqual(why.count(EVICTED), 1)
                self.assertEqual(why.count("cleared Google's bar once"), 1)

    def test_the_counts_are_recorded_wherever_the_clause_fires(self):
        for name, kw in (("works", dict(recent=5, prior=2, vis=self.RANKING)),
                         ("floor", dict(recent=0, prior=0, vis=self.NO_SEARCH))):
            with self.subTest(branch=name):
                m = self._run(total=200, **kw)["measured"]
                self.assertEqual(m["census_evicted"], 2)
                self.assertEqual(m["census_ever_indexed"], 2)
                self.assertEqual(m["census_read"], 90)


class TheRealCorpus(unittest.TestCase):
    """The invariant, against the committed ledger and index_status.json.

    Not a pin on today's wording: it says that a census finding which fires
    must appear in the verdict that gets published. That is precisely the
    property 2026-11-04's change lacked, and it would have gone red on T019
    that night.
    """

    def _active(self):
        from growth import ledger
        return [t for t in ledger.active() if t.get("prefixes")]

    def test_a_firing_census_finding_is_never_dropped_from_the_verdict(self):
        for t in self._active():
            text, kind = review._census_reading(t["prefixes"])
            if not kind:
                continue
            why = review.evaluate(t).get("why") or ""
            with self.subTest(slug=t.get("slug"), kind=kind):
                self.assertIn(text.strip(", "), why)
                self.assertTrue(
                    any(p in why for p in review.CENSUS_TAILS[kind].split(" — ")),
                    "the clause must arrive with its instruction")

    def test_no_technique_carries_two_census_findings(self):
        for t in self._active():
            why = review.evaluate(t).get("why") or ""
            with self.subTest(slug=t.get("slug")):
                self.assertFalse(EVICTED in why and DECLINED in why)
                self.assertFalse(EVICTED in why and NEVER_FETCHED in why)

    def test_t019_is_the_live_eviction_and_now_says_so(self):
        t = next((x for x in self._active()
                  if x.get("slug") == "hub_direct_answers"), None)
        if t is None:
            raise unittest.SkipTest("hub_direct_answers is not active here")
        ev = indexstatus.crawl_evidence(t["prefixes"])
        if not ev["evicted"]:
            raise unittest.SkipTest("the hub tier no longer reads as evicted")
        why = review.evaluate(t)["why"]
        self.assertIn(EVICTED, why)
        self.assertNotIn(DECLINED, why)


if __name__ == "__main__":
    unittest.main()
