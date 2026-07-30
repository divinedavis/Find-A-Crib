#!/usr/bin/env python3
"""
Re-verify the agent re-rental pages in a real browser and record what's posted.

These pages are the most actionable thing on /marketing-agents/ and they go
stale fast: a unit posted first-come-first-served can be gone in days. This
re-renders each one, decides whether units are actually listed, and writes the
answer back into rerental_pages.json + marketing_agents.json.

A browser is not optional here. Half these sites render their listings with
JavaScript — tfc.com serves curl a "Browser Not Supported" shell, and
places.nyc/units 404s to curl but renders fine in Chromium. Raw-HTML checks
produce confident wrong answers on exactly the pages that matter most.

  python3 check_rerentals.py                 # check + report, write nothing
  python3 check_rerentals.py --apply         # also update the two JSON files
  python3 check_rerentals.py --apply --deploy    # ...and scp them to the droplet
  python3 check_rerentals.py --apply --email me@x.com   # ...and mail changes

Only mails when something changed (a page gained or lost units, or broke).
A silent week means the answer is the same as last week, which is the normal
case and not worth an inbox.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RERENTALS = os.path.join(HERE, "rerental_pages.json")
AGENTS = os.path.join(HERE, "marketing_agents.json")
DROPLET = "root@104.236.120.144:/var/www/rent-map/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MONEY = re.compile(r'\$\s?[\d,]{3,}(?:\.\d\d)?')
INCOME = re.compile(r'\bAMI\b|household|income (?:range|limit|requirement)|annual income', re.I)
UNIT = re.compile(r'\bstudio\b|\bbedroom\b|\b\d\s*BR\b|\b\d\s*bed\b', re.I)
# "6 Results", "3 units available" — a hard count when the page gives one
COUNT = re.compile(r'(\d+)\s+(?:results?|units?\s+(?:available|found)|listings?)', re.I)
# pages that explicitly say there's nothing right now
EMPTY = re.compile(r'no (?:results|units|listings|vacancies|apartments)|'
                   r'0 results|check back|currently (?:no|none)|'
                   r'nothing (?:available|posted)', re.I)


def look(page_text):
    """(units_seen, count) — count is 0 unless the page states one itself.

    Only a literal "12 results" counts as a count. Falling back to the number of
    dollar figures on the page reads plausible and is wrong: tfc.com has 164 of
    them across its whole document and nothing like 164 available units. A wrong
    number shown to a renter is worse than no number.
    """
    if EMPTY.search(page_text):
        return False, 0
    money = len(MONEY.findall(page_text))
    m = COUNT.search(page_text)
    n = int(m.group(1)) if m else 0
    # Two independent rent figures plus either income bands or unit types is
    # the pattern every real board shares. One stray "$500 fee" is not a unit.
    has = money >= 2 and (bool(INCOME.search(page_text)) or bool(UNIT.search(page_text)))
    return has, (n if has else 0)


def check(pages):
    """Delegate to rerental_daily.sweep so the public page and the daily email
    can never disagree.

    They used to. This module asked "are there PRICED units?"; the daily job
    asked "are there LISTED buildings?". Clinton Management's availabilities
    page lists six buildings with no rents on the index, so the site said empty
    while the email said six. One extractor, one answer.
    """
    sys.path.insert(0, HERE)
    import rerental_daily as rd
    out = {}
    for name, rec in rd.sweep(pages).items():
        n = max(rec["stated"], len(rec["items"]))
        out[name] = {"url": rec["url"], "status": rec["status"], "error": rec["error"],
                     "waitlist": rec["waitlist"],
                     # a waitlist page is real and worth linking, but it is not
                     # "units posted" — see rerental_daily.WAITLIST
                     "units_seen": bool(n) and not rec["waitlist"],
                     "count": rec["stated"] or n}
    return out


def diff(pages, results):
    """(changes, alive) — changes is a list of human sentences."""
    changes, alive = [], 0
    for name, rec in results.items():
        was = bool(pages[name].get("units_seen"))
        now = rec["units_seen"]
        broke = rec["error"] or (isinstance(rec["status"], int) and rec["status"] >= 400)
        if not broke:
            alive += 1
        if broke:
            changes.append(f"⚠ {name}: page is failing "
                           f"({rec['error'] or 'HTTP ' + str(rec['status'])})")
        elif now and not was:
            changes.append(f"🟢 {name}: units posted"
                           + (f" ({rec['count']})" if rec["count"] else ""))
        elif was and not now:
            changes.append(f"⚪ {name}: units gone — page is empty again")
    return changes, alive


def apply_updates(data, results, today):
    """Write results into rerental_pages.json and patch marketing_agents.json.

    A failing page keeps its previous units_seen rather than being flipped to
    false: a timeout is not evidence that the units went away, and flapping the
    public page on a network blip would be worse than being a week stale.
    """
    for name, rec in results.items():
        page = data["pages"][name]
        broke = rec["error"] or (isinstance(rec["status"], int) and rec["status"] >= 400)
        if not broke:
            page["units_seen"] = rec["units_seen"]
            if rec["count"]:
                page["unit_count"] = rec["count"]
            else:
                page.pop("unit_count", None)
        page["last_ok"] = None if broke else today
        page["broken"] = bool(broke) or None
        if page["broken"] is None:
            page.pop("broken", None)
    data["checked"] = today
    json.dump(data, open(RERENTALS, "w"), indent=1, ensure_ascii=False)

    try:
        agents = json.load(open(AGENTS))
    except FileNotFoundError:
        print("  marketing_agents.json missing — run build_marketing_agents.py first")
        return
    by_name = {a["name"]: a for a in agents["agents"]}
    n = 0
    for name, page in data["pages"].items():
        if name in by_name:
            by_name[name]["rerentals"] = dict(page, checked=today)
            n += 1
    agents["rerental_count"] = n
    json.dump(agents, open(AGENTS, "w"), indent=1, ensure_ascii=False)
    print(f"  wrote {os.path.basename(RERENTALS)} + {os.path.basename(AGENTS)} ({n} merged)")


def deploy():
    """scp to the droplet — for running this from a laptop."""
    r = subprocess.run(["scp", "-q", AGENTS, DROPLET], capture_output=True, text=True)
    if r.returncode:
        print(f"  deploy FAILED: {r.stderr.strip()[:200]}")
        return False
    print(f"  deployed marketing_agents.json -> {DROPLET}")
    return True


def write_out(outdir):
    """Copy the served JSON into a docroot — for running this ON the droplet.

    The repo copy stays the source of truth and gets committed; this is the
    file nginx actually serves.
    """
    dest = os.path.join(outdir, "marketing_agents.json")
    try:
        with open(AGENTS) as src, open(dest, "w") as dst:
            dst.write(src.read())
    except OSError as e:
        print(f"  write to {dest} FAILED: {e}")
        return False
    print(f"  wrote {dest}")
    return True


def email_changes(to, changes, results, today):
    sys.path.insert(0, HERE)
    from growth import emailkit
    live = [n for n, r in results.items() if r["units_seen"]]
    blocks = [
        {"type": "paragraph",
         "text": "What changed on the HPD agents' re-rental pages since the last check."},
        {"type": "card", "heading": "Changes", "body": "\n".join(changes)},
        {"type": "paragraph",
         "text": f"{len(live)} of {len(results)} pages are showing units right now: "
                 + (", ".join(live) if live else "none")},
    ]
    html, text = emailkit.render(
        title="Re-rental pages changed",
        eyebrow=today,
        blocks=blocks,
        cta=("Open the agent directory", "https://findacrib.com/marketing-agents/"),
        footer_note="Sent by check_rerentals.py. Only mails when something changed.",
        width=640)
    for addr in [a.strip() for a in str(to).split(",") if a.strip()]:
        emailkit.send(addr, f"Find A Crib — re-rental pages changed ({today})", html, text)
    print(f"  emailed {to}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the JSON files")
    ap.add_argument("--deploy", action="store_true", help="scp marketing_agents.json to the droplet")
    ap.add_argument("--out", help="directory to also write marketing_agents.json into "
                                  "(use the docroot when running on the droplet)")
    ap.add_argument("--email", help="mail a report, but only if something changed")
    args = ap.parse_args()

    data = json.load(open(RERENTALS))
    pages = data["pages"]
    today = datetime.date.today().isoformat()
    print(f"checking {len(pages)} re-rental pages ({today})\n")

    results = check(pages)
    for name, rec in sorted(results.items(), key=lambda kv: (not kv[1]["units_seen"], kv[0])):
        state = ("UNITS" if rec["units_seen"] else "empty") if not rec["error"] else "FAIL "
        extra = f" ({rec['count']})" if rec["count"] else ""
        print(f"  {state}{extra:<6} {name[:40]:40s} {rec['error'] or rec['status']}")

    changes, alive = diff(pages, results)
    print(f"\n{alive}/{len(pages)} pages reachable · "
          f"{sum(1 for r in results.values() if r['units_seen'])} showing units")
    if changes:
        print("\nCHANGES:")
        for c in changes:
            print("  " + c)
    else:
        print("\nno changes since last check")

    if args.apply:
        apply_updates(data, results, today)
        if args.out:
            write_out(args.out)
        if args.deploy:
            deploy()
    if args.email and changes:
        email_changes(args.email, changes, results, today)
    elif args.email:
        print("  nothing changed — no email sent")


if __name__ == "__main__":
    main()
