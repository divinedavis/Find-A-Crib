#!/usr/bin/env python3
"""
Issue a Find A Crib developer API key.

Generates a key, stores only its SHA-256 hash (the plaintext is shown ONCE),
and records the owner + tier. Used by the developer signup flow and for
manual/admin issuance.

  python3 issue_api_key.py --email dev@example.com --tier free [--label "Acme app"]

Tiers: free (1k req/day), pro (50k), business (500k).
"""
import argparse, hashlib, json, os, secrets, subprocess, sys, urllib.request, urllib.error

PROJECT_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"


def service_key():
    v = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if v:
        return v
    return subprocess.check_output(
        ["security", "find-generic-password", "-s", "rent-map-supabase-service-role", "-w"],
        stderr=subprocess.DEVNULL).decode().strip()


def rest(token, method, path, body=None, prefer=None):
    headers = {"apikey": token, "Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(f"{PROJECT_URL}/rest/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} failed ({e.code}): {e.read().decode()[:300]}")


def issue(email, tier, label=None):
    plain = "fac_live_" + secrets.token_hex(20)          # 40 hex chars of entropy
    key_hash = hashlib.sha256(plain.encode()).hexdigest()
    prefix = plain[:16] + "…"
    token = service_key()
    rest(token, "POST", "api_keys",
         {"key_hash": key_hash, "key_prefix": prefix, "owner_email": email,
          "tier": tier, "label": label},
         prefer="return=minimal")
    return plain, prefix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--tier", default="free", choices=["free", "pro", "business"])
    ap.add_argument("--label", default=None)
    args = ap.parse_args()
    plain, prefix = issue(args.email, args.tier, args.label)
    print(f"Issued {args.tier} key for {args.email}")
    print(f"  prefix : {prefix}")
    print(f"  KEY    : {plain}")
    print("  (store this now — it is not recoverable)")


if __name__ == "__main__":
    main()
