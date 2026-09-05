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

The second way a false WORKS gets written is not a bad threshold but a bad
attribution: a technique with no prefixes of its own is judged on a __site__
series, and on 2026-09-05 seven active techniques were being judged on the same
`organic_visitors` numbers. Four of them carried a WORKS quoting the identical
"median 11.0/day vs 6.0/day" lift. See _co_claimants and _guard_shared_metric.
"""
import datetime
import statistics

from . import indexstatus, ledger, searchconsole

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

# How many of a technique's URLs the index census must have actually inspected
# before "none of them has ever been crawled" counts as evidence rather than as
# silence. See the census guard in evaluate() for why this exists at all.
#
# Three is deliberately low, and the reason is that the guard's cost is
# asymmetric. Firing it wrongly withholds a verdict for one revisit cycle on a
# technique that was going to be retired anyway — retirement is reversible and
# the ledger keeps the series. NOT firing it wrongly destroys a technique on a
# measurement that could not have come out any other way, which has now
# happened three times. The census inspects the whole cohort every few days, so
# a prefix where every inspected URL comes back never-fetched is a statement
# about the tier and not about one unlucky URL; below three it is a statement
# about nothing, and the existing path stands.
MIN_CENSUS_READ = 3

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

# Metrics that are CUMULATIVE STOCKS, not daily flows.
#
# `visitors` is a flow: 16 today, 25 tomorrow, and the median of a window is a
# fair summary of the level. `accounts_with_saves` is a stock: it counts every
# account that has ever saved a building, so it can only ever go up. Running a
# stock through the median-of-two-windows comparison below is not merely
# imprecise, it is rigged in both directions:
#
#   * a stock that grew at all scores works=True forever, because the later
#     window's median is necessarily >= the earlier one's. That is the same
#     false-positive machinery the tri-state fixed on 2026-08-25, arriving by
#     a different road.
#   * a stock that is flat scores "no measurable lift" with no way to tell a
#     technique that is failing from one nothing has entered yet.
#
# For these the question is the CHANGE across the window, expressed as a daily
# rate so windows of different lengths can be compared at all. See _judge_stock.
STOCK_METRICS = frozenset({
    "paying_subs", "comped_subs", "mrr_usd", "api_keys", "api_keys_pro",
    "api_keys_business", "accounts_with_saves", "reports_sold",
    "gsc_serving_ever",
})

# A stock needs a pre-activation span of at least this many days before a
# growth rate measured on it means anything. One reading either side of the
# activation date is not a baseline, it is a coincidence.
MIN_BASELINE_DAYS = 7

# How many co-claimants to name in the `why` string before summarising the rest.
# The string is rendered in the daily email next to the verdict; naming three is
# enough for a reader to recognise the pile, and the full list is kept in
# measured["co_claimants"] either way.
CO_CLAIMANTS_NAMED = 3


def _span_days(pairs):
    """Calendar days between the first and last reading. 0 for a single point."""
    if len(pairs) < 2:
        return 0
    try:
        return (datetime.date.fromisoformat(pairs[-1][0])
                - datetime.date.fromisoformat(pairs[0][0])).days
    except Exception:
        return len(pairs) - 1


def _growth_rate(pairs):
    """(delta, span_days, per_day) for a cumulative series. None if unmeasurable."""
    if len(pairs) < 2:
        return (None, 0, None)
    span = _span_days(pairs)
    delta = pairs[-1][1] - pairs[0][1]
    if not span:
        return (delta, 0, None)
    return (delta, span, delta / span)


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


def _judge_stock(res, metric, after, before, days):
    """Judge a technique whose declared metric is a cumulative stock.

    The reading that matters is how fast the counter moved after activation
    against how fast it was moving before, per day, because the two spans are
    almost never the same length. Everything here refuses to claim more than
    the arithmetic supports: a stock that moved is reported as having moved,
    and is still only works=True when there is a real baseline to beat.
    """
    a_delta, a_span, a_rate = _growth_rate(after)
    b_delta, b_span, b_rate = _growth_rate(before)
    first = after[0][1] if after else None
    last = after[-1][1] if after else None
    res["measured"] = {"metric": metric, "kind": "stock",
                       "start": first, "end": last,
                       "delta_after": a_delta, "span_days_after": a_span,
                       "per_day_after": round(a_rate, 4) if a_rate is not None else None,
                       "delta_before": b_delta, "span_days_before": b_span,
                       "per_day_before": round(b_rate, 4) if b_rate is not None else None,
                       "days_measured": len(after)}

    if len(after) < GRACE_DAYS // 2:
        res["why"] = f"only {len(after)} readings of {metric} since activation"
        return res
    if a_rate is None:
        res["why"] = (f"{metric} has only {len(after)} reading(s) spanning {a_span}d since "
                      f"activation — not enough to measure a rate")
        return res

    moved = f"{metric} went {_num(first)} → {_num(last)} ({_signed(a_delta)}) over {a_span}d"

    if a_delta == 0:
        # Flat is a real reading, but it does not say whether the technique
        # failed or whether nothing has entered it yet. That difference is the
        # whole reason this is not works=False.
        res["action"] = "flag"
        res["why"] = (f"{moved} — the counter has not moved at all since activation, so "
                      f"either nothing reaches this technique or nothing it does converts")
        return res

    if b_span < MIN_BASELINE_DAYS:
        res["why"] = (f"{moved}, but only {b_span}d of pre-activation history — no comparable "
                      f"baseline, so the movement cannot be attributed either way")
        return res

    was = f"vs {_signed(b_delta)} over the {b_span}d before ({round(b_rate, 3)}/day)"
    if a_rate <= b_rate:
        res["action"] = "flag"
        res["why"] = f"{moved} at {round(a_rate, 3)}/day {was} — no acceleration after {days}d"
        return res
    res["works"] = True
    res["why"] = f"{moved} at {round(a_rate, 3)}/day {was}"
    return res


def _co_claimants(t, metric, techs):
    """Other live techniques judged on the SAME site-wide series as `t`.

    A technique with no prefixes of its own is judged on a __site__ metric —
    one series that belongs to the whole site and to no technique in
    particular. When several active techniques declare the same one, the loop
    below compares each of them against those identical numbers and hands the
    same movement to every one of them. On 2026-09-05 SEVEN active techniques
    declared `organic_visitors` (T004, T005, T010, T015, T016, T037, T072) and
    two declared `reports_sold` (T011, T017); four of the seven were carrying a
    WORKS verdict quoting the same "median 11.0/day vs 6.0/day" lift.

    They cannot all have caused it, and this instrument cannot say which did.
    Yesterday's entry found this the hard way on T037 crawl_paths: its linking
    work was fully delivered while every indexing series went the other way
    (serving_pages 63 -> 5, index_state_indexed 10 -> 1), and it still read
    WORKS because it happened to be active while a site-wide number drifted up.

    All of these techniques are live simultaneously, so their trailing windows
    are identical by construction and there is no date arithmetic to do: sharing
    the metric IS the overlap. A technique that declares its own `prefixes` is
    judged on the owned path instead and never reaches here, so it is not a
    claimant on the site-wide series and is not counted.
    """
    out = []
    for other in techs or ():
        if other.get("id") == t.get("id"):
            continue
        if other.get("status") != "active" or other.get("prefixes"):
            continue
        if (other.get("metric") or "organic_visitors") != metric:
            continue
        out.append(f"{other.get('id')} {other.get('slug')}")
    return sorted(out)


def _guard_shared_metric(res, metric, co):
    """Demote a positive verdict that several techniques are claiming at once.

    ONLY works=True is demoted, and the asymmetry is deliberate — the same
    reasoning as the MIN_CENSUS_READ guard above. A false WORKS does not sit
    still: scout.py feeds the WORKS list into the prompt that proposes
    tomorrow's techniques, so it breeds, and it also tells a future review that
    a question is settled when it is not. A false "no lift" costs one flag that
    a person reads and dismisses. Guard the direction that propagates.

    Nothing here touches res["action"], so this can never retire anything: a
    demoted technique keeps running and keeps being measured. What changes is
    that the ledger stops asserting a causal claim the numbers cannot support.
    """
    if not co or res.get("works") is not True:
        return res
    named = ", ".join(co[:CO_CLAIMANTS_NAMED])
    if len(co) > CO_CLAIMANTS_NAMED:
        named += f" and {len(co) - CO_CLAIMANTS_NAMED} more"
    res["works"] = None
    res.setdefault("measured", {})["co_claimants"] = co
    res["why"] = (f"{res['why']} — but {len(co)} other active technique"
                  f"{'s are' if len(co) != 1 else ' is'} judged on the same site-wide "
                  f"{metric} series ({named}), so the movement cannot be attributed to "
                  f"any one of them")
    return res


def _num(v):
    if v is None:
        return "?"
    return str(int(v)) if float(v) == int(v) else str(round(float(v), 2))


def _signed(v):
    if v is None:
        return "?"
    return ("+" if v > 0 else "") + _num(v)


def evaluate(t, techs=None):
    """Judge one technique. Returns a dict; does not mutate the ledger.

    `techs` is the full ledger, used only to find the other techniques judged on
    the same site-wide series (see _co_claimants). It is optional so that a
    caller holding a single record can still evaluate it; passing nothing simply
    means no co-claimant is visible and the guard cannot fire.
    """
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
            # Zero impressions has two causes and this branch used to assume
            # one of them. "Invisible in search" is a claim about Google's
            # JUDGEMENT of the pages — it looked, and it is not showing them.
            # That claim needs Google to have looked, and the URL Inspection
            # census is the only instrument on the site that can say whether it
            # did. Where the census says it has inspected these URLs and not one
            # of them has ever been fetched, the impression count is measuring
            # the crawler's reach, not the pages, and no verdict about the pages
            # can be drawn from it — so this holds instead of retiring, and says
            # what would have to change for the question to become answerable.
            #
            # This is the same false-verdict family as the fixes of 2026-08-25
            # (unconditional works=True), 08-26 (stocks through a flow test) and
            # 08-27 — a path asserting more than its evidence carries — surviving
            # on the retirement side, where it is most expensive. It had already
            # fired three times when this landed: T002, T013 and T023, all three
            # retired for earning no impressions, all three at 0 fetched across
            # 10, 57 and 3 inspected URLs on 2026-08-29.
            #
            # It is deliberately narrow. It needs POSITIVE evidence of no crawl,
            # not merely an absent measurement: a technique whose URLs the
            # census has not sampled (`read` below MIN_CENSUS_READ) falls
            # through to the retirement below exactly as before. The known hole
            # is a technique whose URLs are in no sitemap and therefore in no
            # cohort — the census cannot speak for those, and being unsubmitted
            # is its own finding rather than one to launder through this guard.
            crawl = indexstatus.crawl_evidence(t.get("prefixes"))
            res["measured"]["census_read"] = crawl["read"]
            res["measured"]["census_fetched"] = crawl["fetched"]
            if crawl["read"] >= MIN_CENSUS_READ and crawl["fetched"] == 0:
                res["why"] = (f"{total} owned visitors in {days}d and 0 search "
                              f"impressions, but Google has never fetched any of "
                              f"the {crawl['read']} of its URLs the index census "
                              f"has inspected — that zero measures crawl reach, "
                              f"not these pages, so there is nothing to retire on "
                              f"yet. Re-judge once any of them is crawled")
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
        served = f", {vis['pages']} pages serving in search" if vis["measured"] else ""

        # Reaching here means the technique cleared the floor above — but the
        # floor is `total >= MIN_TOTAL_VISITORS OR recent >= MIN_RECENT_MEDIAN`,
        # and `total` is CUMULATIVE. A technique that drew traffic in its first
        # fortnight and nothing since keeps clearing it forever, because a sum
        # over an ever-longer window cannot fall. This branch used to answer
        # that with an unconditional works=True while its own why-string said
        # "but falling" — the same defect 2026-08-25 fixed on the site-wide
        # paths and 08-26 on the stock metrics, surviving here because this
        # branch never went through either pass. It matters for the same
        # reason: scout.py feeds the WORKS list to the model under the heading
        # ALREADY MEASURED AS WORKING, so a false positive breeds.
        #
        # So WORKS now needs the technique to be alive NOW and not shrinking.
        # Anything else is unproven (works=None) — not failed, which would be
        # its own false claim: these are all above the retirement floor.
        alive_now = (recent or 0) >= MIN_RECENT_MEDIAN
        falling = recent is not None and prior is not None and recent < prior
        if alive_now and not falling:
            res["works"] = True
            res["why"] = (f"{total} owned visitors in {days}d "
                          f"(median {recent}/day{direction})" + served)
        elif falling:
            res["works"] = None
            res["why"] = (f"{total} owned visitors in {days}d, but the trailing "
                          f"{WINDOW}d median is {recent}/day against {prior}/day "
                          f"in the {WINDOW}d before — the cumulative total clears "
                          f"the floor because it cannot fall, while the rate is "
                          f"declining" + served)
        else:
            res["works"] = None
            res["why"] = (f"{total} owned visitors in {days}d clears the "
                          f"{MIN_TOTAL_VISITORS}-visitor floor, but the trailing "
                          f"{WINDOW}d median is {recent}/day — below the "
                          f"{MIN_RECENT_MEDIAN}/day that counts as alive, so the "
                          f"total is carried by days outside the window" + served)
        return res

    # Site-wide technique: judged on its declared global metric, comparing the
    # trailing window against the window immediately before it was activated.
    metric = t.get("metric") or "organic_visitors"
    co = _co_claimants(t, metric, techs)
    pairs = _global(metric)
    after = [(d, v) for d, v in pairs if d >= (t.get("activated") or "")]
    before = [(d, v) for d, v in pairs if d < (t.get("activated") or "")][-WINDOW:]
    if metric in STOCK_METRICS:
        return _guard_shared_metric(
            _judge_stock(res, metric, after,
                         [(d, v) for d, v in pairs if d < (t.get("activated") or "")],
                         days),
            metric, co)
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
    return _guard_shared_metric(res, metric, co)


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
    results = [evaluate(t, techs) for t in techs]
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
