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

The third way is worse than either, because the technique cannot possibly be
the cause: five of the nine techniques declaring `organic_visitors` publish no
URL at all. They are read-only audits of the live docroot, so a site-wide
traffic series is not weak evidence about them, it is no evidence about them —
and until 2026-10-04 it was their whole verdict, and they were also counted
against the four techniques that do act. See _judge_audit.
"""
import datetime
import statistics

from . import indexstatus, ledger, searchconsole

GRACE_DAYS = 21          # nothing is judged before this — indexing is slow
WINDOW = 14              # trailing window for "is it working now"
MIN_TOTAL_VISITORS = 20  # cumulative owned visitors needed to call it alive
MIN_RECENT_MEDIAN = 1    # median daily owned visitors in the trailing window
REDUNDANCY_RATIO = 0.10  # <10% of an overlapping technique's traffic = redundant
TREND_MIN_COVERAGE_PCT = 60.0  # share of a window's days that must hold a reading

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

# WHAT COUNTS AS THIS TECHNIQUE HAVING ACTED, for the techniques whose declared
# metric is a conversion counter they do not themselves move.
#
# reports_sold is a GATE, not an attribution. T011 lifecycle_email emails people
# who have ALREADY bought a Building Report, so it cannot cause the first sale:
# a flat reports_sold says nothing whatever about those emails until you also
# know whether any were sent. _judge_stock's flat branch has been handing the
# reader that unresolved disjunction ("either nothing reaches this technique or
# nothing it does converts") since 2026-08-26, and the ledger has had to carry
# the resolution by hand TWICE — T011's own notes on 2026-08-26 ("reports_sold
# is a GATE, not an attribution") and T008's on 2026-09-24 ("the verdict on it
# is measuring an outage rather than an idea"). A caveat a human has to rewrite
# into the notes every revisit belongs in code.
#
# It is not a hypothetical distinction. On 2026-10-19 both T011 and T017 carried
# the identical flat sentence, and the two cases are opposites:
#
#   T011 lifecycle_email  -> emails_sent, recorded by growth/lifecycle.py. Two
#                            readings in its life, both dated 2026-07-27, then
#                            46 days of silence: it has never sent an email, so
#                            "nothing it does converts" is not weak evidence,
#                            it is impossible.
#   T017 one_time_...     -> sent_saved_paid_ask, recorded by growth/accounts.py
#                            because the $9 ask is put by the ACCOUNT sequence
#                            and not by T017 itself. 15 asks across 16 recorded
#                            days against 0 sales: here the other disjunct is
#                            the one that is ruled out, and the flat counter IS
#                            a reading about the offer.
#   T018 account_lifecycle-> emails_sent, recorded by growth/accounts.py.
#   T008 b2b_outreach     -> emails_sent, recorded by growth/outreach.py. ADDED
#                            2026-10-24, on T008's revisit. It was named in the
#                            paragraph above as one of the two cases the ledger
#                            had carried by hand, and then left out of the map
#                            below — so the sentence it was written to fix was
#                            still the sentence T008 got. It is a THIRD shape,
#                            not a copy of either: T011 acts when this loop
#                            sends, T017 acts when another sequence puts the
#                            ask, and T008 acts when a HUMAN presses send,
#                            which the loop can only know because
#                            outreach.mark() was told. outreach.py drafts and
#                            never sends by design (CAN-SPAM, GDPR), so the
#                            drafting is the module acting and the send is the
#                            TECHNIQUE acting; the hypothesis is about the
#                            second, which is why this maps to emails_sent and
#                            not to the drafts_written series recorded beside
#                            it. A 0 here is therefore the honest reading of a
#                            night with drafts waiting and nobody sending, and
#                            the flat branch's "unmeasurable by construction
#                            and not failed" is the correct verdict for it.
#
# A module constant rather than a field on the technique record, deliberately:
# an `executes` field would have to be threaded through ledger.add() AND
# seed.run()'s sync list, and a seeded technique whose new field is missing from
# that list reverts silently on the next deploy — the trap the 2026-08-26 entry
# wrote down as its rule 7. Promote it to a ledger field the first time a
# technique the scout proposes needs one, and not before.
EXECUTION_SERIES = {
    "lifecycle_email": ("lifecycle_email", "emails_sent"),
    "one_time_building_report_product": ("account_lifecycle", "sent_saved_paid_ask"),
    "account_lifecycle": ("account_lifecycle", "emails_sent"),
    "b2b_outreach": ("b2b_outreach", "emails_sent"),
}


def _executions(slug, window):
    """How many times `slug` acted over `window`, from its execution series.

    `window` is an inclusive (first_date, last_date) pair of ISO strings — the
    span the verdict itself is about, so the two can never describe different
    periods. Returns (acted, readings): `readings` is how many days inside the
    window carry a reading at all, and `acted` is their sum.

    acted is None whenever readings is 0, and THAT IS THE LOAD-BEARING STATE:
    an unwritten series is not a zero. "We measured the technique acting and it
    acted nothing" and "we never measured whether it acted" are different
    findings, and the second one is about the instrument. Same three-state shape
    as growth_paused() (paused / live / unreadable-and-therefore-unknown) and
    the same reason accounts._record_aged_out exists at all: a night that was
    due nobody must not read like a night whose job was broken.

    A technique with no entry in EXECUTION_SERIES returns (None, 0) and so falls
    through to the unchanged disjunction — the guard needs POSITIVE evidence to
    say anything, exactly like the MIN_CENSUS_READ guard below.
    """
    pair = EXECUTION_SERIES.get(slug)
    if not pair or not window:
        return (None, 0)
    lo, hi = window
    vals = [v for d, v in ledger.series(pair[0], pair[1]) if lo <= d <= hi]
    total = 0.0
    seen = 0
    for v in vals:
        try:
            total += float(v)
        except (TypeError, ValueError):
            continue
        seen += 1
    if not seen:
        return (None, 0)
    return (int(total) if total == int(total) else total, seen)


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


def _activation_clock(t):
    """The date `activated` names, or None if it is missing or unreadable.

    _days_active collapses both of those into 0 — the same number it returns
    for a technique activated today. judge() has to tell them apart, because
    one is a technique at the start of its grace period and the other is a
    ledger defect that keeps it there forever. The redundancy pass does not
    need the distinction, so _days_active is left exactly as it is.
    """
    return _day(t.get("activated") or "")


def _owned(t):
    return ledger.series(t["slug"], "owned_visitors", since=t.get("activated"))


def _global(metric, since=None):
    """Site-wide series with the paid-ad flight removed. See PAID_FLIGHT_DAYS."""
    return [(d, v) for d, v in ledger.series("__site__", metric, since=since)
            if d not in PAID_FLIGHT_DAYS]


def _day(d):
    """A reading's date, or None if it is not a date this module can read."""
    try:
        return datetime.date.fromisoformat(d)
    except Exception:
        return None


