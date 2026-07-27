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
        source="seed", evidence="", status="candidate", notes=""):
    """Register a new technique. Returns the record (existing one if the slug
    is already known — the scout re-proposing an old idea must not duplicate it)."""
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
    """Active techniques whose scheduled second look has come due."""
    as_of = as_of or today()
    return [t for t in load_techniques()
            if t.get("status") == "active" and t.get("revisit_on")
            and t["revisit_on"] <= as_of]


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


def set_verdict(tech_id, works, why, measured=None):
    """Record the judgement. Kept separate from status so a technique can be
    'works but retired' (e.g. folded into another) without losing the finding."""
    with _LOCK:
        techs = load_techniques()
        for t in techs:
            if t["id"] == tech_id or t.get("slug") == tech_id:
                t["verdict"] = {
                    "decided": today(),
                    "works": bool(works),
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
    doc[command] = {
        "date": today(),
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        **detail,
    }
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
