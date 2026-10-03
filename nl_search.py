"""Plain-language search: "2 bed under $2,500 near Prospect Park, no violations"
-> the same filters the map's controls set (2026-10-03, Find A Crib Plus).

Two layers, cheapest first:
  1. Rules read everything definite — prices, bedrooms, boroughs, exact
     neighborhood names, "no violations", "section 8", "available now". Free.
  2. Jev (TypeSafe) is asked only when the text points somewhere the rules
     cannot place ("near prospect park", "by the water in queens"): one
     Choice over the city's neighborhoods, keeping up to three it gives real
     weight. ~3k input tokens, about $0.0002 a search.
"""
import re

BOROUGHS = {"manhattan": "M", "brooklyn": "Bk", "bk": "Bk", "queens": "Q", "bronx": "Bx",
            "the bronx": "Bx", "staten island": "SI", "si": "SI"}
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
PLACE_HINT = re.compile(r"\b(near|by|close to|around|next to|walking distance|off the|on the|in)\b")


def _money(s):
    s = s.lower().replace(",", "").replace("$", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(k)?", s)
    if not m:
        return None
    v = float(m.group(1)) * (1000 if m.group(2) else 1)
    if v < 100:           # "3" in "under 3" means $3k on a rent search
        v *= 1000
    return int(v)


def aliases(names_with_boroughs):
    """Lowercase alias -> set of official neighborhood names. The city's NTA
    names are like "Astoria (Central)" or "Bedford-Stuyvesant (East)", so a
    person typing "astoria" or "bed stuy" means every one of them."""
    out = {}
    def add(k, n):
        k = re.sub(r"\s+", " ", k.lower().replace("-", " ")).strip()
        if len(k) >= 4:
            out.setdefault(k, set()).add(n)
    for n, _b in names_with_boroughs:
        add(n, n)
        base = re.sub(r"\s*\(.*?\)", "", n)
        add(base, n)
        for part in re.split(r"-|/|,", base):
            if len(part.strip()) >= 5:
                add(part, n)
    for short, full in {"bed stuy": "bedford stuyvesant", "lic": "long island city", "les": "lower east side",
                        "ues": "upper east side", "uws": "upper west side", "fidi": "financial district",
                        "wburg": "williamsburg", "crown hts": "crown heights"}.items():
        if full in out:
            out[short] = out[full]
    return out


def parse_rules(text, neighborhoods):
    """Definite filters from the text. `neighborhoods` maps a lowercase alias
    to a set of official neighborhood names (see `aliases`). Returns
    (filters, explain, rest)."""
    t = " " + text.lower().strip() + " "
    f = {"boroughs": [], "nbs": [], "pmin": None, "pmax": None, "beds": [], "listed": None, "s8": None, "viol": None}
    explain = []
    amt = r"\$?\s?\d[\d,]*(?:\.\d+)?\s?k?"
    m = re.search(rf"(?:between|from)\s+({amt})\s+(?:and|to|-)\s+({amt})", t) or re.search(rf"({amt})\s*(?:-|–|to)\s*({amt})", t)
    if m and _money(m.group(1)) and _money(m.group(2)):
        f["pmin"], f["pmax"] = sorted([_money(m.group(1)), _money(m.group(2))])
        t = t.replace(m.group(0), " ")
    for pat, key in [(rf"(?:under|below|less than|max(?:imum)?|up to|no more than|cheaper than|<)\s*({amt})", "pmax"),
                     (rf"(?:over|above|more than|at least|min(?:imum)?|>)\s*({amt})", "pmin")]:
        m = re.search(pat, t)
        if m and _money(m.group(1)):
            f[key] = _money(m.group(1)); t = t.replace(m.group(0), " ")
    if f["pmax"] is None and f["pmin"] is None:
        m = re.search(r"\$\s?\d[\d,]*k?|\b\d{1,2}(?:\.\d)?k\b|\b[1-9]\d{3}\b(?=\s*(?:/\s*mo|a month|per month|month|rent|\s|$))", t)
        if m and _money(m.group(0)) and 500 <= _money(m.group(0)) <= 20000:
            f["pmax"] = _money(m.group(0)); t = t.replace(m.group(0), " ")
    if re.search(r"\bstudios?\b", t):
        f["beds"].append(0); t = re.sub(r"\bstudios?\b", " ", t)
    for m in re.finditer(r"\b(\d|one|two|three|four|five)\s*-?\s*(?:br|bd|bed(?:room)?s?|b/r)\b", t):
        n = WORDS.get(m.group(1)) or int(m.group(1))
        f["beds"].append(min(n, 4))
    t = re.sub(r"\b(\d|one|two|three|four|five)\s*-?\s*(?:br|bd|bed(?:room)?s?|b/r)\b", " ", t)
    if re.search(r"\b(no|zero|without|clean of)\s+(open\s+)?violations?\b|\bno violations\b|\bclean building\b", t):
        f["viol"] = "none"; t = re.sub(r"\b(no|zero|without|clean of)\s+(open\s+)?violations?\b|\bclean building\b", " ", t)
    if re.search(r"\bsection\s*8\b|\bvouchers?\b|\bcityfheps\b|\bhasa\b", t):
        f["s8"] = "either"; t = re.sub(r"\bsection\s*8\b|\bvouchers?\b|\bcityfheps\b|\bhasa\b", " ", t)
    if re.search(r"\b(available|for rent|listed|open now|right now|move in)\b", t):
        f["listed"] = "yes"
    tt = t.replace("-", " ")
    for name in sorted(neighborhoods, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", tt):
            for n in sorted(neighborhoods[name]):
                if n not in f["nbs"]:
                    f["nbs"].append(n)
            tt = re.sub(rf"\b{re.escape(name)}\b", " ", tt)
    t = tt
    for name, code in sorted(BOROUGHS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(name)}\b", t) and code not in f["boroughs"]:
            f["boroughs"].append(code); t = re.sub(rf"\b{re.escape(name)}\b", " ", t)
    f["beds"] = sorted(set(f["beds"]))
    if f["pmin"] or f["pmax"]:
        explain.append(("$%s" % format(f["pmin"], ",") if f["pmin"] else "any") + "–" + ("$%s" % format(f["pmax"], ",") if f["pmax"] else "any"))
    if f["beds"]:
        explain.append("/".join("studio" if b == 0 else f"{b} bd" for b in f["beds"]))
    nb_label = [re.sub(r"\s*\(.*?\)", "", n) for n in f["nbs"]]
    explain += list(dict.fromkeys(nb_label)) + [{"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens", "Bx": "Bronx", "SI": "Staten Island"}[b] for b in f["boroughs"]]
    if f["viol"]:
        explain.append("no open violations")
    if f["s8"]:
        explain.append("vouchers")
    if f["listed"]:
        explain.append("available now")
    rest = re.sub(r"\s+", " ", re.sub(r"[^a-z' ]", " ", t)).strip()
    return f, explain, rest


def needs_place(rest, f):
    """Does what is left still name a place the rules could not resolve?"""
    if f["nbs"]:
        return False
    words = [w for w in rest.split() if len(w) > 2 and w not in {"apartment", "apartments", "apt", "apts", "the", "and",
             "with", "for", "rent", "cheap", "nice", "good", "want", "looking", "something", "place", "home", "unit",
             "month", "need", "find", "show", "any", "that", "has", "have", "big", "small", "quiet", "safe"}]
    return bool(words) and bool(PLACE_HINT.search(" " + rest + " ") or len(words) >= 2)


def jev_places(client, text, pairs, boroughs, Choice):
    """Up to three neighborhoods Jev gives real weight to for `text`.
    `pairs` is [(official name, borough code)]."""
    pool = [(n, b) for n, b in pairs if not boroughs or b in boroughs]
    if not pool:
        return [], 0
    criteria = {f"n{i}": f"{n} ({ {'M': 'Manhattan', 'Bk': 'Brooklyn', 'Q': 'Queens', 'Bx': 'Bronx', 'SI': 'Staten Island'}.get(b, b) })"
                for i, (n, b) in enumerate(pool)}
    criteria["none"] = "No particular neighborhood is named or implied"
    r = client.system_one(state=f'An apartment search typed by a New York renter: "{text}"',
                          questions={"area": Choice(instructions="Which New York neighborhood is the renter asking to live in or near?",
                                                    criteria=criteria)})
    probs = r.answers["area"].probabilities
    picks = [k for k, p in sorted(probs.items(), key=lambda kv: -kv[1]) if k != "none" and p >= 0.15][:3]
    return [pool[int(k[1:])][0] for k in picks], r.usage.input_tokens
