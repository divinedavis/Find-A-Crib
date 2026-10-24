#!/usr/bin/env python3
"""Daily B2B prospect research and drafted outreach — drafts only, never sent.

The Developer API is already built and working (free / $49 Pro / $199 Business /
custom Enterprise, self-serve Stripe checkout). What it has never had is demand:
zero real signups. This module supplies the demand side.

Each day it researches a small number of genuinely plausible organisations that
need property-level rent-regulation data, and writes a short personalised draft
for each. It writes them to `growth/outreach_drafts/` and surfaces them in the
daily report for approval.

**It does not send.** That is a deliberate constraint, not an oversight:

  * findacrib.com's domain reputation is load-bearing — the saved-building alert
    emails are a product feature, and bulk cold mail from the same domain would
    put them in spam.
  * Cold email carries real legal obligations (CAN-SPAM, and GDPR for anyone in
    the EU). A human deciding to send is the control that keeps this compliant.
  * A wrong-but-confident cold email costs a prospect permanently. These are
    small, high-value markets.

Needs the same Anthropic key as the scout (keychain `rent-map-anthropic`,
env ANTHROPIC_API_KEY, or growth/.anthropic_key).
"""
import json
import os
import re

from . import ledger, scout

HERE = os.path.dirname(os.path.abspath(__file__))
DRAFTS_DIR = os.path.join(HERE, "outreach_drafts")
PROSPECTS_PATH = os.path.join(HERE, "prospects.json")

# Statuses that can only be true of a prospect whose email actually WENT OUT.
# "drafted" is the one status that is not: a reply, a win and a decline all
# presuppose a send, so any of these four is evidence the human step happened.
# This is the list mark() accepts, read as a claim about the world rather than
# as a workflow label.
SENT_STATUSES = ("sent", "replied", "won", "declined")

MAX_PER_DAY = 5

# Who actually needs property-level rent-regulation data. Rotated daily so the
# research does not keep circling one segment.
SEGMENTS = [
    # --- link-earning segments. These target domain authority rather than
    # revenue: search share is 0.0% and 89 of 47,600 pages get an impression,
    # and links from housing/civic/.gov/.edu sources are the strongest lever on
    # that. The pitch is a free tool or a free dataset, never a link request in
    # exchange for nothing.
    ("press", "Housing reporters, data desks and local-news outlets covering rent regulation, "
              "evictions or affordability in NYC, SF, LA or DC — people who would use a "
              "custom data cut for a story and credit the source"),
    ("tenant-orgs", "Tenant unions, housing legal-aid organisations, and city/state 'tenant "
                    "resources' pages that maintain link lists and would find a free "
                    "address-lookup widget genuinely useful to their readers"),
    ("proptech", "Proptech and rental-listing platforms serving NYC, SF, LA or DC that would "
                 "show renters whether a building is rent-regulated"),
    ("appraisal", "Real-estate appraisal and valuation firms — rent regulation materially "
                  "changes a building's value and they need it per-property"),
    ("legal", "Tenant-side law firms and housing legal-aid organisations handling overcharge, "
              "succession and deregulation cases"),
    ("brokerage", "Residential brokerages and property managers who need to know the "
                  "regulatory status of buildings in their portfolio"),
    ("research", "Housing policy researchers, universities, think tanks and journalists "
                 "covering rent regulation and affordability"),
    ("lending", "Multifamily lenders, underwriters and insurers pricing regulated buildings"),
    ("govtech", "Civic-tech organisations and city/state agencies working on housing data"),
]

