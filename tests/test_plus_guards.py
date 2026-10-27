#!/usr/bin/env python3
"""Static guards for this week's Plus plumbing (2026-10-12/13), the parts no
journey can reach: the App Store purchase carries the account id, agent
phones are Plus in the database itself, and every AI surface on the site
names the monthly cap instead of a generic error."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


class PlusGuards(unittest.TestCase):
    def test_purchase_carries_the_account_token(self):
        # Without it apple_subs_check.py cannot link a purchase to an account
        # (three subscribers were stranded that way until 2026-10-12).
        src = read("ios", "FindACrib", "Services", "PlusStore.swift")
        self.assertIn("options.insert(.appAccountToken(uid))", src)
        self.assertRegex(src, r"product\.purchase\(options:\s*options\)")

    def test_agent_phone_is_plus_in_the_database(self):
        sql = read("supabase", "migrations", "20261012200000_agent_phone_plus_only.sql")
        fn = sql[sql.index("function public.get_agent_phone"):]
        self.assertIn("public.has_plus(auth.uid())", fn)
        self.assertRegex(fn, r"else\s+null")

    def test_site_names_the_monthly_cap(self):
        html = read("index.html")
        msgs = re.findall(r"monthly_limit'?\s*[?:]\s*'([^']+)'", html)
        self.assertGreaterEqual(len(msgs), 2, f"search and the tools each handle monthly_limit: {msgs}")
        for m in msgs:
            self.assertIn("this month", m)


class AscDownloadsSummary(unittest.TestCase):
    """summarise() matches App Store Connect's own figures: downloads are
    first-time only, and conversion is over UNIQUE impressions."""

    @classmethod
    def setUpClass(cls):
        src = read("ios", "scripts", "asc_downloads.py")
        body = src[src.index("def summarise("):src.index("\ndef released_versions(")]
        from collections import defaultdict
        from datetime import datetime, timedelta
        ns = {"defaultdict": defaultdict, "datetime": datetime, "timedelta": timedelta, "DAYS": 60}
        exec(body, ns)
        cls.summarise = staticmethod(ns["summarise"])

    def test_first_time_downloads_and_unique_conversion(self):
        daily = {"2026-10-10": {"downloads_first": 4, "redownloads": 1, "page_views": 2,
                                "impressions": 300, "impressions_unique": 100},
                 "2026-10-01": {"downloads_first": 50, "impressions_unique": 1}}   # outside d7
        d7 = self.summarise(daily, "2026-10-10")["d7"]
        self.assertEqual(d7["downloads"], 4, "redownloads are not App Units")
        self.assertEqual(d7["conv_impression"], 5.0, "(4 + 1) / 100 unique impressions")
        self.assertEqual(d7["conv_page_view"], 200.0, "can pass 100%: most downloads skip the page")

    def test_no_data_is_empty_not_a_crash(self):
        self.assertEqual(self.summarise({}, None), {"d7": {}, "d28": {}, "all": {}})


if __name__ == "__main__":
    unittest.main()
