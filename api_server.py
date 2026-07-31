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
import datetime, hashlib, hmac, json, os, re, secrets, threading, time, urllib.request, urllib.error, urllib.parse
from collections import defaultdict, deque
from flask import Flask, jsonify, request, g

import build_log             # which run-log lines are work that shipped
import nemo_metrics          # NEMO Seamless Gutter traffic, same droplet

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
       or request.path.startswith("/reports/") \
       or request.path.startswith("/embed/") \
       or request.path in ("/dashboard-metrics", "/dashboard-users",
                           "/dashboard-nemo"):   # own Supabase-token owner gate
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
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": ANON_KEY, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            u = json.loads(r.read())
    except urllib.error.HTTPError:
        return "unauth"        # 401/403 from Supabase = bad/expired token
    except Exception:
        return "error"
    email = (u.get("email") or "").strip().lower()
    verified = bool(u.get("email_confirmed_at")
                    or (u.get("user_metadata") or {}).get("email_verified"))
    if not verified:
        return "forbidden"
    if email == OWNER_EMAIL:
        return "ok"
    if email in NEMO_EMAILS:
        return "nemo"      # NEMO tab only — see NEMO_EMAILS
    return "forbidden"


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
    try:
        data = rpc("dashboard_metrics", {})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    # The engine's own build log. It lives on disk in the growth checkout, not
    # in Postgres, because the 05:40 build runs on this droplet and never writes
    # to the database. NEMO's tab has had this from the start; Find A Crib
    # reported traffic and revenue but never what was actually shipped for it.
    data["build"] = _fac_build()
    return jsonify(data)


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
    steps = []
    for slug in sorted(techs):
        t = techs[slug] or {}
        detail = (t.get("detail") or "").strip()
        if not detail:
            continue
        # ok is carried through rather than flattened to a tick: this engine
        # records failures (a technique can report ok:false and still have run),
        # and a card that shows every line green would hide them.
        step = {"slug": slug, "detail": detail, "ok": bool(t.get("ok")),
                "skipped": bool(t.get("skipped"))}
        # A technique with nothing to do is a healthy no-op, not a shipment.
        # The card reports what the engine built; "nothing new to submit" is
        # not something it built. Failures still come through.
        if build_log.did_work(step):
            steps.append({k: step[k] for k in ("slug", "detail", "ok")})
    m = run.get("measure") or {}
    return {
        "date": b.get("date") or m.get("date"),
        "at": b.get("at"),
        "steps": steps,
        "new_urls": b.get("new_urls"),
        "changed_urls": b.get("changed_urls"),
        "deployed": bool(b.get("deployed")),
    }


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
    try:
        return jsonify(nemo_metrics.build_cached())
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