SYSTEM = """You research B2B prospects for Find A Crib, which sells API and bulk access to \
property-level rent-regulation data for New York City, San Francisco, Los Angeles and \
Washington DC (47,000+ DHCR-registered rent-stabilized NYC buildings with HPD violation and \
complaint history, plus SF/LA/DC coverage).

Find REAL organisations that exist and would plausibly pay for this data. Rules:

- Only name organisations you actually found and can cite with a URL. Never invent a company, \
a person, or a contact address. If you are unsure a detail is real, leave the field empty.
- Prefer a public, business-appropriate contact route (a company contact page, a general \
info@/sales@ address, a public API/partnerships page). Do NOT guess personal email addresses \
and do not scrape or infer individuals' contact details.
- Skip anyone who obviously already has this data, and skip direct competitors.
- The draft email must be short (under 120 words), specific about why THIS organisation would \
care, honest about what the data is and its limits, and must not overstate coverage. It should \
read like one person writing to another, not like a template merge.
- Coverage caveats you must never contradict: NYC and DC are authoritative registries; the Los \
Angeles layer is derived from assessor criteria and is labelled "likely RSO", not an official \
list; San Francisco data is anonymized to the block, not the address.

Return ONLY valid JSON:
{
  "prospects": [
    {"org": "name", "url": "https://…", "segment": "…",
     "why": "why they specifically need this data",
     "contact_route": "how to reach them — a public page or general address you actually found",
     "draft_subject": "…", "draft_body": "…",
     "confidence": "high|medium|low"}
  ],
  "notes": "anything relevant, including organisations you considered and rejected and why"
}"""


