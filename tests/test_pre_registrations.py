#!/usr/bin/env python3
"""A pre-registration that fires on an ABSENCE is cashed for free by a pause.

Shipped 2026-10-28.

Five techniques in this ledger carry a condition written down before the
evidence arrived, so the verdict could not be retrofitted. Until today none of
them had a reader: each lived as an English sentence inside a `notes` blob —
T013's is 7,091 characters in — and the 2026-10-28 review found its own due
condition by grepping seed.py.

The shape of the condition decides what a measurement gap does to it:

  * fires_on="event"   the gate stays shut while nobody looks, so an
                       unobserved window can only DELAY the decision. T023
                       needs a /guide/ URL to be fetched; T017 needs the ask
                       count to reach 40. Both came due (10-27, 10-26) during
                       the pause and correctly did not fire.
  * fires_on="absence" nobody looked, so nothing was seen, so "nothing
                       happened" reads as TRUE. T013's condition — "if
                       census_known is still 0 on 2026-10-28" — came due on a
                       census frozen since 2026-10-12, with 16 of its 30 days
                       unobserved, and would have retired the technique and
                       handed 251 pages to T027.

So the pause pushes an absence-condition TOWARD firing and an event-condition
AWAY from it, and only the first can produce a false conclusion. T017's and
T023's were caught by a reviewer writing capitals into the notes by hand;
T013's got no such warning and was the only one of the three that needed one.

These tests pin the distinction, not the prose.
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from growth import ledger  # noqa: E402


def tech(**kw):
    t = {"id": "T999", "slug": "s", "name": "n", "status": "active"}
    t.update(kw)
    return t


def reg(**kw):
    r = {"condition": "c", "fires_on": "event"}
    r.update(kw)
    return r


class NoRecordIsNotACondition(unittest.TestCase):
    def test_absent_field_yields_nothing(self):
        self.assertEqual(ledger.pre_registrations(techs=[tech()]), [])

    def test_empty_list_yields_nothing(self):
        self.assertEqual(ledger.pre_registrations(techs=[tech(pre_registered=[])]), [])

    def test_a_bare_dict_is_accepted_as_one(self):
        out = ledger.pre_registrations(techs=[tech(pre_registered=reg())])
        self.assertEqual(len(out), 1)


class AMalformedRecordIsReportedNeverSkipped(unittest.TestCase):
    """Dropping it silently is the failure the whole mechanism exists to stop."""

    def test_missing_condition_text(self):
        e = ledger.pre_registrations(techs=[tech(pre_registered=[reg(condition="")])])[0]
        self.assertIn("no condition text", e["malformed"])
        self.assertFalse(e["cashable"])
        self.assertFalse(e["due"])

    def test_unknown_fires_on(self):
        e = ledger.pre_registrations(techs=[tech(pre_registered=[reg(fires_on="maybe")])])[0]
        self.assertIn("fires_on", e["malformed"])
        self.assertFalse(e["cashable"])

    def test_missing_fires_on(self):
        e = ledger.pre_registrations(techs=[tech(pre_registered=[{"condition": "c"}])])[0]
        self.assertIn("fires_on", e["malformed"])

    def test_not_a_mapping(self):
        e = ledger.pre_registrations(techs=[tech(pre_registered=["just a sentence"])])[0]
        self.assertEqual(e["malformed"], "not a mapping")
        self.assertFalse(e["cashable"])

    def test_malformed_still_names_its_technique(self):
        e = ledger.pre_registrations(techs=[tech(id="T042", pre_registered=["x"])])[0]
        self.assertEqual(e["id"], "T042")


class AnAbsenceIsNeverCashedAgainstAnUnobservedWindow(unittest.TestCase):
    """The 2026-10-28 case, which is the reason this module exists."""

    def setUp(self):
        self._real = ledger.read_results
        ledger._DATES_CACHE.clear()

    def tearDown(self):
        ledger.read_results = self._real
        ledger._DATES_CACHE.clear()

    def nights(self, dates):
        ledger.read_results = lambda *a, **k: [{"date": d} for d in dates]
        ledger._DATES_CACHE.clear()

    def test_due_on_the_clock_but_short_of_nights_is_not_cashable(self):
        self.nights(["2026-09-29", "2026-09-30"])
        e = ledger.pre_registrations(
            as_of="2026-10-28",
            techs=[tech(pre_registered=[reg(fires_on="absence", since="2026-09-28",
                                            needs_nights=30, decide_on="2026-10-28")])])[0]
        self.assertTrue(e["due"])
        self.assertFalse(e["cashable"])
        self.assertEqual(e["observed_nights"], 2)
        self.assertEqual(e["shortfall"], 28)
        self.assertIn("DO NOT CASH IT", e["why_not"])

    def test_the_same_record_is_cashable_once_the_nights_are_there(self):
        self.nights([f"2026-10-{d:02d}" for d in range(1, 31)])
        e = ledger.pre_registrations(
            as_of="2026-10-31",
            techs=[tech(pre_registered=[reg(fires_on="absence", since="2026-09-28",
                                            needs_nights=30, decide_on="2026-10-28")])])[0]
        self.assertTrue(e["due"])
        self.assertTrue(e["cashable"])
        self.assertEqual(e["shortfall"], 0)

    def test_an_unreadable_since_is_not_treated_as_zero_nights(self):
        """None and 0 are different answers, and neither may cash an absence."""
        self.nights(["2026-10-01"])
        e = ledger.pre_registrations(
            as_of="2026-10-28",
            techs=[tech(pre_registered=[reg(fires_on="absence", since=None,
                                            needs_nights=30, decide_on="2026-10-28")])])[0]
        self.assertTrue(e["due"])
        self.assertFalse(e["cashable"])
        self.assertIsNone(e["observed_nights"])
        self.assertIn("DO NOT CASH IT", e["why_not"])

    def test_an_event_condition_is_cashable_on_the_clock_without_nights(self):
        """The asymmetry. A gap can only delay an event, so it is not blocked."""
        self.nights([])
        e = ledger.pre_registrations(
            as_of="2026-10-28",
            techs=[tech(pre_registered=[reg(fires_on="event", since="2026-09-28",
                                            needs_nights=30, decide_on="2026-10-28")])])[0]
        self.assertTrue(e["due"])
        self.assertTrue(e["cashable"])

    def test_zero_needed_nights_lets_an_absence_cash(self):
        """needs_nights=0 says the condition is not a duration. Honour it."""
        self.nights([])
        e = ledger.pre_registrations(
            as_of="2026-10-28",
            techs=[tech(pre_registered=[reg(fires_on="absence", since="2026-09-28",
                                            needs_nights=0, decide_on="2026-10-28")])])[0]
        self.assertTrue(e["cashable"])


class BookedInMeasuredNightsInsteadOfDates(unittest.TestCase):
    """decide_on=None is the re-pointing three entries asked for and none could express."""

    def setUp(self):
        self._real = ledger.read_results
        ledger._DATES_CACHE.clear()

    def tearDown(self):
        ledger.read_results = self._real
        ledger._DATES_CACHE.clear()

    def nights(self, dates):
        ledger.read_results = lambda *a, **k: [{"date": d} for d in dates]
        ledger._DATES_CACHE.clear()

    def test_not_due_while_nights_are_owed(self):
        self.nights([f"2026-10-{d:02d}" for d in range(1, 15)])
        e = ledger.pre_registrations(
            as_of="2026-12-25",
            techs=[tech(pre_registered=[reg(fires_on="absence", since="2026-09-28",
                                            needs_nights=30, decide_on=None)])])[0]
        self.assertFalse(e["due"])
        self.assertEqual(e["shortfall"], 16)
        self.assertIn("16 more measured nights", e["why_not"])

    def test_no_calendar_can_drift_it(self):
        """A year later, with the same evidence, it is still not due."""
        self.nights([f"2026-10-{d:02d}" for d in range(1, 15)])
        e = ledger.pre_registrations(
            as_of="2027-10-28",
            techs=[tech(pre_registered=[reg(fires_on="absence", since="2026-09-28",
                                            needs_nights=30, decide_on=None)])])[0]
        self.assertFalse(e["due"])

    def test_becomes_due_on_the_nights_alone(self):
        self.nights([f"2026-10-{d:02d}" for d in range(1, 31)])
        e = ledger.pre_registrations(
            as_of="2026-10-31",
            techs=[tech(pre_registered=[reg(fires_on="absence", since="2026-09-28",
                                            needs_nights=30, decide_on=None)])])[0]
        self.assertTrue(e["due"])
        self.assertTrue(e["cashable"])

    def test_a_shut_gate_says_what_it_is_waiting_on(self):
        self.nights(["2026-10-01"])
        e = ledger.pre_registrations(
            techs=[tech(pre_registered=[reg(fires_on="event", since=None, needs_nights=30,
                                            decide_on=None, gate="a /guide/ URL is fetched")])])[0]
        self.assertFalse(e["due"])
        self.assertIn("a /guide/ URL is fetched", e["why_not"])


class ItReportsAndMutatesNothing(unittest.TestCase):
    """Same invariant as verdict_staleness: the record is the record."""

    def test_the_stored_condition_comes_back_untouched(self):
        r = reg(condition="EXACT TEXT", fires_on="absence", since="2026-09-28",
                needs_nights=30, decide_on="2026-10-28")
        snapshot = dict(r)
        t = tech(pre_registered=[r])
        ledger.pre_registrations(techs=[t], as_of="2026-10-28")
        self.assertEqual(r, snapshot)
        self.assertEqual(t["pre_registered"], [r])

    def test_the_condition_is_echoed_verbatim(self):
        e = ledger.pre_registrations(
            techs=[tech(pre_registered=[reg(condition="verbatim please")])])[0]
        self.assertEqual(e["condition"], "verbatim please")


class CashableSortsFirst(unittest.TestCase):
    def setUp(self):
        self._real = ledger.read_results
        ledger.read_results = lambda *a, **k: [{"date": "2026-10-01"}]
        ledger._DATES_CACHE.clear()

    def tearDown(self):
        ledger.read_results = self._real
        ledger._DATES_CACHE.clear()

    def test_order_is_cashable_then_due_then_pending(self):
        techs = [
            tech(id="T001", pre_registered=[reg(fires_on="absence", since=None,
                                                needs_nights=5, decide_on="2026-01-01")]),
            tech(id="T002", pre_registered=[reg(fires_on="event", decide_on=None,
                                                since=None, needs_nights=0, gate="g")]),
            tech(id="T003", pre_registered=[reg(fires_on="event",
                                                decide_on="2026-01-01")]),
        ]
        out = ledger.pre_registrations(techs=techs, as_of="2026-10-28")
        self.assertEqual([e["id"] for e in out], ["T003", "T001", "T002"])
        self.assertTrue(out[0]["cashable"])
        self.assertTrue(out[1]["due"] and not out[1]["cashable"])
        self.assertFalse(out[2]["due"])


class TodaysLedgerHoldsTheThreeKnownConditions(unittest.TestCase):
    """Checkable from the repo, with no droplet, for as long as the pause lasts."""

    def setUp(self):
        self.regs = ledger.pre_registrations(as_of="2026-10-28")
        self.by_id = {e["id"]: e for e in self.regs}

    def test_exactly_T013_T017_T023_carry_one(self):
        self.assertEqual(sorted(self.by_id), ["T013", "T017", "T023"])

    def test_none_is_malformed(self):
        self.assertEqual([e["id"] for e in self.regs if e.get("malformed")], [])

    def test_T013_is_the_only_absence_shaped_one(self):
        self.assertEqual([i for i, e in self.by_id.items() if e["fires_on"] == "absence"],
                         ["T013"])

    def test_T013_is_short_of_the_nights_the_pause_cost(self):
        """14 measured nights 2026-09-29..2026-10-12, of the 30 it needs."""
        e = self.by_id["T013"]
        self.assertEqual(e["observed_nights"], 14)
        self.assertEqual(e["needs_nights"], 30)
        self.assertEqual(e["shortfall"], 16)
        self.assertFalse(e["due"])
        self.assertFalse(e["cashable"])

    def test_nothing_is_cashable_while_the_engine_is_paused(self):
        self.assertEqual([e["id"] for e in self.regs if e["cashable"]], [])

    def test_no_condition_is_booked_on_a_calendar_date_any_more(self):
        """All three were re-pointed off the clock. A new one should be too."""
        self.assertEqual([e["id"] for e in self.regs if e.get("decide_on")], [])

    def test_every_condition_carries_text_and_a_written_date(self):
        for e in self.regs:
            self.assertTrue(e["condition"], e["id"])
            self.assertTrue(e["written"], e["id"])
            datetime.date.fromisoformat(e["written"])

    def test_seed_py_still_owns_the_two_seeded_ones(self):
        """A ledger-only edit would be one deploy from reversion."""
        from growth import seed
        want = {s["slug"]: s["pre_registered"] for s in seed.SEEDS if s.get("pre_registered")}
        self.assertEqual(sorted(want), ["city_guides", "city_seo_expansion"])
        for t in ledger.load_techniques():
            if t["slug"] in want:
                self.assertEqual(t["pre_registered"], want[t["slug"]], t["slug"])


class StatusPrintsThem(unittest.TestCase):
    def test_the_block_names_the_uncashable_absence(self):
        import growth_daily
        lines = growth_daily.pre_registration_lines(as_of="2026-10-28")
        text = "\n".join(lines)
        self.assertIn("pre-registered conditions (3)", text)
        self.assertIn("0 ready to decide", text)
        self.assertIn("T013", text)
        self.assertIn("14 of 30 measured nights", text)

    def test_an_empty_ledger_says_so_rather_than_printing_a_header(self):
        import growth_daily
        real = ledger.pre_registrations
        ledger.pre_registrations = lambda *a, **k: []
        try:
            self.assertEqual(growth_daily.pre_registration_lines(),
                             ["pre-registered conditions: none recorded"])
        finally:
            ledger.pre_registrations = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
