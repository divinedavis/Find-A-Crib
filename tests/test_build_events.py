#!/usr/bin/env python3
"""Unit tests for build_events.py — the Events tab feed. No network.

    python3 tests/test_build_events.py
"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_events as B  # noqa: E402

TODAY = dt.date(2026, 9, 22)


def ev(title, start, address="6206 6th Ave, Brooklyn, NY 11220", agency="hpd", **kw):
    d = {"name": title, "startDate": start, "endDate": kw.pop("end", None), "address": address,
         "categories": kw.pop("categories", []), "permalink": kw.pop("url", f"/events/{abs(hash(title + start))}"),
         "shortDesc": kw.pop("desc", ""), "_agency": agency}
    d.update(kw)
    return d


class Build(unittest.TestCase):
    def test_the_flyer_event_from_two_agencies_is_one_event_with_both_hosts(self):
        raw = [ev("Tenant Clinic with AAANY", "09/23/2026 10:00 AM", agency="hpd"),
               ev("Access Benefits at AAANY Tenant Support Clinic", "09/23/2026 10:00 AM",
                  address="6206 6th Avenue, Brooklyn NY 11220", agency="mayorspeu")]
        out = B.build(raw, TODAY)
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["hosts"], ["Mayor's Public Engagement Unit", "NYC Housing Preservation & Development"])
        self.assertEqual(len(out[0]["links"]), 2, "both agencies' pages are kept")
        self.assertEqual(out[0]["title"], "Access Benefits at AAANY Tenant Support Clinic", "the fuller title wins")

    def test_same_event_listed_twice_by_one_agency_is_one(self):
        raw = [ev("HPD In Your District: Council District 38", "09/24/2026 06:00 PM"),
               ev("HPD In Your District: Council District 38", "09/24/2026 06:00 PM")]
        self.assertEqual(len(B.build(raw, TODAY)), 1)

    def test_same_place_different_days_stay_separate(self):
        raw = [ev("Tenant Resource Fair", "09/24/2026 10:00 AM"), ev("Tenant Resource Fair", "10/01/2026 10:00 AM")]
        self.assertEqual(len(B.build(raw, TODAY)), 2)

    def test_same_day_different_places_stay_separate(self):
        raw = [ev("Tenant Resource Fair", "09/24/2026 10:00 AM", address="1 Centre St, New York, NY"),
               ev("Tenant Resource Fair", "09/24/2026 10:00 AM", address="210 Joralemon St, Brooklyn, NY")]
        self.assertEqual(len(B.build(raw, TODAY)), 2)

    def test_same_day_same_place_unrelated_titles_stay_separate(self):
        raw = [ev("Tenant Resource Fair", "09/24/2026 10:00 AM"),
               ev("Property Owner Clinic: Lead Paint", "09/24/2026 02:00 PM")]
        self.assertEqual(len(B.build(raw, TODAY)), 2)

    def test_non_housing_and_past_events_are_dropped(self):
        raw = [ev("Access Benefits: SNAP enrollment tabling", "09/25/2026 10:00 AM", agency="mayorspeu"),
               ev("Tenant Clinic", "09/01/2026 10:00 AM"),
               ev("Know your rights: eviction help", "09/25/2026 10:00 AM", agency="mayorspeu")]
        titles = [e["title"] for e in B.build(raw, TODAY)]
        self.assertEqual(titles, ["Know your rights: eviction help"])

    def test_ids_are_stable_across_runs_and_hosts(self):
        a = B.build([ev("Tenant Clinic", "09/23/2026 10:00 AM", agency="hpd")], TODAY)[0]["id"]
        b = B.build([ev("Tenant Clinic", "09/23/2026 10:00 AM", agency="mayorspeu")], TODAY)[0]["id"]
        self.assertEqual(a, b, "the app de-duplicates saved events on this id")

    def test_address_normalising(self):
        self.assertEqual(B.norm_address("6206 6th Avenue, Brooklyn"), B.norm_address("6206 6th Ave., Brooklyn NY"))
        self.assertNotEqual(B.norm_address("6206 6th Ave"), B.norm_address("6208 6th Ave"))

    def test_tolerant_field_names_and_dates(self):
        raw = [{"title": "Tenant Fair", "start": "2026-09-30T13:00:00", "location": {"street": "1 Centre St", "city": "New York"},
                "borough": "Manhattan", "url": "https://www.nyc.gov/x", "_agency": "hpd"},
               {"Name": "Eviction prevention clinic", "StartDate": "09/30/2026", "Address": "900 Grand Concourse, Bronx", "_agency": "mayorspeu"}]
        out = B.build(raw, TODAY)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["start"], "2026-09-30T00:00:00")
        self.assertTrue(out[0]["all_day"])
        self.assertEqual(out[0]["borough"], "Bronx", "borough read from the address when the field is missing")
        self.assertEqual(out[1]["start"], "2026-09-30T13:00:00")

    def test_wrapped_payloads(self):
        self.assertEqual(len(B.items_of({"items": [1, 2]})), 2)
        self.assertEqual(len(B.items_of([1])), 1)
        self.assertEqual(B.items_of({"nothing": 1}), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
