#!/usr/bin/env python3
"""NEMO Seamless Gutter traffic, for the owner dashboard's second tab.

Both sites live on this droplet, so the Find A Crib API can read NEMO's numbers
directly instead of standing up a second dashboard app. The dashboard renders
whichever payload it is given through the same template; this module's job is to
hand it NEMO data in the shape that template already understands.

Four sources, in the order they are trusted:

  growth/results.jsonl   the append-only daily ledger the 6am growth engine
                         writes. Bot-filtered, owner-IP-filtered, already
                         judged — this is the history.
  nginx access log       parsed live for TODAY only, because the ledger is
                         written once a morning for the *previous* day and a
                         dashboard that says "live" must not be 18 hours stale.
  growth/snapshot.json   rank/GSC/goal state, refreshed each morning.
  ElevenLabs history     calls into the AI phone assistant, via NEMO's own
                         growth.calls. This — not bookings — is the demand
                         number the tiles lead with: the assistant is forbidden
                         from booking anything, and a caller who hangs up
                         before leaving a message is still the phone ringing.
                         Owner and test numbers are excluded there, not here.

Today's live number is computed by importing NEMO's own growth.metrics rather
than reimplementing its bot regex and channel rules here — two copies of that
logic would drift, and then the dashboard and the morning report would disagree
about the same day. The import is done by file path under a private module name
(`nemo_growth`) because this API's own repo also contains a `growth` package;
a plain `import growth.metrics` would resolve to the wrong one.

Nothing here reads customer rows. Calls, bookings and leads are counted, never
listed: this endpoint returns no names, phones or addresses.
"""
import datetime
import importlib.util
import json
import os
import sqlite3
import sys
import threading
import time

import build_log

NEMO_ROOT = os.environ.get("NEMO_ROOT", "/var/www/nemo-seamless-gutter")
RESULTS = os.path.join(NEMO_ROOT, "growth", "results.jsonl")
SNAPSHOT = os.path.join(NEMO_ROOT, "growth", "snapshot.json")
BOOKINGS_DB = os.environ.get("NEMO_BOOKINGS_DB",
                             os.path.join(NEMO_ROOT, "server", "bookings.sqlite"))

# Parsing a day of access log on every dashboard load would make the page slow
# and the log re-read pointless — the numbers only move as fast as traffic does.
#
# The TTL alone wasn't enough: the request that arrived after it expired paid
# the whole rebuild — the ElevenLabs listing plus a detail lookup per unknown
# call — which took 3–14 s in the access log and froze the dashboard's site
# switcher for exactly that long. Expiry now serves the stale payload
# immediately and rebuilds on a background thread, and the payload is persisted
# beside this file so a recycled gunicorn worker starts from the last answer
# instead of from nothing. Only the first build after a deploy ever blocks.
CACHE_TTL = 120
_CACHE = {"at": 0.0, "data": None}
_LOCK = threading.Lock()
_REFRESHING = False
PAYLOAD_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "nemo_payload_cache.json")

CHANNELS = [
    ("organic", "Organic search", "#eda100"),
    ("local", "Local listings / maps", "#1baf7a"),
    ("ai", "AI assistants", "#8a5cf0"),
    ("direct", "Direct / typed-in", "#2a78d6"),
    ("referral", "Other referral", "#e87ba4"),
    ("campaign", "Tagged campaign", "#eb6834"),
    ("internal", "Internal / same-site", "#9a99a5"),   # derived, see build()
]


# ---------------------------------------------------------------- ledger read
def _daily_series():
    """{date: {metric: value}} for site-wide metrics, oldest first."""
    out = {}
    try:
        with open(RESULTS) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("technique") != "__site__":
                    continue
                # Append-only file: a later line for the same (date, metric)
                # is a correction, so last write wins.
                out.setdefault(r["date"], {})[r["metric"]] = r.get("value")
    except FileNotFoundError:
        return {}
    return out


def _snapshot():
    try:
        with open(SNAPSHOT) as f:
            return json.load(f)
    except Exception:
        return {}


