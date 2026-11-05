"""The census reading must reach the verdict on the paths that skip the census.

Why this exists (2026-11-05). Three findings, and the first one cost a
conclusion that stood in the ledger for a month.

1. T085'S HYPOTHESIS WAS FILED AS REFUTED WHEN IT HAD NEVER BEEN DELIVERED.
   T085 provenance_page claims that publishing the site's sources raises the
   site-level judgement that gates index acceptance. On 2026-10-06 its revisit
   read index_accept_pct_mature flat at 0.0% since activation and wrote "THE
   PRE-REGISTRATION ABOVE IS CASHED AGAINST ITSELF: THE HYPOTHESIS IS WRONG"
   into its notes. But /methodology/ has read `unknown_to_google` with
   `crawled: null` on every census check since 2026-09-08 — two days after
   activation. Google has never fetched the page whose publication IS the
   intervention, so the metric staying flat refutes nothing: a trust signal
   that was never delivered cannot have been tested.

2. WHY THE LOOP COULD NOT SEE IT. `judge: "site"` routes a technique past the
   entire per-prefix block in evaluate(), census apparatus included, so every
   census clause built since 2026-08-29 was unreachable from the site-judged
   path. T085 is the only technique on that path and it owns /methodology/: its
   reading was taken nightly, written to results.jsonl as `provenance_page
   census_read 1 / census_fetched 0`, and every verdict the loop published
   about it said only "index_accept_pct_mature median 0.0/day vs 0.0/day".

3. AND THE THRESHOLD HID IT A SECOND TIME. Even on the per-prefix path the
   clause would not have fired: never_fetched() requires
   `read >= MIN_CENSUS_READ` (three), and /methodology/ is a ONE-URL section,
   so its reading is read 1 / fetched 0 forever. The threshold is correct —
   `read` is a stratified sample and two URLs cannot speak for a large tier —
   but it guards the GENERALISING SENTENCE, and nothing about it requires the
   loop to withhold the COUNTS it holds. T016 (/embed/, read 1, fetched 0) sits
   in the same gap.

4. AND LAST NIGHT'S ENTRY OVERSTATED ITS OWN FIX. It said the census clause
   "NOW REACHES THE VERDICT ON ALL FOUR BRANCHES OF THE PER-PREFIX PATH". It
   reaches the four TERMINAL branches; six exits above them return first, and
   two live techniques were on one of those — T013 (read 57, fetched 0) and
   T023 (read 3, fetched 0), both on the thin-window branch, both publishing
   "Nothing to retire on until the window refills" with no census word, while
   T023's own pre-registered condition is whether Google ever fetches a
   /guide/ URL at all.

WHAT THESE TESTS GUARD:

 1. unfetched_thin() fires ONLY in the gap — strictly between 0 and
    MIN_CENSUS_READ, and only at fetched == 0. Never at read 0 (silence, and
    what a technique with no prefixes gets), never at or above the threshold
    (never_fetched() speaks there and says more), never where `fetched` is
    absent rather than zero.
 2. The thin clause asserts COUNTS AND NOTHING ELSE, and carries no
    instruction. A tail here would be the loop asserting exactly what the
    threshold exists to withhold, so CENSUS_TAILS must have no "thin" key.
 3. census_sentence() routes all four findings, they are mutually exclusive
    over the whole input space, and the two that warrant an instruction read it
    out of CENSUS_TAILS rather than holding a second copy.
 4. The site-judged path actually REACHES the verdict with it — on every branch
    that publishes a judgement — and WRITES the counts into `measured`. The
    blind spot this loop walked into on 2026-11-03 and again on 11-04 was that
    nothing watched the recording half, so deleting it left every suite green.
 5. The thin-window branch of the per-prefix path reaches it too.
 6. The CENSUS_TAILS["unfetched"] extraction is byte-identical to the inline
    string it replaced, so the per-prefix wording did not drift.
"""
import unittest

from growth import review


READ = review.MIN_CENSUS_READ


def reading(**kw):
    """A census reading with every key crawl_evidence() guarantees."""
    out = {"cohort": 0, "read": 0, "fetched": 0, "indexed": 0,
           "ever_indexed": 0, "settled": 0, "settled_indexed": 0,
           "evicted": 0, "evicted_last_crawl": None, "buckets": {}}
    out.update(kw)
    return out


P = ("/methodology/",)


