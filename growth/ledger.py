#!/usr/bin/env python3
"""The technique ledger: what we've tried, what's running, and what it did.

Three files live next to this module:

  techniques.json   the registry — one record per growth technique, whatever
                    its status (candidate / active / retired).
  results.jsonl     append-only daily measurements, one JSON object per line.
                    Append-only on purpose: the year-end "what worked" list is
                    only trustworthy if nothing rewrites history.
  state.json        scratch state techniques need between runs (e.g. yesterday's
                    listing set, so today's run can diff it).

A technique record:

  id          T001, T002, … stable forever, even after retirement
  slug        matches the function name in techniques.py
  name        human label
  hypothesis  why we think this drives traffic or revenue — written BEFORE
              we measure, so the verdict can't be retrofitted
  kind        content | indexing | distribution | lifecycle | conversion
  status      candidate (proposed, not running) | active | retired
  prefixes    URL path prefixes this technique owns, for traffic attribution.
              Empty means site-wide — judged on a global metric instead.
  metric      which measured series decides the verdict (see metrics.py)
  source      seed | scout:YYYY-MM-DD  — where the idea came from
  evidence    why we believed it would work (URL or short note)
  verdict     set by review.py once there's enough data
"""
import datetime
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TECHNIQUES_PATH = os.path.join(HERE, "techniques.json")
RESULTS_PATH = os.path.join(HERE, "results.jsonl")
STATE_PATH = os.path.join(HERE, "state.json")

_LOCK = threading.Lock()

VALID_STATUS = ("candidate", "active", "retired")
VALID_KIND = ("content", "indexing", "distribution", "lifecycle", "conversion")


def today():
    return datetime.date.today().isoformat()


def now_iso():
    """UTC, to the second. The stamp every last_run record is dated with."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- techniques

def load_techniques():
    try:
        with open(TECHNIQUES_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        raise SystemExit(f"techniques.json is corrupt ({e}); refusing to overwrite it")


def save_techniques(techs):
    """Write atomically — a half-written ledger would lose the year's history."""
    tmp = TECHNIQUES_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(techs, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, TECHNIQUES_PATH)


def get(tech_id):
    for t in load_techniques():
        if t["id"] == tech_id or t.get("slug") == tech_id:
            return t
    return None


def active():
    return [t for t in load_techniques() if t.get("status") == "active"]


def next_id():
    ids = [t["id"] for t in load_techniques() if t["id"].startswith("T")]
    n = max((int(i[1:]) for i in ids if i[1:].isdigit()), default=0)
    return f"T{n + 1:03d}"


def add(slug, name, hypothesis, kind, prefixes=None, metric="owned_visitors",
        source="seed", evidence="", status="candidate", notes="", judge=None):
    """Register a new technique. Returns the record (existing one if the slug
    is already known — the scout re-proposing an old idea must not duplicate it).

    `judge="site"` means: this technique owns `prefixes` (so the crawl-path
    audit and the redundancy check still see them) but its verdict comes from
    the declared site-wide `metric`, not from traffic to those URLs. For a
    technique whose hypothesis is about the site rather than about its own
    pages, owned-visitor counting answers the wrong question. See the note in
    review.evaluate(). Absent, prefixes decide as they always have."""
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t.get("slug") == slug:
                return t
        if kind not in VALID_KIND:
            raise ValueError(f"bad kind {kind!r}, expected one of {VALID_KIND}")
        if status not in VALID_STATUS:
            raise ValueError(f"bad status {status!r}")
        rec = {
            "id": next_id(),
            "slug": slug,
            "name": name,
            "hypothesis": hypothesis,
            "kind": kind,
            "status": status,
            "prefixes": prefixes or [],
            "metric": metric,
            "source": source,
            "evidence": evidence,
            "added": today(),
            "activated": today() if status == "active" else None,
            "revisit_on": _revisit_date() if status == "active" else None,
            "retired": None,
            "notes": notes,
            "verdict": None,
        }
        if judge:
            rec["judge"] = judge
        techs.append(rec)
        save_techniques(techs)
        return rec


# How long after activation a technique gets a deliberate second look. The
# 21-day review grace period asks "is this dead?"; a revisit asks the different
# and more useful question "is this the best version of this idea, and should it
# be replaced?" Without a date attached, that question never gets asked again.
REVISIT_DAYS = 30


