"""Move-in deals a marketing agent prints on a re-rental's own listing:
months free, a smaller security deposit, fees cut, a gift card.

Owner, 2026-10-27: "deploy it for all management companies that provide this
data, if they dont provide data for us to use then obviously dont fill in this
table". So this only ever reports what the page says in so many words — no
deal is guessed, and a page that names none gets no box. An ordinary
"security deposit: one month's rent" is the law, not a deal, and never counts.

find_deal(text) -> {"perks": [{"kind", "title", "detail"}], "free_on_12": n,
"quote": "..."} or None. free_on_12 is the months free on a one-year lease,
when the page ties a number to that lease; the tiles use it for the
"≈ $X/mo over the lease" line and print nothing without it.
"""
import re

WORDS = {"a": 1, "an": 1, "one": 1, "first": 1, "two": 2, "three": 3, "four": 4,
         "half a": 0.5, "half an": 0.5}
N = r"(?:\d+(?:\.\d+)?|one|two|three|four|first|half an?|an?)"

FREE = re.compile(rf"\b({N})\s*(?:\(\d\)\s*)?(?:full\s+)?months?['’]?\s*(?:of\s+)?(?:free|rent[- ]free)\b(?:\s+rent)?"
                  r"(?=(?P<tail>[^.;!◄►•\n]{0,48}))", re.I)
FREE_MONTH = re.compile(rf"\b({N})\s+free\s+months?\b(?=(?P<tail>[^.;!◄►•\n]{{0,48}}))", re.I)
LEASE = re.compile(r"\b(?:on|with|for)\s+(?:an?|any|the|either\s+a)?\s*(\d+|one|two|three)\s*-?\s*(?:(?:year|yr)s?\s*)?"
                   r"(?:(?:or|/|&|and)\s*(\d+|two|three)\s*-?\s*)?(year|yr|month)s?\s*-?\s*lease", re.I)
DEP_OFF = re.compile(r"\$\s?([\d,]{3,6})\s+off\s+(?:the\s+|your\s+)?security\s+deposit", re.I)
DEP_FLAT = re.compile(r"\$\s?([\d,]{3,6})\s+security\s+deposit(?=(?P<tail>[^.;!\n]{0,40}))", re.I)
DEP_NONE = re.compile(r"\b(?:no|zero|\$0)\s+security\s+deposit\b|\bsecurity\s+deposit\s+(?:is\s+)?waived\b", re.I)
DEP_REDUCED = re.compile(r"\b(?:reduced|half(?:\s+a)?(?:[- ]month)?)\s+security\s+deposit\b", re.I)
FEES = re.compile(r"\b(\d{2,3})\s?%\s+off\s+(?:the\s+)?(amenit(?:y|ies)|amenity)\s+fees?(?=(?P<tail>[^.;!\n]{0,40}))", re.I)
FEES_WAIVED = re.compile(r"\b(?:no|waived?|free)\s+amenity\s+fees?\b|\bamenity\s+fees?\s+(?:is\s+|are\s+)?waived\b", re.I)
GIFT = re.compile(r"\$\s?([\d,]{2,5})\s+(?:visa\s+|amazon\s+)?gift\s+card", re.I)
# "no months free", "not eligible for ... free" — a page saying there is none.
NEGATED = re.compile(r"\b(?:no|not|without|excludes?|ineligible)\b[^.]{0,20}$", re.I)
FIRST_YEAR = re.compile(r"\b(?:1st|first)\s+(?:lease\s+)?year\b", re.I)
ANY_UNIT = re.compile(r"regardless of (?:the\s+)?unit|any unit|all units", re.I)


def _n(s):
    s = s.lower().strip()
    v = WORDS[s] if s in WORDS else float(s)
    return int(v) if float(v).is_integer() else v


def _months(v):
    v = int(v) if float(v).is_integer() else v
    return f"{v} month{'' if v == 1 else 's'}"


def _lease(m):
    """'1- or 2-year lease' / '1-year lease' / '18-month lease' from a LEASE match."""
    if not m:
        return None, []
    a, b, unit = m.group(1), m.group(2), m.group(3).lower()
    unit = "year" if unit in ("year", "yr") else "month"
    nums = [int(_n(x)) for x in (a, b) if x]
    if len(nums) == 2:
        return f"{nums[0]}- or {nums[1]}-{unit} lease", [(x * 12 if unit == "year" else x) for x in nums]
    return f"{nums[0]}-{unit} lease", [nums[0] * 12 if unit == "year" else nums[0]]


