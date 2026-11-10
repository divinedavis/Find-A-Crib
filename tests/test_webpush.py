"""webpush.py: browser notifications (2026-11-10). The encryption is held to
RFC 8291's own worked example, byte for byte."""
import json
import unittest
import urllib.error

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import webpush as wp

RFC = {  # RFC 8291 section 5 / appendix A: published example values, not keys
    "plaintext": b"When I grow up, I want to be a watermelon",
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",  # gitleaks:allow
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",  # gitleaks:allow
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",  # gitleaks:allow
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "message": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def browser():
    k = ec.generate_private_key(ec.SECP256R1())
    return k, wp.b64u(k.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)), wp.b64u(b"\x03" * 16)


def open_message(sealed: bytes, private: ec.EllipticCurvePrivateKey, ua_public: str, auth: str) -> bytes:
    """The browser's half, written apart from the sender's."""
    salt, as_public, body = sealed[:16], sealed[21:21 + sealed[20]], sealed[21 + sealed[20]:]
    shared = private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = wp._hkdf(wp.unb64u(auth), shared, b"WebPush: info\x00" + wp.unb64u(ua_public) + as_public, 32)
    plain = AESGCM(wp._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(wp._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12), body, None)
    assert plain[-1] == 2
    return plain[:-1]


class Encryption(unittest.TestCase):
    def test_rfc_8291_example_byte_for_byte(self):
        sealed = wp.encrypt(RFC["plaintext"], RFC["ua_public"], RFC["auth"], salt=wp.unb64u(RFC["salt"]), sender_private=wp.unb64u(RFC["as_private"]))
        self.assertEqual(wp.b64u(sealed), RFC["message"])
        ua = ec.derive_private_key(int.from_bytes(wp.unb64u(RFC["ua_private"]), "big"), ec.SECP256R1())
        self.assertEqual(open_message(sealed, ua, RFC["ua_public"], RFC["auth"]), RFC["plaintext"])

    def test_fresh_messages_open_only_for_their_browser(self):
        key, pub, auth = browser()
        note = json.dumps({"title": "New lottery", "body": "Crème — 3 units ☕"}).encode()
        a, b = wp.encrypt(note, pub, auth), wp.encrypt(note, pub, auth)
        self.assertEqual(open_message(a, key, pub, auth), note)
        self.assertNotEqual(a, b)
        with self.assertRaises(Exception):
            open_message(a, key, pub, wp.b64u(b"\x04" * 16))
        with self.assertRaises(ValueError):
            wp.encrypt(b"x" * (wp.MAX_PAYLOAD + 1), pub, auth)
        for bad in ((pub[:20], auth), (pub, "AAAA"), ("A" * 87, auth)):
            self.assertFalse(wp.valid_keys(*bad), bad)
        self.assertTrue(wp.valid_keys(pub, auth))


class Sender(unittest.TestCase):
    def test_vapid_token_verifies_with_our_public_key(self):
        k = wp.generate_keys()
        header = wp.vapid_header("https://fcm.googleapis.com/fcm/send/x", k["public"], k["private"], "mailto:hello@findacrib.com", now=1_800_000_000)
        token, key = header[len("vapid t="):].split(", k=")
        self.assertEqual(key, k["public"])
        h, p, s = token.split(".")
        self.assertEqual(json.loads(wp.unb64u(p)), {"aud": "https://fcm.googleapis.com", "exp": 1_800_000_000 + 43200, "sub": "mailto:hello@findacrib.com"})
        sig = wp.unb64u(s)
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), wp.unb64u(k["public"]))
        pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")), f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256()))

    def test_only_browser_push_services(self):
        for ok in ("https://fcm.googleapis.com/fcm/send/x", "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/Q", "https://wns2-by3p.notify.windows.com/w/?token=x"):
            self.assertEqual(wp.push_endpoint(ok), ok)
        for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://findacrib.com/api/x", "https://fcm.googleapis.com.evil.example/x",
                    "https://fcm.googleapis.com:8443/x", "https://u:p@fcm.googleapis.com/x", "file:///etc/passwd", "", None, 5, "https://" + "a" * 1200, "https://[::1"):
            self.assertIsNone(wp.push_endpoint(bad), bad)

    def test_a_note_links_to_this_site_or_the_https_page_it_is_about(self):
        self.assertEqual(wp.note("t", "b", "https://findacrib.com/casa/?bbl=1&src=x#crime-list")["url"], "/casa/?bbl=1&src=x#crime-list")
        self.assertEqual(wp.note("t", "b", "/alerts/")["url"], "/alerts/")
        listing = "https://housingconnect.nyc.gov/PublicWeb/details/1234"
        self.assertEqual(wp.note("t", "b", listing)["url"], listing)
        for other in ("http://example.org/x", "//evil.example", "javascript:alert(1)", "data:text/html,x", "https://u:p@example.org/", "https://example.org/" + "a" * 600, None):
            self.assertEqual(wp.note("t", "b", other)["url"], "/", other)


class Delivery(unittest.TestCase):
    def setUp(self):
        k = wp.generate_keys()
        self._env = {"WEB_PUSH_PUBLIC_KEY": k["public"], "WEB_PUSH_PRIVATE_KEY": k["private"]}
        import os
        self.saved = {x: os.environ.get(x) for x in self._env}
        os.environ.update(self._env)

    def tearDown(self):
        import os
        for x, v in self.saved.items():
            if v is None:
                os.environ.pop(x, None)
            else:
                os.environ[x] = v

    def test_every_browser_behind_the_addresses_and_gone_ones_are_forgotten(self):
        _, pub, auth = browser()
        subs = [{"email": "a@example.test", "endpoint": "https://fcm.googleapis.com/fcm/send/live", "p256dh": pub, "auth": auth},
                {"email": "a@example.test", "endpoint": "https://fcm.googleapis.com/fcm/send/gone", "p256dh": pub, "auth": auth},
                {"email": "b@example.test", "endpoint": "https://web.push.apple.com/b", "p256dh": pub, "auth": auth}]
        calls, posted = [], []

        def rpc(fn, args, key):
            calls.append((fn, args))
            return subs if fn == "web_push_for_emails" else None

        class Resp:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout):
            posted.append((req.full_url, req.headers.get("Content-encoding"), req.headers.get("Authorization", "")[:8]))
            if req.full_url.endswith("gone"):
                raise urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)
            return Resp()

        sent = wp.push_to_emails(rpc, "k", ["a@example.test", "b@example.test"],
                                 lambda email: None if email == "b@example.test" else wp.note("New", "x", "/alerts/"), log=lambda *a: None, opener=opener)
        self.assertEqual(sent, 1)
        self.assertEqual(posted, [("https://fcm.googleapis.com/fcm/send/live", "aes128gcm", "vapid t="), ("https://fcm.googleapis.com/fcm/send/gone", "aes128gcm", "vapid t=")])
        self.assertIn(("web_push_remove", {"p_endpoint": "https://fcm.googleapis.com/fcm/send/gone"}), calls)

    def test_nothing_without_keys_and_a_failed_lookup_never_raises(self):
        import os
        os.environ.pop("WEB_PUSH_PUBLIC_KEY")
        self.assertEqual(wp.push_to_emails(lambda *a: [], "k", ["a@example.test"], lambda e: {}), 0)
        os.environ.update(self._env)

        def broken(*a):
            raise RuntimeError("supabase down")
        self.assertEqual(wp.push_to_emails(broken, "k", ["a@example.test"], lambda e: {}, log=lambda *a: None), 0)


if __name__ == "__main__":
    unittest.main()
