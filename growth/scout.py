#!/usr/bin/env python3
"""The 6am scout: find techniques we are not running yet.

Once a day it asks a model with live web search what is currently working for
sites like this one — organic search, AI answer engines, distribution, and
revenue — then filters the answers against the ledger so it proposes ideas we
have not already tried and rejected.

What it will and will not do on its own:

  proposes   new techniques, written into the ledger as `candidate` with a
             hypothesis and a source, so the owner (or a later session) can
             implement them
  expands    the tracked keyword universe, which is what the 90%-share goal is
             measured against — new queries are pure upside and cost nothing
  will NOT   write code, change the live site, spend money, or send mail

That boundary is deliberate. A loop that can edit its own production site
unattended will eventually deploy something broken at 6am on a Sunday, and the
whole point of the ledger is that changes are legible and reversible.

Needs an Anthropic API key in keychain `rent-map-anthropic`, env
ANTHROPIC_API_KEY, or a file at growth/.anthropic_key.
"""
import json
import os
import subprocess
import urllib.error
import urllib.request

from . import keywords, ledger, review

HERE = os.path.dirname(os.path.abspath(__file__))
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-5"
MAX_NEW_PER_DAY = 3          # a trickle of well-formed ideas beats a firehose
MAX_KEYWORDS_PER_DAY = 25


def load_key():
    v = os.environ.get("ANTHROPIC_API_KEY")
    if v:
        return v.strip()
    p = os.path.join(HERE, ".anthropic_key")
    if os.path.exists(p):
        return open(p).read().strip()
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", "rent-map-anthropic", "-w"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}]

SYSTEM = """You are the growth scout for Find A Crib (findacrib.com), a property-level map of \
rent-stabilized and rent-controlled housing in NYC, San Francisco, Los Angeles and Washington DC.

Your job each day: search the web for growth techniques that are working RIGHT NOW, and propose \
ones this site is not already running. You are advising a real business with real constraints.

STANDING PRIORITY — GET ALL FOUR CITIES INDEXED AND DISTRIBUTED.
The single largest constraint on this business is that its pages are not in the index. Measured \
2026-08-29 from the engine's own index_status sample: of 455 published URLs, Google had FETCHED 82 \
and INDEXED 1 — the homepage. 55 building pages came back crawled_not_indexed, meaning Google read \
them and declined; ~330 were unknown_to_google, never discovered at all. Of the 274 URLs that have \
ever served a Search Console impression, 271 are NYC and 3 are the bare /sf/, /la/ and /dc/ \
landing pages: not one SF, LA or DC content page has ever appeared in a search result.

So on EVERY run, dedicate a meaningful share of your proposals to getting all four cities — NYC, \
San Francisco, Los Angeles, Washington DC (and Westchester/Yonkers as it comes online) — \
discoverable and cited. Treat all three of these as in scope:
  * GOOGLE — discovery and, harder, acceptance. crawled_not_indexed is a quality verdict, not a \
    plumbing fault, so propose things that change what a page IS: consolidation, unique data per \
    URL, structured data, internal link paths from pages Google already crawls. Submitting more \
    near-duplicate URLs makes this worse and is never the answer.
  * OTHER ENGINES — Bing/Yandex/Seznam/Naver via IndexNow are already wired, but Bing Webmaster \
    Tools, DuckDuckGo (Bing-derived), Brave, Kagi, Apple Spotlight/Siri and the AI answer engines \
    (ChatGPT, Perplexity, Claude, Gemini, AI Overviews) are separate surfaces with their own \
    submission and citation mechanics. This site is crawled ~9,000 times a day by AI agents; being \
    CITED by them is a distribution channel in its own right.
  * SOCIAL — Reddit, Nextdoor, TikTok, Instagram, YouTube and tenant/mutual-aid networks index \
    and surface content on their own terms, and several are where NYC renters actually ask these \
    questions. Propose distribution that earns links and mentions rather than posting spam; \
    anything that violates a platform's rules fails the tests below.

A proposal that only helps NYC is still welcome, but say so, and prefer ones that lift every city \
at once — the non-NYC cities have the same dataset shape and none of the traffic.

Judge every idea against these rules and discard it if it fails any:
- It must be legal, and it must not violate the terms of service of Google, Bing, Reddit, or any \
platform involved. Never propose buying links, private blog networks, cloaking, doorway pages, \
scraped or AI-spun filler content, fake reviews, or bulk unsolicited email.
- It must suit a site whose credibility IS the product. This data is used by tenants to make \
housing decisions; anything that trades accuracy or trust for traffic is worthless here.
- It must be concrete enough to implement, and cheap enough for a solo operator.
- Prefer techniques with a defensible advantage: this site owns a dataset almost nobody else \
publishes at the property level.

Return ONLY valid JSON, no prose, in this shape:
{
  "techniques": [
    {"slug": "snake_case_id", "name": "short label",
     "kind": "content|indexing|distribution|lifecycle|conversion",
     "hypothesis": "why this should drive traffic or revenue HERE, specifically",
     "evidence": "what you found that suggests it works, with a URL",
     "effort": "hours|days|weeks",
     "expected": "what success would look like in numbers",
     "first_step": "the single concrete first action"}
  ],
  "keywords": [
    {"query": "lowercase search query", "city": "nyc|sf|la|dc",
     "intent": "list|check|explain", "why": "why this query matters"}
  ],
  "notes": "anything the owner should know, including techniques you considered and rejected"
}"""


