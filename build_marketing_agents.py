#!/usr/bin/env python3
"""
Scrape HPD's Pre-Qualified List of Marketing Agents into marketing_agents.json.

These are the third-party firms NYC lets run affordable-housing lotteries: they
market the units, take the Housing Connect applications, verify income and sign
the leases. HPD updates the PQL "on a rolling basis", so re-run this now and
then and re-deploy the JSON.

  python3 build_marketing_agents.py

nyc.gov 403s a bare urllib request, so send a browser UA.
"""
import datetime
import html
import json
import re
import urllib.request

SRC = "https://www.nyc.gov/site/hpd/services-and-information/marketing-agent-pql.page"
OUT = "marketing_agents.json"
# Hand-curated re-rental listing pages, merged in on top of the scrape. HPD only
# publishes a corporate homepage, which is almost never where units get posted.
RERENTALS = "rerental_pages.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# The accordion pairs a <div class="faq-questions" data-answer="ID"> heading with
# a <div class="faq-answers" id="ID"> body.
Q_RE = re.compile(r'<div class="faq-questions" data-answer="([^"]+)">(.*?)</div>', re.S)
# The last answer isn't followed by another faq- block, so also stop at the
# close of the accordion container.
A_RE = re.compile(r'<div class="faq-answers" id="([^"]+)">(.*?)</div>\s*'
                  r'(?=<div class="faq-|</div>)', re.S)
FIELD_RE = re.compile(r'<strong>\s*(Contact|Email|Phone|Address)\s*</strong>\s*:?\s*(.*?)'
                      r'(?=<br|<strong>|</p>)', re.S | re.I)
SITE_RE = re.compile(r'<a href="([^"]+)"[^>]*>\s*(?:Website|Web site|website)\s*</a>', re.I)


def text(fragment):
    """HTML fragment -> single-line plain text."""
    s = re.sub(r'(?is)<(script|style).*?</\1>', ' ', fragment)
    s = re.sub(r'(?i)<br\s*/?>', ' ', s)
    s = re.sub(r'(?i)</p>', ' ', s)
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()


def paragraphs(fragment):
    """The blurb paragraphs of an answer body, minus the contact block."""
    out = []
    for p in re.findall(r'(?is)<p[^>]*>(.*?)</p>', fragment):
        if re.search(r'<strong>\s*(Contact|Email|Phone|Address)', p, re.I):
            continue
        t = text(p)
        if t and t.lower() not in ("website",):
            out.append(t)
    return out


# Tags we can derive from the agent's own self-description. HPD doesn't publish
# these as structured fields, so the blurb is the only signal available.
TAGS = [
    ("MWBE", r'\bM/?WBE\b|minority[- ]and[- ]wom[ae]n|women?[- ]owned|minority[- ]owned|'
             r'woman[- ]owned|MBE\b|WBE\b'),
    ("Nonprofit", r'\b501\s?\(?c\)?\s?\(?3\)?|not[- ]for[- ]profit|non[- ]?profit'),
    ("Administering agent", r'administ(?:e|ra)ring agent|administrative agent'),
    ("Property management", r'property manage|management compan|manages? (?:over|more than)?\s*[\d,]+ (?:units|apartments)'),
    ("Sales / homeownership", r'\bhomeownership\b|\bco-?op\b|\bcondo(?:minium)?\b|sales and leasing|\bHDFC\b'),
    ("LIHTC", r'\bLIHTC\b|low[- ]income housing tax credit'),
    ("421-a / IH", r'\b421-?a\b|\b485-?x\b|inclusionary'),
]


def tags_for(blurb):
    found = [name for name, pat in TAGS if re.search(pat, blurb, re.I)]
    return found


def agency_for(blurb):
    """Which agencies the firm says approved it."""
    hpd = bool(re.search(r'\bHPD\b', blurb, re.I))
    hdc = bool(re.search(r'\bHDC\b', blurb, re.I))
    if hpd and hdc:
        return "HPD + HDC"
    if hdc:
        return "HDC"
    return "HPD"  # everyone on this list is on HPD's PQL by definition


def main():
    req = urllib.request.Request(SRC, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")

    answers = dict(A_RE.findall(page))
    agents = []
    for aid, qfrag in Q_RE.findall(page):
        name = text(qfrag).rstrip(",").strip()
        body = answers.get(aid, "")
        if not name:
            continue

        fields = {k.lower(): text(v) for k, v in FIELD_RE.findall(body)}
        site = SITE_RE.search(body)
        blurb = " ".join(paragraphs(body))

        agents.append({
            "name": name,
            "contact": fields.get("contact", ""),
            "email": fields.get("email", ""),
            "phone": fields.get("phone", ""),
            "address": fields.get("address", ""),
            "website": site.group(1) if site else "",
            "agency": agency_for(blurb),
            "tags": tags_for(blurb),
            "about": blurb,
        })

    if len(agents) < 20:
        raise SystemExit(f"only parsed {len(agents)} agents — the PQL page layout "
                         f"probably changed, refusing to overwrite {OUT}")

    # Merge the curated re-rental pages. Match on the exact PQL name; if HPD
    # renames a firm the entry stops matching, so warn loudly rather than
    # silently dropping a link.
    try:
        rr = json.load(open(RERENTALS))
    except FileNotFoundError:
        rr = {"pages": {}, "checked": None}
    pages = rr.get("pages", {})
    by_name = {a["name"]: a for a in agents}
    for name, page in pages.items():
        if name in by_name:
            by_name[name]["rerentals"] = dict(page, checked=rr.get("checked"))
        else:
            print(f"  ⚠ re-rental entry has no matching agent: {name!r}")
    matched = sum(1 for a in agents if a.get("rerentals"))

    agents.sort(key=lambda a: re.sub(r'^[^A-Za-z]+', '', a["name"]).lower() or a["name"].lower())
    json.dump({"source": SRC,
               "fetched": datetime.date.today().isoformat(),
               "count": len(agents),
               "rerental_count": matched,
               "agents": agents},
              open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"wrote {OUT}: {len(agents)} marketing agents, "
          f"{matched} with a re-rental listing page")


if __name__ == "__main__":
    main()
