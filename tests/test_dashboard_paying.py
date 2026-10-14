#!/usr/bin/env python3
"""Paying customers by range (owner, 2026-10-12): the API sends
dashboard_paying(since) as paying_range, and the function stays service-role
only (it reads every subscription)."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DashboardPaying(unittest.TestCase):
    def test_api_sends_paying_range(self):
        with open(os.path.join(ROOT, "api_server.py")) as f:
            src = f.read()
        self.assertIn('"paying_range": (_fac_paying, since)', src)
        self.assertIn('rpc("dashboard_paying"', src)

    def test_function_is_service_role_only(self):
        with open(os.path.join(ROOT, "supabase", "migrations", "20261012160000_subscription_started_at.sql")) as f:
            sql = f.read()
        self.assertIn("revoke all on function public.dashboard_paying(timestamptz) from public, anon, authenticated;", sql)
        self.assertIn("grant execute on function public.dashboard_paying(timestamptz) to service_role;", sql)
        self.assertIn("before insert or update on public.subscriptions", sql)

    def test_plus_customers_by_range(self):
        with open(os.path.join(ROOT, "supabase", "migrations", "20261013210000_dashboard_plus_customers.sql")) as f:
            sql = f.read()
        for key in ("'plus'", "'plus_new'", "'plus_web'", "'plus_app'", "'paying'"):
            self.assertIn(key, sql)
        self.assertIn("revoke all on function public.dashboard_paying(timestamptz) from public, anon, authenticated;", sql)
        self.assertIn("grant execute on function public.dashboard_paying(timestamptz) to service_role;", sql)


if __name__ == "__main__":
    unittest.main()
