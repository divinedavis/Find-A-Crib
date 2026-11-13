#!/usr/bin/env python3
"""Passkeys on findacrib.com (owner, 2026-11-10: "lets do passkeys").

A signed-in visitor adds a passkey in the account panel; afterwards "Sign in
with a passkey" opens the same account with Face ID, Touch ID, Windows Hello
or a phone, without a password.

The WebAuthn checks follow W3C WebAuthn Level 3 sections 7.1 and 7.2, with
the `cryptography` package. Attestation is "none": we don't ask which device
made the key, only that the same key signs later. The browser hands over the
new public key itself (AuthenticatorAttestationResponse.getPublicKey()), so
no CBOR is read.

Accounts are Supabase's. Once a passkey checks out, api_server.py asks
Supabase's admin API for a one-time sign-in token for that account
(generate_link, which sends nothing) and the page exchanges it for a normal
session (supabase.auth.verifyOtp). The token is used once and only after the
passkey has signed our challenge.

Storage (db/0076, service role only) is reached through `store`, an object
with the RPC calls below, so tests can stand in for Supabase.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.serialization import load_der_public_key

CHALLENGE_TTL = 300
MAX_PER_USER = 10
# ES256, EdDSA and RS256: what browsers and authenticators make.
ALGS = {-7: "ec", -8: "ed25519", -257: "rsa"}
FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40
B64U = re.compile(r"^[A-Za-z0-9_-]+$")
RP = {"id": "findacrib.com", "name": "Find A Crib", "origins": ("https://findacrib.com",)}


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def field(body, name, limit):
    """A base64url field of the browser's response as bytes, or None."""
    value = (body or {}).get(name) if isinstance(body, dict) else None
    if not isinstance(value, str) or not value or len(value) > limit or not B64U.match(value):
        return None
    try:
        return unb64u(value)
    except Exception:
        return None


def sha(data: bytes | str) -> bytes:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).digest()


def new_challenge(store, purpose: str, user_id: str | None = None) -> str:
    challenge = secrets.token_bytes(32)
    store.challenge_new(sha(challenge).hex(), purpose, user_id)
    return b64u(challenge)


def user_handle(user_id: str, secret: str) -> str:
    """The meaningless id the device keeps for the account (WebAuthn's user.id
    must not be an email or account id)."""
    return b64u(hmac.new(("fac-passkey-handle:" + secret).encode(), user_id.encode(), hashlib.sha256).digest()[:16])


def registration_options(store, user: dict, secret: str, rp=RP) -> dict:
    return {
        "challenge": new_challenge(store, "register", user["id"]),
        "rp": {"id": rp["id"], "name": rp["name"]},
        "user": {"id": user_handle(user["id"], secret), "name": user.get("email") or "Find A Crib account",
                 "displayName": user.get("email") or "Find A Crib account"},
        "pubKeyCredParams": [{"type": "public-key", "alg": a} for a in ALGS],
        "timeout": CHALLENGE_TTL * 1000,
        "attestation": "none",
        "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True, "userVerification": "required"},
        "excludeCredentials": [{"type": "public-key", "id": p["id"]} for p in store.list(user["id"])],
    }


def login_options(store, rp=RP) -> dict:
    """No account is named: the device offers the passkeys it holds for the site."""
    return {"challenge": new_challenge(store, "login"), "rpId": rp["id"], "timeout": CHALLENGE_TTL * 1000, "userVerification": "required"}


def _ceremony(store, client_data_json: bytes, auth_data: bytes, *, kind: str, purpose: str, user_id, rp, now: float):
    """The checks both ceremonies share: this ceremony, our challenge (once,
    in time, for this purpose and account), our origin and domain, and the
    person present and verified. Returns (flags, counter) or None."""
    try:
        client = json.loads(client_data_json.decode())
    except Exception:
        return None
    if not isinstance(client, dict) or client.get("type") != kind or client.get("crossOrigin") is True:
        return None
    challenge = client.get("challenge")
    if not isinstance(challenge, str) or not B64U.match(challenge) or client.get("origin") not in rp["origins"]:
        return None
    spent = store.challenge_spend(sha(unb64u(challenge)).hex())
    if not spent or spent.get("purpose") != purpose or float(spent.get("expires", 0)) < now:
        return None
    if purpose == "register" and spent.get("user_id") != user_id:
        return None
    if len(auth_data) < 37 or auth_data[:32] != sha(rp["id"]):
        return None
    flags = auth_data[32]
    if not (flags & FLAG_UP) or not (flags & FLAG_UV):
        return None
    return flags, int.from_bytes(auth_data[33:37], "big")


