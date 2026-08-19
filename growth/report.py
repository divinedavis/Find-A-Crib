#!/usr/bin/env python3
"""The daily growth email: what ran, what it moved, and how far from the goals.

Deliberately blunt. If a technique did nothing, the report says it did nothing —
a growth loop that only reports good news is just a slower way of wasting money.

The report is described as emailkit blocks, never as markup, and emailkit
renders the HTML and the plain-text alternative from the same block list. That
is the reason there is no second text builder here: two builders drift, and the
text part is the one a screen reader and a spam filter actually read.
"""
import datetime
import html as _html
import json
import os
import statistics

from . import emailkit, keywords, ledger, review, searchconsole

# Pages published across NYC/SF/LA/DC. The gap between this and the pages that
# have ever earned an impression is the single biggest number in the report.
PUBLISHED_PAGES = 47600
DASHBOARD = "https://findacrib.com/dashboard"

# How many days the SEO corpus may go unwritten before the report says so.
# refresh_seo.sh is nightly, so 1 day old is normal and 2 is already a miss.
SEO_CORPUS_STALE_DAYS = 2

SITE = "https://findacrib.com"

# The email shows this many "waiting on you" candidates; the rest live on a
# standalone page so the report stays readable as the backlog grows.
WAITING_EMAIL_CAP = 5
WAITING_PAGE = "reports/waiting-on-you.html"