def _load_prospects():
    try:
        with open(PROSPECTS_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_prospects(p):
    tmp = PROSPECTS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(p, f, indent=2)
        f.write("\n")
    os.replace(tmp, PROSPECTS_PATH)


def _slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-") or "x"


def todays_segment():
    """Rotate deterministically by day-of-year so segments get even coverage."""
    import datetime
    doy = datetime.date.today().timetuple().tm_yday
    return SEGMENTS[doy % len(SEGMENTS)]


def build_prompt():
    known = _load_prospects()
    seen = sorted({p["org"] for p in known})
    seg_key, seg_desc = todays_segment()
    return f"""Today is {ledger.today()}. Segment to research today: **{seg_key}** — {seg_desc}

Find up to {MAX_PER_DAY} organisations in this segment that would plausibly pay for
property-level rent-regulation data, and draft one short outreach email for each.

What we offer — pick the one that fits the segment:
- FREE, for press / tenant orgs / legal aid: an embeddable address-lookup widget at
  https://findacrib.com/embed/ (one line of HTML, no key, no tracking), and custom data cuts
  for a story on request. For these segments the ask is NOT a link in exchange for nothing —
  lead with the useful thing and let attribution follow. Never offer money for a link, and
  never ask anyone to edit Wikipedia on our behalf.
- PAID, for commercial segments: REST API at https://findacrib.com/api/v1 — free tier
  (1k req/day), Pro $49/mo (50k/day), Business $199/mo (500k/day), Enterprise custom (bulk
  CSV/Parquet delivery, redistribution rights, custom coverage and SLA).
- Coverage: NYC 47,165 DHCR-registered rent-stabilized buildings with owner, managing agent,
  and HPD violation/complaint history; plus San Francisco, Los Angeles and Washington DC.
- The differentiator: almost nobody publishes rent-regulation status at the property level.

Already contacted or already in our list — do NOT propose these again:
{chr(10).join('- ' + s for s in seen) if seen else '(none yet)'}

Search the web to find real organisations. Prefer specific, mid-sized, reachable ones over
household names that will never reply."""


def _mirror(record):
    """Copy the outreach job's outcome into last_run.json (tracked in git).

    Same reason as scout._mirror: outreach_last lives in the gitignored
    state.json, so the cloud review has no way to tell a job that had nothing to
    add from one that never ran. `ok` is explicit on every path here — the
    2026-07-28 lesson, when this function's success path omitted it and the daily
    email announced a healthy run as "DID NOT RUN — unknown error".

    NEVER put prospect names in this record. growth/prospects.json and
    growth/outreach_drafts/ are gitignored precisely because they name real
    organisations; last_run.json is committed, so this carries a count.
    """
    ledger.write_last_run("outreach", {"date": ledger.today(), **record})


def _sent_today():
    """How many drafts a human SENT today, or None if that cannot be read.

    None rather than 0 whenever prospects.json exists and cannot be parsed,
    because review._executions treats an absent reading as "we never measured
    whether it acted" and a 0 as "we measured, and it acted nothing" — opposite
    findings, and the second one is a claim this loop must be able to support.
    _load_prospects() swallows every error into [], which is the right default
    for the research path (a missing file genuinely means no prospects yet) and
    the wrong one here: a corrupt file would record a send count of zero that
    nothing established.

    Counts `sent_at`, which mark() stamps ONCE on the first transition out of
    "drafted" — not `status_at`, which moves again when the same prospect later
    replies or declines and would count one send on two different days.
    """
    if not os.path.exists(PROSPECTS_PATH):
        return 0                      # no file, no prospects, no sends
    try:
        with open(PROSPECTS_PATH) as f:
            known = json.load(f)
    except Exception:
        return None                   # there and unreadable: unknown, not zero
    if not isinstance(known, list):
        return None
    today = ledger.today()
    return sum(1 for p in known
               if isinstance(p, dict) and p.get("sent_at") == today)


def _record_sent(dry_run=False):
    """Write today's SEND count — T008's execution count — on every path.

    WHY THIS EXISTS AT ALL. T008 b2b_outreach declares mrr_usd, and mrr_usd is
    downstream of a step this module deliberately does not take: it drafts and
    never sends, because CAN-SPAM and GDPR need a human. So a flat mrr_usd said
    nothing about the idea, and the ledger carried that caveat by hand on
    2026-09-24 ("the verdict on it is measuring an outage rather than an idea").
    review.EXECUTION_SERIES now maps this slug onto this series, so the flat
    branch can say which disjunct is true instead of handing the reader both.

    RECORDED BEFORE THE API CALL, unlike lifecycle._record_sent and
    accounts._record_sent, and that difference is the point. Those two record
    from every path that LOOKED, where looking means querying the accounts
    table. Here the question — did a human send any of these drafts today — is
    answered from growth/prospects.json alone and needs no key, no credit and
    no model answer. Recording it first is what turns the API-capped nights
    (every night from 2026-09-08 to 2026-10-12) into readings of "it did not
    act" rather than holes indistinguishable from a job that never ran.

    Skipped when _sent_today() cannot read, and under --dry-run, which must
    write nothing. A skipped night reads as unrecorded, which is correct.
    """
    if dry_run:
        return None
    n = _sent_today()
    if n is None:
        return None
    ledger.record_result(ledger.today(), "b2b_outreach", "emails_sent", n)
    return n


def _record_drafted(n, dry_run=False):
    """Write how many drafts the research produced tonight, zero included.

    NOT T008's execution count, and kept separate from emails_sent on purpose.
    A draft is this module acting; a send is the TECHNIQUE acting, and the
    hypothesis ("personalised outreach converts far better than volume") is
    about the second. What this series is for is telling the two failures
    apart at the next revisit: nothing drafted because the API is capped, or
    drafted steadily and never sent because the human step never happened.
    Zeros are recorded for the reason in accounts._record_sent — a night that
    found nobody worth writing to and a night whose researcher is broken look
    identical otherwise.
    """
    if dry_run:
        return None
    ledger.record_result(ledger.today(), "b2b_outreach", "drafts_written", n)
    return n


def run(dry_run=False):
    # Before anything that can fail — see _record_sent on why this one does not
    # wait for the API to answer.
    _record_sent(dry_run)
    key = scout.load_key()
    if not key:
        msg = "no Anthropic key — outreach research skipped (same key as the scout)"
        print(f"  {msg}")
        ledger.set_state("outreach_last", {"date": ledger.today(), "ok": False, "detail": msg})
        _mirror({"ok": False, "detail": msg})
        return {"ok": False, "detail": msg}

    seg_key, _ = todays_segment()
    try:
        resp = scout.call_api(key, build_prompt())
        scout.record_spend("outreach", resp)
        data = scout.extract_json(resp)
    except Exception as e:
        print(f"  outreach research failed: {e}")
        ledger.set_state("outreach_last", {"date": ledger.today(), "ok": False, "detail": str(e)})
        _mirror({"ok": False, "detail": str(e)})
        return {"ok": False, "detail": str(e)}

    known = _load_prospects()
    seen = {p["org"].lower() for p in known}
    added = []

    os.makedirs(DRAFTS_DIR, exist_ok=True)
    for p in (data.get("prospects") or [])[:MAX_PER_DAY]:
        org = (p.get("org") or "").strip()
        if not org or org.lower() in seen:
            continue
        # A prospect with no source URL is unverifiable, so it is not a prospect.
        if not (p.get("url") or "").startswith("http"):
            continue
        rec = {
            "org": org, "url": p.get("url"), "segment": p.get("segment") or seg_key,
            "why": p.get("why", ""), "contact_route": p.get("contact_route", ""),
            "confidence": p.get("confidence", "medium"),
            "found": ledger.today(), "status": "drafted",
            "draft_subject": p.get("draft_subject", ""),
            "draft_body": p.get("draft_body", ""),
        }
        if not dry_run:
            known.append(rec)
            path = os.path.join(DRAFTS_DIR, f"{ledger.today()}-{_slug(org)}.md")
            with open(path, "w") as f:
                f.write(f"# {org}\n\n")
                f.write(f"- Source: {rec['url']}\n- Segment: {rec['segment']}\n")
                f.write(f"- Contact route: {rec['contact_route']}\n")
                f.write(f"- Confidence: {rec['confidence']}\n\n")
                f.write(f"**Why them:** {rec['why']}\n\n---\n\n")
                f.write(f"Subject: {rec['draft_subject']}\n\n{rec['draft_body']}\n")
        added.append(org)
        seen.add(org.lower())

    if not dry_run:
        _save_prospects(known)
        _record_drafted(len(added), dry_run)
        # "ok" must be explicit on the success path too. Both failure paths set
        # ok=False, and the report treats a missing key as failure — so omitting
        # it here made every successful outreach run show up in the daily email
        # as "DID NOT RUN — unknown error".
        ledger.set_state("outreach_last", {"date": ledger.today(), "ok": True,
                                           "segment": seg_key, "added": added,
                                           "notes": data.get("notes", "")})
        # Count, never names: `added` holds real third-party organisations and
        # last_run.json is committed to a public repo.
        _mirror({"ok": True, "segment": seg_key, "drafted": len(added)})
    print(f"  {seg_key}: drafted {len(added)} prospect(s) — review in growth/outreach_drafts/")
    for o in added:
        print(f"    + {o}")
    return {"ok": True, "segment": seg_key, "added": added, "notes": data.get("notes", "")}


def pending(limit=10):
    """Drafts awaiting a send decision, for the daily report."""
    return [p for p in _load_prospects() if p.get("status") == "drafted"][:limit]


def mark(org, status):
    """Record what happened: sent / replied / won / declined.

    Stamps `sent_at` the FIRST time a prospect reaches a status that implies
    the email went out, and never moves it again. That date is T008's whole
    execution record (see _record_sent): `status_at` cannot serve, because it
    is rewritten when the same prospect later replies or declines, which would
    count one send on two separate days and credit the technique with acting
    twice. Set here rather than inferred later because nothing else in this
    repo knows when a human pressed send.
    """
    known = _load_prospects()
    for p in known:
        if p["org"].lower() == org.lower():
            p["status"] = status
            p["status_at"] = ledger.today()
            if status in SENT_STATUSES and not p.get("sent_at"):
                p["sent_at"] = ledger.today()
            _save_prospects(known)
            return p
    return None
