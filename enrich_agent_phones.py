#!/usr/bin/env python3
"""
Enrich managing-agent records in buildings_hpd.json with a phone number,
using the Google Places API (Text Search v1).

WHY THIS EXISTS
  NYC's HPD/DOB open data carries the managing agent's NAME + business address
  but no phone number (stripped for privacy). The only realistic way to attach a
  phone is to look the agent's *business* up in Google Places. Individuals are
  deliberately skipped: publishing a private person's phone in a consumer app is
  a privacy/anti-harassment problem. We only enrich entries that look like a
  managing *company*.

REQUIREMENTS
  A Google Places server key in the macOS keychain:
      security add-generic-password -s rent-map-places-key -a findacrib -w 'AIza...'
  The key MUST be:
    - in the same Google Cloud project as the Street View key (740995613924),
    - have the Places API (New) enabled + billing on,
    - restricted by IP to the box you run this on (NOT HTTP-referrer; referrer
      keys are rejected by the Places API server-side).

USAGE
  python3 enrich_agent_phones.py --dry-run          # count unique business agents + cost estimate, no API calls
  python3 enrich_agent_phones.py --limit 25         # query at most 25 new agents (good for a first paid test)
  python3 enrich_agent_phones.py                    # full run (uses cache; only queries agents not seen before)

OUTPUT
  agent_phones.json   cache of {name|address -> {phone, matched_name, matched_address, confidence}}
  buildings_hpd.json  updated in place: each manager gets manager.phone / manager.phone_confidence when found
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request, urllib.error

HPD_FILE   = "buildings_hpd.json"
CACHE_FILE = "agent_phones.json"
KEYCHAIN_SERVICE = "rent-map-places-key"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.displayName,places.nationalPhoneNumber,places.formattedAddress"

# A managing agent is treated as a *business* (safe to enrich) only if its name
# contains one of these tokens. Everything else is assumed to be an individual.
BUSINESS_RE = re.compile(r"\b(" + "|".join([
    r"LLC", r"L\.?L\.?C", r"INC", r"CORP", r"CO", r"COMPANY", r"LP", r"L\.?P",
    r"LLP", r"MANAGEMENT", r"MGMT", r"MGT", r"REALTY", r"REALTORS", r"PROPERTIES",
    r"PROPERTY", r"ASSOCIATES", r"ASSOC", r"GROUP", r"HOLDINGS", r"PARTNERS",
    r"ENTERPRISES", r"EQUITIES", r"RESIDENTIAL", r"DEVELOPMENT", r"CAPITAL",
    r"HOUSING", r"APARTMENTS", r"ESTATES", r"SERVICES", r"AGENCY", r"TRUST",
    r"FUND", r"REIT", r"MANAGERS", r"ADVISORS",
]) + r")\b", re.I)

# Cost reference: Places Text Search "Pro" SKU (returns formattedAddress + phone)
# is ~$0.032 per request as of 2024 pricing. Used only for the dry-run estimate.
COST_PER_REQUEST = 0.032


def keychain_secret(service):
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL).decode().strip()
    except subprocess.CalledProcessError:
        return None


def is_business(name):
    return bool(name and BUSINESS_RE.search(name))


def tokens(s):
    return set(re.findall(r"[A-Z0-9]+", (s or "").upper()))


def confidence(agent_name, matched_name):
    """Cheap token-overlap score so we don't attach a phone for the wrong place."""
    a, b = tokens(agent_name), tokens(matched_name)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def places_lookup(key, name, address):
    body = json.dumps({"textQuery": f"{name} {address}", "maxResultCount": 1}).encode()
    req = urllib.request.Request(PLACES_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"error": str(e)}
    places = data.get("places") or []
    if not places:
        return {"phone": None}
    p = places[0]
    return {
        "phone": p.get("nationalPhoneNumber"),
        "matched_name": (p.get("displayName") or {}).get("text"),
        "matched_address": p.get("formattedAddress"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count agents + estimate cost; no API calls")
    ap.add_argument("--limit", type=int, default=0, help="max NEW agents to query this run (0 = no limit)")
    ap.add_argument("--min-confidence", type=float, default=0.5, help="min name-overlap to accept a phone")
    ap.add_argument("--sleep", type=float, default=0.1, help="seconds between API calls")
    args = ap.parse_args()

    if not os.path.exists(HPD_FILE):
        sys.exit(f"missing {HPD_FILE} (run from the repo root)")
    hpd = json.load(open(HPD_FILE))

    cache = json.load(open(CACHE_FILE)) if os.path.exists(CACHE_FILE) else {}

    # Collect unique business managing agents, deduped by NAME (one phone per
    # company). Track how many buildings each covers + its most-common address so
    # we can query highest-coverage companies first and spend every dollar well.
    from collections import Counter, defaultdict
    bld_count = Counter()
    addrs = defaultdict(Counter)
    individuals = no_manager = 0
    for rec in hpd.values():
        mgr = (rec or {}).get("manager") or {}
        name, addr = mgr.get("name"), mgr.get("address")
        if not name:
            no_manager += 1
            continue
        if not is_business(name):
            individuals += 1
            continue
        key = re.sub(r"\s+", " ", name.upper()).strip()
        bld_count[key] += 1
        if addr:
            addrs[key][addr] += 1

    # name-key -> (display name, best address); ordered by coverage (most buildings first)
    agents = {}
    for key, _ in bld_count.most_common():
        rep_addr = addrs[key].most_common(1)[0][0] if addrs[key] else ""
        agents[key] = (key, rep_addr)

    uncached = [k for k in agents if k not in cache]  # already coverage-ordered
    print(f"buildings:            {len(hpd):,}")
    print(f"no managing agent:    {no_manager:,}")
    print(f"individual agents:    {individuals:,} (skipped for privacy)")
    print(f"unique business agents:{len(agents):,}")
    print(f"already cached:       {len(agents) - len(uncached):,}")
    print(f"new to query:         {len(uncached):,}")

    if args.dry_run:
        print(f"\nestimated cost this run: ${len(uncached) * COST_PER_REQUEST:,.2f} "
              f"(~${COST_PER_REQUEST} per Places Text Search request)")
        print("no API calls made (--dry-run).")
        return

    key = keychain_secret(KEYCHAIN_SERVICE)
    if not key:
        sys.exit(f"\nNo Places key in keychain. Add one with:\n"
                 f"  security add-generic-password -s {KEYCHAIN_SERVICE} -a findacrib -w 'AIza...'\n"
                 f"See the header of this file for the key restrictions it needs.")

    todo = uncached[: args.limit] if args.limit else uncached
    print(f"\nquerying {len(todo)} agents...\n")
    found = 0
    for i, k in enumerate(todo, 1):
        name, addr = agents[k]
        res = places_lookup(key, name, addr)
        if res.get("error"):
            print(f"  [{i}/{len(todo)}] ERROR {name}: {res['error']}")
            if "HTTP 403" in res["error"] or "HTTP 400" in res["error"]:
                sys.exit("aborting: key/permission problem — fix the key and re-run (cache is preserved)")
            continue
        conf = confidence(name, res.get("matched_name", "")) if res.get("phone") else 0.0
        entry = {
            "phone": res.get("phone") if conf >= args.min_confidence else None,
            "matched_name": res.get("matched_name"),
            "matched_address": res.get("matched_address"),
            "confidence": round(conf, 2),
        }
        cache[k] = entry
        if entry["phone"]:
            found += 1
            print(f"  [{i}/{len(todo)}] {name}  ->  {entry['phone']}  (conf {conf:.2f})")
        else:
            print(f"  [{i}/{len(todo)}] {name}  ->  no confident match")
        if i % 25 == 0:  # checkpoint the cache periodically
            json.dump(cache, open(CACHE_FILE, "w"), indent=1)
        time.sleep(args.sleep)

    json.dump(cache, open(CACHE_FILE, "w"), indent=1)

    # Write phones back into buildings_hpd.json (manager.phone).
    injected = 0
    for rec in hpd.values():
        mgr = (rec or {}).get("manager") or {}
        if not mgr.get("name"):
            continue
        hit = cache.get(re.sub(r"\s+", " ", mgr["name"].upper()).strip())
        if hit and hit.get("phone"):
            mgr["phone"] = hit["phone"]
            mgr["phone_confidence"] = hit["confidence"]
            injected += 1
    json.dump(hpd, open(HPD_FILE, "w"), ensure_ascii=False)

    print(f"\ndone. phones found this run: {found}")
    print(f"buildings now carrying a manager phone: {injected:,}")
    print("note: rebuild buildings.min.json (the file the site loads) to surface these.")


if __name__ == "__main__":
    main()
