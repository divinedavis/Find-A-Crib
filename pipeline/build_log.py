"""Which lines of a growth-engine run log are actually work that shipped.

Both engines report a technique that had nothing to do as ok: "no page is due a
snippet rewrite" and "every queued service already has a page" are healthy
outcomes, not shipments. The owner's dashboard card is a record of what got
built, so those lines are dropped before it renders — a list of the things the
engine decided not to do reads like a list of things it failed to do.

Failures are never dropped. A technique that crashed is news the owner needs,
and hiding it would leave the card quietly wrong.

The `noop` flag on the result dict is the real signal; the text patterns are
the fallback for run logs written before the flag existed and for the Find A
Crib engine, which does not set it.
"""

import re

_NOOP_TEXT = re.compile(
    r"""
      ^(?: no | nothing | none | not\ enough )\b   # "no page is due a rewrite"
    | ^every\b .* \balready\b                      # "every queued town already has a page"
    | \balready\ (?: has | had | is | current | exists | includes | opens )\b
    | \bnothing\ (?: new | to | left )\b
    | ^\[dry-run\] | ^dry\ run\b                   # a rehearsal is not a shipment
    | \b0\ (?: page | pages | url | urls )\b       # "refreshed nearby-links on 0 page(s)"
    """,
    re.VERBOSE | re.IGNORECASE,
)


def did_work(step):
    """True when this run-log entry describes something the engine actually did."""
    if not isinstance(step, dict):
        return False
    if not step.get("ok", True):
        return True                       # a failure is real news — keep it
    if step.get("noop") or step.get("skipped"):
        return False
    # Word-for-word yesterday's line. growth_daily._stamp_unchanged sets this by
    # diffing the run against the previous last_run.json, which is the only
    # place both runs exist at once. A verifier that re-checks a block already
    # in the docroot reports the same sentence every night: true, healthy, and
    # not something the run built. Failures never carry the flag.
    if step.get("unchanged"):
        return False
    detail = (step.get("detail") or "").strip()
    if not detail:
        return False
    return not _NOOP_TEXT.search(detail)


def shipped(steps):
    """The run log with its no-op lines removed."""
    return [s for s in (steps or []) if did_work(s)]
