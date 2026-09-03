#!/usr/bin/env python3
"""
Find A Crib Developer API (v1).

Read-only REST API over the NYC rent-stabilized building dataset, HPD
violation/complaint summaries, and Section 8 / voucher data. Every request
needs an API key (X-API-Key header or ?api_key=); keys are authorized and
metered per day by tier via the api_authorize() Postgres function.

Data is loaded from the static JSON on disk (buildings.min.json, s8.json,
listings.json) into memory at startup — the same files the site serves — so
reads are fast and need no DB round-trip. The DB is used only for auth/metering.

Run:  DATA_DIR=/var/www/rent-map gunicorn -w 2 -b 127.0.0.1:8010 api_server:app
"""
import base64, concurrent.futures, datetime, glob, gzip, hashlib, hmac, json, os, re, secrets, threading, time, urllib.request, urllib.error, urllib.parse
from collections import defaultdict, deque
from flask import Flask, jsonify, request, g, redirect

import build_log             # which run-log lines are work that shipped
import crease_metrics
import nemo_metrics          # NEMO Seamless Gutter traffic, same droplet
import trent_metrics         # Trent's Fresh Spaces traffic, same droplet
import claude_usage          # Anthropic API spend, owner-only tab

DATA_DIR = os.environ.get("DATA_DIR", ".")
SUPABASE_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
STRIPE_SECRET = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WH_SECRET = os.environ.get("STRIPE_API_WEBHOOK_SECRET", "")
PRICES = {"pro": os.environ.get("STRIPE_PRICE_PRO", ""),
          "business": os.environ.get("STRIPE_PRICE_BUSINESS", "")}
# Owner-only analytics dashboard (findacrib.com/dashboard). The anon key is the
# public browser key (safe in source); it's only used server-side here to ask
# Supabase Auth "who is this access token?" — the real gate is the email check.
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRiYWlmb3R6d2x4anZzeGpvaGp0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEzNzI2MTQsImV4cCI6MjA5Njk0ODYxNH0.5hoLfoKkNnEnFuu7jsfCTq_rUQqn8gf32BEI9qiyCI4"
OWNER_EMAIL = "divinejdavis@gmail.com"
# Eric owns NEMO Seamless Gutter and gets the NEMO tab of this dashboard, but
# not Find A Crib's traffic, subscriptions or MRR — that is a different
# business. `_dashboard_auth()` returns a scope, and only the full owner scope
# reaches /dashboard-metrics and /dashboard-users.
#
# Both addresses are listed on purpose. `eric@` is only a Workspace ALIAS and
# cannot authenticate; his actual Google identity is `enemo@`, which is the
# email Google returns to Supabase on sign-in. Allowlisting `eric@` alone would
# reject the only account he can log in with.
NEMO_EMAILS = {"enemo@nemoseamlessgutter.com", "eric@nemoseamlessgutter.com"}
BORO = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens", "Bx": "bronx", "SI": "staten_island"}
BORO_REV = {v: k for k, v in BORO.items()}
MAX_LIMIT = 100
# Anti-scraping: the dataset is the product, so the free tier is deliberately
# shallow. Smaller page size + a hard pagination ceiling force free users to
# narrow with filters instead of walking the whole 47k-building set, and their
# coordinates are rounded (~110m) so a free clone isn't map-grade. Paid tiers
# get full precision and depth.
TIER_MAX_LIMIT = {"free": 25, "pro": 100, "business": 100}
FREE_MAX_RESULTS = 1000          # deepest offset a free key can page a list to
COORD_DECIMALS = {"free": 3}     # None/absent = full precision
DOCS = "https://findacrib.com/developers/"
# Ranges the dashboard picker may ask for. Kept here, not in the SQL, so an
# unknown value never reaches the database at all.
DASHBOARD_RANGES = {"all", "6m", "3m", "month", "today"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__)
# Cap request bodies: the only POST bodies we accept are a tiny email/tier JSON.
# Without this Flask reads an unbounded body, so a large POST to a portal
# endpoint is a cheap memory-exhaustion vector. 16 KB is generous for our shape.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024


def _tier():
    return (getattr(g, "verdict", None) or {}).get("tier", "free")

# ---- load data once at startup ---------------------------------------------
def _load(name, default):
    try:
        return json.load(open(os.path.join(DATA_DIR, name)))
    except Exception:
        return default

BUILDINGS = _load("buildings.min.json", [])
BY_BBL = {b["bbl"]: b for b in BUILDINGS}
_listings = _load("listings.json", {})
LISTED = set(str(k) for k in (_listings.get("counts") or {}).keys())
_s8 = _load("s8.json", {})
S8_BLDG = _s8.get("bldg") or {}
S8_AVAIL = {}
for k, v in (_s8.get("avail") or {}).items():
    S8_AVAIL[k] = json.loads(v) if isinstance(v, str) else v


def s8_for(bbl):
    out = {}
    if bbl in S8_BLDG:
        out["subsidized_building"] = True
        out["subsidized_units"] = S8_BLDG[bbl].get("u")
    if bbl in S8_AVAIL:
        a = S8_AVAIL[bbl]
        out["voucher_listing"] = {"listings": a.get("n"), "price": a.get("p"), "source_url": a.get("url")}
    return out or None


def public_building(b):
    dec = COORD_DECIMALS.get(_tier())            # free tier gets coarse coords
    lat, lng = b.get("lat"), b.get("lng")
    if dec is not None:
        lat = round(lat, dec) if isinstance(lat, (int, float)) else lat
        lng = round(lng, dec) if isinstance(lng, (int, float)) else lng
    h = b.get("h") or {}
    v = h.get("violations") or {}
    c = h.get("complaints") or {}
    hpd = None
    if h:
        hpd = {
            "open_violations": v.get("open"),
            "total_violations": v.get("total"),
            "open_complaints": c.get("open"),
            "last_registered": h.get("lastregistration"),
            "hpd_url": f"https://hpdonline.nyc.gov/hpdonline/building/{h['bid']}/overview" if h.get("bid") else None,
        }
    return {
        "bbl": b["bbl"],
        "address": b.get("a"),
        "borough": BORO.get(b.get("b")),
        "zip": b.get("z") or None,
        "neighborhood": b.get("nb"),
        "latitude": lat,
        "longitude": lng,
        "rent_stabilized": True,             # every building here is DHCR-registered stabilized
        "units": b.get("u"),
        "year_built": b.get("yr"),
        "stabilization_codes": b.get("s") or [],
        "recently_advertised": b["bbl"] in LISTED,
        "hpd": hpd,
        "section8": s8_for(b["bbl"]),
    }


# ---- auth / metering --------------------------------------------------------
def rpc(name, body):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/{name}",
        data=json.dumps(body).encode(),
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=8) as r:
        raw = r.read()
        return json.loads(raw) if raw else None   # void RPCs return an empty body (204)


def authorize(key):
    try:
        return rpc("api_authorize", {"p_key_hash": hashlib.sha256(key.encode()).hexdigest()})
    except Exception:
        return {"allowed": False, "reason": "auth_unavailable"}


def stripe_post(path, fields):
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/{path}",
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Authorization": f"Bearer {STRIPE_SECRET}",
                 "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


# ---- per-IP rate limiting for the unauthenticated developer portal ----------
# The metered /v1 endpoints are throttled per-key in the DB (api_authorize).
# The portal endpoints (signup/usage/upgrade) carry no API key, so without a
# guard anyone could script unlimited free-key minting (issue #20). Sliding
# window, in-process (per gunicorn worker) — coarse but enough to stop
# automation; the per-email cap in api_create_key is the DB-side backstop.
_RL_LOCK = threading.Lock()
_RL_HITS = defaultdict(deque)


def _client_ip():
    # nginx appends the real client to X-Forwarded-For, so the rightmost entry
    # is the hop nginx observed and cannot be spoofed by a client-sent header.
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.remote_addr or "unknown"


def rate_limited(bucket, max_hits, window_sec):
    """True if this IP has exceeded max_hits for `bucket` within window_sec."""
    now = time.time()
    key = f"{bucket}:{_client_ip()}"
    with _RL_LOCK:
        if len(_RL_HITS) > 5000:                      # bound memory under IP-rotation abuse
            stale = now - 3600
            for k in [k for k, d in _RL_HITS.items() if not d or d[-1] < stale]:
                _RL_HITS.pop(k, None)
        dq = _RL_HITS[key]
        cutoff = now - window_sec
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_hits:
            return True
        dq.append(now)
        return False


def _too_many():
    return jsonify(error="rate_limited",
                   message="Too many requests. Please slow down and try again later."), 429


PUBLIC_PATHS = {"/", "/v1", "/v1/", "/health"}


@app.before_request
def gate():
    # portal endpoints (signup/usage/upgrade/webhook) have their own auth;
    # the X-API-Key gate applies only to the metered /v1 data endpoints.
    if request.method == "OPTIONS" or request.path in PUBLIC_PATHS \
       or request.path.startswith("/developers/") \
       or request.path.startswith("/alerts/") \
       or request.path.startswith("/reports/") \
       or request.path.startswith("/embed/") \
       or request.path in ("/dashboard-metrics", "/dashboard-users",
                           "/dashboard-nemo",    # own Supabase-token owner gate
                           "/dashboard-crease",
                           "/dashboard-trent"):
        return
    # Header only — never accept the key in the query string, where it would be
    # captured in nginx access logs, browser history, and Referer headers.
    key = request.headers.get("X-API-Key")
    if not key:
        return jsonify(error="missing_api_key", docs=DOCS,
                       message="Send your key in the X-API-Key header. Get one at " + DOCS), 401
    verdict = authorize(key)
    if not verdict.get("allowed"):
        reason = verdict.get("reason", "unauthorized")
        if reason == "rate_limited":
            return jsonify(error="rate_limited", tier=verdict.get("tier"), daily_limit=verdict.get("limit"),
                           message="Daily request limit reached. Upgrade at " + DOCS), 429
        if reason == "auth_unavailable":
            return jsonify(error="temporarily_unavailable"), 503
        return jsonify(error="invalid_api_key", docs=DOCS), 401
    g.verdict = verdict


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"      # keyed JSON must never be cached
    # CORS only for the read-only data API (meant for cross-origin/browser
    # clients). The /developers/* portal is same-origin only: omitting the
    # header stops a victim's browser being scripted into minting keys or
    # starting a checkout from an attacker's page.
    p = request.path
    if p in PUBLIC_PATHS or p.startswith("/v1") or p.startswith("/embed/"):
        # /embed/* is CORS-open by design: the widget runs on other people's
        # sites. It is read-only, keyless and heavily capped (see embed_search).
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "X-API-Key, Content-Type"
    v = getattr(g, "verdict", None)
    if v:
        resp.headers["X-RateLimit-Limit"] = str(v.get("limit"))
        resp.headers["X-RateLimit-Remaining"] = str(v.get("remaining"))
    return resp


