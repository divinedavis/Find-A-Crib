#!/usr/bin/env python3
"""The tracked query universe — what "90% of searches" actually means.

You cannot own 90% of a market you have not defined, so this file defines it:
every query a person types when they are trying to find out whether housing is
rent-stabilized in a city we cover. Share of that universe is the goal metric.

Two things get measured against it:

  coverage  — does a page on this site exist that actually targets this query?
              Computable today, from the sitemap. It drives the content roadmap.
  position  — where do we rank? Only Google Search Console can answer this
              truthfully (scraping the SERP is against Google's terms and gets
              blocked anyway). Until a Search Console service account is wired
              up, `position` stays null and coverage is the honest proxy.

The scout expands this list over time; entries are never deleted, so the
year-end review can show which queries we won and which we never cracked.
"""
import json
import os
import re

from . import ledger

HERE = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_PATH = os.path.join(HERE, "keywords.json")

CITIES = {
    "nyc": {"name": "New York City", "root": "/", "aka": ["nyc", "new york", "new york city"]},
    "sf": {"name": "San Francisco", "root": "/sf/", "aka": ["sf", "san francisco"]},
    "la": {"name": "Los Angeles", "root": "/la/", "aka": ["la", "los angeles"]},
    "dc": {"name": "Washington DC", "root": "/dc/", "aka": ["dc", "washington dc", "washington d.c."]},
}

# Cornerstone guide pages (seo_guides.py / build_seo.py). Named here so the
# targets below stay in step with the slugs rather than drifting into typos.
SF_GUIDE = "/guide/is-my-apartment-rent-controlled-san-francisco/"
LA_GUIDE = "/guide/is-my-apartment-rent-controlled-los-angeles/"
DC_GUIDE = "/guide/is-my-apartment-rent-controlled-washington-dc/"

# Seed universe. `intent` matters more than volume: "check" and "list" queries
# convert into map sessions, "explain" queries earn links and AI citations.
SEED = [
    # ---- NYC (the deepest dataset, so the widest net)
    ("nyc", "rent stabilized apartments nyc", "list", "/"),
    ("nyc", "rent stabilized buildings nyc", "list", "/"),
    ("nyc", "is my apartment rent stabilized", "check", "/guide/"),
    ("nyc", "how to find out if an apartment is rent stabilized", "check", "/guide/"),
    ("nyc", "rent stabilized apartment lookup", "check", "/"),
    ("nyc", "dhcr rent stabilized building list", "list", "/"),
    ("nyc", "rent stabilized apartments brooklyn", "list", "/borough/brooklyn/"),
    ("nyc", "rent stabilized apartments manhattan", "list", "/borough/manhattan/"),
    ("nyc", "rent stabilized apartments queens", "list", "/borough/queens/"),
    ("nyc", "rent stabilized apartments bronx", "list", "/borough/bronx/"),
    ("nyc", "rent stabilized apartments staten island", "list", "/borough/staten-island/"),
    ("nyc", "what is rent stabilization nyc", "explain", "/guide/"),
    ("nyc", "rent stabilized vs rent controlled", "explain", "/guide/"),
    ("nyc", "rent stabilization succession rights", "explain", "/guide/"),
    ("nyc", "rent overcharge complaint nyc", "explain", "/guide/"),
    ("nyc", "how much can rent go up rent stabilized nyc", "explain", "/guide/"),
    ("nyc", "nyc rent guidelines board 2026 increase", "explain", "/guide/"),
    ("nyc", "rent stabilized lease renewal rules", "explain", "/guide/"),
    ("nyc", "section 8 apartments nyc", "list", "/section8/"),
    ("nyc", "apartments that accept section 8 nyc", "list", "/section8/"),
    ("nyc", "apartments that accept vouchers brooklyn", "list", "/section8/brooklyn/"),
    ("nyc", "cityfheps apartments nyc", "list", "/section8/"),
    ("nyc", "hpd violations lookup", "check", "/"),
    ("nyc", "who owns my building nyc", "check", "/"),
    ("nyc", "rent stabilized apartments for rent", "list", "/available/"),
    ("nyc", "section 8 apartments queens", "list", "/section8/queens/"),
    ("nyc", "section 8 apartments bronx", "list", "/section8/bronx/"),
    ("nyc", "voucher friendly apartments nyc", "list", "/section8/"),
    # ---- San Francisco
    # "explain"/"check" queries point at the city guide, not the city map: the
    # map is a listings UI that cannot answer "what are the exemptions", and
    # counting it as coverage was flattering the number. Guides added 2026-07-29.
    ("sf", "rent controlled apartments san francisco", "list", "/sf/"),
    ("sf", "is my apartment rent controlled sf", "check", SF_GUIDE),
    ("sf", "sf rent board lookup", "check", "/sf/"),
    ("sf", "san francisco rent control list", "list", "/sf/"),
    ("sf", "san francisco rent control rules", "explain", SF_GUIDE),
    ("sf", "sf rent control exemptions", "explain", SF_GUIDE),
    ("sf", "how much can rent go up rent controlled sf", "explain", SF_GUIDE),
    # ---- Los Angeles
    ("la", "rent stabilized apartments los angeles", "list", "/la/"),
    ("la", "rso apartment list los angeles", "list", "/la/"),
    ("la", "is my building rent controlled la", "check", LA_GUIDE),
    ("la", "lahd rso lookup", "check", LA_GUIDE),
    ("la", "los angeles rent control rules", "explain", LA_GUIDE),
    ("la", "la just cause eviction rent control", "explain", LA_GUIDE),
    ("la", "how much can landlord raise rent los angeles rent control", "explain", LA_GUIDE),
    # ---- Washington DC
    ("dc", "rent controlled apartments washington dc", "list", "/dc/"),
    ("dc", "dc rent control list", "list", "/dc/"),
    ("dc", "is my apartment rent controlled dc", "check", DC_GUIDE),
    ("dc", "dc rentregistry lookup", "check", "/dc/"),
    ("dc", "dc rent control rules", "explain", DC_GUIDE),
    ("dc", "dc rent control exemptions", "explain", DC_GUIDE),
    ("dc", "how much can rent go up rent controlled dc", "explain", DC_GUIDE),
    # ---- Developer / data-licensing intent (targets the API demand problem)
    ("nyc", "rent stabilization data api", "list", "/developers/"),
    ("nyc", "nyc housing data api", "list", "/developers/"),
    ("nyc", "affordable housing dataset api", "list", "/developers/"),
]


