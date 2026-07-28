#!/usr/bin/env python3
"""The daily growth email: what ran, what it moved, and how far from the goals.

Deliberately blunt. If a technique did nothing, the report says it did nothing —
a growth loop that only reports good news is just a slower way of wasting money.

The report is described as emailkit blocks, never as markup, and emailkit
renders the HTML and the plain-text alternative from the same block list. That
is the reason there is no second text builder here: two builders drift, and the
text part is the one a screen reader and a spam filter actually read.
"""
import datetime
import statistics

from . import emailkit, keywords, ledger, review

# Pages published across NYC/SF/LA/DC. The gap between this and the pages that
# have ever earned an impression is the single biggest number in the report.
PUBLISHED_PAGES = 47600
DASHBOARD = "https://findacrib.com/dashboard"


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def _money(v):
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _pct(part, whole):
    try:
        return max(0.0, min(100.0, 100.0 * float(part) / float(whole)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _last(metric):
    s = ledger.series("__site__", metric)
    return s[-1][1] if s else None


def _trend(metric, days=14):
    """(yesterday, 7-day median, arrow, tone). Tone is about direction, not
    politeness — a fall in traffic is red even on a report you wrote yourself."""
    pairs = ledger.series("__site__", metric)[-days:] if metric else []
    if not pairs:
        return None, None, "", "mute"
    vals = [v for _, v in pairs]
    recent = statistics.median(vals[-7:]) if len(vals) >= 3 else vals[-1]
    prior = statistics.median(vals[-14:-7]) if len(vals) >= 10 else None
    if prior is None:
        return vals[-1], recent, "", "mute"
    if recent > prior:
        return vals[-1], recent, "▲", "good"
    if recent < prior:
        return vals[-1], recent, "▼", "bad"
    return vals[-1], recent, "=", "mute"


def _pretty_date(iso):
    try:
        return datetime.date.fromisoformat(str(iso)).strftime("%A, %B %d, %Y")
    except ValueError:
        return str(iso)


# ------------------------------------------------------------------- blocks

def build_blocks(run_log=None, review_out=None):
    techs = ledger.load_techniques()
    goals = ledger.get_state("goals", {})
    active = [t for t in techs if t.get("status") == "active"]
    cands = [t for t in techs if t.get("status") == "candidate"]
    retired = [t for t in techs if t.get("status") == "retired"]
    kw = keywords.summary()

    B = []

    # ---- the four numbers worth reading on a phone lock screen
    subs = _last("paying_subs") or 0
    mrr = _last("mrr_usd") or 0
    signups = _last("accounts_with_saves")
    goal_mrr = (goals.get("mrr_usd") or {}).get("target", 10000)
    goal_users = (goals.get("signups") or {}).get("target", 10000)
    v_last, v_med, v_arrow, v_tone = _trend("visitors")
    o_last, o_med, o_arrow, o_tone = _trend("organic_visitors")
    B.append({"type": "tiles", "items": [
        {"label": "Visitors yesterday", "value": _fmt(v_last),
         "delta": f"{v_arrow} {_fmt(v_med)}/day median".strip(), "tone": v_tone},
        {"label": "Organic search", "value": _fmt(o_last),
         "delta": f"{o_arrow} {_fmt(o_med)}/day median".strip(), "tone": o_tone},
        {"label": "Active signups", "value": _fmt(signups),
         "delta": f"of {_fmt(goal_users)} target"},
        {"label": "Revenue", "value": f"{_money(mrr)}/mo",
         "delta": f"{subs} paying subscriber(s)", "tone": "good" if subs else "mute"},
    ]})

    # ---- goals, as distance-to-target rather than a bare number
    share = _last("search_share_pct")
    B.append({"type": "section", "label": "Goals"})
    B.append({"type": "progress", "label": "Revenue",
              "value": f"{_money(mrr)} / {_money(goal_mrr)}",
              "sub": f"{subs} paying subscriber(s)",
              "pct": _pct(mrr, goal_mrr), "tone": "good" if mrr else "info"})
    B.append({"type": "progress", "label": "Signups",
              "value": f"{_fmt(signups)} / {_fmt(goal_users)}",
              "sub": "accounts that have saved at least one building",
              "pct": _pct(signups, goal_users)})
    if share is not None:
        B.append({"type": "progress", "label": "Search share",
                  "value": f"{share}% / 90%",
                  "sub": f"{_fmt(_last('tracked_top3'))} of {kw['total']} tracked queries "
                         f"in the top 3",
                  "pct": _pct(share, 90)})
        serving = _last("gsc_serving_pages")
        if serving is not None:
            indexed_pct = _pct(serving, PUBLISHED_PAGES)
            B.append({"type": "progress", "label": "Indexing",
                      "value": f"{_fmt(serving)} / ~{PUBLISHED_PAGES:,} pages",
                      "sub": "pages that have earned an impression — this is the ceiling "
                             "on everything else",
                      "pct": indexed_pct, "tone": "bad" if indexed_pct < 5 else "info"})
        # Three loose numbers, not a table — four header cells collide at phone
        # width and a one-row table is a table for no reason.
        B.append({"type": "stats", "items": [
            (_fmt(_last("gsc_clicks")), "clicks, last 7d"),
            (_fmt(_last("gsc_impressions")), "impressions"),
            (_fmt(_last("gsc_position")), "avg position")]})
    else:
        B.append({"type": "callout", "tone": "warn", "heading": "Search share unmeasured",
                  "body": f"Search Console is not reporting. Coverage proxy: "
                          f"{kw['coverage_pct']}% of {kw['total']} tracked queries have a page."})

    # ---- the cheapest available rankings
    try:
        from . import searchconsole
        p2 = searchconsole.page2(limit=10)
    except Exception:
        p2 = None
    if p2:
        B.append({"type": "section", "label": "Page-2 queries",
                  "note": "Ranked 11–20 — the cheapest wins on the board"})
        B.append({"type": "table", "cols": ["Query", "Position", "Impressions"],
                  "align": ["left", "right", "right"], "mono": True, "widths": [56, 20, 24],
                  "rows": [[k["query"], (f"{k['position']}", "warn"),
                            _fmt(k.get("impressions", 0))] for k in p2]})

    # ---- traffic
    B.append({"type": "section", "label": "Traffic",
              "note": "Excludes the owner's own visits"})
    rows = []
    for m, label in (("visitors", "All visitors"), ("organic_visitors", "Organic search"),
                     ("ai_visitors", "AI answer engines"), ("direct_visitors", "Direct"),
                     ("referral_visitors", "Referral")):
        last, med, arrow, tone = _trend(m)
        # The arrow rides on the median rather than taking a fourth column —
        # four columns do not fit a phone, and the arrow is about the median.
        rows.append([label, _fmt(last), {"text": f"{arrow} {_fmt(med)}".strip(), "tone": tone}])
    B.append({"type": "table", "cols": ["Source", "Yesterday", "Median/day"],
              "align": ["left", "right", "right"], "mono": True, "rows": rows})

    # ---- what ran
    if run_log:
        failed = sum(1 for r in run_log if not r.get("ok"))
        B.append({"type": "section", "label": "What ran overnight",
                  "note": f"{len(run_log)} jobs · "
                          + (f"{failed} failed" if failed else "all clear")})
        B.append({"type": "status", "items": [
            {"ok": bool(r.get("ok")), "name": r["slug"], "detail": r.get("detail", "")}
            for r in run_log]})

    # ---- per-technique performance
    B.append({"type": "section", "label": f"Active techniques ({len(active)})"})
    rows = []
    for t in active:
        if t.get("prefixes"):
            pairs = ledger.series(t["slug"], "owned_visitors", since=t.get("activated"))
            total = sum(v for _, v in pairs)
            recent = statistics.median([v for _, v in pairs[-7:]]) if pairs else None
            rows.append([{"text": f"{t['id']} {t['name']}",
                          "sub": f"owns {', '.join(t['prefixes'])} · since {t.get('activated')}"},
                         _fmt(total), _fmt(recent)])
        else:
            last, med, _arrow, _tone = _trend(t.get("metric"))
            rows.append([{"text": f"{t['id']} {t['name']}",
                          "sub": f"site-wide · judged on {t.get('metric')}"},
                         _fmt(last), _fmt(med)])
    if rows:
        B.append({"type": "table", "cols": ["Technique", "Total", "Recent/day"],
                  "align": ["left", "right", "right"], "widths": [58, 20, 22], "rows": rows})

    # ---- scheduled second looks. The 21-day review asks "is this dead?"; this
    # asks "is this still the best version of the idea, or should it be replaced?"
    revisits = ledger.revisit_due()
    if revisits:
        B.append({"type": "section", "label": f"Due for revisit ({len(revisits)})",
                  "note": "Decide keep / change / replace"})
        for t in revisits:
            meta = f"scheduled {t.get('revisit_on')}"
            if t.get("prefixes"):
                pairs = ledger.series(t["slug"], "owned_visitors", since=t.get("activated"))
                meta += (f" · {sum(v for _, v in pairs):,} owned visitors "
                         f"since {t.get('activated')}")
            B.append({"type": "card", "heading": f"{t['id']} {t['name']}", "meta": meta,
                      "body": f"Hypothesis was: {(t.get('hypothesis') or '')[:200]}"})

    # ---- review decisions
    if review_out and review_out.get("actions"):
        B.append({"type": "section", "label": "Review decisions today"})
        B.append({"type": "chips", "items": review_out["actions"]})

    # ---- scoreboard
    sb = review.scoreboard()
    if sb["works"] or sb["does_not_work"]:
        B.append({"type": "section", "label": "Scoreboard so far"})
        B.append({"type": "table", "cols": ["Verdict", "Technique", "Why"],
                  "align": ["left", "left", "left"],
                  "rows": [[("WORKS", "good"), f"{r['id']} {r['name']}", r["why"]]
                           for r in sb["works"]]
                          + [[("DIDN'T WORK", "bad"), f"{r['id']} {r['name']}", r["why"]]
                             for r in sb["does_not_work"]]})

    # ---- research jobs: say plainly when they could not run. A daily job that
    # fails quietly (no key, no credit, rate limited) looks like a job with
    # nothing to report, and the difference matters.
    trouble = []
    for key, label in (("scout_last", "Scout (new techniques)"),
                       ("outreach_last", "Outreach (B2B prospects)")):
        st = ledger.get_state(key)
        # `is False` on purpose, not falsiness. Failure paths always write an
        # explicit ok=False with a detail; a record missing the key entirely is
        # an older or partial write, and reporting that as a failure with
        # "unknown error" is a false alarm — which is exactly what happened.
        if st and st.get("ok") is False:
            trouble.append((label, st.get("detail", "unknown error")))
    if trouble:
        B.append({"type": "section", "label": "Research jobs blocked"})
        for label, detail in trouble:
            B.append({"type": "callout", "tone": "bad", "heading": f"{label} did not run",
                      "body": detail})

    # ---- outreach drafts awaiting a send decision
    try:
        from . import outreach
        drafts = outreach.pending(limit=8)
    except Exception:
        drafts = []
    if drafts:
        B.append({"type": "section",
                  "label": f"Outreach drafts awaiting approval ({len(drafts)})",
                  "note": "Nothing is ever sent automatically — files in "
                          "growth/outreach_drafts/"})
        for d in drafts:
            B.append({"type": "card", "heading": d["org"],
                      "meta": f"{d.get('segment')} · confidence {d.get('confidence')} · "
                              f"reach via {d.get('contact_route')}",
                      "body": (d.get("why") or "")[:200],
                      "link": ("Open site", d["url"]) if d.get("url") else None})

    # ---- blocked candidates: the things needing a human
    needs_owner = [t for t in cands if t.get("notes")]
    if needs_owner:
        B.append({"type": "section", "label": "Waiting on you",
                  "note": "These candidates cannot activate without a decision"})
        for t in needs_owner:
            B.append({"type": "callout", "tone": "warn",
                      "heading": f"{t['id']} {t['name']}",
                      "body": (t.get("notes") or "").strip().split("\n")[0]})

    if kw["gaps"]:
        B.append({"type": "section", "label": f"Uncovered queries ({len(kw['gaps'])})",
                  "note": "Drives the content roadmap"})
        B.append({"type": "chips", "items": kw["gaps"][:12]})

    B.append({"type": "note",
              "text": f"Ledger: {len(techs)} techniques — {len(active)} active, "
                      f"{len(cands)} candidate, {len(retired)} retired."})
    return B


def build(run_log=None, review_out=None):
    """(subject, html, text) for the day's report."""
    day = ledger.today()
    html, text = emailkit.render(
        title="Daily growth report",
        eyebrow=_pretty_date(day),
        blocks=build_blocks(run_log=run_log, review_out=review_out),
        cta=("Open the dashboard", DASHBOARD),
        footer_note="Sent by the Find A Crib growth engine. Traffic numbers exclude the "
                    "owner's own visits.",
        width=640)
    return f"Find A Crib growth — {day}", html, text


def build_text(run_log=None, review_out=None):
    """The plain-text rendering — what prints to the console and what goes in
    the text/plain part of the message."""
    return build(run_log=run_log, review_out=review_out)[2]


def email(to, run_log=None, review_out=None, prebuilt=None):
    """Send the report. `prebuilt` reuses a (subject, html, text) already built
    for the console, so one run never reads the ledger twice."""
    subject, html, text = prebuilt or build(run_log=run_log, review_out=review_out)
    for addr in [a.strip() for a in str(to).split(",") if a.strip()]:
        emailkit.send(addr, subject, html, text)
    return True