# ---- endpoints --------------------------------------------------------------
@app.route("/")
@app.route("/v1")
@app.route("/v1/")
def info():
    return jsonify(
        name="Find A Crib Developer API", version="v1", docs=DOCS,
        dataset={"rent_stabilized_buildings": len(BUILDINGS),
                 "section8_buildings": len(S8_BLDG),
                 "voucher_listings": len(S8_AVAIL)},
        endpoints=[
            "GET /v1/buildings/{bbl}",
            "GET /v1/buildings?borough=&zip=&neighborhood=&advertised=&section8=&page=&limit=",
            "GET /v1/section8?bbl=&zip=",
            "GET /v1/search?q=",
        ],
        auth="Send your key in the X-API-Key header.")


@app.route("/health")
def health():
    return jsonify(ok=True, buildings=len(BUILDINGS))


@app.route("/v1/buildings/<bbl>")
def building(bbl):
    b = BY_BBL.get(bbl)
    if not b:
        return jsonify(error="not_found", bbl=bbl), 404
    return jsonify(public_building(b))


@app.route("/v1/buildings")
def buildings():
    boro = request.args.get("borough", "").lower().strip()
    zip_ = request.args.get("zip", "").strip()
    nb = request.args.get("neighborhood", "").lower().strip()
    adv = request.args.get("advertised", "").lower() in ("1", "true", "yes")
    s8 = request.args.get("section8", "").lower() in ("1", "true", "yes")
    tier = _tier()
    max_limit = TIER_MAX_LIMIT.get(tier, TIER_MAX_LIMIT["free"])
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(max_limit, max(1, int(request.args.get("limit", 50))))
    except ValueError:
        return jsonify(error="bad_request", message="page and limit must be integers"), 400
    bcode = BORO_REV.get(boro) if boro else None
    if boro and not bcode:
        return jsonify(error="bad_request", message="borough must be one of " + ", ".join(BORO_REV)), 400

    res = []
    for b in BUILDINGS:
        if bcode and b.get("b") != bcode:
            continue
        if zip_ and str(b.get("z") or "") != zip_:
            continue
        if nb and nb not in (b.get("nb") or "").lower():
            continue
        if adv and b["bbl"] not in LISTED:
            continue
        if s8 and b["bbl"] not in S8_BLDG and b["bbl"] not in S8_AVAIL:
            continue
        res.append(b)

    total = len(res)
    start = (page - 1) * limit
    # Free tier can only reach the first FREE_MAX_RESULTS of any result set, so a
    # single broad query can't be walked to completion. Narrowing with filters
    # (borough/zip/neighborhood) or upgrading lifts the ceiling.
    if tier == "free" and start >= FREE_MAX_RESULTS:
        return jsonify(error="pagination_limit", docs=DOCS,
                       message="Free tier can page through the first %d results per query. "
                               "Add filters (borough, zip, neighborhood) to narrow, or upgrade for full depth."
                               % FREE_MAX_RESULTS), 402
    end = start + limit
    if tier == "free":
        end = min(end, FREE_MAX_RESULTS)
    window = res[start:end]
    return jsonify(
        total=total, page=page, limit=limit,
        results=[public_building(b) for b in window])


@app.route("/v1/section8")
def section8():
    bbl = request.args.get("bbl", "").strip()
    zip_ = request.args.get("zip", "").strip()
    if bbl:
        b = BY_BBL.get(bbl)
        return jsonify(bbl=bbl, section8=s8_for(bbl),
                       address=b.get("a") if b else None,
                       borough=BORO.get(b.get("b")) if b else None)
    if zip_:
        out = []
        for b in BUILDINGS:
            if str(b.get("z") or "") == zip_:
                info = s8_for(b["bbl"])
                if info:
                    out.append({"bbl": b["bbl"], "address": b.get("a"), "section8": info})
        return jsonify(zip=zip_, total=len(out), results=out)
    return jsonify(error="bad_request", message="provide bbl or zip"), 400


@app.route("/v1/search")
def search():
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify(error="bad_request", message="q must be at least 2 characters"), 400
    hits = []
    for b in BUILDINGS:
        hay = f"{b.get('a','')} {b.get('nb','')} {b.get('z','')}".lower()
        if q in hay:
            hits.append(b)
            if len(hits) >= 20:
                break
    return jsonify(query=q, total=len(hits),
                   results=[{"bbl": b["bbl"], "address": b.get("a"),
                             "borough": BORO.get(b.get("b")), "neighborhood": b.get("nb"),
                             "zip": b.get("z")} for b in hits])


@app.route("/embed/search")
def embed_search():
    """Keyless lookup for the embeddable widget (findacrib.com/embed/widget.js).

    The widget exists to be pasted into tenant-org, legal-aid and newsroom
    pages, so requiring an API key would kill it — those embedders will never
    sign up for one. A single shared key baked into the JS is worse: every
    embedder would draw down one 1,000/day quota and the widget would break for
    everyone once it got popular.

    The dataset is still the product, so this is deliberately useless for bulk
    extraction: it requires a query the caller already knows, caps results at
    three, has no pagination or offset, rounds coordinates out entirely, and is
    rate limited per IP. Extracting the corpus this way would mean enumerating
    addresses you would have to already possess.
    """
    if rate_limited("embed", 120, 3600):
        return _too_many()
    q = request.args.get("q", "").strip().lower()
    if len(q) < 3:
        return jsonify(error="bad_request",
                       message="q must be at least 3 characters"), 400
    hits = []
    for b in BUILDINGS:
        hay = f"{b.get('a','')} {b.get('nb','')} {b.get('z','')}".lower()
        if q in hay:
            hits.append(b)
            if len(hits) >= 3:
                break
    out = []
    for b in hits:
        h = b.get("h") or {}
        v = h.get("violations") or {}
        out.append({
            "bbl": b["bbl"],
            "address": b.get("a"),
            "borough": BORO.get(b.get("b")),
            "neighborhood": b.get("nb"),
            "zip": b.get("z") or None,
            "units": b.get("u"),
            "year_built": b.get("yr"),
            "rent_stabilized": True,
            "hpd": {"open_violations": v.get("open")} if v else None,
        })
    resp = jsonify(query=q, results=out,
                   note="Registration is at the building level and does not guarantee a "
                        "specific unit is stabilized.",
                   source="https://findacrib.com/")
    return resp


# ---- developer portal (signup / usage / upgrade / billing webhook) ----------
@app.route("/developers/signup", methods=["POST"])
def signup():
    if rate_limited("signup", 5, 3600):              # a few free keys per hour per IP
        return _too_many()
    email = (request.json or {}).get("email", "").strip().lower() if request.is_json \
            else request.form.get("email", "").strip().lower()
    if not EMAIL_RE.match(email):
        return jsonify(error="invalid_email"), 400
    plain = "fac_live_" + secrets.token_hex(20)
    key_hash = hashlib.sha256(plain.encode()).hexdigest()
    try:
        res = rpc("api_create_key", {"p_email": email, "p_key_hash": key_hash,
                                     "p_key_prefix": plain[:16] + "…"})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    if not res.get("ok"):
        if res.get("reason") == "has_paid_key":
            return jsonify(error="has_paid_key",
                           message="This email already has a paid key. Manage it in the dashboard."), 409
        if res.get("reason") == "free_key_limit":
            return jsonify(error="free_key_limit",
                           message="Too many free keys created for this email today. Try again tomorrow."), 429
        return jsonify(error="signup_failed"), 400
    return jsonify(ok=True, api_key=plain, tier="free", daily_limit=1000,
                   message="Save this key — it is shown only once.")


# ---- borough alerts --------------------------------------------------------
# Public sign-up at findacrib.com/alerts/: "email me the minute a new housing
# lottery or re-rental opens in <borough>". No account. The row lives in
# lottery_alert_subs (db/0021) and is only ever read by lottery_alerts.py on
# the droplet. Same-origin only — no CORS header is added for /alerts/*.
ALERT_BOROS = ("M", "Bk", "Q", "Bx", "SI")
ALERT_KINDS = ("lottery", "rerental")
TOKEN_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@app.route("/alerts/subscribe", methods=["POST"])
def alerts_subscribe():
    if rate_limited("alerts_sub", 6, 3600):           # a few sign-ups per hour per IP
        return _too_many()
    if not request.is_json:                            # blocks cross-site form posts
        return jsonify(error="json_required"), 415
    body = request.get_json(silent=True) or {}
    email = str(body.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify(error="invalid_email"), 400
    boros = sorted({b for b in (body.get("boroughs") or [])
                    if isinstance(b, str) and b in ALERT_BOROS})
    kinds = sorted({k for k in (body.get("kinds") or ALERT_KINDS)
                    if isinstance(k, str) and k in ALERT_KINDS}) or list(ALERT_KINDS)
    if not boros:
        return jsonify(error="no_borough"), 400

    # Optional filters. Blank = none. Anything unparseable is a 400, not a
    # silent "no filter" — someone who typed a rent cap expects it to hold.
    def _num(field, lo, hi, err):
        raw = body.get(field)
        if raw in (None, "", 0):
            return None, None
        try:
            v = int(float(str(raw).replace(",", "").replace("$", "").strip()))
        except (TypeError, ValueError):
            return None, err
        return (v, None) if lo <= v <= hi else (None, err)
    max_rent, e1 = _num("max_rent", 100, 20000, "bad_rent")
    income, e2 = _num("income", 1000, 2000000, "bad_income")
    if e1 or e2:
        return jsonify(error=e1 or e2), 400
    try:
        res = rpc("lottery_alerts_subscribe",
                  {"p_email": email, "p_boroughs": boros, "p_kinds": kinds,
                   "p_max_rent": max_rent, "p_income": income}) or {}
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    if not res.get("ok"):
        reason = res.get("reason", "signup_failed")
        return jsonify(error=reason), (429 if reason == "signup_cap" else 400)
    # Deliberately no "already subscribed" signal in the reply: that would be
    # an oracle for whether an address is on the list.
    return jsonify(ok=True, boroughs=res.get("boroughs"), kinds=res.get("kinds"),
                   max_rent=res.get("max_rent"), income=res.get("income"))


@app.route("/alerts/unsubscribe", methods=["GET", "POST"])
def alerts_unsubscribe():
    body = request.get_json(silent=True) or {}
    token = str(request.args.get("t") or body.get("token")
                or request.form.get("token") or "").strip().lower()
    if not TOKEN_RE.match(token):
        return jsonify(error="bad_token"), 400
    if request.method == "GET":
        # A link in an email gets followed by mail scanners and link previews.
        # A GET must never unsubscribe anyone — the page asks, then POSTs.
        # (Gmail/Apple one-click unsubscribe POSTs to this same URL.)
        return redirect(f"https://findacrib.com/alerts/#unsub={token}", code=302)
    if rate_limited("alerts_unsub", 30, 3600):
        return _too_many()
    try:
        ok = rpc("lottery_alerts_unsubscribe", {"p_token": token})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    return jsonify(ok=bool(ok))


@app.route("/developers/usage", methods=["GET", "POST"])
def usage():
    if rate_limited("usage", 60, 3600):
        return _too_many()
    # Read the key from the header (or a POST body) — never the query string,
    # which would leak it into access logs and history.
    key = request.headers.get("X-API-Key", "").strip()
    if not key and request.is_json:
        key = ((request.json or {}).get("key") or "").strip()
    if not key:
        return jsonify(error="missing_key"), 400
    try:
        s = rpc("api_key_status", {"p_key_hash": hashlib.sha256(key.encode()).hexdigest()})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    if not s.get("ok"):
        return jsonify(error="invalid_key"), 404
    return jsonify(tier=s["tier"], owner=s["owner"], prefix=s["prefix"], status=s["status"],
                   used_today=s["used_today"], daily_limit=s["limit"],
                   remaining=max(0, s["limit"] - s["used_today"]), paid=s["paid"])


@app.route("/developers/upgrade", methods=["POST"])
def upgrade():
    if rate_limited("upgrade", 15, 3600):
        return _too_many()
    body = request.json or {}
    key, tier = body.get("key", "").strip(), body.get("tier", "").strip()
    if tier not in ("pro", "business") or not PRICES.get(tier):
        return jsonify(error="bad_tier"), 400
    try:
        s = rpc("api_key_status", {"p_key_hash": hashlib.sha256(key.encode()).hexdigest()})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    if not s.get("ok"):
        return jsonify(error="invalid_key"), 404
    try:
        session = stripe_post("checkout/sessions", {
            "mode": "subscription",
            "line_items[0][price]": PRICES[tier],
            "line_items[0][quantity]": "1",
            "customer_email": s["owner"],
            "success_url": DOCS + "?upgraded=1",
            "cancel_url": DOCS + "?canceled=1",
            "metadata[api_key_id]": s["id"],
            "metadata[tier]": tier,
            "subscription_data[metadata][api_key_id]": s["id"],
            "subscription_data[metadata][tier]": tier,
        })
    except Exception:
        return jsonify(error="checkout_unavailable"), 502
    return jsonify(checkout_url=session.get("url"))


# ---- one-time paid Building Report -----------------------------------------
# Deliberately account-free. The whole premise is that people need this data
# exactly once, at the moment they are about to sign a lease, so requiring a
# signup before paying would lose most of them. The token in the URL is the
# only credential; building_reports carries no anon grant so the tokens cannot
# be enumerated through the Data API.

REPORT_PRICE = os.environ.get("STRIPE_PRICE_REPORT", "")
_REPORT_CACHE = {}


def _report_corpus():
    """Lazily build the benchmarking corpus; it needs the full 47k set."""
    if "corpus" not in _REPORT_CACHE:
        import building_report
        _REPORT_CACHE["corpus"] = building_report.Corpus(BUILDINGS)
        _REPORT_CACHE["contacts"] = building_report.load_contacts(
            os.path.join(DATA_DIR, "hpd_contacts.json"))
    return _REPORT_CACHE["corpus"], _REPORT_CACHE["contacts"]


def _rest_count(path):
    """Exact row count via Content-Range, without transferring the rows."""
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                 "Prefer": "count=exact", "Range": "0-0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        cr = r.headers.get("Content-Range") or ""
    return int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1].isdigit() else 0


