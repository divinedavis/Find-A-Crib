#!/usr/bin/env python3
"""apple-subscription: a free Sandbox receipt (TestFlight / App Review) may
only grant Plus to allowlisted accounts (2026-10-07 audit L1). Pins the gate's
placement in index.ts and runs the Deno tests of sandbox.ts when deno is
installed (CI has no deno; the static checks still run there)."""
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FN = os.path.join(ROOT, "supabase", "functions", "apple-subscription")


class AppleSandboxGate(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(FN, "index.ts")) as f:
            self.src = f.read()

    def test_gate_runs_before_any_write(self):
        gate = self.src.find("mayGrant(env, user.id, SANDBOX_ALLOW)")
        self.assertGreater(gate, 0, "sandbox gate missing")
        self.assertLess(gate, self.src.find(".upsert("), "gate must precede the upsert")

    def test_allowlist_comes_from_a_secret(self):
        self.assertIn('Deno.env.get("APPLE_SANDBOX_USER_IDS")', self.src)

    def test_no_account_ids_in_public_source(self):
        uuid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        for name in ("index.ts", "sandbox.ts"):
            with open(os.path.join(FN, name)) as f:
                self.assertIsNone(uuid.search(f.read()), f"{name} hardcodes an account id")

    def test_production_needs_the_app_apple_id(self):
        # The 2026-09-20 bug: without it every real customer failed to verify.
        self.assertIn("APP_APPLE_ID = 6807549249", self.src)
        self.assertIn("BUNDLE_ID, APP_APPLE_ID)", self.src)

    @unittest.skipUnless(shutil.which("deno"), "deno not installed")
    def test_deno_unit_tests(self):
        r = subprocess.run(["deno", "test", "--quiet", os.path.join(FN, "sandbox_test.ts")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
