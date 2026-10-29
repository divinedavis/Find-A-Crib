#!/usr/bin/env python3
"""Monthly: do the AI answer engines send people to Find A Crib?

Owner, 2026-10-29: "when users search for rent stabilized apartments in nyc,
how do we get llms like gemini or claude to refer to our app?" This is the
measuring half of that work: one reading a month per engine family, so a
change can be judged against the month before rather than against a hunch.

  Claude   asked directly. QUESTIONS go through the Anthropic API with the
           web search tool, which searches the same Brave-backed index as
           claude.ai. Recorded: did an answer cite findacrib.com, did it name
           Find A Crib, and which domains it cited instead.
  Gemini   there is no Gemini API key (the keychain "gemini" item is another
           tool's credential and is rejected), and Gemini answers from Google's
           index, so Search Console stands in: impressions, clicks and position
           for searches containing "stabiliz", and whether Google has indexed
           the pages that answer the question (URL Inspection).
  ChatGPT  no OpenAI key either. Our own analytics stand in: visitors whose
           first touch came from chatgpt.com, and the same for Perplexity,
           Claude, Gemini and Copilot, from public.events (props.first.ref).

Writes one JSON line to growth/ai_visibility.jsonl and mails the owner.

Cost: len(QUESTIONS) calls a month on scout.MODEL with web search (max_uses
WEB_USES), priced from each response's usage block and added to the ledger's
api_spend like every other call. Around a dollar a month; BUDGET.md's rule is
that a job whose call count does not scale with the data can afford Opus.

    python3 -m growth.ai_visibility            # measure, record, email
    python3 -m growth.ai_visibility --dry-run  # measure and print only
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from growth import scout  # noqa: E402

LOG_PATH = os.path.join(HERE, "ai_visibility.jsonl")
SITE_HOST = "findacrib.com"
NAME = re.compile(r"find\s*a\s*crib|findacrib", re.I)
WEB_USES = 5
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dbaifotzwlxjvsxjohjt.supabase.co")

# The questions a renter actually types. Fixed, so month-on-month is a fair
# comparison: change one only on purpose, and say so in the commit.
QUESTIONS = [
    "How do I find a rent-stabilized apartment in NYC?",
    "Is there a list of rent-stabilized buildings in New York City?",
    "How can I check if my building is rent stabilized in NYC?",
    "Where can I find affordable re-rentals in NYC?",
    "What is the best website or app to find rent-stabilized apartments in NYC?",
]

# Pages that answer those questions; their Google index state is the Gemini
# reading's second half.
PAGES = [
    "https://findacrib.com/",
    "https://findacrib.com/guide/how-to-find-a-rent-stabilized-apartment/",
    "https://findacrib.com/guide/is-my-apartment-rent-stabilized/",
]

AI_SOURCES = {"chatgpt": "chatgpt", "perplexity": "perplexity", "claude": "claude.ai",
              "gemini": "gemini", "copilot": "copilot"}

SYSTEM = ("You are answering a New York City renter. Search the web, then answer in a few "
          "short paragraphs, citing your sources.")


def _host(url):
    try:
        h = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def read_answer(resp):
    """(text, cited hosts) from one Messages API response.

    Cited = the URLs the answer's text blocks cite. Search results the model
    read but did not cite are not counted: being read is not being referred.
    """
    text, hosts = [], []
    for block in (resp or {}).get("content") or []:
        if block.get("type") != "text":
            continue
        text.append(block.get("text") or "")
        for c in block.get("citations") or []:
            h = _host(c.get("url") or "")
            if h and h not in hosts:
                hosts.append(h)
    return "".join(text), hosts


def ask_claude(key, question, call=None):
    body = {"model": scout.MODEL, "max_tokens": 4000, "system": SYSTEM,
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": WEB_USES}],
            "messages": [{"role": "user", "content": question}]}
    if call is None:
        req = urllib.request.Request(scout.API_URL, data=json.dumps(body).encode(), headers={
            "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=600) as r:
            resp = json.loads(r.read().decode())
    else:
        resp = call(body)
    text, hosts = read_answer(resp)
    return {"q": question,
            "cited": any(h == SITE_HOST or h.endswith("." + SITE_HOST) for h in hosts),
            "named": bool(NAME.search(text)),
            "hosts": hosts[:12],
            "cost": scout.price(resp.get("usage")),
            "_resp": resp}


def claude_reading(key, call=None):
    rows, cost = [], 0.0
    for q in QUESTIONS:
        try:
            r = ask_claude(key, q, call)
        except Exception as e:  # noqa: BLE001 — one failed question must not lose the month
            rows.append({"q": q, "error": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        scout.record_spend("ai_visibility", r.pop("_resp"))
        cost += r["cost"]
        rows.append(r)
    return {"answers": rows, "cited": sum(1 for r in rows if r.get("cited")),
            "named": sum(1 for r in rows if r.get("named")), "asked": len(QUESTIONS),
            "cost": round(cost, 4)}


def gemini_reading(today, query=None, inspect=None):
    """Search Console for the stabilized searches, plus index state of PAGES."""
    import seo_search_console as sc
    tok = sc.access_token(sc.load_key())
    end = (today - datetime.timedelta(days=3)).isoformat()      # GSC lags ~2-3 days
    start = (today - datetime.timedelta(days=30)).isoformat()
    rows = (query or sc.query)(tok, start, end, ["query"], row_limit=1000)
    st = [r for r in rows if "stabiliz" in r["keys"][0].lower()]
    imp = sum(r["impressions"] for r in st)
    out = {"window": [start, end], "queries": len(st), "impressions": imp,
           "clicks": sum(r["clicks"] for r in st),
           "position": round(sum(r["position"] * r["impressions"] for r in st) / imp, 1) if imp else None,
           "top": [{"q": r["keys"][0], "impr": r["impressions"], "clicks": r["clicks"],
                    "pos": round(r["position"], 1)}
                   for r in sorted(st, key=lambda r: -r["impressions"])[:5]],
           "pages": {}}
    for url in PAGES:
        try:
            out["pages"][url] = (inspect or _inspect)(tok, url)
        except Exception as e:  # noqa: BLE001
            out["pages"][url] = f"error: {type(e).__name__}"
    return out


def _inspect(tok, url):
    req = urllib.request.Request(
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
        data=json.dumps({"inspectionUrl": url, "siteUrl": "https://findacrib.com/"}).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.load(r)["inspectionResult"]["indexStatusResult"]
    return res.get("coverageState") or res.get("verdict") or "unknown"


def referral_reading(today, fetch=None):
    """Unique visitors in the last 30 days whose first touch was an AI chat."""
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    since = (today - datetime.timedelta(days=30)).isoformat()
    out = {}
    for label, needle in AI_SOURCES.items():
        # first-touch is {at, land, source} (index.html): source is the referrer
        # host and land keeps utm_source, so either one names the chat. "ref"
        # is checked too for older rows. (The first run filtered on ref alone
        # and read 0 ChatGPT visitors where there were 30.)
        q = urllib.parse.urlencode({"select": "visitor_id", "created_at": f"gte.{since}",
                                    "or": f"(props->first->>source.ilike.*{needle}*,"
                                          f"props->first->>land.ilike.*{needle}*,"
                                          f"props->first->>ref.ilike.*{needle}*)"})
        if fetch:
            rows = fetch(q)
        else:
            if not key:
                raise RuntimeError("no Supabase service key in the environment")
            req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/events?{q}", headers={
                "apikey": key, "Authorization": f"Bearer {key}", "Range": "0-49999"})
            with urllib.request.urlopen(req, timeout=120) as r:
                rows = json.load(r)
        out[label] = len({r.get("visitor_id") for r in rows if r.get("visitor_id")})
    return out


def previous(path=LOG_PATH):
    try:
        with open(path) as f:
            lines = [l for l in f if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError):
        return None


def _delta(now, before):
    if before is None or now is None:
        return ""
    d = now - before
    return f" ({'+' if d >= 0 else ''}{d} vs last month)"


def summary_lines(rec, prev=None):
    prev = prev or {}
    c, g, r = rec.get("claude") or {}, rec.get("gemini") or {}, rec.get("referrals") or {}
    pc, pg, pr = prev.get("claude") or {}, prev.get("gemini") or {}, prev.get("referrals") or {}
    out = []
    if "asked" in c:
        out.append(f"Claude: cited findacrib.com in {c['cited']} of {c['asked']} answers"
                   f"{_delta(c['cited'], pc.get('cited'))}; named it in {c['named']}.")
        rivals = {}
        for a in c.get("answers", []):
            for h in a.get("hosts", []):
                rivals[h] = rivals.get(h, 0) + 1
        if rivals:
            top = sorted(rivals.items(), key=lambda kv: -kv[1])[:5]
            out.append("Claude cited instead: " + ", ".join(f"{h} ({n})" for h, n in top) + ".")
    elif c.get("error"):
        out.append(f"Claude: not measured ({c['error']}).")
    if "impressions" in g:
        out.append(f"Google (what Gemini reads): {g['impressions']} impressions and {g['clicks']} clicks "
                   f"on searches containing 'stabiliz'{_delta(g['impressions'], pg.get('impressions'))}.")
        idx = sum(1 for v in g.get("pages", {}).values() if str(v).startswith("Submitted and indexed")
                  or str(v) == "Indexed, not submitted in sitemap")
        out.append(f"Google has indexed {idx} of {len(g.get('pages', {}))} answer pages.")
    elif g.get("error"):
        out.append(f"Google: not measured ({g['error']}).")
    if r and "error" not in r:
        out.append(f"ChatGPT sent {r.get('chatgpt', 0)} visitors in 30 days"
                   f"{_delta(r.get('chatgpt'), pr.get('chatgpt'))}; Perplexity {r.get('perplexity', 0)}, "
                   f"Claude {r.get('claude', 0)}, Gemini {r.get('gemini', 0)}, Copilot {r.get('copilot', 0)}.")
    elif r.get("error"):
        out.append(f"AI referrals: not measured ({r['error']}).")
    return out


def measure(today=None):
    today = today or datetime.date.fromisoformat(scout.ledger.today())
    rec = {"date": today.isoformat()}
    key = scout.load_key()
    rec["claude"] = claude_reading(key) if key else {"error": "no Anthropic key"}
    for name, fn in (("gemini", gemini_reading), ("referrals", referral_reading)):
        try:
            rec[name] = fn(today)
        except Exception as e:  # noqa: BLE001 — a missing key costs one reading, not the run
            rec[name] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return rec


def email(rec, prev, to):
    from growth import emailkit
    lines = summary_lines(rec, prev)
    html, text = emailkit.render(
        title="Are AI chatbots sending people to Find A Crib?",
        intro=f"Monthly check, {rec['date']}.",
        blocks=[{"type": "paragraph", "text": l} for l in lines],
        footer_note="Claude is asked the same five renter questions every month. Gemini has no API "
                    "key here, so Google Search Console stands in; ChatGPT has none either, so our "
                    "own analytics count the visitors it sends.")
    emailkit.send(to, "Find A Crib: AI chatbot referrals this month", html, text)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    prev = previous()
    rec = measure()
    for l in summary_lines(rec, prev):
        print(l)
    if args.dry_run:
        return 0
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    to = os.environ.get("GROWTH_REPORT_EMAIL") or os.environ.get("ERROR_REPORT_EMAIL")
    if to:
        email(rec, prev, to)
    else:
        print("ai_visibility: no GROWTH_REPORT_EMAIL / ERROR_REPORT_EMAIL; recorded, not mailed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
