#!/usr/bin/env python3
"""The daily growth email: what ran, what it moved, and how far from the goals.

Deliberately blunt. If a technique did nothing, the report says it did nothing —
a growth loop that only reports good news is just a slower way of wasting money.
"""
import os
import smtplib
import statistics
from email.mime.text import MIMEText

from . import keywords, ledger, review


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def _series_summary(metric, days=14):
    pairs = ledger.series("__site__", metric)[-days:]
    if not pairs:
        return "no data"
    vals = [v for _, v in pairs]
    recent = statistics.median(vals[-7:]) if len(vals) >= 3 else vals[-1]
    prior = statistics.median(vals[-14:-7]) if len(vals) >= 10 else None
    arrow = ""
    if prior is not None:
        arrow = " ▲" if recent > prior else (" ▼" if recent < prior else " =")
    return f"{_fmt(vals[-1])} yesterday · {_fmt(recent)}/day median{arrow}"


def build_text(run_log=None, review_out=None):
    techs = ledger.load_techniques()
    goals = ledger.get_state("goals", {})
    active = [t for t in techs if t.get("status") == "active"]
    cands = [t for t in techs if t.get("status") == "candidate"]
    retired = [t for t in techs if t.get("status") == "retired"]

    L = []
    L.append("FIND A CRIB — DAILY GROWTH REPORT")
    L.append("=" * 52)
    L.append(f"{ledger.today()}")
    L.append("")

    # ---- goals
    L.append("GOALS")
    def last(metric):
        s = ledger.series("__site__", metric)
        return s[-1][1] if s else None
    subs = last("paying_subs") or 0
    mrr = last("mrr_usd") or 0
    kw = keywords.summary()
    goal_mrr = (goals.get("mrr_usd") or {}).get("target", 10000)
    goal_users = (goals.get("signups") or {}).get("target", 10000)
    L.append(f"  Revenue        ${_fmt(mrr)}/mo of ${_fmt(goal_mrr)}  ({subs} paying subscriber(s))")
    L.append(f"  Signups        {_fmt(last('accounts_with_saves'))} active of {_fmt(goal_users)} target")
    share = last("search_share_pct")
    if share is not None:
        L.append(f"  Search share   {share}% of {kw['total']} tracked queries in the top 10 "
                 f"(target 90%) · {_fmt(last('tracked_top3'))} in the top 3")
        serving = last("gsc_serving_pages")
        if serving is not None:
            L.append(f"  Indexing       {_fmt(serving)} pages earned an impression, of ~47,600 "
                     f"published — this is the ceiling on everything else")
        L.append(f"  Search traffic {_fmt(last('gsc_clicks'))} clicks / "
                 f"{_fmt(last('gsc_impressions'))} impressions (last 7d), "
                 f"avg position {last('gsc_position')}")
    else:
        L.append(f"  Search share   unmeasured — Search Console not reporting. "
                 f"Coverage proxy: {kw['coverage_pct']}% of {kw['total']} queries have a page")
    L.append("")

    # ---- the cheapest available rankings
    try:
        from . import searchconsole
        p2 = searchconsole.page2(limit=10)
        if p2:
            L.append("PAGE-2 QUERIES (rank 11-20 — cheapest wins on the board)")
            for k in p2:
                L.append(f"  pos {k['position']:>5}  {k.get('impressions', 0):>5} impr  {k['query']}")
            L.append("")
    except Exception:
        pass

    # ---- traffic
    L.append("TRAFFIC (excludes owner's own visits)")
    for m, label in (("visitors", "All visitors"), ("organic_visitors", "Organic search"),
                     ("ai_visitors", "AI answer engines"), ("direct_visitors", "Direct"),
                     ("referral_visitors", "Referral")):
        L.append(f"  {label:<20} {_series_summary(m)}")
    L.append("")

    # ---- what ran
    if run_log:
        L.append("WHAT RAN OVERNIGHT")
        for r in run_log:
            mark = "ok " if r.get("ok") else "FAIL"
            L.append(f"  [{mark}] {r['slug']:<18} {r.get('detail', '')}")
        L.append("")

    # ---- per-technique performance
    L.append(f"ACTIVE TECHNIQUES ({len(active)})")
    for t in active:
        if t.get("prefixes"):
            pairs = ledger.series(t["slug"], "owned_visitors", since=t.get("activated"))
            total = sum(v for _, v in pairs)
            recent = statistics.median([v for _, v in pairs[-7:]]) if pairs else None
            L.append(f"  {t['id']} {t['name']}")
            L.append(f"      {_fmt(total)} visitors since {t.get('activated')} "
                     f"· {_fmt(recent)}/day recent · owns {', '.join(t['prefixes'])}")
        else:
            L.append(f"  {t['id']} {t['name']}")
            L.append(f"      site-wide · judged on {t.get('metric')} · {_series_summary(t.get('metric'))}")
    L.append("")

    # ---- review decisions
    if review_out and review_out.get("actions"):
        L.append("REVIEW DECISIONS TODAY")
        for a in review_out["actions"]:
            L.append(f"  {a}")
        L.append("")

    # ---- scoreboard
    sb = review.scoreboard()
    if sb["works"] or sb["does_not_work"]:
        L.append("SCOREBOARD SO FAR")
        for r in sb["works"]:
            L.append(f"  WORKS       {r['id']} {r['name']} — {r['why']}")
        for r in sb["does_not_work"]:
            L.append(f"  DIDN'T WORK {r['id']} {r['name']} — {r['why']}")
        L.append("")

    # ---- research jobs: say plainly when they could not run. A daily job that
    # fails quietly (no key, no credit, rate limited) looks like a job with
    # nothing to report, and the difference matters.
    trouble = []
    for key, label in (("scout_last", "Scout (new techniques)"),
                       ("outreach_last", "Outreach (B2B prospects)")):
        st = ledger.get_state(key)
        if st and not st.get("ok"):
            trouble.append(f"  {label}: DID NOT RUN — {st.get('detail', 'unknown error')}")
    if trouble:
        L.append("RESEARCH JOBS BLOCKED")
        L.extend(trouble)
        L.append("")

    # ---- outreach drafts awaiting a send decision
    try:
        from . import outreach
        drafts = outreach.pending(limit=8)
    except Exception:
        drafts = []
    if drafts:
        L.append(f"OUTREACH DRAFTS AWAITING YOUR APPROVAL ({len(drafts)})")
        L.append("  (nothing is ever sent automatically — files in growth/outreach_drafts/)")
        for d in drafts:
            L.append(f"  · {d['org']} [{d.get('segment')}, confidence {d.get('confidence')}]")
            L.append(f"      {d.get('url')}")
            L.append(f"      why: {(d.get('why') or '')[:150]}")
            L.append(f"      reach via: {d.get('contact_route')}")
        L.append("")

    # ---- blocked candidates: the things needing a human
    needs_owner = [t for t in cands if t.get("notes")]
    if needs_owner:
        L.append("WAITING ON YOU")
        for t in needs_owner:
            first = (t.get("notes") or "").strip().split("\n")[0]
            L.append(f"  {t['id']} {t['name']}")
            L.append(f"      {first}")
        L.append("")

    if kw["gaps"]:
        L.append(f"UNCOVERED QUERIES ({len(kw['gaps'])} shown, drives the content roadmap)")
        for g in kw["gaps"][:12]:
            L.append(f"  · {g}")
        L.append("")

    L.append(f"Ledger: {len(techs)} techniques ({len(active)} active, "
             f"{len(cands)} candidate, {len(retired)} retired)")
    return "\n".join(L)


def email(text, to, subject=None):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASSWORD")
    if not (host and user and pw):
        raise RuntimeError("SMTP_HOST/SMTP_USER/SMTP_PASSWORD not set")
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = subject or f"Find A Crib growth — {ledger.today()}"
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pw)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    return True
