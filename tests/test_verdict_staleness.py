#!/usr/bin/env python3
"""A stored verdict is a frozen string, and `status` printed it undated.

Shipped 2026-10-27.

ledger.set_verdict() stamps `decided` and writes the why-string as it stood
that night. Nothing rewrites that string when the ledger moves underneath it,
and cmd_status printed it with no date at all — so a verdict decided last
night and one decided a fortnight ago under a different configuration were
indistinguishable on screen.

That has now cost two consecutive reviews a real investigation:

  * 2026-10-25 read "3 other active techniques ... (T005 indexnow, T010
    gsc_integration, T015 dataset_schema_ai_citation)" on T004 and T005 and
    had to call review._co_claimants() by hand to establish that T015 —
    retired 2026-10-12 — is not actually counted. Its journal entry filed the
    result as "A NEAR-MISS I AM RECORDING SO THE NEXT RUN DOES NOT 'FIX' IT".
  * 2026-10-26 moved T010 to judge="audit" and pre-registered "T004 AND T005
    MUST HAVE ONE CO-CLAIMANT EACH, NOT THREE ... If T010 reappears in either
    list, the judge field was reverted." On 2026-10-27 `status` showed T010 in
    both lists with a verdict quoting organic_visitors, so that falsification
    condition read as HAVING FIRED. It had not — techniques.json holds
    judge="audit", seed.py agrees, and review.run(apply=False) returns one
    co-claimant each plus the audit verdict for T010.

The second case is the expensive one: the frozen text impersonated a
pre-registered FAILURE, and the reviewer's own instructions pointed at it.

The remedy is a label, never a rewrite. A verdict records a judgement actually
made on a particular night; editing it would destroy the history the ledger
exists to keep. So verdict_staleness() reports two checkable contradictions —
a co-claimant that is no longer active, and an audit-judged technique whose
text came off the metric judge — and cmd_status says so once above the list
and again beneath each line.

These tests pin both detectors, that they are about the TEXT and never about
the technique, that a clean verdict stays silent, the nights-measured 0/None
distinction, the banner's once-per-run behaviour, and the two live cases in
today's ledger.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import growth_daily                  # noqa: E402
from growth import ledger            # noqa: E402


def rec(tid="T900", slug="synthetic", status="active", decided="2026-10-01",
        measured=None, why="w", **kw):
    t = {"id": tid, "slug": slug, "name": f"name {tid}", "kind": "content",
         "status": status, "activated": "2026-01-01", "revisit_on": "2026-12-01",
         "verdict": ({"decided": decided, "works": None, "why": why,
                      "measured": measured or {}} if decided else None)}
    t.update(kw)
    return t


def live(*ids):
    """A ledger in which exactly `ids` are active."""
    return [rec(tid=i, slug=f"s{i}") for i in ids]


class NoVerdictIsNotAStaleOne(unittest.TestCase):

    def test_none_when_no_verdict(self):
        self.assertIsNone(ledger.verdict_staleness(rec(decided=None)))

    def test_none_when_verdict_has_no_decided_date(self):
        t = rec()
        t["verdict"] = {"works": None, "why": "w", "measured": {}}
        self.assertIsNone(ledger.verdict_staleness(t))

    def test_none_input_does_not_raise(self):
        self.assertIsNone(ledger.verdict_staleness(None))

    def test_clean_verdict_is_not_contradicted(self):
        s = ledger.verdict_staleness(rec(measured={"metric": "organic_visitors"}),
                                     techs=live("T900"))
        self.assertFalse(s["contradicted"])
        self.assertEqual(s["contradictions"], [])


class RetiredCoClaimantIsNamed(unittest.TestCase):
    """The 2026-10-25 near-miss, reported instead of re-investigated."""

    def test_retired_co_claimant_is_flagged(self):
        t = rec(measured={"metric": "organic_visitors",
                          "co_claimants": ["T005 indexnow", "T015 dataset_schema"]})
        s = ledger.verdict_staleness(t, techs=live("T900", "T005"))
        self.assertTrue(s["contradicted"])
        self.assertEqual(len(s["contradictions"]), 1)
        self.assertIn("T015 dataset_schema", s["contradictions"][0])
        self.assertNotIn("T005", s["contradictions"][0])

    def test_all_live_co_claimants_stay_silent(self):
        t = rec(measured={"co_claimants": ["T005 indexnow", "T015 dataset_schema"]})
        s = ledger.verdict_staleness(t, techs=live("T900", "T005", "T015"))
        self.assertFalse(s["contradicted"])

    def test_several_retired_co_claimants_are_all_named(self):
        t = rec(measured={"co_claimants": ["T005 a", "T015 b", "T077 c"]})
        s = ledger.verdict_staleness(t, techs=live("T900"))
        for tid in ("T005", "T015", "T077"):
            self.assertIn(tid, s["contradictions"][0])

    def test_no_co_claimants_key_is_not_an_error(self):
        s = ledger.verdict_staleness(rec(measured={"metric": "m"}), techs=live("T900"))
        self.assertFalse(s["contradicted"])

    def test_a_candidate_co_claimant_counts_as_not_live(self):
        """_co_claimants filters on active, not on existing."""
        techs = live("T900") + [rec(tid="T015", status="candidate")]
        t = rec(measured={"co_claimants": ["T015 dataset_schema"]})
        self.assertTrue(ledger.verdict_staleness(t, techs=techs)["contradicted"])


class ReclassifiedJudgeIsNamed(unittest.TestCase):
    """The 2026-10-27 case: frozen text impersonating a pre-registered failure."""

    def test_audit_technique_with_a_metric_verdict_is_flagged(self):
        t = rec(judge="audit", measured={"metric": "organic_visitors"})
        s = ledger.verdict_staleness(t, techs=live("T900"))
        self.assertTrue(s["contradicted"])
        self.assertIn("organic_visitors", s["contradictions"][0])
        self.assertIn("audit", s["contradictions"][0])

    def test_audit_technique_with_an_audit_verdict_is_clean(self):
        t = rec(judge="audit", measured={"judged_on": "its own nightly audit reading"})
        self.assertFalse(ledger.verdict_staleness(t, techs=live("T900"))["contradicted"])

    def test_metric_technique_with_a_metric_verdict_is_clean(self):
        t = rec(measured={"metric": "organic_visitors"})
        self.assertFalse(ledger.verdict_staleness(t, techs=live("T900"))["contradicted"])

    def test_audit_verdict_carrying_both_keys_is_clean(self):
        """judged_on present means the audit judge wrote it, whatever else is there."""
        t = rec(judge="audit", measured={"judged_on": "x", "metric": "organic_visitors"})
        self.assertFalse(ledger.verdict_staleness(t, techs=live("T900"))["contradicted"])

    def test_both_contradictions_can_fire_at_once(self):
        t = rec(judge="audit", measured={"metric": "organic_visitors",
                                         "co_claimants": ["T015 gone"]})
        s = ledger.verdict_staleness(t, techs=live("T900"))
        self.assertEqual(len(s["contradictions"]), 2)


class ItDescribesTheTextAndNeverTheTechnique(unittest.TestCase):
    """A contradiction is not evidence that a technique is doing badly."""

    def test_contradicted_does_not_touch_works(self):
        t = rec(judge="audit", measured={"metric": "m"})
        t["verdict"]["works"] = True
        s = ledger.verdict_staleness(t, techs=live("T900"))
        self.assertTrue(s["contradicted"])
        self.assertTrue(t["verdict"]["works"], "verdict must not be mutated")

    def test_the_stored_string_is_never_rewritten(self):
        t = rec(judge="audit", measured={"metric": "m"}, why="original text")
        ledger.verdict_staleness(t, techs=live("T900"))
        self.assertEqual(t["verdict"]["why"], "original text")


class NightsSinceIsReported(unittest.TestCase):

    def test_zero_and_none_are_different_answers(self):
        s = ledger.verdict_staleness(rec(decided="2026-10-01"), techs=live("T900"))
        self.assertIsInstance(s["nights_since"], int)
        s2 = ledger.verdict_staleness(rec(decided="not-a-date"), techs=live("T900"))
        self.assertIsNone(s2["nights_since"])

    def test_todays_real_ledger_has_no_new_nights_since_the_pause(self):
        """Pins the pause: results.jsonl's newest row is 2026-10-12."""
        self.assertEqual(ledger.measured_nights_since("2026-10-12"), 0)


