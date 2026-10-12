#!/usr/bin/env python3
"""Alert settings for signed-in members (2026-10-12).

The journey suite and the owner's phone share the owner's home connection;
a per-IP 60/hour on /alerts/prefs let the suite lock the owner's own phone
out (429), and the Lotteries tab spun forever. The account limit is per
account now, and "Turn off alerts" in the app works only on the caller's
own verified email."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


def fn(src, name):
    body = src[src.index(f"def {name}():"):]
    return body[:body.index("\n@app.route")]


class AlertsPrefsLimits(unittest.TestCase):
    def setUp(self):
        self.api = read("api_server.py")

    def test_prefs_limit_is_per_account_after_sign_in(self):
        body = fn(self.api, "alerts_prefs")
        self.assertNotIn('rate_limited("alerts_prefs", 60', body, "a per-IP 60/hour locks out a whole household")
        acct = body.index('rate_limited("alerts_prefs:"')
        self.assertLess(body.index("_session_email()"), acct, "the account bucket needs the verified email")
        self.assertRegex(body, r'rate_limited\("alerts_prefs_ip", (\d{3,})')

    def test_turn_off_uses_only_the_session_email(self):
        body = fn(self.api, "alerts_unsubscribe_me")
        self.assertIn('rpc("lottery_alerts_unsubscribe_email", {"p_email": email})', body)
        self.assertNotRegex(body, r"request\.(args|form)|get_json\(\)\.get\(.email", "no email from the request")
        self.assertIn('methods=["POST"]', self.api[self.api.index('"/alerts/unsubscribe-me"') - 20:][:80])
        sql = read("supabase", "migrations", "20261012180000_alerts_unsubscribe_email.sql")
        self.assertIn("to service_role;", sql)
        self.assertIn("from public, anon, authenticated;", sql)


if __name__ == "__main__":
    unittest.main()
