#!/usr/bin/env python3
"""Pull NYC lotteries and waitlists from HousingSearch.ny.gov into hcr.json.

HousingSearch.ny.gov (HCR's replacement for NYHousingSearch.gov) lists every
development with an HCR regulatory agreement that is taking applications —
new-construction lotteries, open waitlists and Mitchell-Lama waitlists. There
is no export and no documented API; the portal is a Salesforce Experience
Cloud site whose Lightning components call Apex over the `aura` endpoint.
Three of those calls, replayed with plain POSTs, give everything the app
needs (stdlib only, ~1s apart, ~110 requests a night):

  HousingSearchV4.getWaitListRecords          one call: every record statewide
  FlexRuntime  MCCWaitlistDetailsChildBuildings per record: building street addresses
  FlexRuntime  MCCWaitlistListingExtract        per record: type, incomes, fee, phone,
                                               description, mailing address, links

Addresses are geocoded with NYC Planning's free GeoSearch (no key), which
also returns the BBL — so a listing whose building is on the DHCR register
lands on that building; the rest become their own pins. Mitchell-Lama
waitlists rarely list a building address; their mailing address (usually
the development's own office) is used and flagged approximate.

The Salesforce framework id (fwuid) changes with each release, so it is read
off the portal's home page on every run rather than hard-coded. The site
does not send its GlobalSign intermediate, so hcr_chain.pem is added to the
trust store; without it every request fails certificate verification.

GlobalSign issues from a new intermediate every quarter, so each renewal of
the portal's certificate used to stop this feed until someone replaced
hcr_chain.pem by hand (2026-11-23: R3 "2025 Q4" -> R46 "2026 Q4", ten hours
stale). heal_chain() now does that step itself: when verification fails it
reads the "CA Issuers" address printed in the portal's certificate, downloads
that intermediate, and keeps it only if it chains to a root this machine
already trusts. Trust is never widened: a certificate the system roots do
not vouch for is thrown away and the run fails as before.

Output hcr.json:
  {"updated": epoch, "updated_iso": ..., "count": n,
   "listings": [{"id", "name", "kind": "Lottery|Waitlist|Mitchell-Lama Waitlist",
                 "status", "ptype": "Rental|Co-op", "boro": "M|Bk|Q|Bx|SI",
                 "min_income", "max_income", "due", "fee", "phone", "url",
                 "info", "desc", "approx": bool,
                 "buildings": [{"street","zip","lat","lng","bbl"}]}]}

Usage:  python3 pipeline/scrape_hcr.py [--out hcr.json]
"""
import json, os, re, ssl, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

from addr_match import build_index, normalize_addr

HERE = Path(__file__).resolve().parent
if HERE.name == "pipeline":  # in the repo, data and growth/ live one level up; flat copies keep them beside the script
    HERE = HERE.parent
# Tracked data files live in data/ in the repo (flat copies keep them beside the script).
DATA = HERE / "data" if Path(__file__).resolve().parent.name == "pipeline" else HERE
SITE = "https://housingsearch.hcr.ny.gov"
UA = "FindACrib/1.0 (+https://findacrib.com; findacrib data pipeline)"
PAUSE = 1.0
GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
COUNTY_TO_BORO = {"New York": "M", "Bronx": "Bx", "Kings": "Bk", "Queens": "Q", "Richmond": "SI"}

CHAIN = Path(__file__).resolve().parent / "hcr_chain.pem"       # tracked: intermediates checked in by hand
CHAIN_AUTO = Path(__file__).resolve().parent / "hcr_chain.auto.pem"  # untracked: the one heal_chain() fetched
# The only places an intermediate may be downloaded from. The address comes out
# of a certificate nobody has verified yet, so it is never followed blindly.
AIA_HOSTS = {"secure.globalsign.com"}
AIA_MAX = 64 * 1024

