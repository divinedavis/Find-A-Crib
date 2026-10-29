#!/usr/bin/env python3
"""Email the owner when users hit errors — web, mobile web and the iPhone app.

Runs on the droplet (cron in deploy/cron-rentmap-errors). Five sources:

  1. `public.events` — js_error (web), crash_trace (a page that never said
     goodbye), push_register_failed / purchase / signin failures (iOS).
  2. nginx — 5xx served to real people on findacrib.com and /api/.
  3. journalctl -u findacrib-api — Python tracebacks behind those 5xx.
  4. The feeds' own files in the docroot — a scrape that died leaves the app
     showing yesterday's listings, which is a user-facing error nobody
     reports. (This was documented as reading the feeds' cron LOGS, and a
     FEED_LOGS table sat here for weeks to say so; nothing ever read it.
     stale_feeds() has always checked the output files' mtimes instead, which
     is the better test — a cron that runs and writes nothing is still a dead
     feed — so the table is gone and the docstring now matches the code.)
  5. The growth engine's own heartbeat — see dead_crons().

It is quiet on purpose. A run mails only when something is worth waking up
for — a NEW JavaScript message, a 5xx burst, a traceback, a crash-shaped
trace, or a feed that stopped — and `--digest` mails a once-a-day summary of
whatever is still open. Nothing to say means no email (owner's rule: never
report a no-op).

    python3 error_report.py                 # alert mode, last 60 minutes
    python3 error_report.py --hours 24 --digest
    python3 error_report.py --dry-run       # print, never send

Reading crash_trace: index.html keeps a breadcrumb trail in localStorage and
reports it on the next boot if the last step is not `pagehide`. That over-
counts badly — iOS Safari fires `visibilitychange` AFTER `pagehide`, and a
suspended tab's 1-second tick can land after it too, so a clean exit often
looks like a crash. Only a trace with NO pagehide at all AND a last step that
is real work (a render, a boot, a map resize) is counted here.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dbaifotzwlxjvsxjohjt.supabase.co")
STATE = Path(os.environ.get("ERROR_STATE", "/var/lib/findacrib/error_report_state.json"))
NGINX_LOGS = ["/var/log/nginx/access.log", "/var/log/nginx/findacrib.access.log"]
APPSTORE_JSON = os.environ.get("APPSTORE_JSON", "/root/findacrib-api/appstore.json")
RELEASE_FLOOR = 3      # people on one unreleased build before it counts as users

# The growth engine's liveness record, written by growth_run.sh in this same
# checkout. Overridable only for testing; on the droplet it is always here.
HEARTBEAT = Path(os.environ.get("GROWTH_HEARTBEAT", HERE / "growth" / "cron_heartbeat.jsonl"))
# The engine's two crons are at their widest 20h40m apart — 05:40 UTC (build,
# pinned to the voucher feed's UTC clock) and 05:00 America/New_York (measure),
# which is 09:00 UTC in summer and 10:00 in winter. 24h is therefore one full
# cycle plus over three hours of margin for a cron that starts late, and it
# trips on the morning digest after the FIRST missed night rather than the
# third. See deploy/cron-rentmap-growth for both schedules.
CRON_MAX_GAP_HOURS = 24
# A record whose phase is a *_start with no matching finish means the script
# was invoked and then died or hung. The longest legitimate run is the build
# job plus its SEO watchdog, which carries its own 3600s timeout; 3h is past
# any of it.
CRON_MAX_INFLIGHT_HOURS = 3
# A step that means the page was still working when it died, rather than a
# tab the phone put away.
CLEAN_LAST_STEPS = {"vis hidden", "vis visible", "tick", "pagehide", "freeze"}

# Browser noise that is not our code and that we cannot fix: a cross-origin
# script (the ad slot) reports only "Script error." with no file or line, a
# browser extension talks to its own missing tab, and ResizeObserver's loop
# warning is fired by Safari itself. These still show in the digest so the
# picture is honest, but they never wake anyone up and are never "new".
IGNORED = ("script error.", "runtime.sendmessage", "resizeobserver loop",
           "extension context invalidated",
           # Brave on iOS injects its cosmetic ad-filter as an inline script
           # into every page; when it trips it reports as ours (2026-09-21).
           "standardselectors",
           # axios's wording, from an extension's own code: this site ships no
           # axios and the string appears nowhere in it. The one visitor who
           # produced it (2026-09-22) opened eight buildings and came back an
           # hour later, and no 5xx or API traceback matched the minute.
           "failed to fetch api data",
           # Mediavine's ad wrapper (Journey, 2026-09-28) throws this from its
           # own file until their onboarding links the Google ad account
           # (MCM). Nothing breaks for the visitor; no ads load yet either.
           "mcmnetworkcode is required",
           # Crypto-wallet browsers (MetaMask, Coinbase, Trust) inject a script
           # that resets window.ethereum; on a page with no wallet it throws at
           # line 1 of OUR url. This site has no "ethereum" anywhere (2026-10-02).
           "window.ethereum")


AD_STACK_HOSTS = ("scriptwrapper.com", "journeymv.com", "mediavine.com", "grow.me",
                  "uidapi.com", "optable.co", "rlcdn.com", "googlesyndication.com",
                  # Google's IMA SDK: Mediavine's video ads (2026-09-30, "a.j")
                  "imasdk.googleapis.com")


# Where our own scripts load from; any other host in a js_error is a third party's.
OUR_HOSTS = ("findacrib.com", "www.findacrib.com")


def is_noise(message: str) -> bool:
    m = message.lower()
    return any(n in m for n in IGNORED)


def service_key():
    for k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY"):
        if os.environ.get(k):
            return os.environ[k]
    sys.exit("no SUPABASE_SERVICE_ROLE_KEY in the environment")


def events(since_iso, key):
    """Every event in the window, paged."""
    q = urllib.parse.urlencode({"select": "event,props,path,visitor_id,created_at",
                                "created_at": f"gte.{since_iso}", "order": "id.asc"})
    out, start = [], 0
    while True:
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/events?{q}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Range": f"{start}-{start + 999}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.load(r)
        out += rows
        if len(rows) < 1000 or start > 200_000:
            return out
        start += 1000


# ------------------------------------------------------------------ sources

def js_errors(rows):
    out = defaultdict(lambda: {"n": 0, "people": set(), "paths": Counter(), "last": "", "noise": False})
    for r in rows:
        if r["event"] != "js_error":
            continue
        p = r.get("props") or {}
        msg = (p.get("msg") or "").strip() or "(empty message)"
        # Cross-origin scripts report as a bare "Script error." with no file or
        # line: that is the ad script or an extension, not our code.
        src = p.get("src") or ""
        key = f"{msg} — {src.rsplit('/', 1)[-1]}" if src else msg
        e = out[key]
        # Mediavine's ad stack (live 9/29) throws unhandled promise rejections
        # from its own files — UID2 from scripts.grow.me, $adManagementConfig
        # from scriptwrapper.com — and its fetches get cut off stacklessly
        # ("Load failed", "Fetch is aborted") as visitors pan and leave. The
        # stack names the ad file when there is one; a stackless rejection of
        # exactly those two messages started with the ads. Digest only.
        at = p.get("at") or ""
        # Safari hides a Safari extension's script behind webkit-masked-url://
        # (2026-10-18: "_0x43b06e is not an Object", obfuscated names, one
        # iPhone visitor). Our scripts always report a findacrib.com URL.
        e["noise"] = (is_noise(key) or any(h in at for h in AD_STACK_HOSTS)
                      or "webkit-masked-url://" in at
                      # A promise rejected with no reason at all (typeof
                      # undefined: no message, no name, no stack). 2026-10-29
                      # 19:31 UTC: one desktop visitor, 4 in 25 s, tab idle
                      # 9 min with only Mediavine's ad refresh running. Our one
                      # bare Promise.reject() (the copy button with no
                      # clipboard) has its own failure handler, so it is
                      # never unhandled. Nothing in such a row can be chased.
                      or (p.get("kind") == "promise" and not at and msg == "(empty message)"
                          and p.get("name") == "undefined")
                      or (p.get("kind") == "promise" and not at and msg in ("Load failed", "Fetch is aborted",
                                                                               # Safari: a response body cut off
                                                                               # mid-read (signal lost / page left);
                                                                               # our streamed download catches its own
                                                                               "The I/O read operation failed.",
                                                                               # Safari's wording for a dynamic import()
                                                                               # that failed. findacrib.com has no
                                                                               # module scripts and no import(); the ad
                                                                               # stack loads modules, and leaving or
                                                                               # losing signal mid-load rejects it
                                                                               # stacklessly (first seen 2026-09-30,
                                                                               # 1 visitor, 1 s after landing).
                                                                               "Importing a module script failed.",
                                                                               # 2026-09-30: Safari when a storage write
                                                                               # fails (full disk / private mode). This
                                                                               # site uses no IndexedDB or Cache API —
                                                                               # the ad stack's identity/prebid caches do.
                                                                               "Failed writing data to the file system",
                                                                               # An AbortError with no stack in the same
                                                                               # second as IMA video-ad errors. Our one
                                                                               # abort (the buildings stall timer, 15 s)
                                                                               # is caught in boot, never unhandled.
                                                                               "The operation was aborted.",
                                                                               # 2026-10-05: one visitor, first minute, no
                                                                               # stack — a TimeoutError and a DOMException
                                                                               # named UnavailableError. Neither string is
                                                                               # in our code (no AbortSignal.timeout, no
                                                                               # "Unavailable"); the ad stack's identity
                                                                               # scripts (UID2 failing the same minutes) are.
                                                                               "operation timed out", "UnavailableError",
                                                                               # 2026-10-06 04:21 UTC: a signed-out visitor,
                                                                               # stackless, in the same second as Mediavine's
                                                                               # scriptwrapper threw "$adManagementConfig.web.init
                                                                               # is not a function" and three "Script error."s.
                                                                               # Our awaited supabase calls never resolve to null.
                                                                               "Cannot destructure property 'data' from null or undefined value"))
                      # A rejected XMLHttpRequest object as the reason: this
                      # site never uses XHR (supabase-js and ours are fetch);
                      # Prebid in Mediavine's stack does (9/29).
                      or (p.get("kind") == "promise" and not at and msg == "[object XMLHttpRequest]")
                      # A file from another site (index.html sends its host
                      # since 2026-10-27): an ad or extension script, not ours.
                      or bool(p.get("host") and p["host"] not in OUR_HOSTS)
                      # WebAssembly: this site ships none (2026-10-27, a third
                      # party's rxEngine.wasm "memory access out of bounds",
                      # 1 visitor, before the host was sent).
                      or ".wasm" in src)
        e["n"] += 1
        e["people"].add(r["visitor_id"])
        e["paths"][r.get("path") or "/"] += 1
        e["last"] = r["created_at"]
    return out


STALE_TRACE = datetime.timedelta(hours=48)


def _ts(v):
    try:
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# A shadow page: a trace that never reached its first once-a-second tick, from
# a visitor who kept tapping around the site right after it booted. Signed-in
# iPhones spawn these — a second copy of the page boots, gets as far as
# adoptHome or the first viewport resize (~250-500 ms), and is gone without a
# pagehide, while the visitor carries on in their real page. One visitor on
# 2026-09-28 produced twelve in three minutes and mailed "12 page deaths";
# every sub-second adoptHome "death" since 9/25 (five visitors) has the same
# shape. A page that really died before its first second does not leave its
# visitor opening buildings, so only a trace that is followed by real
# interaction is dropped, and a boot loop still reports.
SHADOW_WINDOW = datetime.timedelta(seconds=90)
# The signed-in shadow shape — no tick, last step adoptHome or the auth event
# just before it — is dropped even when the visitor did nothing afterwards
# (2026-10-26: two of the day's four "page deaths"; seven visitors with this
# shape since 9/25, none followed by a reload or a complaint). It usually
# boots as the visitor is leaving. Three or more quiet ones from one visitor
# in a run still report: that would be a real loop at sign-in.
SHADOW_LAST = ("adoptHome", "auth INITIAL_SESSION")
SHADOW_LOOP = 3
SHADOW_LOOKUPS = 40       # REST calls per run, at most
INTERACTION_EVENTS = ("building_view", "section_view", "outbound", "status_open",
                      "violations_open", "rodents_open", "pests_open", "bedbugs_open",
                      "complaints_open", "portfolio_open", "featured_click", "hc_click",
                      "geo_start", "home_open", "search")


def visitor_kept_going(key, visitor, booted):
    """True when `visitor` did something on the site in the SHADOW_WINDOW after
    `booted` (ignoring its first two seconds, which the shadow page itself can
    log). None when it cannot be told — then the trace is kept."""
    if not key or not visitor:
        return None
    lo, hi = booted + datetime.timedelta(seconds=2), booted + SHADOW_WINDOW
    q = urllib.parse.urlencode({
        "select": "id", "visitor_id": f"eq.{visitor}", "limit": "1",
        "event": "in.(" + ",".join(INTERACTION_EVENTS) + ")",
        "and": f"(created_at.gte.{lo.isoformat()},created_at.lt.{hi.isoformat()})"})
    try:
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/events?{q}", headers={
            "apikey": key, "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return bool(json.load(r))
    except Exception:
        return None


def crashes(rows, key=None, kept_going=visitor_kept_going, found=None, max_lookups=SHADOW_LOOKUPS):
    """Traces that look like the page died mid-work (see the module docstring).
    `found`, a list, also collects each counted (row, last step): the owner
    dashboard's Crashes page lists them one by one (2026-10-25)."""
    lookups = 0
    out = defaultdict(lambda: {"n": 0, "people": set(), "uas": Counter(), "last": ""})
    boot_only = defaultdict(list)
    quiet_shadows = defaultdict(list)

    def count(r, last):
        if found is not None:
            found.append((r, last or "(no step)"))
        e = out[last or "(no step)"]
        e["n"] += 1
        e["people"].add(r["visitor_id"])
        ua = (r.get("props") or {}).get("ua") or ""
        e["uas"][("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else
                  "Android" if "Android" in ua else "Desktop")] += 1
        e["last"] = r["created_at"]

    for r in rows:
        if r["event"] != "crash_trace":
            continue
        p = r.get("props") or {}
        steps = p.get("steps")
        if not isinstance(steps, list) or not steps:
            continue
        labels = [s[1] if isinstance(s, list) and len(s) > 1 else "" for s in steps]
        if "pagehide" in labels:
            continue                      # it said goodbye; a later tick is not a crash
        # Backgrounded, then reclaimed: after "vis hidden" the only steps are
        # the 1s tick and the street photos finishing on their own. iOS taking
        # a hidden tab's memory back is normal, not a page that died on the
        # visitor (2026-09-23).
        # Any page whose last visibility change was "vis hidden" ended in the
        # background, whatever ran there: 2026-10-22's digest counted a Chrome
        # tab that refreshed its feeds (grid:feeds, grid:build) while hidden,
        # then lost a street photo to a timeout, then was reclaimed.
        if "vis hidden" in labels:
            last_hidden = len(labels) - 1 - labels[::-1].index("vis hidden")
            if "vis visible" not in labels[last_hidden:]:
                continue
        # Never on screen: booted hidden (background tab, prerender, tab
        # restore) and never became visible. Discarding such a page is the
        # browser tidying up, not a death anyone saw (2026-10-20).
        if any(x.startswith("boot ") for x in labels) and "vis visible" not in labels:
            continue
        last = labels[-1]
        if last in CLEAN_LAST_STEPS:
            continue
        # A lone "boot" died before its first step, so it says nothing about
        # what to fix; it is nearly always a tap away in the first second
        # (2026-10-22: the visitor was on a building page 1 s later). Only a
        # visitor who keeps dying at boot is news; see the loop's end.
        if labels == ["boot"]:
            boot_only[r.get("visitor_id")].append(r)
            continue
        # A trace is only sent on the visitor's NEXT boot, which can be days
        # later — so a death on code since replaced read as today's news
        # (2026-09-24: two "deaths" were from 9/18 and 9/22). index.html now
        # stamps the dead page's boot time; older than STALE_TRACE is history.
        booted = _ts(p.get("booted"))
        if booted and _ts(r["created_at"]) - booted > STALE_TRACE:
            continue
        # No boot stamp = the dead page ran code from before a68ba9a
        # (2026-09-24), which is long past STALE_TRACE: a phone that kept an
        # old tab open reported it on its next visit. Two of 2026-10-09's five
        # "page deaths" were these (visitors first seen 9/17 and earlier).
        if not booted:
            continue
        if booted and "tick" not in labels and lookups < max_lookups:
            lookups += 1
            went_on = kept_going(key, r.get("visitor_id"), booted)
            if went_on:
                continue
            if went_on is False and last in SHADOW_LAST:
                quiet_shadows[r.get("visitor_id")].append((r, last))
                continue
        count(r, last)
    for traces in quiet_shadows.values():
        if len(traces) >= SHADOW_LOOP:
            for r, last in traces:
                count(r, last)
    for traces in boot_only.values():
        if len(traces) >= 2:
            for r in traces:
                count(r, "boot")
    return out


