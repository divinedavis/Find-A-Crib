#!/usr/bin/env python3
"""Your Crib (owner, 2026-10-15): 311 calls on a building, crime nearby, and
a watch with alerts — crime alerts free for any account (10/19), 311 alerts
Plus.

The watch is written only through /casa/watch, keyed on the verified session;
the alert job checks has_plus() before any 311 alert; the table denies every
client write. The alert job's
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
        api = read("api/api_server.py")
        start = api.index("def casa_watch():")
        self.body = api[start:api.index("\ndef ", start + 10)]
        self.api = api

    def test_account_comes_from_the_session_and_plus_from_the_server(self):
        self.assertIn("_session_user()", self.body)
        self.assertIn('rpc("has_plus", {"uid": u["id"]})', self.body)
        self.assertNotRegex(self.body, r'get\("(user_id|email|uid|plus)"\)', "never an account id, email or Plus from the body")

    def test_crime_alerts_are_free_and_311_alerts_are_plus(self):
        # Owner, 2026-10-19: "crime alerts should be free".
        self.assertNotIn("plus_required", self.body, "any account can save a watch")
        import casa_alerts, inspect
        main = inspect.getsource(casa_alerts.main)
        gate = main.index('la.rpc("has_plus"')
        self.assertLess(gate, main.index("run_311("), "311 alerts stay behind has_plus")
        self.assertNotIn("continue", main[gate - 80:gate + 120], "a lapsed or free account still gets crime alerts")
        self.assertNotIn("with Find A Crib Plus", inspect.getsource(casa_alerts.run_crime))

    def test_bbl_and_kinds_are_validated(self):
        self.assertIn("BBL_RE.match(bbl)", self.body)
        self.assertIn("k in CASA_CRIME_KINDS", self.body)
        self.assertTrue(self.api.count('request.path.startswith("/casa/")') == 1, "/casa/ skips the API-key gate")

    def test_kinds_match_the_job_and_the_app(self):
        import casa_alerts
        api_kinds = set(re.findall(r'"(\w+)"', self.api[self.api.index("CASA_CRIME_KINDS = {"):][:300].split("}")[0]))
        self.assertEqual(api_kinds, set(casa_alerts.CRIME_KINDS))
        swift = read("ios", "FindACrib", "Services", "CasaService.swift")
        # labels are String(localized: "…") since the app was translated (2026-10-16)
        chips = re.findall(r'\("(\w+)", (?:String\(localized: )?"[^"]+"\)?\)', swift[swift.index("static let crimeKinds"):][:1200])
        self.assertEqual(set(chips), set(casa_alerts.CRIME_KINDS))


class CasaRetries(unittest.TestCase):
    def test_app_and_web_retry_a_busy_data_service(self):
        # NYC Open Data answers a stray 503 about 1 in 15 (owner screenshot, 10/15).
        swift = read("ios", "FindACrib", "Services", "CasaService.swift")
        self.assertIn("for attempt in 0..<3", swift)
        self.assertIn("status == 429 || (500...599).contains(status)", swift)
        web = read("web", "casa", "index.html")
        self.assertIn("r.status === 429 || r.status >= 500 ? again(e)", web)
        self.assertIn('accessibilityIdentifier("casa-retry")', read("ios", "FindACrib", "Features", "Casa", "CasaView.swift"))


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

    def test_report_details_read_like_english(self):
        # Owner, 2026-11-06: each robbery the alert counted, listed.
        d = self.c.detail
        self.assertEqual(d("burglary", "BURGLARY", "BURGLARY,RESIDENCE,UNKNOWN TIM"), "residence")
        self.assertEqual(d("burglary", "BURGLARY", "BURGLARY,TRUCK DAY"), "truck")
        self.assertEqual(d("robbery", "ROBBERY", "ROBBERY,BEGIN AS SHOPLIFTING"), "begin as shoplifting")
        self.assertEqual(d("theft", "PETIT LARCENY", "LARCENY,PETIT OF BICYCLE"), "bicycle")
        self.assertEqual(d("car_theft", "GRAND LARCENY OF MOTOR VEHICLE", "LARCENY,GRAND OF AUTO"), "auto")
        self.assertEqual(d("assault", "FELONY ASSAULT", "ASSAULT 2,1,UNCLASSIFIED"), "felony")
        self.assertEqual(d("assault", "ASSAULT 3 & RELATED OFFENSES", "ASSAULT 3"), "")
        self.assertEqual(d("harassment", "HARRASSMENT 2", "HARASSMENT,SUBD 3"), "", "statute shorthand is left out")

    def test_report_line_has_date_time_place_and_distance(self):
        r = {"kind": "robbery", "title": "Robbery", "detail": "personal electronic device", "date": "2026-08-14",
             "time": "20:00", "place": "street", "metres": 640, "dir": "S", "attempted": True}
        head, sub = self.c.report_line(r)
        self.assertEqual(head, "Robbery — personal electronic device (attempted)")
        self.assertEqual(sub, "Aug 14 · 8:00 PM · street · 0.4\u00a0mi\u00a0S")
        self.assertEqual(self.c.bearing(40.0, -74.0, 40.01, -74.0), "N")
        self.assertEqual(self.c.bearing(40.0, -74.0, 39.99, -73.99), "SE")

    def test_reports_never_ask_for_suspect_or_victim_fields(self):
        import inspect
        src = inspect.getsource(self.c.crime_reports)
        self.assertNotRegex(src, r"susp_|vic_", "the list never fetches who the suspect or victim was")

    def test_crime_email_lists_each_report_and_links_to_the_list(self):
        from growth import emailkit
        reports = [{"kind": "robbery", "title": "Robbery", "detail": "dwelling", "date": f"2026-09-{d:02d}", "time": "08:00",
                    "place": "residence - apt. house", "metres": 600, "dir": "SW", "attempted": False} for d in range(11, 0, -1)]
        html, text = self.c.crime_email(emailkit, "1010330001", "350 W 42nd Street, New York", {"robbery": 11},
                                        reports, "2026-06-30", "2026-09-30")
        self.assertIn("Robbery — dwelling", text)
        self.assertEqual(text.count("Robbery — dwelling"), self.c.EMAIL_REPORTS, "the newest few in the email")
        self.assertIn("See all 11 on Your Crib", html)
        self.assertRegex(html, r"/casa/\?bbl=1010330001&(amp;)?src=casa_crime#crime-list", "the button opens the list")
        self.assertIn("newest 8 of 11", html)

    def test_crime_push_opens_the_list_of_reports(self):
        import inspect
        src = inspect.getsource(self.c.send)
        self.assertIn('"focus": "crime"', src, "the app opens Your Crib on the reports")
        self.assertIn("#crime-list", src)
        self.assertEqual(inspect.getsource(self.c.run_crime).count("crime=True"), 1)

    def test_email_renders(self):
        # emailkit cards need "heading" (a dry run on the droplet caught "title").
        from growth import emailkit
        w = {"bbl": "1017480035", "address": "1919 Madison Avenue"}
        calls = [{"complaint_type": "Rodent", "descriptor": "Rat Sighting", "created_date": "2026-10-12T14:00:33.000", "status": "In Progress"}]
        subject, html, text = self.c.email_parts(emailkit, w, calls)
        self.assertEqual(subject, "New 311 call at 1919 Madison Avenue")
        self.assertIn("• Rodent — Rat Sighting\n        Oct 12, 2026 · In Progress · pests", text)
        self.assertIn("/casa/?bbl=1017480035", html)
        # The alert card (2026-11-05): label top right, count large, open call red.
        self.assertIn("Your Casa", html)
        self.assertIn("1 still open", html)
        self.assertNotIn("<style", html)

    def test_alerts_wait_for_8_am(self):
        self.assertEqual(self.c.SEND_HOURS, range(8, 21))
        src = read("pipeline/casa_alerts.py")
        self.assertLess(src.index("SEND_HOURS and not args.dry_run"), src.index("watches = rest("), "quiet hours stop the run before any send")

    def test_distance(self):
        self.assertAlmostEqual(self.c.metres(40.7585, -73.9925, 40.7585 + 800 / 111_000, -73.9925), 800, delta=10)


if __name__ == "__main__":
    unittest.main()
