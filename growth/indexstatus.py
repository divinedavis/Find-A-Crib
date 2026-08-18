#!/usr/bin/env python3
"""Measured index coverage — is the 47k-page corpus actually *indexed*?

Why this exists
---------------
Every review since 2026-07-27 has gated its strategy on `gsc_serving_pages` —
the number of distinct URLs that earned a Search Console impression in the
window — and has read it as an *indexing* number. searchconsole.py's own
docstring calls it "the only honest read on whether the 47k-page corpus is
actually indexed". That reading is wrong, and it has been driving decisions for
three weeks.

An impression requires two independent things: the page is in Google's index,
AND somebody typed a query it could answer. On a corpus of 47,165 single-address
pages the second one is the binding constraint for almost every page — nobody
searches most addresses in a given week. So "63 of ~47,600 pages served" is
consistent with 63 indexed pages and with 47,000 indexed pages, and the whole
question of what to do next turns on which it is:

  * few pages indexed  -> the constraint is crawl/index acceptance, and
                          consolidating the corpus (T027) is the move.
  * many pages indexed -> the constraint is search demand, publishing more
                          address pages cannot help, and the effort belongs on
                          the query families that have volume.

Nothing in the repo could tell those apart. This can. The Search Console URL
Inspection API returns Google's own coverage state for a URL — "Submitted and
indexed", "Crawled - currently not indexed", "Discovered - currently not
indexed", "Excluded by 'noindex' tag" and so on — which is the direct
measurement the serving count was standing in for.

How it is sampled
-----------------
The API allows 2,000 inspections/day per property, against ~47,600 published
pages, so the whole corpus cannot be measured and a *sample* has to be. Two
properties matter more than sample size:

  stable cohort   The same URLs are re-inspected over time, so a change in the
                  indexed rate is a change in Google's opinion and not a
                  different draw. The cohort persists in index_status.json;
                  URLs are only dropped when they leave the sitemaps, and only
                  topped up to the target size, in sha1 order so the top-up is
                  deterministic rather than build-order dependent.
  stratified      /building/ is 99% of the corpus but 0% of the interesting
                  question. Each page family gets its own quota and its own
                  reported rate, because "are the guides indexed" and "are the
                  address pages indexed" are different questions with different
                  answers and different consequences.

Each run inspects the DAILY_BUDGET cohort URLs whose reading is oldest, so the
cohort is fully refreshed every few days and every URL carries the date its
state was last read.

Output is public URLs and Google's public opinion of them — no PII — so
index_status.json is tracked in git and the cloud review agent can read it.

Runs on the droplet only: it needs the Search Console service-account key.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import ledger

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.join(HERE, "index_status.json")

sys.path.insert(0, os.path.dirname(HERE))

INSPECT_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
SITE_URL = "https://findacrib.com/"

# Per-family cohort quotas. /building/ dominates the corpus and gets the largest
# share, but not a proportional one: at 250 pages its indexed rate carries a
# ~±6pp 95% interval, which is far more precision than any decision here needs,
# and the remaining slots buy the first measurement this site has ever had of
# whether the hub and guide tiers are indexed at all. Those tiers have never
# earned a single impression across 224 pages of serving history, and that fact
# has two completely different explanations — not indexed, or indexed and
# outranked — which imply opposite next moves.
COHORT = {
    "building": 250,
    "neighborhood": 40,
    "zip": 40,
    "dc": 20,
    "la": 20,
    "sf": 20,
    "available": 15,
    "guide": 10,
    "borough": 10,
    "section8": 10,
    "brief": 10,
    "(root)": 10,
}
COHORT_TOTAL = sum(COHORT.values())

# Any published family not named above still gets sampled, at a token rate. The
# engine adds page families over time — a technique ships a new prefix and the
# sampler would otherwise be blind to it until somebody remembered to edit this
# dict, which is exactly the kind of silent gap this module exists to close.
DEFAULT_QUOTA = 5

# 2,000/day and 600/min are the per-property quotas. 100 keeps a wide margin for
# anything else that ever wants the API, refreshes the whole cohort in ~5 days,
# and costs about two minutes of wall clock at the pace set below.
DAILY_BUDGET = int(os.environ.get("GROWTH_INDEX_BUDGET", "100"))
PACE_SECONDS = 0.4        # ~150/min against a 600/min ceiling

# Google's coverageState strings are prose and have changed wording before, so
# match on the substring that carries the meaning rather than on equality.
_STATE_BUCKETS = (
    ("indexed", ("submitted and indexed", "indexed, not submitted")),
    ("crawled_not_indexed", ("crawled - currently not indexed",
                             "crawled — currently not indexed")),
    ("discovered_not_indexed", ("discovered - currently not indexed",
                                "discovered — currently not indexed")),
    # Google has no record of the URL at all — it is not merely un-indexed, it
    # has never been fetched. On 2026-08-17 this was 159 of the 198 URLs read
    # and every one of them was filed as "other", because this needle was
    # missing: the single most decision-relevant state the sampler has ever
    # measured was invisible under a bucket whose own comment says it means
    # "wording this module has not learned yet".
    #
    # Read it literally, and check the discriminator before building on it. The
    # state string alone is not proof a URL was never crawled — Google has been
    # observed relabelling long-known URLs "unknown" — but a never-fetched URL
    # also carries no lastCrawlTime and pageFetchState
    # PAGE_FETCH_STATE_UNSPECIFIED, and a relabelled one keeps its crawl time.
    # All 159 on 2026-08-17 had crawled=None and fetch unspecified; all 39
    # known URLs had a real crawl time and SUCCESSFUL. Re-check that split
    # before reading this bucket as "never discovered" again.
    ("unknown_to_google", ("unknown to google",)),
    ("duplicate", ("duplicate", "alternate page")),
    ("excluded_noindex", ("noindex",)),
    ("blocked", ("blocked", "robots.txt")),
    ("redirect", ("redirect",)),
    ("not_found", ("not found", "404", "soft 404")),
)

# The full vocabulary, in the order a human reads it: accepted first, then the
# three states that are the whole diagnosis — in reverse funnel order, indexed
# then crawled then discovered then never-seen — then the exclusions. Recorded
# as a dense daily series (zeros included) so a bucket that appears for the
# first time does not read as a jump from "missing" and a bucket that empties
# out is visibly zero rather than absent. `unknown` is Google returning no
# coverage state at all — an instrument condition, and not the same thing as
# `unknown_to_google`, which is Google's own answer about the URL; the report
# labels them "no state returned" and "unknown to Google" for that reason.
# `other` is wording this module has not learned yet, and a rising `other` is
# the signal that _STATE_BUCKETS needs a new needle.
BUCKETS = tuple(name for name, _ in _STATE_BUCKETS) + ("other", "unknown")


def bucket(coverage_state):
    """Collapse Google's prose coverage state into a stable, countable bucket."""
    s = (coverage_state or "").strip().lower()
    if not s:
        return "unknown"
    for name, needles in _STATE_BUCKETS:
        if any(n in s for n in needles):
            return name
    return "other"