def _rest(method, path, body=None, prefer=None):
    headers = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


@app.route("/reports/checkout", methods=["POST"])
def report_checkout():
    if rate_limited("report_checkout", 30, 3600):
        return _too_many()
    if not (STRIPE_SECRET and REPORT_PRICE):
        return jsonify(error="reports_unavailable"), 503
    bbl = str((request.json or {}).get("bbl") or "").strip()
    b = BY_BBL.get(bbl)
    if not b:
        return jsonify(error="unknown_building"), 404
    addr = " ".join(w.capitalize() if not w.isdigit() else w
                    for w in str(b.get("a") or "").split())
    try:
        session = stripe_post("checkout/sessions", {
            "mode": "payment",
            "line_items[0][price]": REPORT_PRICE,
            "line_items[0][quantity]": "1",
            "metadata[bbl]": bbl,
            "payment_intent_data[metadata][bbl]": bbl,
            # /report-ready deliberately avoids the /report/ prefix, which nginx
            # proxies to this app for token URLs.
            "success_url": "https://findacrib.com/report-ready/?s={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://findacrib.com/?report_canceled=1",
        })
    except Exception:
        return jsonify(error="checkout_unavailable"), 502
    try:
        _rest("POST", "building_reports",
              {"token": secrets.token_urlsafe(24), "bbl": bbl,
               "stripe_session_id": session.get("id"), "status": "pending"},
              prefer="return=minimal")
    except Exception:
        # The row is a convenience for the pending page; the webhook creates or
        # updates it authoritatively, so a failure here must not block payment.
        pass
    return jsonify(checkout_url=session.get("url"), address=addr)


@app.route("/reports/lookup")
def report_lookup():
    """Exchange a Stripe session id for the report token, once paid.

    The success page polls this: Stripe redirects the buyer back before the
    webhook has necessarily landed, and showing "your purchase failed" during a
    two-second race would be both wrong and alarming.
    """
    if rate_limited("report_lookup", 240, 3600):
        return _too_many()
    sid = (request.args.get("s") or "").strip()
    if not sid.startswith("cs_"):
        return jsonify(error="bad_session"), 400
    try:
        rows = _rest("GET", "building_reports?select=token,status&stripe_session_id=eq."
                     + urllib.parse.quote(sid, safe=""))
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    if not rows:
        return jsonify(status="unknown"), 404
    row = rows[0]
    if row.get("status") != "paid":
        return jsonify(status=row.get("status") or "pending")
    return jsonify(status="paid", url=f"https://findacrib.com/report/{row['token']}")