def build_prompt(docroot=None):
    techs = ledger.load_techniques()
    running = [f"- {t['name']} [{t['status']}] — {t['hypothesis'][:160]}" for t in techs]
    sb = review.scoreboard()
    tried = [f"- {r['name']}: DID NOT WORK — {r['why']}" for r in sb["does_not_work"]]
    won = [f"- {r['name']}: WORKS — {r['why']}" for r in sb["works"]]
    # Kept out of the won list on purpose. A scout told that a technique with
    # $0.00 of lifetime revenue "WORKS" proposes more of it; this section asks
    # for the opposite move — a way to measure it, or a better idea.
    unproven = [f"- {r['name']}: {r['why']}" for r in sb.get("unproven") or []]
    kw = keywords.summary()
    goals = ledger.get_state("goals", {})

    def last(m):
        s = ledger.series("__site__", m)
        return s[-1][1] if s else "unknown"

    return f"""Today is {ledger.today()}.

SITE
findacrib.com — a map of every DHCR-registered rent-stabilized building in NYC (47,165 buildings,
with owner, managing agent, HPD violations and complaints per building), plus San Francisco,
Los Angeles and Washington DC. ~47,000 static SEO pages already exist for NYC buildings,
neighborhoods, boroughs and ZIPs, plus guides. There is a free tier, a $4.99/mo "Plus" tier
(saved-building alerts, agent phone numbers, portfolio research, saved searches), and a
key-metered Developer API that is built but not productized.

CURRENT NUMBERS
- visitors/day: {last('visitors')} (paid ads are currently PAUSED, so this is the organic floor)
- organic search visitors/day: {last('organic_visitors')}
- AI answer engine visitors/day: {last('ai_visitors')}
- paying subscribers: {last('paying_subs')} — revenue is effectively $0
- registered accounts: single digits to low tens
- tracked query universe: {kw['total']} queries, {kw['coverage_pct']}% have a page targeting them

GOALS
- {json.dumps(goals.get('search_share_pct', {}).get('target', 90))}% of searches for rent-stabilized
  housing in the four covered cities
- {json.dumps(goals.get('signups', {}).get('target', 10000))} registered users
- ${json.dumps(goals.get('mrr_usd', {}).get('target', 10000))}/month revenue

TECHNIQUES ALREADY IN THE LEDGER (do not re-propose these)
{chr(10).join(running) if running else '(none)'}

ALREADY MEASURED AS WORKING
{chr(10).join(won) if won else '(nothing judged yet)'}

ALREADY MEASURED AS NOT WORKING — do not propose these again
{chr(10).join(tried) if tried else '(nothing retired yet)'}

RUNNING BUT UNPROVEN — the review read the series and could NOT tell whether these work,
usually because the metric they are judged on has no resolution at this traffic level.
Do not treat these as successes to extend. If you can name a metric that WOULD resolve one
of them, say so in notes; that is worth more than another technique.
{chr(10).join(unproven) if unproven else '(none)'}

QUERIES ALREADY TRACKED — do not propose these or paraphrases of them. "is my apartment
rent controlled sf" and "is my apartment rent controlled san francisco" are the same entry
for our purposes; padding the universe with restatements makes the share goal meaningless.
{chr(10).join('- ' + k['query'] for k in keywords.load()) or '(none yet)'}

TASK
1. Search for what is currently working in 2026 for: programmatic/data-driven SEO, getting large
   page counts actually indexed, ranking in AI answer engines, and monetizing a proprietary
   civic-data set. Prefer sources from the last 6 months.
2. Propose at most {MAX_NEW_PER_DAY} techniques NOT already in the ledger. Fewer, better ideas.
3. Propose up to {MAX_KEYWORDS_PER_DAY} search queries to add to the tracked universe — real
   queries people type about rent regulation in NYC, SF, LA or DC.

Given revenue is the weakest number, at least one technique should target revenue directly."""