class ThinPredicate(unittest.TestCase):
    def test_fires_in_the_gap(self):
        for n in range(1, READ):
            with self.subTest(read=n):
                _, fired = review.unfetched_thin(P, crawl=reading(read=n, cohort=n))
                self.assertTrue(fired, f"read={n} is in the gap and must fire")

    def test_the_live_t085_reading_fires(self):
        # cohort 1, read 1, fetched 0 — /methodology/ on 2026-11-05.
        _, fired = review.unfetched_thin(P, crawl=reading(cohort=1, read=1))
        self.assertTrue(fired)

    def test_silent_where_nothing_inspected(self):
        # read 0 is what a technique declaring no prefixes gets, and an absent
        # measurement is not evidence of anything.
        _, fired = review.unfetched_thin(P, crawl=reading(read=0))
        self.assertFalse(fired)

    def test_silent_at_and_above_the_threshold(self):
        for n in (READ, READ + 1, 57, 250):
            with self.subTest(read=n):
                _, fired = review.unfetched_thin(P, crawl=reading(read=n))
                self.assertFalse(fired, f"never_fetched() owns read={n}")

    def test_silent_once_anything_was_fetched(self):
        _, fired = review.unfetched_thin(P, crawl=reading(read=2, fetched=1))
        self.assertFalse(fired)

    def test_absent_fetched_is_silence_not_zero(self):
        # Same stance seen_and_evicted() takes on a missing key: a reading that
        # does not carry `fetched` has not told us it is zero.
        crawl = reading(read=1)
        crawl.pop("fetched")
        _, fired = review.unfetched_thin(P, crawl=crawl)
        self.assertFalse(fired)

    def test_threshold_is_positive(self):
        # The tripwire if anyone sets MIN_CENSUS_READ to 0 or 1: at 1 the gap
        # `0 < read < 1` is empty and this predicate can never fire, so the
        # disclosure would silently vanish rather than fail.
        self.assertGreater(READ, 1)


class ThinClause(unittest.TestCase):
    def test_states_the_counts_and_the_threshold(self):
        text = review.unfetched_thin_clause(P, crawl=reading(cohort=1, read=1))
        self.assertIn("inspected 1 of its URLs", text)
        self.assertIn("fetched none of them", text)
        self.assertIn(f"below the {READ}", text)
        self.assertIn("not yet a verdict", text)

    def test_empty_where_it_does_not_fire(self):
        self.assertEqual("", review.unfetched_thin_clause(P, crawl=reading(read=READ)))
        self.assertEqual("", review.unfetched_thin_clause(P, crawl=reading(read=0)))

    def test_asserts_nothing_about_the_published_section(self):
        # index_status.json holds `published_urls` as a single site-wide scalar
        # and no per-prefix published count, so "the sample is the whole
        # section" is true of /methodology/ and unprovable from stored data.
        # The clause must not claim it.
        text = review.unfetched_thin_clause(P, crawl=reading(cohort=1, read=1)).lower()
        for forbidden in ("every url", "all of its urls", "the whole section",
                          "only page", "entire section"):
            self.assertNotIn(forbidden, text)

    def test_carries_no_instruction(self):
        # A reading too thin for a verdict must not carry an instruction, so
        # neither the clause nor CENSUS_TAILS may supply one.
        self.assertNotIn("thin", review.CENSUS_TAILS)
        text = review.unfetched_thin_clause(P, crawl=reading(cohort=1, read=1)).lower()
        for forbidden in ("the next move", "rewrite", "retire", "consolidat"):
            self.assertNotIn(forbidden, text)


class CensusSentenceRouting(unittest.TestCase):
    def test_thin(self):
        text, kind = review.census_sentence(P, crawl=reading(cohort=1, read=1))
        self.assertEqual("thin", kind)
        self.assertIn("not yet a verdict", text)

    def test_unfetched(self):
        text, kind = review.census_sentence(P, crawl=reading(cohort=57, read=57))
        self.assertEqual("unfetched", kind)
        self.assertIn("never fetched one of them", text)
        self.assertIn(review.CENSUS_TAILS["unfetched"], text)

    def test_declined(self):
        text, kind = review.census_sentence(
            P, crawl=reading(cohort=250, read=250, fetched=159, settled=159))
        self.assertEqual("declined", kind)
        self.assertIn(review.CENSUS_TAILS["declined"], text)

    def test_evicted(self):
        text, kind = review.census_sentence(
            P, crawl=reading(cohort=90, read=90, fetched=24, settled=24,
                             ever_indexed=2, evicted=2,
                             evicted_last_crawl="2026-08-24"))
        self.assertEqual("evicted", kind)
        self.assertIn(review.CENSUS_TAILS["evicted"], text)

    def test_nothing_where_nothing_was_inspected(self):
        self.assertEqual(("", ""), review.census_sentence(P, crawl=reading(read=0)))

    def test_the_four_are_mutually_exclusive_over_the_input_space(self):
        # Not merely by the elif chain: declined and evicted both require
        # fetched > 0, and the two unfetched cases require fetched == 0.
        seen = set()
        for read in range(0, 14):
            for fetched in range(0, min(read, 13) + 1):
                for settled in range(0, fetched + 1):
                    for ever in range(0, settled + 1):
                        for ev in range(0, ever + 1):
                            crawl = reading(cohort=read, read=read, fetched=fetched,
                                            settled=settled, settled_indexed=0,
                                            ever_indexed=ever, evicted=ev)
                            text, kind = review.census_sentence(P, crawl=crawl)
                            seen.add(kind)
                            # Exactly one finding, and a kind always has words.
                            self.assertEqual(bool(kind), bool(text))
                            if fetched == 0:
                                self.assertIn(kind, ("", "unfetched", "thin"))
                            else:
                                self.assertNotIn(kind, ("unfetched", "thin"))
        # The sweep must actually have reached every branch, or it proves
        # nothing about the ones it missed.
        self.assertEqual({"", "unfetched", "thin", "declined", "evicted"}, seen)

    def test_instructions_have_one_copy(self):
        # Each tail must come out of CENSUS_TAILS, so four verdicts cannot come
        # to say different things about one reading.
        for kind, crawl in (
            ("unfetched", reading(cohort=57, read=57)),
            ("declined", reading(cohort=250, read=250, fetched=159, settled=159)),
        ):
            text, got = review.census_sentence(P, crawl=crawl)
            self.assertEqual(kind, got)
            self.assertTrue(text.endswith(review.CENSUS_TAILS[kind]))


