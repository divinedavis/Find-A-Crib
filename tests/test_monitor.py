"""pipeline/monitor.py, Find A Crib's half of the owner dashboard's Monitor page
(2026-11-15): cleaning, route patterns, the Supabase event mapping, owner
hiding, the overview / stream / journey answers and hourly rollups. Offline:
no Supabase, no Flask needed (the Flask wiring is checked only when Flask is
installed)."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import monitor  # noqa: E402

NOW = int(time.time() * 1000)


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000)) + ".123+00:00"


class Cleaning(unittest.TestCase):
    def test_text_loses_emails_numbers_and_query_strings(self):
        self.assertEqual(monitor.clean_text("hi a@b.co"), "hi …@…")
        self.assertEqual(monitor.clean_text("card 4111 1111 1111 1111"), "card …")
        self.assertEqual(monitor.clean_text("GET https://x.test/a?token=1 failed"), "GET https://x.test/a failed")
        self.assertIsNone(monitor.clean_text("  "))

    def test_route_patterns(self):
        self.assertEqual(monitor.route_of("/v1/buildings/3012340056?x=1"), "/v1/buildings/:id")
        self.assertEqual(monitor.route_of("https://abc.supabase.co/rest/v1/listings?select=*"), "/sb/rest/v1/listings")
        self.assertIsNone(monitor.route_of("nope"))
        self.assertEqual(monitor.platform_of("FindACrib/104 CFNetwork/1.0"), "ios")
        self.assertEqual(monitor.platform_of("Mozilla/5.0 (Macintosh)"), "web")
        self.assertEqual(monitor.platform_of("Googlebot/2.1"), "bot")
        self.assertEqual(monitor.screen_of("/"), "home")
        self.assertEqual(monitor.screen_of("/brooklyn/williamsburg?x=1"), "brooklyn")

    def test_client_rows(self):
        self.assertEqual(monitor.clean_client({"k": "tap", "n": " Save  building ", "sc": "home"})["name"], "Save building")
        self.assertIsNone(monitor.clean_client({"k": "keystroke", "n": "a"}))
        a = monitor.clean_client({"k": "api", "n": "/api/ai/search?q=x", "m": "post", "st": 503, "ms": 900, "msg": "boom"})
        self.assertEqual((a["name"], a["method"], a["status"], a["message"]), ("/api/ai/search", "POST", 503, "boom"))
        self.assertIsNone(monitor.clean_client({"k": "api", "n": "/x", "st": 200, "ms": 3, "msg": "fine"})["message"])


class Data(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.m = monitor.Monitor(os.path.join(self.dir, "m.sqlite"), "salt", sync=False)
        monitor.OWNER_USER = "owner-uuid"
        m = self.m
        for i in range(10):
            m.request({"ts": NOW - i * 60_000, "platform": "web", "method": "GET", "route": "/v1/buildings/:id", "status": 200, "ms": 10 + i})
        m.request({"ts": NOW - 120_000, "platform": "web", "method": "GET", "route": "/v1/buildings/:id", "status": 500, "ms": 800})
        m.request({"ts": NOW - 60_000, "platform": "ios", "method": "POST", "route": "/push/register", "status": 200, "ms": 40, "build": "104"})
        m.request({"ts": NOW - 60_000, "platform": "bot", "method": "GET", "route": "/v1", "status": 200, "ms": 2})
        m.client({"ts": NOW - 90_000, "platform": "web", "visitor": m.hv("v-web-1"), "session": "s1", "kind": "tap", "name": "Save", "screen": "home"})
        m.client({"ts": NOW - 80_000, "platform": "web", "visitor": m.hv("v-web-1"), "session": "s1", "kind": "api", "name": "/sb/rest/v1/listings",
                  "method": "GET", "status": 200, "ms": 120})
        m.flush()
        rows = [
            {"id": 1, "created_at": iso(NOW - 300_000), "visitor_id": "v-app-1", "user_id": None, "event": "building_view", "props": {"platform": "ios", "sid": "a1", "build": 104}, "path": "/app"},
            {"id": 2, "created_at": iso(NOW - 290_000), "visitor_id": "v-app-1", "user_id": None, "event": "save", "props": {"platform": "ios", "sid": "a1", "build": 104}, "path": "/app"},
            {"id": 3, "created_at": iso(NOW - 280_000), "visitor_id": "v-web-2", "user_id": None, "event": "js_error", "props": {"platform": "web", "msg": "x is undefined at a@b.co"}, "path": "/"},
            {"id": 4, "created_at": iso(NOW - 270_000), "visitor_id": "v-web-2", "user_id": None, "event": "tile_served", "props": {"platform": "web"}, "path": "/"},
            {"id": 5, "created_at": iso(NOW - 260_000), "visitor_id": "v-owner", "user_id": "owner-uuid", "event": "save", "props": {"platform": "web"}, "path": "/"},
            {"id": 6, "created_at": iso(NOW - 250_000), "visitor_id": "v-web-2", "user_id": None, "event": "tab", "props": {"platform": "ios", "to": "Map"}, "path": "/app"},
            {"id": 7, "created_at": iso(NOW - 240_000), "visitor_id": "v-web-2", "user_id": None, "event": "section_view", "props": {"platform": "web", "sec": "photo"}, "path": "/"},
            {"id": 8, "created_at": iso(NOW - 230_000), "visitor_id": "v-web-2", "user_id": None, "event": "geo_start", "props": {"platform": "web", "boro": "M"}, "path": "/"},
        ]
        out = [e for e in (m.event_row("events", r) for r in rows) if e]
        out.append(m.event_row("visits", {"id": 9, "created_at": iso(NOW - 200_000), "visitor_id": "v-web-2", "user_id": None, "path": "/brooklyn/x"}))
        m.db.executemany("INSERT INTO sb_events(src,id,ts,platform,visitor,session,kind,name,screen,message,build,owner) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", out)
        m.db.execute("INSERT INTO owner_visitors(visitor) VALUES(?)", (m.hv("v-owner"),))

    def test_event_mapping(self):
        r = self.m.event_row("events", {"id": 1, "created_at": iso(NOW), "visitor_id": "v", "event": "outbound", "props": {"platform": "web", "kind": "zillow"}, "path": "/b"})
        self.assertEqual((r[6], r[7]), ("tap", "Outbound · zillow"))
        self.assertIsNone(self.m.event_row("events", {"id": 2, "created_at": iso(NOW), "visitor_id": "v", "event": "ad_impression", "props": {}}))
        e = self.m.event_row("events", {"id": 3, "created_at": iso(NOW), "visitor_id": "v", "event": "js_error", "props": {"msg": "boom"}})
        self.assertEqual((e[6], e[9]), ("error", "boom"))
        self.assertNotEqual(r[4], "v", "visitor ids are hashed")

    def test_overview(self):
        o = self.m.overview({"range": "1h"}, NOW)
        k = o["kpis"]
        self.assertEqual(k["requests"], 12, "no bots")
        self.assertEqual(k["server_errors"], 1)
        self.assertEqual(o["routes"][0]["route"], "GET /v1/buildings/:id")
        saves = sum(t["n"] for t in o["taps"] if t["name"] == "Save")
        self.assertEqual(saves, 2, "web Save + app save (counted per screen); the owner's save is hidden")
        self.assertIn("building", {s["screen"] for s in o["screens"]})
        self.assertIn("map", {s["screen"] for s in o["screens"]}, "an app tab is named by where it went")
        self.assertFalse({"Section view", "Geo start"} & {t["name"] for t in o["taps"]}, "views and automatic events aren't taps")
        self.assertIn("brooklyn", {s["screen"] for s in o["screens"]})
        self.assertTrue(any(e["message"] == "x is undefined at …@…" for e in o["errors"]))
        self.assertTrue(any(e["source"] == "server" for e in o["errors"]))
        self.assertIn("104", o["builds"])
        self.assertEqual(self.m.overview({"range": "1h", "platform": "ios"}, NOW)["kpis"]["requests"], 1)
        self.assertEqual(sum(t["n"] for t in self.m.overview({"range": "1h", "owner": "1"}, NOW)["taps"] if t["name"] == "Save"), 3)
        self.assertEqual(self.m.overview({"range": "1h", "status": "5xx"}, NOW)["kpis"]["requests"], 1)

    def test_stream_and_journey(self):
        s = self.m.stream({"range": "1h"}, NOW)
        self.assertTrue(all(a["ts"] >= b["ts"] for a, b in zip(s["rows"], s["rows"][1:])))
        self.assertEqual({r["src"] for r in s["rows"]}, {"server", "client", "app"})
        self.assertEqual(len(self.m.stream({"range": "1h", "kind": "request"}, NOW)["rows"]), 12)
        code = self.m.hv("v-app-1")[:8]
        j = self.m.journey(code, {}, NOW)
        self.assertEqual([r["kind"] for r in j["sessions"][0]["rows"]], ["screen", "tap"])
        self.assertIsNone(self.m.journey("zz")["visitor"])

    def test_rollups_and_pruning(self):
        self.assertGreater(self.m.catch_up_rollups(NOW + 3600_000), 0)
        o = self.m.overview({"range": "7d"}, NOW + 3600_000)
        self.assertEqual(o["source"], "hourly")
        self.assertEqual(o["kpis"]["requests"], 12)
        self.m.prune(NOW + 31 * 86400_000)
        self.assertEqual(self.m.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)
        self.assertGreater(self.m.db.execute("SELECT COUNT(*) FROM hourly").fetchone()[0], 0)


class NoiseAndDiagnostics(unittest.TestCase):
    """Owner, 2026-11-16: "what are these errors?" The Errors table led with
    render storms and Mediavine's ad scripts. Those are kept apart now."""
    AD = {"platform": "web", "msg": "Failed parsing identifiers", "kind": "promise", "name": "Error",
          "at": "s@https://scripts.journeymv.com/tags/optable/1af4864eafad1bbd65ea.min.js:1:22267"}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.m = m = monitor.Monitor(os.path.join(self.dir, "m.sqlite"), "salt", sync=False)
        rows = [
            {"id": 1, "created_at": iso(NOW - 300_000), "visitor_id": "v1", "user_id": None, "event": "js_error", "props": {"platform": "web", "msg": "x is undefined"}, "path": "/"},
            {"id": 2, "created_at": iso(NOW - 290_000), "visitor_id": "v1", "user_id": None, "event": "js_error", "props": self.AD, "path": "/"},
            {"id": 3, "created_at": iso(NOW - 280_000), "visitor_id": "v2", "user_id": None, "event": "js_error", "props": {"platform": "web", "msg": "Script error."}, "path": "/"},
            {"id": 4, "created_at": iso(NOW - 270_000), "visitor_id": "v2", "user_id": None, "event": "render_storm", "props": {"platform": "web", "grid": 5}, "path": "/"},
        ]
        m.db.executemany("INSERT INTO sb_events(src,id,ts,platform,visitor,session,kind,name,screen,message,build,owner) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         [m.event_row("events", r) for r in rows])
        m.client({"ts": NOW - 60_000, "platform": "web", "visitor": m.hv("v3"), "kind": "api", "name": "/sb/rest/v1/events", "method": "POST", "status": 0, "ms": 9})
        m.client({"ts": NOW - 50_000, "platform": "web", "visitor": m.hv("v3"), "kind": "api", "name": "/sb/rest/v1/listings", "method": "GET", "status": 0, "ms": 9})
        m.flush()

    def test_kinds_at_ingest(self):
        kinds = dict(self.m.db.execute("SELECT id, kind FROM sb_events").fetchall())
        self.assertEqual(kinds, {1: "error", 2: "noise", 3: "noise", 4: "diag"})
        self.assertEqual(monitor.api_failure_kind("POST", "/sb/rest/v1/events", 0), "noise")
        self.assertEqual(monitor.api_failure_kind("POST", "/sb/rest/v1/events", 503), "error", "a 5xx from Supabase is still ours to know")
        self.assertEqual(monitor.api_failure_kind("GET", "/sb/rest/v1/listings", 0), "error")
        self.assertIsNone(monitor.api_failure_kind("GET", "/x", 200))

    def check(self, o, hourly=False):
        msgs = [e["message"] for e in o["errors"]]
        self.assertIn("x is undefined", msgs)
        if not hourly:   # hourly totals count failed calls per route but don't list them
            self.assertIn("GET /sb/rest/v1/listings → no response", msgs)
        self.assertFalse({"Failed parsing identifiers", "Script error.", "POST /sb/rest/v1/events → no response"} & set(msgs))
        self.assertFalse(any("storm" in m.lower() for m in msgs))
        self.assertEqual(o["noise"]["n"], 3, "ad script + Script error. + dropped analytics ping")
        self.assertEqual([d["message"] for d in o["diagnostics"]], ["Render storm"])
        self.assertEqual(o["kpis"]["client_errors"], 2)

    def test_overview_raw(self):
        self.check(self.m.overview({"range": "1h"}, NOW))

    def test_overview_hourly(self):
        self.m.catch_up_rollups(NOW + 3600_000)
        self.check(self.m.overview({"range": "7d"}, NOW + 3600_000), hourly=True)

    def test_stream_filters_by_kind(self):
        self.assertEqual({r["kind"] for r in self.m.stream({"range": "1h", "kind": "noise"}, NOW)["rows"]}, {"noise"})
        self.assertEqual(len(self.m.stream({"range": "1h", "kind": "diag"}, NOW)["rows"]), 1)

    def test_reclassify_old_rows_once(self):
        m = self.m
        m.db.execute("UPDATE sb_events SET kind='error'")   # as stored before error_kind()
        m.catch_up_rollups(NOW + 3600_000)
        m.sb_url, m.sb_key = "https://x.test", "k"
        calls = []
        m._sb_get = lambda table, params: calls.append(params) or [{"id": 2, "props": self.AD}, {"id": 3, "props": {"msg": "Script error."}}, {"id": 1, "props": {"msg": "x"}}]
        self.assertTrue(m.reclassify(NOW + 3600_000))
        self.assertEqual(dict(m.db.execute("SELECT id, kind FROM sb_events").fetchall()), {1: "error", 2: "noise", 3: "noise", 4: "diag"})
        self.check(m.overview({"range": "7d"}, NOW + 3600_000), hourly=True)
        self.assertFalse(m.reclassify(NOW + 3600_000), "runs once")
        self.assertEqual(len(calls), 1)

    def test_reclassify_waits_for_supabase(self):
        m = self.m
        m.sb_url, m.sb_key = "https://x.test", "k"

        def down(table, params):
            raise OSError("down")
        m._sb_get = down
        with self.assertRaises(OSError):
            m.reclassify(NOW)
        self.assertIsNone(m.db.execute("SELECT 1 FROM sync_state WHERE src=?", (monitor.RECLASS,)).fetchone(), "tried again next loop")


class NoPersonalData(unittest.TestCase):
    def test_no_owner_id_in_code(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "pipeline", "monitor.py")).read()
        self.assertNotRegex(src, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


if __name__ == "__main__":
    unittest.main()


class WebsiteHalf(unittest.TestCase):
    ROOT = os.path.join(os.path.dirname(__file__), "..")

    def test_pages_load_the_monitor_before_their_own_scripts(self):
        for page in ("web/index.html", "web/casa/index.html"):
            html = open(os.path.join(self.ROOT, page)).read()
            i = html.find('<script src="/static/platform/monitor.js')
            self.assertGreater(i, 0, page)
            self.assertEqual(html.find("<script"), i, f"{page}: the monitor must load first so Supabase's fetch is timed")

    def test_script_never_reads_typed_text_and_is_shipped(self):
        js = open(os.path.join(self.ROOT, "web/static/platform/monitor.js")).read()
        self.assertNotIn("textarea", js)
        self.assertNotRegex(js, r'input\[type="(text|search|email|password)')
        self.assertIn("/api/monitor", js)
        self.assertIn("navigator.webdriver", js, "the journey suite's browsers must not count as visitors")
        deploy = open(os.path.join(self.ROOT, "scripts/deploy_app.sh")).read()
        self.assertIn("static/platform/monitor.js", deploy)


    def test_a_failed_fetch_names_its_caller_not_the_wrapper(self):
        """monitor.js wraps window.fetch, so a failed request's stack starts in
        the wrapper. The page reports the first frame outside it (2026-11-17:
        an ad script's "Failed to fetch" read as ours, at monitor.js:52)."""
        import re
        import shutil
        import subprocess
        node = shutil.which("node")
        for page in ("web/index.html", "web/dc/index.html", "web/la/index.html",
                     "web/sf/index.html", "web/westchester/index.html"):
            html = open(os.path.join(self.ROOT, page)).read()
            m = re.search(r"\n\s*(const frames = .*?\n\s*const where = .*?;)\n", html)
            self.assertIsNotNone(m, f"{page}: the rejection handler must skip monitor.js frames")
            if not node:
                continue
            js = ("const r = {stack: 'TypeError: Failed to fetch\\n"
                  "    at window.fetch (https://findacrib.com/static/platform/monitor.js?v=1:52:30)\\n"
                  "    at x (https://c.amazon-adsystem.com/aax2/apstag.js:2:1)'};\n"
                  + m.group(1) + "\nconsole.log(where);\n"
                  "const alone = {stack: 'TypeError: Failed to fetch\\n    at window.fetch (https://findacrib.com/static/platform/monitor.js?v=1:52:30)'};\n"
                  + m.group(1).replace("r && r.stack", "alone && alone.stack").replace("(r.stack)", "(alone.stack)")
                              .replace("const frames", "const frames2").replace("const where", "const where2")
                              .replace("frames.find", "frames2.find").replace("frames[0]", "frames2[0]")
                  + "\nconsole.log(where2);\n")
            out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=20)
            self.assertEqual(out.returncode, 0, out.stderr)
            caller, alone = out.stdout.strip().splitlines()
            self.assertIn("amazon-adsystem.com", caller, page)
            self.assertIn("monitor.js", alone, f"{page}: with no other frame, keep the wrapper's")


class ApiGate(unittest.TestCase):
    def test_the_developer_key_gate_lets_the_monitor_routes_through(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "api", "api_server.py")).read()
        gate = src[src.index("def gate():"):src.index("key = request.headers.get(\"X-API-Key\")")]
        self.assertIn('"/monitor"', gate)
        self.assertIn('"/owner/monitor"', gate)
        self.assertIn("fac_monitor.init_app(app)", src)