# ------------------------------------------------------------------ live day
def _nemo_growth(sub):
    """Import a submodule of NEMO's growth package under a private name, or None."""
    pkg_dir = os.path.join(NEMO_ROOT, "growth")
    init = os.path.join(pkg_dir, "__init__.py")
    if not os.path.exists(init):
        return None
    name = "nemo_growth"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, init, submodule_search_locations=[pkg_dir])
        if spec is None or spec.loader is None:
            return None
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[name] = pkg
        try:
            spec.loader.exec_module(pkg)
        except Exception:
            sys.modules.pop(name, None)
            return None
    try:
        return importlib.import_module(name + "." + sub)
    except Exception:
        return None


def _nemo_growth_metrics():
    """Import NEMO's growth.metrics under a private name, or None."""
    return _nemo_growth("metrics")


def _today_live():
    """Today so far, straight from the access log. ({} if unavailable.)"""
    m = _nemo_growth_metrics()
    if m is None:
        return {}
    today = datetime.date.today()
    try:
        data = m.collect(days=1, end=today)
    except Exception:
        return {}
    return data.get(today.isoformat(), {})


def _all_time_leads():
    """Bookings and phone leads ever taken. Counts only — no customer rows.

    Delegates to NEMO's own lead_totals when it imports, so the dashboard and
    the morning report apply the same owner/test-row exclusions. The direct
    read below is the fallback and deliberately counts everything: better an
    obviously-too-high number than a silently different one.
    """
    m = _nemo_growth_metrics()
    if m is not None:
        try:
            return m.lead_totals()
        except Exception:
            pass
    out = {"bookings_all_time": 0, "phone_leads_all_time": 0}
    if not os.path.exists(BOOKINGS_DB):
        return out
    try:
        con = sqlite3.connect(f"file:{BOOKINGS_DB}?mode=ro", uri=True, timeout=5)
    except Exception:
        return out
    try:
        for table, key in (("bookings", "bookings_all_time"),
                           ("leads", "phone_leads_all_time")):
            try:
                out[key] = con.execute(f"select count(*) from {table}").fetchone()[0]
            except sqlite3.Error:
                pass
    finally:
        con.close()
    return out


# ------------------------------------------------------------------ assembly
def _n(x):
    return x if isinstance(x, (int, float)) else 0


def _calls(dates, today_key):
    """AI phone calls: all-time, this period, and today. Counts only.

    Delegated wholesale to NEMO's growth.calls so the owner-number exclusion is
    applied in exactly one place. A missing key or an unreachable API leaves the
    counts at zero and raises a warning rather than failing the page — the
    dashboard saying "0 calls" with a note beats it saying nothing at all.
    """
    out = {"all_time": 0, "own_excluded": 0, "period": 0, "today": 0, "ok": False}
    mod = _nemo_growth("calls")
    if mod is None:
        return out
    st = {}
    try:
        rows = mod.fetch(status=st)
        totals = mod.call_totals(rows, refresh=False)
        by_day = mod.calls_by_day(sorted(set(dates) | {today_key}), rows, refresh=False)
    except Exception:
        return out
    # A revoked key and a quiet phone both come back as zero calls, so the tile
    # is only trustworthy when the fetch actually reached ElevenLabs.
    if not st.get("ok"):
        return out
    out["ok"] = True
    out["all_time"] = _n(totals.get("ai_calls_all_time"))
    out["own_excluded"] = _n(totals.get("own_calls_excluded"))
    out["today"] = _n((by_day.get(today_key) or {}).get("ai_calls"))
    out["period"] = sum(_n((by_day.get(d) or {}).get("ai_calls")) for d in set(dates))
    return out