_ctx = ssl.create_default_context()
for _f in (CHAIN, CHAIN_AUTO):
    try:
        _ctx.load_verify_locations(cafile=str(_f))
    except FileNotFoundError:
        if _f is CHAIN:
            print("warn: hcr_chain.pem is missing", file=sys.stderr)
    except Exception as e:  # keep going; the default store may have it
        print(f"warn: {_f.name} not loaded:", e, file=sys.stderr)
_healed = False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def aia_url(leaf_pem):
    """The "CA Issuers" address printed in a certificate, if we may fetch it."""
    try:
        text = subprocess.run(["openssl", "x509", "-noout", "-text"], input=leaf_pem,
                              capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"CA Issuers - URI:(\S+)", text)
    if not m:
        return None
    u = urllib.parse.urlsplit(m.group(1))
    if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in AIA_HOSTS or u.port:
        return None
    return m.group(1)


def chains_to_a_trusted_root(pem):
    """True only when the system's own roots vouch for this certificate."""
    paths = ssl.get_default_verify_paths()
    cmd = ["openssl", "verify"]
    if paths.cafile and os.path.exists(paths.cafile):
        cmd += ["-CAfile", paths.cafile]
    if paths.capath and os.path.isdir(paths.capath):
        cmd += ["-CApath", paths.capath]
    with tempfile.NamedTemporaryFile("w", suffix=".pem") as f:
        f.write(pem)
        f.flush()
        try:
            return subprocess.run(cmd + [f.name], capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


def heal_chain():
    """Fetch the intermediate the portal does not send. True when one was added.

    Runs after a verification failure, at most once per run. The portal's own
    certificate is read unverified, but only to find out which intermediate it
    names; that intermediate must come from a known CA host and must chain to
    a root already trusted here before it is used or saved.
    """
    global _healed
    if _healed:
        return False
    _healed = True
    try:
        host = urllib.parse.urlsplit(SITE).hostname
        url = aia_url(ssl.get_server_certificate((host, 443), timeout=20))
        if not url:
            print("warn: certificate chain broken and no usable CA Issuers address", file=sys.stderr)
            return False
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            raw = r.read(AIA_MAX + 1)
        if len(raw) > AIA_MAX:
            print("warn: intermediate from", url, "is too large", file=sys.stderr)
            return False
        pem = raw.decode("ascii") if raw.lstrip().startswith(b"-----BEGIN") else ssl.DER_cert_to_PEM_cert(raw)
        if not chains_to_a_trusted_root(pem):
            print("warn: intermediate from", url, "does not chain to a trusted root; not used", file=sys.stderr)
            return False
        _ctx.load_verify_locations(cadata=pem)
    except Exception as e:
        print("warn: could not repair the certificate chain:", e, file=sys.stderr)
        return False
    print("certificate chain repaired with", url)
    try:
        CHAIN_AUTO.write_text(pem)
    except OSError as e:  # the next run fetches it again; nothing is lost
        print("warn: could not save", CHAIN_AUTO.name, e, file=sys.stderr)
    return True


def get(url, data=None, headers=None, timeout=40):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        broken_chain = isinstance(e.reason, ssl.SSLCertVerificationError) and url.startswith(SITE + "/")
        if not (broken_chain and heal_chain()):
            raise
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
        return r.read().decode("utf-8", "replace")


def aura_context():
    """fwuid + app marker from the home page's bootstrap URL (URL-encoded JSON)."""
    html = get(SITE + "/housing/s/")
    m = re.search(r"fwuid%22%3A%22([^%]+)%22", html)
    a = re.search(r"APPLICATION%40markup%3A%2F%2Fsiteforce%3AcommunityApp%22%3A%22([^%]+)%22", html)
    if not (m and a):
        raise SystemExit("could not find fwuid/app marker on the portal home page")
    return json.dumps({"mode": "PROD", "fwuid": m.group(1), "app": "siteforce:communityApp",
                       "loaded": {"APPLICATION@markup://siteforce:communityApp": a.group(1)},
                       "dn": [], "globals": {}, "uad": False})


def aura(ctx, action, page_uri="/housing/s/"):
    body = urllib.parse.urlencode({"message": json.dumps({"actions": [action]}), "aura.context": ctx,
                                   "aura.pageURI": page_uri, "aura.token": "null"}).encode()
    txt = get(SITE + "/housing/s/sfsites/aura?r=1&aura.ApexAction.execute=1", data=body,
              headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                       "Referer": SITE + "/housing/s/"})
    d = json.loads(txt)
    if d.get("exceptionEvent"):
        raise RuntimeError("aura exception: " + str(d.get("exceptionMessage"))[:300])
    act = d["actions"][0]
    if act.get("state") != "SUCCESS":
        raise RuntimeError("aura action %s: %s" % (act.get("state"), json.dumps(act.get("error"))[:300]))
    rv = act.get("returnValue")
    if isinstance(rv, dict) and "returnValue" in rv:
        rv = rv["returnValue"]
    if isinstance(rv, str):
        try:
            rv = json.loads(rv)
        except ValueError:
            pass
    return rv


