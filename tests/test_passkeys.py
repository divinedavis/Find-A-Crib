"""passkeys.py (2026-11-10): a stand-in authenticator makes real keys and
signs exactly what WebAuthn signs, so every check runs for real."""
import json
import secrets
import time
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import passkeys as pk

RP = pk.RP
SECRET = "test-secret"


class Store:
    """Stands in for the db/0076 functions."""

    def __init__(self):
        self.challenges, self.keys = {}, {}

    def challenge_new(self, h, purpose, user_id, ttl=pk.CHALLENGE_TTL, now=None):
        self.challenges[h] = {"purpose": purpose, "user_id": user_id, "expires": (now or time.time()) + ttl}

    def challenge_spend(self, h):
        return self.challenges.pop(h, None)

    def add(self, cred_id, user_id, public_key, alg, counter, transports, name, max_per_user):
        if cred_id in self.keys:
            return "exists"
        if sum(1 for k in self.keys.values() if k["user_id"] == user_id) >= max_per_user:
            return "limit"
        self.keys[cred_id] = {"id": cred_id, "user_id": user_id, "public_key": public_key, "alg": alg, "counter": counter,
                              "transports": transports, "name": name}
        return "ok"

    def get(self, cred_id):
        return self.keys.get(cred_id)

    def used(self, cred_id, counter):
        self.keys[cred_id]["counter"] = max(self.keys[cred_id]["counter"], counter)
        self.keys[cred_id]["last_used"] = True

    def list(self, user_id):
        return [k for k in self.keys.values() if k["user_id"] == user_id]

    def remove(self, cred_id, user_id):
        return 1 if self.keys.get(cred_id, {}).get("user_id") == user_id and self.keys.pop(cred_id) else 0


class Authenticator:
    def __init__(self, kind="ec"):
        self.kind = kind
        self.key = {"ec": lambda: ec.generate_private_key(ec.SECP256R1()), "ed25519": ed25519.Ed25519PrivateKey.generate,
                    "rsa": lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048)}[kind]()
        self.alg = {"ec": -7, "ed25519": -8, "rsa": -257}[kind]
        self.raw_id = secrets.token_bytes(32)
        self.id = pk.b64u(self.raw_id)

    def _data(self, rp_id=RP["id"], flags=0x05, attested=False, count=0, cred=None):
        head = pk.sha(rp_id) + bytes([flags | (0x40 if attested else 0)]) + count.to_bytes(4, "big")
        if not attested:
            return head
        cred = cred or self.raw_id
        return head + bytes(16) + len(cred).to_bytes(2, "big") + cred + b"\xa5"

    def _client(self, kind, challenge, origin=RP["origins"][0]):
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def create(self, challenge, **over):
        spki = self.key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        return {"id": pk.b64u(self.raw_id),  # `cred` swaps only the one inside authenticatorData
                "clientDataJSON": pk.b64u(self._client(over.get("type", "webauthn.create"), challenge, over.get("origin", RP["origins"][0]))),
                "authenticatorData": pk.b64u(self._data(over.get("rp_id", RP["id"]), over.get("flags", 0x05), over.get("attested", True), cred=over.get("cred"))),
                "publicKey": pk.b64u(spki), "publicKeyAlgorithm": over.get("alg", self.alg), "transports": ["internal", "<bad>"]}

    def get(self, challenge, **over):
        auth = self._data(over.get("rp_id", RP["id"]), over.get("flags", 0x05), count=over.get("count", 0))
        cdj = self._client(over.get("type", "webauthn.get"), challenge, over.get("origin", RP["origins"][0]))
        signed = auth + pk.sha(cdj)
        sig = (self.key.sign(signed, ec.ECDSA(hashes.SHA256())) if self.kind == "ec" else self.key.sign(signed) if self.kind == "ed25519"
               else self.key.sign(signed, padding.PKCS1v15(), hashes.SHA256()))
        if over.get("tamper"):
            sig = sig[:-1] + bytes([sig[-1] ^ 1])
        return {"id": self.id, "clientDataJSON": pk.b64u(cdj), "authenticatorData": pk.b64u(auth), "signature": pk.b64u(sig)}


ADA = {"id": "11111111-1111-1111-1111-111111111111", "email": "ada@example.test"}
BO = {"id": "22222222-2222-2222-2222-222222222222", "email": "bo@example.test"}


