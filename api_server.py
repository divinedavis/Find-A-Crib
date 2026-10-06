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
import base64, datetime, glob, gzip, hashlib, hmac, json, os, re, secrets, threading, time, urllib.request, urllib.error, urllib.parse
import zoneinfo

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, g, redirect

import build_log             # which run-log lines are work that shipped
import crease_metrics
import nemo_metrics          # NEMO Seamless Gutter traffic, same droplet
import trent_metrics         # Trent's Fresh Spaces traffic, same droplet
import marracat_metrics      # Marracat, fetched from its own droplet
import claude_usage          # Anthropic API spend, owner-only tab
import ai_gateway            # Plus check + $20/month cap for every AI call
import nl_search             # plain-language search -> map filters
import rent_check            # "is this rent fair?" — statistics, no model
import building_records      # one building's public records, for the Claude features
import claude_features       # landlord report card (Haiku) + Ask about this building (Sonnet)
import listing_page          # a re-rental's own page as text, for Help me apply
import creator_outreach      # owner's creator-review tracker, /dashboard/creators/
import business_checklist    # owner's business & legal setup checklist, /dashboard/business/

DATA_DIR = os.environ.get("DATA_DIR", ".")
SUPABASE_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
STRIPE_SECRET = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WH_SECRET = os.environ.get("STRIPE_API_WEBHOOK_SECRET", "")
PRICES = {"pro": os.environ.get("STRIPE_PRICE_PRO", ""),
          "business": os.environ.get("STRIPE_PRICE_BUSINESS", "")}
# Owner-only analytics dashboard (divinedavis.com/dashboard/, proxied here). The anon key is the
# public browser key (safe in source); it's only used server-side here to ask
# Supabase Auth "who is this access token?" — the real gate is the email check.
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRiYWlmb3R6d2x4anZzeGpvaGp0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEzNzI2MTQsImV4cCI6MjA5Njk0ODYxNH0.5hoLfoKkNnEnFuu7jsfCTq_rUQqn8gf32BEI9qiyCI4"
OWNER_EMAIL = "divinejdavis@gmail.com"
# Eric owns NEMO Seamless Gutter and gets the NEMO tab of this dashboard, but
# not Find A Crib's traffic, subscriptions or MRR — that is a different
# business. `_dashboard_auth()` returns a scope, and only the full owner scope
# reaches /dashboard-metrics and /dashboard-users.
#
# Gated by Supabase auth.users UUID, NOT email. Sign-up is auto-confirmed
# (mailer_autoconfirm=true, no email verification), so an email allowlist lets
# anyone register an unclaimed address and walk in — which is exactly what the
# old NEMO_EMAILS set allowed: neither enemo@ nor eric@nemoseamlessgutter.com
# had an account (security audit 2026-09-25).
#
# To grant Eric the NEMO tab: have him sign in once (Google, as
# enemo@nemoseamlessgutter.com — eric@ is only a Workspace alias and cannot
# authenticate), confirm the row is really his (provider = google in
# auth.identities), then add its id here and redeploy with deploy_api.sh:
#   select u.id, u.email, i.provider from auth.users u
#     join auth.identities i on i.user_id = u.id
#    where u.email = 'enemo@nemoseamlessgutter.com';
NEMO_USER_IDS = frozenset()   # lowercase UUID strings
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
FMR = _load("fmr.json", {})
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
    with urllib.request.urlopen(req, timeout=15) as r:
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
       or request.path.startswith("/push/") \
       or request.path.startswith("/ai/") \
       or request.path == "/geo" \
       or request.path.startswith("/reports/") \
       or request.path.startswith("/embed/") \
       or request.path.startswith("/dashboard-creators") \
       or request.path == "/dashboard-business" \
       or request.path == "/creators-ingest" \
       or request.path in ("/dashboard-metrics", "/dashboard-users", "/dashboard-visitors",
                           "/dashboard-claude",  # added 2026-09-06: it was answering missing_api_key (401) on every dashboard load
                           "/dashboard-nemo",    # own Supabase-token owner gate
                           "/dashboard-crease",
                           "/dashboard-trent",
                           "/dashboard-marracat",
                           "/dashboard-marracat-users"):
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
ALERT_KINDS = ("lottery", "rerental", "voucher")
TOKEN_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@app.route("/alerts/subscribe", methods=["POST"])
def alerts_subscribe():
    if rate_limited("alerts_sub", 6, 3600):           # a few sign-ups per hour per IP
        return _too_many()
    if not request.is_json:                            # blocks cross-site form posts
        return jsonify(error="json_required"), 415
    body = request.get_json(silent=True) or {}
    # Alerts need an account (2026-09-08): the address is the verified
    # session's, never the one in the body — so nobody can subscribe someone
    # else, and the sign-up modal on the map is a real gate, not a curtain.
    email = _session_email()
    if not email:
        return jsonify(error="sign_in_required"), 401
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
        # Household size (2026-10-03, db/0047): optional, 1-12; lets the
        # sender check a re-rental's flyer income limits for the right row.
        try:
            hh = int((request.get_json(silent=True) or {}).get("household_size") or 0)
        except (TypeError, ValueError):
            hh = 0
        if res.get("ok") and 1 <= hh <= 12:
            rpc("lottery_alerts_set_household", {"p_email": email, "p_household": hh})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    if not res.get("ok"):
        reason = res.get("reason", "signup_failed")
        return jsonify(error=reason), (429 if reason == "signup_cap" else 400)
    # Alerts are open to every account again (owner, 2026-10-01, db/0042).
    # plus_required stays in the reply, always false, because TestFlight and
    # App Store builds 101+ read it to decide whether to show the paywall.
    plus_required = False
    # Deliberately no "already subscribed" signal in the reply: that would be
    # an oracle for whether an address is on the list.
    return jsonify(ok=True, boroughs=res.get("boroughs"), kinds=res.get("kinds"),
                   max_rent=res.get("max_rent"), income=res.get("income"),
                   plus_required=plus_required)


