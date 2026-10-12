#!/usr/bin/env python3
"""Signing out unregisters the phone (owner, 2026-10-12: an 8 AM round-up
landed on a phone that had signed out), and /push/unregister removes only the
caller's own device row."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


class PushSignOut(unittest.TestCase):
    def test_sign_out_unregisters_before_dropping_the_session(self):
        src = read("ios", "FindACrib", "Services", "AuthService.swift")
        body = src[src.index("func signOut() async {"):]
        body = body[:body.index("\n    }\n")]
        self.assertIn("PushService.shared.unregister()", body)
        self.assertLess(body.index("unregister()"), body.index("auth.signOut()"),
                        "unregister needs the session, so it must run before signOut")

    def test_unregister_posts_to_the_api(self):
        src = read("ios", "FindACrib", "Services", "PushService.swift")
        self.assertIn('"https://findacrib.com/api/push/unregister"', src)

    def test_api_removes_only_the_callers_row(self):
        src = read("api_server.py")
        fn = src[src.index("def push_unregister():"):src.index("def _session_email")]
        self.assertIn('rpc("device_token_remove_own"', fn)
        self.assertIn('"p_user_id": u["id"]', fn)
        sql = read("supabase", "migrations", "20261012170000_device_token_remove_own.sql")
        self.assertRegex(sql, r"where token = p_token and user_id = p_user_id")
        self.assertIn("to service_role;", sql)


if __name__ == "__main__":
    unittest.main()