class SiteJudgedPathReachesTheVerdict(unittest.TestCase):
    """The fix, exercised the only way that proves it: through evaluate()."""

    def _t085(self):
        from growth import ledger
        for t in ledger.load_techniques():
            if t["id"] == "T085":
                return t
        self.skipTest("T085 absent from the ledger")

    def test_t085_is_still_on_the_site_judged_path(self):
        # If this changes, the test below stops testing what it claims to.
        t = self._t085()
        self.assertEqual("site", t.get("judge"))
        self.assertTrue(t.get("prefixes"))

    def test_verdict_carries_the_census_reading(self):
        from growth import ledger
        techs = ledger.load_techniques()
        res = review.evaluate(self._t085(), techs)
        self.assertIn("index census", res["why"])
        self.assertIn("fetched none of them", res["why"])

    def test_measured_carries_the_counts(self):
        # THE HALF NOTHING WAS WATCHING. On 2026-11-03 and again on 11-04 this
        # loop found that deleting the code which WRITES a census value left
        # every suite green, because every test read the sentence instead. This
        # asserts the recording half directly.
        from growth import ledger
        techs = ledger.load_techniques()
        res = review.evaluate(self._t085(), techs)
        for key in ("census_read", "census_fetched", "census_cohort"):
            self.assertIn(key, res["measured"])
        self.assertEqual(0, res["measured"]["census_fetched"])

    def test_no_decision_changed(self):
        # A reason changed, never a decision: works stays None and the action
        # stays what the metric comparison made it.
        from growth import ledger
        techs = ledger.load_techniques()
        res = review.evaluate(self._t085(), techs)
        self.assertIsNone(res["works"])
        self.assertEqual("flag", res["action"])


class ThinWindowBranchReachesTheVerdict(unittest.TestCase):
    """The exit last night's entry said was covered and was not."""

    def _by_id(self, tid):
        from growth import ledger
        for t in ledger.load_techniques():
            if t["id"] == tid:
                return t
        self.skipTest(f"{tid} absent from the ledger")

    def test_t023_states_its_census_reading(self):
        from growth import ledger
        techs = ledger.load_techniques()
        t = self._by_id("T023")
        if t.get("status") != "active":
            self.skipTest("T023 not active")
        res = review.evaluate(t, techs)
        if "Nothing to retire on until the window refills" not in res["why"]:
            self.skipTest("T023 is no longer on the thin-window branch")
        self.assertIn("index census", res["why"])
        self.assertIn("census_read", res["measured"])

    def test_t013_states_its_census_reading(self):
        from growth import ledger
        techs = ledger.load_techniques()
        t = self._by_id("T013")
        if t.get("status") != "active":
            self.skipTest("T013 not active")
        res = review.evaluate(t, techs)
        if "Nothing to retire on until the window refills" not in res["why"]:
            self.skipTest("T013 is no longer on the thin-window branch")
        self.assertIn("index census", res["why"])
        self.assertIn("census_read", res["measured"])


class PerPrefixWordingDidNotDrift(unittest.TestCase):
    def test_unfetched_tail_is_byte_identical(self):
        # CENSUS_TAILS["unfetched"] was lifted verbatim out of the per-prefix
        # tail. This pins the reassembled sentence to the exact string that
        # shipped on 2026-11-03, so the extraction cannot have reworded it.
        expected = ("unproven rather than failed: nothing has been measured about "
                    "whether these pages can rank, so the next move is to get them "
                    "crawled rather than to rewrite or retire them")
        rebuilt = ("unproven rather than failed: nothing has been measured about "
                   "whether these pages can rank, so "
                   + review.CENSUS_TAILS["unfetched"])
        self.assertEqual(expected, rebuilt)

    def test_t001_verdict_still_carries_it(self):
        # T001 is the live technique on that leg; its wording must not move.
        from growth import ledger
        techs = ledger.load_techniques()
        for t in techs:
            if t["id"] == "T001" and t.get("status") == "active":
                res = review.evaluate(t, techs)
                if "never fetched any of the" in res["why"]:
                    self.assertIn(review.CENSUS_TAILS["unfetched"], res["why"])
                return


if __name__ == "__main__":
    unittest.main()