def verify_registration(store, body, user: dict, rp=RP, now: float | None = None, name: str | None = None) -> dict:
    """Checks a new passkey and keeps it. {"id": ...} or {"error": ...}."""
    now = now or time.time()
    cred_id, cdj, auth = field(body, "id", 1400), field(body, "clientDataJSON", 4000), field(body, "authenticatorData", 4000)
    spki, alg = field(body, "publicKey", 2000), (body or {}).get("publicKeyAlgorithm") if isinstance(body, dict) else None
    if not (cred_id and cdj and auth and spki) or alg not in ALGS:
        return {"error": "incomplete"}
    got = _ceremony(store, cdj, auth, kind="webauthn.create", purpose="register", user_id=user["id"], rp=rp, now=now)
    if not got:
        return {"error": "ceremony"}
    flags, counter = got
    if not (flags & FLAG_AT) or len(auth) < 55:
        return {"error": "no credential"}
    n = int.from_bytes(auth[53:55], "big")
    if auth[55:55 + n] != cred_id:
        return {"error": "credential mismatch"}
    try:
        key = load_der_public_key(spki)
    except Exception:
        return {"error": "key"}
    kind = ALGS[alg]
    if not ((kind == "ec" and isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1))
            or (kind == "ed25519" and isinstance(key, ed25519.Ed25519PublicKey))
            or (kind == "rsa" and isinstance(key, rsa.RSAPublicKey))):
        return {"error": "key"}
    transports = [t for t in ((body.get("transports") if isinstance(body.get("transports"), list) else []) or [])
                  if isinstance(t, str) and re.fullmatch(r"[a-z-]{2,16}", t)][:6]
    result = store.add(b64u(cred_id), user["id"], b64u(spki), alg, counter, transports, (name or "")[:60] or None, MAX_PER_USER)
    if result != "ok":
        return {"error": result}
    return {"id": b64u(cred_id)}


def verify_assertion(store, body, rp=RP, now: float | None = None) -> str | None:
    """Checks a sign-in. The account id it opens, or None."""
    now = now or time.time()
    cred_id = (body or {}).get("id") if isinstance(body, dict) else None
    if not isinstance(cred_id, str) or len(cred_id) > 1400 or not B64U.match(cred_id):
        return None
    cdj, auth, sig = field(body, "clientDataJSON", 4000), field(body, "authenticatorData", 4000), field(body, "signature", 1200)
    if not (cdj and auth and sig):
        return None
    row = store.get(cred_id)
    if not row:
        return None
    got = _ceremony(store, cdj, auth, kind="webauthn.get", purpose="login", user_id=None, rp=rp, now=now)
    if not got:
        return None
    _, counter = got
    signed = auth + sha(cdj)
    try:
        key = load_der_public_key(unb64u(row["public_key"]))
        if row["alg"] == -7:
            key.verify(sig, signed, ec.ECDSA(hashes.SHA256()))
        elif row["alg"] == -8:
            key.verify(sig, signed)
        else:
            key.verify(sig, signed, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, Exception):
        return None
    # A counter that went backwards means a copied key (WebAuthn 6.1.1); most
    # passkeys sync between devices and always report 0.
    if counter and int(row.get("counter") or 0) and counter <= int(row["counter"]):
        return None
    store.used(cred_id, counter)
    return row["user_id"]


def device_name(user_agent: str) -> str:
    """The kind of device a passkey was added from, for the account panel."""
    ua = user_agent or ""
    osn = next((n for p, n in ((r"iPhone", "iPhone"), (r"iPad", "iPad"), (r"Android", "Android"), (r"Mac OS X|Macintosh", "Mac"),
                               (r"Windows", "Windows"), (r"CrOS", "Chromebook"), (r"Linux", "Linux")) if re.search(p, ua)), "")
    br = next((n for p, n in ((r"Edg/", "Edge"), (r"Firefox/", "Firefox"), (r"Chrome/", "Chrome"), (r"Safari/", "Safari")) if re.search(p, ua)), "")
    return " on ".join(x for x in (br, osn) if x) or "This device"


class SupabaseStore:
    """The db/0076 functions, through the API's service-role rpc()."""

    def __init__(self, rpc):
        self.rpc = rpc

    def challenge_new(self, h, purpose, user_id):
        self.rpc("passkey_challenge_new", {"p_hash": h, "p_purpose": purpose, "p_user_id": user_id, "p_ttl": CHALLENGE_TTL})

    def challenge_spend(self, h):
        rows = self.rpc("passkey_challenge_spend", {"p_hash": h}) or []
        if not rows:
            return None
        r = rows[0]
        return {"purpose": r["purpose"], "user_id": r.get("user_id"), "expires": r["expires_epoch"]}

    def add(self, cred_id, user_id, public_key, alg, counter, transports, name, max_per_user):
        return self.rpc("passkey_add", {"p_id": cred_id, "p_user_id": user_id, "p_public_key": public_key, "p_alg": alg,
                                        "p_counter": counter, "p_transports": transports, "p_name": name, "p_max": max_per_user})

    def get(self, cred_id):
        rows = self.rpc("passkey_get", {"p_id": cred_id}) or []
        return rows[0] if rows else None

    def used(self, cred_id, counter):
        self.rpc("passkey_used", {"p_id": cred_id, "p_counter": counter})

    def list(self, user_id):
        return self.rpc("passkey_list", {"p_user_id": user_id}) or []

    def remove(self, cred_id, user_id):
        return self.rpc("passkey_remove", {"p_id": cred_id, "p_user_id": user_id}) or 0