def build(days=14):
    """The dashboard view model for NEMO."""
    hist = _daily_series()
    today_key = datetime.date.today().isoformat()
    live = _today_live()
    warnings = []
    if not live:
        warnings.append("Today's live traffic could not be read from the access log.")

    # History, excluding today — today comes from the live parse so the two
    # never double-count the same visitors.
    # A day with no visitors AND no bot hits was not a quiet day, it was a day
    # with no measurement: NEMO's dedicated nginx access_log did not exist until
    # 2026-07-27, and every genuinely measured day logs ~2,000 bot hits. Keeping
    # those rows made the board claim "Since July 25" for data that starts on
    # the 27th, and dragged every per-day average down with two phantom zeros.
    traffic_days = sorted(d for d, m in hist.items()
                          if "visitors" in m and d != today_key
                          and not (_n(m.get("visitors")) == 0
                                   and _n(m.get("bot_hits")) == 0))
    rows = [{"date": d,
             "visitors": _n(hist[d].get("visitors")),
             "views": _n(hist[d].get("pageviews"))} for d in traffic_days]
    if live:
        rows.append({"date": today_key,
                     "visitors": _n(live.get("visitors")),
                     "views": _n(live.get("pageviews"))})

    spark = rows[-days:]

    totals = {
        "visitors": sum(r["visitors"] for r in rows),
        "views": sum(r["views"] for r in rows),
        "bots": sum(_n(hist[d].get("bot_hits")) for d in traffic_days) + _n(live.get("bot_hits")),
        "call_taps": (sum(_n(hist[d].get("call_taps")) for d in traffic_days)
                      + _n(live.get("call_taps"))),
    }

    # Call conversion — of the people who reached the site, how many opened the
    # dialer. On a contractor site this is the number that matters: a visitor
    # who does not ring is worth nothing, and ranking improvements are only
    # real if this moves with them.
    #
    # Measured from the tel: beacon in analytics.js, so it starts at the day
    # that shipped (2026-07-30) and has no history before it. `measured_since`
    # exists so the UI can say that instead of drawing a flat zero back to July
    # and implying nobody ever called.
    tap_days = sorted(d for d, m in hist.items() if "call_taps" in m and d != today_key)
    if live and "call_taps" in live:
        tap_days.append(today_key)
    measured_visitors = (sum(_n(hist[d].get("visitors")) for d in tap_days if d != today_key)
                         + (_n(live.get("visitors")) if today_key in tap_days else 0))
    totals["call_conversion"] = {
        "taps": totals["call_taps"],
        # Rate against visitors in the measured window only — dividing new taps
        # by all-time visitors would understate it forever.
        "visitors": measured_visitors,
        "pct": round(100.0 * totals["call_taps"] / measured_visitors, 1) if measured_visitors else None,
        "measured_since": tap_days[0] if tap_days else None,
        "today_taps": _n(live.get("call_taps")),
    }

    channels = {}
    for key, _name, _hex in CHANNELS:
        if key == "internal":
            continue
        channels[key] = sum(_n(hist[d].get(key + "_visitors")) for d in traffic_days) \
            + _n(live.get(key + "_visitors"))
    # NEMO's growth engine classifies a same-site referrer as "internal" but
    # doesn't record that series, so the six named channels come up short of the
    # visitor count. The remainder is that bucket — derived rather than dropped,
    # so the donut adds up to the number on the tile instead of quietly losing
    # a third of the traffic.
    channels["internal"] = max(0, totals["visitors"] - sum(channels.values()))

    # Leads: the ledger has a per-day series, the database has the truth about
    # all-time. Both are shown, because "2 bookings ever" and "0 today" answer
    # different questions.
    leads_days = sorted(d for d, m in hist.items() if "total_leads" in m and d != today_key)
    period_bookings = sum(_n(hist[d].get("bookings")) for d in leads_days) + _n(live.get("bookings"))
    period_phone = sum(_n(hist[d].get("phone_leads")) for d in leads_days) + _n(live.get("phone_leads"))
    all_time = _all_time_leads()

    # Calls into the AI. Counted over the same window the traffic tiles cover so
    # "calls in this period" and "visitors" answer the same question, and read
    # straight from ElevenLabs rather than from the ledger — the ledger only
    # learns yesterday's number at 6am and this tile is on the live page.
    call_dates = [r["date"] for r in rows] or [today_key]
    calls = _calls(call_dates, today_key)
    if not calls["ok"]:
        warnings.append("Call history could not be read from the phone assistant.")

    snap = _snapshot()
    goal = snap.get("goal") or {}
    gsc = snap.get("gsc") or {}
    pages = snap.get("pages") or {}
    page_counts = {k: len(v) for k, v in pages.items() if isinstance(v, list)}
    last_build = snap.get("last_build") or {}

    return {
        "site": "nemo",
        "domain": snap.get("site") or "nemoseamlessgutter.com",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "since": rows[0]["date"] if rows else None,
        "live": bool(live),
        "totals": totals,
        "today": {
            "visitors": _n(live.get("visitors")),
            "views": _n(live.get("pageviews")),
            "ai_calls": calls["today"],
            "bookings": _n(live.get("bookings")),
            "phone_leads": _n(live.get("phone_leads")),
            "organic": _n(live.get("organic_visitors")),
            "call_taps": _n(live.get("call_taps")),
            "bots": _n(live.get("bot_hits")),
        },
        "channels": channels,
        "sparkline": spark,
        "leads": {
            "ai_calls_all_time": calls["all_time"],
            "period_calls": calls["period"],
            "own_calls_excluded": calls["own_excluded"],
            "calls_ok": calls["ok"],
            "period_bookings": period_bookings,
            "period_phone": period_phone,
            "bookings_all_time": _n(all_time.get("bookings_all_time")),
            "phone_leads_all_time": _n(all_time.get("phone_leads_all_time")),
            "own_rows_excluded": _n(all_time.get("own_rows_excluded")),
        },
        "search": {
            "share_pct": goal.get("share_pct"),
            "target_pct": goal.get("target_pct"),
            "top3": goal.get("top3"),
            "top10": goal.get("top10"),
            "tracked_queries": goal.get("tracked_queries"),
            "coverage_pct": goal.get("coverage_pct"),
            "statement": goal.get("statement"),
            "clicks": gsc.get("clicks"),
            "impressions": gsc.get("impressions"),
            "avg_position": gsc.get("avg_position"),
            "connected": bool(gsc.get("connected")),
            "gsc_date": gsc.get("date"),
        },
        "pages": {"counts": page_counts, "total": sum(page_counts.values())},
        "build": {
            "date": last_build.get("date"),
            # Only what the run actually shipped. A technique that found nothing
            # to do reports ok with a "no page is due a rewrite" detail; listing
            # those alongside real work turns the card into a list of non-events.
            "steps": [s.get("detail")
                      for s in build_log.shipped(last_build.get("log"))
                      if s.get("ok") and s.get("detail")][:6],
        },
        "warnings": warnings,
    }