def _session_user():
    """{id, email} of the Supabase session in the Authorization header, or
    None. Verified server-side (GET /auth/v1/user) — the client's own claims
    are never trusted."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    if not token:
        return None
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": ANON_KEY, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            u = json.loads(r.read())
    except Exception:
        return None
    email = (u.get("email") or "").strip().lower()
    uid = str(u.get("id") or "")
    if not EMAIL_RE.match(email) or not re.fullmatch(r"[0-9a-f-]{36}", uid):
        return None
    return {"id": uid, "email": email}


# ---- AI features (Find A Crib Plus, owner 2026-10-03) ------------------------
AI = ai_gateway.Gateway(rpc, SUPABASE_URL, SERVICE_KEY)
NB_PAIRS = sorted({(b["nb"], b["b"]) for b in BUILDINGS if b.get("nb")})
NB_ALIASES = nl_search.aliases(NB_PAIRS)
_jev = None


def _jev_client():
    """One TypeSafe client for the process; None without a key or the SDK."""
    global _jev
    if _jev is None and os.environ.get("TYPESAFE_API_KEY"):
        try:
            from typesafe_sdk import TypeSafeClient
            _jev = TypeSafeClient()
        except Exception:
            _jev = False
    return _jev or None


@app.route("/ai/search", methods=["POST"])
def ai_search():
    """Plain-language search -> the map's filters. Plus only; the rules part
    is free to run, Jev is called only for a place the rules cannot pin."""
    user = _session_user()
    err = AI.allow(user, "search")
    if err:
        return jsonify(error=err), (401 if err == "sign_in_required" else 402 if err == "plus_required" else 429)
    q = ((request.get_json(silent=True) or {}).get("q") or "").strip()[:200]
    if len(q) < 2:
        return jsonify(error="empty"), 400
    f, explain, rest = nl_search.parse_rules(q, NB_ALIASES)
    used_ai, model, tokens = False, "rules", 0
    client = _jev_client()
    if client and nl_search.needs_place(rest, f):
        try:
            from typesafe_sdk import Choice
            places, tokens = nl_search.jev_places(client, q, NB_PAIRS, f["boroughs"], Choice)
            if places:
                f["nbs"] = places
                explain += list(dict.fromkeys(re.sub(r"\s*\(.*?\)", "", n) for n in places))
            used_ai, model = True, "jev-1.13.0"
        except Exception as e:      # Jev down: the rules' answer still stands
            app.logger.warning("ai_search jev failed: %s", type(e).__name__)
    AI.record(user, "search", model, input_tokens=tokens)
    return jsonify(ok=True, filters=f, explain=explain, used_ai=used_ai)


@app.route("/ai/rent-check")
def ai_rent_check():
    """Is this building's advertised rent typical for its neighborhood and
    ZIP? Plus only; plain statistics (rent_check.py), so it costs nothing."""
    user = _session_user()
    err = AI.allow(user, "rent_check")
    if err:
        return jsonify(error=err), (401 if err == "sign_in_required" else 402 if err == "plus_required" else 429)
    bbl = re.sub(r"\D", "", request.args.get("bbl", ""))[:10]
    out = rent_check.check(bbl, BY_BBL, _listings, FMR)
    AI.record(user, "rent_check", "rules")
    return jsonify(out)


def _sb_rest(path, method="GET", body=None, prefer=None):
    """Service-role PostgREST call; returns parsed JSON or None."""
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def _ai_cache_get(feature, key, max_age_days=7):
    try:
        since = (datetime.datetime.utcnow() - datetime.timedelta(days=max_age_days)).isoformat() + "Z"
        rows = _sb_rest(f"ai_cache?feature=eq.{feature}&key=eq.{urllib.parse.quote(key)}&created_at=gte.{since}&select=payload")
        return rows[0]["payload"] if rows else None
    except Exception:
        return None


def _ai_cache_put(feature, key, payload):
    try:
        _sb_rest("ai_cache?on_conflict=feature,key", "POST",
                 {"feature": feature, "key": key, "payload": payload, "created_at": datetime.datetime.utcnow().isoformat() + "Z"},
                 prefer="resolution=merge-duplicates,return=minimal")
    except Exception:
        pass


def _records_for(bbl):
    b = BY_BBL.get(bbl)
    if not b:
        return None
    contacts = None
    try:
        rows = _sb_rest(f"hpd_contacts?bbl=eq.{bbl}&select=owner,manager&limit=1")
        contacts = rows[0] if rows else None
    except Exception:
        pass
    return building_records.gather(bbl, b, contacts)


def _ai_err(err):
    return jsonify(error=err), (401 if err == "sign_in_required" else 402 if err == "plus_required" else 429)


@app.route("/ai/report-card")
def ai_report_card():
    """Landlord report card (Plus): Claude Haiku's plain-English read of the
    building's public records, kept a week per building.
    RETIRED 2026-10-03 (owner: too slow; removed from the app, the site and
    Plus) — answers 410 so older TestFlight builds stop spending on it."""
    return jsonify(error="retired"), 410
    user = _session_user()
    bbl = re.sub(r"\D", "", request.args.get("bbl", ""))[:10]
    err = AI.allow(user, "report_card", claude_features.HAIKU)
    if err:
        return _ai_err(err)
    hit = _ai_cache_get("report_card", bbl)
    if hit:
        AI.record(user, "report_card", claude_features.HAIKU, cached=True)
        return jsonify(ok=True, cached=True, **hit)
    rec = _records_for(bbl)
    if not rec:
        return jsonify(error="unknown_building"), 404
    try:
        card, u = claude_features.report_card(rec)
    except Exception as e:
        app.logger.warning("report_card failed: %s", type(e).__name__)
        return jsonify(error="unavailable"), 503
    AI.record(user, "report_card", u["model"] or claude_features.HAIKU, u["input_tokens"], u["output_tokens"],
              cache_write_tokens=u["cache_write_tokens"], cache_read_tokens=u["cache_read_tokens"])
    payload = {"card": card, "as_of": rec["as_of"]}
    _ai_cache_put("report_card", bbl, payload)
    return jsonify(ok=True, cached=False, **payload)


@app.route("/ai/ask", methods=["POST"])
def ai_ask():
    """Ask about this building (Plus): Claude Sonnet answers from the
    building's public records only, citing the record section.
    RETIRED 2026-10-03 with the report card — 410."""
    return jsonify(error="retired"), 410
    user = _session_user()
    body = request.get_json(silent=True) or {}
    bbl = re.sub(r"\D", "", str(body.get("bbl", "")))[:10]
    question = str(body.get("question") or "").strip()[:300]
    if len(question) < 3:
        return jsonify(error="empty"), 400
    err = AI.allow(user, "ask", claude_features.SONNET)
    if err:
        return _ai_err(err)
    rec = _records_for(bbl)
    if not rec:
        return jsonify(error="unknown_building"), 404
    try:
        answer, u = claude_features.ask(rec, question)
    except Exception as e:
        app.logger.warning("ask failed: %s", type(e).__name__)
        return jsonify(error="unavailable"), 503
    AI.record(user, "ask", u["model"] or claude_features.SONNET, u["input_tokens"], u["output_tokens"],
              ok=answer is not None, cache_write_tokens=u["cache_write_tokens"], cache_read_tokens=u["cache_read_tokens"])
    if answer is None:
        return jsonify(ok=False, error="declined"), 200
    return jsonify(ok=True, answer=answer, as_of=rec["as_of"])


_featured = {"at": 0, "by_href": {}}


def _featured_listing(href):
    """The re-rental with this link in today's featured.json (re-read every
    10 minutes). Help me apply only ever fetches these pages."""
    if time.time() - _featured["at"] > 600:
        try:
            with open(os.path.join(DATA_DIR, "featured.json")) as f:
                _featured["by_href"] = {x.get("href"): x for x in json.load(f).get("listings", []) if x.get("href")}
            _featured["at"] = time.time()
        except Exception:
            pass
    return _featured["by_href"].get(href)


@app.route("/ai/apply-help", methods=["POST"])
def ai_apply_help():
    """Help me apply (Plus): steps, documents, deadline, contact and a draft
    email for one re-rental, from the listing and the agent's own page."""
    user = _session_user()
    href = str((request.get_json(silent=True) or {}).get("href") or "")[:500]
    err = AI.allow(user, "apply_help", claude_features.HAIKU)
    if err:
        return _ai_err(err)
    listing = _featured_listing(href)
    if not listing:
        return jsonify(error="unknown_listing"), 404
    key = hashlib.sha1(href.encode()).hexdigest()
    # 7 days: flyer_reader.py reads every listing ahead each night, so a tap
    # is a cache hit, not a 5-60 s page read (owner, 2026-10-03: "this is
    # taking too long for some listings").
    hit = _ai_cache_get("apply_help", key, max_age_days=7)
    if hit:
        AI.record(user, "apply_help", claude_features.HAIKU, cached=True)
        return jsonify(ok=True, cached=True, **hit)
    keep = {k: listing.get(k) for k in claude_features.APPLY_KEEP}
    page = listing_page.text_of(href) if listing.get("href_kind") != "pdf" else ""
    try:
        help_, u = claude_features.apply_help(keep, page)
    except Exception as e:
        app.logger.warning("apply_help failed: %s", type(e).__name__)
        return jsonify(error="unavailable"), 503
    AI.record(user, "apply_help", u["model"] or claude_features.HAIKU, u["input_tokens"], u["output_tokens"],
              cache_write_tokens=u["cache_write_tokens"], cache_read_tokens=u["cache_read_tokens"])
    payload = {"help": help_, "page_read": bool(page)}
    _ai_cache_put("apply_help", key, payload)
    return jsonify(ok=True, cached=False, **payload)


