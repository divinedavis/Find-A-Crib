#!/usr/bin/env python3
"""Notifications in a browser (owner, 2026-11-10: Web Push).

A signed-in visitor who turns notifications on for a browser (the account
panel in index.html) gets the same alerts the iPhone app gets by APNs:
lottery and re-rental alerts (lottery_alerts.py) and Your Casa crime and 311
alerts (casa_alerts.py). Subscriptions live in public.web_push_subs
(db/0075), apart from device_tokens so the APNs code never sees one.

The message encryption (RFC 8291, aes128gcm) and the sender's token (VAPID,
RFC 8292) use the `cryptography` package every Python on the droplet has;
tests/test_webpush.py holds the encryption to RFC 8291's worked example.

Environment: WEB_PUSH_PUBLIC_KEY / WEB_PUSH_PRIVATE_KEY (base64url, the
P-256 pair; `python3 pipeline/webpush.py keys` makes one), WEB_PUSH_SUBJECT. The API
reads them from its .env, the alert jobs from /etc/findacrib/env/webpush.env.
Without them nothing is sent and the site offers no switch.

    python3 pipeline/webpush.py keys
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MAX_PAYLOAD = 3000
RECORD = 4096
# Only the browsers' own push services are ever posted to (Chrome/Edge,
# Firefox, Safari, Windows): the server sends to whatever address a
# subscription names, so anything else is refused.
PUSH_HOSTS = re.compile(r"^(fcm\.googleapis\.com|updates\.push\.services\.mozilla\.com|[a-z0-9-]+\.notify\.windows\.com|([a-z0-9-]+\.)?push\.apple\.com)$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{20,120}$")


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256 with one block of output, all 32 bytes or fewer need."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def _point(public: bytes) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)


def encrypt(plaintext: bytes | str, p256dh: str, auth: str, *, salt: bytes | None = None, sender_private: bytes | None = None) -> bytes:
    """A message only this browser can read: the aes128gcm body for its push
    service. The salt and sender key are random per message; tests pass the RFC's."""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    ua_public, secret = unb64u(p256dh), unb64u(auth)
    if len(ua_public) != 65 or ua_public[0] != 4 or len(secret) != 16:
        raise ValueError("bad subscription keys")
    if len(plaintext) > MAX_PAYLOAD:
        raise ValueError("message too long")
    ua = _point(ua_public)  # raises on a point that isn't on the curve
    sender = (ec.derive_private_key(int.from_bytes(sender_private, "big"), ec.SECP256R1()) if sender_private
              else ec.generate_private_key(ec.SECP256R1()))
    as_public = sender.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    ikm = _hkdf(secret, sender.exchange(ec.ECDH(), ua), b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    # 0x02 marks the last (here, only) record.
    sealed = AESGCM(key).encrypt(nonce, plaintext + b"\x02", None)
    return salt + RECORD.to_bytes(4, "big") + bytes([len(as_public)]) + as_public + sealed


def generate_keys() -> dict:
    key = ec.generate_private_key(ec.SECP256R1())
    return {"public": b64u(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
            "private": b64u(key.private_numbers().private_value.to_bytes(32, "big"))}


def vapid_header(endpoint: str, public: str, private: str, subject: str, now: float | None = None) -> str:
    """Who is sending: a 12-hour ES256 token for that push service, and our key."""
    key = ec.derive_private_key(int.from_bytes(unb64u(private), "big"), ec.SECP256R1())
    part = lambda o: b64u(json.dumps(o, separators=(",", ":")).encode())
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(endpoint))
    unsigned = part({"typ": "JWT", "alg": "ES256"}) + "." + part({"aud": origin, "exp": int((now or time.time()) + 12 * 3600), "sub": subject})
    r, s = decode_dss_signature(key.sign(unsigned.encode(), ec.ECDSA(hashes.SHA256())))
    return f"vapid t={unsigned}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={public}"


def push_endpoint(value) -> str | None:
    """The address if it is a browser push service's, else None."""
    if not isinstance(value, str) or len(value) > 1000:
        return None
    try:
        u = urllib.parse.urlsplit(value)
        port = u.port
    except ValueError:
        return None
    ok = u.scheme == "https" and port is None and not u.username and not u.password and PUSH_HOSTS.match(u.hostname or "")
    return value if ok else None


def valid_keys(p256dh, auth) -> bool:
    """Keys a message can actually be sealed for."""
    if not (isinstance(p256dh, str) and isinstance(auth, str) and KEY_RE.match(p256dh) and KEY_RE.match(auth)):
        return False
    try:
        encrypt(b"", p256dh, auth)
        return True
    except Exception:
        return False


def config(env=os.environ) -> dict | None:
    public, private = env.get("WEB_PUSH_PUBLIC_KEY", ""), env.get("WEB_PUSH_PRIVATE_KEY", "")
    try:
        if len(unb64u(public)) != 65 or len(unb64u(private)) != 32:
            return None
    except Exception:
        return None
    return {"public": public, "private": private, "subject": env.get("WEB_PUSH_SUBJECT") or "mailto:hello@findacrib.com"}


def send(sub: dict, note: dict, cfg: dict | None = None, opener=urllib.request.urlopen) -> dict:
    """One notification to one browser. status 201/200 = taken; 404/410 = the
    browser unsubscribed (`remove` says to forget it)."""
    cfg = cfg or config()
    endpoint = push_endpoint(sub.get("endpoint"))
    if not cfg or not endpoint:
        return {"ok": False, "status": 0, "remove": False}
    body = encrypt(json.dumps(note, separators=(",", ":")), sub["p256dh"], sub["auth"])
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "TTL": "86400", "Urgency": "normal", "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "Authorization": vapid_header(endpoint, cfg["public"], cfg["private"], cfg["subject"])})
    try:
        with opener(req, timeout=10) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = 0
    return {"ok": 200 <= status < 300, "status": status, "remove": status in (404, 410)}


def note(title: str, body: str, url: str | None, tag: str | None = None) -> dict:
    """What the service worker shows. The link is a page on this site, or the
    https page an alert is about (a lottery's official listing, as the email
    links it); anything else opens the map."""
    path = "/"
    if url:
        u = urllib.parse.urlsplit(str(url))
        if u.netloc in ("", "findacrib.com", "www.findacrib.com") and u.scheme in ("", "https") and (u.path or "/").startswith("/") and not str(url).startswith("//"):
            path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, u.fragment))
        elif u.scheme == "https" and u.hostname and not u.username and len(str(url)) <= 500:
            path = str(url)
    return {"title": str(title)[:120], "body": str(body)[:300], "url": path, "tag": (tag or "")[:80] or None}


