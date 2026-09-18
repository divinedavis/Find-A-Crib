#!/usr/bin/env python3
"""Push a borough alert to the iPhone app over APNs.

Used by lottery_alerts.py beside the email: when a subscriber has the app and
has allowed notifications, the same alert lands on the phone the minute it
opens. Standard library only — the dispatcher runs on the droplet's system
python3, which has neither PyJWT nor cryptography — so the provider token is
signed with the openssl binary and the request goes through curl, which
speaks the HTTP/2 APNs requires.

Environment (growth.env on the droplet; never in the repo):
  APNS_KEY_PATH   the team-scoped .p8 (key GNUQ5SMWH6, team CG89RY4W6R — ONE
                  key for every app on the team; Apple issues it once)
  APNS_KEY_ID, APNS_TEAM_ID
  APNS_TOPIC      the bundle id, com.divinedavis.findacrib

The three traps this is built around (memory: apns setup):
  * openssl signs ES256 as DER; Apple wants the raw r||s pair. der_to_jose()
    does that conversion. Get it wrong and APNs answers 403 InvalidProviderToken.
  * The device's "environment" is a CLAIM. A TestFlight build is production,
    a Debug build is sandbox, and a device that misreads its own profile
    registers wrong. On 400 BadDeviceToken we try the other host and, if that
    works, tell the caller to refile the row. Only 410 Unregistered deletes.
  * The provider token is minted at most every 20 minutes and reused for up
    to 50 (Apple rejects faster refreshes); it is cached in a file next to the
    dispatcher state.

    python3 apns.py --probe            # credentials check with a fake token
    python3 apns.py --to <hex> --env production --title "x" --body "y"
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE = os.path.join(HERE, ".apns_token.json")
HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def der_to_jose(der: bytes) -> bytes:
    """ECDSA DER SEQUENCE{INTEGER r, INTEGER s} -> 64 raw bytes r||s."""
    assert der[0] == 0x30, "not a DER sequence"
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    out = b""
    for _ in range(2):
        assert der[i] == 0x02, "expected DER integer"
        n = der[i + 1]
        v = der[i + 2:i + 2 + n]
        out += v.lstrip(b"\x00").rjust(32, b"\x00")
        i += 2 + n
    return out


def provider_token(key_path: str, key_id: str, team_id: str, now: float | None = None) -> str:
    """A signed ES256 JWT, cached for 30 minutes (Apple: refresh no more than
    every 20, no less than every 60)."""
    now = now or time.time()
    try:
        with open(TOKEN_CACHE) as f:
            c = json.load(f)
        if c.get("kid") == key_id and now - c.get("iat", 0) < 30 * 60:
            return c["token"]
    except Exception:
        pass
    header = _b64url(json.dumps({"alg": "ES256", "kid": key_id}).encode())
    claims = _b64url(json.dumps({"iss": team_id, "iat": int(now)}).encode())
    signing = f"{header}.{claims}".encode()
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(signing)
        path = tf.name
    try:
        der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path, path],
                             check=True, capture_output=True).stdout
    finally:
        os.unlink(path)
    token = f"{header}.{claims}.{_b64url(der_to_jose(der))}"
    try:
        with open(TOKEN_CACHE, "w") as f:
            json.dump({"kid": key_id, "iat": int(now), "token": token}, f)
        os.chmod(TOKEN_CACHE, 0o600)
    except Exception:
        pass
    return token


def config() -> dict | None:
    c = {k: os.environ.get(k) for k in ("APNS_KEY_PATH", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_TOPIC")}
    if not all(c.values()) or not os.path.exists(c["APNS_KEY_PATH"]):
        return None
    return c


def _post(host: str, token: str, cfg: dict, payload: dict, collapse: str | None = None) -> tuple[int, str]:
    cmd = ["curl", "-s", "--http2", "-o", "-", "-w", "\n%{http_code}", "-X", "POST",
           "-H", f"authorization: bearer {provider_token(cfg['APNS_KEY_PATH'], cfg['APNS_KEY_ID'], cfg['APNS_TEAM_ID'])}",
           "-H", f"apns-topic: {cfg['APNS_TOPIC']}", "-H", "apns-push-type: alert",
           "-H", "apns-priority: 10", "-H", "apns-expiration: " + str(int(time.time()) + 6 * 3600),
           "-H", "content-type: application/json"]
    if collapse:
        cmd += ["-H", f"apns-collapse-id: {collapse[:64]}"]
    cmd += ["--data", json.dumps(payload), f"{host}/3/device/{token}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    body, _, code = (r.stdout or "").rpartition("\n")
    try:
        reason = json.loads(body).get("reason", "") if body.strip() else ""
    except Exception:
        reason = body.strip()[:80]
    return int(code or 0), reason


def send(token: str, env: str, title: str, body: str, url: str | None = None, *,
         collapse: str | None = None, cfg: dict | None = None) -> dict:
    """Deliver one alert. Returns {ok, status, reason, env, refile, remove}:
    `refile` names the environment that actually worked when the stored one
    did not; `remove` is True only on 410 Unregistered."""
    cfg = cfg or config()
    if not cfg:
        return {"ok": False, "status": 0, "reason": "apns_not_configured", "env": env, "refile": None, "remove": False}
    payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
    if url:
        payload["url"] = url
    env = env if env in HOSTS else "production"
    code, reason = _post(HOSTS[env], token, cfg, payload, collapse)
    refile = None
    if code == 400 and reason == "BadDeviceToken":
        other = "sandbox" if env == "production" else "production"
        code2, reason2 = _post(HOSTS[other], token, cfg, payload, collapse)
        if code2 == 200:
            code, reason, refile, env = code2, reason2, other, other
    return {"ok": code == 200, "status": code, "reason": reason, "env": env,
            "refile": refile, "remove": code == 410}


def probe(cfg: dict) -> int:
    """Credentials check without a device: a fake but well-formed token must
    come back 400 BadDeviceToken from BOTH hosts. 403 means the key, key id,
    team id or the DER->JOSE conversion is wrong."""
    fake = "ab" * 32
    ok = True
    for env, host in HOSTS.items():
        code, reason = _post(host, fake, cfg, {"aps": {"alert": "probe"}})
        good = code == 400 and reason == "BadDeviceToken"
        ok &= good
        print(f"{env:11s} {code} {reason:22s} {'credentials OK' if good else 'PROBLEM'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--to")
    ap.add_argument("--env", default="production")
    ap.add_argument("--title", default="Find A Crib")
    ap.add_argument("--body", default="Test alert")
    ap.add_argument("--url")
    a = ap.parse_args()
    cfg = config()
    if not cfg:
        sys.exit("APNS_KEY_PATH / APNS_KEY_ID / APNS_TEAM_ID / APNS_TOPIC not set, or the key file is missing")
    if a.probe:
        return probe(cfg)
    if not a.to:
        sys.exit("--to <device token hex> or --probe")
    print(json.dumps(send(a.to, a.env, a.title, a.body, a.url, cfg=cfg)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
