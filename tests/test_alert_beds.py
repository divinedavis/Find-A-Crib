"""Alerts honour the Beds choice (owner, 2026-11-24).

He had "1" picked under Beds in the app's Lotteries filter and was sent
"New re-rental in Brooklyn: 325 Gates Ave." — a studio. Two gaps: the choice
never left the phone, and a re-rental found by an intraday sweep carried no
size for any filter to use. These pin both, end to end and offline.
"""
import json
import os
import re
import tempfile
import unittest
from unittest import mock

import lottery_alerts as L
import rerental_daily as rd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = "Example Housing Group"
SUB = {"email": "renter@example.com", "kinds": ["lottery", "rerental"], "boroughs": ["Bk"]}


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


def rerental(**kw):
    row = {"agent": AGENT, "key": "10 example", "label": "10 Example Ave.", "url": "https://agent.example/board",
           "boro": "Brooklyn", "hood": "Bedford-Stuyvesant", "rent_low": None, "income_max": None}
    row.update(kw)
    return L.rerental_items({"items": [row]})[0]


def lottery(beds):
    return L.hc_items({"lotteries": [{"id": 7, "name": "Example Court", "borough": "Brooklyn", "beds": beds,
                                      "href": "https://housingconnect.example/7"}]})[0]


class Sender(unittest.TestCase):
    def test_a_studio_is_not_sent_to_someone_who_asked_for_one_bedrooms(self):
        studio = rerental(beds=[0])
        self.assertFalse(L.wants(dict(SUB, beds=[1]), studio))
        self.assertTrue(L.wants(dict(SUB, beds=[0, 1]), studio))
        self.assertTrue(L.wants(dict(SUB, beds=[]), studio))
        self.assertTrue(L.wants(SUB, studio))                      # never chose: every size

    def test_a_listing_that_states_no_size_still_goes_out(self):
        # hiding it would say "none for you" when the truth is "not stated"
        self.assertTrue(L.wants(dict(SUB, beds=[1]), rerental()))

    def test_a_lottery_with_several_sizes_goes_to_anyone_wanting_one_of_them(self):
        lot = lottery(["Studio", "2-bed"])
        self.assertEqual(lot["bed_sizes"], [0, 2])
        self.assertFalse(L.wants(dict(SUB, beds=[1]), lot))
        self.assertTrue(L.wants(dict(SUB, beds=[2]), lot))
        self.assertTrue(L.wants(dict(SUB, beds=[1]), lottery(None)))

    def test_the_alert_itself_says_the_size(self):
        item = rerental(beds=[0], rent_low=2368)
        self.assertEqual(item["beds"], "Studio")
        self.assertIn("Studio", item["sub"])
        self.assertIsNone(rerental()["beds"])
        self.assertEqual(L.bed_label([1, 2, 4]), "1-bed / 2-bed / 4+ bed")

    def test_a_flyers_unit_table_fills_in_a_missing_size_only(self):
        blank, stated = rerental(), rerental(beds=[2])
        table = {"https://agent.example/board": {"units": [{"beds": 1, "income_max": 90000}, {"beds": 1}]}}
        L.enrich_rerentals([blank, stated], table)
        self.assertEqual(blank["bed_sizes"], [1])
        self.assertEqual(stated["bed_sizes"], [2])

    def test_the_footer_names_the_sizes(self):
        self.assertIn("1-bedrooms", L.filter_words(dict(SUB, beds=[1])))
        self.assertEqual(L.filter_words(SUB), "")

    def test_choices_are_read_from_their_own_rpc_and_a_failure_filters_nobody(self):
        def rpc(name, body, key):
            return {"lottery_alerts_beds_all": [{"email": "renter@example.com", "beds": [1]}]}.get(name, [])
        with mock.patch.object(L, "rpc", side_effect=rpc):
            subs = L.with_households([dict(SUB), dict(SUB, email="other@example.com")], "k")
        self.assertEqual([s["beds"] for s in subs], [[1], []])
        with mock.patch.object(L, "rpc", side_effect=OSError("down")):
            subs = L.with_households([dict(SUB)], "k")
        self.assertEqual(subs[0]["beds"], [])