def _write_waiting_page(items):
    """Write the full 'waiting on you' list into the docroot and return its URL.

    noindex — it's an internal worklist, not content, and build_seo.py's
    sitemaps are built from an explicit URL list so it never enters them.
    Returns None when there is no docroot to write into (local runs), in which
    case the email falls back to showing everything rather than hiding items
    behind a link that doesn't exist.
    """
    root = os.environ.get("GROWTH_DOCROOT")
    if not root or not os.path.isdir(root):
        return None
    rows = []
    for t in items:
        notes = _html.escape((t.get("notes") or "").strip()).replace("\n", "<br>")
        rows.append(
            f'<article style="border-left:3px solid #d97706;background:#fffbeb;'
            f'border-radius:8px;padding:14px 16px;margin:0 0 12px">'
            f'<h2 style="margin:0 0 6px;font-size:16px;color:#b45309">'
            f'{_html.escape(t.get("id", ""))} {_html.escape(t.get("name", ""))}</h2>'
            f'<p style="margin:0;font-size:14px;line-height:1.55;color:#1a1f36">'
            f'{notes}</p></article>')
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex,nofollow">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Waiting on you — Find A Crib growth</title></head>'
        '<body style="margin:0;background:#f6f7f9;font-family:-apple-system,'
        'BlinkMacSystemFont,Segoe UI,Roboto,sans-serif">'
        '<main style="max-width:680px;margin:0 auto;padding:28px 16px">'
        '<h1 style="font-size:20px;color:#1a1f36">Waiting on you — '
        'these candidates cannot activate without a decision</h1>'
        f'<p style="font-size:13px;color:#6b7280">{len(items)} candidate(s) · '
        f'generated {ledger.today()} by the growth engine</p>'
        + "".join(rows) + "</main></body></html>")
    path = os.path.join(root, WAITING_PAGE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, path)
    return f"{SITE}/{WAITING_PAGE}"


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def _money(v):
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _pct(part, whole):
    try:
        return max(0.0, min(100.0, 100.0 * float(part) / float(whole)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _last(metric):
    s = ledger.series("__site__", metric)
    return s[-1][1] if s else None


def _index_summary():
    """The index-coverage summary, RECOMPUTED from the cohort, not read back.

    index_status.json carries both the per-URL cohort and a `summary` blob, and
    the blob is a cache written by whichever version of summarise() last ran on
    the droplet. Reading it back means every improvement to the counting — a new
    coverage-state needle, a new rate — shows up in the report a night late, and
    shows up as "—" in the meantime, which is indistinguishable from a stratum
    with nothing read yet. The cohort is the fact; the summary is a view of it,
    and it is cheap enough (a few hundred records) to take the view fresh.

    Returns None if the file cannot be read, so callers can tell "no data" from
    "data that summarises to nothing".
    """
    try:
        from . import indexstatus
        with open(indexstatus.STATUS_PATH) as f:
            cohort = json.load(f).get("cohort") or {}
        return indexstatus.summarise(cohort) if cohort else None
    except Exception:
        return None


def _index_families(limit=8):
    """Rows for the sampled index-coverage table: one page family per row.

    Families with nothing read yet are dropped rather than shown as 0% — an
    unread stratum is not a failing one, and on a cohort that refreshes over
    several days there is always one.
    """
    fams = (_index_summary() or {}).get("by_family") or {}
    if not fams:
        return []
    def _cell(pct):
        if pct is None:
            return ("—", "")
        return (f"{pct}%", "good" if pct >= 70 else ("warn" if pct >= 30 else "bad"))

    rows = []
    for name, f in sorted(fams.items(), key=lambda kv: -(kv[1].get("read") or 0)):
        read = f.get("read") or 0
        if not read:
            continue
        # Fetched and Kept, not "indexed" and "top non-indexed state". The old
        # fourth column spelled out the dominant failure state in prose, which
        # these two rates now say numerically and per-stratum: a low Fetched is a
        # distribution problem for that tier (Google never came), a high Fetched
        # with a low Kept is a quality one (it came and declined). That is the
        # actual fork in the road and it is different per family — on 2026-08-18
        # /building/ read 20.4% fetched / 17.6% kept while /guide/, /brief/,
        # /section8/, /dc/ and /la/ read 0% fetched, meaning every verdict ever
        # recorded against those tiers measured distribution, not demand.
        # Kept is "—" rather than 0% when nothing was fetched: no page has been
        # judged, so there is no acceptance rate to report, and a 0 there would
        # read as a quality verdict Google never gave.
        rows.append([f"/{name}/" if name != "(root)" else "/",
                     _cell(f.get("fetched_pct")),
                     _cell(f.get("accept_pct")),
                     str(read)])
        if len(rows) >= limit:
            break
    return rows


def _index_ages():
    """Acceptance by how long ago Google last fetched the page, oldest last.

    Rows are dropped when the band holds nothing fetched, so the table is only
    ever as wide as the evidence. Kept is "—" and not 0% for an empty band, the
    same rule as the family table: no page judged means no rate, and a 0 there
    would read as a verdict Google never gave.
    """
    tot = (_index_summary() or {}).get("total") or {}
    bands = tot.get("by_crawl_age") or {}
    rows = []
    for label, b in bands.items():
        n = b.get("fetched") or 0
        if not n:
            continue
        pct = b.get("accept_pct")
        cell = ("—", "") if pct is None else (
            f"{pct}%", "good" if pct >= 70 else ("warn" if pct >= 30 else "bad"))
        rows.append([label, str(n), cell])
    return rows


def _index_states():
    """Site-wide coverage-state split as chips: "crawled, not indexed — 61".

    Counted from the cohort when it is readable, and from the ledger series
    otherwise, so the report still renders anywhere the metrics do.

    The cohort comes first because the series is append-only history and a day's
    row is frozen at whatever the code knew that morning. On 2026-08-18 the
    recorded row said `unknown to Google — 74, state not recognised — 159` while
    the cohort those numbers were counted from held 233 URLs whose stored state
    read "URL is unknown to Google" — see summarise(). Plotting the frozen row is
    right; showing it as today's split is not, and the two blocks disagreeing in
    one email is worse than either. The series is not rewritten to match: an
    append-only record of what was believed on the day is the point of it.

    Empty buckets are dropped: the series is deliberately dense so a zero is a
    fact, but a chip row of nine zeroes is nine chips of noise.
    """
    from . import indexstatus
    buckets = ((_index_summary() or {}).get("total") or {}).get("buckets")
    out = []
    for b in indexstatus.BUCKETS:
        n = buckets.get(b) if buckets else _last(f"index_state_{b}")
        if not n:
            continue
        out.append(f"{_STATE_LABEL.get(b, b.replace('_', ' '))} — {_fmt(n)}")
    # One bucket and it is "indexed" tells the reader nothing the bar above did
    # not; the split is only worth the space when there is a split to show.
    return out if len(out) > 1 else []


_STATE_LABEL = {
    "indexed": "indexed",
    "crawled_not_indexed": "crawled, not indexed",
    "discovered_not_indexed": "discovered, never crawled",
    # Google's own answer, not a gap in this instrument — distinct from
    # "unknown" below, which is the API returning no coverage state at all.
    "unknown_to_google": "unknown to Google",
    "duplicate": "duplicate / alternate",
    "excluded_noindex": "noindex",
    "blocked": "blocked",
    "redirect": "redirect",
    "not_found": "404 / soft 404",
    "other": "state not recognised",
    "unknown": "no state returned",
}


def _trend(metric, days=14):
    """(yesterday, 7-day median, arrow, tone). Tone is about direction, not
    politeness — a fall in traffic is red even on a report you wrote yourself."""
    pairs = ledger.series("__site__", metric)[-days:] if metric else []
    if not pairs:
        return None, None, "", "mute"
    vals = [v for _, v in pairs]
    recent = statistics.median(vals[-7:]) if len(vals) >= 3 else vals[-1]
    prior = statistics.median(vals[-14:-7]) if len(vals) >= 10 else None
    if prior is None:
        return vals[-1], recent, "", "mute"
    if recent > prior:
        return vals[-1], recent, "▲", "good"
    if recent < prior:
        return vals[-1], recent, "▼", "bad"
    return vals[-1], recent, "=", "mute"


def _pretty_date(iso):
    try:
        return datetime.date.fromisoformat(str(iso)).strftime("%A, %B %d, %Y")
    except ValueError:
        return str(iso)


# ------------------------------------------------------------------- blocks

def build_blocks(run_log=None, review_out=None):
    techs = ledger.load_techniques()
    goals = ledger.get_state("goals", {})
    active = [t for t in techs if t.get("status") == "active"]
    cands = [t for t in techs if t.get("status") == "candidate"]
    retired = [t for t in techs if t.get("status") == "retired"]
    kw = keywords.summary()

    B = []

    # ---- the four numbers worth reading on a phone lock screen
    subs = _last("paying_subs") or 0
    mrr = _last("mrr_usd") or 0
    signups = _last("accounts_with_saves")
    goal_mrr = (goals.get("mrr_usd") or {}).get("target", 10000)
    goal_users = (goals.get("signups") or {}).get("target", 10000)
    v_last, v_med, v_arrow, v_tone = _trend("visitors")
    o_last, o_med, o_arrow, o_tone = _trend("organic_visitors")
    B.append({"type": "tiles", "items": [
        {"label": "Visitors yesterday", "value": _fmt(v_last),
         "delta": f"{v_arrow} {_fmt(v_med)}/day median".strip(), "tone": v_tone},
        {"label": "Organic search", "value": _fmt(o_last),
         "delta": f"{o_arrow} {_fmt(o_med)}/day median".strip(), "tone": o_tone},
        {"label": "Active signups", "value": _fmt(signups),
         "delta": f"of {_fmt(goal_users)} target"},
        {"label": "Revenue", "value": f"{_money(mrr)}/mo",
         "delta": f"{subs} paying subscriber(s)", "tone": "good" if subs else "mute"},
    ]})

    # ---- goals, as distance-to-target rather than a bare number
    share = _last("search_share_pct")
    B.append({"type": "section", "label": "Goals"})
    B.append({"type": "progress", "label": "Revenue",
              "value": f"{_money(mrr)} / {_money(goal_mrr)}",
              "sub": f"{subs} paying subscriber(s)",
              "pct": _pct(mrr, goal_mrr), "tone": "good" if mrr else "info"})
    B.append({"type": "progress", "label": "Signups",
              "value": f"{_fmt(signups)} / {_fmt(goal_users)}",
              "sub": "accounts that have saved at least one building",
              "pct": _pct(signups, goal_users)})
    if share is not None:
        B.append({"type": "progress", "label": "Search share",
                  "value": f"{share}% / 90%",
                  "sub": f"{_fmt(_last('tracked_top3'))} of {kw['total']} tracked queries "
                         f"in the top 3",
                  "pct": _pct(share, 90)})
        serving = _last("gsc_serving_pages")
        if serving is not None:
            indexed_pct = _pct(serving, PUBLISHED_PAGES)
            B.append({"type": "progress", "label": "Search footprint",
                      "value": f"{_fmt(serving)} / ~{PUBLISHED_PAGES:,} pages",
                      # Renamed from "Indexing" on 2026-08-15. An impression
                      # needs the page indexed AND somebody to have searched for
                      # it, and on 47k single-address pages the second is the
                      # binding constraint — so this was never the indexing
                      # number it was labelled as. The real one is below.
                      "sub": "pages that earned an impression — indexed *and* searched for",
                      "pct": indexed_pct, "tone": "bad" if indexed_pct < 5 else "info"})
            # That count on its own reads as a plateau when it is really a
            # rotation: on 2026-08-04 it held at 89 while nine URLs entered the
            # set and nine left it. Say which it is, or the number misleads.
            stable = _last("gsc_serving_stable")
            ever = _last("gsc_serving_ever")
            if stable is not None and serving:
                held = round(100.0 * stable / serving)
                B.append({"type": "note",
                          "text": f"{_fmt(stable)} of those {_fmt(serving)} also served "
                                  f"yesterday ({held}% held); "
                                  f"{_fmt(_last('gsc_serving_entered'))} entered and "
                                  f"{_fmt(_last('gsc_serving_left'))} dropped out overnight. "
                                  f"{_fmt(ever)} distinct pages have served at least once "
                                  f"since this was first recorded."})
        # Three loose numbers, not a table — four header cells collide at phone
        # width and a one-row table is a table for no reason.
        #
        # These are the PAGE dimension, which is the site's actual footprint;
        # gsc_clicks/gsc_impressions are the query dimension, which drops
        # anonymized queries and on this corpus reported 11 impressions against
        # a real 137 (see searchconsole.collect). Fall back to the query numbers
        # for days recorded before 2026-08-14, when the page series starts, so
        # the trend does not break at the changeover — `is None` and not `or`,
        # because a genuine zero is a fact, not a missing value.
        # ---- the measured index rate, which is a different question from the
        # footprint above and the one that decides whether to publish more pages
        # or fewer. Sampled from the URL Inspection API — see growth/indexstatus.py.
        # Same rule as _index_states(): count from the cohort when it is there,
        # fall back to the frozen series row when it is not.
        _ixtot = (_index_summary() or {}).get("total") or {}
        _read = _ixtot.get("read") or _last("index_read")
        _pct_ix = _ixtot.get("indexed_pct")
        if _pct_ix is None:
            _pct_ix = _last("index_pct")
        if _read and _pct_ix is not None:
            B.append({"type": "progress", "label": "Indexed (sampled)",
                      "value": f"{_pct_ix}% of {_fmt(_read)} inspected",
                      "sub": "Google's own coverage state for a fixed stratified "
                             "sample of published pages",
                      "pct": _pct_ix,
                      "tone": "bad" if _pct_ix < 30 else
                              ("warn" if _pct_ix < 70 else "good")})
            # indexed_pct is the product of two independent failures, and until
            # 2026-08-18 only the product was reported — so every review since
            # 07-27 argued about whether "3.7% indexed" meant Google would not
            # come or would not keep, when the answer was both and in known
            # proportions. Split out so a fix can be judged on the half it was
            # aimed at: see summarise() in indexstatus.py.
            _fet = _ixtot.get("fetched_pct")
            _acc = _ixtot.get("accept_pct")
            if _fet is None:
                _fet, _acc = _last("index_fetched_pct"), _last("index_accept_pct")
            if _fet is not None and _acc is not None:
                B.append({"type": "tiles", "items": [
                    {"label": "Ever fetched", "value": f"{_fet}%",
                     "delta": "Googlebot came for the page",
                     "tone": "bad" if _fet < 50 else "info"},
                    {"label": "Kept, of fetched", "value": f"{_acc}%",
                     "delta": "and did not drop it again",
                     "tone": "bad" if _acc < 50 else "info"}]})
            # "Kept, of fetched" is an average over crawls of every age, and on
            # 2026-08-19 that average (15.8%) sat between a 62.5% matured slice
            # and three consecutive 0% bands — a number that described no page
            # on the site and would have justified either of two opposite
            # decisions. The band table is the disaggregation; see MATURE_DAYS
            # in indexstatus.py for why this is the axis that matters.
            _ages = _index_ages()
            if _ages:
                B.append({"type": "table",
                          # "Last fetched", not "Fetched": the family table
                          # directly above uses Fetched for a percentage, and
                          # two columns of the same name meaning different
                          # things in one email is how a number gets misread.
                          "cols": ["Last fetched", "Pages", "Kept"],
                          "rows": _ages})
                _accm, _nm = _ixtot.get("accept_pct_mature"), _ixtot.get("fetched_mature")
                B.append({"type": "note", "text": (
                    f"Acceptance among the {_fmt(_nm)} pages Google last fetched "
                    f"{_ixtot.get('mature_days', 21)}+ days ago — long enough for "
                    f"\"not indexed\" to be a verdict rather than a queue position — "
                    f"is {_accm}%."
                    if _accm is not None else
                    "No sampled page has a crawl old enough to tell a verdict from a "
                    "queue position yet.")})
            # What the un-indexed 97% actually is. The per-family table below
            # gives each stratum's worst state; this gives the site-wide split,
            # which is the line that says which fix applies — see the comment on
            # summarise() in indexstatus.py.
            chips = _index_states()
            if chips:
                B.append({"type": "chips", "items": chips})
            ix = _index_families()
            if ix:
                B.append({"type": "table",
                          "cols": ["Page family", "Fetched", "Kept", "Read"],
                          "rows": ix})
            _wrong = _last("index_wrong_canonical")
            if _wrong:
                B.append({"type": "note", "text":
                          f"{_fmt(_wrong)} sampled pages are indexed under a Google-chosen "
                          f"canonical that is not their own URL — those can never serve "
                          f"under the address they were built for."})
        ixrun = ledger.read_last_run().get("indexstatus") or {}
        if ixrun.get("ok") is False:
            B.append({"type": "callout", "tone": "warn",
                      "heading": "Index sampling did not run",
                      "body": str(ixrun.get("detail") or "unknown error")})

        _pc, _pi = _last("gsc_page_clicks"), _last("gsc_page_impressions")
        B.append({"type": "stats", "items": [
            (_fmt(_last("gsc_clicks") if _pc is None else _pc), "clicks, last 7d"),
            (_fmt(_last("gsc_impressions") if _pi is None else _pi), "impressions"),
            (_fmt(_last("gsc_position")), "avg position")]})
        if _pi is not None:
            B.append({"type": "note", "text":
                      "Clicks and impressions are Search Console's page dimension. Its query "
                      "dimension drops anonymized rare queries and, on a corpus of single-address "
                      "pages, reports a small fraction of the real total."})
    else:
        B.append({"type": "callout", "tone": "warn", "heading": "Search share unmeasured",
                  "body": f"Search Console is not reporting. Coverage proxy: "
                          f"{kw['coverage_pct']}% of {kw['total']} tracked queries have a page."})

    # ---- the deploy path behind every number above. refresh_seo.sh is a
    # nightly job; when it stops, the ~47k pages Google actually crawls freeze
    # and no content change in this repo can reach them, so a flat indexing
    # number is a deploy failure rather than a content problem. That distinction
    # spent 2026-08-01..08-08 buried inside t_crawl_paths' detail string, where
    # it read as a footnote to an orphan report. It is the owner action.
    build = ledger.read_last_run().get("build") or {}
    corpus, pipe = build.get("seo_corpus"), build.get("seo_pipeline")
    if corpus and (corpus.get("days_old") or 0) >= SEO_CORPUS_STALE_DAYS:
        days = corpus["days_old"]
        # "Needs a hand on the droplet" is true but was, until 2026-08-12, the
        # end of what this could say — the owner got a date and had to SSH in to
        # find out whether cron fired, the build crashed or the rsync failed.
        # refresh_seo.sh now records the step it died in; when it has, name it
        # here, because the step IS the fix.
        if pipe:
            cause = (f" That pipeline's own last record says: {pipe['state']} "
                     f"(as of {pipe.get('hours_ago', '?')}h ago, at commit "
                     f"{pipe.get('head', '?')}).")
        else:
            cause = (" It reports nothing about itself yet — the droplet is still "
                     "running a refresh_seo.sh from before 2026-08-12, which will "
                     "self-report from its first run after the next pull.")
        B.append({"type": "callout",
                  "tone": "bad" if days >= 3 else "warn",
                  "heading": f"SEO corpus frozen for {days} days",
                  "body": f"The ~{PUBLISHED_PAGES:,}-page corpus in the docroot was last "
                          f"written {_pretty_date(corpus['written'])}. scripts/refresh_seo.sh "
                          f"runs nightly, so it has not completed since then and every "
                          f"build_seo.py change pushed since is still only in git. The daily "
                          f"growth build's own pages are unaffected — they deploy on a "
                          f"separate rsync." + cause +
                          # Until 2026-08-14 this ended "nothing in the repo can
                          # restart it", which stopped being true when
                          # growth_run.sh got seo_watchdog(): the 05:40 build now
                          # re-runs refresh_seo.sh itself whenever the corpus is
                          # stale. So a corpus still frozen at this point is the
                          # watchdog having failed, not the cron merely missing,
                          # and the heartbeat says which.
                          " growth_run.sh's watchdog re-runs scripts/refresh_seo.sh "
                          "after the 05:40 build whenever the corpus is this old, so "
                          "seeing this means the watchdog also failed or has not "
                          "deployed — growth/cron_heartbeat.jsonl carries its "
                          "seo_watchdog_finish rc."})

    # ---- the cheapest available rankings
    try:
        from . import searchconsole
        p2 = searchconsole.page2(limit=10)
    except Exception:
        p2 = None
    if p2:
        B.append({"type": "section", "label": "Page-2 queries",
                  "note": "Ranked 11–20 — the cheapest wins on the board"})
        B.append({"type": "table", "cols": ["Query", "Position", "Impressions"],
                  "align": ["left", "right", "right"], "mono": True, "widths": [56, 20, 24],
                  "rows": [[k["query"], (f"{k['position']}", "warn"),
                            _fmt(k.get("impressions", 0))] for k in p2]})

    # ---- the page-level twin of the above: which URLs are close, not which
    # queries. When the fix is rewriting a page rather than publishing one,
    # this is the list that tells you which page.
    try:
        from . import searchconsole
        heads = searchconsole.headroom(limit=10)
    except Exception:
        heads = []
    if heads:
        addr = sum(1 for p in heads if p["url"].startswith("https://findacrib.com/building/"))
        note = "Already served, ranking 11–30 — rewrite these before publishing new ones"
        if addr:
            note += (f" · {addr} of {len(heads)} are single-address pages, listed last: "
                     f"their only query is the street address, so a rewrite adds no volume")
        B.append({"type": "section", "label": "Pages with headroom", "note": note})
        B.append({"type": "table", "cols": ["Page", "Position", "Impressions"],
                  "align": ["left", "right", "right"], "mono": True, "widths": [56, 20, 24],
                  "rows": [[p["url"].replace("https://findacrib.com", "") or "/",
                            (f"{p['position']}", "warn"), _fmt(p["impressions"])]
                           for p in heads]})

    # ---- traffic
    B.append({"type": "section", "label": "Traffic",
              "note": "Excludes the owner's own visits"})
    rows = []
    for m, label in (("visitors", "All visitors"), ("organic_visitors", "Organic search"),
                     ("ai_visitors", "AI answer engines"), ("direct_visitors", "Direct"),
                     ("referral_visitors", "Referral")):
        last, med, arrow, tone = _trend(m)
        # The arrow rides on the median rather than taking a fourth column —
        # four columns do not fit a phone, and the arrow is about the median.
        rows.append([label, _fmt(last), {"text": f"{arrow} {_fmt(med)}".strip(), "tone": tone}])
    B.append({"type": "table", "cols": ["Source", "Yesterday", "Median/day"],
              "align": ["left", "right", "right"], "mono": True, "rows": rows})

    # ---- what ran
    if run_log:
        failed = sum(1 for r in run_log if not r.get("ok"))
        B.append({"type": "section", "label": "What ran overnight",
                  "note": f"{len(run_log)} jobs · "
                          + (f"{failed} failed" if failed else "all clear")})
        B.append({"type": "status", "items": [
            {"ok": bool(r.get("ok")), "name": r["slug"], "detail": r.get("detail", "")}
            for r in run_log]})

    # ---- per-technique performance
    B.append({"type": "section", "label": f"Active techniques ({len(active)})"})
    rows = []
    for t in active:
        if t.get("prefixes"):
            pairs = ledger.series(t["slug"], "owned_visitors", since=t.get("activated"))
            total = sum(v for _, v in pairs)
            recent = statistics.median([v for _, v in pairs[-7:]]) if pairs else None
            # Search visibility rides in the sub-line rather than a fourth
            # column — four columns do not fit a phone — but it is the number
            # that says whether a zero-visitor technique is early or dead.
            vis = searchconsole.recent_visibility(t["slug"], since=t.get("activated"))
            sub = f"owns {', '.join(t['prefixes'])} · since {t.get('activated')}"
            if vis["measured"]:
                sub += (f" · {vis['pages']} pages serving, {vis['impressions']} impressions"
                        + (f", best position {vis['best_position']}"
                           if vis["best_position"] is not None else ""))
            rows.append([{"text": f"{t['id']} {t['name']}", "sub": sub},
                         _fmt(total), _fmt(recent)])
        else:
            last, med, _arrow, _tone = _trend(t.get("metric"))
            rows.append([{"text": f"{t['id']} {t['name']}",
                          "sub": f"site-wide · judged on {t.get('metric')}"},
                         _fmt(last), _fmt(med)])
    if rows:
        B.append({"type": "table", "cols": ["Technique", "Total", "Recent/day"],
                  "align": ["left", "right", "right"], "widths": [58, 20, 22], "rows": rows})

    # ---- scheduled second looks. The 21-day review asks "is this dead?"; this
    # asks "is this still the best version of the idea, or should it be replaced?"
    revisits = ledger.revisit_due()
    if revisits:
        B.append({"type": "section", "label": f"Due for revisit ({len(revisits)})",
                  "note": "Decide keep / change / replace"})
        for t in revisits:
            meta = f"scheduled {t.get('revisit_on')}"
            if t.get("prefixes"):
                pairs = ledger.series(t["slug"], "owned_visitors", since=t.get("activated"))
                meta += (f" · {sum(v for _, v in pairs):,} owned visitors "
                         f"since {t.get('activated')}")
            B.append({"type": "card", "heading": f"{t['id']} {t['name']}", "meta": meta,
                      "body": f"Hypothesis was: {(t.get('hypothesis') or '')[:200]}"})

    # ---- review decisions
    if review_out and review_out.get("actions"):
        B.append({"type": "section", "label": "Review decisions today"})
        B.append({"type": "chips", "items": review_out["actions"]})

    # ---- scoreboard
    sb = review.scoreboard()
    if sb["works"] or sb["does_not_work"]:
        B.append({"type": "section", "label": "Scoreboard so far"})
        B.append({"type": "table", "cols": ["Verdict", "Technique", "Why"],
                  "align": ["left", "left", "left"],
                  "rows": [[("WORKS", "good"), f"{r['id']} {r['name']}", r["why"]]
                           for r in sb["works"]]
                          + [[("DIDN'T WORK", "bad"), f"{r['id']} {r['name']}", r["why"]]
                             for r in sb["does_not_work"]]})

    # ---- research jobs: say plainly when they could not run. A daily job that
    # fails quietly (no key, no credit, rate limited) looks like a job with
    # nothing to report, and the difference matters.
    trouble = []
    for key, label in (("scout_last", "Scout (new techniques)"),
                       ("outreach_last", "Outreach (B2B prospects)")):
        st = ledger.get_state(key)
        # `is False` on purpose, not falsiness. Failure paths always write an
        # explicit ok=False with a detail; a record missing the key entirely is
        # an older or partial write, and reporting that as a failure with
        # "unknown error" is a false alarm — which is exactly what happened.
        if st and st.get("ok") is False:
            trouble.append((label, st.get("detail", "unknown error")))
    if trouble:
        B.append({"type": "section", "label": "Research jobs blocked"})
        for label, detail in trouble:
            B.append({"type": "callout", "tone": "bad", "heading": f"{label} did not run",
                      "body": detail})

    # ---- what the engine spent on the API. A daily job that quietly costs 50x
    # what it should looks exactly like one that is working, right up until the
    # account hits its cap — which is what happened on 2026-07-28.
    spend = ledger.get_state("api_spend", {}) or {}
    if spend:
        days = sorted(spend)[-7:]
        today_total = sum((spend.get(ledger.today()) or {}).values())
        week_total = sum(sum(v.values()) for d, v in spend.items() if d in days)
        B.append({"type": "section", "label": "API spend (estimated)",
                  "note": "Token cost of the LLM jobs — see growth/BUDGET.md"})
        B.append({"type": "stats", "items": [
            (f"${today_total:,.2f}", "today"),
            (f"${week_total:,.2f}", f"last {len(days)} days"),
            (f"${week_total / max(len(days), 1):,.2f}", "per day average")]})

    # ---- outreach drafts awaiting a send decision
    try:
        from . import outreach
        drafts = outreach.pending(limit=8)
    except Exception:
        drafts = []
    if drafts:
        B.append({"type": "section",
                  "label": f"Outreach drafts awaiting approval ({len(drafts)})",
                  "note": "Nothing is ever sent automatically — files in "
                          "growth/outreach_drafts/"})
        for d in drafts:
            B.append({"type": "card", "heading": d["org"],
                      "meta": f"{d.get('segment')} · confidence {d.get('confidence')} · "
                              f"reach via {d.get('contact_route')}",
                      "body": (d.get("why") or "")[:200],
                      "link": ("Open site", d["url"]) if d.get("url") else None})

    # ---- blocked candidates: the things needing a human
    needs_owner = [t for t in cands if t.get("notes")]
    if needs_owner:
        try:
            page_url = _write_waiting_page(needs_owner)
        except Exception:
            page_url = None
        # only cap when the overflow has somewhere to live
        shown = needs_owner[:WAITING_EMAIL_CAP] if page_url else needs_owner
        B.append({"type": "section", "label": "Waiting on you",
                  "note": "These candidates cannot activate without a decision"})
        for t in shown:
            B.append({"type": "callout", "tone": "warn",
                      "heading": f"{t['id']} {t['name']}",
                      "body": (t.get("notes") or "").strip().split("\n")[0]})
        rest = len(needs_owner) - len(shown)
        if rest:
            B.append({"type": "card",
                      "heading": f"{rest} more waiting on a decision",
                      "body": "The full list, with complete notes, is on one page.",
                      "link": (f"See all {len(needs_owner)}", page_url)})

    if kw["gaps"]:
        B.append({"type": "section", "label": f"Uncovered queries ({len(kw['gaps'])})",
                  "note": "Drives the content roadmap"})
        B.append({"type": "chips", "items": kw["gaps"][:12]})

    B.append({"type": "note",
              "text": f"Ledger: {len(techs)} techniques — {len(active)} active, "
                      f"{len(cands)} candidate, {len(retired)} retired."})
    return B


def build(run_log=None, review_out=None):
    """(subject, html, text) for the day's report."""
    day = ledger.today()
    html, text = emailkit.render(
        title="Daily growth report",
        eyebrow=_pretty_date(day),
        blocks=build_blocks(run_log=run_log, review_out=review_out),
        cta=("Open the dashboard", DASHBOARD),
        footer_note="Sent by the Find A Crib growth engine. Traffic numbers exclude the "
                    "owner's own visits.",
        width=640)
    return f"Find A Crib growth — {day}", html, text


def build_text(run_log=None, review_out=None):
    """The plain-text rendering — what prints to the console and what goes in
    the text/plain part of the message."""
    return build(run_log=run_log, review_out=review_out)[2]


def email(to, run_log=None, review_out=None, prebuilt=None):
    """Send the report. `prebuilt` reuses a (subject, html, text) already built
    for the console, so one run never reads the ledger twice."""
    subject, html, text = prebuilt or build(run_log=run_log, review_out=review_out)
    for addr in [a.strip() for a in str(to).split(",") if a.strip()]:
        emailkit.send(addr, subject, html, text)
    return True