@app.route("/reports/unsubscribe", methods=["GET", "POST"])
def report_unsubscribe():
    """Stop the buyer follow-up sequence.

    Accepts GET (the link in the footer) and POST (Gmail/Outlook one-click via
    the List-Unsubscribe-Post header). Uses unsub_token, never the report
    token: the report token is access to something they paid for, and
    unsubscribe links get fetched by mail scanners.

    Always answers 200 with the same page, even for an unknown token. Telling a
    caller which tokens are real would turn this into an enumeration oracle
    over buyer records, and there is nothing useful to say differently.
    """
    if rate_limited("report_unsub", 120, 3600):
        return _too_many()
    t = (request.args.get("t") or (request.form.get("t") if request.form else "") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{16,80}", t or ""):
        try:
            _rest("PATCH", "building_reports?unsub_token=eq." + urllib.parse.quote(t, safe=""),
                  {"unsubscribed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                  prefer="return=minimal")
        except Exception:
            pass
    html = ("<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta name=robots content='noindex,nofollow'>"
            "<title>Unsubscribed — Find A Crib</title>"
            "<style>body{font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
            "max-width:520px;margin:12vh auto;padding:0 22px;color:#111}"
            "h1{font-size:21px}p{color:#5a5f6a}a{color:#1a56db}</style>"
            "<h1>You're unsubscribed</h1>"
            "<p>We won't send you any more follow-ups about your building report. "
            "The report itself stays available at the link we emailed you — that link "
            "still works and does not expire.</p>"
            "<p>This does not affect saved-building alerts if you have a Find A Crib "
            "account; those are managed from your account.</p>"
            "<p><a href='https://findacrib.com/'>Back to the map →</a></p>")
    return app.response_class(html, mimetype="text/html")


@app.route("/reports/<token>")
def report_view(token):
    if rate_limited("report_view", 300, 3600):
        return _too_many()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token or ""):
        return "Not found", 404
    try:
        rows = _rest("GET", "building_reports?select=token,bbl,status,view_count&token=eq."
                     + urllib.parse.quote(token, safe=""))
    except Exception:
        return "Temporarily unavailable", 503
    if not rows or rows[0].get("status") != "paid":
        return "Not found", 404
    row = rows[0]
    try:
        import building_report
        corpus, contacts = _report_corpus()
        html = building_report.render(
            row["bbl"], corpus, contacts,
            s8=bool(S8_BLDG.get(row["bbl"])),
            listed=bool(LISTED and row["bbl"] in LISTED))
    except KeyError:
        return "Not found", 404
    except Exception:
        return "Report temporarily unavailable", 503
    try:
        _rest("PATCH", "building_reports?token=eq." + urllib.parse.quote(token, safe=""),
              {"view_count": (row.get("view_count") or 0) + 1,
               "last_viewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
              prefer="return=minimal")
    except Exception:
        pass
    return app.response_class(html, mimetype="text/html")


def _fulfil_report(session, bbl):
    """Mark a paid report and email the buyer their link.

    Idempotent on stripe_session_id: Stripe retries webhooks, and a retry must
    not mint a second token for a purchase already fulfilled.
    """
    sid = session.get("id")
    email = ((session.get("customer_details") or {}).get("email")
             or session.get("customer_email") or "").strip()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    token = None
    try:
        rows = _rest("GET", "building_reports?select=token,status&stripe_session_id=eq."
                     + urllib.parse.quote(sid, safe=""))
    except Exception:
        rows = None
    if rows:
        if rows[0].get("status") == "paid":
            return rows[0]["token"]          # already fulfilled; do nothing
        token = rows[0]["token"]
        _rest("PATCH", "building_reports?stripe_session_id=eq." + urllib.parse.quote(sid, safe=""),
              {"status": "paid", "paid_at": now, "email": email or None,
               "unsub_token": secrets.token_urlsafe(18)},
              prefer="return=minimal")
    else:
        token = secrets.token_urlsafe(24)
        _rest("POST", "building_reports",
              {"token": token, "bbl": str(bbl), "email": email or None,
               "stripe_session_id": sid, "status": "paid", "paid_at": now,
               "unsub_token": secrets.token_urlsafe(18)},
              prefer="return=minimal")
    if email and token:
        try:
            _email_report(email, str(bbl), token)
        except Exception:
            pass                              # the link still works; mail is a convenience
    return token


def _email_report(to, bbl, token):
    """Deliver the paid report. Shares the house style with every other email
    we send (growth/emailkit.py) — this is the first thing a buyer sees after
    paying, so it should not be the one that looks like a mail-merge."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from growth import emailkit

    if not emailkit.smtp_configured():
        return
    b = BY_BBL.get(str(bbl)) or {}
    addr = " ".join(w.capitalize() if not w.isdigit() else w
                    for w in str(b.get("a") or "your building").split())
    url = f"https://findacrib.com/report/{token}"
    html, text = emailkit.render(
        title=f"Your building report — {addr}",
        intro="Thanks for the purchase. Your report is ready, and the link below doesn't "
              "expire — keep this email if you want to come back to it.",
        blocks=[
            {"type": "steps", "items": [
                "How this building's violation record compares with every other "
                "rent-stabilized building in the city.",
                "Who is registered as the owner and managing agent, and what else "
                "they run.",
                "A pre-filled DHCR rent-history request — the free step that "
                "establishes whether you're being overcharged.",
            ]},
        ],
        cta=("Open your report", url),
        footer_note="This is a one-time purchase receipt and delivery. "
                    "Questions? Just reply to this email.")
    emailkit.send(to, f"Your building report — {addr}", html, text)


@app.route("/developers/stripe-webhook", methods=["POST"])
def stripe_webhook():
    # Fail closed: with no configured signing secret we cannot authenticate the
    # payload, and an empty key would let anyone forge a valid signature. Reject
    # as a misconfiguration rather than proceed.
    if not STRIPE_WH_SECRET:
        return "webhook secret not configured", 500
    body = request.get_data(as_text=True)
    sig = request.headers.get("Stripe-Signature", "")
    parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
    t, v1 = parts.get("t"), parts.get("v1")
    if not (t and v1):
        return "bad signature", 400
    try:
        ts = int(t)
    except (TypeError, ValueError):
        return "bad signature", 400
    if abs(time.time() - ts) > 300:
        return "bad signature", 400
    mac = hmac.new(STRIPE_WH_SECRET.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, v1):
        return "bad signature", 400
    event = json.loads(body)
    obj = event.get("data", {}).get("object", {})
    typ = event.get("type", "")
    try:
        if typ == "checkout.session.completed":
            meta = obj.get("metadata") or {}
            kid = meta.get("api_key_id")
            if kid:
                rpc("api_set_tier", {"p_key_id": kid, "p_tier": meta.get("tier", "pro"),
                                     "p_customer": obj.get("customer"), "p_sub": obj.get("subscription")})
            elif meta.get("bbl"):
                _fulfil_report(obj, meta["bbl"])
        elif typ == "customer.subscription.deleted":
            rpc("api_downgrade_by_sub", {"p_sub": obj.get("id")})
    except Exception:
        return "error", 500
    return "", 200


# ---- owner-only analytics dashboard -----------------------------------------
# Verdicts are cached per token for a minute. Every dashboard click paid a
# round trip to Supabase Auth before its own data query could start, on a page
# whose sidebar and site switcher fire several requests in a row. Caching only
# the answer for a token we already checked doesn't loosen the gate: the token
# is a signed JWT that stays valid until it expires regardless of what we do
# here, so a minute of memory cannot admit anyone the live check would refuse.
_AUTH_CACHE = {}
_AUTH_CACHE_LOCK = threading.Lock()
_AUTH_CACHE_TTL = 60


# A short memo for the helpers that /dashboard-metrics bolts onto the RPC.
# Profiled 2026-09-03 on the droplet, all-time window: the RPC itself is
# 0.56 s, _fac_adtiles 1.02 s (20 concurrent REST pages of ad-tile events,
# aggregated here), _fac_channels 0.15 s, _fac_signage 0.11 s,
# _fac_consult_clicks 0.09 s — so the endpoint's 1.9 s was two-thirds
# helpers. Each is keyed on its `since` boundary, which is a fixed timestamp
# for a given range on a given day, so the same window inside the TTL is a
# dict lookup. Per gunicorn worker, so the first hit on each worker still
# pays; that is the cost of not adding a shared store for a one-reader page.
# 120 s is well under the page's own 5-minute refresh, so nothing on screen
# can be older than it already could be.
_MEMO = {}
_MEMO_LOCK = threading.Lock()


def _memo(ttl):
    def wrap(fn):
        def inner(*args):
            key = (fn.__name__,) + tuple(str(a) for a in args)
            now = time.time()
            with _MEMO_LOCK:
                hit = _MEMO.get(key)
                if hit and hit[0] > now:
                    return hit[1]
            val = fn(*args)
            with _MEMO_LOCK:
                if len(_MEMO) > 64:
                    _MEMO.clear()
                _MEMO[key] = (now + ttl, val)
            return val
        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        return inner
    return wrap


def _dashboard_auth():
    """Classify the caller by their Supabase access token.

    Returns 'ok' only for the verified owner email; 'forbidden' for any other
    signed-in user, 'unauth' for a missing/invalid token, 'error' if Supabase
    Auth can't be reached. The token is verified server-side against Supabase
    (GET /auth/v1/user) — we never trust claims decoded on the client.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return "unauth"
    token = auth[7:].strip()
    if not token:
        return "unauth"
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _AUTH_CACHE_LOCK:
        hit = _AUTH_CACHE.get(key)
        if hit and now < hit[0]:
            return hit[1]
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": ANON_KEY, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            u = json.loads(r.read())
    except urllib.error.HTTPError:
        return _auth_cached(key, "unauth", token)   # 401/403 = bad/expired token
    except Exception:
        return "error"     # never cached: a Supabase blip is not a verdict
    email = (u.get("email") or "").strip().lower()
    verified = bool(u.get("email_confirmed_at")
                    or (u.get("user_metadata") or {}).get("email_verified"))
    if not verified:
        return _auth_cached(key, "forbidden", token)
    if email == OWNER_EMAIL:
        return _auth_cached(key, "ok", token)
    if email in NEMO_EMAILS:
        return _auth_cached(key, "nemo", token)   # NEMO tab only, see NEMO_EMAILS
    return _auth_cached(key, "forbidden", token)


def _jwt_exp(token):
    """The `exp` claim, or None. Read, not trusted.

    Supabase already told us whether the token is good; this only shortens how
    long that answer is reused, so a forged claim can shorten its own cache
    entry and nothing else.
    """
    try:
        body = token.split(".")[1]
        body += "=" * (-len(body) % 4)
        exp = json.loads(base64.urlsafe_b64decode(body)).get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


def _auth_cached(key, verdict, token):
    """Remember `verdict` for this token and return it.

    The entry never outlives the token: an access token that expires in 10s is
    cached for 10s, so a minute of memory can't keep answering 'ok' for a token
    Supabase would now reject.
    """
    until = time.time() + _AUTH_CACHE_TTL
    exp = _jwt_exp(token)
    if exp:
        until = min(until, exp)
    with _AUTH_CACHE_LOCK:
        if len(_AUTH_CACHE) > 64:          # a handful of people, not a crowd
            _AUTH_CACHE.clear()
        _AUTH_CACHE[key] = (until, verdict)
    return verdict


def _dashboard_denial(verdict, allowed):
    """Response to send when `verdict` is not in `allowed`, else None.

    Every dashboard route funnels through this so adding a scope can never
    silently widen one of them: a route lists the scopes it accepts, and
    anything else is a 403 whether it is an unknown caller or a signed-in
    user whose scope simply does not cover this feed.
    """
    if verdict == "error":
        return jsonify(error="temporarily_unavailable"), 503
    if verdict == "unauth":
        return jsonify(error="sign_in_required"), 401
    if verdict not in allowed:
        return jsonify(error="forbidden", message="This dashboard is private."), 403
    return None


@app.route("/dashboard-metrics")
def dashboard_metrics():
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    # The range picker. Allowlisted rather than passed through: this value
    # reaches a SECURITY DEFINER function, and an allowlist is the difference
    # between a filter and an injection surface. Anything unrecognised falls
    # back to 'all' instead of erroring — a bad querystring should not blank
    # the owner's dashboard.
    rng = (request.args.get("range") or "all").lower()
    if rng not in DASHBOARD_RANGES:
        rng = "all"
    try:
        data = rpc("dashboard_metrics", {"p_range": rng})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    # The engine's own build log. It lives on disk in the growth checkout, not
    # in Postgres, because the 05:40 build runs on this droplet and never writes
    # to the database. NEMO's tab has had this from the start; Find A Crib
    # reported traffic and revenue but never what was actually shipped for it.
    data["build"] = _fac_build()
    data["search"] = _fac_search()
    data["channels"] = _fac_channels(data.get("since"))
    data["adtiles"] = _fac_adtiles(data.get("since"))
    # Inputs for the goals card's audience-INDEPENDENT streams. Deliberately
    # not range-scoped: that card is pinned to all-time for the same reason.
    data["goalstreams"] = {"ai": _fac_ai_crawls(),
                           "consult_clicks": _fac_consult_clicks(),
                           "agents": _fac_agent_pool()}
    data["signage"] = _fac_signage(data.get("since"))
    return jsonify(data)


# Channels worth naming on the card, in the order they are shown. The key is
# the ?src= value the nginx short link redirects to (/tt -> /?src=tiktok).
FAC_CHANNELS = [("tiktok", "TikTok"), ("instagram", "Instagram"),
                ("youtube", "YouTube"), ("reddit", "Reddit"),
                # Printed counter QR pieces: nginx serves /c as a 302 to
                # ?src=qr-counter, so a scan is counted exactly like a tagged
                # social link and needs nothing on the object but a short path.
                ("qr-counter", "Counter QR")]


@_memo(120)
def _fac_channels(since):
    """Visitors who arrived through a tagged channel link.

    A referrer cannot answer "did TikTok send anyone": a comment saying "use
    findacrib.com" gets typed into the reader's own browser, so document.referrer
    is empty and the visit is indistinguishable from a bookmark. Of the visits
    banked before this shipped, 2,023 of 2,825 carried no referrer at all and not
    one carried a TikTok one. What survives is the entry path — nginx serves /tt,
    /ig, /yt and /rd as 302s to /?src=<channel> and the tracking snippet already
    records location.search — so this counts tags, not referrers.

    `since` is the boundary the SQL function computed for this range, passed back
    in rather than re-derived here: two independent readings of "this month" that
    disagree by a timezone would put a card on the page that contradicts the
    cards beside it. None means all time.

    Returns {} on any failure — a dashboard that loses one card should drop it,
    not 500 the page.
    """
    q = ("visits?select=path,visitor_id,created_at&path=like.*src%3D*"
         "&order=created_at.desc&limit=20000")
    if since:
        q += f"&created_at=gte.{urllib.parse.quote(str(since))}"
    try:
        rows = _rest("GET", q) or []
    except Exception:
        return {}
    seen, visits = {}, {}
    for r in rows:
        m = re.search(r"[?&]src=([\w-]+)", r.get("path") or "")
        if not m:
            continue
        c = m.group(1).lower()
        visits[c] = visits.get(c, 0) + 1
        seen.setdefault(c, set()).add(r.get("visitor_id"))
    known = {k for k, _ in FAC_CHANNELS}
    out = [{"key": k, "label": lbl, "visitors": len(seen.get(k, ())),
            "visits": visits.get(k, 0)}
           for k, lbl in FAC_CHANNELS]
    # Anything tagged by hand that is not in the list still counts, rather than
    # vanishing into a total that does not add up.
    for c in sorted(set(visits) - known):
        out.append({"key": c, "label": c.title(),
                    "visitors": len(seen.get(c, ())), "visits": visits[c]})
    return {"rows": out,
            "visitors": sum(len(v) for v in seen.values()),
            "visits": sum(visits.values()),
            "tagged": True}


# The owner's own browsing is not inventory. His signed-in user_id is fixed;
# his anonymous visitor_ids are learned the same way traffic_report.py learns
# them — any visitor_id ever seen alongside that user_id. Without this his own
# testing IS the ad-tile card, the way it was the whole Crease demand tile.
FAC_OWNER_UID = "af2629f7-1121-4bee-8a2b-cede9318c864"


def _fac_owner_visitors():
    """visitor_ids belonging to the owner, from both logs. () on failure."""
    ids = set()
    for tbl in ("events", "visits"):
        try:
            rows = _rest("GET", f"{tbl}?select=visitor_id"
                                f"&user_id=eq.{FAC_OWNER_UID}&limit=10000") or []
        except Exception:
            continue
        ids.update(r.get("visitor_id") for r in rows if r.get("visitor_id"))
    return ids


# The three tile events, and which advertiser each one belongs to.
AD_TILE_EVENTS = ("tile_impression", "tile_served", "featured_click", "hc_click")

# How many impressions a slot has to bank before its click rate is published.
# Under a hundred, the confidence interval on the rate is wider than the rate,
# and the card would be quoting noise at a buyer.
AD_CTR_MIN = 100

# A served-impression window also has to be OLD enough, not just big enough.
# `tile_served` shipped mid-afternoon and banked 214 impressions within hours,
# clearing AD_CTR_MIN — but almost every click on record predates it, so the
# rate published as "0.0%, below average" on a slot that had just produced 65
# clicks. Impressions accumulate in minutes and clicks do not; a rate divided
# over a window hours old is noise wearing a verdict. One full day is the floor.
AD_WINDOW_MIN_HOURS = 24


@_memo(120)
def _fac_adtiles(since):
    """Advertiser-tile inventory: what the re-rental and lottery tiles earned.

    This is the card a marketing agent gets shown when asked to pay for the
    slot, so the numbers have to survive being read by the buyer. Two rules
    it does not bend:

    * Impressions are the browser's viewability count (half the tile, one
      second, once per apartment per session), not renders. The grid rebuilds
      on every pan, so renders would be an order of magnitude larger and
      indefensible.
    * Reach is distinct visitors, and it is reported next to impressions
      rather than instead of them. "1,200 impressions" from forty people is a
      different product than from four hundred, and only one of those two
      numbers says which.

    Impression tracking shipped 2026-08-24; clicks go back to 2026-08-02.
    `first_impression` is returned so the card can say so instead of showing a
    CTR built on a denominator that did not exist yet — and the CTR itself is
    computed only over the window where BOTH sides were measured: clicks from
    before the first impression are reported, but never divided by it. A rate
    is withheld entirely until the window has banked AD_CTR_MIN impressions,
    because below that the margin of error is wider than the number.

    Returns {} on any failure — one card should drop, not the page.
    """
    # 50,000 is a CEILING, not a promise. tile_served banked ~1,500 on its first
    # full day, so this window reaches the cap in about a month — and because the
    # order is created_at.desc, hitting it silently drops the OLDEST rows, which
    # is exactly where every click older than impression-counting lives. The
    # all-time card would quietly lose its own history. Detect and report it
    # rather than let the numbers shrink without saying why.
    # PAGINATE. `limit=50000` is a lie PostgREST tells politely: it caps a
    # response at 1,000 rows whatever you ask for, and the guard below used to
    # test len(rows) >= 50000, which could never fire. The moment tile_served
    # began firing ~1,500 times a day, the newest 1,000 ad-tile events were
    # almost entirely today's renders and every click fell off the end — this
    # card reported 0 clicks against a real 72, with `truncated` reading False.
    #
    # FETCH THE PAGES CONCURRENTLY. Walking them one at a time was the second
    # of the two things making /dashboard-metrics slow (the first was the
    # nginx log scan in _fac_ai_crawls): all-time is 19,530 ad-tile events, so
    # 20 sequential round-trips at ~83ms each, ~1.7s of the endpoint's ~2.5s.
    # One count query says how many pages there are up front, then a small
    # pool fetches them at once. Same number of requests to PostgREST, same
    # rows, three waves instead of twenty.
    #
    # Offset paging over a table still being written can shift a row between
    # pages either way; fetching them together narrows that window rather than
    # widening it, because every page is read at nearly the same instant
    # instead of over a second and a half.
    PAGE = 1000
    MAX_PAGES = 200          # 200k events; a real ceiling, and it is reported
    base = ("events?select=event,props,visitor_id,created_at"
            f"&event=in.({','.join(AD_TILE_EVENTS)})"
            "&order=created_at.desc")
    if since:
        base += f"&created_at=gte.{urllib.parse.quote(str(since))}"
    rows, truncated = [], False
    try:
        total = _rest_count(base)
        pages = min(-(-total // PAGE), MAX_PAGES) if total else 1
        truncated = total > MAX_PAGES * PAGE
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for batch in pool.map(
                    lambda i: _rest("GET", f"{base}&offset={i * PAGE}&limit={PAGE}") or [],
                    range(pages)):
                rows += batch
    except Exception:
        # The count is one more thing that can fail. Fall back to the sequential
        # walk rather than dropping the card: slow beats absent.
        rows, truncated = [], False
        try:
            for p_ in range(MAX_PAGES):
                batch = _rest("GET", f"{base}&offset={p_ * PAGE}&limit={PAGE}") or []
                rows += batch
                if len(batch) < PAGE:
                    break
            else:
                truncated = True
        except Exception:
            return {}
    mine = _fac_owner_visitors()
    rows = [r for r in rows if r.get("visitor_id") not in mine]

    # The first impression has to be known before anything is bucketed: it is
    # the left edge of the only window in which a click rate means anything.
    first_impr = min((r["created_at"] for r in rows
                      if r.get("event") == "tile_impression" and r.get("created_at")),
                     default=None)
    # Served impressions started being counted later than viewable ones, so they
    # get their own left edge. Sharing first_impr would divide clicks banked
    # before `tile_served` existed by a denominator that did not exist yet —
    # the exact mistake the viewable window was built to avoid.
    first_served = min((r["created_at"] for r in rows
                        if r.get("event") == "tile_served" and r.get("created_at")),
                       default=None)

    # agent -> {kind, impressions, clicks, clicks_measured, reach set, addrs set}
    by_agent, kinds = {}, {}
    for r in rows:
        props = r.get("props") or {}
        ev = r.get("event")
        if ev in ("tile_impression", "tile_served"):
            kind = props.get("kind") or "rerental"
            agent = props.get("agent") or "—"
        elif ev == "hc_click":
            kind, agent = "lottery", "NYC Housing Connect"
        else:                                     # featured_click
            kind, agent = "rerental", props.get("agent") or "—"
        a = by_agent.setdefault(agent, {"agent": agent, "kind": kind,
                                        "impressions": 0, "served": 0, "clicks": 0,
                                        "clicks_measured": 0, "clicks_served": 0,
                                        "_reach": set(), "_units": set()})
        k = kinds.setdefault(kind, {"kind": kind, "impressions": 0, "served": 0,
                                    "clicks": 0, "clicks_measured": 0,
                                    "clicks_served": 0, "_reach": set()})
        field = ("impressions" if ev == "tile_impression"
                 else "served" if ev == "tile_served" else "clicks")
        a[field] += 1
        k[field] += 1
        if field == "clicks":
            when = r.get("created_at") or ""
            if first_impr and when >= first_impr:
                a["clicks_measured"] += 1
                k["clicks_measured"] += 1
            if first_served and when >= first_served:
                a["clicks_served"] += 1
                k["clicks_served"] += 1
        if r.get("visitor_id"):
            a["_reach"].add(r["visitor_id"])
            k["_reach"].add(r["visitor_id"])
        if props.get("addr"):
            a["_units"].add(props["addr"])

    # Age of the served window, in hours. Timestamps are ISO from PostgREST.
    served_window_ready = False
    if first_served:
        try:
            t0 = datetime.datetime.fromisoformat(first_served.replace("Z", "+00:00"))
            age_h = (datetime.datetime.now(datetime.timezone.utc) - t0).total_seconds() / 3600
            served_window_ready = age_h >= AD_WINDOW_MIN_HOURS
        except Exception:
            served_window_ready = False

    def finish(d, extra=()):
        out = {kk: vv for kk, vv in d.items() if not kk.startswith("_")}
        out["reach"] = len(d["_reach"])
        for e in extra:
            out[e] = len(d["_" + e])
        # CTR is left null rather than 0 when nothing was measured — a "0.0%"
        # click rate on zero impressions reads as a tile nobody clicks — and
        # null again while the sample is too small to survive being quoted.
        # Numerator is only the clicks inside the measured window; dividing
        # every click since August by two impressions counted this morning is
        # how a card ends up claiming a 1,450% click rate.
        out["ctr"] = (100.0 * d["clicks_measured"] / d["impressions"]) \
            if d["impressions"] >= AD_CTR_MIN else None
        # The industry rate: clicks over SERVED impressions, which is what every
        # published display/native CTR benchmark divides by. Same minimum sample
        # and same measured-window rule as the viewable rate above.
        out["ctr_served"] = (100.0 * d["clicks_served"] / d["served"]) \
            if (d["served"] >= AD_CTR_MIN and served_window_ready) else None
        return out

    agents = sorted((finish(v, ("units",)) for v in by_agent.values()),
                    key=lambda x: (-x["impressions"], -x["clicks"], x["agent"]))
    return {
        "agents": agents,
        "kinds": [finish(kinds[k]) for k in ("rerental", "lottery") if k in kinds],
        "impressions": sum(a["impressions"] for a in agents),
        "served": sum(a["served"] for a in agents),
        "clicks": sum(a["clicks"] for a in agents),
        "clicks_measured": sum(a["clicks_measured"] for a in agents),
        "clicks_served": sum(a["clicks_served"] for a in agents),
        "ctr": (100.0 * sum(a["clicks_measured"] for a in agents)
                / sum(a["impressions"] for a in agents))
               if sum(a["impressions"] for a in agents) >= AD_CTR_MIN else None,
        "ctr_served": (100.0 * sum(a["clicks_served"] for a in agents)
                       / sum(a["served"] for a in agents))
                      if (sum(a["served"] for a in agents) >= AD_CTR_MIN
                          and served_window_ready) else None,
        "served_window_ready": served_window_ready,
        "ctr_min": AD_CTR_MIN,
        "first_served": first_served,
        # True when the query came back full: the numbers are then a recent
        # slice, not the window asked for, and the card must say so.
        "truncated": truncated,
        "reach": len(set().union(*[v["_reach"] for v in by_agent.values()]) if by_agent else set()),
        "advertisers": len([a for a in agents if a["agent"] != "NYC Housing Connect"]),
        "first_impression": first_impr,
    }


# Consultancies our visitors already hand themselves to. A click here is a
# person who has decided their stabilization question is worth paying somebody
# about — which is a different, more valuable event than a listing hand-off.
CONSULT_DOMAINS = ("mgnyconsulting.com", "afny.org", "clintonmanagement.com",
                   "taxsolute.com", "resideny.com", "kgupright.com")
# The user agents that identify themselves as AI crawlers. Matched
# case-insensitively against the UA field of this site's own nginx log.
AI_CRAWLERS = ("GPTBot", "ChatGPT-User", "PerplexityBot", "CCBot", "ClaudeBot",
               "anthropic-ai", "CloudVertexBot", "Bytespider", "Amazonbot",
               "meta-externalagent", "Applebot-Extended", "cohere-ai")
FAC_ACCESS_LOG = os.environ.get("FAC_ACCESS_LOG", "/var/log/nginx/findacrib.access.log")
# Shared with the OTHER gunicorn worker, and across restarts. The in-process
# dict this replaced hid how expensive the scan is: with -w 2 each worker paid
# the full cost once an hour, so a dashboard load had roughly even odds of
# landing on a cold worker and waiting for it.
FAC_AI_CACHE = os.environ.get(
    "FAC_AI_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 ".cache", "ai_crawls.json"))
_AI_TTL = 3600
_AI_REFRESHING = threading.Lock()


def _fac_agent_pool():
    """How many HPD marketing agents there ARE — the ceiling on slot sales.

    An advertiser slot is not sold per click; it is sold to a named agent for a
    month. So the size of this business is bounded by how many such agents
    exist, and in NYC that is a small, countable number rather than a market.
    85 on the HPD list, 22 of them currently running a re-rental page.

    This is the number that turns "advertiser revenue scales with traffic" into
    "advertiser revenue scales with traffic until it runs out of advertisers".
    """
    out = {"total": 0, "swept": 0, "sellable": 0}
    try:
        with open(os.path.join(DATA_DIR, "marketing_agents.json")) as f:
            d = json.load(f)
        out["total"] = int(d.get("count") or 0)          # exist on the HPD list
        out["swept"] = int(d.get("rerental_count") or 0)  # have a page we sweep
    except Exception:
        pass
    try:
        # The number that actually bounds slot revenue: agents whose listings
        # are in the grid RIGHT NOW. You cannot sell a tile to an agent whose
        # apartments you do not carry — there would be nothing to put in it.
        # Housing Connect is excluded here as elsewhere; it is a city lottery.
        with open(os.path.join(DATA_DIR, "featured.json")) as f:
            lst = (json.load(f) or {}).get("listings") or []
        names = {(x.get("agent") or "").strip() for x in lst}
        names.discard("")
        names = {x for x in names if "housing connect" not in x.lower()}
        out["sellable"] = len(names)
    except Exception:
        pass
    return out


def _ai_crawl_scan():
    """Count AI-crawler requests in today's log plus yesterday's rotation.

    ~17MB and a couple of seconds. Never called on a request thread.
    """
    pat = re.compile("|".join(AI_CRAWLERS), re.I)
    total, days = 0, 0
    for path in (FAC_ACCESS_LOG + ".1", FAC_ACCESS_LOG):
        try:
            with open(path, "r", errors="replace") as f:
                total += sum(1 for line in f if pat.search(line))
        except Exception:
            continue
        days += 1
    if not days:
        return {"per_day": 0, "window_days": 0, "ok": False}
    # Today's log is partial, so a straight sum over two files understates the
    # daily rate. Yesterday's rotation alone is the honest full day.
    return {"per_day": int(round(total / days)), "window_days": days, "ok": True}


def _ai_cache_read():
    try:
        with open(FAC_AI_CACHE) as f:
            doc = json.load(f)
        if isinstance(doc.get("val"), dict):
            return float(doc.get("at") or 0), doc["val"]
    except Exception:
        pass
    return 0.0, None


def _ai_cache_refresh():
    """Rescan and rewrite the cache. Runs on a background thread."""
    try:
        val = _ai_crawl_scan()
        os.makedirs(os.path.dirname(FAC_AI_CACHE), exist_ok=True)
        tmp = FAC_AI_CACHE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"at": time.time(), "val": val}, f)
        os.replace(tmp, FAC_AI_CACHE)
    except Exception:
        pass
    finally:
        try:
            _AI_REFRESHING.release()
        except RuntimeError:
            pass


def _fac_ai_crawls():
    """AI-crawler requests per day, measured off this site's own nginx log.

    Not from the analytics beacon: crawlers do not run JavaScript, so every
    number on the rest of this dashboard is blind to them by construction. They
    are also the largest single consumer of this site — roughly 8,000 requests a
    day against ~150 human page views — and the only revenue stream here whose
    volume is a property of the CORPUS rather than of the audience.

    THIS NEVER BLOCKS. Scanning 17MB of nginx log takes ~2s, and it was the
    whole reason /dashboard-metrics ran at a 2.1s median and a 4.9s worst case:
    every other part of that endpoint together is under half a second. An
    in-process hourly cache did not fix it, because gunicorn runs two workers
    and each one paid the scan separately, so a page load was a coin flip on
    whether it hit a warm one.

    So the request path only ever reads a file. A stale value is served as-is
    and a refresh is kicked off behind it; the number is a rolling daily rate
    off a log that is still being written, so "an hour old" is not a different
    answer, it is the same answer measured a moment earlier. Only the very
    first call after a deploy has nothing to return, and it returns ok:false
    rather than waiting — the card reads that as "not measured yet", which for
    about two seconds is exactly true.
    """
    at, val = _ai_cache_read()
    if val is None or time.time() - at >= _AI_TTL:
        # non-blocking: whichever worker gets the lock does the scan, the other
        # serves what it has. Released in _ai_cache_refresh's finally.
        if _AI_REFRESHING.acquire(blocking=False):
            threading.Thread(target=_ai_cache_refresh, daemon=True).start()
    if val is None:
        return {"per_day": 0, "window_days": 0, "ok": False}
    return val


def _ai_cache_prewarm():
    """Fill the cache at startup so the first dashboard load after a deploy
    does not read ok:false. Both workers may do this; os.replace makes the
    write atomic, so the only cost is one duplicated background scan per
    restart, off every request path."""
    at, val = _ai_cache_read()
    if val is not None and time.time() - at < _AI_TTL:
        return
    if _AI_REFRESHING.acquire(blocking=False):
        threading.Thread(target=_ai_cache_refresh, daemon=True).start()


_ai_cache_prewarm()


@_memo(120)
def _fac_consult_clicks():
    """All-time outbound clicks to rent-stabilization consultancies."""
    # Counted in Postgres, not in Python. PostgREST caps a response at 1,000
    # rows whatever `limit` says, so pulling outbound events and filtering here
    # silently sampled an arbitrary thousand of 2,400 and reported 1 hit. The
    # destination lives in props->>href.
    ors = ",".join(f"props->>href.ilike.*{d}*" for d in CONSULT_DOMAINS)
    q = "events?select=id&event=eq.outbound&or=(" + urllib.parse.quote(ors, safe="*,.>-") + ")"
    try:
        rng = _rest_count(q)
    except Exception:
        return 0
    return rng


FAC_LAST_RUN = os.environ.get(
    "FAC_LAST_RUN", "/root/Find-A-Crib/growth/last_run.json")


def _fac_build():
    """What the Find A Crib growth engine shipped on its last run.

    Returns {} when the file is missing or unreadable — a dashboard that loses
    its build log should drop the card, not 500 the whole page.
    """
    try:
        with open(FAC_LAST_RUN) as f:
            run = json.load(f)
    except Exception:
        return {}
    b = run.get("build") or {}
    techs = b.get("techniques") or {}
    steps, held = [], []
    for slug in sorted(techs):
        t = techs[slug] or {}
        detail = (t.get("detail") or "").strip()
        if not detail:
            continue
        # ok is carried through rather than flattened to a tick: this engine
        # records failures (a technique can report ok:false and still have run),
        # and a card that shows every line green would hide them.
        step = {"slug": slug, "detail": detail, "ok": bool(t.get("ok")),
                "skipped": bool(t.get("skipped")),
                "unchanged": bool(t.get("unchanged"))}
        # A technique with nothing to do is a healthy no-op, not a shipment.
        # The card reports what the engine built; "nothing new to submit" is
        # not something it built. Failures still come through.
        if build_log.did_work(step):
            steps.append({k: step[k] for k in ("slug", "detail", "ok")})
        elif step["unchanged"]:
            # Dropped, but counted. The suppressed lines are the verifiers
            # re-confirming yesterday's state; if the card simply went quiet the
            # owner would read a healthy morning as a dead engine, which is the
            # failure mode the run log exists to prevent. `since` is the date
            # the sentence last moved, so a line standing still for a fortnight
            # can be told from one that settled overnight.
            held.append({"slug": slug, "since": t.get("same_since")})
    m = run.get("measure") or {}
    sinces = sorted(h["since"] for h in held if h.get("since"))
    return {
        "date": b.get("date") or m.get("date"),
        "at": b.get("at"),
        "steps": steps,
        "unchanged": len(held),
        "unchanged_since": sinces[0] if sinces else None,
        "new_urls": b.get("new_urls"),
        "changed_urls": b.get("changed_urls"),
        "deployed": bool(b.get("deployed")),
    }


FAC_GSC_PAGES = os.environ.get(
    "FAC_GSC_PAGES", "/root/Find-A-Crib/growth/gsc_pages.json")
FAC_INDEX_STATUS = os.environ.get(
    "FAC_INDEX_STATUS", "/root/Find-A-Crib/growth/index_status.json")


# ---------------------------------------------------------------------------
# Counter signage: which question on a printed plate earns the scan
# ---------------------------------------------------------------------------
# nginx writes one line per QR redirect into its own log rather than leaving
# them in the site log. Two reasons, and the second is the one that matters:
# the file stays small enough to read on the request path, and it counts the
# people who pointed a camera at a plate and then closed the tab before any
# JavaScript ran. Those never reach `visits`, and they are exactly the
# difference between "the sign got read" and "the site was worth staying on" —
# the two things this card has to tell apart.
FAC_QR_LOG = os.environ.get("FAC_QR_LOG", "/var/log/nginx/findacrib-qr.log")

# The questions a plate can ask. The key is the FIRST CHARACTER of the plate
# code, so /c/a3 is the third plate asking question A and the arm falls out of
# the tag with no registry to keep in sync — putting a new plate on a counter
# changes nothing in this file, only inventing a new QUESTION does.
#
# The venue lists are the point of the split. Both questions are true and both
# are answered by this site; they differ in who is standing at the counter.
# Question A talks to somebody who already has a landlord, which at a bodega
# counter is everyone. Question B talks to somebody mid-move, which is a few
# percent of any given room and close to all of a self-storage lobby. So the
# copy is not really an A/B test of words — it is a test of whether a room is
# full of residents or full of movers, and the words follow the room.
SIGNAGE_ARMS = [
    {
        "key": "a",
        "headline": "Is your building rent-stabilized?",
        "code": "findacrib.com/c/a<n>",
        "audience": "People who already live here",
        "why": ("Everyone standing at a counter has a landlord; roughly one "
                "renter household in ten moves in a year, so on any given day "
                "almost nobody in the room is mid-search. This question also "
                "has money behind it — a stabilized unit means a capped "
                "increase, a renewal right, and sometimes an overcharge "
                "refund — which is what makes somebody pull a phone out for a "
                "sign on a counter. It is answerable for 47,198 buildings."),
        "venues": [
            {"code": "a1", "place": "Laundromats",
             "why": "30–60 minutes of forced dwell, and a building with in-unit laundry never sends anyone here — the room is renters by construction"},
            {"code": "a2", "place": "Bodegas, delis and corner stores",
             "why": "Daily repeat trade from a three-block radius; the same plate is seen twenty times, which is how a counter sign actually works"},
            {"code": "a3", "place": "Barbershops, hair and nail salons",
             "why": "Long waits, neighbourhood regulars, and a room where people already talk about their landlords"},
            {"code": "a4", "place": "Check cashing, money transfer and tax preparers",
             "why": "Renter-heavy, and the customer is already in a paperwork-about-money frame when they read it"},
            {"code": "a5", "place": "Pharmacy pickup counters",
             "why": "A ten-minute wait facing a counter, in a chain that serves the same blocks every day"},
            {"code": "a6", "place": "Repair counters — phone, shoe, tailoring, dry cleaning",
             "why": "The transaction is drop-off then pickup, so the plate gets two viewings per customer"},
            {"code": "a7", "place": "Public library branches and community centres",
             "why": "Free counter space, a civic question, and staff who will say yes without being sold to"},
            {"code": "a8", "place": "Tenant associations, mutual-aid tables, senior centres",
             "why": "The highest-intent room there is, and the one most likely to pass the link on rather than just scan it"},
            {"code": "a9", "place": "Immigrant-serving groceries, halal butchers, bakeries",
             "why": "Stabilized status is most often unknown, and most often worth money, exactly where tenants are least likely to have been told"},
        ],
    },
    {
        "key": "b",
        "headline": "Find rent-stabilized apartments",
        "code": "findacrib.com/c/b<n>",
        "audience": "People who are moving right now",
        "why": ("A promise instead of a question, and it only beats A where "
                "the room is already mid-move — then the share of people it "
                "speaks to goes from a few percent to most of the counter. "
                "It is backed by live listings rather than the whole "
                "stabilized set, so it is a thinner promise: put it where the "
                "thinness does not matter because the person is searching "
                "anyway."),
        "venues": [
            {"place": "Self-storage front desks",
             "why": "Nobody rents a unit except side-on to a move; the lobby is the purest mid-move room in the city"},
            {"place": "Truck rental and moving supply counters",
             "why": "Boxes and a van are bought days before a lease starts — and often while the next place is still undecided"},
            {"place": "Mailbox rental, packing and shipping stores",
             "why": "A change-of-address counter is a move in progress, stated out loud"},
            {"place": "Furniture and mattress shops",
             "why": "Bought for a specific new room, usually in the two weeks either side of the move"},
            {"place": "Hardware stores — key cutting, paint, curtain rails",
             "why": "The errand list of somebody who just got keys, or is about to"},
            {"place": "Coffee and copy shops next to a campus, August–September",
             "why": "A dense, seasonal, apartment-hunting population that turns over completely every year"},
            {"place": "Coworking desks and job centres",
             "why": "A new job in a new borough is the most common reason a search starts at all"},
            {"place": "Any counter that already has an apartment-flyer board",
             "why": "The room has told you what it is for. Put the plate beside the board, not on the other wall"},
        ],
    },
]

# Under this many scans a rate is not printed. A count carries roughly +/- 2*sqrt(N),
# so 25 scans against 40 is an overlapping pair of intervals and not a result;
# calling one question the winner off numbers that small is the single easiest
# way to engrave the wrong plate.
QR_RATE_FLOOR = 30
QR_CALL_FLOOR = 100

# The whole scan history is read on every dashboard load, so it is capped.
# A file this size is a fault — a redirect loop, a crawler, someone hammering
# the short link — not a counter that got busy, and the cap keeps that fault
# from turning into a slow dashboard rather than pretending to measure it.
QR_LOG_MAX_LINES = 200000
# PostgREST answers with at most one page whatever the limit says, so a tagged
# feed that reaches the page size has been truncated and the counts under it
# are floors. Detected rather than assumed absent: the same silent truncation
# on a $limit that looked generous has cost this project a day before.
QR_PAGE_SIZE = 1000

_QR_TAG = re.compile(r"[?&]src=qr-([a-z0-9]{1,8})")
# One line of findacrib-qr.log: $time_iso8601 $status $request_uri "$http_user_agent"
_QR_LINE = re.compile(r'^(\S+) (\d{3}) (\S+) "([^"]*)"')
# A link preview fetcher and a command-line client are not somebody holding a
# phone up to a plate. curl is named because it is what the short link gets
# tested with, and a test must never look like a scan.
_QR_BOT = re.compile(r"bot|crawl|spider|slurp|headless|preview|curl|wget|"
                     r"python|okhttp|libwww|scan|monitor", re.I)


def _qr_plate(path):
    """The plate code out of a tagged path, or None."""
    m = _QR_TAG.search(path or "")
    return m.group(1) if m else None


def _qr_arm(plate):
    """Which question a plate code asks.

    The engraved plate that predates the codes tags itself `qr-counter` and
    asks question A. It keeps its own name rather than being renamed `a0`,
    because the code is cut into the plastic and cannot be changed; the mapping
    lives here instead.
    """
    if not plate:
        return None
    if plate == "counter":
        return "a"
    return plate[0] if plate[0].isalpha() else None


FAC_PLACEMENTS = os.environ.get(
    "FAC_PLACEMENTS", "/root/Find-A-Crib/growth/placements.json")


def _fac_placements():
    """Which plate is on which counter, and since when.

    Returns (rows, live_from). `live_from` maps a plate code to the earliest
    date any copy of it went out — the moment its scans stop being the owner
    checking a proof and start being somebody at a counter.

    Missing file gives ({}, {}) and the card then counts NOTHING and says so.
    That is the deliberate direction to fail in: the alternative is counting
    every test scan as a customer, which on this project has a track record.
    """
    try:
        with open(FAC_PLACEMENTS) as f:
            rows = (json.load(f) or {}).get("placements") or []
    except Exception:
        return [], {}
    live_from = {}
    for r in rows:
        c, d = r.get("code"), r.get("placed")
        if c and d and (c not in live_from or d < live_from[c]):
            live_from[c] = d
    return rows, live_from


def _qr_scans(since, live_from=None):
    """Redirects through /c and /c/<code>, by plate, from nginx's own log.

    Returns (counted, pre, unlogged, log_present). An unreadable or absent log
    gives empties and log_present False: "no scan log" and "no scans" are
    different findings, and the card says which one it is.

    Three buckets, and nothing is ever silently dropped:

      counted   the plate is on a counter and this scan came after it got
                there. The only bucket that is a customer.
      pre       scanned before that plate was placed. Testing, by definition —
                a plate on a desk has no customers. Reported, not deleted, so
                a number the owner remembers seeing does not just vanish.
      unlogged  scanned on a plate with no placement record at all. NOT
                counted, and surfaced loudly: it means either a test, or a
                plate that went out and never got written down. Both need the
                owner, and silently choosing either one for him is wrong.
    """
    paths = [FAC_QR_LOG] + sorted(glob.glob(FAC_QR_LOG + ".*"))
    out, pre, unlogged, seen_file, lines = {}, {}, {}, False, 0
    for p in paths:
        if lines > QR_LOG_MAX_LINES:
            break
        try:
            f = gzip.open(p, "rt", errors="replace") if p.endswith(".gz") \
                else open(p, "r", errors="replace")
        except Exception:
            continue
        seen_file = True
        try:
            with f:
                for line in f:
                    lines += 1
                    if lines > QR_LOG_MAX_LINES:
                        break
                    m = _QR_LINE.match(line)
                    if not m:
                        continue
                    ts, _status, uri, ua = m.groups()
                    if _QR_BOT.search(ua):
                        continue
                    if since and _iso(ts) and _iso(ts) < _iso(str(since)):
                        continue
                    # /c -> the original engraved plate; /c/<code> -> a numbered one
                    u = uri.split("?")[0]
                    code = "counter" if u.rstrip("/") == "/c" else u.rsplit("/", 1)[-1]
                    if not re.fullmatch(r"[a-z0-9]{1,8}", code or ""):
                        continue
                    if live_from is not None:
                        lf = live_from.get(code)
                        if not lf:
                            unlogged[code] = unlogged.get(code, 0) + 1
                            continue
                        # Date-only compare: the log stamp is a full ISO
                        # timestamp and the placement is a day, so slicing to
                        # 10 chars is what makes "placed today" mean all of
                        # today rather than midnight onwards.
                        if ts[:10] < lf[:10]:
                            pre[code] = pre.get(code, 0) + 1
                            continue
                    out[code] = out.get(code, 0) + 1
        except Exception:
            continue
    return out, pre, unlogged, seen_file


def _iso(s):
    """A comparable UTC datetime out of an ISO-ish string, or None.

    The two sides being compared come from different places — nginx writes
    $time_iso8601, Postgres hands back whatever the range function computed —
    so they are parsed rather than string-compared. A timestamp that will not
    parse counts the row IN: losing a scan is worse than counting one twice on
    a card whose whole problem is small numbers.
    """
    if not s:
        return None
    t = str(s).strip().replace(" ", "T")
    t = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", "", t)[:19]
    try:
        return datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        try:
            return datetime.datetime.strptime(t[:10], "%Y-%m-%d")
        except Exception:
            return None


# Events that mean the scan went somewhere. A tile impression is not on the
# list: it fires because the page rendered, not because anybody did anything,
# so counting it would make every bounce look like an engaged visit.
QR_ENGAGED = ("search", "building_view", "save", "outbound",
              "report_checkout_start", "violations_open", "signin")


@_memo(120)
def _fac_signage(since):
    """The counter-plate card: scans, sessions and engagement per question.

    Three numbers per arm and they come from two different systems on purpose:

      scans     nginx redirects. Counts the camera, including the people who
                never waited for the page. This is what the HEADLINE earns.
      sessions  distinct visitor_id carrying the tag. Counts arrival.
      engaged   distinct visitor_id who then searched, opened a building or
                saved one. This is what the SITE earns.

    The verdict is engaged/scans, not scans, because a question that pulls
    scans out of people with no interest in the answer is worse than one that
    pulls fewer. Nothing is called until an arm banks QR_CALL_FLOOR scans.

    Returns {} on failure — a dashboard that loses one card should drop it.
    """
    arms = {}
    for a in SIGNAGE_ARMS:
        arms[a["key"]] = dict(a, scans=0, sessions=0, engaged=0,
                              rate=None, plates={})

    placements, live_from = _fac_placements()
    scans, pre_scans, unlogged, log_present = _qr_scans(since, live_from)
    for code, cnt in scans.items():
        k = _qr_arm(code)
        if k not in arms:
            continue
        arms[k]["scans"] += cnt
        arms[k]["plates"].setdefault(code, {"code": code, "scans": 0,
                                            "sessions": 0, "engaged": 0})
        arms[k]["plates"][code]["scans"] += cnt

    # `qr-` rather than `src=` as the LIKE needle: an `=` inside a PostgREST
    # filter value is a parse hazard and the tag is the only place "qr-" ever
    # appears in a path.
    sess, eng, truncated = {}, {}, False
    try:
        q = "visits?select=path,visitor_id&path=like.*qr-*&limit=20000"
        if since:
            q += f"&created_at=gte.{urllib.parse.quote(str(since))}"
        rows = _rest("GET", q) or []
        truncated = truncated or len(rows) >= QR_PAGE_SIZE
        for r in rows:
            code = _qr_plate(r.get("path"))
            if code:
                sess.setdefault(code, set()).add(r.get("visitor_id"))
        q = "events?select=path,visitor_id,event&path=like.*qr-*&limit=20000"
        if since:
            q += f"&created_at=gte.{urllib.parse.quote(str(since))}"
        rows = _rest("GET", q) or []
        truncated = truncated or len(rows) >= QR_PAGE_SIZE
        for r in rows:
            code = _qr_plate(r.get("path"))
            if not code:
                continue
            # An event is also proof of arrival, and it is the more reliable
            # proof: `visits` is one insert at the end of a long async boot and
            # a small share of sessions never land one, while an event fires
            # off whatever the visitor actually did.
            sess.setdefault(code, set()).add(r.get("visitor_id"))
            if r.get("event") in QR_ENGAGED:
                eng.setdefault(code, set()).add(r.get("visitor_id"))
    except Exception:
        pass

    for code in set(sess) | set(eng):
        k = _qr_arm(code)
        if k not in arms:
            continue
        p = arms[k]["plates"].setdefault(code, {"code": code, "scans": 0,
                                                "sessions": 0, "engaged": 0})
        p["sessions"] = len(sess.get(code, ()))
        p["engaged"] = len(eng.get(code, ()))
        arms[k]["sessions"] += p["sessions"]
        arms[k]["engaged"] += p["engaged"]

    # A plate row that says only "a4" is a code the reader has to go and look
    # up, which in practice means the per-plate numbers get skipped. The venue
    # each code was cut for is declared right here in SIGNAGE_ARMS, so the row
    # can carry it. Plates with no venue assigned (the pre-code `counter`
    # plate, or a code cut later) keep their bare code rather than borrowing
    # somebody else's label.
    venue_of = {v["code"]: v["place"]
                for a in SIGNAGE_ARMS for v in a.get("venues", []) if v.get("code")}

    out = []
    for a in SIGNAGE_ARMS:
        arm = arms[a["key"]]
        for pl in arm["plates"].values():
            pl["venue"] = venue_of.get(pl["code"])
            pl["stores"] = [r for r in placements
                            if r.get("code") == pl["code"] and not r.get("removed")]
            pl["since"] = live_from.get(pl["code"])
        if arm["scans"] >= QR_RATE_FLOOR:
            arm["rate"] = round(100.0 * arm["engaged"] / arm["scans"], 1)
        arm["plates"] = sorted(arm["plates"].values(),
                               key=lambda p: (-p["scans"], p["code"]))
        out.append(arm)

    # The call, in one sentence, so the card cannot be read as a scoreboard
    # before it is one.
    ready = [a for a in out if a["scans"] >= QR_CALL_FLOOR]
    if len(ready) < 2:
        short = min((a["scans"] for a in out), default=0)
        verdict = ("Not callable yet. Each question needs about "
                   f"{QR_CALL_FLOOR} scans before the two can be told apart — "
                   f"the thinner arm has {short}. A count carries roughly "
                   "±2√N, so 25 scans against 40 is the same number twice.")
    else:
        best = max(out, key=lambda a: (a["rate"] or 0))
        other = [a for a in out if a is not best][0]
        gap = (best["rate"] or 0) - (other["rate"] or 0)
        verdict = (f"“{best['headline']}” is converting {best['rate']}% of "
                   f"scans against {other['rate']}%. " +
                   ("That gap is inside the noise on these counts — keep both "
                    "running." if gap < 5 else
                    "Both arms have cleared the floor, so this is a real "
                    "difference, not a coin flip."))

    # Every live placement, not only the ones attached to a plate that has
    # already been scanned: a campaign that starts next week has four rows and
    # zero scans, and the kiosk card has to draw the rows before the scans.
    live_rows = [r for r in placements if not r.get("removed")]
    return {"arms": out, "log": log_present, "verdict": verdict,
            "truncated": truncated,
            "placements": live_rows,
            "placed": len(live_rows),
            "rooms": len({r["code"] for r in placements if not r.get("removed")}),
            "excluded_pre": sum(pre_scans.values()),
            "unlogged": sorted(({"code": c, "scans": n} for c, n in unlogged.items()),
                               key=lambda r: -r["scans"]),
            "rate_floor": QR_RATE_FLOOR, "call_floor": QR_CALL_FLOOR}

def _fac_search():
    """Search Console and indexing, for the Find A Crib tab.

    NEMO's tab has had a rankings card since July and this one never did, even
    though findacrib.com has been a verified property the whole time — the
    numbers were being collected every morning and read by nobody.

    Read from the growth checkout's own artifacts rather than from Google.
    This runs on the request path, and the rule this endpoint learned the hard
    way three separate times is that nothing on the request path may touch the
    network: an ElevenLabs fetch and a reverse-DNS lookup each turned a
    dashboard load into a ten-second stall. The 05:40 build already writes both
    of these files; serving yesterday's honest numbers beats blocking on
    today's.

    Returns {} when the files are missing, so a dashboard that loses its
    growth checkout drops the card instead of 500-ing the page.
    """
    out = {}
    try:
        with open(FAC_GSC_PAGES) as f:
            g = json.load(f)
    except Exception:
        g = {}
    pages = g.get("pages") or []
    if pages:
        # Impressions are summed across serving pages rather than taken from
        # the tracked-query total. The two differ by an order of magnitude
        # here, because most of what Google shows this site is a building page
        # answering a query nobody thought to track.
        clicks = sum(int(p.get("clicks") or 0) for p in pages)
        impressions = sum(int(p.get("impressions") or 0) for p in pages)
        ranked = [p for p in pages if p.get("position") is not None]
        avg_pos = (sum(float(p["position"]) for p in ranked) / len(ranked)) if ranked else None
        out.update({
            "clicks": clicks,
            "impressions": impressions,
            "ctr": (clicks / impressions) if impressions else None,
            "avg_position": avg_pos,
            "serving_pages": len(pages),
            "serving_ever": (g.get("churn") or {}).get("gsc_serving_ever"),
            "date": g.get("date"),
            "untracked": (g.get("discovered_untracked") or [])[:8],
        })
    try:
        with open(FAC_INDEX_STATUS) as f:
            ix = json.load(f)
    except Exception:
        ix = {}
    total = ((ix.get("summary") or {}).get("total") or {})
    if total:
        buckets = total.get("buckets") or {}
        cohort = sum(int(v or 0) for v in buckets.values())
        # The growth engine's search-share goal (90% of tracked queries ranking
        # top 10), so the dashboard's GOALS block can carry it. Read from the
        # engine's own ledger rather than recomputed here.
        try:
            with open(FAC_LAST_RUN) as f:
                sc = (json.load(f).get("searchconsole") or {})
            out["share_pct"] = sc.get("share_pct")
            out["tracked_ranking"] = sc.get("tracked_ranking")
            kw_path = os.path.join(os.path.dirname(FAC_LAST_RUN), "keywords.json")
            with open(kw_path) as f:
                kws = json.load(f)
            out["tracked_queries"] = len(kws) if isinstance(kws, list) else len(kws.get("keywords", []))
        except Exception:
            pass
        out["index"] = {
            "published": ix.get("published_urls"),
            "cohort": cohort,
            "indexed": buckets.get("indexed"),
            "unknown_to_google": buckets.get("unknown_to_google"),
            "crawled_not_indexed": buckets.get("crawled_not_indexed"),
            "discovered_not_indexed": buckets.get("discovered_not_indexed"),
            "accept_pct": total.get("accept_pct"),
            "accept_pct_mature": total.get("accept_pct_mature"),
            "updated": ix.get("updated"),
        }
    return out


@app.route("/dashboard-nemo")
def dashboard_nemo():
    """NEMO Seamless Gutter traffic — the dashboard's second site tab.

    Same owner gate as the Find A Crib metrics: NEMO has no analytics database
    and no dashboard of its own, and both sites sit on this droplet, so the
    numbers are read from NEMO's growth ledger and nginx log here rather than
    duplicating the whole dashboard app under the other domain.
    """
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    # Eric's NEMO scope reaches this feed and nothing else.
    denied = _dashboard_denial(_dashboard_auth(), ("ok", "nemo"))
    if denied:
        return denied
    rng = (request.args.get("range") or "all").lower()
    if rng not in DASHBOARD_RANGES:
        rng = "all"
    try:
        return jsonify(nemo_metrics.build_cached(rng=rng))
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503


@app.route("/dashboard-crease")
def dashboard_crease():
    """Crease traffic and demand — the dashboard's third site tab.

    Same owner gate as the Find A Crib metrics, and deliberately not Eric's
    scope: this is a different business of the same owner's, not a client's
    site. Traffic comes from this box's own nginx log; everything about orders
    and demand is read over loopback from the Crease dispatcher, which owns
    that schema. Counts only — no customer rows cross this endpoint.
    """
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    rng = (request.args.get("range") or "all").lower()
    if rng not in DASHBOARD_RANGES:
        rng = "all"
    try:
        return jsonify(crease_metrics.build_cached(rng=rng))
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503


@app.route("/dashboard-trent")
def dashboard_trent():
    """Trent's Fresh Spaces — the dashboard's fourth site tab.

    Owner-only, like Crease and unlike NEMO: Trent has no login here, and the
    payload mixes his booking counts with market-size figures that are the
    owner's working notes rather than a client report. Everything comes off
    this box — the site's own nginx log, the Node app's SQLite, and Search
    Console via the estate service account. Counts only: no customer row, name
    or phone crosses this endpoint.
    """
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    rng = (request.args.get("range") or "all").lower()
    if rng not in DASHBOARD_RANGES:
        rng = "all"
    try:
        return jsonify(trent_metrics.build_cached(rng=rng))
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503


@app.route("/dashboard-claude")
def dashboard_claude():
    """Anthropic API spend — owner only.

    Owner scope and nothing else: this is the bill, and it is the one payload
    here that describes the operator rather than any site's visitors. Eric's
    NEMO scope must never reach it.

    Degrades rather than fails. With no ANTHROPIC_ADMIN_KEY set the module
    returns ok=False with a reason, which the tab renders as a setup card — a
    500 here would look like the dashboard is broken when the only thing
    missing is a key that has to be created by hand in the Console.
    """
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    try:
        return jsonify(claude_usage.build_cached())
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503


@app.route("/dashboard-users")
def dashboard_users():
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    try:
        data = rpc("dashboard_users", {})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    return jsonify(users=data or [])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8010)
