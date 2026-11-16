"""Find A Crib's half of the owner dashboard's Monitor page (owner, 2026-11-15:
"a real time dashboard for monitoring user journeys, errors, etc. … what apis
get requests, what buttons get touched, latency, error rate trends … separate
mobile from web. do the same for findacrib").

Same answers, in the same shape, as Marracat's web/server/monitor.js, so the
dashboard page reads both. Kept in /var/lib/findacrib-api/monitor.sqlite:

  requests   every request this API answers: route pattern, status, time to
             answer, web / ios / bot. Timed in before/after_request.
  client     what the website reports to POST /monitor: taps (the label a
             person saw) and its calls to this API and to Supabase, timed as
             the visitor waited.
  sb_events  a copy of Supabase public.events and public.visits (synced every
             minute, 30 days back): the site's and the app's interactions,
             screens and errors (js_error, app_error …), each with its
             platform and session. That's where most of Find A Crib happens,
             since both clients talk to Supabase directly.
  hourly     totals per hour for ranges over a day, kept a year.

Journeys are anonymous (owner, 2026-11-15): visitor and session ids are stored
as salted hashes, shown as short codes. No user id, email, IP, query string
or typed text is kept. The owner's own traffic (OWNER_USER_ID, and every
visitor id that account ever used) is flagged and hidden unless asked for.
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from error_report import js_error_is_noise

KEEP_RAW_DAYS = 30
KEEP_HOURLY_DAYS = 400
RAW_MAX_MS = 86400_000
KINDS = ("tap", "screen", "api", "error")
FILTER_KINDS = KINDS + ("noise", "diag")   # what the stream can be narrowed to
RECLASS = "reclass_v1"   # sync_state marker: rows stored before error_kind() existed were re-sorted
PLATFORMS = ("web", "ios", "bot")
RANGES = {"15m": 15 * 60e3, "1h": 3600e3, "6h": 6 * 3600e3, "24h": 86400e3, "7d": 7 * 86400e3,
          "30d": 30 * 86400e3, "90d": 90 * 86400e3, "1y": 365 * 86400e3}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
APP_UA = re.compile(r"^(FindACrib|Find%20A%20Crib|Find A Crib)/", re.I)
NOT_A_PERSON = re.compile(r"bot|crawl|spider|headless|preview|lighthouse|slurp|facebookexternalhit|playwright|python-|curl/|wget|uptime", re.I)
VISITOR = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
SESSION = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
OWNER_USER = os.environ.get("OWNER_USER_ID", "")   # the owner's account id, set on the server only

# Supabase events: what each one is on the Monitor page.
# Views and things that fire on their own (geo_start: the page located the
# visitor; section_view: a building section scrolled into view) aren't taps.
SKIP_EVENTS = {"tile_served", "ad_impression", "tile_impression", "push_registered", "app_open", "visit",
               "usage_optin", "usage_optout", "push_permission", "section_view", "geo_start"}
SCREEN_EVENTS = {"building_view": "building", "results_view": "results", "signin_view": "sign in"}
ERROR_EVENTS = {"js_error", "app_error", "crash_trace", "render_storm"}
# Not every one of those is something to fix (owner, 2026-11-16: "what are
# these errors?" — the Errors table led with 129 render storms and Mediavine's
# ad scripts). Each row is stored as one of three kinds:
#   error  ours, worth chasing
#   noise  browser noise: an ad script, an extension or a dropped connection,
#          decided by the same js_error_is_noise() the morning digest uses
#   diag   a diagnostic tripwire, not a failure. render_storm fires when the
#          results list refreshes 4+ times in 5 s (index.html, since 9/6),
#          which panning and the page's own boot do routinely.
DIAG_EVENTS = {"render_storm"}
# Our own analytics writes. A phone that loses signal or leaves the page
# mid-send rejects them with no response; nothing on screen breaks, and the
# digest has always called that a dropped connection.
BEACON_ROUTES = {"POST /sb/rest/v1/events", "POST /sb/rest/v1/visits"}


def error_kind(ev, props):
    """error, noise or diag for one Supabase error event."""
    if ev in DIAG_EVENTS:
        return "diag"
    if ev == "js_error" and js_error_is_noise(props):
        return "noise"
    return "error"


def api_failure_kind(method, route, status):
    """None for a call that worked, else error or noise."""
    if not (status == 0 or (status or 0) >= 500):
        return None
    return "noise" if status == 0 and f"{method} {route}" in BEACON_ROUTES else "error"


def human(n):
    n = n.replace("_", " ").strip()
    return n[:1].upper() + n[1:]


def clean_text(s, mx=120):
    if not isinstance(s, str):
        return None
    t = re.sub(r"\s+", " ", s).strip()
    t = re.sub(r"(https?://[^\s?#]+)[?#]\S*", r"\1", t)
    t = re.sub(r"[^\s@]+@[^\s@]+\.[^\s@]+", "…@…", t)
    t = re.sub(r"\d[\d\s-]{5,}\d", "…", t)
    if not t:
        return None
    return t if len(t) <= mx else t[:mx - 1] + "…"


def route_of(p):
    """A path as a route pattern: ids, numbers and long tokens become :id."""
    if not isinstance(p, str):
        return None
    s = re.split(r"[?#]", p)[0]
    if s.startswith("http://") or s.startswith("https://"):
        try:
            u = urllib.parse.urlparse(s)
            s = ("/sb" if u.hostname and u.hostname.endswith(".supabase.co") else "") + u.path
        except ValueError:
            return None
    if not s.startswith("/"):
        return None
    parts = []
    for seg in s.split("/"):
        if seg and (re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", seg, re.I) or re.search(r"\d{4,}", seg) or len(seg) > 32 or re.search(r"[:,%@]", seg)):
            seg = ":id"
        parts.append(seg)
    r = re.sub(r"/{2,}", "/", "/".join(parts))
    return r[:120]


def platform_of(ua):
    ua = ua or ""
    if APP_UA.search(ua):
        return "ios"
    if NOT_A_PERSON.search(ua):
        return "bot"
    return "web"


def screen_of(path):
    """A page path as a screen name: "/" home, "/building/…" building, …"""
    if not isinstance(path, str):
        return None
    seg = [s for s in re.split(r"[?#]", path)[0].split("/") if s]
    if not seg:
        return "home"
    s = seg[0].lower()
    if s.endswith(".html"):
        s = s[:-5] or "home"
    if s in ("index", ""):
        return "home"
    return re.sub(r"[^a-z0-9_:-]", "", s)[:40] or "home"


def _num(v, lo, hi):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi else None


def clean_client(e, offset=0):
    if not isinstance(e, dict) or e.get("k") not in KINDS:
        return None
    row = {"kind": e["k"], "name": None, "screen": None, "method": None, "status": None, "ms": None, "message": None, "offset": offset}
    sc = e.get("sc")
    if isinstance(sc, str) and re.match(r"^[a-z0-9_:/-]{1,40}$", sc, re.I):
        row["screen"] = sc.lower()
    k = e["k"]
    if k == "tap":
        row["name"] = clean_text(e.get("n"), 80)
        if not row["name"]:
            return None
    elif k == "screen":
        row["name"] = row["screen"] or (e.get("n").lower() if isinstance(e.get("n"), str) and re.match(r"^[a-z0-9_:/-]{1,40}$", e.get("n"), re.I) else None)
        if not row["name"]:
            return None
        row["screen"] = row["name"]
    elif k == "api":
        row["name"] = route_of(e.get("n"))
        if not row["name"]:
            return None
        m = str(e.get("m") or "GET").upper()
        row["method"] = m if m in METHODS else "GET"
        row["status"] = _num(e.get("st"), 0, 599)
        row["ms"] = _num(e.get("ms"), 0, 120000)
        if row["status"] == 0 or (row["status"] or 0) >= 500:
            row["message"] = clean_text(e.get("msg"), 200)
    elif k == "error":
        row["message"] = clean_text(e.get("msg"), 200)
        if not row["message"]:
            return None
        row["name"] = clean_text(e.get("n"), 80) or "error"
    return row


def _pct(sorted_ms, p):
    if not sorted_ms:
        return None
    i = min(len(sorted_ms) - 1, max(0, -(-int(p * len(sorted_ms) * 1000) // 1000) - 1))
    return round(sorted_ms[i], 1)


def _stat(ms):
    ms.sort()
    return {"p50": _pct(ms, 0.5), "p95": _pct(ms, 0.95)}


def _bucket_for(span):
    for limit, b in ((15 * 60e3, 30e3), (3600e3, 60e3), (6 * 3600e3, 300e3), (86400e3, 900e3),
                     (7 * 86400e3, 3600e3), (30 * 86400e3, 6 * 3600e3)):
        if span <= limit:
            return int(b)
    return 86400_000


class Monitor:
    def __init__(self, path, salt, supabase_url="", service_key="", sync=True):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.salt = (salt or "monitor").encode()
        self.sb_url, self.sb_key = supabase_url.rstrip("/"), service_key
        self._req, self._cli = [], []
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS requests (ts INTEGER NOT NULL, platform TEXT NOT NULL, method TEXT NOT NULL, route TEXT NOT NULL,
                status INTEGER NOT NULL, ms REAL NOT NULL, build TEXT, owner INTEGER NOT NULL DEFAULT 0);
              CREATE INDEX IF NOT EXISTS requests_ts ON requests(ts);
              CREATE TABLE IF NOT EXISTS client (ts INTEGER NOT NULL, platform TEXT NOT NULL, visitor TEXT NOT NULL, session TEXT,
                kind TEXT NOT NULL, name TEXT, screen TEXT, method TEXT, status INTEGER, ms REAL, message TEXT, build TEXT,
                owner INTEGER NOT NULL DEFAULT 0);
              CREATE INDEX IF NOT EXISTS client_ts ON client(ts);
              CREATE INDEX IF NOT EXISTS client_visitor ON client(visitor, ts);
              CREATE TABLE IF NOT EXISTS sb_events (src TEXT NOT NULL, id INTEGER NOT NULL, ts INTEGER NOT NULL, platform TEXT NOT NULL,
                visitor TEXT NOT NULL, session TEXT, kind TEXT NOT NULL, name TEXT, screen TEXT, message TEXT, build TEXT,
                owner INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(src, id));
              CREATE INDEX IF NOT EXISTS sb_events_ts ON sb_events(ts);
              CREATE INDEX IF NOT EXISTS sb_events_visitor ON sb_events(visitor, ts);
              CREATE TABLE IF NOT EXISTS owner_visitors (visitor TEXT PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS sync_state (src TEXT PRIMARY KEY, last_id INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS hourly (hour INTEGER NOT NULL, platform TEXT NOT NULL, src TEXT NOT NULL, key TEXT NOT NULL,
                n INTEGER NOT NULL, errors INTEGER NOT NULL, p50 REAL, p95 REAL, visitors INTEGER, PRIMARY KEY(hour, platform, src, key));
            """)
        self._owner_cache = (0, set())
        if sync:
            threading.Thread(target=self._loop, daemon=True, name="monitor").start()

    # ---------- ids ----------
    def hv(self, v):
        return hmac.new(self.salt, ("monitor:" + str(v)).encode(), hashlib.sha256).hexdigest()[:16]

    def owners(self):
        t, s = self._owner_cache
        if time.time() - t > 60:
            with self.lock:
                s = {r[0] for r in self.db.execute("SELECT visitor FROM owner_visitors")}
            self._owner_cache = (time.time(), s)
        return s

    # ---------- writes ----------
    def request(self, row):
        self._req.append(row)
        if len(self._req) >= 300:
            self.flush()

    def client(self, row):
        self._cli.append(row)
        if len(self._cli) >= 300:
            self.flush()

    def flush(self):
        reqs, clis = self._req, self._cli
        self._req, self._cli = [], []
        if not reqs and not clis:
            return
        with self.lock:
            try:
                self.db.execute("BEGIN")
                self.db.executemany("INSERT INTO requests(ts,platform,method,route,status,ms,build,owner) VALUES(?,?,?,?,?,?,?,?)",
                                    [(r["ts"], r["platform"], r["method"], r["route"], r["status"], r["ms"], r.get("build"), 1 if r.get("owner") else 0) for r in reqs])
                self.db.executemany("""INSERT INTO client(ts,platform,visitor,session,kind,name,screen,method,status,ms,message,build,owner)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(c["ts"], c["platform"], c["visitor"], c.get("session"), c["kind"], c.get("name"), c.get("screen"), c.get("method"),
                      c.get("status"), c.get("ms"), c.get("message"), c.get("build"), 1 if c.get("owner") else 0) for c in clis])
                self.db.execute("COMMIT")
            except sqlite3.Error:
                self.db.execute("ROLLBACK")

    # ---------- Supabase copy ----------
    def _sb_get(self, table, params):
        url = f"{self.sb_url}/rest/v1/{table}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"apikey": self.sb_key, "Authorization": f"Bearer {self.sb_key}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def event_row(self, src, r):
        """One Supabase row as a sb_events row, or None when it isn't shown."""
        props = r.get("props") if isinstance(r.get("props"), dict) else {}
        try:
            d = datetime.datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            ts = int(d.timestamp() * 1000)
        except (KeyError, ValueError):
            return None
        visitor = self.hv(r.get("visitor_id") or "")
        platform = "ios" if (props.get("platform") == "ios" or str(r.get("path") or "").startswith("/app")) else "web"
        session = self.hv("s:" + str(props["sid"]))[:12] if props.get("sid") else None
        build = str(props.get("build"))[:6] if props.get("build") and str(props.get("build")).isdigit() else None
        owner = 1 if OWNER_USER and r.get("user_id") == OWNER_USER else 0
        if src == "visits":
            return (src, r["id"], ts, "web", visitor, None, "screen", screen_of(r.get("path")), screen_of(r.get("path")), None, None, owner)
        ev = str(r.get("event") or "")
        if not ev or ev in SKIP_EVENTS:
            return None
        if ev in ERROR_EVENTS:
            msg = props.get("msg") or props.get("message") or props.get("error") or props.get("kind") or human(ev)
            return (src, r["id"], ts, platform, visitor, session, error_kind(ev, props), ev, None, clean_text(str(msg), 200), build, owner)
        if ev in SCREEN_EVENTS or ev == "tab":
            sc = SCREEN_EVENTS.get(ev) or re.sub(r"[^a-z0-9_:-]", "", str(props.get("to") or props.get("tab") or "tab").lower())[:40] or "tab"
            return (src, r["id"], ts, platform, visitor, session, "screen", sc, sc, None, build, owner)
        detail = props.get("tool") or props.get("kind") or props.get("tab") or props.get("filter")
        name = human(ev) + (f" · {clean_text(str(detail), 30)}" if isinstance(detail, (str, int)) and str(detail) else "")
        return (src, r["id"], ts, platform, visitor, session, "tap", name, screen_of(r.get("path")) if platform == "web" else None, None, build, owner)

    def sync(self, max_pages=120):
        """Copy new events and visits; the first run goes 30 days back."""
        if not self.sb_url or not self.sb_key:
            return 0
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - KEEP_RAW_DAYS * 86400))
        n = 0
        for src, cols in (("events", "id,created_at,visitor_id,user_id,event,props,path"), ("visits", "id,created_at,visitor_id,user_id,path")):
            with self.lock:
                row = self.db.execute("SELECT last_id FROM sync_state WHERE src=?", (src,)).fetchone()
            last = row[0] if row else None
            for _ in range(max_pages):
                params = {"select": cols, "order": "id.asc", "limit": "1000"}
                if last is None:
                    params["created_at"] = f"gte.{since}"
                else:
                    params["id"] = f"gt.{last}"
                try:
                    rows = self._sb_get(src, params)
                except (urllib.error.URLError, ValueError, TimeoutError, OSError):
                    break
                if not rows:
                    break
                out, owners = [], set()
                for r in rows:
                    if OWNER_USER and r.get("user_id") == OWNER_USER and r.get("visitor_id"):
                        owners.add(self.hv(r["visitor_id"]))
                    e = self.event_row(src, r)
                    if e:
                        out.append(e)
                last = rows[-1]["id"]
                with self.lock:
                    self.db.execute("BEGIN")
                    self.db.executemany("INSERT OR IGNORE INTO sb_events(src,id,ts,platform,visitor,session,kind,name,screen,message,build,owner) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", out)
                    self.db.executemany("INSERT OR IGNORE INTO owner_visitors(visitor) VALUES(?)", [(o,) for o in owners])
                    self.db.execute("INSERT OR REPLACE INTO sync_state(src,last_id) VALUES(?,?)", (src, last))
                    self.db.execute("COMMIT")
                n += len(out)
                if owners:
                    self._owner_cache = (0, set())
                if len(rows) < 1000:
                    break
        return n

    def reclassify(self, now=None):
        """Once: sort rows stored before error_kind() into error / noise / diag,
        then rebuild the hourly totals they fed. Needs each js_error's props,
        which sb_events never kept, so they are read back from Supabase. Not
        marked done until that read succeeds."""
        with self.lock:
            if self.db.execute("SELECT 1 FROM sync_state WHERE src=?", (RECLASS,)).fetchone():
                return False
        if not self.sb_url or not self.sb_key:
            return False
        now = now or time.time() * 1000
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now / 1000 - KEEP_RAW_DAYS * 86400))
        noisy, last = [], None
        for _ in range(200):
            params = {"select": "id,props", "event": "eq.js_error", "order": "id.asc", "limit": "1000"}
            params["id" if last is not None else "created_at"] = f"gt.{last}" if last is not None else f"gte.{since}"
            rows = self._sb_get("events", params)   # raises: retried on the next loop
            noisy += [r["id"] for r in rows if js_error_is_noise(r.get("props"))]
            if len(rows) < 1000:
                break
            last = rows[-1]["id"]
        this_hour = int(now // 3600_000 * 3600_000)
        first = this_hour - KEEP_RAW_DAYS * 86400_000
        with self.lock:
            self.db.execute("BEGIN")
            self.db.execute(f"UPDATE sb_events SET kind='diag' WHERE kind='error' AND name IN ({','.join('?' * len(DIAG_EVENTS))})", sorted(DIAG_EVENTS))
            self.db.executemany("UPDATE sb_events SET kind='noise' WHERE src='events' AND id=? AND kind='error'", [(i,) for i in noisy])
            self.db.execute("DELETE FROM hourly WHERE hour>=?", (first,))
            self.db.execute("COMMIT")
        h = first
        while h < this_hour:
            self.rollup_hour(h)
            h += 3600_000
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO sync_state(src,last_id) VALUES(?,?)", (RECLASS, len(noisy)))
        return True

    def _loop(self):
        last_roll = 0
        while True:
            try:
                self.flush()
                self.reclassify()
                self.sync()
                if time.time() - last_roll > 600:
                    self.catch_up_rollups()
                    self.prune()
                    last_roll = time.time()
            except Exception as e:  # never take the API down
                print("monitor loop failed:", type(e).__name__, e, flush=True)
            for _ in range(30):
                time.sleep(2)
                self.flush()

    # ---------- rollups ----------
    def rollup_hour(self, hour):
        end = hour + 3600_000
        owners = self.owners()
        groups = {}

        def add(platform, src, key, ms, err, visitor=None):
            g = groups.setdefault((platform, src, key), {"n": 0, "errors": 0, "ms": [], "v": set()})
            g["n"] += 1
            g["errors"] += 1 if err else 0
            if ms is not None:
                g["ms"].append(ms)
            if visitor:
                g["v"].add(visitor)
        with self.lock:
            reqs = self.db.execute("SELECT platform, method, route, status, ms FROM requests WHERE ts>=? AND ts<? AND owner=0", (hour, end)).fetchall()
            clis = self.db.execute("SELECT platform, visitor, kind, name, screen, method, status, ms, message FROM client WHERE ts>=? AND ts<? AND owner=0", (hour, end)).fetchall()
            sbs = self.db.execute("SELECT platform, visitor, kind, name, screen, message FROM sb_events WHERE ts>=? AND ts<? AND owner=0", (hour, end)).fetchall()
        for r in reqs:
            add(r["platform"], "req", f"{r['method']} {r['route']}", r["ms"], r["status"] >= 500)
        for c in list(clis) + [dict(x, method=None, status=None, ms=None) for x in map(dict, sbs)]:
            c = dict(c)
            if c["visitor"] in owners:
                continue
            if c["kind"] == "api":
                fk = api_failure_kind(c["method"], c["name"], c["status"])
                add(c["platform"], "capi", f"{c['method']} {c['name']}", c["ms"], fk == "error", c["visitor"])
                if fk == "noise":
                    add(c["platform"], "noise", f"{c['method']} {c['name']} → no response", None, False, c["visitor"])
            elif c["kind"] in ("error", "noise", "diag"):
                add(c["platform"], c["kind"], c["message"] or c["name"], None, c["kind"] == "error", c["visitor"])
            else:
                add(c["platform"], c["kind"], (f"{c['screen']} › " if c["kind"] == "tap" and c.get("screen") else "") + (c["name"] or ""), None, False, c["visitor"])
            add(c["platform"], "visit", "*", None, False, c["visitor"])
        with self.lock:
            self.db.execute("BEGIN")
            for (platform, src, key), g in groups.items():
                st = _stat(g["ms"])
                self.db.execute("INSERT OR REPLACE INTO hourly(hour,platform,src,key,n,errors,p50,p95,visitors) VALUES(?,?,?,?,?,?,?,?,?)",
                                (hour, platform, src, key, g["n"], g["errors"], st["p50"], st["p95"], len(g["v"]) or None))
            self.db.execute("COMMIT")
        return len(groups)

    def catch_up_rollups(self, now=None):
        now = now or time.time() * 1000
        this_hour = int(now // 3600_000 * 3600_000)
        with self.lock:
            last = self.db.execute("SELECT MAX(hour) FROM hourly").fetchone()[0]
        h = max(last + 3600_000 if last is not None else this_hour - KEEP_RAW_DAYS * 86400_000, this_hour - KEEP_RAW_DAYS * 86400_000)
        n = 0
        while h < this_hour:
            self.rollup_hour(h)
            h += 3600_000
            n += 1
        return n

    def prune(self, now=None):
        now = now or time.time() * 1000
        raw = now - KEEP_RAW_DAYS * 86400_000
        with self.lock:
            for t in ("requests", "client", "sb_events"):
                self.db.execute(f"DELETE FROM {t} WHERE ts<?", (raw,))
            self.db.execute("DELETE FROM hourly WHERE hour<?", (now - KEEP_HOURLY_DAYS * 86400_000,))

    # ---------- reads ----------
    def _filters(self, q, table):
        where, args = [], []
        p = q.get("platform")
        if p in PLATFORMS:
            where.append("platform=?")
            args.append(p)
        else:
            where.append("platform<>'bot'")
        if q.get("owner") != "1":
            where.append("owner=0")
            if table != "requests":
                where.append("visitor NOT IN (SELECT visitor FROM owner_visitors)")
        b = q.get("build")
        if b and re.match(r"^\d{1,6}$", b):
            where.append("build=?")
            args.append(b)
        st = {"2xx": (200, 299), "3xx": (300, 399), "4xx": (400, 499), "5xx": (500, 599)}.get(q.get("status"))
        if st:
            if table == "sb_events":
                where.append("0")
            else:
                where.append(("kind='api' AND " if table == "client" else "") + "status BETWEEN ? AND ?")
                args += list(st)
        r = q.get("route")
        if r:
            if table == "requests":
                where.append("((method || ' ' || route)=? OR route=?)")
                args += [r, r]
            elif table == "client":
                where.append("((method || ' ' || name)=? OR name=?)")
                args += [r, r]
            else:
                where.append("0")
        k = q.get("kind")
        if table != "requests" and k in FILTER_KINDS:
            where.append("kind=?")
            args.append(k)
        if table == "requests" and k and k != "request":
            where.append("0")
        if table != "requests" and k == "request":
            where.append("0")
        sc = q.get("screen")
        if table != "requests" and sc and re.match(r"^[a-z0-9_:/ -]{1,40}$", sc, re.I):
            where.append("screen=?")
            args.append(sc)
        text = q.get("q")
        if text:
            like = "%" + re.sub(r"[%_]", "", str(text)[:80]) + "%"
            if table == "requests":
                where.append("route LIKE ?")
                args.append(like)
            else:
                where.append("(name LIKE ? OR message LIKE ? OR screen LIKE ?)")
                args += [like, like, like]
        v = q.get("visitor")
        if v and re.match(r"^[a-f0-9]{6,16}$", v):
            if table == "requests":
                where.append("0")
            else:
                where.append("visitor LIKE ?")
                args.append(v + "%")
        return (" AND " + " AND ".join(f"({w})" for w in where)) if where else "", args

    def overview(self, q, now=None):
        now = int(now or time.time() * 1000)
        rng = q.get("range") if q.get("range") in RANGES else "1h"
        span = RANGES[rng]
        since = now - span
        bucket = _bucket_for(span)
        nb = int(-(-span // bucket))
        start = since // bucket * bucket
        series = [{"t": int(start + i * bucket), "web": {"n": 0, "err": 0, "ms": []}, "ios": {"n": 0, "err": 0, "ms": []},
                   "bot": {"n": 0, "err": 0, "ms": []}} for i in range(nb + 1)]

        def slot(ts):
            return series[min(len(series) - 1, max(0, int((ts - start) // bucket)))]
        routes, taps, screens, errs, capi, builds = {}, {}, {}, {}, {}, set()
        diags = {}
        noise = {"n": 0, "v": set(), "vn": 0}
        visitors, sessions = set(), set()
        k = {"req": 0, "rerr": 0, "taps": 0, "cerr": 0, "ms": []}
        if span <= RAW_MAX_MS:
            rf, ra = self._filters(q, "requests")
            with self.lock:
                reqs = self.db.execute(f"SELECT ts, platform, method, route, status, ms, build FROM requests WHERE ts>=?{rf}", [since] + ra).fetchall()
                cf, ca = self._filters(q, "client")
                clis = self.db.execute(f"SELECT ts, platform, visitor, session, kind, name, screen, method, status, ms, message, build FROM client WHERE ts>=?{cf}", [since] + ca).fetchall()
                sf, sa = self._filters(q, "sb_events")
                sbs = self.db.execute(f"SELECT ts, platform, visitor, session, kind, name, screen, NULL method, NULL status, NULL ms, message, build FROM sb_events WHERE ts>=?{sf}", [since] + sa).fetchall()
            for r in reqs:
                s = slot(r["ts"])[r["platform"]]
                err = r["status"] >= 500
                s["n"] += 1
                s["err"] += err
                s["ms"].append(r["ms"])
                k["req"] += 1
                k["rerr"] += err
                k["ms"].append(r["ms"])
                key = f"{r['method']} {r['route']}"
                g = routes.setdefault(key, {"route": key, "n": 0, "errors": 0, "s4": 0, "ms": [], "web": 0, "ios": 0})
                g["n"] += 1
                g["errors"] += err
                g["s4"] += 1 if 400 <= r["status"] < 500 else 0
                g["ms"].append(r["ms"])
                if r["platform"] != "bot":
                    g[r["platform"]] += 1
                if r["build"]:
                    builds.add(r["build"])
            for c in list(clis) + list(sbs):
                visitors.add(c["visitor"])
                if c["session"]:
                    sessions.add(c["session"])
                if c["build"]:
                    builds.add(c["build"])
                kind = c["kind"]
                if kind == "tap":
                    k["taps"] += 1
                    g = taps.setdefault((c["screen"] or "", c["name"]), {"name": c["name"], "screen": c["screen"], "n": 0, "v": set(), "web": 0, "ios": 0})
                    g["n"] += 1
                    g["v"].add(c["visitor"])
                    g[c["platform"]] = g.get(c["platform"], 0) + 1
                elif kind == "screen":
                    g = screens.setdefault(c["name"], {"screen": c["name"], "n": 0, "v": set()})
                    g["n"] += 1
                    g["v"].add(c["visitor"])
                elif kind == "api":
                    fk = api_failure_kind(c["method"], c["name"], c["status"])
                    err = fk == "error"
                    key = f"{c['method']} {c['name']}"
                    if fk == "noise":
                        noise["n"] += 1
                        noise["v"].add(c["visitor"])
                    g = capi.setdefault(key, {"route": key, "n": 0, "errors": 0, "ms": []})
                    g["n"] += 1
                    g["errors"] += err
                    if c["ms"] is not None:
                        g["ms"].append(c["ms"])
                    if err:
                        k["cerr"] += 1
                        e = errs.setdefault("api\0" + key, {"source": "client", "kind": "failed request",
                                                             "message": key + (f" → {c['status']}" if c["status"] else " → no response"),
                                                             "n": 0, "last": 0, "platforms": set(), "v": set()})
                        e["n"] += 1
                        e["last"] = max(e["last"], c["ts"])
                        e["platforms"].add(c["platform"])
                        e["v"].add(c["visitor"])
                elif kind == "noise":
                    noise["n"] += 1
                    noise["v"].add(c["visitor"])
                elif kind in ("error", "diag"):
                    if kind == "error":
                        k["cerr"] += 1
                    msg = c["message"] or c["name"]
                    e = (errs if kind == "error" else diags).setdefault("err\0" + msg, {"source": "client", "kind": c["name"], "message": msg, "n": 0, "last": 0, "platforms": set(), "v": set()})
                    e["n"] += 1
                    e["last"] = max(e["last"], c["ts"])
                    e["platforms"].add(c["platform"])
                    e["v"].add(c["visitor"])
            for g in routes.values():
                if g["errors"]:
                    e = errs.setdefault("srv\0" + g["route"], {"source": "server", "kind": "5xx", "message": g["route"] + " answered 5xx",
                                                              "n": 0, "last": 0, "platforms": set(), "v": set()})
                    e["n"] += g["errors"]
        else:
            p = q.get("platform") if q.get("platform") in PLATFORMS else None
            with self.lock:
                rows = self.db.execute("SELECT * FROM hourly WHERE hour>=?" + (" AND platform=?" if p else " AND platform<>'bot'"),
                                       [since] + ([p] if p else [])).fetchall()
            like = (q.get("q") or "").lower() or None
            for h in rows:
                if like and like not in h["key"].lower():
                    continue
                if q.get("route") and h["key"] != q["route"]:
                    continue
                if h["src"] == "req":
                    s = slot(h["hour"])[h["platform"]]
                    s["n"] += h["n"]
                    s["err"] += h["errors"]
                    if h["p50"] is not None:
                        s["ms"].append(h["p50"])
                    s.setdefault("p95s", [])
                    if h["p95"] is not None:
                        s["p95s"].append(h["p95"])
                    k["req"] += h["n"]
                    k["rerr"] += h["errors"]
                    if h["p50"] is not None:
                        k["ms"].append(h["p50"])
                    g = routes.setdefault(h["key"], {"route": h["key"], "n": 0, "errors": 0, "s4": 0, "ms": [], "p95s": [], "web": 0, "ios": 0})
                    g["n"] += h["n"]
                    g["errors"] += h["errors"]
                    if h["p50"] is not None:
                        g["ms"].append(h["p50"])
                    if h["p95"] is not None:
                        g["p95s"].append(h["p95"])
                    if h["platform"] != "bot":
                        g[h["platform"]] += h["n"]
                elif h["src"] == "tap":
                    k["taps"] += h["n"]
                    screen, name = h["key"].split(" › ", 1) if " › " in h["key"] else (None, h["key"])
                    g = taps.setdefault(h["key"], {"name": name, "screen": screen, "n": 0, "v": set(), "vn": 0, "web": 0, "ios": 0})
                    g["n"] += h["n"]
                    g["vn"] += h["visitors"] or 0
                    g[h["platform"]] = g.get(h["platform"], 0) + h["n"]
                elif h["src"] == "screen":
                    g = screens.setdefault(h["key"], {"screen": h["key"], "n": 0, "v": set(), "vn": 0})
                    g["n"] += h["n"]
                    g["vn"] += h["visitors"] or 0
                elif h["src"] == "capi":
                    g = capi.setdefault(h["key"], {"route": h["key"], "n": 0, "errors": 0, "ms": []})
                    g["n"] += h["n"]
                    g["errors"] += h["errors"]
                    if h["p50"] is not None:
                        g["ms"].append(h["p50"])
                    k["cerr"] += h["errors"]
                elif h["src"] == "noise":
                    noise["n"] += h["n"]
                    noise["vn"] += h["visitors"] or 0
                elif h["src"] in ("error", "diag"):
                    if h["src"] == "error":
                        k["cerr"] += h["n"]
                    e = (errs if h["src"] == "error" else diags).setdefault("err\0" + h["key"], {"source": "client", "kind": "error" if h["src"] == "error" else "diagnostic", "message": h["key"], "n": 0, "last": 0,
                                                            "platforms": set(), "v": set(), "vn": 0})
                    e["n"] += h["n"]
                    e["last"] = max(e["last"], h["hour"] + 3600_000)
                    e["platforms"].add(h["platform"])
                    e["vn"] += h["visitors"] or 0

        def out(g):
            st = _stat(g["ms"])
            if g.get("p95s"):
                st["p95"] = _stat(g["p95s"])["p95"]
            return st
        k["ms"].sort()
        by_n = lambda d: sorted(d.values(), key=lambda g: -g["n"])
        return {
            "range": rng, "since": since, "until": now, "bucket_ms": bucket, "source": "raw" if span <= RAW_MAX_MS else "hourly",
            "kpis": {"requests": k["req"], "server_errors": k["rerr"], "error_rate": round(k["rerr"] / k["req"] * 100, 2) if k["req"] else 0,
                     "p50": _pct(k["ms"], 0.5), "p95": _pct(k["ms"], 0.95),
                     "visitors": len(visitors) if span <= RAW_MAX_MS else None, "sessions": len(sessions) if span <= RAW_MAX_MS else None,
                     "taps": k["taps"], "client_errors": k["cerr"]},
            "series": [{"t": s["t"], **{p: {"n": s[p]["n"], "err": s[p]["err"], **out(s[p])} for p in ("web", "ios", "bot")}} for s in series],
            "routes": [{"route": g["route"], "n": g["n"], "errors": g["errors"], "s4": g["s4"], "error_rate": round(g["errors"] / g["n"] * 100, 2) if g["n"] else 0,
                        "web": g["web"], "ios": g["ios"], **out(g)} for g in by_n(routes)[:40]],
            "client_routes": [{"route": g["route"], "n": g["n"], "errors": g["errors"], **out(g)} for g in by_n(capi)[:25]],
            "taps": [{"name": g["name"], "screen": g["screen"], "n": g["n"], "visitors": g.get("vn") or len(g["v"]), "web": g.get("web", 0), "ios": g.get("ios", 0)}
                     for g in by_n(taps)[:40]],
            "screens": [{"screen": g["screen"], "n": g["n"], "visitors": g.get("vn") or len(g["v"])} for g in by_n(screens)[:25]],
            "errors": [{"source": e["source"], "kind": e["kind"], "message": e["message"], "n": e["n"], "last": e["last"] or None,
                        "platforms": sorted(e["platforms"]), "visitors": e.get("vn") or len(e["v"])} for e in by_n(errs)[:40]],
            # Kept apart from errors (see error_kind): the page shows noise as one
            # grey line and diagnostics in their own small table.
            "noise": {"n": noise["n"], "visitors": noise["vn"] or len(noise["v"])},
            "diagnostics": [{"source": e["source"], "kind": e["kind"], "message": e["message"], "n": e["n"], "last": e["last"] or None,
                             "platforms": sorted(e["platforms"]), "visitors": e.get("vn") or len(e["v"])} for e in by_n(diags)[:10]],
            "builds": sorted(builds, key=lambda b: -int(b))[:15],
        }

    def stream(self, q, now=None, limit=200):
        now = int(now or time.time() * 1000)
        span = min(RANGES.get(q.get("range"), RANGES["1h"]), RAW_MAX_MS * 30)
        since = max(now - span, int(q.get("after") or 0) if str(q.get("after") or "").isdigit() else 0)
        rf, ra = self._filters(q, "requests")
        cf, ca = self._filters(q, "client")
        sf, sa = self._filters(q, "sb_events")
        with self.lock:
            reqs = self.db.execute(f"SELECT ts, platform, method, route, status, ms, build, owner FROM requests WHERE ts>?{rf} ORDER BY ts DESC LIMIT ?", [since] + ra + [limit]).fetchall()
            clis = self.db.execute(f"""SELECT ts, platform, substr(visitor,1,8) visitor, substr(session,1,8) session, kind, name, screen, method, status, ms, message, build, owner
                FROM client WHERE ts>?{cf} ORDER BY ts DESC LIMIT ?""", [since] + ca + [limit]).fetchall()
            sbs = self.db.execute(f"""SELECT ts, platform, substr(visitor,1,8) visitor, substr(session,1,8) session, kind, name, screen, message, build, owner
                FROM sb_events WHERE ts>?{sf} ORDER BY ts DESC LIMIT ?""", [since] + sa + [limit]).fetchall()
        rows = [dict(r, src="server", kind="request", name=r["route"]) for r in map(dict, reqs)] + \
               [dict(r, src="client") for r in map(dict, clis)] + [dict(r, src="app") for r in map(dict, sbs)]
        rows.sort(key=lambda r: -r["ts"])
        return {"rows": rows[:limit], "until": now}

    def journey(self, visitor, q=None, now=None):
        q = q or {}
        if not re.match(r"^[a-f0-9]{6,16}$", visitor or ""):
            return {"visitor": None, "sessions": []}
        now = int(now or time.time() * 1000)
        since = now - KEEP_RAW_DAYS * 86400_000
        own = "" if q.get("owner") == "1" else " AND owner=0"
        with self.lock:
            rows = [dict(r) for r in self.db.execute(f"""SELECT ts, platform, session, kind, name, screen, method, status, ms, message, build FROM client
                     WHERE visitor LIKE ? AND ts>=?{own}
                     UNION ALL SELECT ts, platform, session, kind, name, screen, NULL, NULL, NULL, message, build FROM sb_events
                     WHERE visitor LIKE ? AND ts>=?{own} ORDER BY ts LIMIT 2000""", (visitor + "%", since, visitor + "%", since))]
        sessions = []
        for r in rows:
            key = r["session"] or "—"
            s = sessions[-1] if sessions else None
            if not s or (r["session"] and s["session"] != key and s["session"] != "—") or r["ts"] - s["end"] > 30 * 60_000:
                s = {"session": key, "start": r["ts"], "end": r["ts"], "platform": r["platform"], "build": r["build"], "rows": []}
                sessions.append(s)
            s["end"] = r["ts"]
            s["rows"].append(r)
        return {"visitor": visitor, "sessions": list(reversed(sessions))[:30]}


# ---------- Flask wiring ----------

def init_app(app, env=os.environ):
    """Time every request, take the website's reports at POST /monitor, and
    answer the dashboard at GET /owner/monitor (behind MONITOR_KEY)."""
    from flask import g, jsonify, request

    data_dir = env.get("MONITOR_DIR", "/var/lib/findacrib-api")
    try:
        os.makedirs(data_dir, exist_ok=True)
        if not os.access(data_dir, os.W_OK):
            raise PermissionError(data_dir)
    except OSError:   # a laptop or the test run: keep it out of the way
        import tempfile
        data_dir = os.path.join(tempfile.gettempdir(), "findacrib-monitor")
        os.makedirs(data_dir, exist_ok=True)
    mon = Monitor(os.path.join(data_dir, "monitor.sqlite"), env.get("MONITOR_SALT") or env.get("SUPABASE_SERVICE_ROLE_KEY", "")[-24:] or "monitor",
                  env.get("SUPABASE_URL", "https://dbaifotzwlxjvsxjohjt.supabase.co"), env.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                  sync=env.get("MONITOR_SYNC", "1") == "1" and bool(env.get("SUPABASE_SERVICE_ROLE_KEY")))
    key = env.get("MONITOR_KEY", "")
    budget = {"minute": 0, "ips": {}}

    @app.before_request
    def _monitor_start():
        g._mon_t0 = time.perf_counter()

    @app.after_request
    def _monitor_log(resp):
        try:
            p = request.path or ""
            if re.match(r"^/(monitor|owner/|health\b)", p) or not hasattr(g, "_mon_t0"):
                return resp
            rule = request.url_rule.rule if request.url_rule is not None else None
            route = route_of(re.sub(r"<(?:[^:>]+:)?([^>]+)>", r":\1", rule)) if rule else route_of(p)
            if route:
                ua = request.headers.get("User-Agent", "")
                m = re.match(r"^\S+?/(\d{1,6})\b", ua) if APP_UA.search(ua) else None
                mon.request({"ts": int(time.time() * 1000), "platform": platform_of(ua), "method": request.method, "route": route,
                             "status": resp.status_code, "ms": round((time.perf_counter() - g._mon_t0) * 1000, 2),
                             "build": m.group(1) if m else None, "owner": False})
        except Exception:
            pass
        return resp

    @app.route("/monitor", methods=["POST"])
    def monitor_ingest():
        ua = request.headers.get("User-Agent", "")
        if NOT_A_PERSON.search(ua):
            return "", 204
        body = request.get_json(silent=True, force=True) or {}
        ev = body.get("ev") if isinstance(body.get("ev"), list) else []
        if not ev or len(ev) > 100:
            return "", 400
        raw = str(body.get("id") or "")
        if not VISITOR.match(raw):
            return "", 400
        ip = request.headers.get("X-Real-IP") or request.remote_addr or "?"
        minute = int(time.time() // 60)
        if minute != budget["minute"]:
            budget["minute"], budget["ips"] = minute, {}
        used = budget["ips"].get(ip, 0) + len(ev)
        if used > 1500:
            return "", 429
        budget["ips"][ip] = used
        now = int(time.time() * 1000)
        cnow = _num(body.get("now"), 0, 1e14)
        visitor = mon.hv(raw)
        owner = visitor in mon.owners()
        session = mon.hv("s:" + body["s"])[:12] if isinstance(body.get("s"), str) and SESSION.match(body["s"]) else None
        n = 0
        for e in ev:
            off = min(600000, max(0, cnow - e.get("t"))) if cnow is not None and isinstance(e, dict) and _num(e.get("t"), 0, 1e14) is not None else 0
            r = clean_client(e, off)
            if not r:
                continue
            mon.client({"ts": now - int(r["offset"]), "platform": "web", "visitor": visitor, "session": session, "kind": r["kind"], "name": r["name"],
                        "screen": r["screen"], "method": r["method"], "status": r["status"], "ms": r["ms"], "message": r["message"], "build": None, "owner": owner})
            n += 1
        return ("", 204) if n else ("", 400)

    @app.route("/owner/monitor")
    def monitor_read():
        given = request.headers.get("X-Metrics-Key", "")
        if len(key) < 32 or not hmac.compare_digest(hashlib.sha256(key.encode()).digest(), hashlib.sha256(given.encode()).digest()):
            return "", 404
        mon.flush()
        q = {k: v for k, v in request.args.items() if isinstance(v, str)}
        view = q.get("view", "overview")
        try:
            if view == "stream":
                data = mon.stream(q)
            elif view == "journey":
                data = mon.journey(q.get("visitor"), q)
            else:
                data = mon.overview(q)
        except Exception as e:
            print("monitor query failed:", type(e).__name__, e, flush=True)
            return jsonify(error="query_failed"), 500
        resp = jsonify(data)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    return mon
