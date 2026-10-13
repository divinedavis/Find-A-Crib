#!/usr/bin/env python3
"""Renter tools (2026-10-13): the rules behind repairs, rent increases,
rights and the renewal coach, and the gateway's free (account-only) path."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_gateway  # noqa: E402
import renter_tools as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Repair(unittest.TestCase):
    def test_heat_letter_cites_the_code_and_asks_by_tomorrow(self):
        r = R.repair({"issue": "heat", "address": "30 Allen St", "unit": "4B", "today": "2026-10-13"})
        self.assertTrue(r["urgent"])
        self.assertEqual(r["ask_by"], "2026-10-14")
        self.assertIn("§ 27-2029", r["letter"])
        self.assertIn("30 Allen St, Apt 4B", r["letter"])
        self.assertIn("68°F", r["rule"])

    def test_unknown_issue_and_future_date_fall_back(self):
        r = R.repair({"issue": "<script>", "since": "2099-01-01", "today": "2026-10-13"})
        self.assertEqual(r["issue"], "other")
        self.assertNotIn("2099", r["letter"])
        self.assertIn("[Your name]", r["letter"])

    def test_every_issue_has_a_law(self):
        for k, it in R.ISSUES.items():
            self.assertTrue(it["law"] and it["rule"], k)


class RentIncrease(unittest.TestCase):
    def test_2026_freeze_flags_any_stabilized_increase(self):
        r = R.rent_increase({"stabilized": "yes", "current_rent": "2000", "new_rent": "2060", "term": "1", "lease_start": "2026-11-01"})
        self.assertEqual(r["verdict"], "likely_illegal")
        self.assertEqual(r["allowed_rent"], 2000.0)

    def test_order_57_allows_three_percent(self):
        r = R.rent_increase({"stabilized": "yes", "current_rent": "2000", "new_rent": "2060", "term": "1", "lease_start": "2026-02-01"})
        self.assertEqual(r["verdict"], "looks_ok")
        r = R.rent_increase({"stabilized": "yes", "current_rent": "2000", "new_rent": "2090", "term": "2", "lease_start": "2026-02-01"})
        self.assertEqual(r["allowed_rent"], 2090.0)

    def test_orders_cover_contiguous_years(self):
        import datetime
        orders = sorted(R.RGB_ORDERS, key=lambda o: o[1])
        for a, b in zip(orders, orders[1:]):
            self.assertEqual(datetime.date.fromisoformat(a[2]) + datetime.timedelta(days=1), datetime.date.fromisoformat(b[1]))

    def test_good_cause_and_notice(self):
        r = R.rent_increase({"stabilized": "no", "current_rent": "2000", "new_rent": "2300", "years": "3", "notice_days": "30"})
        self.assertEqual(r["verdict"], "likely_illegal")
        titles = " ".join(f["title"] for f in r["findings"])
        self.assertIn("8.38%", titles)
        self.assertIn("30 days", titles)
        ok = R.rent_increase({"stabilized": "no", "current_rent": "2000", "new_rent": "2100", "years": "3", "notice_days": "90"})
        self.assertEqual(ok["verdict"], "looks_ok")

    def test_missing_rents(self):
        self.assertEqual(R.rent_increase({"stabilized": "no", "current_rent": "", "new_rent": "x"})["verdict"], "need_rents")


class Renewal(unittest.TestCase):
    def test_dates_compare_and_check(self):
        r = R.renewal({"lease_end": "2027-01-31", "current_rent": "2400", "offered_rent": "2500", "stabilized": "yes",
                       "zip": "11216", "beds": "1", "today": "2026-10-13"}, {"11216": [3000, 3350, 3900, 4800]})
        labels = [d["label"] for d in r["dates"]]
        self.assertIn("Your lease ends", labels)
        self.assertTrue(any("earliest" in x for x in labels))
        self.assertEqual(r["compare"]["fmr"], 3350)
        self.assertEqual(r["check"]["verdict"], "likely_illegal")      # starts 2027-02-01: Order #58, 0%
        self.assertEqual(len(r["reminders"]), 1)

    def test_no_zip_no_compare(self):
        r = R.renewal({"lease_end": "2027-01-31", "current_rent": "2400"}, {})
        self.assertIsNone(r["compare"])
        self.assertIsNone(r["check"])


class Rights(unittest.TestCase):
    def test_cards_have_ids_laws_and_the_current_numbers(self):
        ids = [c["id"] for c in R.RIGHTS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(c["law"] for c in R.RIGHTS))
        blob = " ".join(c["text"] for c in R.RIGHTS)
        self.assertIn(f"{R.LOCAL_RENT_STANDARD:g}%", blob)
        self.assertIn("0% increase", blob)

    def test_ai_schema_only_cites_real_cards(self):
        enum = R.SCHEMAS["rights_answer"]["properties"]["cards"]["items"]["enum"]
        self.assertEqual(enum, [c["id"] for c in R.RIGHTS])


class FreeGateway(unittest.TestCase):
    USER = {"id": "00000000-0000-0000-0000-000000000001"}

    def gw(self, plus):
        a = {"has_plus": plus, "ai_user_calls_today": 0, "ai_user_spend_month": 0, "ai_spend_month": 0}
        return ai_gateway.Gateway(lambda fn, params: a[fn], "https://x.invalid", "k")

    def test_free_rules_tool_needs_an_account_not_plus(self):
        self.assertIsNone(self.gw(False).allow(self.USER, "repair", "rules", plus=False))
        self.assertEqual(self.gw(False).allow(None, "repair", "rules", plus=False), "sign_in_required")

    def test_a_model_can_never_skip_plus(self):
        self.assertEqual(self.gw(False).allow(self.USER, "rights_answer", R.MODEL, plus=False), "budget")
        self.assertEqual(self.gw(False).allow(self.USER, "rights_answer", R.MODEL), "plus_required")
        self.assertIn(R.MODEL, ai_gateway.PRICES)

    def test_api_routes_gate_as_designed(self):
        src = open(os.path.join(ROOT, "api_server.py")).read()
        self.assertIn('_rules_tool("repair", renter_tools.repair, _REPAIR_KEYS)', src)
        self.assertIn('_rules_tool("renewal", lambda a: renter_tools.renewal(a, FMR), _RENEWAL_KEYS, plus=True)', src)
        self.assertIn("renter_tools.py", open(os.path.join(ROOT, "scripts", "deploy_api.sh")).read())


if __name__ == "__main__":
    unittest.main()