def push_to_emails(rpc, key, emails, make_note, log=print, opener=urllib.request.urlopen) -> int:
    """Every browser behind these addresses gets make_note(email); browsers
    that unsubscribed are forgotten. Returns how many took it. Never raises:
    a push service being down must not stop an email alert run."""
    cfg = config()
    if not cfg or not emails:
        return 0
    try:
        subs = rpc("web_push_for_emails", {"p_emails": list(emails)}, key) or []
    except Exception as e:
        log(f"   web push lookup failed ({type(e).__name__})")
        return 0
    sent = 0
    for sub in subs:
        msg = make_note((sub.get("email") or "").lower())
        if not msg:
            continue
        r = send(sub, msg, cfg, opener)
        sent += r["ok"]
        if r["remove"]:
            try:
                rpc("web_push_remove", {"p_endpoint": sub["endpoint"]}, key)
            except Exception:
                pass
        elif not r["ok"]:
            log(f"   web push not delivered ({r['status']})")
    return sent


if __name__ == "__main__" and sys.argv[1:] == ["keys"]:
    k = generate_keys()
    print(f"WEB_PUSH_PUBLIC_KEY={k['public']}\nWEB_PUSH_PRIVATE_KEY={k['private']}\nWEB_PUSH_SUBJECT=mailto:hello@findacrib.com")
