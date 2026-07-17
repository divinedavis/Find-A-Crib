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
import hashlib, json, os, urllib.request, urllib.error
from flask import Flask, jsonify, request, g

DATA_DIR = os.environ.get("DATA_DIR", ".")
SUPABASE_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BORO = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens", "Bx": "bronx", "SI": "staten_island"}
BORO_REV = {v: k for k, v in BORO.items()}
MAX_LIMIT = 100
DOCS = "https://findacrib.com/developers"

app = Flask(__name__)

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
        "latitude": b.get("lat"),
        "longitude": b.get("lng"),
        "rent_stabilized": True,             # every building here is DHCR-registered stabilized
        "units": b.get("u"),
        "year_built": b.get("yr"),
        "stabilization_codes": b.get("s") or [],
        "recently_advertised": b["bbl"] in LISTED,
        "hpd": hpd,
        "section8": s8_for(b["bbl"]),
    }


# ---- auth / metering --------------------------------------------------------
def authorize(key):
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/api_authorize",
        data=json.dumps({"p_key_hash": key_hash}).encode(),
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return {"allowed": False, "reason": "auth_unavailable"}


PUBLIC_PATHS = {"/", "/v1", "/v1/", "/health"}


@app.before_request
def gate():
    if request.method == "OPTIONS" or request.path in PUBLIC_PATHS:
        return
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
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
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(MAX_LIMIT, max(1, int(request.args.get("limit", 50))))
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
    window = res[start:start + limit]
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8010)