def apex(cls, method, params, namespace=""):
    return {"id": "1;a", "descriptor": "aura://ApexActionController/ACTION$execute", "callingDescriptor": "UNKNOWN",
            "params": {"namespace": namespace, "classname": cls, "method": method, "params": params,
                       "cacheable": False, "isContinuation": False}}


def list_records(ctx):
    inp = {"RentLow": None, "RentHigh": None, "UnitType": None, "Income": None, "SelectedCity": None,
           "SelectedCounty": None, "SelectedZip": None, "LocationType": "City", "Project": None,
           "isHearingVisionChecked": False, "isMobilityChecked": False, "isRentalChecked": False,
           "isCoOpChecked": False, "selectedAmenities": [], "houseHoldSize": None}
    return aura(ctx, apex("HousingSearchV4", "getWaitListRecords", {"input": inp}))


def child_buildings(ctx, rid):
    rv = aura(ctx, apex("FlexRuntime", "doEncryptedDatasourceWithMetadata",
                        {"globalKey": "MCCWaitlistDetailsChildBuildings/HCR/1.0",
                         "scope": json.dumps({"Parent.Id": rid}), "actionElementId": None, "fileBased": False},
                        namespace="omnistudio"), page_uri=f"/housing/s/waitlist/{rid}/x")
    return [{"street": r.get("Building_Address__Street__s"), "city": r.get("Building_Address__City__s"),
             "zip": r.get("Building_Address__PostalCode__s")} for r in (rv or []) if isinstance(r, dict)]


def extract(ctx, rid):
    ds = {"type": "DataRaptor", "value": {"dsDelay": "", "bundleType": "", "inputMap": json.dumps({"Id": rid}),
          "jsonMap": json.dumps({"recordId": rid}), "resultVar": "", "bundleName": "MCCWaitlistListingExtract"},
          "orderBy": {"name": "", "isReverse": False}, "contextVariables": [], "vlocityAsync": False}
    rv = aura(ctx, apex("FlexRuntime", "handleData", {"dataSourceMap": json.dumps(ds)}, namespace="omnistudio"),
              page_uri=f"/housing/s/waitlist/{rid}/x")
    # the DataRaptor answer nests once or twice; find the first dict with an Id
    def find(o):
        if isinstance(o, dict):
            if o.get("Id") == rid or "ListingDescription" in o:
                return o
            for v in o.values():
                f = find(v)
                if f: return f
        elif isinstance(o, list):
            for v in o:
                f = find(v)
                if f: return f
        return None
    return find(rv) or {}


CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NYC_ZIP = re.compile(r"\b(1[0-1]\d{3}|10[0-4]\d{2}|11[0-6]\d{2})\b")
NYC_WORDS = re.compile(r"\b(bronx|brooklyn|queens|staten island|new york|manhattan|ny)\b", re.I)


