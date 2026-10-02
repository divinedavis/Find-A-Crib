#!/usr/bin/env python3
"""Did Google actually READ the sitemaps — and which shards did it never open?

Why this exists
---------------
2026-10-02 is the morning the gap became the most important unmeasured thing on
this site. The index census has, for 41 consecutive days, reported every one of
the 60 /sf/, /la/ and /dc/ hub URLs it samples as "URL is unknown to Google",
and /la/ and /dc/ themselves with them. Those two URLs are:

  * listed in sitemap-main.xml at priority 0.9, inside the sitemap index,
  * linked as plain static <a href> from the header nav, the overflow menu AND
    the footer prose of the homepage — verified against the served bytes, not
    assumed: all three occurrences sit outside every <script> block,
  * carrying a self-referencing canonical and <meta name="robots"
    content="index,follow">,
  * on a homepage Googlebot fetched on 2026-10-02, the same morning,

and Google says it has never heard of them. Every previous run read that as
site-level crawl rationing, and that may well be what it is. But the whole
inference rests on an assumption NOTHING on this box has ever checked: that
Google read the sitemap shard those URLs live in. growth/indexstatus.py builds
its cohort from `sitemap_urls(docroot)` — the LOCAL files — so "unknown to
Google" is measured against what WE published, never against what Google
downloaded. If sitemap-la.xml has never been fetched, "unknown" is fully
explained, it is a different problem from crawl rationing, and it is fixable.
If it HAS been fetched and Google read 20 URLs out of it, then rationing is
confirmed by elimination rather than by assumption, and the submission class of
lever is closed on evidence.

Those two readings call for opposite work, and no number in this repo tells them
apart. This asks Google directly: the Search Console Sitemaps API reports, per
sitemap, when it was last submitted, when Google last DOWNLOADED it, how many
URLs Google read out of it, and whether it parsed with errors or warnings.

What it deliberately does NOT report
------------------------------------
`contents[].indexed` is in the API response and is not used anywhere here. That
counter has been deprecated for years and returns 0 for every property, so
surfacing it would put a hard zero next to the word "indexed" in a report whose
entire subject is indexing. A number that is always 0 is not a measurement, and
on this site a false zero is worse than a missing one.

What `ok` means
---------------
`ok` is set explicitly on EVERY exit path, including the success path — the
2026-07-28 lesson, where outreach.run() omitted it and the report announced a
healthy job as "DID NOT RUN - unknown error".

`ok` is False only for a real defect, in one of three shapes:

  * the call could not be made or failed (no credentials, auth, HTTP, bad JSON),
  * a shard the live sitemap index advertises is UNKNOWN to Search Console,
  * Search Console reports parse errors against a shard.

A shard that is known, parsed clean and simply has not been re-downloaded
lately is reported with its age and does NOT fail: download cadence is Google's
decision, and an audit that goes permanently red on somebody else's schedule
carries no information. The STALE_DAYS line names it instead.

Runs on the droplet only: it needs the same Search Console service-account key
growth/indexstatus.py uses, and the same read-only scope. No new secret.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import ledger

SITE_URL = "https://findacrib.com/"
SITEMAPS_API = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
                + urllib.parse.quote(SITE_URL, safe="") + "/sitemaps")

# Days since Google last downloaded a shard before this names it in the detail
# line. Not a failure — see the docstring. Two weeks is chosen against this
# site's own cadence rather than as a round number: the growth build rewrites
# sitemap-daily.xml nightly and IndexNow is pinged nightly, so a fortnight
# without a re-download is Google declining an invitation it keeps receiving.
STALE_DAYS = 14

# Shards named outright in the detail line, worst first, as indexstatus caps
# evicted_urls and t_frozen_pages caps frozen_urls. A detail line that lists
# forty shard names buries the one that matters.
NAME_CAP = 10

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def _int(v):
    """The v3 API returns int64 fields as JSON STRINGS ("4084", not 4084).

    Coerced here rather than at each use site, because `int(v) > 0` on the
    string "0" is a TypeError and `v > 0` on it is silently always True.
    """
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _date(v):
    """The date half of an RFC3339 timestamp, or None. Never raises."""
    if not v:
        return None
    s = str(v)
    return s[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s) else None


def _age_days(datestr, today=None):
    """Whole days between `datestr` and today, or None when undatable."""
    import datetime
    if not datestr:
        return None
    try:
        d = datetime.date.fromisoformat(datestr)
    except ValueError:
        return None
    t = datetime.date.fromisoformat(today or ledger.today())
    return (t - d).days


def local_shards(docroot):
    """{shard filename: URL count} from the live sitemap index, plus the index.

    Reads the same files growth/indexstatus.py:sitemap_urls() reads, with the
    same containment rule: a <loc> in the index names a file, and this only ever
    opens a name matching sitemap-<slug>.xml inside the docroot. The index is
    web-served and generated, but it must not be able to choose a path.

    Returns ({name: n_urls}, index_present). An empty mapping with
    index_present False is a bare checkout, not a defect.
    """
    index = os.path.join(docroot, "sitemap.xml")
    try:
        with open(index) as f:
            locs = _LOC.findall(f.read())
    except OSError:
        return {}, False
    out = {}
    for loc in locs:
        name = os.path.basename(urllib.parse.urlparse(loc).path)
        if not re.fullmatch(r"sitemap-[A-Za-z0-9_-]+\.xml", name):
            continue
        try:
            with open(os.path.join(docroot, name)) as f:
                body = f.read()
        except OSError:
            # Advertised in the index and absent from the docroot: a 404 for
            # Googlebot. Recorded as 0 URLs rather than skipped, so the shard
            # still shows up in the comparison below instead of vanishing.
            out[name] = 0
            continue
        out[name] = len(_LOC.findall(body))
    return out, True


def fetch(token, timeout=30):
    """sitemaps.list for the property. Returns (list_of_sitemaps, error_string)."""
    req = urllib.request.Request(
        SITEMAPS_API, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if not isinstance(payload, dict):
        return None, "response was not a JSON object"
    # An empty property legitimately returns {} with no "sitemap" key. That is
    # a finding (nothing submitted at all), not a malformed response, so it
    # comes back as an empty list rather than an error.
    return payload.get("sitemap") or [], None


def _shard_name(path):
    return os.path.basename(urllib.parse.urlparse(str(path)).path)


def collect(docroot):
    """Read Google's own view of our sitemaps and fold it into the ledger.

    Never raises: a measurement job must not be the reason the night's other
    measurements go unrecorded.
    """
    today = ledger.today()
    local, have_index = local_shards(docroot)
    if not have_index:
        detail = (f"no sitemap index readable at {os.path.join(docroot, 'sitemap.xml')} "
                  f"— this is a bare checkout rather than a deployed docroot, so "
                  f"there is nothing to compare Google's view against")
        out = {"ok": False, "detail": detail, "shards_live": 0, "shards_known": 0}
        ledger.write_last_run("sitemapstatus", out)
        return out

    try:
        import seo_search_console as sc
        token = sc.access_token(sc.load_key())
    except SystemExit as e:                      # load_key() exits when unset
        detail = f"no Search Console credentials: {e}"
        out = {"ok": False, "detail": detail, "shards_live": len(local),
               "shards_known": 0}
        ledger.write_last_run("sitemapstatus", out)
        return out
    except Exception as e:
        detail = f"Search Console auth failed: {type(e).__name__}: {e}"
        out = {"ok": False, "detail": detail, "shards_live": len(local),
               "shards_known": 0}
        ledger.write_last_run("sitemapstatus", out)
        return out

    sitemaps, err = fetch(token)
    if err:
        detail = f"sitemaps.list failed: {err}"
        out = {"ok": False, "detail": detail, "shards_live": len(local),
               "shards_known": 0}
        ledger.write_last_run("sitemapstatus", out)
        return out

    # ---- Google's side, keyed by filename so it joins to the local side.
    # The index entry (sitemap.xml) is held separately: it is a sitemaps-index
    # rather than a shard, its `contents` counts the whole property, and adding
    # it to the shard totals would double-count every URL on the site.
    seen, index_rec = {}, None
    for s in sitemaps:
        name = _shard_name(s.get("path"))
        rec = {
            "downloaded": _date(s.get("lastDownloaded")),
            "submitted_at": _date(s.get("lastSubmitted")),
            "pending": bool(s.get("isPending")),
            "errors": _int(s.get("errors")),
            "warnings": _int(s.get("warnings")),
            # Sum across content types (web, image, video). `indexed` is
            # deliberately not read — see the module docstring.
            "urls_read": sum(_int(c.get("submitted"))
                             for c in (s.get("contents") or [])),
        }
        if s.get("isSitemapsIndex") or name == "sitemap.xml":
            index_rec = rec
            continue
        seen[name] = rec

    shards = {}
    for name in sorted(local):
        rec = dict(seen.get(name) or {})
        rec["urls_local"] = local[name]
        rec["known"] = name in seen
        if rec["known"]:
            rec["age_days"] = _age_days(rec.get("downloaded"), today)
        shards[name] = rec
    # A sitemap Search Console holds that our index no longer advertises. Left
    # over from an older build, still being re-downloaded, still spending
    # whatever attention this domain gets. Named, not failed: deleting a
    # submitted sitemap is the owner's call in the Search Console UI.
    orphaned = sorted(n for n in seen if n not in local)

    known = [n for n, r in shards.items() if r["known"]]
    unknown = sorted(n for n, r in shards.items() if not r["known"])
    never = sorted(n for n in known if not shards[n].get("downloaded"))
    errored = sorted(n for n in known if shards[n].get("errors"))
    warned = sorted(n for n in known if shards[n].get("warnings"))
    ages = {n: shards[n]["age_days"] for n in known
            if shards[n].get("age_days") is not None}
    stale = sorted((a, n) for n, a in ages.items() if a >= STALE_DAYS)
    urls_read = sum(shards[n].get("urls_read") or 0 for n in known)
    urls_local = sum(local.values())

    # ---- series. Levels, one row per metric per night, same shape as the
    # index census: these are read as a trend and the question "did a shard
    # that was being downloaded stop being downloaded" needs the history.
    for metric, value in (
            ("sitemap_shards_live", len(local)),
            ("sitemap_shards_known", len(known)),
            ("sitemap_shards_unknown", len(unknown)),
            ("sitemap_shards_never_downloaded", len(never)),
            ("sitemap_shards_stale", len(stale)),
            ("sitemap_shards_orphaned", len(orphaned)),
            ("sitemap_shards_errored", len(errored)),
            ("sitemap_urls_read", urls_read),
            ("sitemap_urls_local", urls_local)):
        ledger.record_result(today, "__site__", metric, value)
    # Held back rather than written as 0 when there is nothing to date, under
    # the same rule the census block states: an absent day is honest, a zero is
    # a claim. "Google's oldest sitemap download is 0 days old" would be a
    # claim that every shard was downloaded today.
    if ages:
        ledger.record_result(today, "__site__", "sitemap_oldest_download_days",
                             max(ages.values()))
        ledger.record_result(today, "__site__", "sitemap_newest_download_days",
                             min(ages.values()))

    # ---- the detail line. Worst first, because the first clause is what gets
    # quoted into a journal entry.
    bits = [f"{len(known)} of {len(local)} live sitemap shards are known to Search "
            f"Console; Google has read {urls_read:,} URLs out of them against "
            f"{urls_local:,} listed locally"]
    if unknown:
        bits.append("in the live sitemap index and NEVER SUBMITTED OR NEVER PROCESSED "
                    "by Search Console: " + ", ".join(unknown[:NAME_CAP])
                    + (f", +{len(unknown) - NAME_CAP} more" if len(unknown) > NAME_CAP else ""))
    if never:
        bits.append("known but NEVER DOWNLOADED: " + ", ".join(never[:NAME_CAP])
                    + (f", +{len(never) - NAME_CAP} more" if len(never) > NAME_CAP else ""))
    if errored:
        bits.append("parse ERRORS: " + ", ".join(
            f"{n} ({shards[n]['errors']})" for n in errored[:NAME_CAP]))
    if warned:
        bits.append("parse warnings: " + ", ".join(
            f"{n} ({shards[n]['warnings']})" for n in warned[:NAME_CAP]))
    if stale:
        bits.append(f"not re-downloaded in {STALE_DAYS}+ days, oldest first: " + ", ".join(
            f"{n} ({a}d)" for a, n in stale[:NAME_CAP])
            + (f", +{len(stale) - NAME_CAP} more" if len(stale) > NAME_CAP else ""))
    if orphaned:
        bits.append("held by Search Console and no longer in our index: "
                    + ", ".join(orphaned[:NAME_CAP]))
    if index_rec:
        bits.append(f"the index itself was last downloaded "
                    f"{index_rec.get('downloaded') or 'NEVER'}")
    # Only ever say "every shard" when every shard really was read.
    if known and not unknown and not never and not errored:
        bits.append("every live shard has been downloaded at least once")

    out = {
        "ok": not (unknown or errored),
        "detail": " — ".join(bits),
        "shards_live": len(local),
        "shards_known": len(known),
        "shards_unknown": unknown,
        "shards_never_downloaded": never,
        "shards_errored": errored,
        "shards_stale": [n for _a, n in stale],
        "shards_orphaned": orphaned,
        "urls_read": urls_read,
        "urls_local": urls_local,
        "oldest_download_days": max(ages.values()) if ages else None,
        "index_downloaded": (index_rec or {}).get("downloaded"),
        # The per-shard join, so a review reading last_run.json out of git can
        # answer "which shard holds /la/, and when did Google last open it"
        # without the API and without a droplet.
        "shards": shards,
    }
    ledger.write_last_run("sitemapstatus", out)
    return out