def load():
    try:
        with open(KEYWORDS_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def save(kws):
    tmp = KEYWORDS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(kws, f, indent=2)
        f.write("\n")
    os.replace(tmp, KEYWORDS_PATH)


def seed():
    """Create the universe if absent. Idempotent — never clobbers added queries.

    Also re-points seed-sourced entries at their current SEED target. Without
    this, retargeting a query in SEED (say, from the city map to a guide page
    written later) silently did nothing, because the query already existed and
    was skipped — so the roadmap and the ledger drifted apart with no signal.
    Only `source == "seed"` rows are touched: a target the scout chose is its
    own, and coverage is left for check_coverage to recompute rather than
    guessed at here.
    """
    kws = load()
    by_query = {k["query"]: k for k in kws}
    retargeted = 0
    for city, query, intent, target in SEED:
        existing = by_query.get(query)
        if existing is None:
            kws.append({"query": query, "city": city, "intent": intent,
                        "target": target, "source": "seed", "added": ledger.today(),
                        "covered": None, "position": None, "impressions": None, "clicks": None})
            continue
        if existing.get("source") == "seed" and existing.get("target") != target:
            existing["target"] = target
            existing["intent"] = intent
            # The old verdict was about a different page, so it is no longer an
            # answer to anything. Clearing it means the ledger says "unknown"
            # until check_coverage looks at the new target, rather than carrying
            # a `covered: true` earned by a page this query no longer points at.
            existing["covered"] = None
            existing["coverage_detail"] = f"retargeted to {target}, not yet re-checked"
            retargeted += 1
    if retargeted:
        print(f"  keywords: retargeted {retargeted} seed queries", flush=True)
    save(kws)
    return kws


# City nicknames collapse to one form, so "…sf" and "…san francisco" are not
# tracked as two separate queries. The share goal is a percentage of this list;
# letting restatements inflate it would make the number meaningless.
_ALIASES = {"sf": "sanfrancisco", "san": "", "francisco": "sanfrancisco",
            "la": "losangeles", "los": "", "angeles": "losangeles",
            "nyc": "newyork", "new": "", "york": "newyork",
            "dc": "washingtondc", "washington": "washingtondc",
            "apartment": "apt", "apartments": "apt",
            "stabilised": "stabilized"}
# Only genuinely contentless words. Intent words stay: "lookup", "list", "for
# rent", "check" and "difference" are what separate a tool query from a
# listings query from an explainer, and collapsing them merges queries that
# want completely different pages. An over-eager list here silently deletes
# real coverage, which is worse than tracking a near-duplicate.
_NOISE = {"a", "an", "the", "is", "my", "of", "to", "and", "i", "does", "do"}


def _fingerprint(q):
    """Order-insensitive content signature of a query."""
    toks = []
    for t in re.split(r"[^a-z0-9]+", (q or "").lower()):
        if not t:
            continue
        t = _ALIASES.get(t, t)
        if t and t not in _NOISE:
            toks.append(t)
    return frozenset(toks)


def add(query, city, intent, target="", source="scout", note=""):
    kws = load()
    q = query.strip().lower()
    if any(k["query"] == q for k in kws):
        return None
    fp = _fingerprint(q)
    if fp and any(_fingerprint(k["query"]) == fp for k in kws):
        return None
    kws.append({"query": q, "city": city, "intent": intent, "target": target,
                "source": source, "added": ledger.today(), "note": note,
                "covered": None, "position": None, "impressions": None, "clicks": None})
    save(kws)
    return q


def _tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 2]