def geocode(text):
    """lat/lng (+ BBL when GeoSearch answers). GeoSearch is NYC Planning's free
    geocoder and returns the BBL outright, but it 503s for stretches; the
    Census geocoder is the fallback for coordinates."""
    try:
        d = json.loads(get(GEOSEARCH + "?" + urllib.parse.urlencode({"text": text, "size": 1}), timeout=15))
        f = (d.get("features") or [None])[0]
        if f:
            lng, lat = f["geometry"]["coordinates"]
            p = f.get("properties", {})
            bbl = ((p.get("addendum") or {}).get("pad") or {}).get("bbl") or p.get("pad_bbl")
            return {"lat": round(lat, 6), "lng": round(lng, 6), "bbl": str(bbl) if bbl else None}
    except Exception:
        pass
    try:
        d = json.loads(get(CENSUS + "?" + urllib.parse.urlencode({"address": text, "benchmark": "Public_AR_Current", "format": "json"}), timeout=25))
        m = (d.get("result", {}).get("addressMatches") or [None])[0]
        if m:
            return {"lat": round(m["coordinates"]["y"], 6), "lng": round(m["coordinates"]["x"], 6), "bbl": None}
    except Exception as e:
        print("  geocode failed:", text[:60], e, file=sys.stderr)
    return None


