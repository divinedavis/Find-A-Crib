#!/usr/bin/env python3
"""One-time paid Building Report.

The free building page already publishes the raw numbers — "192 open violations,
511 total". What it never says is what that *means*, who is behind it, or what
to do next. Selling a copy of free data would be a bad product and a dishonest
one; this sells the three things the free page deliberately does not have:

  1. Benchmark      192 open violations is meaningless until you know the median
                    stabilized building has 25, and this one sits in the worst
                    8% of Brooklyn. That comparison needs the whole 47k corpus,
                    which is the one asset a prospective tenant cannot assemble.
  2. Who + what else Owner, managing agent and head officer, plus every OTHER
                    building the same owner runs and their combined record.
  3. What to do      A pre-filled DHCR rent-history request — the single action
                    that actually establishes whether you are being overcharged
                    — plus the complaint routes, with the deadlines spelled out.

Written for the moment someone is about to sign a lease, so it is blunt about
risk and equally blunt about what the data cannot tell them.

    python3 building_report.py --bbl 3051620020 --out /tmp/r.html
"""
import argparse
import datetime
import json
import os
import statistics

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
SITE = "https://findacrib.com"

BORO_NAME = {"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens",
             "Bx": "the Bronx", "SI": "Staten Island"}
BORO_SLUG = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens",
             "Bx": "bronx", "SI": "staten-island"}


