"""Which apartment sizes a listing states, as numbers the alerts can filter on.

Sizes are 0 (studio) to 4, where 4 means four bedrooms or more: the same
buckets as the Beds row in the app's Lotteries filter (LotteryFeed.bedsMatch).

2026-11-24: the owner picked "1" under Beds and was still sent a studio. The
choice only filtered the list on the phone; the alerts never heard about it,
and a re-rental found by an intraday sweep carried no size anyway. This module
is the one place that turns what a source prints into sizes, for both the
sweep (rerental_daily) and the sender (lottery_alerts).

The rule everywhere: None means "the source did not say", and a listing that
did not say is never hidden from anyone. Reading too few sizes off a card is
the dangerous mistake (someone misses a home that fits), so lists and ranges
are read whole: "Studio, 1 & 2 Bedrooms" is three sizes, "1-3 BR" is three.
"""
import re

TOP = 4                      # "4" stands for four or more
_ONE = r'(?:studio|\d)'
_SEP = r'\s*(?:,|&|/|\band\b|\bor\b|\bto\b|-|–|—)\s*'
_RUN = rf'{_ONE}(?:{_SEP}{_ONE})*'
_WORD = r'(?:bed(?:room)?s?|bdrms?|bds?|brs?)'
# "2 bedroom", "2-Bed", "1BR", "4+ bedrooms", "Studio, 1 & 2 Bedrooms", "1-3 beds"
_BEFORE = re.compile(rf'(?<![\w$.,])({_RUN})\s*\+?\s*-?\s*{_WORD}\b', re.I)
# "Bedrooms: 2", "Beds: Studio - 2"
_AFTER = re.compile(rf'\bbed(?:room)?s?\s*:\s*({_RUN})(?![\w.,]*\d)', re.I)
# "Unit Size: 0", "Unit Size: studio", "Unit Size: 0 - 2" (Tax Solute)
_UNIT_SIZE = re.compile(rf'\bunit size:\s*({_RUN})\s*$', re.I)
# A bare "Studio" at a line start or after a separator ("1-Bedroom, Studio"),
# so a building's "yoga studio" is not an apartment size.
_STUDIO = re.compile(r'(?:^|[:|•–,&/-]\s*|\b(?:and|or)\s+)studios?\b(?!\s+(?:space|room|class|gym))', re.I)
_RANGE = re.compile(r'^(?:\bto\b|-|–|—)$', re.I)


def _n(tok):
    return 0 if tok.lower() == "studio" else int(tok)


def _run_sizes(run):
    """"studio, 1 & 2" -> {0, 1, 2}; "1-3" -> {1, 2, 3}."""
    parts = [p for p in re.split(rf'({_SEP})', run) if p]
    out, prev = set(), None
    for i, p in enumerate(parts):
        if not re.fullmatch(_ONE, p.strip(), re.I):
            continue
        n = _n(p.strip())
        sep = parts[i - 1].strip() if i else ""
        if prev is not None and _RANGE.match(sep) and prev < n:
            out.update(range(prev, n + 1))
        out.add(n)
        prev = n
    return out


def bucket(sizes):
    """Sorted, with everything from four bedrooms up folded into 4."""
    return sorted({min(int(s), TOP) for s in sizes if 0 <= int(s) <= 9})


def sizes_in(lines):
    """The sizes a card's own text states, or None when it states none."""
    if isinstance(lines, str):
        lines = lines.split("\n")
    found = set()
    for line in lines:
        line = re.sub(r'\s+', ' ', str(line or "")).strip()
        if not line:
            continue
        for rx in (_BEFORE, _AFTER, _UNIT_SIZE):
            for m in rx.finditer(line):
                found |= _run_sizes(m.group(1))
        if _STUDIO.search(line):
            found.add(0)
    return bucket(found) or None


def sizes_of(value):
    """Sizes from a feed's own field: ["Studio", "2-bed"], "studio", "2", 3, [0, 1]."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    vals = value if isinstance(value, (list, tuple, set)) else [value]
    found = set()
    for v in vals:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            found.add(int(v))
            continue
        t = str(v).strip().lower()
        if t.startswith("studio"):
            found.add(0)
        else:
            m = re.match(r'(\d+)', t)
            if m:
                found.add(int(m.group(1)))
    return bucket(found) or None


def wanted(value):
    """A subscriber's stored choice as a set, empty when they chose nothing."""
    try:
        return set(bucket(value or []))
    except (TypeError, ValueError):
        return set()


def fits(want, sizes):
    """False only when the listing states its sizes and none is one they want."""
    want = wanted(want)
    if not want or not sizes:
        return True
    return bool(want & set(bucket(sizes)))


def words(want):
    """"studios", "1-bedrooms", "studios and 1-bedrooms", "3-bedrooms and 4+ bedrooms"."""
    names = ["studios" if s == 0 else "4+ bedrooms" if s == TOP else f"{s}-bedrooms" for s in sorted(wanted(want))]
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
