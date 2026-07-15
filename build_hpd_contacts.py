#!/usr/bin/env python3
"""
Upload sanitized HPD operator contacts to the hpd_contacts table.

buildings.min.json no longer embeds owner/manager/officer (they were 79% of
the file); the frontend lazy-loads them from this table when a building's
popup or detail page opens. Sanitization matches slim.py: phone numbers are
never published — they become a has_phone flag (real numbers live in the
private agent_phones table, served only by the Plus-gated get_agent_phone()).

Run after each HPD refresh (fetch_hpd.py), alongside slim.py + build_research.py:
  python3 build_hpd_contacts.py
"""
import json, subprocess, sys, urllib.request

PROJECT_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"
BATCH = 4000


def keychain(service):
    return subprocess.check_output(
        ["security", "find-generic-password", "-s", service, "-w"],
        stderr=subprocess.DEVNULL).decode().strip()


def sanitize(contact):
    if not isinstance(contact, dict):
        return None
    c = dict(contact)
    c.pop("phone_confidence", None)
    if c.pop("phone", None):
        c["has_phone"] = True
    return c


def rest(token, method, path, body=None):
    req = urllib.request.Request(
        f"{PROJECT_URL}/rest/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": token, "Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates"},
        method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} failed ({e.code}): {e.read().decode()[:300]}")


def main():
    hpd = json.load(open("buildings_hpd.json"))
    items = hpd.items() if isinstance(hpd, dict) else ((r["bbl"], r) for r in hpd)
    rows = []
    for bbl, h in items:
        row = {"bbl": bbl,
               "owner": sanitize(h.get("owner")),
               "manager": sanitize(h.get("manager")),
               "officer": sanitize(h.get("officer"))}
        if row["owner"] or row["manager"] or row["officer"]:
            rows.append(row)
    print(f"{len(rows)} buildings with contacts")
    token = keychain("rent-map-supabase-service-role")
    for i in range(0, len(rows), BATCH):
        rest(token, "POST", "hpd_contacts", rows[i:i+BATCH])
        print(f"{min(i+BATCH, len(rows))}/{len(rows)}")
    print("done")


if __name__ == "__main__":
    main()
