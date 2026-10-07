#!/usr/bin/env python3
"""App Store Server Notifications V2 receiver (2026-10-07, audit L13).

Static checks run everywhere; the Deno suite (real Apple-signed TEST payload
against the pinned G3 root, forged chains, missing OIDs, stale/future
signedDate, renewal/expiry/refund/grace decisions) runs when deno is
installed — CI has no deno."""
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FN = os.path.join(ROOT, "supabase", "functions", "apple-notifications")


def read(*p):
    with open(os.path.join(*p)) as f:
        return f.read()


class AppleNotifications(unittest.TestCase):
    def setUp(self):
        self.src = read(FN, "index.ts")
        self.jws = read(FN, "appleJWS.ts")

    def test_public_endpoint_is_declared_without_jwt_gate(self):
        cfg = read(ROOT, "supabase", "config.toml")
        self.assertRegex(cfg, r"\[functions\.apple-notifications\]\s*\nverify_jwt = false")

    def test_every_jws_is_verified_before_use_and_replays_refused(self):
        self.assertIn("maxAgeMs: MAX_NOTIFICATION_AGE_MS", self.src)
        self.assertIn("verifyAppleJWS<TransactionInfo>(p.data.signedTransactionInfo)", self.src)
        self.assertIn("verifyAppleJWS<RenewalInfo>(p.data.signedRenewalInfo)", self.src)
        handler = self.src[self.src.find("Deno.serve"):]
        self.assertLess(handler.find("verifyAppleJWS<NotificationPayload>"), handler.find("await log("))
        self.assertLess(handler.find("verifyAppleJWS<NotificationPayload>"), handler.find("admin.from("))

    def test_verifier_pins_root_and_app_store_oids(self):
        self.assertIn('"1.2.840.113635.100.6.11.1"', self.jws)
        self.assertIn('"1.2.840.113635.100.6.2.1"', self.jws)
        self.assertIn("x5c.length !== 3", self.jws)

    def test_sandbox_needs_the_allowlist_and_stripe_is_never_overwritten(self):
        self.assertIn("mayGrant(env, userId, SANDBOX_ALLOW)", self.src)
        self.assertLess(self.src.find("mayGrant(env, userId"), self.src.find('.upsert({ user_id: userId'))
        self.assertIn('mine.provider === "stripe"', self.src)

    def test_no_account_ids_in_public_source(self):
        uuid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
        for name in ("index.ts", "decide.ts"):
            self.assertIsNone(uuid.search(read(FN, name)), name)

    @unittest.skipUnless(shutil.which("deno"), "deno not installed")
    def test_deno_suite(self):
        r = subprocess.run(["deno", "test", "--allow-net", "--allow-read", FN],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
