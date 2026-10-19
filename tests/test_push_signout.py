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


class PushSignedOutAnyRoad(unittest.TestCase):
    """Owner, 2026-10-19: "if im not logged into fac on the iphone, i shouldnt
    get rerental/lottery alerts" — not only after tapping Sign out."""

    def setUp(self):
        self.push = read("ios", "FindACrib", "Services", "PushService.swift")

    def test_a_signed_out_phone_forgets_its_token(self):
        upload = self.push[self.push.index("private func upload("):]
        self.assertIn("await forget(token)", upload[:upload.index("\n    }\n")],
                      "a token that arrives while signed out is dropped from every account")
        unreg = self.push[self.push.index("func unregister() async {"):]
        unreg = unreg[:unreg.index("\n    }\n")]
        self.assertIn("guard let session = auth?.session else { await forget(token); return }", unreg)
        self.assertIn('"https://findacrib.com/api/push/forget"', self.push)

    def test_a_session_that_ends_by_itself_forgets_too(self):
        auth = read("ios", "FindACrib", "Services", "AuthService.swift")
        case = auth[auth.index("case .signedOut, .userDeleted:"):]
        self.assertIn("PushService.shared.sessionEnded()", case[:case.index("default:")])

    def test_open_app_hides_a_late_alert_when_signed_out(self):
        will = self.push[self.push.index("willPresent notification"):]
        self.assertIn("completionHandler(signedIn ? [.banner, .list, .sound] : [])", will[:600])

    def test_forget_needs_no_session_and_only_takes_a_token(self):
        src = read("api_server.py")
        fn = src[src.index("def push_forget():"):src.index("# ---- Your Crib")]
        self.assertNotIn("_session_user()", fn)
        self.assertIn("PUSH_TOKEN_RE.match(token)", fn)
        self.assertIn('rate_limited("push_forget"', fn)
        self.assertIn('rpc("device_token_remove", {"p_token": token})', fn)


if __name__ == "__main__":
    unittest.main()