class Passkeys(unittest.TestCase):
    def add(self, store, key, user=ADA, **over):
        return pk.verify_registration(store, key.create(pk.registration_options(store, user, SECRET)["challenge"], **over), user)

    def test_each_kind_adds_then_signs_in_to_its_own_account(self):
        for kind in ("ec", "ed25519", "rsa"):
            store, key = Store(), Authenticator(kind)
            opts = pk.registration_options(store, ADA, SECRET)
            self.assertEqual(opts["rp"]["id"], "findacrib.com")
            self.assertEqual(opts["authenticatorSelection"]["userVerification"], "required")
            self.assertNotIn("ada", opts["user"]["id"].lower())
            self.assertEqual(pk.verify_registration(store, key.create(opts["challenge"]), ADA, name="Safari on Mac"), {"id": key.id}, kind)
            self.assertEqual(store.keys[key.id]["transports"], ["internal"])
            self.assertEqual(pk.verify_assertion(store, key.get(pk.login_options(store)["challenge"])), ADA["id"], kind)
            self.assertTrue(store.keys[key.id]["last_used"])

    def test_a_sign_in_fails_on_any_wrong_detail_and_a_challenge_works_once(self):
        store, key = Store(), Authenticator()
        self.add(store, key)
        for why, over in {"another origin": {"origin": "https://evil.example"}, "another domain": {"rp_id": "evil.example"},
                          "a registration": {"type": "webauthn.create"}, "no verification": {"flags": 0x01},
                          "nobody present": {"flags": 0x04}, "changed signature": {"tamper": True}}.items():
            self.assertIsNone(pk.verify_assertion(store, key.get(pk.login_options(store)["challenge"], **over)), why)
        self.assertIsNone(pk.verify_assertion(store, key.get(pk.b64u(secrets.token_bytes(32)))), "a challenge we never gave")
        ch = pk.login_options(store)["challenge"]
        self.assertEqual(pk.verify_assertion(store, key.get(ch)), ADA["id"])
        self.assertIsNone(pk.verify_assertion(store, key.get(ch)), "replayed")
        ch = pk.login_options(store)["challenge"]
        self.assertIsNone(pk.verify_assertion(store, key.get(ch), now=time.time() + pk.CHALLENGE_TTL + 5), "expired")
        self.assertIsNone(pk.verify_assertion(store, Authenticator().get(pk.login_options(store)["challenge"])), "a key we don't know")
        for junk in (None, {}, {"id": "x"}, {**key.get(pk.login_options(store)["challenge"]), "signature": "%%"}):
            self.assertIsNone(pk.verify_assertion(store, junk))

    def test_a_counter_that_goes_backwards_is_a_copied_key(self):
        store, key = Store(), Authenticator()
        self.add(store, key)
        self.assertTrue(pk.verify_assertion(store, key.get(pk.login_options(store)["challenge"], count=5)))
        self.assertIsNone(pk.verify_assertion(store, key.get(pk.login_options(store)["challenge"], count=5)))
        self.assertTrue(pk.verify_assertion(store, key.get(pk.login_options(store)["challenge"], count=6)))
        synced = Authenticator()
        self.add(store, synced)
        for _ in range(2):
            self.assertTrue(pk.verify_assertion(store, synced.get(pk.login_options(store)["challenge"], count=0)))

    def test_adding_is_checked_as_carefully_and_only_for_the_account_that_asked(self):
        store, key = Store(), Authenticator()
        self.assertEqual(pk.verify_registration(store, key.create(pk.registration_options(store, ADA, SECRET)["challenge"]), BO), {"error": "ceremony"})
        self.assertEqual(pk.verify_registration(store, key.create(pk.login_options(store)["challenge"]), ADA), {"error": "ceremony"})
        for error, overs in {"ceremony": [{"origin": "https://evil.example"}, {"rp_id": "evil.example"}, {"type": "webauthn.get"}, {"flags": 0x01}],
                             "no credential": [{"attested": False}], "credential mismatch": [{"cred": secrets.token_bytes(32)}],
                             "key": [{"alg": -257}], "incomplete": [{"alg": -999}]}.items():
            for over in overs:
                self.assertEqual(self.add(store, key, **over), {"error": error}, over)
        self.assertEqual(self.add(store, key), {"id": key.id})
        self.assertEqual(self.add(store, key), {"error": "exists"})
        self.assertEqual([c["id"] for c in pk.registration_options(store, ADA, SECRET)["excludeCredentials"]], [key.id])
        for _ in range(pk.MAX_PER_USER - 1):
            self.add(store, Authenticator())
        self.assertEqual(self.add(store, Authenticator()), {"error": "limit"})

    def test_device_names(self):
        self.assertEqual(pk.device_name("Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) Version/19.0 Mobile Safari/604.1"), "Safari on iPhone")
        self.assertEqual(pk.device_name("Mozilla/5.0 (Windows NT 10.0) Chrome/140 Safari/537.36 Edg/140"), "Edge on Windows")
        self.assertEqual(pk.device_name(""), "This device")


if __name__ == "__main__":
    unittest.main()