def live_build():
    """The newest build on the App Store, from appstore.json (asc_downloads.py
    on the Mac writes it twice a day). None when unknown — then nothing is
    filtered, so a missing file can hide nothing."""
    try:
        b = json.loads(Path(APPSTORE_JSON).read_text()).get("live_build")
        return int(b) if b is not None else None
    except Exception:
        return None


def unreleased_rows(rows, live):
    """iOS rows from a build that is not on the App Store yet, unless enough
    different people run it that it must be a real rollout.

    Only three kinds of device run an unreleased build: the owner's phone on
    TestFlight, App Review, and Apple's own launch of every upload minutes
    after it lands. Builds 70 and 71 (2026-09-20) each drew one fresh install
    ~10 min after upload that tapped Sign in with Apple 14 times and got
    AuthorizationError 1000 (no Apple ID on the device) — the "19 app
    failures" email. Those are errors our own shipping creates, not users'.
    The 3-person floor covers the gap between a release and the next
    appstore.json refresh."""
    if live is None:
        return set()
    people = defaultdict(set)
    for r in rows:
        p = r.get("props") or {}
        b = str(p.get("build") or "")
        if p.get("platform") == "ios" and b.isdigit() and int(b) > live:
            people[b].add(r["visitor_id"])
    return {b for b, v in people.items() if len(v) < RELEASE_FLOOR}


