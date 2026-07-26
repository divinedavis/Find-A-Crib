#!/usr/bin/env python3
"""The daily review: keep what works, retire what doesn't, drop what's redundant.

This is the half of the loop that makes it self-improving rather than merely
automated. Every day it re-reads the measured series behind each active
technique and asks three questions:

  1. Has it had a fair run?      (below GRACE_DAYS, nothing is judged — SEO
                                  changes take weeks to show up in a series)
  2. Did it earn its traffic?    (owned visitors since activation vs threshold)
  3. Is it redundant?            (another technique owns overlapping URLs and
                                  massively outperforms it)

Retiring is cheap and reversible: status flips to "retired", the driver stops
running it tomorrow, and the verdict stays in the ledger forever so the same
idea does not get re-proposed as if it were new.
"""
import datetime
import statistics

from . import ledger

GRACE_DAYS = 21          # nothing is judged before this — indexing is slow
WINDOW = 14              # trailing window for "is it working now"
MIN_TOTAL_VISITORS = 20  # cumulative owned visitors needed to call it alive
MIN_RECENT_MEDIAN = 1    # median daily owned visitors in the trailing window
REDUNDANCY_RATIO = 0.10  # <10% of an overlapping technique's traffic = redundant


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
    return ledger.series("__site__", metric, since=since)


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
    res = {"id": t["id"], "slug": slug, "name": t.get("name", slug),
           "days_active": days, "action": "keep", "why": "", "measured": {}}

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
        res["measured"] = {"total_owned_visitors": total,
                           "recent_median": recent, "prior_median": prior,
                           "days_measured": len(pairs)}
        if len(pairs) < GRACE_DAYS // 2:
            res["why"] = f"only {len(pairs)} days of measurement — not enough to judge"
            return res
        if total < MIN_TOTAL_VISITORS and (recent or 0) < MIN_RECENT_MEDIAN:
            res["action"] = "retire"
            res["why"] = (f"{total} owned visitors in {days}d and a trailing median of "
                          f"{recent} — below the bar to keep running daily")
            return res
        direction = ""
        if recent is not None and prior is not None:
            direction = " and rising" if recent > prior else (
                " but falling" if recent < prior else " and flat")
        res["why"] = f"{total} owned visitors in {days}d (median {recent}/day{direction})"
        return res

    # Site-wide technique: judged on its declared global metric, comparing the
    # trailing window against the window immediately before it was activated.
    metric = t.get("metric") or "organic_visitors"
    pairs = _global(metric)
    after = [(d, v) for d, v in pairs if d >= (t.get("activated") or "")]
    before = [(d, v) for d, v in pairs if d < (t.get("activated") or "")][-WINDOW:]
    a_med = statistics.median([v for _, v in after[-WINDOW:]]) if after else None
    b_med = statistics.median([v for _, v in before]) if before else None
    res["measured"] = {"metric": metric, "median_after": a_med, "median_before": b_med,
                       "days_measured": len(after)}
    if len(after) < GRACE_DAYS // 2:
        res["why"] = f"only {len(after)} days of {metric} since activation"
        return res
    if b_med is None:
        res["why"] = f"{metric} median {a_med}/day since activation (no pre-activation baseline)"
        return res
    if a_med is not None and a_med <= b_med:
        res["action"] = "flag"
        res["why"] = (f"{metric} median {a_med}/day vs {b_med}/day before activation — "
                      f"no measurable lift after {days}d")
        return res
    res["why"] = f"{metric} median {a_med}/day vs {b_med}/day before activation"
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
        elif r["action"] == "keep" and r["days_active"] >= GRACE_DAYS and r["measured"] and apply:
            # record a running verdict so the year-end list is always current
            ledger.set_verdict(r["id"], True, r["why"], r["measured"])

    for rr in redundant:
        if rr["weak"] in red_ids and apply:
            why = (f"redundant with {rr['strong_slug']} "
                   f"({rr['weak_visitors']} vs {rr['strong_visitors']} owned visitors)")
            ledger.set_status(rr["weak"], "retired", why)
            ledger.set_verdict(rr["weak"], False, why)
            actions.append(f"RETIRED {rr['weak']} — {why}")

    return {"evaluated": results, "redundant": redundant, "actions": actions}


def scoreboard():
    """The list the owner wants at the end of the year: what worked, what didn't."""
    techs = ledger.load_techniques()
    works, fails, pending = [], [], []
    for t in techs:
        v = t.get("verdict")
        row = {"id": t["id"], "name": t.get("name"), "kind": t.get("kind"),
               "status": t.get("status"), "source": t.get("source"),
               "hypothesis": t.get("hypothesis"),
               "activated": t.get("activated"), "retired": t.get("retired"),
               "why": (v or {}).get("why"), "measured": (v or {}).get("measured")}
        if not v:
            pending.append(row)
        elif v.get("works"):
            works.append(row)
        else:
            fails.append(row)
    works.sort(key=lambda r: -( (r.get("measured") or {}).get("total_owned_visitors") or 0))
    return {"works": works, "does_not_work": fails, "not_yet_judged": pending}