# The iPhone app files its APNs token against the signed-in account
# (Services/PushService.swift); lottery_alerts.py pushes the borough alerts
# it emails to every device behind that address. The account id comes from
# the verified session, never from the body.
PUSH_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")


@app.route("/push/register", methods=["POST"])
def push_register():
    if rate_limited("push_reg", 30, 3600):
        return _too_many()
    if not request.is_json:
        return jsonify(error="json_required"), 415
    u = _session_user()
    if not u:
        return jsonify(error="sign_in_required"), 401
    body = request.get_json(silent=True) or {}
    token = str(body.get("token") or "").strip().lower()
    if not PUSH_TOKEN_RE.match(token):
        return jsonify(error="bad_token"), 400
    env = "sandbox" if body.get("env") == "sandbox" else "production"
    build = str(body.get("build") or "")[:20]
    try:
        rpc("device_token_upsert", {"p_user_id": u["id"], "p_token": token, "p_env": env, "p_build": build})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    return jsonify(ok=True, env=env)


@app.route("/push/unregister", methods=["POST"])
def push_unregister():
    if rate_limited("push_reg", 30, 3600):
        return _too_many()
    if not request.is_json:
        return jsonify(error="json_required"), 415
    if not _session_user():
        return jsonify(error="sign_in_required"), 401
    token = str((request.get_json(silent=True) or {}).get("token") or "").strip().lower()
    if not PUSH_TOKEN_RE.match(token):
        return jsonify(error="bad_token"), 400
    try:
        rpc("device_token_remove", {"p_token": token})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    return jsonify(ok=True)