class TheDateCacheIsKeyedOnTheFile(unittest.TestCase):

    def test_repeated_calls_agree(self):
        a = ledger.measured_nights_since("2026-09-01")
        b = ledger.measured_nights_since("2026-09-01")
        self.assertEqual(a, b)
        self.assertGreater(a, 0)

    def test_a_stubbed_reader_does_not_poison_the_real_file(self):
        """The bug this cache shipped with, caught by the full suite.

        _measured_dates() is keyed on the results file, but its data comes
        from read_results(), which tests monkeypatch. Keying on the file
        alone stored a stub's synthetic rows under the real file's stat, and
        restoring the stub does not touch the file — so every later call got
        the synthetic answer. It failed only under the full suite, because
        tests/test_revisit_visibility.py has to run first to plant it.
        """
        real = ledger.measured_nights_since("2026-09-01")
        orig = ledger.read_results
        ledger.read_results = lambda *a, **k: [{"date": "2026-12-31"}]
        try:
            self.assertEqual(ledger.measured_nights_since("2026-09-01"), 1)
        finally:
            ledger.read_results = orig
        self.assertEqual(ledger.measured_nights_since("2026-09-01"), real,
                         "a stubbed reader leaked into the real file's cache entry")

    def test_an_appended_row_is_seen(self):
        """(mtime_ns, size) must invalidate inside the same second."""
        import json
        import tempfile
        orig = ledger.RESULTS_PATH
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            ledger.RESULTS_PATH = path
            with open(path, "w") as f:
                f.write(json.dumps({"date": "2026-01-01", "technique": "t",
                                    "metric": "m", "value": 1}) + "\n")
            self.assertEqual(ledger.measured_nights_since("2025-12-31"), 1)
            with open(path, "a") as f:
                f.write(json.dumps({"date": "2026-01-02", "technique": "t",
                                    "metric": "m", "value": 1}) + "\n")
            self.assertEqual(ledger.measured_nights_since("2025-12-31"), 2)
        finally:
            ledger.RESULTS_PATH = orig
            os.unlink(path)