def _store(data):
    with _LOCK:
        _CACHE["at"] = time.time()
        _CACHE["data"] = data
    tmp = PAYLOAD_CACHE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, PAYLOAD_CACHE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _refresh_bg(days):
    global _REFRESHING
    try:
        _store(build(days=days))
    except Exception:
        pass
    finally:
        with _LOCK:
            _REFRESHING = False


def build_cached(days=14):
    global _REFRESHING
    now = time.time()
    with _LOCK:
        data, at = _CACHE["data"], _CACHE["at"]

    if data is None:
        # Fresh process: the last payload another worker (or a previous life of
        # this one) persisted is a better answer than a 14 s rebuild.
        try:
            with open(PAYLOAD_CACHE) as f:
                disk = json.load(f)
        except Exception:
            disk = None
        if isinstance(disk, dict):
            with _LOCK:
                if _CACHE["data"] is None:
                    _CACHE["data"] = disk       # at stays 0.0 → refresh below
                data, at = _CACHE["data"], _CACHE["at"]

    if data is not None:
        if now - at < CACHE_TTL:
            return data
        # Stale: hand it over now, rebuild behind the response. One refresh at
        # a time — a second expired request must not start a second rebuild.
        with _LOCK:
            kick = not _REFRESHING
            if kick:
                _REFRESHING = True
        if kick:
            threading.Thread(target=_refresh_bg, args=(days,), daemon=True).start()
        return data

    # Nothing in memory or on disk — first build after a deploy pays once.
    data = build(days=days)
    _store(data)
    return data


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