def _session_email():
    """Email of the Supabase session in the Authorization header, or None.

    Verified server-side (GET /auth/v1/user), same as the dashboard gate —
    the client's own claims are never trusted, and the email is the only
    thing this returns."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    if not token:
        return None
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": ANON_KEY, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            u = json.loads(r.read())
    except Exception:
        return None
    email = (u.get("email") or "").strip().lower()
    return email if EMAIL_RE.match(email) else None


@app.route("/alerts/prefs")
def alerts_prefs():
    """The caller's own alert preferences, for the /alerts/ page to pre-fill.

    Keyed on the verified session email only — there is no email parameter,
    so it cannot say whether anyone else is subscribed."""
    if rate_limited("alerts_prefs", 60, 3600):
        return _too_many()
    email = _session_email()
    if not email:
        return jsonify(error="sign_in_required"), 401
    try:
        res = rpc("lottery_alerts_prefs", {"p_email": email}) or {}
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    res["ok"] = True
    res["email"] = email
    res["plus_required"] = False   # alerts need no Plus since 2026-10-01; old builds read it
    try:
        res["household_size"] = rpc("lottery_alerts_household", {"p_email": email})
    except Exception:
        res["household_size"] = None
    return jsonify(res)


@app.route("/alerts/digest-off", methods=["GET", "POST"])
def alerts_digest_off():
    """Stop only the Tuesday round-up for a borough subscriber; the
    the-minute-it-opens alerts keep going. Same shape as unsubscribe: a GET
    (from the email) only redirects to the page, which asks and then POSTs."""
    body = request.get_json(silent=True) or {}
    token = str(request.args.get("t") or body.get("token") or "").strip().lower()
    if not TOKEN_RE.match(token):
        return jsonify(error="bad_token"), 400
    if request.method == "GET":
        return redirect(f"https://findacrib.com/alerts/#digestoff={token}", code=302)
    if rate_limited("alerts_unsub", 30, 3600):
        return _too_many()
    try:
        ok = rpc("lottery_alerts_digest_off", {"p_token": token})
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    return jsonify(ok=bool(ok))


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


# Alert-email click counter (2026-09-12). lottery_alerts.py:track_links routes
# every link in an alert email through here: record who clicked, then 302 on.
# The signature must match lottery_alerts.alert_link_sig byte for byte. A bad
# or missing signature still gets somewhere useful — the map — but never the
# `u` it carried, so this is not an open redirect.
ALERT_LINK_KINDS = ("alert", "welcome", "nudge", "weekly")
# Corporate mail gateways fetch every link before the reader sees the message.
# Those hits are stored with is_bot so the dashboard can leave them out.
LINK_SCANNER_RE = re.compile(
    r"bot|crawl|spider|preview|scan|safelinks|proofpoint|mimecast|barracuda|"
    r"forcepoint|symantec|trendmicro|sophos|fireeye|cisco|zscaler|urldefense|"
    r"python|curl|wget|go-http|java/|okhttp|headless", re.I)


def _alert_link_sig(sub_id, kind, url):
    k = hashlib.sha256(b"fac-alert-link-v1:" + SERVICE_KEY.encode()).digest()
    return hmac.new(k, f"{sub_id}|{kind}|{url}".encode(), hashlib.sha256).hexdigest()[:32]


@app.route("/alerts/go", methods=["GET", "HEAD"])
def alerts_go():
    sub_id = str(request.args.get("s") or "").strip().lower()
    kind = str(request.args.get("k") or "")
    url = str(request.args.get("u") or "")
    sig = str(request.args.get("g") or "")
    fallback = "https://findacrib.com/?src=alert"
    if not (SERVICE_KEY and TOKEN_RE.match(sub_id) and kind in ALERT_LINK_KINDS
            and url.startswith(("https://", "http://")) and len(url) <= 2048
            and hmac.compare_digest(sig, _alert_link_sig(sub_id, kind, url))):
        resp = redirect(fallback, code=302)
    else:
        ua = request.headers.get("User-Agent", "")
        bot = request.method == "HEAD" or not ua or bool(LINK_SCANNER_RE.search(ua))
        host = (urllib.parse.urlsplit(url).hostname or "")[:253]
        if not rate_limited("alerts_go", 120, 3600):
            # Off the request thread: the click must never wait on Supabase.
            def _record():
                try:
                    rpc("alert_click_record", {"p_sub": sub_id, "p_kind": kind,
                                               "p_host": host, "p_bot": bot})
                except Exception:
                    pass
            threading.Thread(target=_record, daemon=True).start()
        resp = redirect(url, code=302)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# ---- /geo: coarse network location for the map's first view -----------------
#
# The map opens on the visitor's own neighbourhood without asking the browser
# for location (no permission prompt — owner rule). The IP is resolved
# server-side against DB-IP's free City Lite database (scripts/refresh_geoip.sh)
# and only a rounded point plus the borough of the nearest rent-stabilized
# building goes back. Nothing is stored: the address is not logged here and
# the visits table has never held IPs.
GEOIP_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dbip-city-lite.mmdb")
_GEO = {"reader": None, "mtime": 0.0}
_GEO_LOCK = threading.Lock()
_GEO_CACHE = {}                      # rounded (lat, lng) -> boro; bounded below
NYC_BBOX = (40.49, -74.27, 40.92, -73.68)     # lat_min, lng_min, lat_max, lng_max


def _geo_reader():
    try:
        import maxminddb
    except ImportError:
        return None
    try:
        mtime = os.stat(GEOIP_DB).st_mtime
    except OSError:
        return None
    with _GEO_LOCK:
        if _GEO["reader"] is None or _GEO["mtime"] != mtime:
            try:
                if _GEO["reader"] is not None:
                    _GEO["reader"].close()
            except Exception:
                pass
            _GEO["reader"] = maxminddb.open_database(GEOIP_DB)
            _GEO["mtime"] = mtime
        return _GEO["reader"]


def _nearest_boro(lat, lng):
    """Borough of the nearest building within ~2 km, by the map's own data —
    so "near you" means near something the map can actually show."""
    key = (round(lat, 2), round(lng, 2))
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    best, best_d = None, (0.02 ** 2) * 2       # ~2 km in squared degrees
    coslat = 0.757                             # cos(40.7°): scale lng to lat
    for b in BUILDINGS:
        blat, blng = b.get("lat"), b.get("lng")
        if not isinstance(blat, (int, float)) or not isinstance(blng, (int, float)):
            continue
        d = (blat - lat) ** 2 + ((blng - lng) * coslat) ** 2
        if d < best_d:
            best, best_d = b.get("b"), d
    if len(_GEO_CACHE) > 4000:
        _GEO_CACHE.clear()
    _GEO_CACHE[key] = best
    return best


@app.route("/geo")
def geo():
    if rate_limited("geo", 60, 60):
        return _too_many()
    reader = _geo_reader()
    if reader is None:
        return jsonify(ok=False, reason="unavailable")
    try:
        rec = reader.get(_client_ip()) or {}
    except Exception:
        rec = {}
    loc = rec.get("location") or {}
    lat, lng = loc.get("latitude"), loc.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return jsonify(ok=False, reason="unknown")
    inside = NYC_BBOX[0] <= lat <= NYC_BBOX[2] and NYC_BBOX[1] <= lng <= NYC_BBOX[3]
    boro = _nearest_boro(lat, lng) if inside else None
    city = ((rec.get("city") or {}).get("names") or {}).get("en")
    # Rounded to ~1 km: enough to open the map on the right neighbourhood,
    # not enough to place a household.
    return jsonify(ok=bool(boro), lat=round(lat, 2), lng=round(lng, 2),
                   boro=boro, city=city)


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
                "A pre-filled DHCR rent-history request — the step that "
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
_MEMO_REFRESHING = set()
# One computation per key at a time. The all-time window asks _fac_adtiles(None)
# twice in the same request (the ranged card and the all-time card), and both
# used to run the heaviest query side by side.
_MEMO_KEYLOCKS = {}
# Past its ttl an entry is still served for this long while a background thread
# recomputes it. Before this, every expired entry was paid in the foreground:
# by 2026-09-26 a cold all-time load was the 3.5 s RPC then a 4.5 s adtiles
# scan — 8-9 s, 336 of 1,613 dashboard-metrics calls over 8 s — and the page's
# 8 s sign-in failsafe told the owner "Sign-in is taking too long".
_MEMO_STALE = 1800


def _memo(ttl):
    def wrap(fn):
        def compute(key, args, fresh_ok=False):
            with _MEMO_LOCK:
                keylock = _MEMO_KEYLOCKS.setdefault(key, threading.Lock())
            with keylock:
                if fresh_ok:
                    with _MEMO_LOCK:
                        hit = _MEMO.get(key)
                    if hit and hit[0] > time.time():
                        return hit[1]   # a concurrent caller just computed it
                return _compute(key, args)

        def _compute(key, args):
            val = fn(*args)
            # Every helper returns {} (or None) on failure. Caching that for
            # the full ttl turned one slow query into ten minutes of a blank
            # card: on 2026-09-26 the all-time ad count failed once and the
            # dashboard showed today's 28 under an "all time" label until the
            # memo expired. A failure is retried on the next load instead.
            if val is None or val == {}:
                return val
            now = time.time()
            with _MEMO_LOCK:
                if len(_MEMO) > 128:
                    for k in [k for k, v in _MEMO.items() if v[0] + _MEMO_STALE < now]:
                        del _MEMO[k]
                    if len(_MEMO) > 128:
                        _MEMO.clear()
                _MEMO[key] = (now + ttl, val)
            return val

        def background(key, args):
            try:
                compute(key, args)
            except Exception:
                pass
            finally:
                with _MEMO_LOCK:
                    _MEMO_REFRESHING.discard(key)

        def inner(*args):
            key = (fn.__name__,) + tuple(str(a) for a in args)
            now = time.time()
            with _MEMO_LOCK:
                hit = _MEMO.get(key)
                if hit and hit[0] > now:
                    return hit[1]
                stale = hit is not None and hit[0] + _MEMO_STALE > now
                kick = stale and key not in _MEMO_REFRESHING
                if kick:
                    _MEMO_REFRESHING.add(key)
            if stale:
                if kick:
                    threading.Thread(target=background, args=(key, args), daemon=True).start()
                return hit[1]
            return compute(key, args, fresh_ok=True)

        inner.refresh = lambda *args: compute((fn.__name__,) + tuple(str(a) for a in args), args)
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
    uid = (u.get("id") or "").strip().lower()
    # email_confirmed_at only. user_metadata is writable by the user themself
    # (supabase.auth.updateUser({data: …})), so user_metadata.email_verified
    # proves nothing and must never be a fallback.
    if not u.get("email_confirmed_at"):
        return _auth_cached(key, "forbidden", token)
    if email == OWNER_EMAIL:
        return _auth_cached(key, "ok", token)
    if uid and uid in NEMO_USER_IDS:
        return _auth_cached(key, "nemo", token)   # NEMO tab only, see NEMO_USER_IDS
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


# Tracking began 24 June 2026. A `since` before that selects the same rows as
# no `since` at all — but dashboard_metrics() computes 6m/3m as now() minus an
# interval, so the value moved on every call and a memo keyed on it never hit:
# those two windows paid the full adtiles scan on every click, TTL or not.
FAC_TRACKING_START = datetime.datetime(2026, 6, 24, 4, tzinfo=datetime.timezone.utc)


# That covered 6m only while 3m still reached back past 24 June. On
# 2026-09-25 "3 months ago" became 25 June, the 3m boundary started moving
# again, and every 3-month click paid the adtiles scan (~2.3 s) on top of the
# main RPC — past 8 s cold, so the picker sat disabled and then failed. A
# moving boundary is therefore floored to FAC_SINCE_STEP: the side cards count
# from up to ten minutes before the headline window on a 90-day range, and the
# memo hits for the whole step. Midnight and month boundaries are already on
# a step and do not move.
FAC_SINCE_STEP = 600


def _fac_since(since):
    """The range boundary as a memo key: None when it is before tracking began."""
    if not since:
        return None
    try:
        t = datetime.datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except ValueError:
        return since
    if t <= FAC_TRACKING_START:
        return None
    ts = int(t.timestamp()) // FAC_SINCE_STEP * FAC_SINCE_STEP
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()


# The SQL function is 2.2 s for all-time (0.4 s today) and its answer does not
# change inside a minute. The page asks for the same window from two tabs, a
# reload and its 5-minute refresh; this is what keeps those from each paying.
@_memo(60)
def _fac_metrics_rpc(rng, builds):
    # `builds` is the tuple of iOS builds that ever reached the App Store, from
    # appstore.json. The SQL counts app launches as visits and drops every
    # other build (simulators, TestFlight, App Review). An empty tuple means
    # the file is missing, and the SQL then applies no filter — a dashboard
    # without appstore.json should not silently lose every app user.
    return rpc("dashboard_metrics", {"p_range": rng,
                                     "p_ios_builds": list(builds) if builds else None})


def _fac_released_builds():
    """iOS build numbers that reached the App Store, as strings, sorted."""
    rb = _fac_appstore().get("released_builds") or []
    return tuple(sorted({str(b) for b in rb if str(b).isdigit()}, key=int))


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
        # A copy: the memo hands every caller the same dict, and the keys added
        # below must not leak into it.
        data = dict(_fac_metrics_rpc(rng, _fac_released_builds()))
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    since = _fac_since(data.get("since"))
    # The side cards are independent network calls, so they run side by side
    # rather than one after another: cold, the sequence was adtiles 2.3 s +
    # ads_served 0.4 s + the rest, stacked on the main RPC. Each helper
    # already returns {} (or its own empty shape) on failure.
    jobs = {
        # The engine's own build log. It lives on disk in the growth checkout,
        # not in Postgres, because the 05:40 build runs on this droplet and
        # never writes to the database.
        "build": (_fac_build,),
        "channels": (_fac_channels, since),
        "page_views": (_fac_page_views, since),
        "mediavine": (_fac_mediavine, since),
        # Free-to-paid for the accounts created in this range (db/0048).
        "plus_cohort": (_fac_plus_cohort, since),
        "plus_all": (_fac_plus_cohort, None),
        # The header's Raptive goal (25k/month) is always the last 30 days.
        "page_views_30d": (_fac_page_views, (datetime.datetime.now(datetime.timezone.utc)
                                              - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:00:00Z")),
        # Inputs for the goals card's audience-INDEPENDENT streams. Deliberately
        # not range-scoped: that card is pinned to all-time for the same reason.
        "ai": (_fac_ai_crawls,),
        "consult_clicks": (_fac_consult_clicks,),
        "agents": (_fac_agent_pool,),
        "signage": (_fac_signage, since),
        "appstore": (_fac_appstore,),
        # Seven calendar months of distinct visitors, for the bars beside the
        # seven days. Not range-scoped: a month bar that changed with the
        # picker would be a different chart wearing the same axis.
        "months": (_fac_months,),
        # Accounts created per day and per month, for the sign-up bars paired
        # with the visitor bars. Same windows as the chart, not range-scoped.
        "signups_series": (_fac_signups_series,),
        # Alert sign-up conversion, 7-day rolling per day since alerts
        # launched (db/0038). Not range-scoped: it is a trend line.
        "alert_trend": (_fac_alert_trend,),
        # Visitors and sign-ups per day since 24 Jun, for the visitors chart's
        # period picker (db/0040). Not range-scoped.
        "daily_series": (_fac_daily_series,),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = {k: pool.submit(*v) for k, v in jobs.items()}
        got = {k: f.result() for k, f in futs.items()}
    data["goalstreams"] = {k: got.pop(k) for k in ("ai", "consult_clicks", "agents")}
    # Paying excludes first-month trials since the trial launched (2026-10-04):
    # the RPC behind data["subscriptions"] counts 'trialing' as paying, which
    # would book every trial as $4.99 of MRR.
    plus_all = got.pop("plus_all") or {}
    subs = data.get("subscriptions")
    if isinstance(subs, dict) and plus_all.get("paying") is not None:
        subs["paying"] = plus_all["paying"]
        subs["trialing"] = plus_all.get("trialing", 0)
        subs["mrr"] = round(plus_all["paying"] * 4.99, 2)
    data.update(got)
    # Moving goals for the three audience counts. The check runs against the
    # numbers of the all-time call (the same fixed windows every range shows)
    # and only reads on the others, so switching the range picker cannot
    # record an achievement twice.
    data["goals"] = (_fac_goals(data.get("engagement") or {}, True) if rng == "all"
                     else _fac_goals_read())
    return jsonify(data)


# 80k visitors a day (owner, 2026-09-30; was 8k DAU on 9/27); WAU/MAU derived
# as in the page. Only seeds a missing row — the live goals are the
# dashboard_goals table, set to these by hand the same day.
FAC_GOAL_DEFAULTS = (("dau", 80000), ("wau", 360000), ("mau", 800000))


def _fac_goals(engagement, evaluate):
    """Current goal and the record of goals reached, per audience count.

    dashboard_goal_check (db/0027) raises a reached goal by 30%, rounded up to
    a ten, and appends {goal, value, achieved_at}. With evaluate=False it only
    reads."""
    out = {}
    for key, default in FAC_GOAL_DEFAULTS:
        val = engagement.get(key) if evaluate else None
        try:
            val = float(val) if val is not None else None
        except (TypeError, ValueError):
            val = None
        try:
            out[key] = rpc("dashboard_goal_check",
                           {"p_metric": key, "p_value": val, "p_default": default}) or {}
        except Exception:
            out[key] = {}
    return out


# The read-only copy the non-all-time ranges show: three RPCs whose answer
# only changes when an all-time call records a goal.
@_memo(120)
def _fac_goals_read():
    return _fac_goals({}, False)


FAC_MONTHS = 7
FAC_TZ = "America/New_York"


# 60 s like the metrics RPC (~0.5 s of SQL): at 600 s the chart's "last 30
# days" lagged the investor tiles under it (5,470 vs 5,473 visitors).
@_memo(60)
def _fac_daily_series():
    """{days: [{date, visitors, signups}], periods: {"7"|"30"|"90": {visitors,
    prev_visitors, signups, prev_signups}, "all": {visitors, signups}}} —
    distinct visitors counted as dashboard_metrics' v_all, sign-ups as the
    Sign-ups tile (db/0040). {} on failure."""
    try:
        return rpc("dashboard_daily_series", {"p_ios_builds": list(_fac_released_builds()) or None}) or {}
    except Exception:
        return {}


@_memo(600)
def _fac_alert_trend():
    """[{date, visitors, signups, on, *_day}] — alert sign-up conversion as a
    7-day rolling rate per New York day since 2026-09-03, with "on" = the
    sign-ups that actually receive alerts (grandfathered or Plus). Built to
    watch the 2026-09-30 switch to Plus-only alerts. [] on failure."""
    try:
        return rpc("dashboard_alert_trend", {"p_ios_builds": list(_fac_released_builds()) or None}) or []
    except Exception:
        return []


@_memo(300)
def _fac_signups_series():
    """{"days": {"YYYY-MM-DD": n}, "months": {"YYYY-MM": n}} of Find A Crib
    accounts, counted as the Sign-ups tile counts them (db/0036). Missing
    keys are zero. {} on failure, so the chart simply draws no sign-up bars."""
    try:
        return rpc("dashboard_signups_series",
                   {"p_days": 14, "p_months": FAC_MONTHS}) or {}
    except Exception:
        return {}


# Not range-scoped (see the docstring), so it was 0.8 s of PostgREST paging
# recomputed on every flip for an answer that changes once a day.
@_memo(600)
def _fac_months(count=FAC_MONTHS):
    """Distinct visitors and page views per calendar month, newest last.

    Computed here rather than by summing the daily sparkline: a person who
    comes back on three days is three daily visitors and one monthly one,
    and on a site where returning visitors are the number being watched the
    sum would flatter every month by exactly the amount that matters.

    Buckets are New York calendar months, the same clock the range picker
    uses. Months before per-site logging began carry `logged: False` so the
    chart can draw a gap rather than a zero, and the current month carries
    `partial: True` so it is not read as a bad month at the start of one.
    """
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(FAC_TZ)
    now = datetime.datetime.now(tz)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Walk back count-1 months from the first of this month.
    y, m = first.year, first.month
    for _ in range(count - 1):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    start = first.replace(year=y, month=m)
    keys = []
    y, m = start.year, start.month
    for _ in range(count):
        keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    out = {k: {"month": k, "visitors": 0, "views": 0,
               "partial": k == keys[-1], "logged": False} for k in keys}
    # PostgREST caps a response at 1,000 rows and says nothing when it does —
    # the first cut of this function asked for 50,000, got the oldest 1,000,
    # and reported August as one visitor. Page in created_at order until a
    # short page comes back.
    PAGE, MAX_PAGES = 1000, 60
    rows = []
    try:
        mine = _fac_owner_visitors()
        for page in range(MAX_PAGES):
            chunk = _rest("GET", "visits?select=visitor_id,created_at"
                                 f"&created_at=gte.{urllib.parse.quote(start.isoformat())}"
                                 f"&order=created_at.asc&limit={PAGE}&offset={page * PAGE}") or []
            rows.extend(chunk)
            if len(chunk) < PAGE:
                break
    except Exception:
        return {"months": list(out.values()), "ok": False}
    seen = {k: set() for k in keys}
    earliest = None
    for r in rows:
        ts = r.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz)
        except Exception:
            continue
        k = f"{dt.year:04d}-{dt.month:02d}"
        if k not in out or r.get("visitor_id") in mine:
            continue
        out[k]["views"] += 1
        if r.get("visitor_id"):
            seen[k].add(r["visitor_id"])
        if earliest is None or dt < earliest:
            earliest = dt
    for k in keys:
        out[k]["visitors"] = len(seen[k])
        # A month is "logged" from the month the first row landed in onward,
        # even if a later one happened to be empty.
        out[k]["logged"] = bool(earliest) and k >= f"{earliest.year:04d}-{earliest.month:02d}"
    return {"months": list(out.values()), "ok": True,
            "truncated": len(rows) >= PAGE * MAX_PAGES,
            "history_from": earliest.date().isoformat() if earliest else None}


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


@_memo(600)
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


@_memo(600)
def _fac_page_views(since):
    """Website page views: one public.visits row per page load (index.html's
    boot insert and build_seo.py's TRACK_SNIPPET on every generated page),
    cleaned exactly as dashboard_metrics' v_all cleans them — the owner's
    visitor ids out, and a building/borough/neighborhood hit with no referrer
    out (a scraper that runs JS, never a person arriving from somewhere).
    The owner asked for page views in place of time on site, 2026-09-28.
    `map` is the app page itself ("/" and "/?…"); `other` is every other page
    (building, landlord, guide and city pages). {} on failure."""
    conds = ["visitor_id.not.is.null",
             "or(and(referrer.not.is.null,referrer.neq.),"
             "and(path.not.like./building/*,path.not.like./borough/*,path.not.like./neighborhood/*))"]
    mine = sorted(_fac_owner_visitors())
    if mine:
        conds.append("visitor_id.not.in.(" + ",".join('"' + v.replace('"', "") + '"' for v in mine) + ")")
    q = "visits?select=id&and=" + urllib.parse.quote("(" + ",".join(conds) + ")", safe='(),.*/"')
    if since:
        q += f"&created_at=gte.{urllib.parse.quote(str(since))}"
    try:
        total = _rest_count(q)
        on_map = _rest_count(q + "&or=" + urllib.parse.quote("(path.eq./,path.like./?*)", safe="(),.*/?"))
    except Exception:
        return {}
    return {"total": total, "map": on_map, "other": total - on_map}


@_memo(600)
def _fac_plus_cohort(since):
    """{accounts, paying, trialing} for accounts created since `since` (None =
    all). {} on failure."""
    try:
        return rpc("dashboard_plus_cohort", {"since": str(since) if since else None}) or {}
    except Exception:
        return {}


@_memo(600)
def _fac_mediavine(since):
    """Mediavine ads shown on the website, from the page's own batched count
    (index.html: ad_impression rows with network=mediavine carrying paid /
    house / n). Mediavine has no reporting API, so this is the site's view;
    their dashboard is the money. Owner's visits out. Revenue is estimated only
    when FAC_MEDIAVINE_PAGE_RPM (Mediavine dashboard, $ per 1,000 page views)
    is set in the API's .env. {} on failure."""
    q = ("events?select=props&event=eq.ad_impression&props->>network=eq.mediavine"
         "&props->>platform=eq.web")
    if since:
        q += f"&created_at=gte.{urllib.parse.quote(str(since))}"
    mine = sorted(_fac_owner_visitors())
    if mine:
        ids = ",".join('"' + v.replace('"', "") + '"' for v in mine)
        q += "&or=" + urllib.parse.quote(f"(visitor_id.is.null,visitor_id.not.in.({ids}))", safe="(),.")
    paid = house = rows = 0
    try:
        start = 0
        while True:
            chunk = _rest("GET", q + f"&order=id.asc&offset={start}&limit=1000") or []
            for r in chunk:
                pr = r.get("props") or {}
                paid += int(pr.get("paid") or 0)
                house += int(pr.get("house") or 0)
            rows += len(chunk)
            if len(chunk) < 1000 or start > 200_000:
                break
            start += 1000
    except Exception:
        return {}
    out = {"paid": paid, "house": house, "total": paid + house, "rows": rows}
    try:
        rpm = float(os.environ.get("FAC_MEDIAVINE_PAGE_RPM") or 0)
    except ValueError:
        rpm = 0
    if rpm > 0:
        out["page_rpm"] = rpm
    # Google's ads in the iPhone app (AdMob), on the same tile (owner,
    # 2026-10-03): one ad_impression row per live ad the app showed;
    # TestFlight's test ads (mode=test) are Google's samples and stay out.
    # AdMob's console has the money; FAC_ADMOB_ECPM ($ per 1,000 ads, copied
    # from it) gives an estimate when set.
    try:
        aq = "events?select=id&event=eq.ad_impression&props->>mode=eq.live&props->>platform=eq.ios"
        if since:
            aq += f"&created_at=gte.{urllib.parse.quote(str(since))}"
        if mine:
            aq += "&or=" + urllib.parse.quote(f"(visitor_id.is.null,visitor_id.not.in.({ids}))", safe="(),.")
        out["admob"] = _rest_count(aq)
        ecpm = float(os.environ.get("FAC_ADMOB_ECPM") or 0)
        if ecpm > 0:
            out["admob_ecpm"] = ecpm
    except Exception:
        pass
    return out




# Every ad the owner's platforms have put in front of someone, one number.
# Find A Crib is the only product that serves ads (checked 2026-09-25: no
# other repo logs an ad event), so "all platforms" is its three surfaces:
#   * web advertiser tiles — `tile_served` (rendered into the grid);
#   * iPhone advertiser tiles — `tile_impression` with platform=ios, which the
#     app logs at render time (it has no separate tile_served);
#   * the iPhone AdMob banner — `ad_impression` with mode=live. TestFlight's
#     mode=test rows are Google's sample ads, not inventory: reported beside
#     the total, never in it.
# AdSense on the web is wired but has no slot id, so it serves nothing yet.
# Owner traffic is dropped the same way the ad-tile card drops it.
FAC_AD_SOURCES = (
    # Counted the way Google counts its own ads (owner, 2026-09-28): an
    # impression when the ad LOADS, once per ad per page view, seen or not —
    # AdSense counts one when an ad "has begun to download" and pays on that.
    # tile_served is exactly that (countServed: once per apartment per page);
    # tile_impression, the seen count, is the Advertiser metrics page's.
    # The app has one event for both: its tile_impression fires as the tile
    # loads onto the screen.
    ("web_tiles", "event=eq.tile_served"),
    ("app_tiles", "event=eq.tile_impression&props->>platform=eq.ios"),
    ("admob", "event=eq.ad_impression&props->>mode=eq.live&props->>platform=eq.ios"),
    # The website's AdSense in-feed tiles, logged when a slot fills (index.html
    # settleAds, 2026-09-25). Web rows carry platform=web.
    ("adsense", "event=eq.ad_impression&props->>mode=eq.live&props->>platform=eq.web&props->>network=eq.adsense"),
    ("admob_test", "event=eq.ad_impression&props->>mode=eq.test"),
)




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


APPSTORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "appstore.json")