def _revisit_date(days=REVISIT_DAYS):
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def set_revisit(tech_id, on=None, days=REVISIT_DAYS):
    """Schedule (or push forward) the next deliberate review of a technique."""
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t["id"] == tech_id or t.get("slug") == tech_id:
                t["revisit_on"] = on or _revisit_date(days)
                save_techniques(techs)
                return t
    return None


def revisit_due(as_of=None):
    """Techniques whose scheduled second look has come due.

    Includes ones the automatic review already retired, and that is the point.

    The two mechanisms were wired so the cheap one always won a race the
    deliberate one could not see. review.py retires on GRACE_DAYS = 21 days
    after activation; _revisit_date() schedules the second look for
    REVISIT_DAYS = 30. So on the default dates the automatic retirement fires
    exactly nine days before every scheduled revisit, and because this function
    used to filter to status == "active", retirement then cancelled the revisit
    outright. Not "delayed" — cancelled, silently, with the date still sitting
    in the record.

    That is not hypothetical. Every retirement this loop has ever made landed
    nine days early and cancelled the review that had been booked for it:
    T001 and T002 retired 2026-08-16 against revisits scheduled 2026-08-25,
    T023 retired 08-19 against 08-28, T013 retired 08-20 against 08-29. T001's
    own notes had recorded an explicit condition and date for the decision —
    "NEW DECISION DATE 2026-08-26: if /section8/ still earns zero impressions
    21 days after it has a verified inbound link" — and the machine retired it
    on the metric that note had already ruled out, ten days early, during the
    24 days the corpus was frozen so the inbound link it was waiting on had
    never deployed. The reasoning was in the ledger and was never re-read.

    So a retirement now defers the second look rather than deleting it. The
    revisit asks a different question from the review — "is this still the best
    version of this idea?" — and a verdict of "no" is a perfectly good input to
    it. What is not a good input is silence.

    Bounded on purpose: a retired technique comes due only if it was retired
    BEFORE its own revisit date, i.e. only where the retirement is what
    pre-empted the second look. One retired after its revisit date already had
    that look, and does not come back.
    """
    as_of = as_of or today()
    out = []
    for t in load_techniques():
        on = t.get("revisit_on")
        if not on or on > as_of:
            continue
        status = t.get("status")
        if status == "active":
            out.append(t)
        elif status == "retired" and (t.get("retired") or "") < on:
            out.append(t)
    return out


def set_status(tech_id, status, why=""):
    if status not in VALID_STATUS:
        raise ValueError(f"bad status {status!r}")
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t["id"] == tech_id or t.get("slug") == tech_id:
                prev = t.get("status")
                t["status"] = status
                if status == "active" and not t.get("activated"):
                    t["activated"] = today()
                if status == "active" and not t.get("revisit_on"):
                    t["revisit_on"] = _revisit_date()
                if status == "retired":
                    t["retired"] = today()
                if why:
                    t["notes"] = (t.get("notes", "") + f"\n[{today()}] {prev}→{status}: {why}").strip()
                save_techniques(techs)
                return t
    return None


def note(tech_id, text):
    """Append a dated line to a technique's notes without changing anything else.

    Revisits mostly produce reasoning, not status changes, and until now the
    only way to record one was to flip a status you did not want to flip.

    THIS DOES NOT ALWAYS SURVIVE. seed.run() re-applies `notes` from
    growth/seed.py on every build for any slug where that file declares one, so
    a note appended here to a SEEDED technique is silently reverted by the next
    run — no error, no log line, and the ledger then reads as though the revisit
    never happened. Discovered 2026-08-27, when two of four revisit notes
    written this way vanished on the next build; it is the same trap 08-26
    documented for `metric` in set_metric(), reached by a different door, and it
    is exactly how a past entry came to claim a fix its diff never made.

    So this warns when the target is seeded with notes. If you see that warning,
    put the text in growth/seed.py instead — that file is the source of truth —
    and re-read the ledger AFTER a build, not after the write.
    """
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t["id"] == tech_id or t.get("slug") == tech_id:
                t["notes"] = (t.get("notes", "") + f"\n[{today()}] {text}").strip()
                save_techniques(techs)
                if _seed_owns_notes(t.get("slug")):
                    print(f"  WARNING: {t.get('slug')} declares notes in growth/seed.py — "
                          f"this note will be REVERTED by the next build. Put it in seed.py.")
                return t
    return None


