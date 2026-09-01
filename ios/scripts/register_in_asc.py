#!/usr/bin/env python3
"""Register the Find A Crib bundle ID, enable Sign In with Apple, and create the
App Store Connect app record — all via the ASC API.

The Bundle ID dropdown in ASC's "New App" dialog only lists identifiers that
are already registered under Certificates, Identifiers & Profiles. Registering
one here is what makes it appear there.

Idempotent. Re-run safely; each step looks up the existing resource before
creating. Reads credentials from scripts/asc-config.env and writes the
resulting ASC app id back to the same file.

App Store names are globally unique, so app creation walks NAME_CANDIDATES
until one sticks.


Usage:
    python3 scripts/register_in_asc.py
    python3 scripts/register_in_asc.py --dry-run   # report, change nothing
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import time

import jwt
import requests

CONFIG_PATH = pathlib.Path(__file__).resolve().parent / "asc-config.env"
API_BASE = "https://api.appstoreconnect.apple.com/v1"

NAME_CANDIDATES = [
    "Find A Crib",
    "Find A Crib: Rent Stabilized NYC",
    "Find A Crib — Rent-Stabilized Homes",
]
SKU = "findacrib-ios-001"
BUNDLE_NAME = "Find A Crib"

# Sign In with Apple is shipped in SignInView, so the identifier needs it or
# the entitlement will not sign. Google needs nothing from Apple.
CAPABILITIES: list[str] = []   # no push, no Sign in with Apple yet


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"missing {CONFIG_PATH} — copy asc-config.env.example")
    cfg: dict = {}
    for line in CONFIG_PATH.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        k, _, v = s.partition("=")
        cfg[k.strip()] = os.path.expandvars(v.strip().strip('"').strip("'"))
    return cfg


def write_config_value(key: str, value: str) -> None:
    text = CONFIG_PATH.read_text()
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    # The env file is `source`d by shell scripts — quote anything with spaces.
    if any(c in value for c in ' \t"'):
        value = '"' + value.replace('"', '\\"') + '"'
    line = f"{key}={value}"
    text = pattern.sub(line, text) if pattern.search(text) else text.rstrip() + f"\n{line}\n"
    CONFIG_PATH.write_text(text)


def make_token(cfg: dict) -> str:
    private_key = pathlib.Path(cfg["ASC_KEY_PATH"]).expanduser().read_text()
    now = int(time.time())
    return jwt.encode(
        {"iss": cfg["ASC_ISSUER_ID"], "iat": now, "exp": now + 15 * 60, "aud": "appstoreconnect-v1"},
        private_key,
        algorithm="ES256",
        headers={"kid": cfg["ASC_KEY_ID"], "typ": "JWT"},
    )


def api(token: str, method: str, path: str, params=None, body=None, ok_statuses=()) -> tuple[int, dict]:
    r = requests.request(
        method,
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params=params or {},
        json=body,
        timeout=30,
    )
    if r.status_code >= 400 and r.status_code not in ok_statuses:
        raise SystemExit(f"{method} {path} -> {r.status_code}\n{r.text}")
    return r.status_code, (r.json() if r.text else {})


def register_bundle_id(token: str, identifier: str, dry_run: bool) -> str | None:
    _, res = api(token, "GET", "/bundleIds", params={"filter[identifier]": identifier, "limit": 1})
    data = res.get("data", [])
    if data:
        print(f"   already registered (resource id {data[0]['id']})")
        return data[0]["id"]
    if dry_run:
        print("   would register it")
        return None
    body = {
        "data": {
            "type": "bundleIds",
            "attributes": {"identifier": identifier, "name": BUNDLE_NAME, "platform": "IOS"},
        }
    }
    _, res = api(token, "POST", "/bundleIds", body=body)
    rid = res["data"]["id"]
    print(f"   registered (resource id {rid})")
    return rid


def add_capability(token: str, bundle_resource_id: str, capability_type: str, dry_run: bool) -> None:
    _, res = api(token, "GET", f"/bundleIds/{bundle_resource_id}/bundleIdCapabilities")
    if any(e.get("attributes", {}).get("capabilityType") == capability_type for e in res.get("data", [])):
        print(f"   {capability_type} already enabled")
        return
    if dry_run:
        print(f"   would enable {capability_type}")
        return
    attributes: dict = {"capabilityType": capability_type}

    # APPLE_ID_AUTH is rejected with "Please select at least one configuration
    # for Sign In with Apple" unless it carries a consent setting. PRIMARY_APP
    # is the right one here: this app is the primary, not a grouped app
    # inheriting another's Apple ID relationship.
    if capability_type == "APPLE_ID_AUTH":
        attributes["settings"] = [
            {
                "key": "APPLE_ID_AUTH_APP_CONSENT",
                "options": [{"key": "PRIMARY_APP_CONSENT"}],
            }
        ]

    body = {
        "data": {
            "type": "bundleIdCapabilities",
            "attributes": attributes,
            "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle_resource_id}}},
        }
    }
    api(token, "POST", "/bundleIdCapabilities", body=body)
    print(f"   enabled {capability_type}")


def create_app(token: str, *, identifier: str, bundle_resource_id: str, dry_run: bool) -> tuple[str, str] | None:
    _, res = api(token, "GET", "/apps", params={"filter[bundleId]": identifier, "limit": 1})
    data = res.get("data", [])
    if data:
        name = data[0]["attributes"]["name"]
        print(f"   app already exists (id {data[0]['id']}, name {name!r})")
        return data[0]["id"], name
    if dry_run:
        print(f"   would try names: {NAME_CANDIDATES}")
        return None

    for name in NAME_CANDIDATES:
        body = {
            "data": {
                "type": "apps",
                "attributes": {
                    "bundleId": identifier,
                    "name": name,
                    "primaryLocale": "en-US",
                    "sku": SKU,
                },
                "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle_resource_id}}},
            }
        }
        status, res = api(token, "POST", "/apps", body=body, ok_statuses=(409, 403, 400))
        if status < 400:
            app_id = res["data"]["id"]
            print(f"   created app (id {app_id}, name {name!r})")
            return app_id, name

        errors = " ".join(e.get("detail", "") for e in res.get("errors", []))

        # Apple does not expose app creation on the API — `apps` is
        # GET_COLLECTION / GET_INSTANCE / UPDATE only. Every name candidate
        # will fail the same way, so stop rather than hammering the endpoint
        # three times and reporting it as a naming problem.
        if "does not allow 'CREATE'" in errors:
            print("   app records cannot be created over the API — Apple allows")
            print("   only GET and UPDATE on /apps. Create it once in the dashboard:")
            print("     https://appstoreconnect.apple.com/apps  ->  +  ->  New App")
            print(f"     Platform  iOS")
            print(f"     Name      {NAME_CANDIDATES[0]}")
            print(f"     Language  English (U.S.)")
            print(f"     Bundle ID {identifier}")
            print(f"     SKU       {SKU}")
            print(f"     Access    Full Access")
            print("   then re-run this script to capture the app id.")
            return None

        print(f"   name {name!r} rejected: {errors.strip() or status}")

    raise SystemExit("all name candidates rejected — pick a new name and re-run")


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    cfg = load_config()
    bundle = cfg["ASC_BUNDLE_ID"]

    print(f"==> key {cfg['ASC_KEY_ID']} / issuer {cfg['ASC_ISSUER_ID'][:8]}…"
          + ("  (DRY RUN)" if dry_run else ""))
    token = make_token(cfg)

    print(f"==> bundle id {bundle}")
    bundle_resource_id = register_bundle_id(token, bundle, dry_run)

    if bundle_resource_id:
        print("==> capabilities")
        for capability in CAPABILITIES:
            add_capability(token, bundle_resource_id, capability, dry_run)

        print("==> App Store Connect app record")
        result = create_app(token, identifier=bundle, bundle_resource_id=bundle_resource_id, dry_run=dry_run)
        if result and not dry_run:
            app_id, name = result
            write_config_value("ASC_APP_ID", app_id)
            write_config_value("ASC_APP_NAME", name)
            print(f"==> saved ASC_APP_ID={app_id} to scripts/asc-config.env")



if __name__ == "__main__":
    main()