# Supabase auth answer for a wrong email/password pair. Not app failures.
USER_SIGNIN_MISTAKES = re.compile(r"invalid login credentials", re.I)
# Cancel on Google's consent page: GoTrue gets access_denied with no
# description and builds before the 10/19 fix showed it as an error.
GOOGLE_DECLINED = re.compile(r"unspecified error_description", re.I)
APPLE_UNAVAILABLE = re.compile(r"AuthorizationError error 1000\b")


def app_failures(rows, skip_builds=frozenset()):
    """iPhone app rows that record a failure the user saw."""
    out = defaultdict(lambda: {"n": 0, "people": set(), "last": ""})
    # Apple's 1000 after the app's own retry is the phone, not the app: no
    # Apple Account in Settings or Screen Time limits, and the app already
    # says so and offers Google or email. One person tapping three times
    # (2026-10-22, build 154, while others signed in with Apple fine) was the
    # whole of a digest's "app failures". Two or more people is a pattern
    # worth reading (2026-09-19's half-presented sheet), so it stays.
    apple_1000 = {r["visitor_id"] for r in rows
                  if r["event"] == "signin" and (r.get("props") or {}).get("provider") == "apple"
                  and APPLE_UNAVAILABLE.search((r.get("props") or {}).get("text") or "")}
    for r in rows:
        p = r.get("props") or {}
        if p.get("platform") != "ios":
            continue
        if str(p.get("build") or "") in skip_builds:
            continue
        ev, label = r["event"], None
        if ev == "push_register_failed":
            label = f"Push registration failed ({p.get('text') or p.get('error') or '?'})"
        elif ev == "signin" and p.get("result") in ("error",):
            # A mistyped password is the person, not the app: the sheet says
            # so and offers "Forgot password?" (EmailSignInView). The 10/17
            # digest's only "app failure" was one of these.
            if USER_SIGNIN_MISTAKES.search(p.get("text") or ""):
                continue
            if p.get("provider") == "google" and GOOGLE_DECLINED.search(p.get("text") or ""):
                continue
            if (len(apple_1000) == 1 and p.get("provider") == "apple"
                    and APPLE_UNAVAILABLE.search(p.get("text") or "")):
                continue
            label = f"Sign-in failed ({p.get('provider') or '?'})"
        elif ev == "purchase" and p.get("result") in ("error", "unverified"):
            label = f"Purchase {p.get('result')}"
        elif ev == "app_error":
            label = f"{p.get('where') or 'app'}: {(p.get('text') or '')[:80]}"
        if not label:
            continue
        e = out[label]
        e["n"] += 1
        e["people"].add(r["visitor_id"])
        e["last"] = r["created_at"]
    return out


