#!/usr/bin/env python3
"""Email the owner when users hit errors — web, mobile web and the iPhone app.

Runs on the droplet (cron in deploy/cron-rentmap-errors). Four sources:

  1. `public.events` — js_error (web), crash_trace (a page that never said
     goodbye), push_register_failed / purchase / signin failures (iOS).
  2. nginx — 5xx served to real people on findacrib.com and /api/.
  3. journalctl -u findacrib-api — Python tracebacks behind those 5xx.
  4. The feeds' own cron logs — a scrape that died leaves the app showing
     yesterday's listings, which is a user-facing error nobody reports.

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
FEED_LOGS = {
    "Zumper listings": "/var/log/rentmap-scrape.log",
    "HCR lotteries": "/var/log/rentmap-hcr.log",
    "Re-rentals": "/var/log/rentmap-rerentals.log",
    "Borough alerts": "/var/log/rentmap-alerts.log",
}
# A step that means the page was still working when it died, rather than a
# tab the phone put away.
CLEAN_LAST_STEPS = {"vis hidden", "vis visible", "tick", "pagehide", "freeze"}

# Browser noise that is not our code and that we cannot fix: a cross-origin
# script (the ad slot) reports only "Script error." with no file or line, a
# browser extension talks to its own missing tab, and ResizeObserver's loop
# warning is fired by Safari itself. These still show in the digest so the
# picture is honest, but they never wake anyone up and are never "new".
IGNORED = ("script error.", "runtime.sendmessage", "resizeobserver loop",
           "extension context invalidated")


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
        e["noise"] = is_noise(key)
        e["n"] += 1
        e["people"].add(r["visitor_id"])
        e["paths"][r.get("path") or "/"] += 1
        e["last"] = r["created_at"]
    return out


def crashes(rows):
    """Traces that look like the page died mid-work (see the module docstring)."""
    out = defaultdict(lambda: {"n": 0, "people": set(), "uas": Counter(), "last": ""})
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
        last = labels[-1]
        if last in CLEAN_LAST_STEPS:
            continue
        e = out[last or "(no step)"]
        e["n"] += 1
        e["people"].add(r["visitor_id"])
        ua = p.get("ua") or ""
        e["uas"][("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else
                  "Android" if "Android" in ua else "Desktop")] += 1
        e["last"] = r["created_at"]
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


def app_failures(rows, skip_builds=frozenset()):
    """iPhone app rows that record a failure the user saw."""
    out = defaultdict(lambda: {"n": 0, "people": set(), "last": ""})
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
    checks = {"listings_zumper.json": 36, "hcr.json": 6, "featured.json": 36, "s8.json": 48}
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


# ------------------------------------------------------------------- report

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build(window_label, js, crash, app, five, tracebacks, stale, new_msgs):
    def table(title, headers, rows):
        if not rows:
            return ""
        th = "".join(f"<th align='left' style='padding:6px 10px;border-bottom:1px solid #ddd;font-size:12px;color:#666'>{esc(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;font-size:14px'>{c}</td>" for c in r) + "</tr>" for r in rows)
        return (f"<h3 style='font:600 16px system-ui;margin:22px 0 6px'>{esc(title)}</h3>"
                f"<table cellspacing='0' style='border-collapse:collapse;width:100%'>"
                f"<tr>{th}</tr>{body}</table>")

    parts = []
    parts.append(table("JavaScript errors (web)", ["Message", "Times", "People", "Where", "New?"], [
        [esc(k), v["n"], len(v["people"]), esc(v["paths"].most_common(1)[0][0] if v["paths"] else "—"),
         "<b style='color:#b3261e'>new</b>" if k in new_msgs else ("browser noise" if v["noise"] else "")]
        for k, v in sorted(js.items(), key=lambda kv: -kv[1]["n"])[:12]]))
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
            f"<p style='color:#888;font-size:12px;margin-top:22px'>error_report.py on 104.236.120.144 · "
            f"dashboard: https://divinedavis.com/dashboard/</p></div>")

    lines = [f"Find A Crib errors — {window_label}", ""]
    for title, d in (("JavaScript errors", js), ("Pages that died mid-work", crash), ("iPhone app failures", app)):
        if d:
            lines.append(title + ":")
            for k, v in sorted(d.items(), key=lambda kv: -kv[1]["n"])[:10]:
                lines.append(f"  {v['n']:>4}x  {len(v['people'])} people  {k}")
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
    js, crash, app = js_errors(rows), crashes(rows), app_failures(rows, skip)
    five, tracebacks, stale = nginx_5xx(minutes), api_tracebacks(minutes), stale_feeds()

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
    worth_it = bool(new_msgs) or bool(tracebacks) or bool(stale) or sum(five.values()) >= 5 \
        or sum(v["n"] for v in crash.values()) >= 10 or sum(v["n"] for v in app.values()) >= 3
    if a.digest:
        worth_it = bool(js or crash or app or five or tracebacks or stale)

    label = f"last {a.hours:g}h" if a.hours != 24 else "last 24 hours"
    html, text = build(label, js, crash, app, five, tracebacks, stale, new_msgs)
    counts = (f"js {sum(v['n'] for v in js.values())} ({len(new_msgs)} new), crashes "
              f"{sum(v['n'] for v in crash.values())}, app {sum(v['n'] for v in app.values())}, "
              f"5xx {sum(five.values())}, tracebacks {sum(tracebacks.values())}, stale {len(stale)}"
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