class ApiError(RuntimeError):
    """An Anthropic API error, carrying the API's own message.

    urllib raises a bare 'HTTP Error 400: Bad Request' on failure, which hides
    the one thing worth knowing. Billing and rate-limit problems both surface as
    4xx here, and a daily job that logs only the status code looks broken when
    it is merely out of credit.
    """

    def __init__(self, status, etype, message):
        self.status, self.etype, self.message = status, etype, message
        super().__init__(f"{etype or 'http_' + str(status)}: {message}")


# Published per-million-token rates for the model above, so a run can price
# itself. Update these together with MODEL — a stale rate here reports a
# confident wrong number, which is worse than reporting none.
PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK = 5.00, 25.00     # claude-opus-5


def price(usage):
    """Dollar estimate for one API response's `usage` block.

    Cache reads are ~0.1x input and cache writes ~1.25x, so this is an
    estimate, not an invoice — it is here to catch an order-of-magnitude
    problem (a job that quietly costs 50x what it should), not to reconcile
    billing. Web-search results land in input tokens, which is why a
    search-heavy call is dominated by the input side.
    """
    u = usage or {}
    tin = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
           + u.get("cache_creation_input_tokens", 0))
    tout = u.get("output_tokens", 0)
    return round(tin / 1e6 * PRICE_IN_PER_MTOK + tout / 1e6 * PRICE_OUT_PER_MTOK, 4)


def record_spend(job, resp):
    """Add one call's estimated cost to today's running total in the ledger."""
    try:
        cost = price((resp or {}).get("usage"))
        day = ledger.today()
        spend = ledger.get_state("api_spend", {}) or {}
        today = spend.get(day) or {}
        today[job] = round((today.get(job) or 0) + cost, 4)
        # Keep a fortnight; this is a tripwire, not an accounting system.
        spend = {d: v for d, v in spend.items() if d >= _days_ago(14)}
        spend[day] = today
        ledger.set_state("api_spend", spend)
        return cost
    except Exception:
        return 0.0        # never let cost bookkeeping break the job it measures


def _days_ago(n):
    import datetime
    return (datetime.date.fromisoformat(ledger.today())
            - datetime.timedelta(days=n)).isoformat()


