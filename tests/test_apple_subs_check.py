#!/usr/bin/env python3
"""apple_subs_check.py (2026-10-12): Apple's status wins over our row, a
token-carrying subscription is linked to its account, and a paying one with no
account is reported, never guessed at."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import apple_subs_check as c  # noqa: E402

DAY = 86_400_000
NOW = 1_791_800_000_000
UID = "34c58884-043a-441e-8ffb-4a5fc5aa626e"


class FakeApple:
    def __init__(self, by_otid):
        self.by_otid = by_otid

    def status(self, otid):
        return self.by_otid.get(otid, (None, None))


class FakeDB:
    def __init__(self, rows, notes, users=()):
        self.rows, self.notes, self.users = rows, notes, set(users)
        self.patches, self.inserts = [], []

    def get(self, path):
        return self.rows if path.startswith("subscriptions") else self.notes

    def patch(self, path, body):
        self.patches.append((path, body))

    def insert(self, table, body):
        self.inserts.append(body)

    def user_exists(self, uid):
        return uid in self.users


def tx(**kw):
    base = {"productId": c.PRODUCT_ID, "expiresDate": NOW + 30 * DAY, "originalPurchaseDate": NOW - DAY, "price": 4990}
    base.update(kw)
    return base


class Desired(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(c.desired(c.ACTIVE, tx())[0], "active")
        self.assertEqual(c.desired(c.ACTIVE, tx(offerDiscountType="FREE_TRIAL", price=0))[0], "trialing")
        self.assertEqual(c.desired(c.GRACE, tx())[0], "active")
        self.assertEqual(c.desired(c.BILLING_RETRY, tx())[0], "inactive")
        self.assertEqual(c.desired(c.EXPIRED, tx())[0], "inactive")
        self.assertEqual(c.desired(c.REVOKED, tx())[0], "canceled")
        self.assertEqual(c.desired(c.ACTIVE, tx(revocationDate=NOW))[0], "canceled")


class Check(unittest.TestCase):
    def test_row_follows_apple(self):
        row = {"user_id": UID, "status": "trialing", "current_period_end": c.iso(NOW),
               "apple_original_transaction_id": "1"}
        db = FakeDB([row], [])
        fixed, linked, unlinked, errors = c.check(db, FakeApple({"1": (c.ACTIVE, tx())}), dry=False)
        self.assertEqual(len(fixed), 1)
        self.assertEqual(db.patches[0][1]["status"], "active")

    def test_matching_row_is_left_alone(self):
        t = tx()
        row = {"user_id": UID, "status": "active", "current_period_end": c.iso(t["expiresDate"]),
               "apple_original_transaction_id": "1"}
        db = FakeDB([row], [{"original_transaction_id": "1"}])
        self.assertEqual(c.check(db, FakeApple({"1": (c.ACTIVE, t)}), dry=False), ([], [], [], []))
        self.assertEqual(db.patches, [])

    def test_token_links_a_real_account(self):
        db = FakeDB([], [{"original_transaction_id": "2"}], users=[UID])
        fixed, linked, unlinked, errors = c.check(db, FakeApple({"2": (c.ACTIVE, tx(appAccountToken=UID.upper()))}), dry=False)
        self.assertEqual(len(linked), 1)
        self.assertEqual(db.inserts[0]["user_id"], UID)
        self.assertEqual(db.inserts[0]["status"], "active")

    def test_unknown_token_is_reported_not_linked(self):
        db = FakeDB([], [{"original_transaction_id": "3"}], users=[])
        fixed, linked, unlinked, errors = c.check(db, FakeApple({"3": (c.ACTIVE, tx(appAccountToken=UID))}), dry=False)
        self.assertEqual((len(linked), len(unlinked)), (0, 1))
        self.assertEqual(db.inserts, [])

    def test_expired_unlinked_is_quiet(self):
        db = FakeDB([], [{"original_transaction_id": "4"}])
        self.assertEqual(c.check(db, FakeApple({"4": (c.EXPIRED, tx())}), dry=False), ([], [], [], []))

    def test_dry_run_writes_nothing(self):
        row = {"user_id": UID, "status": "inactive", "current_period_end": None, "apple_original_transaction_id": "1"}
        db = FakeDB([row], [{"original_transaction_id": "2"}], users=[UID])
        apple = FakeApple({"1": (c.ACTIVE, tx()), "2": (c.ACTIVE, tx(appAccountToken=UID))})
        fixed, linked, _, _ = c.check(db, apple, dry=True)
        self.assertEqual((len(fixed), len(linked)), (1, 1))
        self.assertEqual((db.patches, db.inserts), ([], []))


if __name__ == "__main__":
    unittest.main()
