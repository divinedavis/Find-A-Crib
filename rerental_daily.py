#!/usr/bin/env python3
"""
Daily sweep of the 14 agent re-rental pages -> an emailed digest.

check_rerentals.py answers "is this page still real?" for the public site. This
answers the question you actually care about every morning: what showed up
overnight. It renders each page, fingerprints the listings, diffs against
yesterday's snapshot, and mails the difference in the same format as the growth
report.

  python3 rerental_daily.py                        # print the report
  python3 rerental_daily.py --email me@x.com       # ...and send it
  python3 rerental_daily.py --email me@x.com --quiet-if-same
                                                   # send only when something moved

Two kinds of page live in this list and the report keeps them apart:
  * unit boards   - specific apartments with rents (Affordable for NY, MGNY, ...)
  * waitlists     - buildings taking applications, no per-unit rent
                    (TF Cornerstone, Wavecrest)
Counting a waitlist's marketing copy as "units" is how you get a report that
says 164 apartments are available at TF Cornerstone. There are none; there is a
wait list.
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RERENTALS = os.path.join(HERE, "rerental_pages.json")
HISTORY = os.path.join(HERE, "rerental_history.json")
SITE = "https://findacrib.com/marketing-agents/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Pages that take applications for a building rather than listing priced units.
# Extracting "rents" from these yields the surrounding marketing copy.
WAITLIST = {"TF Cornerstone", "The Wavecrest Management Team Ltd.", "Restored Homes"}

MONEY = re.compile(r'\$\s?[\d,]+(?:\.\d\d)?')
COUNT = re.compile(r'(\d+)\s+(?:results?|units?\s+(?:available|found)|listings?)', re.I)
EMPTY = re.compile(r'no (?:results|units|listings|vacancies|apartments)|0 results|'
                   r'check back|currently (?:no|none)|nothing (?:available|posted)', re.I)
ADDR = re.compile(r'^\s*\d{1,5}(?:[-–]\d{1,4})?\s+[A-Za-z0-9.\'&\- ]{2,60}?'
                  r'(?:street|st|avenue|ave|road|rd|boulevard|blvd|place|pl|drive|dr|'
                  r'lane|ln|court|ct|parkway|pkwy|terrace|way|plaza|broadway)\b\.?',
                  re.I)


DIRS = {"w": "west", "e": "east", "n": "north", "s": "south"}
STREET = re.compile(r'\b(street|st|avenue|ave|road|rd|boulevard|blvd|place|pl|drive|dr|'
                    r'lane|ln|court|ct|parkway|pkwy|terrace|way|plaza)\b\.?', re.I)


def key_of(label):
    """Collapse the many spellings of one building into a single key.

    Sites print the same address two or three ways on one page — '211 W. 29th
    St' next to '211 West 29th Street, New York, NY 10001', or the building name
    above its postal address. Without this, one listing counts as two and shows
    up as 'new' the day a site changes its formatting.
    """
    s = label.lower()
    s = re.sub(r',.*$', '', s)                        # drop city/state/zip tail
    s = re.sub(r'\b(apartments?|apt|unit\(?s?\)?|available|floor|fl)\b', ' ', s)
    s = re.sub(r'\b\d{4}\b', ' ', s)                  # posting codes like 0726
    s = STREET.sub(' ', s)                            # street-type is noise once parsed
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    parts = []
    for p in s.split():
        p = DIRS.get(p, p)                            # w -> west
        p = re.sub(r'^(\d+)(st|nd|rd|th)$', r'\1', p)  # 29th -> 29
        parts.append(p)
    return " ".join(parts[:3]) if parts else s


def listings_from(text, waitlist, own_office=None):
    """(items, stated_count). items are display labels, deduped by key_of.

    `own_office` is the agent's own address from the HPD list. Every one of
    these sites puts it in the footer, where it reads exactly like a listing —
    Housing Partnership's '253 West 35th Street' and MHANY's '470 Vanderbilt
    Avenue' were both being counted as available apartments.
    """
    if EMPTY.search(text):
        return [], 0
    m = COUNT.search(text)
    stated = int(m.group(1)) if m else 0
    # Match the office on house-number + street only. The HPD record carries a
    # suite ("481 Wythe Ave Unit 101") that the site's footer omits ("481 Wythe
    # Ave"), so a whole-key comparison misses it and the office lands in the
    # listings. Two tokens is enough to identify a building.
    def stem(k):
        return " ".join(k.split()[:2])
    skip = {stem(key_of(own_office))} if own_office else set()
    items, seen = [], set()
    for line in (l.strip() for l in text.split("\n")):
        if not line or len(line) > 90:
            continue
        if not ADDR.match(line):
            continue
        k = key_of(line)
        if not k or k in seen or stem(k) in skip:
            continue
        seen.add(k)
        items.append({"key": k, "label": re.sub(r'\s+', ' ', line)[:64]})
    if waitlist:
        # buildings, not units - a stated "N results" would be about something else
        stated = 0
    return items, stated


def offices():
    """agent name -> their own office address, so it can be filtered out."""
    try:
        agents = json.load(open(os.path.join(HERE, "marketing_agents.json")))["agents"]
    except (FileNotFoundError, ValueError, KeyError):
        return {}
    return {a["name"]: a.get("address", "") for a in agents}


def sweep(pages):
    from playwright.sync_api import sync_playwright
    own = offices()
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 1600}, user_agent=UA)
        for name, meta in pages.items():
            rec = {"url": meta["url"], "status": None, "error": None,
                   "items": [], "stated": 0, "waitlist": name in WAITLIST}
            page = ctx.new_page()
            try:
                resp = page.goto(meta["url"], wait_until="domcontentloaded", timeout=35000)
                rec["status"] = resp.status if resp else None
                page.wait_for_timeout(3500)
                # several of these lazy-load the listing grid on scroll
                for _ in range(5):
                    page.mouse.wheel(0, 1600)
                    page.wait_for_timeout(700)
                page.wait_for_timeout(1500)
                text = page.evaluate("document.body ? document.body.innerText : ''")
                rec["items"], rec["stated"] = listings_from(
                    text, rec["waitlist"], own.get(name))
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {str(e)[:60]}"
            finally:
                try: page.close()
                except Exception: pass
            out[name] = rec
        browser.close()
    return out


def load_history():
    try:
        return json.load(open(HISTORY))
    except (FileNotFoundError, ValueError):
        return {"last": {}, "date": None}


def diff(prev, results):
    """Per agent: which listing keys are new, which disappeared."""
    d = {}
    for name, rec in results.items():
        if rec["error"]:
            d[name] = {"new": [], "gone": [], "failed": True}
            continue
        before = set(prev.get(name, []))
        now = {i["key"] for i in rec["items"]}
        label = {i["key"]: i["label"] for i in rec["items"]}
        d[name] = {"new": [label[k] for k in now - before] if before else [],
                   "gone": sorted(before - now) if before else [],
                   "failed": False,
                   "first_seen": not before}
    return d


def build_report(results, deltas, today, had_history):
    live = {n: r for n, r in results.items()
            if not r["error"] and (r["items"] or r["stated"])}
    boards = {n: r for n, r in live.items() if not r["waitlist"]}
    total_units = sum(max(r["stated"], len(r["items"])) for r in boards.values())
    new_total = sum(len(d["new"]) for d in deltas.values())
    failed = [n for n, r in results.items() if r["error"]]

    tiles = [
        {"label": "Pages with listings", "value": f"{len(live)}/{len(results)}",
         "tone": "good" if live else "warn"},
        {"label": "Units on unit boards", "value": str(total_units)},
        {"label": "New since yesterday",
         "value": ("—" if not had_history else str(new_total)),
         "tone": "good" if new_total else "mute"},
        {"label": "Pages failing", "value": str(len(failed)),
         "tone": "bad" if failed else "mute"},
    ]

    rows = []
    for name, rec in sorted(results.items(),
                            key=lambda kv: (kv[1]["waitlist"],
                                            -max(kv[1]["stated"], len(kv[1]["items"])),
                                            kv[0])):
        if rec["error"]:
            state = "failed"
        elif rec["waitlist"]:
            state = "waitlist" + (f" · {len(rec['items'])} bldg" if rec["items"] else "")
        else:
            n = max(rec["stated"], len(rec["items"]))
            state = f"{n} unit{'s' if n != 1 else ''}" if n else "empty"
        d = deltas.get(name, {})
        moved = ""
        if d.get("new"):
            moved = f"+{len(d['new'])}"
        elif d.get("gone"):
            moved = f"-{len(d['gone'])}"
        rows.append([name[:34], state, moved])

    blocks = [{"type": "tiles", "items": tiles},
              {"type": "section", "label": "Every page",
               "note": "Unit boards first, then building waitlists."},
              {"type": "table", "cols": ["Agent", "Listed", "Δ"], "rows": rows,
               "align": ["left", "left", "right"], "widths": ["58%", "27%", "15%"]}]

    if new_total:
        lines = []
        for name, d in deltas.items():
            for label in d["new"]:
                lines.append(f"{name}: {label}")
        blocks.insert(1, {"type": "callout", "tone": "good",
                          "heading": f"{new_total} new listing{'s' if new_total != 1 else ''}",
                          "body": "\n".join(lines[:20])})
    elif had_history:
        blocks.insert(1, {"type": "callout", "tone": "mute",
                          "heading": "Nothing new overnight",
                          "body": "Same listings as yesterday. These pages are "
                                  "first-come, first-served, so a quiet day is normal."})

    if failed:
        blocks.append({"type": "callout", "tone": "bad",
                       "heading": f"{len(failed)} page could not be loaded"
                                  if len(failed) == 1 else
                                  f"{len(failed)} pages could not be loaded",
                       "body": "\n".join(f"{n}: {results[n]['error']}" for n in failed)})

    blocks.append({"type": "note",
                   "text": "Counts come from each site. Waitlist pages (TF Cornerstone, "
                           "Wavecrest, Restored Homes) take applications for a building "
                           "rather than listing priced units, so they are not counted as "
                           "units. Listing detection is best-effort — always open the page "
                           "before acting."})
    return blocks, new_total, failed


def to_text(results, deltas, today, new_total, failed):
    out = [f"RE-RENTAL SWEEP — {today}", ""]
    for name, rec in sorted(results.items()):
        if rec["error"]:
            out.append(f"  FAIL   {name[:38]:38s} {rec['error']}")
        else:
            n = max(rec["stated"], len(rec["items"]))
            kind = "waitlist" if rec["waitlist"] else (f"{n} units" if n else "empty")
            d = deltas.get(name, {})
            mark = f"  (+{len(d['new'])} new)" if d.get("new") else ""
            out.append(f"  {kind:12s} {name[:38]:38s}{mark}")
    out += ["", f"new since yesterday: {new_total}", f"failing: {len(failed)}"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", help="comma-separated recipients")
    ap.add_argument("--quiet-if-same", action="store_true",
                    help="only send when something changed or broke")
    args = ap.parse_args()

    pages = json.load(open(RERENTALS))["pages"]
    today = datetime.date.today().isoformat()
    hist = load_history()
    had_history = bool(hist.get("last"))

    results = sweep(pages)
    deltas = diff(hist.get("last", {}), results)
    blocks, new_total, failed = build_report(results, deltas, today, had_history)
    text = to_text(results, deltas, today, new_total, failed)
    print(text)

    # snapshot for tomorrow — only for pages that loaded, so a failed fetch
    # doesn't erase yesterday's listings and re-announce them all as "new"
    snap = dict(hist.get("last", {}))
    for name, rec in results.items():
        if not rec["error"]:
            snap[name] = [i["key"] for i in rec["items"]]
    json.dump({"last": snap, "date": today}, open(HISTORY, "w"), indent=1)

    if not args.email:
        return
    if args.quiet_if_same and had_history and not new_total and not failed:
        print("\nnothing moved — no email sent")
        return

    sys.path.insert(0, HERE)
    from growth import emailkit
    subject = (f"Find A Crib re-rentals — {new_total} new" if new_total
               else f"Find A Crib re-rentals — {today}")
    html, txt = emailkit.render(
        title="Re-rental sweep",
        eyebrow=today,
        blocks=blocks,
        cta=("Open the agent directory", SITE),
        footer_note="Sent by rerental_daily.py. Covers the HPD marketing agents "
                    "that publish a re-rental page.",
        width=640)
    for addr in [a.strip() for a in args.email.split(",") if a.strip()]:
        emailkit.send(addr, subject, html, txt)
    print(f"\nemailed {args.email}")


if __name__ == "__main__":
    main()
