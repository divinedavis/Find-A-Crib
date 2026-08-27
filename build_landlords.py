#!/usr/bin/env python3
"""Build landlords.json — the portfolio behind every NYC rent-stabilized landlord.

Why this tier exists
--------------------
The 2026-08-27 index census found Google fetching 55 of 250 sampled building
pages and indexing one. Those pages are 53-71% identical to each other, because
a template over one building can only say so much. This tier is the opposite
shape: one page per landlord, and no two portfolios are alike. "Who owns my
building", "<LLC name> nyc" and "worst landlords" are real, high-intent queries
whose only serious incumbent is JustFix's Who Owns What.

Everything here is already public: HPD requires every registered building to
name an owner and a managing agent, and the site already shows both on the
building page and searches them in the box.

Who gets a page
---------------
Owner and managing-agent names only — never the head officer. An officer is an
individual named as a company's contact, and a page titled with a private
person's name is the one case here with a real cost to getting wrong.

  * an organisation-shaped name with 5+ buildings, or
  * any name with 10+ buildings

A name with ten buildings is operating as a landlord business whether or not it
is spelled like one. Below that, an individual with a couple of houses stays out.

Usage:  python3 build_landlords.py        # writes landlords.json
"""
import json, os, re, subprocess, sys, urllib.request, collections

PROJECT_REF = "dbaifotzwlxjvsxjohjt"
QUERY_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
HERE = os.path.dirname(os.path.abspath(__file__))

# Names that read as a company rather than a person. Deliberately broad: a false
# positive publishes a portfolio page for a landlord who is in fact an
# individual, which the 10-building rule would have published anyway; a false
# negative just means the name needs ten buildings instead of five.
ORG_RE = re.compile(
    r"\b(LLC|L\.?L\.?C|LP|LLP|INC|CORP|CORPORATION|REALTY|REAL ESTATE|MANAGEMENT|MGMT|"
    r"PROPERTIES|PROPERTY|ASSOCIATES|ASSOC|HOLDINGS?|GROUP|PARTNERS?|PARTNERSHIP|TRUST|"
    r"HDFC|HOUSING|DEVELOPMENT|EQUITIES|VENTURES?|COMPANY|CO\.|ENTERPRISES?|ESTATES|"
    r"OWNERS?|BUILDERS?|MANAGERS?|RESIDENTIAL|APARTMENTS?)\b", re.I)
ORG_MIN, PERSON_MIN = 5, 10


def keychain(service):
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def run_sql(token, sql):
    req = urllib.request.Request(
        QUERY_URL, data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "curl/8.7.1"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read().decode())


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:70].strip("-")


KEEP_UPPER = {"LLC", "LP", "LLP", "INC", "HDFC", "NY", "NYC", "USA", "II", "III", "IV",
              "LTD", "CO", "DBA", "JV", "MGMT", "HDC", "LLLP", "PC"}
KEEP_LOWER = {"of", "and", "the", "at", "for", "in", "on", "de", "la"}


def display(name):
    """HPD stores names shouting. Title-case without mangling the initialisms.

    Splitting on whitespace alone turned "C&C APARTMENT MANAGEMENT" into
    "C&c ..." and "GPG MANAGEMENT" into "Gpg ...", so the split is on letters
    and a vowel-free run of three or fewer letters is treated as an initialism.
    """
    def fix(tok, first):
        up = tok.upper()
        if up in KEEP_UPPER:
            return up
        if len(tok) <= 3 and not re.search(r"[AEIOUY]", up):
            return up                       # GPG, C, JBM — an initialism, not a word
        if not first and tok.lower() in KEEP_LOWER:
            return tok.lower()
        return tok[:1].upper() + tok[1:].lower()

    parts = re.split(r"([A-Za-z]+)", name.strip())
    seen_word = False
    out = []
    for p in parts:
        if p.isalpha():
            out.append(fix(p, not seen_word))
            seen_word = True
        else:
            out.append(p)
    return "".join(out)


def main():
    token = os.environ.get("SUPABASE_ACCESS_TOKEN") or keychain("supabase-pat-clockin")
    if not token:
        sys.exit("no Supabase token (SUPABASE_ACCESS_TOKEN or keychain supabase-pat-clockin)")

    rows = run_sql(token, """
      select bbl, trim(owner->>'name') nm, 'owner' as role
        from public.hpd_contacts where coalesce(owner->>'name','') <> ''
      union all
      select bbl, trim(manager->>'name'), 'manager'
        from public.hpd_contacts where coalesce(manager->>'name','') <> '';""")
    print(f"hpd_contacts rows: {len(rows):,}")

    blds = {b["bbl"]: b for b in json.load(open(os.path.join(HERE, "buildings.min.json")))}
    try:
        listed = set(json.load(open(os.path.join(HERE, "listings.json"))).get("counts") or {})
    except Exception:
        listed = set()

    by_name = collections.defaultdict(lambda: {"bbls": set(), "roles": set()})
    for r in rows:
        nm = (r["nm"] or "").strip()
        # A bare number or one-character name is a data-entry artefact, not a landlord.
        if len(nm) < 4 or nm.isdigit():
            continue
        if r["bbl"] not in blds:          # registered with HPD but not DHCR-stabilized
            continue
        e = by_name[nm.upper()]
        e["bbls"].add(r["bbl"])
        e["roles"].add(r["role"])

    out = []
    for up, e in by_name.items():
        n = len(e["bbls"])
        org = bool(ORG_RE.search(up))
        if n < (ORG_MIN if org else PERSON_MIN):
            continue
        items, boros = [], collections.Counter()
        units = viol = classc = adv = 0
        for bbl in e["bbls"]:
            b = blds[bbl]
            v = (b.get("h") or {}).get("violations") or {}
            units += b.get("u") or 0
            viol += v.get("open") or 0
            classc += v.get("oc") or 0
            if bbl in listed:
                adv += 1
            boros[b["b"]] += 1
            items.append({"bbl": bbl, "a": b.get("a"), "b": b["b"], "nb": b.get("nb"),
                          "u": b.get("u"), "ov": v.get("open") or 0, "oc": v.get("oc") or 0,
                          "adv": bbl in listed})
        items.sort(key=lambda x: (-(x["ov"] or 0), x["a"] or ""))
        out.append({"name": display(up), "slug": slugify(up), "org": org,
                    "roles": sorted(e["roles"]), "buildings": n, "units": units,
                    "open_violations": viol, "open_class_c": classc, "advertised": adv,
                    "boroughs": dict(boros), "items": items})

    # Two landlords can slug the same ("ABC Realty LLC" / "ABC Realty, L.L.C.").
    # Suffix the later ones rather than letting one page overwrite another.
    seen = collections.Counter()
    out.sort(key=lambda e: (-e["buildings"], e["name"]))
    for e in out:
        seen[e["slug"]] += 1
        if seen[e["slug"]] > 1:
            e["slug"] = f"{e['slug']}-{seen[e['slug']]}"

    path = os.path.join(HERE, "landlords.json")
    json.dump({"generated": __import__("datetime").date.today().isoformat(),
               "org_min": ORG_MIN, "person_min": PERSON_MIN, "landlords": out},
              open(path, "w"), separators=(",", ":"))
    print(f"landlords: {len(out):,} entities covering "
          f"{len({b for e in out for b in [i['bbl'] for i in e['items']]}):,} buildings "
          f"-> {os.path.getsize(path)/1e6:.1f} MB")
    print("  top: " + ", ".join(f"{e['name']} ({e['buildings']})" for e in out[:5]))


if __name__ == "__main__":
    main()