def _in_window(pairs, end, window):
    """The values whose date falls in the `window` calendar days ending at `end`.

    Selection is by DATE, never by position. See _trend for why that distinction
    is the whole point of this helper.
    """
    start = end - datetime.timedelta(days=window - 1)
    out = []
    for d, v in pairs:
        day = _day(d)
        if day is not None and start <= day <= end:
            out.append(v)
    return out


def _latest(pairs):
    """The newest date in a series, or today for a series with no usable date."""
    days = [d for d in (_day(x) for x, _v in pairs) if d is not None]
    return max(days) if days else datetime.date.today()


def _covered(vals, window):
    """Does this window hold enough readings for its median to describe it?

    A median is a statement about a period, and it can only be read as one
    where most of that period is actually present. The threshold is a judgement
    call rather than a derivation: at TREND_MIN_COVERAGE_PCT=60 a 14-day window
    survives an outage of up to five nights and refuses the sixth, which is the
    length at which this site's own pauses start to reach back into a
    materially different traffic regime.
    """
    return len(vals) * 100.0 >= TREND_MIN_COVERAGE_PCT * window


def _trend(pairs, window=WINDOW, anchor=None):
    """(recent_median, prior_median, cmp) over two adjacent CALENDAR windows.

    WHY THIS IS DATE-WINDOWED AND NOT `vals[-window:]`, which is what it was
    until 2026-10-16. The old form took the last `window` READINGS and every
    caller then described the result as "the trailing 14d median". Those are
    the same number only while the series has a reading for every day. The
    moment a night is missed the positional window silently stretches: fourteen
    readings ending 2026-10-12 cover fourteen days today, but the same slice
    taken on the first night after #PAUSED-20261012 would reach back to
    2026-09-30 and still be published as "the trailing 14d". The series already
    carries two such holes (2026-07-16 -> 07-19, 2026-07-26 -> 07-28), and the
    pause guarantees a third of at least four days.

    That mislabel is not cosmetic, because two of the three things this pair
    drives are COMPARISONS between the windows — `falling` (recent < prior) and
    the site-wide "no measurable lift" flag. Comparing a median over 14 days
    with a median over 21 days is not a direction, and the same reasoning is
    already settled elsewhere in this engine: indexstatus.crawl_rate_report
    refuses a crawl-count comparison outright when its denominator moved, and
    the journal's standing rule is never to quote those counts without
    `crawl_rate.comparable`. This is that rule, applied to the window that
    retires techniques.

    So both windows are now cut by date from `anchor`, and the third return
    value says whether they hold enough days to be read as periods at all.
    `comparable` is None when there is no prior window to compare with, exactly
    as crawl_rate_report does it, because "no baseline" and "a baseline that
    agrees" must not render the same.

    THE ANCHOR IS THE LAST READING'S DATE, NOT TODAY, and that is the one
    choice here worth defending. Anchoring on today reads as the more honest
    "trailing fourteen days from now", and it was the first thing tried — but
    it makes a verdict move when no evidence has. Run against the frozen
    2026-10-12 ledger it flipped T001 fresh_section8 from "0.5/day, below the
    1/day that counts as alive" to "1/day and rising", purely because the four
    unmeasured nights of the pause had pushed four older days out of the
    window. That is the instrument reporting its own clock, which is the exact
    defect the 2026-10-08 entry recorded against the crawl-rate sampler when
    the same date read twice returned 6 and 10. Anchoring on the last reading
    keeps a verdict still until a measurement moves it, and loses nothing: a
    hole INSIDE the window still cuts the coverage, which is the case this
    function exists for, and how stale the whole series is belongs to
    cron_liveness, which already says it in days on every status line.

    The medians themselves are still returned when a window is thin. They are
    not wrong — they are exactly right about the days that were measured — and
    callers that only want a level (is anything arriving at all) can use them.
    What `comparable` withholds is the right to call the pair a TREND, and what
    `recent_covered` withholds is the right to retire on a hollow window.
    """
    anchor = anchor or _latest(pairs)
    cmp_ = {"window_days": window, "anchor": anchor.isoformat()}
    if len(pairs) < 2:
        cmp_.update({"comparable": None, "recent_covered": False,
                     "note": "fewer than two readings — no window to cut"})
        return (None, None, cmp_)

    recent = _in_window(pairs, anchor, window)
    prior = _in_window(pairs, anchor - datetime.timedelta(days=window), window)
    r_cov, p_cov = _covered(recent, window), _covered(prior, window)
    cmp_.update({"recent_readings": len(recent), "prior_readings": len(prior),
                 "recent_covered": r_cov, "prior_covered": p_cov})

    r_med = statistics.median(recent) if recent else None
    p_med = statistics.median(prior) if prior else None
    if not prior:
        cmp_["comparable"] = None
        cmp_["note"] = (f"{len(recent)} reading{'' if len(recent) == 1 else 's'} in the "
                        f"{window} days to {anchor} and none in the {window} before — "
                        f"a level, not yet a direction")
        return (r_med, p_med, cmp_)

    cmp_["comparable"] = bool(r_cov and p_cov)
    if cmp_["comparable"]:
        cmp_["note"] = (f"{len(recent)} and {len(prior)} readings in the two {window}-day "
                        f"windows to {anchor} — both windows are substantially complete, "
                        f"so the two medians compare directly")
    else:
        thin = []
        if not r_cov:
            thin.append(f"the trailing window holds {len(recent)} of {window} days")
        if not p_cov:
            thin.append(f"the window before it holds {len(prior)} of {window} days")
        cmp_["note"] = (f"NOT comparable: {' and '.join(thin)}, so the two medians "
                        f"describe periods of different length and their difference is "
                        f"not a trend — nights the engine did not run are missing days, "
                        f"not days with no traffic")
    return (r_med, p_med, cmp_)


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
        # whole reason this is not works=False — and where the technique's own
        # actions are measured, the loop can say WHICH of the two it is instead
        # of handing the reader a disjunction to resolve by hand every revisit.
        # See EXECUTION_SERIES for the four live cases and how they differ.
        #
        # works stays None on all three branches. Resolving the disjunction
        # changes what the ledger SAYS, never whether the technique is credited:
        # "it acted 15 times and nothing converted" is a reason to look at the
        # offer, not a measured success, and promoting it to works=False here
        # would retire on one flat counter what MIN_BASELINE_DAYS below refuses
        # to attribute even when the counter moves.
        res["action"] = "flag"
        window = (after[0][0], after[-1][0]) if after else None
        acted, readings = _executions(res["slug"], window)
        res["measured"]["executions"] = acted
        res["measured"]["execution_readings"] = readings
        flat = f"{moved} — the counter has not moved at all since activation"
        if readings and not acted:
            res["why"] = (f"{flat}, and it acted 0 times on the {readings} day(s) of "
                          f"those {a_span}d that recorded whether it acted — so this "
                          f"zero measures its own execution and not its effect, and "
                          f"there is nothing to judge yet. Re-judge once it has acted "
                          f"once; if it never does, it is unmeasurable by construction "
                          f"and not failed")
        elif acted:
            res["why"] = (f"{flat}, and it DID act {acted} time(s) across {readings} "
                          f"day(s) of those {a_span}d — so nothing-reaches-it is ruled "
                          f"out and this is a reading about what it does, not about "
                          f"whether it ran")
        else:
            res["why"] = (f"{flat}, so either nothing reaches this technique or nothing "
                          f"it does converts — and its own action count is unrecorded "
                          f"across those {a_span}d, so the loop cannot say which")
        return res

    # A COUNTER THAT MOVED IS NOT EVIDENCE FOR A TECHNIQUE THAT NEVER ACTED.
    # Until 2026-10-24 only the flat branch above consulted the execution
    # count, and T008 b2b_outreach is the case that showed that is not enough:
    # mrr_usd went 0 → 4.99, so its series is NOT flat, so the guard was never
    # reached — and the 4.99 is a subscription that a drafted, never-sent
    # outreach email cannot have caused. The reading it got instead ("no
    # comparable baseline, so the movement cannot be attributed either way") is
    # safe, and silent about the one recorded fact that settles it.
    #
    # Placed after the flat branch and before the baseline one so the flat
    # wording is untouched, and needing POSITIVE evidence exactly as the flat
    # branch does: an unwritten series says nothing and falls through, because
    # "we never measured whether it acted" is not "it did not act". works stays
    # None on this path. It never promotes a verdict — it refuses to credit a
    # movement to a technique the loop recorded as not having acted, which is
    # the same refusal _co_claimants makes when several techniques claim one
    # series, reached from the other side.
    acted, readings = _executions(res["slug"], (after[0][0], after[-1][0]))
    if readings and not acted:
        res["measured"]["executions"] = acted
        res["measured"]["execution_readings"] = readings
        res["action"] = "flag"
        res["why"] = (f"{moved}, but it acted 0 times on the {readings} day(s) of those "
                      f"{a_span}d that recorded whether it acted — so whatever moved this "
                      f"counter, this technique did not cause it")
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
        # A read-only audit is not a claimant on anything. It publishes no URL
        # and cannot move a traffic series, so listing it here does not warn a
        # reader about a rival explanation — it manufactures one. Five of the
        # nine techniques declaring `organic_visitors` are audits (see
        # _judge_audit), and counting them demoted the four that actually act
        # every night on evidence that was arithmetic rather than measurement.
        if other.get("judge") == "audit":
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


