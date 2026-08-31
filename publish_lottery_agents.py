#!/usr/bin/env python3
"""
Split marketing_agents.json into the half the world can see and the half Plus
pays for, then publish each to where it belongs.

Until now the whole file shipped to the docroot, contact block and all. Gating
those fields in /marketing-agents/ would have been theatre while
findacrib.com/marketing_agents.json answered the same question to anyone who
asked, so the split has to happen before the file is written, not in the page
that renders it.

  public  -> <docroot>/marketing_agents.json
             firm name, agency, borough, tags, blurb, and whether a contact and
             a re-rental board EXIST. Enough to index, enough to search, enough
             to decide the page is worth an account.
  private -> public.lottery_agent_contacts (service role)
             contact person, phone, email, postal address, website, and the
             re-rental listing URL. Reachable only through the Plus-gated
             get_lottery_agent_contacts() RPC (migration db/0016).

The repo's own marketing_agents.json keeps every field — it is the input that
build/check scripts read, and it is gitignored-adjacent working data, not
something nginx serves.

  python3 publish_lottery_agents.py --out /var/www/rent-map   # write + push
  python3 publish_lottery_agents.py --dry-run                 # show the split
"""
import argparse, json, os, re, subprocess, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "marketing_agents.json")
PROJECT_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"

# Everything here is withheld from the public file. `about` is deliberately NOT
# in this list: it is the firm's own marketing blurb, it is what makes the page
# worth indexing, and withholding it would cost SEO without protecting anything.
PRIVATE_FIELDS = ("contact", "email", "phone", "address", "website")
# Same idea inside the rerentals block: the URL is the thing we hand-verified
# and the thing nobody else publishes. The counts are the teaser.
PRIVATE_RERENTAL = {"url": "rerental_url", "title": "rerental_title", "note": "rerental_note"}

BOROS = ("Manhattan", "Bronx", "Brooklyn", "Queens", "Staten Island")


def norm(name):
    """Key an agent by its name, tolerant of whitespace and punctuation drift.

    The public file and the private table are joined on this in the browser, so
    it has to be reproducible in JS too — hence uppercase + strip to A-Z0-9 and
    single spaces, nothing cleverer.
    """
    k = re.sub(r"[^A-Z0-9 ]+", " ", (name or "").upper())
    return re.sub(r"\s+", " ", k).strip()


def boro_of(agent):
    """Which borough the firm's own office sits in, read off its postal address.

    The address itself is private (it is a contact detail), but the borough is
    a useful public facet and gives away nothing you could mail.
    """
    addr = agent.get("address") or ""
    for b in BOROS:
        if b.lower() in addr.lower():
            return b
    # Manhattan addresses are the ones that habitually say "New York, NY".
    if re.search(r"\bNew York,?\s*N\.?Y\.?", addr, re.I):
        return "Manhattan"
    return None


def split(data):
    """(public payload, private rows) from the full marketing_agents.json."""
    pub_agents, rows = [], []
    for a in data.get("agents", []):
        key = norm(a.get("name"))
        if not key:
            continue
        rr = a.get("rerentals") or {}
        pub = {k: v for k, v in a.items() if k not in PRIVATE_FIELDS and k != "rerentals"}
        pub["key"] = key
        pub["boro"] = boro_of(a)
        # Flags, not values: the page needs to know a lock is worth drawing.
        pub["has_contact"] = bool(any(a.get(f) for f in PRIVATE_FIELDS))
        if rr:
            pub["rerentals"] = {
                "has_page": bool(rr.get("url")),
                # Counts are what make the row worth unlocking, so they stay public.
                "units_seen": bool(rr.get("units_seen")),
                "unit_count": rr.get("unit_count"),
                "checked": rr.get("checked"),
                "last_ok": rr.get("last_ok"),
                # Whether the board takes building applications rather than
                # listing units changes what the row SAYS, not what it reveals.
                "waitlist": bool(rr.get("waitlist")),
            }
        row = {"key": key, "display_name": a.get("name") or key}
        for f in PRIVATE_FIELDS:
            row[f] = a.get(f) or None
        for src, dest in PRIVATE_RERENTAL.items():
            row[dest] = rr.get(src) or None
        rows.append(row)
        pub_agents.append(pub)

    public = {k: v for k, v in data.items() if k != "agents"}
    public["agents"] = pub_agents
    # Say so in the file itself. Someone will fetch this directly and wonder
    # where the phone numbers went.
    public["contacts"] = "plus"
    return public, rows


def keychain(service):
    return subprocess.check_output(
        ["security", "find-generic-password", "-s", service, "-w"],
        stderr=subprocess.DEVNULL).decode().strip()


def push(rows, token):
    """Upsert every row in one request; 85 firms is one small POST."""
    req = urllib.request.Request(
        f"{PROJECT_URL}/rest/v1/lottery_agent_contacts",
        data=json.dumps(rows).encode(),
        headers={"apikey": token, "Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"push failed ({e.code}): {e.read().decode()[:300]}")
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="docroot to write the PUBLIC marketing_agents.json into")
    ap.add_argument("--dry-run", action="store_true", help="print the split, write nothing")
    args = ap.parse_args()

    data = json.load(open(SRC))
    public, rows = split(data)
    withheld = sum(1 for r in rows if any(r[f] for f in PRIVATE_FIELDS))
    boards = sum(1 for r in rows if r["rerental_url"])
    print(f"  {len(rows)} firms · {withheld} with a contact block withheld · "
          f"{boards} re-rental URLs withheld")

    if args.dry_run:
        print(json.dumps(public["agents"][0], indent=1, ensure_ascii=False)[:600])
        return

    token = keychain("rent-map-supabase-service-role")
    print(f"  pushed {push(rows, token)} rows to lottery_agent_contacts")

    if args.out:
        dest = os.path.join(args.out, "marketing_agents.json")
        tmp = dest + ".tmp"
        with open(tmp, "w") as f:
            json.dump(public, f, indent=1, ensure_ascii=False)
        os.replace(tmp, dest)
        print(f"  wrote {dest} (public)")


if __name__ == "__main__":
    main()