def family(url):
    """The page family a URL belongs to — its first path segment.

    /dc/neighborhood/foo/ and /dc/ both read as "dc"; that is deliberate. The
    three non-NYC cities are each one publishing project and are worth counting
    as one, and separating a city's own landing page from its hubs would leave a
    stratum of size one.
    """
    path = urllib.parse.urlparse(url).path or "/"
    seg = path.strip("/").split("/")[0]
    return seg or "(root)"


# --------------------------------------------------------------- the sitemaps

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def sitemap_urls(docroot):
    """Every URL the site has told Google about, read from the docroot sitemaps.

    The sitemap index is the right source rather than a filesystem walk: it is
    exactly the set Google was asked to crawl, it already includes the daily
    growth engine's own pages (sitemap-daily.xml), and it excludes anything in
    the docroot that is not a published page — the app bundle, the data blobs,
    the scraper's working files.
    """
    index = os.path.join(docroot, "sitemap.xml")
    try:
        with open(index) as f:
            shards = _LOC.findall(f.read())
    except OSError:
        return []
    out, seen = [], set()
    for shard in shards:
        name = os.path.basename(urllib.parse.urlparse(shard).path)
        # Only ever open a file inside the docroot: the sitemap index is
        # generated, but it is also web-served and there is no reason for this
        # to be able to read a path a <loc> chose.
        if not re.fullmatch(r"sitemap-[A-Za-z0-9_-]+\.xml", name):
            continue
        try:
            with open(os.path.join(docroot, name)) as f:
                body = f.read()
        except OSError:
            continue
        for url in _LOC.findall(body):
            if url.startswith(SITE_URL.rstrip("/")) and url not in seen:
                seen.add(url)
                out.append(url)
    return out