def esc(s):
    return (str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def titlecase(a):
    return " ".join(w.capitalize() if not w.isdigit() else w for w in str(a or "").split())


def _open_violations(b):
    return ((b.get("h") or {}).get("violations") or {}).get("open") or 0


# --------------------------------------------------------------- benchmarking

class Corpus:
    """The 47k-building comparison set. Loaded once; percentiles precomputed."""

    def __init__(self, buildings):
        self.buildings = buildings
        self.by_bbl = {str(b["bbl"]): b for b in buildings}
        self._by_boro = {}
        self._by_nb = {}
        for b in buildings:
            if not (b.get("h") or {}).get("violations"):
                continue
            self._by_boro.setdefault(b.get("b"), []).append(_open_violations(b))
            key = (b.get("b"), b.get("nb"))
            self._by_nb.setdefault(key, []).append(_open_violations(b))
        self._sorted = {k: sorted(v) for k, v in self._by_boro.items()}
        self._sorted_nb = {k: sorted(v) for k, v in self._by_nb.items()}
        self._all = sorted(_open_violations(b) for b in buildings
                           if (b.get("h") or {}).get("violations"))

    @staticmethod
    def _pct_worse_than(sorted_vals, v):
        """What share of the set has FEWER open violations than v (0-100)."""
        if not sorted_vals:
            return None
        import bisect
        return round(100.0 * bisect.bisect_left(sorted_vals, v) / len(sorted_vals))

    def rank(self, b):
        v = _open_violations(b)
        boro = self._sorted.get(b.get("b"), [])
        nb = self._sorted_nb.get((b.get("b"), b.get("nb")), [])
        return {
            "open": v,
            "city_pct": self._pct_worse_than(self._all, v),
            "boro_pct": self._pct_worse_than(boro, v),
            "nb_pct": self._pct_worse_than(nb, v),
            "city_median": int(statistics.median(self._all)) if self._all else None,
            "boro_median": int(statistics.median(boro)) if boro else None,
            "nb_median": int(statistics.median(nb)) if nb else None,
            "nb_count": len(nb),
        }

    def per_unit(self, b):
        """Violations per apartment — the comparison that survives building size."""
        u = b.get("u") or 0
        if not u:
            return None
        return round(_open_violations(b) / u, 2)


def verdict(rank, per_unit):
    """Plain-English risk read. Deliberately hedged: violations are a signal
    about management, not a prediction about a specific apartment."""
    p = rank.get("boro_pct")
    if p is None:
        return ("unknown", "There isn't enough comparable data to place this building.")
    if p >= 90:
        return ("poor", "This building is among the worst 10% in its borough for open "
                        "violations. That is a strong signal of deferred maintenance and a "
                        "landlord who does not close things out.")
    if p >= 70:
        return ("below average", "This building carries more open violations than about "
                                 f"{p}% of stabilized buildings in its borough. Worth asking "
                                 "pointed questions before you sign.")
    if p >= 40:
        return ("typical", "This building sits near the middle of the pack for its borough. "
                           "Not a red flag on its own.")
    return ("better than most", "This building has fewer open violations than most stabilized "
                                "buildings in its borough — a reasonable sign of upkeep.")


# ------------------------------------------------------------------ portfolio

def _name(field):
    """HPD contacts arrive as {name, type, address} or as a bare string."""
    if isinstance(field, dict):
        return (field.get("name") or "").strip()
    return str(field or "").strip()


def _addr_of(field):
    return (field.get("address") or "").strip() if isinstance(field, dict) else ""


def portfolio(corpus, contacts, bbl):
    """Every other building run by the same owner, with their combined record.

    Matching is by normalized owner name, which is the only join the public data
    supports. It is imperfect — an owner using two spellings reads as two
    owners — so the report says so rather than implying a complete picture.
    """
    me = contacts.get(str(bbl)) or {}
    owner = _name(me.get("owner"))
    if not owner:
        return None
    key = " ".join(owner.lower().split())
    peers = [b for b, c in contacts.items()
             if " ".join(_name(c.get("owner")).lower().split()) == key and str(b) != str(bbl)]
    rows = []
    for pb in peers:
        b = corpus.by_bbl.get(str(pb))
        if b:
            rows.append(b)
    rows.sort(key=_open_violations, reverse=True)
    return {
        "owner": owner,
        "owner_addr": _addr_of(me.get("owner")),
        "manager": _name(me.get("manager")),
        "manager_addr": _addr_of(me.get("manager")),
        "officer": _name(me.get("officer")),
        "count": len(rows),
        "total_open": sum(_open_violations(b) for b in rows),
        "total_units": sum(b.get("u") or 0 for b in rows),
        "worst": rows[:12],
    }


# --------------------------------------------------------------------- render

CSS = """
:root{--ink:#111;--ink2:#5a5f6a;--line:#e2e5ec;--bg:#fff;--accent:#1a56db;
      --bad:#b42318;--warn:#b54708;--ok:#136c3a}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     color:var(--ink);background:#f6f7f9}
.wrap{max-width:760px;margin:0 auto;padding:28px 22px 60px;background:#fff}
h1{font-size:27px;line-height:1.2;margin:.1em 0 .1em}
h2{font-size:19px;margin:1.9em 0 .5em;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:1.3em 0 .3em}
.meta{color:var(--ink2);font-size:14px;margin-bottom:20px}
.verdict{border-radius:12px;padding:16px 18px;margin:18px 0;border:1px solid var(--line)}
.verdict.poor{background:#fef3f2;border-color:#fda29b}
.verdict.below.average{background:#fffaeb;border-color:#fec84b}
.verdict.typical{background:#f8f9fc}
.verdict.better.than.most{background:#f0fdf4;border-color:#a6f4c5}
.verdict b{display:block;font-size:17px;margin-bottom:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.stat{border:1px solid var(--line);border-radius:10px;padding:11px 13px}
.stat b{display:block;font-size:23px;line-height:1.15}
.stat span{color:var(--ink2);font-size:12.5px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--ink2);font-weight:600;background:#fbfcfd}
a{color:var(--accent)}
.bar{height:9px;background:#eef0f4;border-radius:99px;overflow:hidden;margin:7px 0 3px}
.bar i{display:block;height:100%;background:var(--accent)}
.bar.poor i{background:var(--bad)}
.note{background:#f8f9fc;border:1px solid var(--line);border-radius:10px;padding:13px 15px;
      font-size:14px;color:var(--ink2);margin:14px 0}
.letter{border:1px solid var(--line);border-radius:10px;padding:16px 18px;background:#fcfcfd;
        font:14px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}
ol li,ul li{margin:.35em 0}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
      color:var(--ink2);font-size:12.5px}
@media print{body{background:#fff}.wrap{max-width:none;padding:0}.noprint{display:none}}
"""


def _stat(v, label):
    return f"<div class='stat'><b>{v}</b><span>{esc(label)}</span></div>"


def render(bbl, corpus, contacts, s8=None, listed=False):
    b = corpus.by_bbl.get(str(bbl))
    if not b:
        raise KeyError(f"BBL {bbl} is not in the rent-stabilized dataset")

    addr = titlecase(b.get("a"))
    boro = BORO_NAME.get(b.get("b"), "")
    nb = b.get("nb") or ""
    r = corpus.rank(b)
    pu = corpus.per_unit(b)
    v = (b.get("h") or {}).get("violations") or {}
    c = (b.get("h") or {}).get("complaints") or {}
    grade, why = verdict(r, pu)
    pf = portfolio(corpus, contacts, bbl)
    today = datetime.date.today().isoformat()

    # ---- header + verdict
    out = [f"<h1>{esc(addr)}</h1>",
           f"<div class='meta'>{esc(nb)}, {esc(boro)} {esc(b.get('z') or '')} · BBL {esc(b['bbl'])} · "
           f"{b.get('u') or '—'} apartments · built {b.get('yr') or '—'} · report generated {today}</div>"]

    out.append(f"<div class='verdict {esc(grade)}'><b>Condition: {esc(grade)}</b>{esc(why)}</div>")

    # The class counts (a/b/c) cover every violation ever recorded, not the open
    # subset — HPD's feed does not publish status broken down by class, and we
    # do not hold it. Labelling "class C" next to "open" would read as 172 open
    # hazards when it means 172 on record, which is exactly the kind of scare a
    # paid report must not manufacture.
    out.append("<div class='grid'>"
               + _stat(f"{v.get('open', 0):,}", "open HPD violations")
               + _stat(f"{pu if pu is not None else '—'}", "open violations per apartment")
               + _stat(f"{v.get('last_12mo', 0):,}", "new violations, last 12 months")
               + _stat(f"{v.get('c', 0):,}", "class C ever recorded (not necessarily open)")
               + "</div>")

    # ---- benchmark
    out.append("<h2>1. How this compares</h2>")
    out.append("<p>A violation count means nothing on its own. Here is where this building "
               "sits against every other DHCR-registered rent-stabilized building we track.</p>")
    rows = []
    for label, pct, med, n in (
            (f"{nb}, {boro}", r["nb_pct"], r["nb_median"], r["nb_count"]),
            (boro, r["boro_pct"], r["boro_median"], None),
            ("All five boroughs", r["city_pct"], r["city_median"], len(corpus._all))):
        if pct is None:
            continue
        cls = " poor" if pct >= 90 else ""
        rows.append(
            f"<tr><td>{esc(label)}{f' ({n:,} buildings)' if n else ''}</td>"
            f"<td>{med:,}</td>"
            f"<td><div class='bar{cls}'><i style='width:{max(1, min(100, pct))}%'></i></div>"
            f"worse than {pct}% of them</td></tr>")
    out.append("<table><tr><th>Compared with</th><th>Median open violations</th>"
               f"<th>This building ({r['open']:,} open)</th></tr>{''.join(rows)}</table>")

    out.append("<div class='note'><b>What the classes mean.</b> "
               "<b>Class C</b> is immediately hazardous — no heat, no hot water, lead paint, "
               "vermin — and the landlord has 24 hours to start work. <b>Class B</b> is "
               "hazardous, 30 days. <b>Class A</b> is non-hazardous, 90 days. An old open "
               "class C is the single strongest sign that a landlord ignores orders.</div>")

    out.append("<table>"
               "<tr><th>Record</th><th>Open</th><th>Total ever</th><th>Last 12 months</th></tr>"
               f"<tr><td>HPD violations</td><td>{v.get('open', 0):,}</td>"
               f"<td>{v.get('total', 0):,}</td><td>{v.get('last_12mo', 0):,}</td></tr>"
               f"<tr><td>HPD complaints</td><td>{c.get('open', 0):,}</td>"
               f"<td>{c.get('total', 0):,}</td><td>{c.get('last_12mo', 0):,}</td></tr>"
               f"<tr><td>By class, all time</td><td colspan='3'>A: {v.get('a', 0):,} · "
               f"B: {v.get('b', 0):,} · C: {v.get('c', 0):,} "
               f"<span style='color:#5a5f6a'>(of {v.get('total', 0):,} ever recorded — HPD does "
               f"not publish the open/closed split by class, so we do not claim one)</span>"
               f"</td></tr></table>")

    # ---- who runs it
    out.append("<h2>2. Who runs this building</h2>")
    if pf:
        out.append("<table>"
                   + (f"<tr><th>Registered owner</th><td>{esc(pf['owner'])}"
                      + (f"<br><span style='color:#5a5f6a;font-size:13px'>{esc(pf['owner_addr'])}</span>"
                         if pf['owner_addr'] else "") + "</td></tr>" if pf['owner'] else "")
                   + (f"<tr><th>Managing agent</th><td>{esc(pf['manager'])}"
                      + (f"<br><span style='color:#5a5f6a;font-size:13px'>{esc(pf['manager_addr'])}</span>"
                         if pf['manager_addr'] else "") + "</td></tr>" if pf['manager'] else "")
                   + (f"<tr><th>Head officer</th><td>{esc(pf['officer'])}</td></tr>" if pf['officer'] else "")
                   + f"<tr><th>Last HPD registration</th><td>{esc((b.get('h') or {}).get('lastregistration') or '—')}</td></tr>"
                   + "</table>")
        if pf["count"]:
            out.append(f"<h3>The same owner is registered on {pf['count']:,} other "
                       f"rent-stabilized building{'s' if pf['count'] != 1 else ''}</h3>")
            out.append("<div class='grid'>"
                       + _stat(f"{pf['count']:,}", "other buildings")
                       + _stat(f"{pf['total_open']:,}", "their combined open violations")
                       + _stat(f"{pf['total_units']:,}", "apartments under this owner")
                       + "</div>")
            prows = "".join(
                f"<tr><td><a href='{SITE}/building/{BORO_SLUG.get(x.get('b'), 'nyc')}/"
                f"{'-'.join(str(titlecase(x.get('a'))).lower().split())}-{x['bbl']}/'>"
                f"{esc(titlecase(x.get('a')))}</a></td>"
                f"<td>{esc(BORO_NAME.get(x.get('b'), ''))}</td>"
                f"<td>{x.get('u') or '—'}</td><td>{_open_violations(x):,}</td></tr>"
                for x in pf["worst"])
            out.append("<table><tr><th>Building</th><th>Borough</th><th>Apartments</th>"
                       f"<th>Open violations</th></tr>{prows}</table>")
            if pf["count"] > len(pf["worst"]):
                out.append(f"<p style='font-size:14px;color:#5a5f6a'>Showing the "
                           f"{len(pf['worst'])} with the most open violations, of {pf['count']:,}.</p>")
            out.append("<div class='note'>Portfolios are matched on the registered owner name "
                       "exactly as HPD holds it. An owner who registers under two spellings, or "
                       "through separate LLCs per building — which is common — will look smaller "
                       "here than they are. Treat this as a floor, not a complete picture.</div>")
    else:
        out.append("<p>HPD has no current registration contact on file for this building. That "
                   "is itself worth noting: registration is required annually, and a lapsed one "
                   "often means an owner who is hard to reach when something breaks.</p>")

    # ---- voucher / listing context
    extras = []
    if s8:
        extras.append("This building appears in HPD or HUD subsidized-housing records, so some "
                      "units may be income-restricted.")
    if listed:
        extras.append("An apartment here was advertised recently, so the landlord is actively "
                      "renting.")
    if extras:
        out.append("<h2>3. Other signals</h2><ul>"
                   + "".join(f"<li>{esc(e)}</li>" for e in extras) + "</ul>")

    # ---- the action pack
    n = "4" if extras else "3"
    out.append(f"<h2>{n}. What to do before you sign</h2>")
    out.append("<p>If this apartment is rent stabilized, the legal rent is whatever DHCR has on "
               "record — not whatever the lease says. The only way to know is to ask DHCR for "
               "the rent history. It is <b>free</b>, and you are entitled to the history for "
               "your own apartment.</p>")
    out.append("<ol>"
               "<li><b>Request the rent history.</b> Email the letter below to "
               "<a href='mailto:rentinfo@hcr.ny.gov'>rentinfo@hcr.ny.gov</a>, or call the DHCR "
               "Rent Info Line on <b>(718) 739-6400</b>. Ask for the full registration history, "
               "not just the current year.</li>"
               "<li><b>Compare it to the rent you were quoted.</b> Large unexplained jumps "
               "between tenants are the classic overcharge pattern, often justified by "
               "individual apartment improvements that may never have happened.</li>"
               "<li><b>If it looks wrong, file an overcharge complaint</b> (DHCR form RA-89). "
               "Overcharge awards can be trebled where the overcharge was wilful. Do not sit on "
               "it — the lookback period is limited, so time matters.</li>"
               "<li><b>Check open violations yourself</b> on "
               "<a href='https://hpdonline.nyc.gov/'>HPD Online</a>, and put anything the "
               "landlord promises to fix in writing in the lease rider.</li>"
               "</ol>")

    out.append("<h3>Copy this — pre-filled for your building</h3>")
    letter = (
        f"To: NYS Homes and Community Renewal, Office of Rent Administration\n"
        f"Subject: Rent registration history request — {addr}, Apt ____\n\n"
        f"To whom it may concern,\n\n"
        f"I am requesting the complete rent registration history for:\n\n"
        f"    Address:   {addr}, {nb}, {boro}, NY {b.get('z') or ''}\n"
        f"    BBL:       {b['bbl']}\n"
        f"    Apartment: ____________\n\n"
        f"I am the current or prospective tenant of this apartment. Please send the full\n"
        f"registration history for all years available, including the registered legal\n"
        f"regulated rent and any preferential rent recorded for each year.\n\n"
        f"Name:            ____________________\n"
        f"Contact address: ____________________\n"
        f"Phone / email:   ____________________\n\n"
        f"Thank you.\n")
    out.append(f"<div class='letter'>{esc(letter)}</div>")

    # ---- limits
    out.append("<h2>What this report cannot tell you</h2>")
    out.append("<ul>"
               "<li><b>Whether your specific apartment is stabilized.</b> Registration is at the "
               "building level. Individual units can be deregulated. Only the DHCR rent history "
               "for your unit settles it.</li>"
               "<li><b>What the legal rent is.</b> New York does not publish per-unit registered "
               "rents. That is exactly why step 1 above exists.</li>"
               "<li><b>Current conditions.</b> Violation records lag, and an open violation may "
               "already be fixed but not yet closed out — or closed on paper and not in reality.</li>"
               "<li><b>Which of the open violations are the dangerous ones.</b> HPD publishes the "
               "class breakdown across all violations ever recorded, not across the currently "
               "open ones, so nobody can honestly tell you how many open class C hazards this "
               "building has. Look the building up on HPD Online for the live, itemised list.</li>"
               "<li><b>Anything about the landlord's intentions.</b> This is a record of the "
               "building, not a prediction about your tenancy.</li>"
               "</ul>")

    out.append("<div class='foot'>Sources: NY State DHCR rent-stabilized building registrations "
               "(2024 files); NYC HPD Open Data — property registrations, registration contacts, "
               "violations and complaints; NYC PLUTO. Compiled by Find A Crib. This report is "
               f"information, not legal advice. Generated {today} · "
               f"<a href='{SITE}/'>findacrib.com</a></div>")

    body = "\n".join(out)
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Building report — {esc(addr)}, {esc(boro)}</title>
<meta name="robots" content="noindex,nofollow">
<style>{CSS}</style></head><body><div class="wrap">{body}</div></body></html>"""


# ----------------------------------------------------------------------- CLI

def load_corpus(data_dir=None):
    d = data_dir or DATA_DIR
    with open(os.path.join(d, "buildings.min.json")) as f:
        return Corpus(json.load(f))


def load_contacts(path=None):
    """bbl -> {owner, manager, officer}. Falls back to an empty map so a report
    can still be produced without the contacts file."""
    p = path or os.path.join(DATA_DIR, "hpd_contacts.json")
    try:
        with open(p) as f:
            raw = json.load(f)
    except Exception:
        return {}
    if isinstance(raw, list):
        return {str(r["bbl"]): r for r in raw if r.get("bbl")}
    return {str(k): v for k, v in raw.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bbl", required=True)
    ap.add_argument("--out", help="write HTML here (default: stdout)")
    ap.add_argument("--data-dir", default=DATA_DIR)
    args = ap.parse_args()

    corpus = load_corpus(args.data_dir)
    contacts = load_contacts(os.path.join(args.data_dir, "hpd_contacts.json"))
    html = render(args.bbl, corpus, contacts)
    if args.out:
        with open(args.out, "w") as f:
            f.write(html)
        print(f"wrote {args.out} ({len(html):,} bytes)")
    else:
        print(html)


if __name__ == "__main__":
    main()
