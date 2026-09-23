#!/usr/bin/env python3
"""Street address -> the register's BBL. Shared by every availability feed.

Lifted out of scrape_listings.py (2026-09-23) so build_vacancies.py can match
a manager's own listing to a building without importing that file's headless
browser dependencies, which only exist on the droplet. The rules are
unchanged: canonicalise "NUMBER REST", then look it up in an index built from
every address (and address range) on the DHCR register.
"""
import json
import re

SUFFIX_MAP = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "PLACE": "PL",
    "ROAD": "RD", "DRIVE": "DR", "LANE": "LN", "TERRACE": "TER",
    "COURT": "CT", "PARKWAY": "PKWY", "SQUARE": "SQ", "HEIGHTS": "HTS",
}
DIRECTION_MAP = {"WEST": "W", "EAST": "E", "NORTH": "N", "SOUTH": "S"}
SPECIAL_NAME_MAP = {
    "AVENUE OF THE AMERICAS": "6TH AVE",
    "AVE OF THE AMERICAS": "6TH AVE",
}



def normalize_addr(s: str) -> str:
    """Return canonical 'NUMBER REST' string (e.g. '246 10TH AVE')."""
    if not s:
        return ""
    s = s.upper().strip()
    # strip unit / apt
    s = re.split(r"\s+(?:#|APT|UNIT|SUITE|STE)\b", s)[0].strip()
    s = re.sub(r"[#,.;]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # special multi-word names first
    for k, v in SPECIAL_NAME_MAP.items():
        if k in s:
            s = s.replace(k, v)
    parts = s.split(" ")
    out = []
    for tok in parts:
        if tok in SUFFIX_MAP:
            out.append(SUFFIX_MAP[tok])
        elif tok in DIRECTION_MAP:
            out.append(DIRECTION_MAP[tok])
        else:
            out.append(tok)
    return " ".join(out)


def build_index(records):
    """Return dict normalized_addr -> bbl. For range-numbered DHCR rows, index every number in the range."""
    idx = {}
    for r in records:
        if r["b"] not in ("M", "Bk", "Q", "Bx", "SI"):  # all five boroughs
            continue
        for raw in (r.get("a"), r.get("address_alt")):
            if not raw:
                continue
            norm = normalize_addr(raw)
            if not norm:
                continue
            # handle range like "303 TO 309 10TH AVE"
            m = re.match(r"^(\d+)\s+TO\s+(\d+)\s+(.+)$", norm)
            if m:
                lo, hi, rest = int(m.group(1)), int(m.group(2)), m.group(3)
                step = 2 if (hi - lo) % 2 == 0 else 1
                for n in range(lo, hi + 1, step):
                    idx[f"{n} {rest}"] = r["bbl"]
            else:
                idx[norm] = r["bbl"]
    return idx