def check_coverage(docroot):
    """For each query, does a page exist whose visible text targets it?

    Deliberately shallow: it checks that the declared target page exists and
    that its title/h1 carries the query's distinguishing tokens. That catches
    the real failure mode — a query nobody wrote a page for — without pretending
    to predict rank.
    """
    kws = load()

    # Guard: run against anything that is not a BUILT docroot — a bare repo
    # checkout, say — and every query comes back uncovered, silently destroying
    # real coverage history. A checkout has index.html but none of the generated
    # section directories, so require those before writing anything.
    built = sum(1 for d in ("borough", "guide", "buildings", "section8", "neighborhood")
                if os.path.isdir(os.path.join(docroot, d)))
    if built < 2:
        raise RuntimeError(
            f"{docroot!r} does not look like a built docroot (found {built} of the expected "
            f"generated directories) — refusing to overwrite coverage data with false negatives")

    STOP = {"the", "and", "for", "how", "what", "out", "much", "can", "you", "your", "are", "that"}
    changed = 0
    for k in kws:
        target = k.get("target") or CITIES.get(k["city"], {}).get("root", "/")
        path = os.path.join(docroot, target.strip("/"), "index.html")
        if target == "/":
            path = os.path.join(docroot, "index.html")
        covered = False
        detail = "no page at target"
        if os.path.exists(path):
            try:
                with open(path, errors="replace") as f:
                    html = f.read(200_000).lower()
            except Exception:
                html = ""
            head = " ".join(re.findall(r"<title>(.*?)</title>|<h1[^>]*>(.*?)</h1>",
                                       html, re.S | re.I)[0] if re.search(r"<title>", html) else "")
            head = re.sub(r"<[^>]+>", " ", head)
            toks = [t for t in _tokens(k["query"]) if t not in STOP]
            hit_head = sum(1 for t in toks if t in head)
            hit_body = sum(1 for t in toks if t in html)
            if toks and hit_head >= max(2, len(toks) // 2):
                covered, detail = True, "targeted by title/h1"
            elif toks and hit_body >= len(toks):
                covered, detail = True, "all terms present in body only (weak)"
            else:
                detail = f"page exists, {hit_body}/{len(toks)} terms present"
        if k.get("covered") != covered:
            changed += 1
        k["covered"] = covered
        k["coverage_detail"] = detail
        k["coverage_checked"] = ledger.today()
    save(kws)
    return kws, changed


def summary():
    kws = load()
    total = len(kws)
    covered = sum(1 for k in kws if k.get("covered"))
    by_city = {}
    for k in kws:
        c = by_city.setdefault(k["city"], {"total": 0, "covered": 0})
        c["total"] += 1
        c["covered"] += 1 if k.get("covered") else 0
    ranked = [k for k in kws if k.get("position")]
    top10 = sum(1 for k in ranked if (k.get("position") or 99) <= 10)
    return {
        "total": total,
        "covered": covered,
        "coverage_pct": round(100.0 * covered / total, 1) if total else 0.0,
        "by_city": by_city,
        "ranked_known": len(ranked),
        "top10": top10,
        "share_pct": round(100.0 * top10 / total, 1) if total and ranked else None,
        "gaps": [k["query"] for k in kws if not k.get("covered")][:40],
    }