def call_api(key, prompt, timeout=600):
    # 180s timed out on 2026-08-13 once max_tokens gave Opus 5 real headroom —
    # a thinking model doing web search legitimately generates for minutes.
    body = {
        "model": MODEL,
        # Opus 5 spends part of this on thinking before any text, and web-search
        # answers are long — 4k truncated them, and 8k once went entirely to
        # thinking, ending the reply before the JSON started (2026-08-13).
        # 16k did the same on 2026-08-28: stop_reason=max_tokens with the entire
        # visible output being "I'll research current growth techniques before
        # proposing." — the whole budget went to thinking and eight server-side
        # searches, and the run produced nothing. There is nothing to salvage
        # from a reply that never reached a "{", so _salvage() cannot help here
        # and the only lever is headroom. This is a ceiling, not a spend: a run
        # that already finishes inside 16k costs exactly what it did before, and
        # the failed run had already paid for 16,000 tokens and got no techniques
        # and no keywords for them.
        "max_tokens": 32000,
        "system": SYSTEM,
        "tools": TOOLS,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(),
        headers={"content-type": "application/json",
                 "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(raw).get("error") or {}
        except Exception:
            err = {}
        raise ApiError(e.code, err.get("type"), err.get("message") or raw[:200]) from None


def _salvage(blob):
    """Best-effort parse of a JSON object that was cut off mid-write.

    Long web-search answers get truncated at max_tokens, which leaves a valid
    prefix and a half-written final element. Rather than throw the whole day's
    research away, walk back to the last balanced position and close it. The
    partial element is dropped, never guessed at.
    """
    decoder = json.JSONDecoder()
    for end in range(len(blob), 1, -1):
        chunk = blob[:end]
        # close whatever is still open, innermost first
        depth = []
        in_str = esc = False
        for ch in chunk:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                depth.append(ch)
            elif ch in "}]":
                if depth:
                    depth.pop()
        if in_str:
            continue
        candidate = chunk.rstrip().rstrip(",")
        candidate += "".join("}" if c == "{" else "]" for c in reversed(depth))
        try:
            return decoder.decode(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("could not salvage JSON from a truncated response")


def extract_json(resp):
    """Pull the JSON object out of the response, ignoring any search chatter."""
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    truncated = resp.get("stop_reason") == "max_tokens"

    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start < 0:
        raise ValueError(f"no JSON object in response (stop_reason={resp.get('stop_reason')}): "
                         f"{text[:300]}")
    blob = text[start:end + 1] if end > start else text[start:]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as e:
        try:
            out = _salvage(blob)
            print(f"  note: response was malformed{' (truncated at max_tokens)' if truncated else ''}"
                  f" — salvaged the complete entries and dropped the partial one")
            return out
        except Exception:
            raise ValueError(
                f"unparseable JSON{' — truncated at max_tokens' if truncated else ''}: {e}") from None


def _mirror(record):
    """Copy the scout's outcome into last_run.json, which is tracked in git.

    scout_last lives in growth/state.json, and state.json is gitignored because
    it carries per-URL content hashes and visitor ids. So the daily review — which
    runs on a bare checkout in the cloud — has never been able to see whether the
    scout ran, failed for want of a key, or hit a billing cap; on 2026-08-16 it
    could only infer a successful run from `source: scout:<date>` tags left behind
    in keywords.json. That is the same blind spot last_run.json was created to
    close for the crons, so the answer is the same file.

    COUNTS AND ERRORS ONLY. This repo is public. Slugs and queries are already
    published in techniques.json and keywords.json, but do not widen this to echo
    model output — see outreach._mirror, where the equivalent field is a list of
    named third-party organisations that must never be committed.
    """
    ledger.write_last_run("scout", {"date": ledger.today(), **record})


def run(dry_run=False, docroot=None):
    key = load_key()
    if not key:
        msg = ("no Anthropic key — set keychain `rent-map-anthropic`, env ANTHROPIC_API_KEY, "
               "or growth/.anthropic_key. Scout skipped.")
        print(f"  {msg}")
        ledger.set_state("scout_last", {"date": ledger.today(), "ok": False, "detail": msg})
        _mirror({"ok": False, "detail": msg})
        return {"ok": False, "detail": msg}

    prompt = build_prompt(docroot)
    try:
        resp = call_api(key, prompt)
        record_spend("scout", resp)
        data = extract_json(resp)
    except Exception as e:
        print(f"  scout call failed: {e}")
        ledger.set_state("scout_last", {"date": ledger.today(), "ok": False, "detail": str(e)})
        _mirror({"ok": False, "detail": str(e)})
        return {"ok": False, "detail": str(e)}

    known = {t["slug"] for t in ledger.load_techniques()}
    added_t, added_k = [], []

    for t in (data.get("techniques") or [])[:MAX_NEW_PER_DAY]:
        slug = (t.get("slug") or "").strip().lower().replace("-", "_")
        if not slug or slug in known:
            continue
        kind = t.get("kind") if t.get("kind") in ledger.VALID_KIND else "content"
        notes = "\n".join(filter(None, [
            f"effort: {t.get('effort')}" if t.get("effort") else None,
            f"expected: {t.get('expected')}" if t.get("expected") else None,
            f"first step: {t.get('first_step')}" if t.get("first_step") else None,
        ]))
        if not dry_run:
            ledger.add(slug=slug, name=t.get("name") or slug,
                       hypothesis=t.get("hypothesis") or "", kind=kind,
                       prefixes=[], metric="organic_visitors",
                       source=f"scout:{ledger.today()}",
                       evidence=t.get("evidence") or "", status="candidate", notes=notes)
        added_t.append(slug)

    for k in (data.get("keywords") or [])[:MAX_KEYWORDS_PER_DAY]:
        q = (k.get("query") or "").strip().lower()
        city = k.get("city") if k.get("city") in keywords.CITIES else None
        if not q or not city:
            continue
        if not dry_run:
            if keywords.add(q, city, k.get("intent") or "list", source=f"scout:{ledger.today()}",
                            note=k.get("why", "")):
                added_k.append(q)
        else:
            added_k.append(q)

    out = {"ok": True, "techniques_added": added_t, "keywords_added": added_k,
           "notes": data.get("notes", "")}
    ledger.set_state("scout_last", {"date": ledger.today(), **out})
    _mirror({"ok": True, "techniques_added": len(added_t),
             "keywords_added": len(added_k)})
    print(f"  proposed {len(added_t)} technique(s), added {len(added_k)} keyword(s)")
    for s in added_t:
        print(f"    + {s}")
    return out
