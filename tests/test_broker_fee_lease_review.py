#!/usr/bin/env python3
"""Unit tests for broker_fee.py (FARE Act / RPL 238-a / GOL 7-108 rules) and
lease_review.py's guardrails (quote + number grounding, input limits). No
network and no model call.

    python3 tests/test_broker_fee_lease_review.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import broker_fee as B  # noqa: E402

try:
    import lease_review as L  # noqa: E402  (imports anthropic via claude_features)
except ImportError:
    L = None


def levels(out):
    return {f["title"]: f["level"] for f in out["findings"]}


class BrokerFee(unittest.TestCase):
    def test_listing_agent_fee_is_illegal(self):
        out = B.check({"found": "listing_agent", "broker_fee": "3,000"})
        self.assertEqual(out["verdict"], "likely_illegal")
        self.assertIn("Admin Code § 20-699.21(b)", out["findings"][0]["law"])
        self.assertTrue(any("311" in s for s in out["next_steps"]))

    def test_own_broker_in_writing_is_ok(self):
        out = B.check({"found": "own_broker", "hired_in_writing": "yes", "broker_fee": 3000})
        self.assertEqual(out["verdict"], "looks_ok")

    def test_own_broker_without_agreement_is_a_warning(self):
        out = B.check({"found": "own_broker", "hired_in_writing": "no", "broker_fee": 3000})
        self.assertEqual(out["verdict"], "check")

    def test_required_broker_is_illegal_even_for_own_broker(self):
        out = B.check({"found": "own_broker", "hired_in_writing": "yes", "broker_fee": 3000, "required_broker": "yes"})
        self.assertEqual(out["verdict"], "likely_illegal")

    def test_application_fee_cap(self):
        self.assertEqual(B.check({"app_fee": "20"})["verdict"], "looks_ok")
        self.assertEqual(B.check({"app_fee": "$100"})["verdict"], "likely_illegal")

    def test_deposit_over_one_month(self):
        self.assertEqual(B.check({"rent": 2500, "deposit": 2500})["verdict"], "looks_ok")
        self.assertEqual(B.check({"rent": 2500, "deposit": 5000})["verdict"], "likely_illegal")

    def test_late_fee_is_lesser_of_50_or_5_percent(self):
        # 5% of $800 = $40 < $50, so $45 is over the cap.
        self.assertEqual(B.check({"rent": 800, "late_fee": 45})["verdict"], "likely_illegal")
        self.assertEqual(B.check({"rent": 3000, "late_fee": 50})["verdict"], "looks_ok")

    def test_undisclosed_fees(self):
        self.assertEqual(B.check({"fees_disclosed": "no"})["verdict"], "likely_illegal")

    def test_listing_text_signals(self):
        self.assertEqual(B.listing_signals("Gorgeous 1BR. Broker fee: one month")[0], "fee")
        self.assertEqual(B.listing_signals("NO FEE! Owner pays.")[0], "no_fee")
        self.assertEqual(B.listing_signals("Sunny studio near the park")[0], None)
        out = B.check({"found": "listing_agent", "listing_text": "1BR. 15% broker fee applies."})
        self.assertEqual(out["verdict"], "likely_illegal")

    def test_garbage_input(self):
        out = B.check({"found": "<script>", "rent": "abc", "deposit": "-5", "app_fee": None})
        self.assertEqual(out["verdict"], "nothing_to_check")


LEASE = ("RESIDENTIAL LEASE. Monthly rent: $2,450.00, due on the 1st. Term: 12 months starting 2026-11-01. "
         "Security deposit: $4,900.00. If rent is not received by the 2nd of the month, Tenant shall pay a late "
         "charge of $150. Landlord shall not be responsible for any repairs to the apartment, including heat. "
         + "Tenant agrees to keep the apartment clean. " * 12)


@unittest.skipIf(L is None, "anthropic SDK not installed in this python")
class LeaseGuards(unittest.TestCase):
    def review(self, flags, ask=None, summary=None):
        return L.grounded({"summary": summary or {"monthly_rent": "$2,450.00", "term": "12 months",
                                                  "start_date": "2026-11-01", "security_deposit": "$4,900.00"},
                           "flags": flags, "ask_before_signing": ask or []}, LEASE)

    def test_quote_must_be_in_the_lease(self):
        out = self.review([
            {"title": "Late fee too high", "quote": "Tenant shall pay a late charge of $150",
             "why": "Capped at $50 or 5% of rent.", "law": "rpl_238a_late", "severity": "high"},
            {"title": "Pets banned", "quote": "No pets of any kind are permitted",
             "why": "Invented clause.", "law": "none", "severity": "low"},
        ])
        self.assertEqual([f["title"] for f in out["flags"]], ["Late fee too high"])
        self.assertIn("238-a(2)", out["flags"][0]["law_text"])

    def test_quote_matching_ignores_whitespace_and_case(self):
        out = self.review([{"title": "Repairs waived", "quote": "landlord shall NOT be responsible\nfor any repairs",
                            "why": "Habitability can't be waived.", "law": "rpl_235b", "severity": "high"}])
        self.assertEqual(len(out["flags"]), 1)

    def test_invented_numbers_are_dropped(self):
        out = self.review([{"title": "Deposit", "quote": "Security deposit: $4,900.00",
                            "why": "That's $9,999 over the limit.", "law": "gol_7108", "severity": "high"}],
                          ask=["Will you take $4,900 back to $2,450?", "Is the rent $3,333?"],
                          summary={"monthly_rent": "$9,000", "term": "12 months", "start_date": None, "security_deposit": None})
        self.assertEqual(out["flags"], [])
        self.assertEqual(out["ask_before_signing"], ["Will you take $4,900 back to $2,450?"])
        self.assertIsNone(out["summary"]["monthly_rent"])

    def test_law_caps_may_be_named(self):
        out = self.review([{"title": "Late fee", "quote": "late charge of $150",
                            "why": "New York caps late fees at $50 or 5% of rent, after 5 days.",
                            "law": "rpl_238a_late", "severity": "high"}])
        self.assertEqual(len(out["flags"]), 1)

    def test_limits(self):
        with self.assertRaises(L.LeaseError) as e:
            L.clean("too short")
        self.assertEqual(e.exception.code, "empty")
        with self.assertRaises(L.LeaseError) as e:
            L.clean("x" * (L.MAX_CHARS + 1))
        self.assertEqual(e.exception.code, "too_long")
        with self.assertRaises(L.LeaseError) as e:
            L.pdf_text(b"not a pdf")
        self.assertEqual(e.exception.code, "bad_pdf")


if __name__ == "__main__":
    unittest.main()
