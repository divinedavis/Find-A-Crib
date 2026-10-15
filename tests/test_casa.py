#!/usr/bin/env python3
"""Your Casa (owner, 2026-10-15): 311 calls on a building, crime nearby, and
a Plus watch with alerts.

The watch is written only through /casa/watch, keyed on the verified session
and gated on has_plus(); the table denies every client write. The alert job's
crime kinds, the API's allow-list and the app's chips must agree."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


class CasaWatchRoute(unittest.TestCase):
    def setUp(self):
        api = read("api_server.py")
        start = api.index("def casa_watch():")
        self.body = api[start:api.index("\ndef ", start + 10)]
        self.api = api

    def test_account_comes_from_the_session_and_plus_from_the_server(self):
        self.assertIn("_session_user()", self.body)
        self.assertIn('rpc("has_plus", {"uid": u["id"]})', self.body)
        self.assertIn('error="plus_required"), 402', self.body)
        self.assertNotRegex(self.body, r'get\("(user_id|email|uid)"\)', "never an account id or email from the body")
        self.assertLess(self.body.index("if not plus:"), self.body.index('"casa_watches?on_conflict=user_id"'),
                        "the Plus check comes before the write")

    def test_bbl_and_kinds_are_validated(self):
        self.assertIn("BBL_RE.match(bbl)", self.body)
        self.assertIn("k in CASA_CRIME_KINDS", self.body)
        self.assertTrue(self.api.count('request.path.startswith("/casa/")') == 1, "/casa/ skips the API-key gate")

    def test_kinds_match_the_job_and_the_app(self):
        import casa_alerts
        api_kinds = set(re.findall(r'"(\w+)"', self.api[self.api.index("CASA_CRIME_KINDS = {"):][:300].split("}")[0]))
        self.assertEqual(api_kinds, set(casa_alerts.CRIME_KINDS))
        swift = read("ios", "FindACrib", "Services", "CasaService.swift")
        chips = re.findall(r'\("(\w+)", "[^"]+"\)', swift[swift.index("static let crimeKinds"):][:600])
        self.assertEqual(set(chips), set(casa_alerts.CRIME_KINDS))


class CasaTable(unittest.TestCase):
    def test_clients_cannot_write_or_truncate(self):
        sql = read("supabase", "migrations", "20261015120000_casa_watches.sql")
        self.assertIn("enable row level security", sql)
        self.assertIn("revoke insert, update, delete, truncate, trigger, references on public.casa_watches from anon, authenticated;", sql)
        self.assertIn("using (auth.uid() = user_id)", sql)


class CasaAlertText(unittest.TestCase):
    def setUp(self):
        import casa_alerts
        self.c = casa_alerts

    def test_pests_lead_the_311_push(self):
        calls = [{"complaint_type": "Noise - Residential", "descriptor": "Loud Music/Party"},
                 {"complaint_type": "UNSANITARY CONDITION", "descriptor": "PESTS"},
                 {"complaint_type": "Rodent", "descriptor": "Rat Sighting"}]
        title, body = self.c.push_text("350 W 42nd Street", calls)
        self.assertEqual(title, "3 new 311 calls at 350 W 42nd Street")
        self.assertIn("Pests", body)
        self.assertIn("2 about pests", body)
        self.assertFalse(self.c.is_pest({"complaint_type": "HEAT/HOT WATER", "descriptor": "APARTMENT ONLY"}))

    def test_crime_push_names_the_dates_first_and_counts_plurals(self):
        title, body = self.c.crime_text("350 W 42nd Street", {"robbery": 1, "shootings": 2, "theft": 0},
                                        "2026-03-31", "2026-06-30")
        self.assertEqual(title, "New NYPD reports near 350 W 42nd Street")
        self.assertEqual(body, "Apr 1 – Jun 30, within half a mile: 2 shootings, 1 robbery")

    def test_email_renders(self):
        # emailkit cards need "heading" (a dry run on the droplet caught "title").
        from growth import emailkit
        w = {"bbl": "1017480035", "address": "1919 Madison Avenue"}
        calls = [{"complaint_type": "Rodent", "descriptor": "Rat Sighting", "created_date": "2026-10-12T14:00:33.000", "status": "In Progress"}]
        subject, html, text = self.c.email_parts(emailkit, w, calls)
        self.assertEqual(subject, "New 311 call at 1919 Madison Avenue")
        self.assertIn("Rodent — Rat Sighting\n  Oct 12, 2026 · In Progress · pests", text)
        self.assertIn("/casa/?bbl=1017480035", html)

    def test_distance(self):
        self.assertAlmostEqual(self.c.metres(40.7585, -73.9925, 40.7585 + 800 / 111_000, -73.9925), 800, delta=10)


if __name__ == "__main__":
    unittest.main()