def _clean(text):
    return re.sub(r"\s+", " ", text or "")


def find_deal(text):
    t = _clean(text)
    if not t:
        return None
    perks, quotes = [], []

    # Months free, each with the lease it rides on when the page names one.
    offers = []                                    # (months, lease text, lease lengths in months)
    for rx in (FREE, FREE_MONTH):
        for m in rx.finditer(t):
            if NEGATED.search(t[max(0, m.start() - 30):m.start()]):
                continue
            try:
                n = _n(m.group(1))
            except ValueError:
                continue
            if not n or n > 4:
                continue
            desc, lengths = _lease(LEASE.search(m.group("tail")))
            if (n, desc) not in [(o[0], o[1]) for o in offers]:
                offers.append((n, desc, lengths))
                quotes.append((m.group(0) + " " + (lm.group(0) if (lm := LEASE.search(m.group("tail"))) else "")).strip())
    if offers:
        top = max(o[0] for o in offers)
        if len({o[0] for o in offers}) > 1:
            title = f"Up to {_months(top)} free"
            # Short, so the line fits beside its title on a phone:
            # "1 mo on 1-yr, 2 on 2-yr".
            parts = []
            for i, (n, d, _) in enumerate(sorted(offers)):
                short = d.replace("-year lease", "-yr").replace("-month lease", "-mo").replace(" or ", "/") if d else None
                parts.append(f"{n}{' mo' if i == 0 else ''}" + (f" on {short}" if short else ""))
            detail = ", ".join(parts)
        else:
            title = f"{_months(top)} free"
            descs = [d for _, d, _ in offers if d]
            detail = f"On a {descs[0]}" if descs else None
        perks.append({"kind": "free", "title": title, "detail": detail})
    free_on_12 = None
    for n, _, lengths in offers:
        if 12 in lengths:
            free_on_12 = n if free_on_12 is None else min(free_on_12, n)

    # Security deposit: only an amount or wording that marks it as a deal.
    m = DEP_OFF.search(t)
    if m:
        perks.append({"kind": "deposit", "title": f"${m.group(1)} off the security deposit",
                      "detail": "Any unit size" if ANY_UNIT.search(t[m.end():m.end() + 50]) else None})
        quotes.append(m.group(0))
    elif (m := DEP_FLAT.search(t)) and (ANY_UNIT.search(m.group("tail")) or re.search(r"\bonly\b|\bjust\b", t[max(0, m.start() - 12):m.start()], re.I)):
        perks.append({"kind": "deposit", "title": f"${m.group(1)} security deposit",
                      "detail": "Any unit size" if ANY_UNIT.search(m.group("tail")) else None})
        quotes.append(m.group(0).strip())
    elif (m := DEP_NONE.search(t)):
        perks.append({"kind": "deposit", "title": "No security deposit", "detail": None})
        quotes.append(m.group(0))
    elif (m := DEP_REDUCED.search(t)):
        perks.append({"kind": "deposit", "title": "Reduced security deposit", "detail": None})
        quotes.append(m.group(0))

    m = FEES.search(t)
    if m:
        perks.append({"kind": "fees", "title": f"{m.group(1)}% off amenity fees",
                      "detail": "First lease year" if FIRST_YEAR.search(m.group("tail")) else None})
        quotes.append(m.group(0).strip())
    elif (m := FEES_WAIVED.search(t)):
        perks.append({"kind": "fees", "title": "No amenity fee", "detail": None})
        quotes.append(m.group(0))

    m = GIFT.search(t)
    if m:
        perks.append({"kind": "gift", "title": f"${m.group(1)} gift card", "detail": None})
        quotes.append(m.group(0))

    if not perks:
        return None
    return {"perks": perks, "free_on_12": free_on_12, "quote": " · ".join(quotes)[:300]}


def attach(records):
    """records' deal_src (the listing page's text) and _card -> rec["deal"].

    The listing page says the most; the board card is the fallback for
    agents with no page per apartment (K&G's vacancies board). A deal that
    reads the same on three or more of one agent's listings is the site's
    banner or footer, not this apartment's offer, and is dropped.
    """
    for r in records:
        d = find_deal(r.pop("deal_src", "") or "") or find_deal(" \n".join(r.get("_card") or []))
        if d:
            r["deal"] = d
    seen = {}
    for r in records:
        if r.get("deal"):
            seen.setdefault((r["agent"], r["deal"]["quote"]), []).append(r)
    for rs in seen.values():
        if len(rs) >= 3:
            for r in rs:
                r.pop("deal")
    return sum(1 for r in records if r.get("deal"))
