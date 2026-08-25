#!/usr/bin/env python3
"""The daily review: keep what works, retire what doesn't, drop what's redundant.

This is the half of the loop that makes it self-improving rather than merely
automated. Every day it re-reads the measured series behind each active
technique and asks three questions:

  1. Has it had a fair run?      (below GRACE_DAYS, nothing is judged — SEO
                                  changes take weeks to show up in a series)
  2. Did it earn its traffic?    (owned visitors since activation vs threshold)
  3. If not, is it invisible or  (owned Search Console impressions — the
     merely un-clicked?           leading indicator; see MIN_OWNED_IMPRESSIONS)
  4. Is it redundant?            (another technique owns overlapping URLs and
                                  massively outperforms it)

Retiring is cheap and reversible: status flips to "retired", the driver stops
running it tomorrow, and the verdict stays in the ledger forever so the same
idea does not get re-proposed as if it were new.

A verdict is TRI-STATE, and the third state is the important one. Until
2026-08-25 every path that did not retire wrote works=True, including the
three paths whose own `why` string says the evidence cannot support a
judgement: "not enough days of measurement", "search visibility has never been
measured", and "no pre-activation baseline". That is how T008 b2b_outreach was
recorded on 2026-08-25 as "WORKS — mrr_usd median 0.0/day since activation":
its declared metric has read exactly 0.0 every day of its life, there is no
before-window to compare against, and the loop wrote down that it works. The
verdict then propagates — scout.py feeds the WORKS list into the prompt that
proposes tomorrow's techniques, so a false positive does not sit still, it
breeds. So:

    works=True   a positive signal was actually measured
    works=False  measured and failed — retire
    works=None   judged and NOT established either way

None is not the same as no verdict at all. No verdict means "too young to
look"; None means "we looked, and the instrument could not resolve it" — which
is a finding about the instrument, and belongs in front of someone.
"""
import datetime
import statistics

from . import ledger, searchconsole

GRACE_DAYS = 21          # nothing is judged before this — indexing is slow
WINDOW = 14              # trailing window for "is it working now"
MIN_TOTAL_VISITORS = 20  # cumulative owned visitors needed to call it alive
MIN_RECENT_MEDIAN = 1    # median daily owned visitors in the trailing window
REDUNDANCY_RATIO = 0.10  # <10% of an overlapping technique's traffic = redundant

# Search impressions on a technique's own URLs, below which it is invisible
# rather than merely un-clicked. Deliberately low: the whole site earns ~20
# impressions a week, so a technique whose pages Google serves at all is
# carrying a real signal. Above this bar a technique that misses the visitor
# threshold is flagged for a rewrite, not retired — retiring a page that ranks
# for a query nobody types is right, retiring one Google serves but we title
# badly throws away the work at the moment it started paying.
MIN_OWNED_IMPRESSIONS = 5

# Two days of paid acquisition — 2026-07-17 and 07-18, 288 and 279 visitors
# against a ~20/day organic baseline either side. The campaign is paused and
# was never a property of any technique, but those two days sit inside the
# pre-activation window of everything activated in late July, so leaving them
# in makes a technique look like it lost traffic it never had. Every review
# since has been told in prose to subtract them by hand; this is that
# instruction moved into the instrument, which is the only place it holds.
# The medians largely shrug the spike off — the totals do not, so this matters
# more now that both are reported.
PAID_FLIGHT_DAYS = frozenset({"2026-07-17", "2026-07-18"})


def _days_active(t):
    a = t.get("activated")
    if not a:
        return 0
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(a)).days
    except Exception:
        return 0


def _owned(t):
    return ledger.series(t["slug"], "owned_visitors", since=t.get("activated"))


def _global(metric, since=None):
    """Site-wide series with the paid-ad flight removed. See PAID_FLIGHT_DAYS."""
    return [(d, v) for d, v in ledger.series("__site__", metric, since=since)
            if d not in PAID_FLIGHT_DAYS]


def _trend(pairs, window=WINDOW):
    """(recent_median, prior_median) over two adjacent windows."""
    vals = [v for _, v in pairs]
    if len(vals) < 2:
        return (None, None)
    recent = vals[-window:]
    prior = vals[-2 * window:-window] or []
    return (statistics.median(recent) if recent else None,
            statistics.median(prior) if prior else None)


