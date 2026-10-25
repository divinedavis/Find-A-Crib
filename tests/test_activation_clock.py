#!/usr/bin/env python3
"""An active technique with no activation date was invisible to judgement.

Shipped 2026-10-25. review._days_active() returns 0 when `activated` is
missing or unreadable, which is the same number it returns for a technique
activated today, so evaluate()'s grace check answered "only 0d active — under
the 21d grace period" every night forever. The technique was never judged, and
never retired either, because every retirement path lies below that check.

T016 embeddable_building_lookup_widget lived in that state for its whole life:
active since 2026-07-27, 253 readings of its own series recorded from
2026-09-12, `verdict` still null on 2026-10-25.

The 2026-08-13 entry hit the SAME hole one field over — T015 and T016 were
active with `revisit_on` null, so ledger.revisit_due() skipped them — and
diagnosed the cause exactly: the hole opens whenever a technique is made
active by hand-editing the ledger instead of through ledger.set_status(),
which stamps `activated` and `revisit_on` together. That fix stamped
revisit_on and left activated null, so T016 came up for revisit on a clock it
still could not be judged against.

These tests pin the flag closed, and pin the three ways it could be made
useless again: firing below the grace check (where it can never be reached),
firing on audits (which are judged on night one and do not use the clock), and
carrying a `measured` payload (which would make run() write a verdict the loop
never computed).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import ledger            # noqa: E402
from growth import review as R       # noqa: E402


def tech(**kw):
    """A minimal active technique record. No prefixes, so a record that gets
    past the clock check does not reach Search Console or the index census."""
    base = {"id": "T999", "slug": "synthetic", "name": "synthetic",
            "status": "active", "activated": "2026-01-01", "metric": "organic_visitors"}
    base.update(kw)
    return base


class ActivationClock(unittest.TestCase):

    def test_missing_date_is_not_a_date(self):
        self.assertIsNone(R._activation_clock(tech(activated=None)))

    def test_absent_key_is_not_a_date(self):
        t = tech()
        del t["activated"]
        self.assertIsNone(R._activation_clock(t))

    def test_unreadable_date_is_not_a_date(self):
        for bad in ("", "soon", "2026-13-01", "tomorrow", "0000"):
            self.assertIsNone(R._activation_clock(tech(activated=bad)), bad)

    def test_a_real_date_reads_back(self):
        self.assertEqual(R._activation_clock(tech(activated="2026-09-12")).isoformat(),
                         "2026-09-12")

    def test_days_active_still_collapses_both_to_zero(self):
        # Left deliberately as it was: find_redundant() does not need the
        # distinction. If this ever changes, the flag below is the thing that
        # must keep working, not this.
        self.assertEqual(R._days_active(tech(activated=None)), 0)
        self.assertEqual(R._days_active(tech(activated="nonsense")), 0)


class MissingClockIsFlagged(unittest.TestCase):

    def test_active_with_no_clock_is_flagged(self):
        r = R.evaluate(tech(activated=None))
        self.assertEqual(r["action"], "flag")

    def test_active_with_unreadable_clock_is_flagged(self):
        r = R.evaluate(tech(activated="whenever"))
        self.assertEqual(r["action"], "flag")

    def test_it_is_never_silently_kept(self):
        # The whole defect: "keep" is silent by design, so a keep here is the
        # technique disappearing from judgement without anyone being told.
        r = R.evaluate(tech(activated=None))
        self.assertNotEqual(r["action"], "keep")

    def test_the_flag_claims_nothing_about_whether_it_works(self):
        r = R.evaluate(tech(activated=None))
        self.assertIsNone(r["works"])

    def test_the_flag_writes_no_verdict(self):
        # run() calls ledger.set_verdict only when `measured` is non-empty.
        # An empty payload is what keeps this an announcement rather than a
        # verdict the loop never computed.
        r = R.evaluate(tech(activated=None))
        self.assertEqual(r["measured"], {})

    def test_the_why_names_the_field_and_the_remedy(self):
        why = R.evaluate(tech(activated=None))["why"]
        self.assertIn("activated", why)
        self.assertIn("set_status", why)

    def test_a_stamped_clock_does_not_reach_the_flag(self):
        r = R.evaluate(tech(activated="2026-10-20"))
        self.assertEqual(r["action"], "keep")
        self.assertIn("grace period", r["why"])

    def test_a_non_active_technique_short_circuits_first(self):
        # status is checked above the clock, so a candidate with no clock is
        # skipped rather than flagged — it is not supposed to have one yet.
        for status in ("candidate", "retired"):
            r = R.evaluate(tech(status=status, activated=None))
            self.assertEqual(r["action"], "skip", status)

    def test_an_audit_with_no_clock_is_not_flagged(self):
        # Audits are judged on their own nightly reading from night one and
        # never consult the clock, so flagging one would be noise about a
        # field it does not use.
        r = R.evaluate(tech(judge="audit", activated=None))
        self.assertNotEqual(r["action"], "flag")


class Ordering(unittest.TestCase):
    """The check is worthless below the grace check, which returns first."""

    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "growth", "review.py")
        with open(path) as f:
            self.src = f.read()

    def test_the_clock_check_sits_above_the_grace_check(self):
        clock = self.src.index("_activation_clock(t) is None")
        grace = self.src.index("if days < GRACE_DAYS:")
        self.assertLess(clock, grace,
                        "the clock check must precede the grace check or it is unreachable")

    def test_the_clock_check_sits_below_the_audit_return(self):
        audit = self.src.index('if t.get("judge") == "audit":')
        clock = self.src.index("_activation_clock(t) is None")
        self.assertLess(audit, clock)


class TheRealLedger(unittest.TestCase):
    """The regression that stops the 2026-08-13 hole reopening on a third field."""

    def setUp(self):
        self.techs = ledger.load_techniques()

    def test_every_active_technique_without_a_clock_is_flagged(self):
        # Deliberately not "every active technique has a clock": T016 does not
        # have one on 2026-10-25, and the point is that the loop now SAYS so
        # every night instead of parking it. If someone stamps T016, this still
        # holds — there is simply nothing left to flag.
        for t in self.techs:
            if t.get("status") != "active" or t.get("judge") == "audit":
                continue
            if R._activation_clock(t) is not None:
                continue
            r = R.evaluate(t, self.techs)
            self.assertEqual(r["action"], "flag",
                             f"{t['id']} {t['slug']} is active with no activation clock "
                             f"and was not flagged")

    def test_no_active_technique_is_parked_at_zero_days_active(self):
        for t in self.techs:
            if t.get("status") != "active" or t.get("judge") == "audit":
                continue
            r = R.evaluate(t, self.techs)
            if r["action"] == "keep" and "grace period" in (r["why"] or ""):
                self.assertIsNotNone(
                    R._activation_clock(t),
                    f"{t['id']} {t['slug']} is sitting in the grace period with no "
                    f"activation date, so it will sit there forever")


if __name__ == "__main__":
    unittest.main()