class StatusSaysItOnceAndThenPerLine(unittest.TestCase):

    def render(self, techs):
        out = []
        real_load, real_log = ledger.load_techniques, growth_daily.log
        try:
            ledger.load_techniques = lambda: techs
            growth_daily.log = lambda *a: out.append(" ".join(str(x) for x in a) if a else "")
            stale = {t["id"]: ledger.verdict_staleness(t, techs=techs) for t in techs}
            bad = [i for i, s in stale.items() if s and s["contradicted"]]
            if bad:
                growth_daily.log(f"NOTE: {len(bad)} stored verdict"
                                 f"{'s' if len(bad) != 1 else ''} below "
                                 f"({', '.join(sorted(bad))})")
            for t in techs:
                s = stale.get(t["id"])
                if s:
                    growth_daily.log(f"decided {s['decided']}")
                    for c in s["contradictions"]:
                        growth_daily.log(f"^ FROZEN TEXT, NOT A LIVE READING — it {c}")
        finally:
            ledger.load_techniques, growth_daily.log = real_load, real_log
        return "\n".join(out)

    def test_banner_names_every_contradicted_id_once(self):
        techs = [rec(tid="T004", judge="audit", measured={"metric": "m"}),
                 rec(tid="T005", measured={"co_claimants": ["T015 gone"]}),
                 rec(tid="T006")]
        text = self.render(techs)
        self.assertEqual(text.count("NOTE:"), 1)
        self.assertIn("T004, T005", text)
        self.assertIn("2 stored verdicts", text)

    def test_no_banner_when_nothing_is_contradicted(self):
        self.assertNotIn("NOTE:", self.render([rec(tid="T006")]))

    def test_singular_wording_for_one(self):
        text = self.render([rec(tid="T004", judge="audit", measured={"metric": "m"})])
        self.assertIn("1 stored verdict ", text)

    def test_every_contradiction_gets_its_own_line(self):
        techs = [rec(tid="T010", judge="audit",
                     measured={"metric": "organic_visitors",
                               "co_claimants": ["T015 gone"]})]
        self.assertEqual(self.render(techs).count("FROZEN TEXT"), 2)


class TodaysLedgerHasExactlyTheThreeKnownCases(unittest.TestCase):
    """Regressions against the real ledger, so a future run can check this shipped."""

    def setUp(self):
        self.techs = ledger.load_techniques()
        self.stale = {t["id"]: ledger.verdict_staleness(t, techs=self.techs)
                      for t in self.techs}

    def test_t004_t005_t010_are_the_contradicted_ones(self):
        bad = sorted(i for i, s in self.stale.items() if s and s["contradicted"])
        self.assertEqual(bad, ["T004", "T005", "T010"])

    def test_t010_carries_both_contradictions(self):
        self.assertEqual(len(self.stale["T010"]["contradictions"]), 2)

    def test_t010_is_still_an_audit_in_the_ledger(self):
        """If this fails the judge really was reverted — unlike the printed text."""
        t = next(x for x in self.techs if x["id"] == "T010")
        self.assertEqual(t.get("judge"), "audit")
        self.assertFalse(t.get("prefixes"))

    def test_every_verdict_in_the_ledger_is_dated(self):
        for t in self.techs:
            if t.get("verdict"):
                self.assertTrue(t["verdict"].get("decided"),
                                f"{t['id']} has a verdict with no decided date")


if __name__ == "__main__":
    unittest.main()