def clean_mailing(s):
    """A Mitchell-Lama 'mail your application to' line, reduced to something a
    geocoder can place: drop 'Suite …', 'c/o …', sentences of instructions."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) > 120 or not re.search(r"\d", s):
        return None
    s = re.sub(r"^(.*?(Corp|Corporation|Inc|LLC|Associates|Housing Company|Management)\.?),\s*", "", s)
    s = re.sub(r",?\s*(Suite|Ste\.?|Room|Rm\.?|Floor|Fl\.?|#)\s*[A-Za-z0-9-]+", "", s)
    s = s.replace(" - ", ", ")
    return s if (NYC_ZIP.search(s) or NYC_WORDS.search(s)) else None


def money(s):
    try:
        return int(re.sub(r"[^\d]", "", str(s))) or None
    except ValueError:
        return None


def main():
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else DATA / "hcr.json"
    ctx = aura_context()
    recs = list_records(ctx)
    nyc = [r for r in recs if r.get("County", "").split(" (")[0] in COUNTY_TO_BORO]
    print(f"{len(recs)} records statewide, {len(nyc)} in NYC")
    # --incremental: the list call above is ONE request and carries the status
    # and deadline of every record. Reuse the stored detail (buildings,
    # incomes, phone, description — ~2 requests + geocoding per record) for
    # anything already in the output with the same status, and fetch only what
    # is new or changed. That is what lets the hourly cron exist: ~1 request an
    # hour instead of ~110, and a lottery that opens at noon is in hcr.json —
    # and in the borough alerts — within the hour rather than tomorrow.
    keep = {}
    if "--incremental" in sys.argv:
        try:
            for l in json.loads(out.read_text()).get("listings") or []:
                keep[l["id"]] = l
        except (OSError, ValueError, KeyError):
            keep = {}
        print(f"incremental: {len(keep)} stored records")
    try:
        blds_all = json.load(open(DATA / "buildings.min.json"))
        addr_idx = {b: build_index([x for x in blds_all if x["b"] == b]) for b in COUNTY_TO_BORO.values()}
        dhcr_bbls = {x["bbl"] for x in blds_all}
    except Exception as e:
        print("warn: no DHCR index:", e, file=sys.stderr); addr_idx, dhcr_bbls = {}, set()
    listings = []
    for r in nyc:
        rid = r["Id"]
        old = keep.get(rid)
        if old and old.get("status") == r.get("Status"):
            old = dict(old, name=r.get("ProjectName") or old.get("name"),
                       due=r.get("ApplicationEndDate") or old.get("due"))
            listings.append(old)
            continue
        time.sleep(PAUSE)
        try:
            blds = child_buildings(ctx, rid)
        except Exception as e:
            print("  buildings failed", rid, e, file=sys.stderr); blds = []
        time.sleep(PAUSE)
        try:
            ex = extract(ctx, rid)
        except Exception as e:
            print("  extract failed", rid, e, file=sys.stderr); ex = {}
        boro = COUNTY_TO_BORO[r["County"].split(" (")[0]]
        approx = False
        if not blds and ex.get("MailOrInPerson"):
            # Mitchell-Lama waitlists list only where to mail the application —
            # usually the development's own office. Use it when it is a real NYC
            # street address, and say so.
            m = clean_mailing(ex["MailOrInPerson"])
            if m:
                blds = [{"street": m, "city": "", "zip": ""}]
                approx = True
        geo_blds = []
        for b in blds:
            q = ", ".join(x for x in [b.get("street"), b.get("city") or r["County"].split(" (")[0], "NY", b.get("zip")] if x)
            time.sleep(0.3)
            g = geocode(q)
            # BBL: GeoSearch's if it gave one, else the DHCR register by normalized
            # address — a hit means this lottery is IN a rent-stabilized building.
            bbl = (g or {}).get("bbl")
            if bbl and bbl not in dhcr_bbls:
                bbl = None
            if not bbl and not approx and b.get("street"):
                bbl = addr_idx.get(boro, {}).get(normalize_addr(b["street"]))
            row = {"street": b.get("street"), "zip": b.get("zip") or None, "bbl": bbl}
            if g:
                row.update({"lat": g["lat"], "lng": g["lng"]})
            geo_blds.append(row)
        kind = "Mitchell-Lama Waitlist" if (r.get("IsMitchellLama") or "Mitchell" in str(ex.get("Type", ""))) else r.get("Type")
        listings.append({
            "id": rid, "name": r.get("ProjectName") or ex.get("Name"), "kind": kind, "status": r.get("Status"),
            "ptype": ex.get("ProjectType") or "Rental", "boro": boro, "county": r.get("County"),
            # Salesforce hands some incomes back as floats; the app decodes Int
            "min_income": (lambda v: int(round(v)) if isinstance(v, (int, float)) else None)(r.get("MinimumIncome") or money(ex.get("MinIncome"))),
            "max_income": (lambda v: int(round(v)) if isinstance(v, (int, float)) else None)(r.get("MaximumIncome") or money(ex.get("MaxIncome"))),
            "due": r.get("ApplicationEndDate"), "fee": money(ex.get("ApplicationFee")),
            "phone": ex.get("MainContactPhone") or None,
            "url": f"{SITE}/housing/s/waitlist/{rid}/detail",
            "info": ex.get("MoreInformation") or None,
            "desc": re.sub(r"\s+", " ", str(ex.get("ListingDescription") or ""))[:400] or None,
            "image": r.get("Image") if r.get("HasImage") else None,
            "senior": bool(r.get("seniorLabel")), "accessible": bool(r.get("isAccessibleUnit")),
            "approx": approx, "buildings": geo_blds,
        })
        print(f"  {r.get('ProjectName')!s:40.40} {kind:22} {r.get('Status'):6} buildings={len(geo_blds)}{' (approx)' if approx else ''}")
    now = int(time.time())
    out.write_text(json.dumps({"updated": now, "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now)),
                               "count": len(listings), "listings": listings}, indent=0, ensure_ascii=False))
    n_b = sum(len(l["buildings"]) for l in listings); n_geo = sum(1 for l in listings for b in l["buildings"] if b.get("lat"))
    n_bbl = sum(1 for l in listings for b in l["buildings"] if b.get("bbl"))
    print(f"wrote {out}: {len(listings)} listings, {n_b} buildings, {n_geo} geocoded, {n_bbl} with a BBL")


if __name__ == "__main__":
    main()
