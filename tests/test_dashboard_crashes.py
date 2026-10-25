#!/usr/bin/env python3
"""The owner dashboard's Crashes page (2026-10-25): the route is behind the
dashboard read key, the window is allowlisted, the per-day SQL is
service-role only, and the page counts crashes by the nightly email's own
rules (error_report.crashes), so the two never disagree."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import error_report  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


def trace(visitor, steps, at="2026-10-25T04:10:38+00:00", booted="2026-10-25T04:09:49+00:00", dev="iphone"):
    return {"event": "crash_trace", "visitor_id": visitor, "created_at": at,
            "props": {"dev": dev, "platform": "web", "booted": booted, "steps": [[i, s] for i, s in enumerate(steps)]}}


class DashboardCrashes(unittest.TestCase):
    def test_route_is_keyed_and_allowlisted(self):
        src = read("api_server.py")
        self.assertIn('"/dashboard-crashes"', src[src.index("DASHBOARD_READ_PATHS ="):src.index("EMAIL_RE =")])
        fn = src[src.index("def dashboard_crashes():"):]
        fn = fn[:fn.index("\n\n\n")]
        self.assertIn('_dashboard_denial(_dashboard_auth(), ("ok",))', fn)
        self.assertIn("CRASH_WINDOWS.get(", fn)
        self.assertIn('error_report.crashes(rows, SERVICE_KEY, found=found)', src)
        self.assertIn("error_report.py", read("scripts", "deploy_api.sh"), "the API imports it, so it must ship with it")

    def test_function_is_service_role_only(self):
        sql = read("db", "0069_dashboard_crash_days.sql")
        self.assertIn("revoke execute on function public.dashboard_crash_days(timestamptz) from public, anon, authenticated;", sql)
        self.assertIn("grant execute on function public.dashboard_crash_days(timestamptz) to service_role;", sql)

    def test_found_lists_the_same_crashes_the_email_counts(self):
        rows = [
            trace("a", ["boot", "vis visible", "tick", "vv-resize 775 la0 ad15 img36 v2", "win-resize 430x775"]),
            trace("b", ["boot", "vis visible", "tick", "vis hidden", "tick"]),                 # reclaimed in the background
            trace("c", ["boot", "vis visible", "tick", "grid:done", "pagehide"]),            # said goodbye
        ]
        found = []
        out = error_report.crashes(rows, None, kept_going=lambda *a: None, found=found)
        self.assertEqual([last for _, last in found], ["win-resize 430x775"])
        self.assertEqual(sum(e["n"] for e in out.values()), len(found), "the list and the counts agree")


if __name__ == "__main__":
    unittest.main()
