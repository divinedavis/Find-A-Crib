#!/usr/bin/env python3
"""The owner dashboard's investor card picks 14/30/60/90 days or all time
(owner, 2026-10-19; 14 days added 10-20). The window is allowlisted before it reaches the SECURITY
DEFINER function, the route is behind the dashboard read key, and the
function stays service-role only."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


class DashboardInvestor(unittest.TestCase):
    def test_route_is_keyed_and_allowlisted(self):
        src = read("api/api_server.py")
        self.assertIn('"/dashboard-investor"', src[src.index("DASHBOARD_READ_PATHS ="):src.index("EMAIL_RE =")])
        self.assertIn('DASHBOARD_INVESTOR_DAYS = {"14": 14, "30": 30, "60": 60, "90": 90, "all": None}', src)
        fn = src[src.index("def dashboard_investor():"):]
        fn = fn[:fn.index("\n\n\n")]
        self.assertIn('_dashboard_denial(_dashboard_auth(), ("ok",))', fn)
        self.assertIn("DASHBOARD_INVESTOR_DAYS.get(", fn)
        self.assertIn('rpc("dashboard_investor"', src)

    def test_function_is_service_role_only(self):
        sql = read("db", "0065_dashboard_investor_window.sql")
        self.assertIn("revoke all on function public.dashboard_investor(int, text[]) from public, anon, authenticated;", sql)
        self.assertIn("grant execute on function public.dashboard_investor(int, text[]) to service_role;", sql)
        # greatest() skips nulls, so all time must be handled before it
        # (the first cut read all time as a one-day window).
        self.assertIn("case when p_days is null then 36500", sql)


    def test_trends_ride_along_and_are_service_role_only(self):
        # Day-by-day lines per tile (owner, 2026-11-11, design D). Same
        # allowlisted window, same key; a failed trends query must not take
        # the numbers down with it.
        src = read("api/api_server.py")
        self.assertIn('rpc("dashboard_investor_trends"', src)
        fn = src[src.index("def _fac_investor_trends_rpc("):]
        fn = fn[:fn.index("\n\n\n")]
        self.assertIn("return None", fn)
        route = src[src.index("def dashboard_investor():"):]
        route = route[:route.index("\n\n\n")]
        self.assertIn('data["trends"] = trends.result()', route)
        sql = read("db", "0077_dashboard_investor_trends.sql")
        self.assertIn("revoke all on function public.dashboard_investor_trends(int, text[]) from public, anon, authenticated;", sql)
        self.assertIn("grant execute on function public.dashboard_investor_trends(int, text[]) to service_role;", sql)
        # Bounded however it's called: no runaway generate_series.
        self.assertIn("least(greatest(p_days, 1), 366)", sql)
        self.assertIn("3660)", sql)

if __name__ == "__main__":
    unittest.main()