# ------------------------------------------------------------------ the cohort

def _load():
    try:
        with open(STATUS_PATH) as f:
            doc = json.load(f)
    except Exception:
        doc = {}
    doc.setdefault("cohort", {})
    return doc


def _save(doc):
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, STATUS_PATH)


def _rank(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def reconcile(cohort, published):
    """Drop cohort URLs that are no longer published, then top each family back
    up to its quota. Returns (cohort, dropped, added).

    Existing members are never evicted to make room for a lower-hashing
    newcomer: the point of the cohort is that today's rate and last week's rate
    describe the same pages. It only ever shrinks by de-publication.
    """
    live = set(published)
    dropped = [u for u in cohort if u not in live]
    for u in dropped:
        cohort.pop(u, None)

    have = {}
    for u in cohort:
        have[family(u)] = have.get(family(u), 0) + 1
    by_family = {}
    for u in published:
        by_family.setdefault(family(u), []).append(u)

    added = []
    for fam in sorted(set(COHORT) | set(by_family)):
        quota = COHORT.get(fam, DEFAULT_QUOTA)
        need = quota - have.get(fam, 0)
        if need <= 0:
            continue
        for u in sorted(by_family.get(fam, []), key=_rank):
            if need <= 0:
                break
            if u not in cohort:
                cohort[u] = {"family": fam}
                added.append(u)
                need -= 1
    return cohort, dropped, added


def _due(cohort, budget):
    """The `budget` cohort URLs to inspect tonight: oldest reading first *within
    each family*, and the families interleaved in proportion to their size.

    A single global sort by (checked, sha1) looks equivalent and is not, because
    the two sha1 orderings compose badly. reconcile() tops a family up by taking
    the `quota` lowest-hashing candidates, so /building/ holds the 250 lowest
    hashes out of 47,165 URLs — all of them tiny — while /guide/ holds all 7 of
    its candidates, spread across the whole hash range. Sorted globally, every
    /building/ member therefore sorts ahead of almost everything else, and the
    larger the candidate pool the further forward the family lands.

    That is what happened on 2026-08-16 and 08-17: 196 of the first 198 URLs
    read were /building/, with 1 /neighborhood/, 1 /zip/ and nothing at all from
    /guide/, /section8/, /brief/ or the three city tiers — the strata the
    stratified cohort exists to measure, and the ones whose "indexed vs indexed
    and outranked" question had been open for weeks. The rate was right; the
    order silently made it a /building/-only rate for the first four nights.

    Proportional interleaving fixes it: a family with 250 of 388 cohort URLs
    still gets ~64 of a 100-URL budget, so the whole cohort still refreshes in
    the same ~4 nights, but every family is sampled on the FIRST night. The key
    is each member's fractional position in its own family, so families are
    consumed at equal relative speed regardless of size.

    Three parts to the sort key, and each is load-bearing:

      checked   Staleness first, so this is still honestly "oldest reading
                first" and a family that errored out or was added late catches
                up on its own. Never-read URLs sort ahead of every read one.
      slot      The member's fractional position in its family — EXCEPT that
                each family's oldest member is pinned to the front. Without the
                pin, a family smaller than cohort/budget members starves
                outright: at 100 of 388 the cut falls near 0.26, so /dc/, /la/
                and /sf/ (2 URLs each) and /guide/ (7) would sit at 0.5 and 0.14
                and never be reached at all. The pin costs one slot per family —
                sixteen of a hundred — and buys first-night coverage of every
                stratum, which is the entire point of stratifying.
      fam,rank  Deterministic tie-breaks, so two runs over the same cohort
                inspect the same URLs in the same order.
    """
    fams = {}
    for u in cohort:
        fams.setdefault(cohort[u].get("family") or family(u), []).append(u)
    order = []
    for fam, members in fams.items():
        members.sort(key=lambda u: (cohort[u].get("checked") or "", _rank(u)))
        n = len(members)
        for i, u in enumerate(members):
            slot = 0.0 if i == 0 else (i + 1.0) / n
            order.append((cohort[u].get("checked") or "", slot, fam, _rank(u), u))
    order.sort()
    return [t[-1] for t in order[:budget]]


# ------------------------------------------------------------------- the API

def inspect(token, url, timeout=30):
    """One URL Inspection call. Returns (record, error_string)."""
    body = json.dumps({"inspectionUrl": url, "siteUrl": SITE_URL,
                       "languageCode": "en-US"}).encode()
    req = urllib.request.Request(
        INSPECT_API, data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:                       # network, timeout, bad JSON
        return None, f"{type(e).__name__}: {e}"
    idx = ((payload.get("inspectionResult") or {}).get("indexStatusResult") or {})
    state = idx.get("coverageState")
    rec = {
        "state": state,
        "bucket": bucket(state),
        "verdict": idx.get("verdict"),
        "crawled": (idx.get("lastCrawlTime") or "")[:10] or None,
        "fetch": idx.get("pageFetchState"),
        "checked": ledger.today(),
    }
    # A Google-chosen canonical that is not the URL we submitted is the quiet
    # failure mode for a large templated corpus — the page is "indexed" under
    # somebody else's URL and will never serve under its own. Record it only
    # when it actually differs, so the common case costs no bytes.
    google_canonical = idx.get("googleCanonical")
    if google_canonical and google_canonical.rstrip("/") != url.rstrip("/"):
        rec["google_canonical"] = google_canonical
    return rec, None


# ------------------------------------------------------------------ summarise

def summarise(cohort):
    """Per-family and overall counts over whatever has been read so far.

    The bucket is RE-DERIVED from the stored raw `state` string on every call
    rather than read back from `rec["bucket"]`, and that is load-bearing.
    inspect() stamps a bucket at read time, so a URL keeps whatever vocabulary
    bucket() knew on the night it was inspected until it happens to be
    re-inspected — four nights later, at the current rotation. On 2026-08-18
    that meant 159 of 298 readings still carried `other` while their own stored
    state read, literally, "URL is unknown to Google": bucket() learned that
    wording on 08-17 and the backlog could not benefit from it. The daily series
    therefore reported unknown_to_google 74 / other 159 when the truth was 233 /
    0 — and `other` is documented to mean "wording this module has not learned
    yet, add a needle", so the report was standing there asking the next review
    to go find a needle that already existed.

    Re-deriving makes every future bucket() improvement retroactive across the
    whole cohort the moment it lands, which is the only behaviour that lets
    `other` keep meaning what its comment says it means. The raw state is
    already stored on every record, so this costs nothing but the lookup.
    """
    fams = {}
    for url, rec in cohort.items():
        fam = rec.get("family") or family(url)
        f = fams.setdefault(fam, {"cohort": 0, "read": 0, "indexed": 0,
                                  "fetched": 0, "buckets": {},
                                  "wrong_canonical": 0})
        f["cohort"] += 1
        # `checked` is stamped by inspect() on every successful call and by
        # nothing else, so it — not the presence of a bucket or a state — is
        # what separates "read" from "still waiting its turn". A URL Google
        # answers about with no coverageState at all is read, and buckets as
        # `unknown`.
        if not (rec.get("checked") or rec.get("bucket")):
            continue
        b = bucket(rec.get("state"))
        f["read"] += 1
        f["buckets"][b] = f["buckets"].get(b, 0) + 1
        if b == "indexed":
            f["indexed"] += 1
        # Has Google ever fetched this URL? lastCrawlTime is the direct
        # evidence and the discriminator the unknown_to_google comment names,
        # so it is used here rather than inferring it from the bucket. On
        # 2026-08-18 the two agreed exactly — all 233 unknown_to_google rows had
        # no crawl time, all 65 others had one — and if they ever disagree, the
        # crawl time is the fact and the coverage prose is the summary of it.
        if rec.get("crawled"):
            f["fetched"] += 1
        if rec.get("google_canonical"):
            f["wrong_canonical"] += 1
    for f in fams.values():
        f["indexed_pct"] = round(100.0 * f["indexed"] / f["read"], 1) if f["read"] else None
        f["fetched_pct"] = round(100.0 * f["fetched"] / f["read"], 1) if f["read"] else None
        f["accept_pct"] = (round(100.0 * f["indexed"] / f["fetched"], 1)
                           if f["fetched"] else None)
    total = {"cohort": sum(f["cohort"] for f in fams.values()),
             "read": sum(f["read"] for f in fams.values()),
             "indexed": sum(f["indexed"] for f in fams.values()),
             "fetched": sum(f["fetched"] for f in fams.values()),
             "wrong_canonical": sum(f["wrong_canonical"] for f in fams.values())}
    total["indexed_pct"] = (round(100.0 * total["indexed"] / total["read"], 1)
                            if total["read"] else None)
    # Discovery and acceptance are independent failures with opposite fixes, and
    # indexed_pct is their product — which is why three weeks of reviews read
    # "3.7% indexed" as one problem and argued about which one it was.
    #
    #   fetched_pct  did Google ever come and get the page? 21.8% on 2026-08-18.
    #                A discovery/crawl-budget number. Links and sitemaps move it;
    #                nothing about the page itself does, because nothing about
    #                the page has been seen.
    #   accept_pct   of the pages it did fetch, how many did it keep? 16.9% on
    #                2026-08-18 — 54 of 65 fetched URLs came back "crawled,
    #                currently not indexed". A quality/duplication judgement.
    #                Submitting more URLs cannot move it and consolidating might.
    #
    # Recorded separately so a change can be judged on the one it was aimed at:
    # a sitemap or linking fix that moves fetched_pct and leaves accept_pct flat
    # worked exactly as intended, and reading that as failure — or as success —
    # off the combined rate is a coin toss.
    total["fetched_pct"] = (round(100.0 * total["fetched"] / total["read"], 1)
                            if total["read"] else None)
    total["accept_pct"] = (round(100.0 * total["indexed"] / total["fetched"], 1)
                           if total["fetched"] else None)
    # The newest crawl date anywhere in the cohort: "is Googlebot still coming
    # at all", which no rate answers. A cohort whose newest crawl is a week old
    # is a different emergency from one that is crawled nightly and declined.
    crawls = [r.get("crawled") for r in cohort.values() if r.get("crawled")]
    total["last_crawl"] = max(crawls) if crawls else None
    # The site-wide state split. "3% indexed" says the corpus is not being
    # accepted; it does not say why, and the two dominant failure states imply
    # opposite work. "Discovered - currently not indexed" means Google knows the
    # URL and has not spent a crawl on it — a crawl-budget/priority problem, so
    # the move is to submit fewer, better-linked URLs. "Crawled - currently not
    # indexed" means it fetched the page and declined it — a quality/duplication
    # judgement, so the move is to consolidate or strengthen the pages
    # themselves. Publishing more addresses is wrong under both, but everything
    # after that diverges, so this split is recorded rather than left implicit
    # in the per-family "top non-indexed state".
    states = {b: 0 for b in BUCKETS}
    for f in fams.values():
        for b, n in (f.get("buckets") or {}).items():
            states[b] = states.get(b, 0) + n
    total["buckets"] = states
    return {"total": total, "by_family": fams}


# ---------------------------------------------------------------------- run

def collect(docroot, budget=None):
    """Inspect a slice of the cohort and fold the result into the ledger.

    Never raises: a measurement job must not be the reason the night's other
    measurements go unrecorded. Every exit path writes an explicit `ok` into the
    last_run record — the 2026-07-28 lesson, where outreach.run() omitted `ok`
    on success and the report announced a healthy job as "DID NOT RUN".
    """
    budget = DAILY_BUDGET if budget is None else budget
    doc = _load()
    cohort = doc["cohort"]

    published = sitemap_urls(docroot)
    if not published:
        detail = (f"no sitemap URLs readable under {docroot} — cannot tell which "
                  f"pages are published, so nothing was inspected")
        ledger.write_last_run("indexstatus", {"ok": False, "detail": detail,
                                              "inspected": 0})
        return {"ok": False, "detail": detail, "inspected": 0}

    cohort, dropped, added = reconcile(cohort, published)

    try:
        import seo_search_console as sc
        token = sc.access_token(sc.load_key())
    except SystemExit as e:                      # load_key() exits when unset
        detail = f"no Search Console credentials: {e}"
        ledger.write_last_run("indexstatus", {"ok": False, "detail": detail,
                                              "inspected": 0})
        return {"ok": False, "detail": detail, "inspected": 0}
    except Exception as e:
        detail = f"Search Console auth failed: {type(e).__name__}: {e}"
        ledger.write_last_run("indexstatus", {"ok": False, "detail": detail,
                                              "inspected": 0})
        return {"ok": False, "detail": detail, "inspected": 0}

    inspected, errors, first_error = 0, 0, None
    for url in _due(cohort, budget):
        rec, err = inspect(token, url)
        if err:
            errors += 1
            first_error = first_error or f"{url}: {err}"
            # 403 means the service account is not an owner or full user of the
            # property — every subsequent call will fail the same way, and 100
            # of them is a waste of two minutes and of the quota. 429 means the
            # daily quota is already gone. Both are "stop now", not "retry".
            if " 403" in err or " 429" in err:
                break
            if errors >= 10:
                break
            continue
        prev = cohort.get(url) or {}
        rec["family"] = prev.get("family") or family(url)
        # Keep the first date this URL was seen indexed. "When did Google accept
        # this page" is not recoverable afterwards and is the number that says
        # how long acceptance takes on this corpus.
        if rec["bucket"] == "indexed":
            rec["first_indexed"] = prev.get("first_indexed") or ledger.today()
        elif prev.get("first_indexed"):
            rec["first_indexed"] = prev["first_indexed"]
        cohort[url] = rec
        inspected += 1
        time.sleep(PACE_SECONDS)

    summary = summarise(cohort)
    doc["cohort"] = cohort
    doc["summary"] = summary
    doc["updated"] = ledger.today()
    doc["published_urls"] = len(published)
    _save(doc)

    today = ledger.today()
    tot = summary["total"]
    # Only record when the cohort actually holds readings. A denied or dead API
    # leaves read=0, and writing that into the series would put a hard zero on
    # the day — a measurement failure rendered as "nothing is indexed", which is
    # the same class of mistake as reporting a healthy job as "DID NOT RUN".
    # An absent day is honest; a zero is a claim.
    if tot["read"]:
        for metric, value in (("index_cohort", tot["cohort"]),
                              ("index_read", tot["read"]),
                              ("index_indexed", tot["indexed"]),
                              ("index_wrong_canonical", tot["wrong_canonical"]),
                              ("index_pct", tot["indexed_pct"]),
                              # The two halves index_pct multiplies together.
                              # See summarise(): a linking fix is judged on
                              # fetched_pct and a consolidation on accept_pct,
                              # and neither is legible in the combined rate.
                              ("index_fetched", tot["fetched"]),
                              ("index_fetched_pct", tot["fetched_pct"]),
                              ("index_accept_pct", tot["accept_pct"])):
            if value is not None:
                ledger.record_result(today, "__site__", metric, value)
        # index_status.json holds only the LATEST state per URL, so it can never
        # answer "did pages move from discovered to crawled to indexed after we
        # changed something" — the question any fix to a 3%-indexed corpus has
        # to be judged on. results.jsonl is the only append-only series here, so
        # the split goes in it, one metric per bucket.
        for b in BUCKETS:
            ledger.record_result(today, "__site__", f"index_state_{b}",
                                 tot["buckets"].get(b, 0))
        # The building corpus on its own, because it is 99% of the pages and the
        # one whose answer decides whether to publish more of them or fewer.
        bld = summary["by_family"].get("building") or {}
        if bld.get("indexed_pct") is not None:
            ledger.record_result(today, "__site__", "index_pct_building",
                                 bld["indexed_pct"])

    ok = inspected > 0 or not errors
    out = {"ok": ok, "inspected": inspected, "errors": errors,
           "cohort": tot["cohort"], "read": tot["read"],
           "indexed_pct": tot["indexed_pct"],
           # Both halves in last_run.json, because that file is what the cloud
           # review reads first and "21.8% ever fetched, 16.9% of those kept" is
           # the whole diagnosis in two numbers.
           "fetched_pct": tot["fetched_pct"],
           "accept_pct": tot["accept_pct"],
           "last_crawl": tot["last_crawl"],
           "published_urls": len(published),
           "added": len(added), "dropped": len(dropped),
           # last_run.json is committed nightly and is the first thing a review
           # reads. Carrying the split here means the diagnosis is legible from
           # `growth_daily.py status` alone, without opening the cohort file.
           "states": {b: n for b, n in tot["buckets"].items() if n}}
    if first_error:
        out["detail"] = (f"{errors} inspection(s) failed, first: {first_error}"
                         + ("" if " 403" not in first_error else
                            " — the Search Console service account must be an "
                            "owner or full user of the property to use the URL "
                            "Inspection API; a restricted user gets 403."))
    ledger.write_last_run("indexstatus", out)
    return out