def nginx_5xx(minutes):
    """5xx lines served in the window, by status and path, bots excluded."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    line_re = re.compile(r'^\S+ \S+ \S+ \[([^\]]+)\] "(\w+) ([^ "]+)[^"]*" (\d{3}) .*"([^"]*)"$')
    out = Counter()
    for path in NGINX_LOGS:
        if not os.path.exists(path):
            continue
        try:
            tail = subprocess.run(["tail", "-n", "20000", path], capture_output=True, text=True, timeout=30).stdout
        except Exception:
            continue
        for line in tail.splitlines():
            m = line_re.match(line)
            if not m:
                continue
            when, _method, req, status, ua = m.groups()
            if not status.startswith("5"):
                continue
            try:
                ts = datetime.datetime.strptime(when, "%d/%b/%Y:%H:%M:%S %z")
            except ValueError:
                continue
            if ts < cutoff:
                continue
            if re.search(r"bot|crawler|spider|slurp|bingpreview", ua, re.I):
                continue
            out[f"{status} {req.split('?')[0][:70]}"] += 1
    return out


def api_tracebacks(minutes):
    """The API's own exceptions behind those 5xx."""
    try:
        log = subprocess.run(["journalctl", "-u", "findacrib-api", "--since", f"-{minutes}min",
                              "--no-pager", "-o", "cat"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return Counter()
    out = Counter()
    for block in log.split("Traceback (most recent call last):")[1:]:
        last = [l for l in block.strip().splitlines() if l.strip()][:1]
        out[(last[0].strip() if last else "traceback")[:120]] += 1
    return out


def stale_feeds():
    """A feed whose file stopped refreshing is an error users see as old data."""
    out = {}
    docroot = os.environ.get("GROWTH_DOCROOT", "/var/www/rent-map")
    checks = {"hcr.json": 6, "featured.json": 36, "s8.json": 48}
    # The Events tab (build_events.py, twice a day). Only checked once the
    # feed has existed: before the NYC_API_KEY is in place there is no file,
    # and "missing" would mail every hour about a feature not yet switched on.
    if os.path.exists(os.path.join(docroot, "events.json")):
        checks["events.json"] = 30
    now = datetime.datetime.now().timestamp()
    for name, max_hours in checks.items():
        p = os.path.join(docroot, name)
        if not os.path.exists(p):
            out[name] = "missing"
            continue
        age = (now - os.path.getmtime(p)) / 3600
        if age > max_hours:
            out[name] = f"{age:.0f}h old (expected under {max_hours}h)"
    return out


# ---------------------------------------------------------------- stale claims
# TWO KINDS OF PROMISE, AND THEY ARE FALSIFIED BY DIFFERENT CLOCKS.
#
# A page can promise a nightly refresh about ITSELF ("Updated daily." on
# /section8/), or it can promise one about ANOTHER section ("Find A Crib
# rebuilds a list every night … see the current voucher listings" on a
# neighborhood hub). The first is falsified by that page's own build age. The
# second is not: it is a statement about the voucher build's cadence, and it
# stays true however old the referring page gets, as long as /section8/ is
# still being rebuilt. Judging it on the referring page's own age would be
# wrong in both directions — see the note above REFERRING_PHRASES.

# ---- the self claim: the wording /section8/ uses about /section8/ ----------
# The wording growth/techniques.py t_fresh_section8 emits ONLY on its fresh
# path, i.e. only when _feed_freshness() found the voucher feed current. A live
# page carrying one of these is a page that promised the reader a nightly
# refresh. The stale path says "listings as of <date>" and "had at least one
# apartment listed" instead, which stays true however old it gets, and must
# never be reported here.
#
# Pinned by tests/test_stale_claims.py against growth/techniques.py: reword the
# template and the test fails rather than this list silently matching nothing.
CADENCE_PHRASES = (
    "Updated daily.",
    "refreshed nightly",
    "Rebuilt daily from the overnight feed",
    "rent-stabilized buildings with live listings",
)

# ---- the referring claim: what other tiers say about /section8/ ------------
# Three code sites in build_seo.py put a present-tense promise about the
# voucher build onto pages OUTSIDE /section8/, and between them they reach far
# more readers than the section itself does:
#
#   VOUCHER_XLINK (build_seo.py:151)       — the NYC hub tier: /neighborhood/,
#       /zip/, /borough/, /buildings/. "Find A Crib rebuilds a list every night
#       of the DHCR-registered rent-stabilized buildings that have an apartment
#       listed for Section 8 … from the overnight AffordableHousing.com feed."
#   CITY_VOUCHER_XLINK (build_seo.py:191)  — the three city browse hubs,
#       /sf/buildings/, /la/buildings/, /dc/buildings/. "every night it rebuilds
#       the list of DHCR-registered rent-stabilized buildings …"
#   the methodology cadence table (build_seo.py:3388) — /methodology/ publishes
#       a row reading "Housing-voucher listings (/section8/) — Rebuilt nightly".
#
# WHY THESE ARE NOT JUDGED ON THEIR OWN AGE, which is the whole design of this
# half and the reason it is not a copy of the block above. Every one of these
# pages reaches the docroot through scripts/refresh_seo.sh, and the only live
# cron that runs it is deploy/cron-rentmap-seo at `10 4 1 * *` — the FIRST OF
# EACH MONTH. So a perfectly honest /methodology/ is routinely 30 days old
# while the voucher build runs faithfully every night, and an age check on the
# page itself would fire on all 370-odd of them on 29 days out of 30. The
# claim is about /section8/, so /section8/'s own build age is what falsifies
# it — and that also catches the case the self claim above cannot see: a
# /section8/ that froze on its STALE path is honestly dated about itself and
# still has 370 pages promising, elsewhere, that it is rebuilt nightly.
#
# Pinned by tests/test_stale_claims.py, which asserts each phrase still occurs
# in build_seo.py EXACTLY ONCE: reword one of the three and the test fails
# rather than this list matching nothing forever, and reuse one on a fourth
# tier and it fails too, which is the signal to extend REFERRING_SECTIONS
# below. It cannot catch a fourth site that invents NEW wording — nothing
# short of reading the corpus could, and that is the honest limit of this
# check rather than a gap to paper over.
REFERRING_PHRASES = (
    "rebuilds a list every night",
    "every night it rebuilds the list",
    "Rebuilt nightly",
)
# Docroot-relative, and deliberately a list rather than a walk of the whole
# docroot: /building/ alone is 47,165 pages whose template carries none of
# these, and reading the corpus to find 370 pages is the kind of cost that
# gets a check turned off. The cost of the list is that a new tier has to be
# added to it; the test above is what makes that visible.
REFERRING_SECTIONS = (
    "buildings",        # VOUCHER_XLINK, NYC citywide hub
    "neighborhood",     # VOUCHER_XLINK, 198 NYC neighborhood hubs
    "zip",              # VOUCHER_XLINK, 165 NYC ZIP hubs
    "borough",          # VOUCHER_XLINK, 5 borough hubs
    "sf/buildings",     # CITY_VOUCHER_XLINK
    "la/buildings",     # CITY_VOUCHER_XLINK
    "dc/buildings",     # CITY_VOUCHER_XLINK
    "methodology",      # the cadence table
)

# The same 48h the page itself uses (growth/techniques.py FEED_STALE_HOURS) to
# decide whether it may say "right now" about the feed at all, and the same
# allowance stale_feeds() gives s8.json. A page refuses to make a present-tense
# claim about a feed older than this; a page whose own build is this far behind
# has no better standing to make one about itself.
CADENCE_CLAIM_HOURS = 48


def _claiming_pages(root, phrases):
    """[(mtime, phrase)] for every index.html under root carrying a phrase."""
    out = []
    if not os.path.isdir(root):
        return out
    for dirpath, _dirnames, filenames in os.walk(root):
        if "index.html" not in filenames:
            continue
        page = os.path.join(dirpath, "index.html")
        try:
            mtime = os.path.getmtime(page)
            with open(page, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        found = [p for p in phrases if p in text]
        if found:
            out.append((mtime, found[0]))
    return out


def _newest_page(root):
    """mtime of the newest index.html under root, or None if there is none.

    When the voucher build last ran, regardless of which wording it chose —
    which is what falsifies a promise about that build's cadence.
    """
    newest = None
    for dirpath, _dirnames, filenames in os.walk(root):
        if "index.html" not in filenames:
            continue
        try:
            mtime = os.path.getmtime(os.path.join(dirpath, "index.html"))
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def _feed_contrast(docroot, now):
    """The voucher feed's own age, as a clause — contrast, never the verdict.

    A fresh feed behind a frozen page is the informative pair: it says the
    scrape is doing its job and whatever publishes from it is not.
    """
    try:
        feed_h = (now - os.path.getmtime(os.path.join(docroot, "s8.json"))) / 3600.0
    except OSError:
        return ""
    if feed_h <= CADENCE_CLAIM_HOURS:
        return (f" — while s8.json, the feed they cite, refreshed {feed_h:.0f}h ago. "
                f"The scrape is running and the pages built from it are not")
    return f" — s8.json is {feed_h / 24:.1f} days old too (see Feeds)"


def stale_claims(docroot=None, now=None):
    """A live page still promising a nightly refresh that has stopped.

    THE GAP THIS EXISTS TO COVER. Three instruments watch this engine and all
    three are blind to it at once:

      * dead_crons() stands down on a deliberate pause (owner, 2026-10-12),
        correctly — a pause is not a failure.
      * stale_feeds() is green, because the feed really does keep refreshing:
        the scrape runs from cron-rentmap-scrape, which is NOT paused. It
        watches the inputs, not what was published from them.
      * growth/techniques.py t_frozen_pages measures a page's age against the
        NEWEST page in the docroot, deliberately, "so a night the whole
        pipeline failed reports no freezes rather than 49,000 of them". A
        uniform freeze is invisible to it by design — and it runs under the
        paused cron anyway.

    So the engine can stop on purpose, the feed can stay fresh, and the pages
    built from it can sit for days telling tenants they were "Updated daily"
    with nothing on the box noticing. That is not an engine-liveness fact, it
    is a wrong sentence on a page someone is reading to decide where to live,
    and it is why this does NOT stand down on the pause the way dead_crons()
    does: a deliberate pause is a fine reason for the engine to be off and no
    reason at all for the site to keep making a promise it is not keeping.

    This runs from cron-rentmap-errors, which is independent of the growth
    cron, so it reports while the engine is paused — the one channel that can.

    IT REPORTS THE CONDITION AND NOT THE CAUSE. It reads page mtimes and the
    feed's, not the crontab, so it says what is old and what is not and leaves
    the diagnosis to the reader. Asserting a cause from one aggregate is how
    this codebase has been wrong before.

    TWO FINDINGS, AT MOST ONE EACH:

      "/section8/"              the section's own fresh-path wording, judged on
                                the freshest page that carries it. If even the
                                newest one is past the allowance then every one
                                of them is, so the finding cannot be an
                                artifact of one forgotten corner of the tier.
      "pages citing /section8/" the NYC hubs, the three city browse hubs and
                                /methodology/ promising that section is
                                rebuilt nightly, judged on /SECTION8/'s build
                                age and never on their own — see the note
                                above REFERRING_PHRASES for why.

    Both stand down on a box with no <docroot>/section8 at all: nothing
    published it, so there is no build age to judge either claim against, and
    a referring page pointing at a section this box does not serve is a
    different and larger problem than this check is about.
    """
    out = {}
    if docroot is None:
        docroot = os.environ.get("GROWTH_DOCROOT", "/var/www/rent-map")
    # Only speak for a box that actually publishes these pages — the same
    # reason stale_feeds() checks events.json only once it exists.
    section = os.path.join(docroot, "section8")
    if not os.path.isdir(section):
        return out
    if now is None:
        now = datetime.datetime.now().timestamp()

    # ---- the section's claim about itself ---------------------------------
    claiming = _claiming_pages(section, CADENCE_PHRASES)
    if claiming:
        newest, phrase = max(claiming)
        hours = (now - newest) / 3600.0
        if hours > CADENCE_CLAIM_HOURS:
            n = len(claiming)
            detail = (f'{n} page{"" if n == 1 else "s"} still say{"s" if n == 1 else ""} '
                      f'"{phrase.rstrip(".")}" but {"was" if n == 1 else "the freshest was"} '
                      f'built {hours / 24:.1f} days ago')
            out["/section8/"] = detail + _feed_contrast(docroot, now)

    # ---- what the rest of the site claims about the section ---------------
    built = _newest_page(section)
    if built is None:
        return out
    built_h = (now - built) / 3600.0
    if built_h <= CADENCE_CLAIM_HOURS:
        return out
    referring = []
    for rel in REFERRING_SECTIONS:
        hits = _claiming_pages(os.path.join(docroot, rel), REFERRING_PHRASES)
        if hits:
            referring.append((rel, hits))
    if not referring:
        return out

    pages = sum(len(h) for _rel, h in referring)
    phrase = referring[0][1][0][1]
    where = ", ".join("/" + rel.strip("/") + "/" for rel, _h in referring)
    detail = (f'{pages} page{"" if pages == 1 else "s"} in '
              f'{len(referring)} section{"" if len(referring) == 1 else "s"} '
              f'({where}) say{"s" if pages == 1 else ""} "{phrase.rstrip(".")}" about '
              f'/section8/, which was itself last rebuilt {built_h / 24:.1f} days ago '
              f"— judged on that section's build age, not on these pages' own, "
              f"because the promise is about it and not about them")
    # The feed clause only once per email: the row above already carries it
    # when both findings fire, and the same sentence twice in one table is how
    # a reader learns to skim the table.
    if "/section8/" not in out:
        detail += _feed_contrast(docroot, now)
    out["pages citing /section8/"] = detail
    return out


def dead_crons():
    """The growth engine stopped and nothing on this box noticed for 72 hours.

    growth_run.sh appends a record to growth/cron_heartbeat.jsonl before it
    does anything else and again when it finishes, and its own header states
    the invariant that makes the file worth reading: EVERY INVOCATION LEAVES A
    RECORD, so no record means the script did not run at all — cron, the host
    or the checkout — and never means "it ran but stayed quiet".

    Nothing on the droplet has ever read that file. It was written for the
    daily review agent, which runs in Anthropic's cloud with only a git
    checkout, and which therefore can report a dead engine to git and to
    nobody. From 2026-09-24 GitHub's copy of the heartbeat stopped at
    2026-09-23T05:42:12Z and the review agent read that as dead crons. They
    were not: they ran every night, but every `git pull` failed (six untracked
    files on the droplet collided with files since committed), so every job
    ran three-day-old code and every ledger push was rejected — including the
    heartbeat that recorded pull=failed. Only this box can see that, which is
    why the pull state is checked here too.

    This is the missing half of that instrument. error_report.py runs hourly
    from a cron of its own, independent of the growth cron, and already mails
    the one person who can restart it.

    Deliberately only reported on the --digest run (see main()): a dead cron
    is a once-a-day fact, and the hourly path would mail the same sentence
    seventy-two times over an outage this length, which is how an alert gets
    filtered into a folder and stops working.
    """
    out = {}
    # Only speak for a host that actually runs the engine. A checkout without
    # growth_run.sh is not a broken engine, it is a box that never had one —
    # the same reason stale_feeds() checks events.json only once it exists.
    if not (HERE / "growth_run.sh").exists():
        return out
    # Paused on purpose (owner, 2026-10-12: "pause seo for FAC"): a cron file
    # with no live growth_run line is not a dead engine.
    try:
        cron = Path("/etc/cron.d/rentmap-growth").read_text()
        if not any(l.strip() and not l.lstrip().startswith("#") and "growth_run.sh" in l for l in cron.splitlines()):
            return out
    except OSError:
        pass
    try:
        last, lines = "", []
        with open(HEARTBEAT) as fh:
            for line in fh:
                if line.strip():
                    last = line.strip()
                    lines.append(last)
    except FileNotFoundError:
        out["growth engine"] = ("no heartbeat file at growth/cron_heartbeat.jsonl — "
                                "growth_run.sh has never completed a run on this host")
        return out
    except OSError as e:
        out["growth engine"] = f"heartbeat unreadable: {e}"
        return out
    if not last:
        out["growth engine"] = "heartbeat file is empty — no run has ever been recorded"
        return out

    try:
        rec = json.loads(last)
        at = datetime.datetime.strptime(rec["at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (ValueError, KeyError, TypeError):
        # A heartbeat we cannot parse is itself a failure of the instrument,
        # and staying quiet about it would leave the engine unwatched again.
        out["growth engine"] = f"last heartbeat record is unreadable: {last[:120]}"
        return out

    age = (datetime.datetime.now(datetime.timezone.utc) - at).total_seconds() / 3600
    job, phase = rec.get("job") or "?", rec.get("phase") or "?"
    if age > CRON_MAX_GAP_HOURS:
        out["growth engine"] = (
            f"last ran {age:.0f}h ago ({rec['at']}, {job}/{phase}) — expected under "
            f"{CRON_MAX_GAP_HOURS}h. /etc/cron.d/rentmap-growth is not firing: "
            f"nothing is being measured, built or deployed")
    elif phase.endswith("start") and age > CRON_MAX_INFLIGHT_HOURS:
        # The other half of the three-way ambiguity growth_run.sh was written
        # to resolve: this one ran, and then died or hung part way through.
        out["growth engine"] = (
            f"started {age:.0f}h ago ({rec['at']}, {job}/{phase}) and never "
            f"recorded a finish — the run is hung or was killed. "
            f"Check /var/log/rentmap-growth.log")
    else:
        # Running, but on what code? Every run in the last day failing its
        # pull means every cron on this box is running a frozen checkout and
        # nothing it commits reaches GitHub.
        now = datetime.datetime.now(datetime.timezone.utc)
        recent = []
        for line in lines[-200:]:
            try:
                r = json.loads(line)
                t = datetime.datetime.strptime(r["at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=datetime.timezone.utc)
            except (ValueError, KeyError, TypeError):
                continue
            if (now - t).total_seconds() < CRON_MAX_GAP_HOURS * 3600 and r.get("pull") in ("ok", "failed"):
                recent.append(r)
        if recent and all(r["pull"] == "failed" for r in recent):
            out["growth engine"] = (
                f"runs, but every git pull in the last {CRON_MAX_GAP_HOURS}h failed "
                f"({len(recent)} records) — all Find A Crib crons are running a stale "
                f"checkout and ledger pushes are rejected. Run `git status` and "
                f"`git pull --rebase origin main` in /root/Find-A-Crib")
    return out


# ------------------------------------------------------------------- report

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build(window_label, js, crash, app, five, tracebacks, stale, new_msgs, crons=None,
          claims=None):
    def table(title, headers, rows):
        if not rows:
            return ""
        th = "".join(f"<th align='left' style='padding:6px 10px;border-bottom:1px solid #ddd;font-size:12px;color:#666'>{esc(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;font-size:14px'>{c}</td>" for c in r) + "</tr>" for r in rows)
        return (f"<h3 style='font:600 16px system-ui;margin:22px 0 6px'>{esc(title)}</h3>"
                f"<table cellspacing='0' style='border-collapse:collapse;width:100%'>"
                f"<tr>{th}</tr>{body}</table>")

    crons = crons or {}
    claims = claims or {}
    parts = []
    # First, above the user-facing errors. A stopped engine is not one more
    # thing that went wrong that hour — it is every following number in this
    # email being measured by something that is no longer running.
    parts.append(table("Engine", ["Job", "State"], [[esc(k), esc(v)] for k, v in crons.items()]))
    # Directly under the engine and above the error tables, because this is not
    # something that went wrong for one visitor: it is a sentence every visitor
    # to the section reads, and it is currently false. See stale_claims().
    #
    # "Where" rather than "Section": one row is a section's claim about itself
    # and the other is the rest of the site's claim about that section, so the
    # column is a location and not always a published tier.
    parts.append(table("Pages promising a refresh that stopped", ["Where", "State"],
                       [[esc(k), esc(v)] for k, v in (claims or {}).items()]))
    # Browser noise stays out of the email (owner, 2026-10-05: "should i get
    # emails on browser noise?"): it never triggers one, and when something
    # real does, the noise is one line under the table, not rows in it.
    real = {k: v for k, v in js.items() if not v["noise"]}
    noisy = [v for v in js.values() if v["noise"]]
    parts.append(table("JavaScript errors (web)", ["Message", "Times", "People", "Where", "New?"], [
        [esc(k), v["n"], len(v["people"]), esc(v["paths"].most_common(1)[0][0] if v["paths"] else "—"),
         "<b style='color:#b3261e'>new</b>" if k in new_msgs else ""]
        for k, v in sorted(real.items(), key=lambda kv: -kv[1]["n"])[:12]]))
    if noisy:
        parts.append(f"<p style='font:13px system-ui;color:#666;margin:6px 0 0'>Plus {sum(v['n'] for v in noisy)} "
                     f"browser-noise error{'s' if sum(v['n'] for v in noisy) != 1 else ''} (ad scripts, extensions, "
                     f"dropped connections) — not shown, nothing to fix.</p>")
    parts.append(table("Pages that died mid-work", ["Last thing it did", "Times", "People", "Device"], [
        [esc(k), v["n"], len(v["people"]), esc(v["uas"].most_common(1)[0][0] if v["uas"] else "—")]
        for k, v in sorted(crash.items(), key=lambda kv: -kv[1]["n"])[:10]]))
    parts.append(table("iPhone app failures", ["What failed", "Times", "People"], [
        [esc(k), v["n"], len(v["people"])] for k, v in sorted(app.items(), key=lambda kv: -kv[1]["n"])[:10]]))
    parts.append(table("Server errors (5xx)", ["Status and path", "Times"], [[esc(k), n] for k, n in five.most_common(10)]))
    parts.append(table("API exceptions", ["First line", "Times"], [[esc(k), n] for k, n in tracebacks.most_common(8)]))
    parts.append(table("Feeds", ["File", "State"], [[esc(k), esc(v)] for k, v in stale.items()]))

    html = (f"<div style='font:15px/1.5 system-ui,-apple-system,sans-serif;max-width:720px;color:#111'>"
            f"<h2 style='font-size:20px;margin:0 0 4px'>Find A Crib — errors, {esc(window_label)}</h2>"
            f"<p style='color:#666;font-size:13px;margin:0 0 6px'>What users hit on findacrib.com, mobile web and the iPhone app. "
            f"Nothing worth reporting means no email.</p>{''.join(parts)}"
            f"<p style='color:#888;font-size:12px;margin-top:22px'>error_report.py on 142.93.183.172 · "
            f"dashboard: https://divinedavis.com/dashboard/</p></div>")

    lines = [f"Find A Crib errors — {window_label}", ""]
    if crons:
        lines += ["Engine:"] + [f"  {k}: {v}" for k, v in crons.items()] + [""]
    if claims:
        lines += ["Pages promising a refresh that stopped:"] \
            + [f"  {k}: {v}" for k, v in claims.items()] + [""]
    # The plain-text part hides browser noise like the HTML does (2026-10-16:
    # Gmail's text view listed 62 ad-script "Load failed" rows as errors).
    for title, d in (("JavaScript errors", real), ("Pages that died mid-work", crash), ("iPhone app failures", app)):
        if d:
            lines.append(title + ":")
            for k, v in sorted(d.items(), key=lambda kv: -kv[1]["n"])[:10]:
                lines.append(f"  {v['n']:>4}x  {len(v['people'])} people  {k}")
        if title == "JavaScript errors" and noisy:
            lines.append(f"  (plus {sum(v['n'] for v in noisy)} browser-noise errors: ad scripts, extensions, dropped connections)")
            lines.append("")
    if five:
        lines += ["Server 5xx:"] + [f"  {n:>4}x  {k}" for k, n in five.most_common(10)] + [""]
    if tracebacks:
        lines += ["API exceptions:"] + [f"  {n:>4}x  {k}" for k, n in tracebacks.most_common(8)] + [""]
    if stale:
        lines += ["Feeds:"] + [f"  {k}: {v}" for k, v in stale.items()]
    return html, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--digest", action="store_true", help="send whenever anything is open, not only on something new")
    ap.add_argument("--email", default=os.environ.get("ERROR_REPORT_EMAIL") or os.environ.get("GROWTH_REPORT_EMAIL"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    minutes = int(a.hours * 60)
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = events(since, service_key())
    skip = unreleased_rows(rows, live_build())
    js, crash, app = js_errors(rows), crashes(rows, service_key()), app_failures(rows, skip)
    five, tracebacks, stale = nginx_5xx(minutes), api_tracebacks(minutes), stale_feeds()
    crons = dead_crons()
    claims = stale_claims()

    try:
        state = json.loads(STATE.read_text())
    except Exception:
        state = {}
    known = set(state.get("known_js", []))
    # A first run has nothing known, so everything would read as new and the
    # first email would be all alarm and no signal.
    first_run = "known_js" not in state
    new_msgs = set() if first_run else {k for k in js if k not in known and not js[k]["noise"]}

    # What earns an email: something we have never seen, something breaking on
    # the server, or a real burst. A handful of the same old cross-origin
    # "Script error." does not.
    # A dead cron is deliberately NOT in the hourly path's list. It is a fact
    # with a daily cadence, and an outage lasts days: the 2026-09-24 one ran
    # 72 hours, which the hourly run would have turned into 72 identical
    # emails. The digest fires once a morning at 08:10 ET and names it in the
    # subject line, which is one email per day of outage and the first of them
    # on the morning after the first missed night.
    worth_it = bool(new_msgs) or bool(tracebacks) or bool(stale) or sum(five.values()) >= 5 \
        or sum(v["n"] for v in crash.values()) >= 10 or sum(v["n"] for v in app.values()) >= 3
    if a.digest:
        worth_it = bool(js or crash or app or five or tracebacks or stale or crons or claims)
    else:
        crons = {}
        # Digest-only for the same reason as a dead cron: a page that has been
        # frozen for days is a fact with a daily cadence, and the hourly path
        # would mail the identical sentence 24 times a day for as long as it
        # lasted, which is how an alert gets filtered into a folder.
        claims = {}

    label = f"last {a.hours:g}h" if a.hours != 24 else "last 24 hours"
    html, text = build(label, js, crash, app, five, tracebacks, stale, new_msgs, crons,
                       claims)
    counts = (f"js {sum(v['n'] for v in js.values())} ({len(new_msgs)} new), crashes "
              f"{sum(v['n'] for v in crash.values())}, app {sum(v['n'] for v in app.values())}, "
              f"5xx {sum(five.values())}, tracebacks {sum(tracebacks.values())}, stale {len(stale)}"
              + (f", dead crons {len(crons)}" if crons else "")
              + (f", stale page promises {len(claims)}" if claims else "")
              + (f", ignored unreleased builds {','.join(sorted(skip))}" if skip else ""))

    if not worth_it:
        print(f"nothing to report ({counts})")
        return
    if a.dry_run or not a.email:
        print(text)
        print(f"\n[{'dry run' if a.dry_run else 'no ERROR_REPORT_EMAIL set'}] would email: {counts}")
        return

    from growth import emailkit
    bits = []
    # Leads the subject. Everything else in this email is something users hit;
    # this one is the machine that measures and deploys the site having
    # stopped, and it needs to be readable in a phone notification without
    # opening the mail.
    if crons:
        bits.append("GROWTH ENGINE NOT RUNNING")
    # Second only to a dead engine: unlike everything below it, this one is
    # wrong content on a live page rather than a failure a visitor hit.
    if claims:
        bits.append("stale refresh promise on the site")
    if new_msgs:
        bits.append(f"{len(new_msgs)} new JS error{'s' if len(new_msgs) > 1 else ''}")
    if five:
        bits.append(f"{sum(five.values())} 5xx")
    if tracebacks:
        bits.append(f"{sum(tracebacks.values())} API exceptions")
    if crash:
        bits.append(f"{sum(v['n'] for v in crash.values())} page deaths")
    if app:
        bits.append(f"{sum(v['n'] for v in app.values())} app failures")
    if stale:
        bits.append(f"{len(stale)} stale feed{'s' if len(stale) > 1 else ''}")
    subject = "Find A Crib errors: " + (", ".join(bits) if bits else label)
    emailkit.send(a.email, subject, html, text, from_name="Find A Crib alerts")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"known_js": sorted(known | set(js)),
                                 "last_sent": datetime.datetime.now(datetime.timezone.utc).isoformat()}))
    print(f"emailed {a.email}: {counts}")


if __name__ == "__main__":
    main()
