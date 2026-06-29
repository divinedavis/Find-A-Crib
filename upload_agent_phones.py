#!/usr/bin/env python3
"""
Push harvested managing-agent phone numbers into the PRIVATE Supabase table
public.agent_phones, keyed by BBL. The site never sees these numbers directly;
they are only returned by get_agent_phone() to Find A Crib Plus subscribers.

Source of truth is agent_phones.json (company name -> phone, from
enrich_agent_phones.py) joined against buildings_hpd.json (bbl -> manager name),
so it does not depend on the enrichment's write-back step.

Usage:
  python3 upload_agent_phones.py --dry-run     # show how many bbls would get a phone
  python3 upload_agent_phones.py               # upsert into Supabase
"""
import argparse, json, os, re, subprocess, sys, urllib.request, urllib.error

HPD_FILE   = "buildings_hpd.json"
CACHE_FILE = "agent_phones.json"
PROJECT_REF = "dbaifotzwlxjvsxjohjt"
REST = f"https://{PROJECT_REF}.supabase.co/rest/v1/agent_phones"
BATCH = 500


def keychain(service):
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL).decode().strip()
    except subprocess.CalledProcessError:
        return None


def norm(name):
    return re.sub(r"\s+", " ", name.upper()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-confidence", type=float, default=0.5)
    args = ap.parse_args()

    hpd = json.load(open(HPD_FILE))
    cache = json.load(open(CACHE_FILE)) if os.path.exists(CACHE_FILE) else {}

    rows = []
    for bbl, rec in hpd.items():
        mgr = (rec or {}).get("manager") or {}
        name = mgr.get("name")
        if not name:
            continue
        hit = cache.get(norm(name))
        if hit and hit.get("phone") and hit.get("confidence", 0) >= args.min_confidence:
            rows.append({"bbl": bbl, "phone": hit["phone"], "agent_name": name,
                         "confidence": hit["confidence"]})

    print(f"buildings with a confident agent phone: {len(rows):,}")
    if args.dry_run:
        for r in rows[:5]:
            print("  e.g.", r["bbl"], r["agent_name"], "->", r["phone"])
        print("dry-run: nothing written.")
        return

    key = keychain("rent-map-supabase-service-role")
    if not key:
        sys.exit("missing keychain item rent-map-supabase-service-role")
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    sent = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        req = urllib.request.Request(REST, data=json.dumps(chunk).encode(),
                                     method="POST", headers=headers)
        try:
            urllib.request.urlopen(req, timeout=30).read()
            sent += len(chunk)
            print(f"  upserted {sent:,}/{len(rows):,}")
        except urllib.error.HTTPError as e:
            sys.exit(f"upsert failed at batch {i}: HTTP {e.code} {e.read().decode()[:300]}")
    print(f"done. {sent:,} rows in agent_phones.")


if __name__ == "__main__":
    main()