# How much of an audit's own `detail` line goes into its verdict. The verdicts
# are read in techniques.json and in the morning email, and t_frozen_pages'
# detail runs past 1,500 characters — long enough to bury every other
# technique's row. The full sentence always survives in last_run.json, which is
# where a reader who wants it goes.
AUDIT_DETAIL_CAP = 240


def _audit_reading(slug):
    """Last night's pass/fail reading for a read-only audit technique.

    Written by cmd_build into last_run.json under build.techniques.<slug> —
    {ok, detail, same_since, unchanged} — which is the only place an audit's
    own result is recorded. Audits write no per-technique series: t_crawl_paths
    has recorded exactly zero rows in results.jsonl since 2026-08-05, which is
    the whole reason this helper has to read last_run instead of the ledger.

    Returns None when there is no reading, and that is a distinct answer from a
    failing one: an audit that did not run cannot be reported green.
    """
    try:
        rec = ((ledger.read_last_run() or {}).get("build") or {})
        return (rec.get("techniques") or {}).get(slug) or None
    except Exception:
        return None


def _judge_audit(res, t):
    """Verdict for a technique that only MEASURES — it publishes nothing.

    Five active techniques are in this class: T037 crawl_paths, T072
    page_uniqueness, T089 canonical_integrity, T090 frozen_pages and T091
    voucher_reach. Every one of them reads the live docroot, writes nothing,
    and ships no URL (they are exactly techniques.DOCROOT_VERIFIERS minus
    derived_building_facts, which owns /building/ and is judged on it).

    All five declared `metric: "organic_visitors"` with no prefixes, so they
    fell through to the site-wide path and were handed the site's own traffic
    as their verdict. That is wrong twice over.

      * It is unfalsifiable in the wrong direction. An audit cannot move
        organic_visitors; it has no pages for anyone to visit. So a rising
        site-wide series credits it with a lift it cannot have caused, and a
        falling one convicts it of a failure that is not its own. T037 was
        recorded WORKS on 2026-09-04 on "organic_visitors 9.5/day vs 2.5/day"
        on a week when gsc_nonbranded_clicks was 0 and every indexing series
        it claims to influence was moving the other way — the 2026-09-04 entry
        had to write "DISTRUST ITS WORKS VERDICT" into the ledger by hand.
      * It poisoned the four techniques that DO act. _co_claimants counts
        every active prefix-less technique on the same metric, so these five
        audits sat in the co-claimant list of T004 sitemap_daily, T005
        indexnow, T010 gsc_integration and T015 dataset_schema_ai_citation,
        inflating it to eight and demoting those four every single night. Of
        the nine claimants on organic_visitors, five could never have been
        candidates for causing anything.

    So `judge: "audit"` says: report this technique's own nightly reading and
    nothing else. No traffic series is consulted, `action` is always "keep",
    and _co_claimants skips it so it stops diluting the techniques it was
    never competing with.

    `works` stays None on every path, deliberately. A green audit is a
    statement about the CORPUS ("no canonical defects tonight"), not evidence
    that the audit earns its place; the thing that would earn it is a count of
    defects it has caught and nothing records that. Writing True off a green
    read would be the same false-positive-that-breeds this module's docstring
    exists to prevent. If an audit should ever be retired, that is a judgement
    a person makes in the journal, which is the honest place for it.
    """
    rd = _audit_reading(t["slug"])
    res["action"] = "keep"
    res["measured"] = {"judged_on": "its own nightly audit reading",
                       "publishes_urls": False}
    if not rd:
        res["why"] = ("audits only and publishes nothing, so no traffic series can "
                      "measure it — and last_run.json carries no reading for it, so "
                      "there is nothing to report tonight either")
        return res
    detail = str(rd.get("detail") or "").strip()
    if len(detail) > AUDIT_DETAIL_CAP:
        detail = detail[:AUDIT_DETAIL_CAP].rstrip() + "… (full line in last_run.json)"
    ok = rd.get("ok")
    res["measured"]["audit_ok"] = ok
    res["measured"]["audit_detail"] = detail
    if rd.get("same_since"):
        res["measured"]["audit_same_reading_since"] = rd["same_since"]
    state = "GREEN" if ok else ("FAILING" if ok is False else "no pass/fail recorded")
    res["why"] = (f"audits only and publishes nothing, so it is judged on its own "
                  f"nightly reading rather than on traffic it cannot cause — "
                  f"{state}: {detail or 'no detail recorded'}")
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

    # Ahead of the grace check on purpose. GRACE_DAYS exists so a slow-moving
    # traffic series is not read too early; an audit has no traffic series at
    # all, so "under the 21d grace period" would promise a traffic verdict that
    # is never coming. Its own reading is meaningful on night one. See
    # _judge_audit for the five techniques in this class and why they were
    # being judged on numbers they cannot move.
    if t.get("judge") == "audit":
        return _judge_audit(res, t)

    # AN ACTIVE TECHNIQUE WITH NO ACTIVATION CLOCK IS UNJUDGEABLE, AND THE
    # GRACE PERIOD WAS HIDING THAT. _days_active returns 0 when `activated` is
    # missing or unreadable, which is indistinguishable from "activated
    # today", so the grace check below answered "only 0d active" every night
    # forever. Never judged — and never retired either, because every
    # retirement path lies below this point.
    #
    # T016 embeddable_building_lookup_widget sat in that state for its whole
    # life: active, 253 readings of its own series recorded from 2026-09-12,
    # every verdict discarded, `verdict` still null on 2026-10-25. The
    # 2026-08-13 entry hit the SAME hole one field over — T015 and T016 were
    # active with `revisit_on` null, so revisit_due() skipped them — and named
    # the cause exactly right: the hole opens whenever a technique is made
    # active by hand-editing the ledger instead of through set_status(), which
    # stamps `activated` and `revisit_on` together. That fix set revisit_on and
    # left activated null, so the technique came up for revisit on a clock it
    # still could not be judged against.
    #
    # A FLAG, not a keep. A missing clock is a ledger defect with a one-line
    # remedy, and flags are surfaced in the daily report beside the
    # retirements (see run()) where someone can act on it, while a keep is
    # silent by design. works stays None and `measured` stays empty, so this
    # announces the defect and writes NO verdict — there is nothing measured
    # to write, and run() only calls set_verdict when measured is non-empty.
    if _activation_clock(t) is None:
        res["action"] = "flag"
        res["why"] = (f"ACTIVE WITH NO ACTIVATION DATE — `activated` is "
                      f"{t.get('activated')!r} in the ledger, so the {GRACE_DAYS}d grace "
                      f"clock reads 0d every night and this technique can be neither "
                      f"judged nor retired, however long it runs. Its readings are being "
                      f"recorded and discarded. Stamp the date it really went live "
                      f"(ledger.set_status stamps it on promotion; a hand-edited status "
                      f"does not) and the verdict paths below become reachable")
        return res

    if days < GRACE_DAYS:
        res["action"] = "keep"
        res["why"] = f"only {days}d active — under the {GRACE_DAYS}d grace period"
        return res

    # OWNING URLS AND BEING JUDGED ON THEIR TRAFFIC ARE TWO DIFFERENT CLAIMS,
    # and until now `prefixes` asserted both. That is right for nearly
    # everything here — a section exists to draw traffic to itself — but it has
    # no answer for a technique whose whole hypothesis is site-level. The case
    # that forced it is T085 provenance_page: one page, linked from every
    # footer, whose claim is that the site is refused wholesale on trust and
    # that publishing its sources changes that. Judged on visits to
    # /methodology/ it would be retired at day 21 for not being a traffic page,
    # which is not a finding about the hypothesis at all — it is the instrument
    # answering a question nobody asked.
    #
    # So `judge: "site"` says "own these URLs, but judge me on my declared
    # metric". prefixes still do their other jobs — t_crawl_paths audits the
    # section for reachability, find_redundant sees the overlap — while the
    # verdict comes from the site-wide path below, which flags but never
    # retires. The default is unchanged: absent the field, prefixes win exactly
    # as before, so no existing technique moves. Deliberately NOT inferred from
    # `metric` alone: T023 city_guides carries prefixes and metric
    # "organic_visitors", and it is better judged on its owned path than thrown
    # onto the seven-way site-wide pile.
    if t.get("prefixes") and t.get("judge") != "site":
        pairs = _owned(t)
        total = sum(v for _, v in pairs)
        recent, prior, trend = _trend(pairs)
        vis = searchconsole.recent_visibility(slug, since=t.get("activated"))
        res["measured"] = {"total_owned_visitors": total,
                           "recent_median": recent, "prior_median": prior,
                           # The medians are a pair of levels; these say whether
                           # the pair is also a direction. Recorded beside them
                           # and never instead of them, the same way
                           # indexstatus.crawl_rate_report keeps the raw counts
                           # beside `comparable`.
                           "trend_comparable": trend["comparable"],
                           "trend_recent_readings": trend.get("recent_readings"),
                           "trend_prior_readings": trend.get("prior_readings"),
                           "trend_note": trend["note"],
                           "days_measured": len(pairs),
                           "owned_serving_pages": vis["pages"],
                           "owned_impressions": vis["impressions"],
                           "owned_best_position": vis["best_position"]}
        # Recorded beside the raw counts, never instead of them: the raw pair is
        # the series that goes back to the start and has to stay comparable to
        # itself. Absent on every reading before 2026-09-20 — see
        # searchconsole.recent_visibility on why brand_measured gates this.
        if vis.get("brand_measured"):
            res["measured"]["owned_nonbranded_pages"] = vis["nonbranded_pages"]
            res["measured"]["owned_nonbranded_impressions"] = vis["nonbranded_impressions"]
            res["measured"]["owned_unattributed_pages"] = vis["unattributed_pages"]
        if len(pairs) < GRACE_DAYS // 2:
            res["why"] = f"only {len(pairs)} days of measurement — not enough to judge"
            return res
        if total < MIN_TOTAL_VISITORS and (recent or 0) < MIN_RECENT_MEDIAN:
            # The visitor series says dead. Before acting on it, check that the
            # series was actually TAKEN — a median of 0 over a window the engine
            # spent mostly not running is a fact about the engine, not about the
            # technique, and the two are indistinguishable in the number itself.
            # This is the same shape as the census guard below: positive
            # evidence of no traffic, not merely an absent measurement. It is
            # placed first because it is the cheaper check and because a window
            # this thin makes every branch under it unsafe, not just the
            # retirement.
            if not trend["recent_covered"]:
                res["why"] = (f"{total} owned visitors in {days}d and a trailing median of "
                              f"{recent}/day, but that window holds only "
                              f"{trend.get('recent_readings', 0)} of its {WINDOW} days — "
                              f"the engine did not run for most of it, so the median "
                              f"measures the gap and not the technique. Nothing to retire "
                              f"on until the window refills")
                return res
            # Check the leading indicator too — a technique whose pages Google
            # serves is early, not dead, and the two look identical in a
            # visitor count of zero.
            if not vis["measured"]:
                res["why"] = (f"{total} owned visitors in {days}d, but its pages' search "
                              f"visibility has never been measured — not retiring on a "
                              f"metric with no resolution at this traffic level")
                return res
            if vis["impressions"] >= MIN_OWNED_IMPRESSIONS:
                res["action"] = "flag"
                # "Served but not clicked — rewrite the titles" is only advice
                # if somebody typed a query these pages could answer. Where the
                # whole impression count is sitelinks under "findacrib" /
                # "findacrib.com", there is no query whose title to rewrite, and
                # sending a future run to rewrite titles would spend it on a
                # page Google is not offering to anyone. Same evidence, opposite
                # instruction, so it has to be said separately.
                if vis.get("brand_measured") and not vis["nonbranded_impressions"]:
                    res["why"] = (f"{total} owned visitors in {days}d and {vis['pages']} of its "
                                  f"pages earned {vis['impressions']} search impressions — but "
                                  f"0 of those impressions came from a non-branded query "
                                  f"({vis['unattributed_pages']} of the pages had no query "
                                  f"attributed at all), so this is brand navigation reaching "
                                  f"them as sitelinks, not housing-intent visibility. Not a "
                                  f"title problem and not a retirement: nothing has been "
                                  f"measured about whether these pages can rank")
                    return res
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
        # A direction is a claim ABOUT TWO WINDOWS, so it needs both of them to
        # be windows. Where `trend["comparable"]` is False the medians still
        # stand as levels but their difference is an artifact of which nights
        # the engine ran, so no direction is asserted at all.
        direction = ""
        if recent is not None and prior is not None and trend["comparable"]:
            direction = " and rising" if recent > prior else (
                " but falling" if recent < prior else " and flat")
        # The corroborating clause on every verdict string below. It used to
        # read "N pages serving in search" off the raw page count, and on
        # 2026-09-20 that put "9 pages serving in search" on T046's WORKS when
        # all nine were brand sitelinks and gsc_serving_nonbranded was 0. A
        # verdict is read months later by someone with no memory of the day, so
        # the clause has to carry which of the two it is or it is worse than
        # absent. Where the split has not been measured the old wording stands,
        # because the old readings genuinely do not know.
        if not vis["measured"]:
            served = ""
        elif not vis.get("brand_measured") or not vis["pages"]:
            # No serving pages means there is no split to report — "0 pages
            # serving, all brand navigation" reads as a finding about brand
            # when it is a finding about nothing.
            served = f", {vis['pages']} pages serving in search"
        elif vis["nonbranded_pages"]:
            served = (f", {vis['nonbranded_pages']} of {vis['pages']} serving pages on "
                      f"non-branded queries ({vis['nonbranded_impressions']} impressions)")
        else:
            served = (f", but its {vis['pages']} serving pages earned 0 non-branded "
                      f"impressions — brand sitelinks, not search visibility")

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
        falling = (recent is not None and prior is not None
                   and trend["comparable"] and recent < prior)

        # And being alive is still not enough to call it WORKING. Every
        # technique in this ledger exists to earn search or answer-engine
        # visibility — that is what the 90% share goal measures. Where Search
        # Console has been measured for these prefixes and reports no
        # non-branded impressions at all, nobody reached these pages from a
        # housing search, so whatever the visitor count is counting, it is not
        # the thing the technique was built to cause. On this site that is
        # mostly internal navigation: 233 of 241 visitors on 2026-09-22 landed
        # on "/" and clicked through the map, which no content change to a hub
        # page caused and none would have prevented.
        #
        # The WORDING for this already landed on 2026-09-20, in the `served`
        # clause above, after T046 carried "9 pages serving in search" on a
        # WORKS verdict while all nine were brand sitelinks. Only the wording:
        # the verdict itself was left asserting True beside a clause that
        # contradicted it, which is strictly worse than either alone. This
        # closes the other half, and it is the third member of the same family
        # as 2026-08-25 (unconditional works=True), 08-26 (stocks through a
        # flow test) and 08-27 (this branch's cumulative floor).
        #
        # works=None, never False: these techniques all cleared the retirement
        # floor above, and "failed" would be its own unsupported claim. The
        # cost of the false positive is concrete — scout.py feeds the WORKS
        # list to the model under the heading ALREADY MEASURED AS WORKING, so
        # a technique that earned nothing in search becomes the template the
        # next proposals are modelled on.
        unseen = ""
        if vis["measured"] and not vis["impressions"]:
            unseen = ("its pages earned 0 search impressions over the same window, "
                      "so none of those visitors arrived from a search")
        elif vis.get("brand_measured") and vis["pages"] and not vis["nonbranded_impressions"]:
            unseen = (f"all {vis['impressions']} impressions its {vis['pages']} serving "
                      f"pages earned came from branded queries, so none of those "
                      f"visitors arrived from a housing-intent search")

        if alive_now and not falling and not unseen:
            res["works"] = True
            res["why"] = (f"{total} owned visitors in {days}d "
                          f"(median {recent}/day{direction})" + served)
        elif alive_now and not falling:
            res["works"] = None
            res["why"] = (f"{total} owned visitors in {days}d "
                          f"(median {recent}/day{direction}), but {unseen} — "
                          f"unproven rather than failed: the traffic is real and above "
                          f"the floor, but it is not evidence for a technique whose "
                          f"premise is search visibility")
        elif falling:
            res["works"] = None
            res["why"] = (f"{total} owned visitors in {days}d, but the trailing "
                          f"{WINDOW}d median is {recent}/day against {prior}/day "
                          f"in the {WINDOW}d before — the cumulative total clears "
                          f"the floor because it cannot fall, while the rate is "
                          f"declining" + served)
        else:
            res["works"] = None
            thin = ("" if trend["recent_covered"] else
                    f", though that window holds only {trend.get('recent_readings', 0)} "
                    f"of its {WINDOW} days, so some of this is nights the engine missed")
            res["why"] = (f"{total} owned visitors in {days}d clears the "
                          f"{MIN_TOTAL_VISITORS}-visitor floor, but the trailing "
                          f"{WINDOW}d median is {recent}/day — below the "
                          f"{MIN_RECENT_MEDIAN}/day that counts as alive, so the "
                          f"total is carried by days outside the window" + thin + served)
        return res

    # Site-wide technique: judged on its declared global metric, comparing the
    # trailing window against the window immediately before it was activated.
    metric = t.get("metric") or "organic_visitors"
    co = _co_claimants(t, metric, techs)
    pairs = _global(metric)
    after = [(d, v) for d, v in pairs if d >= (t.get("activated") or "")]
    pre = [(d, v) for d, v in pairs if d < (t.get("activated") or "")]
    if metric in STOCK_METRICS:
        return _guard_shared_metric(_judge_stock(res, metric, after, pre, days), metric, co)

    # Both windows cut by DATE, for the reason _trend gives at length: a slice
    # of the last WINDOW READINGS is only the last WINDOW DAYS while the engine
    # ran every night, and this path publishes the result as "in the last 14d".
    # The trailing window ends at the last reading (see _trend on why not
    # today); the baseline window ends the day before activation, which is the
    # comparison this path has always meant to make.
    _activated = _day(t.get("activated") or "")
    a_vals = _in_window(after, _latest(after), WINDOW)
    b_vals = (_in_window(pre, _activated - datetime.timedelta(days=1), WINDOW)
              if _activated else [v for _, v in pre[-WINDOW:]])
    a_med = statistics.median(a_vals) if a_vals else None
    b_med = statistics.median(b_vals) if b_vals else None
    # Totals alongside the medians, because at this traffic level the median is
    # frequently the wrong statistic and silently says "0.0" about a series that
    # is plainly moving: ai_visitors ran 0,1,0,0,0,1,1,0,0,2,2,1 over the twelve
    # days to 2026-08-24 — a median of 0.0 and a total of 8. Reporting both is
    # what stops "median 0.0/day" being read as "nothing happened".
    a_sum = sum(a_vals) if a_vals else None
    b_sum = sum(b_vals) if b_vals else None
    # Same contract as the owned-prefix path: the medians are levels, and this
    # says whether their difference is also a direction.
    a_cov, b_cov = _covered(a_vals, WINDOW), _covered(b_vals, WINDOW)
    comparable = None if not b_vals else bool(a_cov and b_cov)
    res["measured"] = {"metric": metric, "median_after": a_med, "median_before": b_med,
                       "total_after": a_sum, "total_before": b_sum,
                       "window_days": WINDOW, "days_measured": len(after),
                       "window_readings_after": len(a_vals),
                       "window_readings_before": len(b_vals),
                       "trend_comparable": comparable}
    totals = (f" [{a_sum} in the last {len(a_vals)}d"
              + (f" vs {b_sum} in the {len(b_vals)}d before]" if b_vals else "]")) if a_vals else ""
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
    if not comparable:
        # Neither "no lift" nor "works" can be asserted across windows of
        # different real length. Flag rather than keep, because an unreadable
        # comparison is a thing to fix and not a thing to pass over, and
        # works=None rather than True so scout.py's ALREADY MEASURED AS WORKING
        # list never learns from a window that was half missing.
        res["action"] = "flag"
        res["works"] = None
        res["why"] = (f"{metric} median {a_med}/day vs {b_med}/day before "
                      f"activation{totals} — but the trailing window holds "
                      f"{len(a_vals)} of {WINDOW} days and the baseline {len(b_vals)} of "
                      f"{WINDOW}, so the two are not the same length of time and the "
                      f"difference between them is not a lift either way")
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