class Sweep(unittest.TestCase):
    """A listing that is new right now gets its size and rent off the board."""

    CARD = {"agent": AGENT, "address": "10 Example Ave.", "borough": "Brooklyn", "money_kind": "rent",
            "money_low": 2368, "income_1p_max": 154440, "beds": "2",
            "_card": ["10 Example Ave.", "Brooklyn, NY", "Unit Size: 0", "Rent: $2,368.05"]}

    def record(self, fresh, items=None):
        items = items or [{"key": rd.key_of("10 Example Ave."), "label": "10 Example Ave.", "url": None}]
        results = {AGENT: {"url": "https://agent.example/board", "error": None, "items": items,
                           "stated": 0, "waitlist": False}}
        deltas = {AGENT: {"new": items, "gone": [], "failed": False}}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rd, "NEW_FEED", os.path.join(d, "new.json")), \
                mock.patch.object(rd, "PLACES", os.path.join(d, "places.json")), \
                mock.patch.object(rd, "place_of", return_value={"hood": "Bedford-Stuyvesant", "boro": "Brooklyn"}), \
                mock.patch.object(rd, "featured_money", return_value={}):
            rd.record_new(deltas, results, "2026-11-24", fresh=fresh)
            with open(os.path.join(d, "new.json")) as f:
                return json.load(f)["items"][0]

    def test_the_cards_own_text_beats_the_tiles_single_size(self):
        figs = rd.figures_of([self.CARD])
        self.assertEqual(figs[(AGENT, rd.key_of("10 Example Ave."))],
                         {"boro": "Brooklyn", "rent_low": 2368, "income_max": 154440, "beds": [0]})
        self.assertEqual(rd.figures_of([dict(self.CARD, _card=None)])[(AGENT, rd.key_of("10 Example Ave."))]["beds"], [2])

    def test_a_new_listing_is_recorded_with_what_the_board_says_now(self):
        fresh = mock.Mock(return_value=rd.figures_of([self.CARD]))
        row = self.record(fresh)
        fresh.assert_called_once_with({AGENT})
        self.assertEqual((row["beds"], row["rent_low"]), ([0], 2368))
        # ...and that row is what keeps the studio from a 1-bedroom subscriber
        item = L.rerental_items({"items": [row]})[0]
        self.assertFalse(L.wants(dict(SUB, beds=[1]), item))
        self.assertTrue(L.wants(dict(SUB, beds=[0]), item))

    def test_nothing_is_fetched_unless_asked_and_a_failed_read_still_records(self):
        self.assertNotIn("beds", self.record(None))                         # tests and old callers: offline
        self.assertNotIn("beds", self.record(mock.Mock(return_value={})))   # board unreadable: sent without

    def test_an_item_that_already_states_its_size_costs_no_second_read(self):
        fresh = mock.Mock(return_value={})
        row = self.record(fresh, [{"key": "feed 1", "label": "Example Court", "url": None, "beds": [1, 2]}])
        fresh.assert_not_called()
        self.assertEqual(row["beds"], [1, 2])

    def test_fresh_figures_is_bounded_and_never_raises(self):
        seen = []
        def sweep(pages):
            seen.append(sorted(pages))
            return [self.CARD]
        pages = {f"Agent {i:02d}": {"url": "https://agent.example"} for i in range(20)}
        out = rd.fresh_figures(set(pages), pages, sweep)
        self.assertEqual(len(seen[0]), rd.FRESH_MAX)
        self.assertIn((AGENT, rd.key_of("10 Example Ave.")), out)
        self.assertEqual(rd.fresh_figures({"Agent 01"}, pages, mock.Mock(side_effect=RuntimeError("no browser"))), {})
        self.assertEqual(rd.fresh_figures(set(), pages, sweep), {})
        self.assertEqual(rd.fresh_figures({"Nobody"}, pages, sweep), {})

    def test_the_real_sweep_asks_for_fresh_figures(self):
        self.assertIn("record_new(deltas, results, today, fresh=fresh_figures)", read("pipeline", "rerental_daily.py"))


class Api(unittest.TestCase):
    def setUp(self):
        self.api = read("api", "api_server.py")
        ns = {}
        src = self.api[self.api.index("def _alert_beds(raw):"):]
        exec(src[:src.index("\n@app.route")], ns)
        self.clean = ns["_alert_beds"]

    def fn(self, name):
        body = self.api[self.api.index(f"def {name}():"):]
        return body[:body.index("\n@app.route")]

    def test_only_the_five_sizes_are_accepted(self):
        self.assertEqual(self.clean([1]), [1])
        self.assertEqual(self.clean([4, 0, 0]), [0, 4])
        self.assertEqual(self.clean([]), [])
        self.assertEqual(self.clean(None), [])
        for bad in ([5], [-1], ["1"], [1.0], [True], "1", {"1": 1}, [0, 1, 2, 3, 4, 0]):
            self.assertIsNone(self.clean(bad), bad)

    def test_setting_beds_uses_only_the_session_email(self):
        body = self.fn("alerts_beds")
        self.assertIn('rpc("lottery_alerts_set_beds", {"p_email": email, "p_beds": beds})', body)
        self.assertLess(body.index("_session_email()"), body.index("lottery_alerts_set_beds"))
        self.assertNotRegex(body, r"request\.(args|form)|\.get\(.email")
        self.assertIn("request.is_json", body)
        self.assertIn('methods=["POST"]', self.api[self.api.index('"/alerts/beds"') - 20:][:60])
        self.assertIn('"bad_beds"', body)

    def test_subscribe_changes_beds_only_when_the_client_sends_them(self):
        body = self.fn("alerts_subscribe")
        self.assertIn('if res.get("ok") and "beds" in body:', body)
        self.assertIn('"bad_beds"', body)

    def test_prefs_report_the_choice(self):
        self.assertIn('res["beds"] = _alert_beds(rpc("lottery_alerts_beds", {"p_email": email})) or []',
                      self.fn("alerts_prefs"))

    def test_the_functions_are_service_role_only(self):
        sql = read("db", "0079_alert_beds.sql")
        for sig in ("lottery_alerts_set_beds(text, integer[])", "lottery_alerts_beds_all()", "lottery_alerts_beds(text)"):
            self.assertIn(f"revoke all on function public.{sig} from public, anon, authenticated;", sql)
            self.assertIn(f"grant execute on function public.{sig} to service_role;", sql)
        self.assertEqual(len(re.findall(r"security definer set search_path to 'public'", sql)), 3)
        self.assertIn("beds <@ array[0, 1, 2, 3, 4]::smallint[]", sql)


if __name__ == "__main__":
    unittest.main()