def _fac_appstore():
    """The iPhone app's App Store numbers, as pulled by ios/scripts/asc_downloads.py.

    That script runs on the owner's Mac (the App Store Connect key does not
    live on this droplet) and scp's appstore.json next to this file twice a
    day. Missing or unreadable -> {} and the dashboard drops the card rather
    than 500ing.
    """
    try:
        with open(APPSTORE_FILE) as f:
            d = json.load(f)
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


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


@app.route("/dashboard-marracat")
def dashboard_marracat():
    """Marracat — the dashboard's fifth site tab.

    Owner scope only: another of the owner's businesses, not Eric's. The
    numbers are computed on Marracat's own droplet and fetched with a shared
    key (see marracat_metrics.py). Counts only: no shopper's name, email or
    order crosses this endpoint.
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
        return jsonify(marracat_metrics.build_cached(rng=rng))
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503


@app.route("/dashboard-marracat-users")
def dashboard_marracat_users():
    """Marracat's shopper roster (names, emails, orders) for the owner's
    /dashboard/marracat-users/ page. Owner scope only, like /dashboard-users."""
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    data = marracat_metrics.users()
    if not data.get("ok"):
        return jsonify(error="temporarily_unavailable", warnings=data.get("warnings")), 503
    return jsonify(data)


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
    # [[build, version]] from App Store Connect (asc_downloads.py writes it
    # into appstore.json), so the page never hand-maintains that map again.
    return jsonify(users=data or [], versions=_fac_appstore().get("versions") or [])


VISITOR_WINDOWS = ("today", "7", "30", "90", "all")


@_memo(300)
def _fac_visitors(window="today"):
    """Visitors seen in a window (2026-10-06: load one window at a time, not
    every visitor ever). today = since midnight in New York."""
    since = None
    if window == "today":
        ny = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
        since = ny.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(datetime.timezone.utc).isoformat()
    elif window in ("7", "30", "90"):
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=int(window))).isoformat()
    rows = rpc("dashboard_visitors", {"since": since}) or []
    mine = set(_fac_owner_visitors())
    return [r for r in rows if r.get("visitor_id") not in mine]


@app.route("/dashboard-visitors")
def dashboard_visitors():
    """Every visitor of the site and the app (owner, 2026-10-06), in the
    Signed Up Users page's shape (db/0049); the owner's own visits left out."""
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    window = request.args.get("days", "today")
    if window not in VISITOR_WINDOWS:
        window = "today"
    try:
        rows = _fac_visitors(window)
    except Exception:
        return jsonify(error="temporarily_unavailable"), 503
    return jsonify(users=rows, versions=_fac_appstore().get("versions") or [])


# ---------- creator outreach (owner only) ----------
# The page is /dashboard/creators/ on divinedavis.com, whose nginx proxies
# /api/dashboard-* here. Rows and brief files live outside git, see
# creator_outreach.py.
@app.route("/dashboard-creators")
def dashboard_creators():
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    return jsonify(creators=creator_outreach.listing(), stages=creator_outreach.STAGES)


@app.route("/dashboard-creators/<cid>", methods=["POST"])
def dashboard_creator_update(cid):
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    try:
        row = creator_outreach.update(cid, request.get_json(silent=True))
    except KeyError:
        return jsonify(error="not_found"), 404
    except ValueError as e:
        return jsonify(error="bad_request", message=str(e)), 400
    return jsonify(creator=row)


@app.route("/dashboard-creators/<cid>/send", methods=["POST"])
def dashboard_creator_send(cid):
    """The row's Send button: email the creator their PDF brief now."""
    if rate_limited("creator-send", 60, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    try:
        return jsonify(creator=creator_outreach.send_pitch(cid))
    except KeyError:
        return jsonify(error="not_found"), 404
    except ValueError as e:
        return jsonify(error="cannot_send", message=str(e)), 400
    except Exception as e:
        return jsonify(error="send_failed", message=type(e).__name__), 502


@app.route("/dashboard-creators/<cid>/brief.<ext>")
def dashboard_creator_brief(cid, ext):
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    p = creator_outreach.brief_file(cid, ext)
    if p is None:
        return jsonify(error="not_found"), 404
    from flask import send_file
    resp = send_file(p, mimetype="application/pdf" if ext == "pdf" else "image/jpeg",
                     download_name=f"{cid}-brief.{ext}")
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


# ---------- business & legal checklist (owner only) ----------
# /dashboard/business/ on divinedavis.com. The steps live in the page; this
# stores which are done, notes and the per-app matrix, see business_checklist.py.
@app.route("/dashboard-business", methods=["GET", "POST"])
def dashboard_business():
    if rate_limited("dashboard", 120, 3600):
        return _too_many()
    denied = _dashboard_denial(_dashboard_auth(), ("ok",))
    if denied:
        return denied
    if request.method == "GET":
        return jsonify(business_checklist.listing())
    try:
        return jsonify(business_checklist.update(request.get_json(silent=True)))
    except ValueError as e:
        return jsonify(error="bad_request", message=str(e)), 400


@app.route("/creators-ingest", methods=["POST"])
def creators_ingest():
    """The owner's laptop app pushes briefs and sent-pitch stages here.
    Shared secret, compared in constant time; unset key = endpoint off."""
    if rate_limited("creators-ingest", 300, 3600):
        return _too_many()
    want = os.environ.get("CREATOR_INGEST_KEY", "")
    got = request.headers.get("X-Ingest-Key", "")
    if not want or not hmac.compare_digest(want.encode(), got.encode()):
        return jsonify(error="forbidden"), 403
    # The app-wide 16 KB body cap stays for every other route; a brief JPG +
    # PDF as base64 is ~350 KB, so this one route (key-checked above) gets more.
    request.max_content_length = 1_500_000
    try:
        return jsonify(creator_outreach.ingest(request.get_json(silent=True)))
    except ValueError as e:
        return jsonify(error="bad_request", message=str(e)), 400


# Keep every range's expensive parts fresh so no page load pays them cold —
# the page prefetches all five windows after its first paint anyway, so this
# is about one page load's worth of queries every 10 minutes. Only under
# gunicorn (one worker, see deploy/findacrib-api.override.conf), never on a
# plain import.
def _fac_keep_warm():
    time.sleep(5)
    while True:
        try:
            builds = _fac_released_builds()
            for rng in sorted(DASHBOARD_RANGES):
                since = _fac_since((_fac_metrics_rpc.refresh(rng, builds) or {}).get("since"))
                for helper in (_fac_channels, _fac_signage):
                    helper.refresh(since)
            _fac_months.refresh()
        except Exception:
            pass
        time.sleep(600)


if "gunicorn" in os.path.basename(__import__("sys").argv[0]):
    threading.Thread(target=_fac_keep_warm, daemon=True).start()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8010)
