#!/usr/bin/env python3
"""ai_gateway.allow (2026-10-12): Plus only, a daily cap per feature, a $1
per-person monthly budget (owner: "lets do a per person budget of $1") that
free rules-only features never hit, and the shared monthly cap."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_gateway  # noqa: E402

USER = {"id": "00000000-0000-0000-0000-000000000001"}


def gateway(plus=True, today=0, mine=0, month=0):
    answers = {"has_plus": plus, "ai_user_calls_today": today, "ai_user_spend_month": mine, "ai_spend_month": month}
    return ai_gateway.Gateway(lambda fn, params: answers[fn], "https://x.invalid", "k")


class Budget(unittest.TestCase):
    def test_member_under_every_cap_goes_ahead(self):
        self.assertIsNone(gateway(mine=50_000).allow(USER, "apply_help", "claude-haiku-4-5"))

    def test_one_dollar_a_month_per_person(self):
        self.assertEqual(ai_gateway.USER_CAP_MICROS, 1_000_000)
        self.assertEqual(gateway(mine=1_000_000).allow(USER, "lease_review", "claude-haiku-5-5"), "monthly_limit")
        self.assertIsNone(gateway(mine=999_999).allow(USER, "lease_review", "claude-haiku-5-5"))

    def test_free_rules_feature_never_hits_the_dollar(self):
        self.assertIsNone(gateway(mine=5_000_000).allow(USER, "broker_fee", "rules"))

    def test_other_gates_still_apply(self):
        self.assertEqual(gateway(plus=False).allow(USER, "apply_help"), "plus_required")
        self.assertEqual(gateway(today=999).allow(USER, "apply_help"), "daily_limit")
        self.assertEqual(gateway(month=ai_gateway.CAP_MICROS).allow(USER, "apply_help"), "budget")
        self.assertEqual(gateway().allow(None, "apply_help"), "sign_in_required")

    def test_api_marks_broker_fee_free(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api_server.py")).read()
        self.assertIn('AI.allow(user, "broker_fee", "rules")', src)


if __name__ == "__main__":
    unittest.main()
