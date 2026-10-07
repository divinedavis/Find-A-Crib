#!/usr/bin/env python3
"""Upload App Store creative assets (header / search results / universal)
to an app's Asset Library through the ASC API (spec 4.5.1, fall 2026).

Works for any app on the team: the API key in asc-config.env is team-wide.
Upload only. It never submits an asset for review or places it on a
version, custom product page or experiment, because those go public and
several apps are under an App Store freeze (see memory).

    ~/.venvs/dhcr-map/bin/python scripts/asc_creative_assets.py list APP_ID
    ~/.venvs/dhcr-map/bin/python scripts/asc_creative_assets.py upload APP_ID DIR [--prefix NAME]
    ~/.venvs/dhcr-map/bin/python scripts/asc_creative_assets.py retire APP_ID --prefix NAME

`upload` sends every *.png under DIR (recursively). The reference name is
`<prefix>/<relative path>`, so a rerun skips files already in the library
instead of uploading duplicates. `retire` removes every live asset whose
reference name starts with `<prefix>/` (archives approved ones, deletes
drafts, since Apple only archives approved assets), so a redesigned set can
be uploaded under the same names.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import jwt
import requests

HERE = Path(__file__).resolve().parent
API = "https://api.appstoreconnect.apple.com"


def _cfg():
    cfg = {}
    for line in (HERE / "asc-config.env").read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            cfg[k] = v.strip().strip('"')
    return cfg


def _headers():
    cfg = _cfg()
    now = int(time.time())
    key = Path(os.path.expandvars(cfg["ASC_KEY_PATH"])).expanduser().read_text()
    tok = jwt.encode({"iss": cfg["ASC_ISSUER_ID"], "iat": now, "exp": now + 15 * 60,
                      "aud": "appstoreconnect-v1"}, key, algorithm="ES256",
                     headers={"kid": cfg["ASC_KEY_ID"]})
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def call(method, path, body=None):
    r = requests.request(method, API + path, headers=_headers(), json=body, timeout=60)
    if r.status_code >= 400:
        sys.exit(f"{method} {path} -> {r.status_code}\n{r.text[:1500]}")
    return r.json() if r.text else {}


def images(app_id):
    out, path = [], f"/v1/appAssetLibraries/{app_id}/images?limit=200&filter[category]=CREATIVE_ASSETS"
    while path:
        d = call("GET", path)
        out += d["data"]
        nxt = d.get("links", {}).get("next")
        path = nxt[len(API):] if nxt else None
    return out


def upload_one(app_id, f, ref):
    data = f.read_bytes()
    d = call("POST", "/v1/appAssetLibraryImages", {"data": {
        "type": "appAssetLibraryImages",
        "attributes": {"category": "CREATIVE_ASSETS", "fileName": f.name,
                       "fileSize": len(data), "referenceName": ref},
        "relationships": {"assetLibrary": {"data": {"type": "appAssetLibraries", "id": app_id}}}}})
    img = d["data"]
    for op in img["attributes"].get("uploadOperations") or []:
        chunk = data[op["offset"]:op["offset"] + op["length"]]
        hdrs = {h["name"]: h["value"] for h in op.get("requestHeaders") or []}
        r = requests.request(op["method"], op["url"], headers=hdrs, data=chunk, timeout=300)
        if r.status_code >= 400:
            sys.exit(f"chunk upload failed {r.status_code}: {r.text[:500]}")
    call("PATCH", f"/v1/appAssetLibraryImages/{img['id']}", {"data": {
        "type": "appAssetLibraryImages", "id": img["id"], "attributes": {"uploaded": True}}})
    for _ in range(40):
        a = call("GET", f"/v1/appAssetLibraryImages/{img['id']}")["data"]["attributes"]
        if a.get("state") not in ("AWAITING_UPLOAD", "UPLOAD_COMPLETE"):
            break
        time.sleep(3)
    return img["id"], a.get("state"), a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "upload", "retire"])
    ap.add_argument("app_id")
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--prefix", default="")
    a = ap.parse_args()

    existing = images(a.app_id)
    if a.cmd == "list":
        for i in existing:
            at = i["attributes"]
            print(f"{i['id']}  {at.get('state'):<22} {at.get('referenceName')}")
        return
    if a.cmd == "retire":
        if not a.prefix:
            sys.exit("retire needs --prefix")
        for i in existing:
            at = i["attributes"]
            if at.get("state") != "ARCHIVED" and (at.get("referenceName") or "").startswith(a.prefix + "/"):
                if at.get("state") == "APPROVED":
                    call("PATCH", f"/v1/appAssetLibraryImages/{i['id']}", {"data": {
                        "type": "appAssetLibraryImages", "id": i["id"], "attributes": {"archived": True}}})
                    print(f"archived {at.get('referenceName')}")
                else:
                    call("DELETE", f"/v1/appAssetLibraryImages/{i['id']}")
                    print(f"deleted  {at.get('referenceName')} ({at.get('state')})")
        return
    have = {i["attributes"].get("referenceName") for i in existing if i["attributes"].get("state") != "ARCHIVED"}
    root = Path(a.dir).expanduser()
    for f in sorted(root.rglob("*.png")):
        if f.name.startswith("preview"):
            continue  # local mock-ups, not assets
        ref = "/".join(filter(None, [a.prefix, str(f.relative_to(root))]))
        if ref in have:
            print(f"skip  {ref} (already in library)")
            continue
        iid, state, attrs = upload_one(a.app_id, f, ref)
        detail = "" if state not in ("FAILED",) else f" {attrs.get('stateDetails') or attrs}"
        print(f"{state:<22} {ref}  ({iid}){detail}")


if __name__ == "__main__":
    main()