def evaluate(t):
    """Judge one technique. Returns a dict; does not mutate the ledger."""
    days = _days_active(t)
    slug = t["slug"]
    # works defaults to None: a path has to earn True by measuring something.
    res = {"id": t["id"], "slug": slug, "name": t.get("name", slug),
           "days_active": days, "action": "keep", "why": "", "measured": {},
           "works": None}

    if t.get("status") != "active":
        res["action"] = "skip"
        res["why"] = f"status is {t.get('status')}"
        return res

    if days < GRACE_DAYS:
        res["action"] = "keep"
        res["why"] = f"only {days}d active — under the {GRACE_DAYS}d grace period"
        return res

    if t.get("prefixes"):
        pairs = _owned(t)
        total = sum(v for _, v in pairs)
        recent, prior = _trend(pairs)
        vis = searchconsole.recent_visibility(slug, since=t.get("activated"))
        res["measured"] = {"total_owned_visitors": total,
                           "recent_median": recent, "prior_median": prior,
                           "days_measured": len(pairs),
                           "owned_serving_pages": vis["pages"],
                           "owned_impressions": vis["impressions"],
                           "owned_best_position": vis["best_position"]}
        if len(pairs) < GRACE_DAYS // 2:
            res["why"] = f"only {len(pairs)} days of measurement — not enough to judge"
            return res
        if total < MIN_TOTAL_VISITORS and (recent or 0) < MIN_RECENT_MEDIAN:
            # The visitor series says dead. Check the leading indicator before
            # acting on it — a technique whose pages Google serves is early,
            # not dead, and the two look identical in a visitor count of zero.
            if not vis["measured"]:
                res["why"] = (f"{total} owned visitors in {days}d, but its pages' search "
                              f"visibility has never been measured — not retiring on a "
                              f"metric with no resolution at this traffic level")
                return res
            if vis["impressions"] >= MIN_OWNED_IMPRESSIONS:
                res["action"] = "flag"
                res["why"] = (f"{total} owned visitors in {days}d, but {vis['pages']} of its "
                              f"pages earned {vis['impressions']} search impressions "
                              f"(best position {vis['best_position']}) — served but not "
                              f"clicked: rewrite the titles, do not retire")
                return res
            res["action"] = "retire"
            res["works"] = False
            res["why"] = (f"{total} owned visitors in {days}d, and its pages earned "
                          f"{vis['impressions']} search impressions across "
                          f"{vis['pages']} URLs — invisible in search, not merely un-clicked")
            return res
        direction = ""
        if recent is not None and prior is not None:
            direction = " and rising" if recent > prior else (
                " but falling" if recent < prior else " and flat")
        res["works"] = True
        res["why"] = (f"{total} owned visitors in {days}d (median {recent}/day{direction})"
                      + (f", {vis['pages']} pages serving in search" if vis["measured"] else ""))
        return res

    # Site-wide technique: judged on its declared global metric, comparing the
    # trailing window against the window immediately before it was activated.
    metric = t.get("metric") or "organic_visitors"
    pairs = _global(metric)
    after = [(d, v) for d, v in pairs if d >= (t.get("activated") or "")]
    before = [(d, v) for d, v in pairs if d < (t.get("activated") or "")][-WINDOW:]
    a_med = statistics.median([v for _, v in after[-WINDOW:]]) if after else None
    b_med = statistics.median([v for _, v in before]) if before else None
    # Totals alongside the medians, because at this traffic level the median is
    # frequently the wrong statistic and silently says "0.0" about a series that
    # is plainly moving: ai_visitors ran 0,1,0,0,0,1,1,0,0,2,2,1 over the twelve
    # days to 2026-08-24 — a median of 0.0 and a total of 8. Reporting both is
    # what stops "median 0.0/day" being read as "nothing happened".
    a_sum = sum(v for _, v in after[-WINDOW:]) if after else None
    b_sum = sum(v for _, v in before) if before else None
    res["measured"] = {"metric": metric, "median_after": a_med, "median_before": b_med,
                       "total_after": a_sum, "total_before": b_sum,
                       "window_days": WINDOW, "days_measured": len(after)}
    totals = (f" [{a_sum} in the last {min(WINDOW, len(after))}d"
              + (f" vs {b_sum} in the {len(before)}d before]" if before else "]")) if after else ""
    if len(after) < GRACE_DAYS // 2:
        res["why"] = f"only {len(after)} days of {metric} since activation"
        return res
    if b_med is None:
        # No before-window, so nothing here can attribute the level of the
        # metric to this technique — least of all when that level is zero.
        # This is the path that wrote "WORKS — mrr_usd median 0.0/day".
        if not a_sum:
            res["why"] = (f"{metric} has totalled {a_sum or 0} across all {len(after)}d since "
                          f"activation, and there is no pre-activation baseline — nothing "
                          f"measured either way")
        else:
            res["why"] = (f"{metric} median {a_med}/day since activation{totals}, but no "
                          f"pre-activation baseline to attribute it to")
        return res
    if a_med is not None and a_med <= b_med:
        res["action"] = "flag"
        res["why"] = (f"{metric} median {a_med}/day vs {b_med}/day before activation{totals} — "
                      f"no measurable lift after {days}d")
        return res
    res["works"] = True
    res["why"] = f"{metric} median {a_med}/day vs {b_med}/day before activation{totals}"
    return res