def _seed_owns_notes(slug):
    """True when growth/seed.py declares a notes= for this slug, so seed.run()
    will overwrite whatever note() just appended.

    Imported lazily and defensively: seed imports this module at load time, so a
    module-level import here would be circular, and a failure to answer the
    question must never be the reason a note does not get written.
    """
    try:
        from . import seed
        for s in seed.SEEDS:
            if s.get("slug") == slug:
                return bool(s.get("notes"))
    except Exception:
        return False
    return False


def reactivate(tech_id, why=""):
    """Bring a retired technique back, with its measurement clock restarted.

    Deliberately NOT the same as set_status(id, "active"), and the difference
    decides whether a revisit means anything. set_status leaves `activated` at
    the original date, so a technique revived after 30 days is already past
    GRACE_DAYS the moment it comes back: review.py judges it on the next run,
    finds the same flat series the revisit just rejected as unsound, and
    retires it again before the second run has produced a single day of its own
    evidence. The revival would survive about 24 hours and look, in the ledger,
    like the revisit had agreed with the retirement.

    So the clock restarts. `first_activated` keeps the original date — the
    history is not rewritten — and the stale verdict is cleared rather than
    left standing, because it describes a run that has been deliberately
    superseded and would otherwise keep the technique in the scoreboard's
    failure column and on the scout's "do not propose again" list while it is
    being actively retried.
    """
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t["id"] == tech_id or t.get("slug") == tech_id:
                prev = t.get("status")
                if not t.get("first_activated"):
                    t["first_activated"] = t.get("activated")
                t["status"] = "active"
                t["activated"] = today()
                t["retired"] = None
                t["verdict"] = None
                t["revisit_on"] = _revisit_date()
                t["notes"] = (t.get("notes", "")
                              + f"\n[{today()}] {prev}→active (clock restarted, "
                                f"first activated {t.get('first_activated')}): {why}").strip()
                save_techniques(techs)
                return t
    return None


def set_metric(tech_id, metric, why=""):
    """Repoint a site-wide technique at a different global series.

    This is a bigger act than it looks, so it is a named operation rather than
    an edit to techniques.json. A verdict is a sentence about a metric: "no
    measurable lift" is a claim about the series it was measured on and about
    nothing else. Leave the old verdict standing under a new metric and the
    ledger asserts something no measurement supports — which is how T011 came
    to carry "mrr_usd median 0.0/day" when mrr_usd was, by construction,
    incapable of containing the one-time revenue that technique exists to
    produce. So the stale verdict is cleared here, and the change is dated in
    the notes where the next reader will trip over it.

    The old metric's history is untouched: results.jsonl is append-only and the
    series stays readable, so a future review can always ask what the previous
    instrument said.

    CALLING THIS ALONE IS NOT ENOUGH FOR A SEEDED TECHNIQUE, and the failure is
    silent. seed.run() re-applies `metric` from growth/seed.py on every single
    run — it is deliberately the source of truth for a seeded technique's
    wording — so a metric changed only here reverts on the next build with no
    error and no log line. That is exactly what happened on 2026-08-26: T011 and
    T018 were repointed, verified as changed, and were back to mrr_usd and
    visitors an hour later, while the notes explaining the change survived, so
    the ledger read as though the change had been made. Change SEEDS in seed.py
    in the same commit, then call this. Scout-proposed techniques are not
    seeded and do not have this problem.
    """
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t["id"] == tech_id or t.get("slug") == tech_id:
                prev = t.get("metric")
                if prev == metric:
                    return t
                t["metric"] = metric
                t["verdict"] = None
                t["notes"] = (t.get("notes", "")
                              + f"\n[{today()}] metric {prev} → {metric}; prior verdict "
                                f"cleared because it was decided against {prev}: {why}").strip()
                save_techniques(techs)
                return t
    return None