def find_redundant(techs):
    """Techniques whose URLs overlap and whose traffic is a rounding error next
    to the overlapping one. Running both costs build time and splits link equity."""
    out = []
    act = [t for t in techs if t.get("status") == "active" and t.get("prefixes")]
    totals = {t["slug"]: sum(v for _, v in _owned(t)) for t in act}
    for a in act:
        for b in act:
            if a["slug"] >= b["slug"]:
                continue
            overlap = any(p.startswith(q) or q.startswith(p)
                          for p in a["prefixes"] for q in b["prefixes"])
            if not overlap:
                continue
            ta, tb = totals[a["slug"]], totals[b["slug"]]
            if _days_active(a) < GRACE_DAYS or _days_active(b) < GRACE_DAYS:
                continue
            weak, strong, wv, sv = ((a, b, ta, tb) if ta < tb else (b, a, tb, ta))
            if sv > 0 and wv <= sv * REDUNDANCY_RATIO:
                out.append({"weak": weak["id"], "weak_slug": weak["slug"],
                            "strong_slug": strong["slug"], "weak_visitors": wv,
                            "strong_visitors": sv})
    return out


def run(apply=True):
    """Evaluate everything; optionally write the decisions back to the ledger."""
    techs = ledger.load_techniques()
    results = [evaluate(t) for t in techs]
    redundant = find_redundant(techs)
    red_ids = {r["weak"] for r in redundant}

    actions = []
    for r in results:
        if r["action"] == "retire" and apply:
            ledger.set_status(r["id"], "retired", r["why"])
            ledger.set_verdict(r["id"], False, r["why"], r["measured"])
            actions.append(f"RETIRED {r['id']} {r['slug']} — {r['why']}")
        elif r["action"] == "flag":
            # A flag nobody reads is not a decision. Surfaced in the daily
            # report next to the retirements so "served but not clicked" and
            # "no lift" reach the person who can rewrite the page.
            actions.append(f"FLAGGED {r['id']} {r['slug']} — {r['why']}")
            if r["measured"] and apply:
                # A flag is a judgement too, and it must overwrite any earlier
                # WORKS rather than let it stand unchallenged underneath.
                ledger.set_verdict(r["id"], None, r["why"], r["measured"])
        elif r["action"] == "keep" and r["days_active"] >= GRACE_DAYS and r["measured"] and apply:
            # Record a running verdict so the year-end list is always current —
            # r["works"], never a bare True. See the tri-state note up top.
            ledger.set_verdict(r["id"], r["works"], r["why"], r["measured"])

    for rr in redundant:
        if rr["weak"] in red_ids and apply:
            why = (f"redundant with {rr['strong_slug']} "
                   f"({rr['weak_visitors']} vs {rr['strong_visitors']} owned visitors)")
            ledger.set_status(rr["weak"], "retired", why)
            ledger.set_verdict(rr["weak"], False, why)
            actions.append(f"RETIRED {rr['weak']} — {why}")

    return {"evaluated": results, "redundant": redundant, "actions": actions}


def scoreboard():
    """The list the owner wants at the end of the year: what worked, what didn't.

    Four buckets, because "we never looked" and "we looked and could not tell"
    are different facts and collapsing them loses the more actionable one.
    `unproven` carries an explicit works=None verdict; `not_yet_judged` has no
    verdict at all.
    """
    techs = ledger.load_techniques()
    works, fails, unproven, pending = [], [], [], []
    for t in techs:
        v = t.get("verdict")
        row = {"id": t["id"], "name": t.get("name"), "kind": t.get("kind"),
               "status": t.get("status"), "source": t.get("source"),
               "hypothesis": t.get("hypothesis"),
               "activated": t.get("activated"), "retired": t.get("retired"),
               "why": (v or {}).get("why"), "measured": (v or {}).get("measured")}
        if not v:
            pending.append(row)
        elif v.get("works") is True:
            works.append(row)
        elif v.get("works") is False:
            fails.append(row)
        else:
            unproven.append(row)
    works.sort(key=lambda r: -( (r.get("measured") or {}).get("total_owned_visitors") or 0))
    return {"works": works, "does_not_work": fails, "unproven": unproven,
            "not_yet_judged": pending}