def set_verdict(tech_id, works, why, measured=None):
    """Record the judgement. Kept separate from status so a technique can be
    'works but retired' (e.g. folded into another) without losing the finding.

    works is tri-state: True, False, or None for "judged and not established".
    Do not coerce None to False — see the note at the top of review.py. A
    technique nobody could measure has not failed, and filing it under failure
    would retire ideas for the sins of the instrument.
    """
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t["id"] == tech_id or t.get("slug") == tech_id:
                t["verdict"] = {
                    "decided": today(),
                    "works": None if works is None else bool(works),
                    "why": why,
                    "measured": measured or {},
                }
                save_techniques(techs)
                return t
    return None


# ------------------------------------------------------------------ results

def record_result(date, technique, metric, value, meta=None):
    """Append one measurement. Idempotent per (date, technique, metric): a
    re-run of the same day overwrites nothing but is de-duplicated on read."""
    row = {"date": date, "technique": technique, "metric": metric,
           "value": value, "meta": meta or {},
           "written": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    with _LOCK:
        with open(RESULTS_PATH, "a") as f:
            f.write(json.dumps(row) + "\n")
    return row


def read_results(technique=None, metric=None, since=None):
    """Read measurements, newest write winning for a given (date, technique, metric)."""
    try:
        with open(RESULTS_PATH) as f:
            rows = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []
    dedup = {}
    for r in rows:
        dedup[(r["date"], r["technique"], r["metric"])] = r   # later line wins
    out = list(dedup.values())
    if technique:
        out = [r for r in out if r["technique"] == technique]
    if metric:
        out = [r for r in out if r["metric"] == metric]
    if since:
        out = [r for r in out if r["date"] >= since]
    return sorted(out, key=lambda r: r["date"])


def series(technique, metric, since=None):
    """[(date, value), …] for one technique+metric."""
    return [(r["date"], r["value"]) for r in read_results(technique, metric, since)]


# -------------------------------------------------------------------- state

def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


def get_state(key, default=None):
    return load_state().get(key, default)


# ----------------------------------------------------------------- last run

# state.json is gitignored (it carries per-URL content hashes and visitor ids),
# so the cloud review agent cannot see it and has no way to tell whether the
# droplet crons actually ran. This file is the sanitized, git-tracked answer:
# no hashes, no ids, just what happened and when. Without it the agent reads an
# absent state.json as "no build has ever executed" and raises a false alarm.
LAST_RUN_PATH = os.path.join(HERE, "last_run.json")


def write_last_run(command, detail):
    try:
        with open(LAST_RUN_PATH) as f:
            doc = json.load(f)
    except Exception:
        doc = {}
    doc[command] = {"date": today(), "at": now_iso(), **detail}
    tmp = LAST_RUN_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, LAST_RUN_PATH)
    return doc


def patch_last_run(command, detail):
    """Merge fields into an existing last_run record without restamping it.

    write_last_run() above always sets `date` and `at` to now, which is right
    for "this command just finished" but wrong for a correction applied after
    the fact. The build's record carries two fields — seo_corpus and
    seo_pipeline — that describe a SECOND pipeline's state at the moment the
    build read the docroot, and growth_run.sh's SEO watchdog then re-runs that
    pipeline immediately afterwards. So on exactly the mornings the watchdog
    works, the committed record still says the corpus is frozen (2026-08-20:
    heartbeat seo_watchdog_finish rc=0 at 05:41:24, last_run.json build
    seo_pipeline "NO RUN FOR 2.0 DAYS"). This lets the watchdog correct those
    two fields in place while `at` keeps meaning "when the build ran".

    Returns the whole document. A record that does not exist yet is created
    with today's date, so this is safe to call unconditionally.
    """
    try:
        with open(LAST_RUN_PATH) as f:
            doc = json.load(f)
    except Exception:
        doc = {}
    rec = doc.get(command)
    if not isinstance(rec, dict):
        rec = {"date": today(), "at": now_iso()}
    rec.update(detail)
    doc[command] = rec
    tmp = LAST_RUN_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, LAST_RUN_PATH)
    return doc


def read_last_run():
    try:
        with open(LAST_RUN_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def set_state(key, value):
    with _LOCK:
        s = load_state()
        s[key] = value
        save_state(s)
